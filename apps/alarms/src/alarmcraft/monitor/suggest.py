"""Rules from the suite's catalog: each event an app declares may carry the rule its app suggests
(``[[publishes.events]]`` ``rule``). A person starts a rule from it in the editor; a suggestion
marked ``enabled`` (only a ``system`` event may ask for it) is created once, by itself, so a new
installation hears that a part of the suite stopped without writing a rule first. One deleted
stays deleted.
"""

from __future__ import annotations

import logging
from typing import Any

from alarmcraft import APP_ID
from alarmcraft.alarms.blocks import EVENT_BLOCKS
from alarmcraft.alarms.model import kind_matches
from alarmcraft.alarms.rules import RuleDraft, RuleStore

LOGGER = logging.getLogger(__name__)
SUGGESTED = "suggested:"
SYSTEM_USER = "system"


def catalog_of(client: Any) -> list[dict[str, Any]]:
    """The catalog by app, Alarms' own events left out (Alarms does not judge itself)."""

    found = []
    for app in client.event_catalog() or []:
        if app.get("app") == APP_ID:
            continue
        events = [dict(item) for item in app.get("events") or [] if item.get("kind")]
        found.append({**app, "events": events})
    return found


def counting_rules(rules: list[dict[str, Any]], kind: str) -> list[dict[str, str]]:
    """The rules whose event blocks hear ``kind``."""

    found = []
    for rule in rules:
        for node in (rule.get("diagram") or {}).get("nodes") or []:
            if node.get("block") not in EVENT_BLOCKS:
                continue
            if kind_matches(list((node.get("parameters") or {}).get("kinds") or []), kind):
                found.append(
                    {"rule_id": rule["rule_id"], "name": rule.get("name") or rule["rule_id"]}
                )
                break
    return found


def suggested_rule(event: dict[str, Any]) -> dict[str, Any]:
    """A Simple rule (the editor's body) from a declared event and the rule its app suggests
    (``when``: event, repeated so many times in ``minutes``, or still open after ``minutes``)."""

    rule = event.get("rule") or {}
    when = rule.get("when") or "event"
    minutes = int(rule.get("minutes") or 0)
    condition: dict[str, Any] = {"input": "event", "event": {"kinds": [event["kind"]]}}
    if when == "repeated":
        condition.update(
            test="count", count=int(rule.get("count") or 1), window_minutes=max(minutes, 1)
        )
    elif when == "open":
        condition.update(test="open", for_seconds=float(minutes * 60))
    else:
        condition.update(test="count", count=1, window_minutes=60)
    system = event.get("category") == "system"
    draft: dict[str, Any] = {
        "name": str(event.get("title") or event["kind"])[:120],
        "enabled": True,
        "creates": rule.get("creates") or ("alarm" if rule else "notice"),
        "priority": rule.get("priority") or "medium",
        # A system event is about a part of the suite, not an asset: one alarm for the rule.
        "where": {} if system else {"anywhere": True},
        "editor": "simple",
        "simple": {"conditions": [condition]},
        "cause": str(event.get("description") or "")[:2000],
    }
    if system:
        condition["event"]["about"] = "any"
        # Who hears a system event: the rule's owner (the administrator creating it).
        draft["notify"] = {"recipients": ["owner"]}
    return draft


def apply_enabled(
    rules: RuleStore, catalog: list[dict[str, Any]], *, taken: set[str]
) -> list[dict[str, Any]]:
    """Create, once each, the suggested rules their apps mark ``enabled``; answers those made."""

    made = []
    for app in catalog:
        for event in app["events"]:
            rule = event.get("rule") or {}
            mark = SUGGESTED + event["kind"]
            if not rule.get("enabled") or rules.meta(mark) is not None:
                continue
            try:
                draft = RuleDraft.model_validate(
                    {**suggested_rule(event), "owner": None, "notify": {"recipients": ["owner"]}}
                )
            except ValueError:
                LOGGER.warning("Suggested rule of %s not valid; skipped", event["kind"])
                rules.set_meta(mark, "invalid")
                continue
            made.append(rules.create(draft.config(), by=SYSTEM_USER, taken=taken))
            rules.set_meta(mark, made[-1]["rule_id"])
    return made
