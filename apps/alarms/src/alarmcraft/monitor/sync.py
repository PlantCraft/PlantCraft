"""Rules into alarms: each rule's alarms kept in step with the rule, the asset tree and the
suite's executions.

A rule has one alarm per subject (``engine.scope.subjects``): saving the rule writes them, and
each minute adds the alarm of an asset that came under the rule (a new asset in its branch, of
its type, in its execution) and removes the alarm of one that left it. A rule ``anywhere`` makes
the alarm of an asset when the first event about it counts (``alarm_for``). A change of the
rule's logic (its diagram) ends the alarm's open occurrence and starts it over; a change of
words (name, rationalization, priority, who) keeps its state. The person's own part of an alarm
(acknowledged, shelved, out of service) is never touched here.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from alarmcraft.alarms.model import OWNER
from alarmcraft.alarms.records import config_of
from alarmcraft.alarms.rules import RuleDraft, RuleStore, alarm_config, alarm_id_for
from alarmcraft.alarms.store import AlarmStore
from alarmcraft.engine import scope
from alarmcraft.engine.run import Subject
from alarmcraft.i18n import t
from alarmcraft.monitor.reader import AssetTree

LOGGER = logging.getLogger(__name__)
# A change in any of these is a new condition: the alarm's open occurrence ends.
CONDITION = ("subject", "logic")


def draft_of(rule: dict[str, Any]) -> RuleDraft | None:
    try:
        return RuleDraft.model_validate(
            {key: value for key, value in rule.items() if key in RuleDraft.model_fields}
        )
    except ValueError:
        return None


def subject_of(alarm: dict[str, Any], assets: dict[str, dict]) -> Subject:
    """The subject an alarm is about, from what its rule wrote (``alarm_config``)."""

    key = str(alarm.get("subject") or "")
    if key.startswith("execution:"):
        app, _, schedule = key.removeprefix("execution:").partition(":")
        return Subject(key, "execution", schedule, None, alarm.get("label"), app)
    if not key:
        return Subject("", "none")
    return Subject(key, "asset", key, assets.get(key), alarm.get("label"))


class RuleSync:
    def __init__(
        self,
        rules: RuleStore,
        alarms: AlarmStore,
        tree: AssetTree,
        clock: Callable[[], datetime],
        schedules: Callable[[], list[dict[str, Any]]] | None = None,
    ):
        self.rules = rules
        self.alarms = alarms
        self.tree = tree
        self.clock = clock
        self.schedules = schedules or (lambda: [])

    def end_occurrence(self, alarm: dict[str, Any], why: str, by: str = "") -> None:
        state = alarm.get("state") or {}
        if state.get("active") and state.get("occurrence"):
            now = self.clock().isoformat()
            self.alarms.close_occurrence(int(state["occurrence"]), now, None)
            self.alarms.log(alarm, "cleared", at=now, by=by, detail=why)

    def _write(
        self, alarm_id: str, config: dict[str, Any], current: dict[str, Any] | None, by: str
    ) -> dict[str, Any]:
        if current is None:
            alarm = self.alarms.put(alarm_id, config, by=by or "alarms")
            self.alarms.log(alarm, "created", at=self.clock().isoformat(), by=by)
            return alarm
        before = config_of(current)
        config = {**config, "enabled": before.get("enabled", True)}
        if before == config:
            return current
        reset = any(before.get(key) != config.get(key) for key in CONDITION) or (
            before.get("rule_enabled", True) and not config.get("rule_enabled", True)
        )
        if reset:
            self.end_occurrence(current, t("Rule changed"), by)
        return self.alarms.update(alarm_id, config, by=by or "alarms", reset_state=reset) or current

    def sync(self, rule: dict[str, Any], *, by: str = "") -> list[dict[str, Any]]:
        """Write the rule's alarms; the rule's alarms afterwards."""

        draft = draft_of(rule)
        rule_id = rule["rule_id"]
        existing = {alarm["alarm_id"]: alarm for alarm in self.alarms.of_rule(rule_id)}
        if draft is None:
            for alarm in existing.values():
                self.drop(alarm, t("The rule is not valid"), by)
            return []
        assets = self.tree.assets()
        if draft.where.anywhere:
            for alarm_id, alarm in existing.items():
                subject = subject_of(alarm, assets)
                config = alarm_config(
                    rule_id,
                    draft,
                    subject=subject.key,
                    asset_id=subject.asset_id,
                    label=_label(subject, assets),
                    owner=_responsible(alarm) or draft.owner,
                )
                self._write(alarm_id, config, alarm, by)
            return self.alarms.of_rule(rule_id)
        if not assets and (draft.where.under or draft.where.types):
            # PlantCraft did not answer: keep the branch's alarms rather than drop them.
            return list(existing.values())
        wanted: set[str] = set()
        found = scope.subjects(draft, assets, self.schedules())
        for subject in found:
            alarm_id = alarm_id_for(rule_id, subject.key, single=draft.single)
            wanted.add(alarm_id)
            current = existing.get(alarm_id)
            config = alarm_config(
                rule_id,
                draft,
                subject=subject.key,
                asset_id=subject.asset_id,
                label=subject.label,
                owner=(current and _responsible(current)) or draft.owner,
            )
            self._write(alarm_id, config, current, by)
        for alarm_id, alarm in existing.items():
            if alarm_id not in wanted:
                self.drop(alarm, t("No longer under the rule"), by)
        return self.alarms.of_rule(rule_id)

    def sync_all(self) -> None:
        rules = self.rules.list()
        known = {rule["rule_id"] for rule in rules}
        for rule in rules:
            try:
                self.sync(rule)
            except Exception:  # noqa: BLE001 - one rule never stops the others
                LOGGER.exception("Rule %s not synced", rule.get("rule_id"))
        for alarm in self.alarms.list():
            if alarm.get("rule_id") not in known:
                self.drop(alarm, t("Rule deleted"), "")

    def drop(self, alarm: dict[str, Any], why: str, by: str) -> None:
        self.end_occurrence(alarm, why, by)
        self.alarms.delete(alarm["alarm_id"])
        self.alarms.log(alarm, "deleted", at=self.clock().isoformat(), by=by, detail=why)

    def remove(self, rule_id: str, *, by: str) -> None:
        for alarm in self.alarms.of_rule(rule_id):
            self.drop(alarm, t("Rule deleted"), by)

    def alarm_for(
        self, rule: dict[str, Any], draft: RuleDraft, subject: Subject, owner: str | None = None
    ) -> dict[str, Any]:
        """The rule's alarm on this subject (a rule ``anywhere``: made when the first event
        about it counts); its responsible follows the owner the app names in its events."""

        alarm_id = alarm_id_for(rule["rule_id"], subject.key, single=draft.single)
        current = self.alarms.get(alarm_id)
        responsible = owner if owner and OWNER.match(owner) else None
        config = alarm_config(
            rule["rule_id"],
            draft,
            subject=subject.key,
            asset_id=subject.asset_id,
            label=subject.label,
            owner=responsible or (current and _responsible(current)) or draft.owner,
        )
        return self._write(alarm_id, config, current, "")


def _responsible(alarm: dict[str, Any]) -> str | None:
    found = (alarm.get("state") or {}).get("responsible")
    return str(found) if found and OWNER.match(str(found)) else None


def _label(subject: Subject, assets: dict[str, dict]) -> str | None:
    if subject.kind == "asset":
        return str((assets.get(subject.id) or {}).get("name") or subject.id)
    return subject.label
