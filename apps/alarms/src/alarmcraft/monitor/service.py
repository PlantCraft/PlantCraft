"""The monitor: every enabled alarm, judged once per cycle by its rule's diagram.

One background thread runs a cycle every ``ALARMCRAFT_CYCLE_SECONDS``: it keeps each rule's
alarms in step with the asset tree and the executions (``monitor.sync``, once a minute), reads
the events the apps published since the last cycle (``Incoming``), reads every value the rules
need in one batch from where the last cycle stopped, runs each alarm's diagram on its subject
(``engine.run``), records raises and clears (occurrences and journal), keeps the events with the
rules they counted for and publishes to PlantCraft. Plant data is read with Alarms' service
token; nothing runs without an app key. Publishing never blocks judging: a refused write is
logged and shown on the Status page.

A rule ``per`` rule over many assets makes one alarm, raised while any of its assets is (each
asset's memory is kept apart in the alarm's state). A shelved alarm is still judged but raises
nothing: no occurrence, no journal line, no event.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from plantcraft_sdk.client import PlantCraftError

from alarmcraft.alarms.blocks import EVENT_BLOCKS, nodes
from alarmcraft.alarms.incoming import IncomingStore
from alarmcraft.alarms.model import AlarmDraft, kind_matches
from alarmcraft.alarms.records import config_of, status_of
from alarmcraft.alarms.rules import RuleDraft, RuleStore
from alarmcraft.alarms.store import AlarmStore
from alarmcraft.engine import python as python_block
from alarmcraft.engine import run as engine
from alarmcraft.engine import scope
from alarmcraft.i18n import t
from alarmcraft.monitor import publish, suggest
from alarmcraft.monitor.incoming import Incoming, owner_of
from alarmcraft.monitor.notifier import Notifier
from alarmcraft.monitor.reader import ApiReader
from alarmcraft.monitor.sync import RuleSync, draft_of, subject_of

LOGGER = logging.getLogger(__name__)
TICK_SECONDS = 1.0
# The first cycle (and one after a long stop) reads at most this far back.
FIRST_WINDOW = timedelta(minutes=10)
MAX_BACKFILL = timedelta(hours=1)
APP_LOOKBACK = timedelta(hours=6)
RESULTS_EVERY = timedelta(minutes=5)
SYNC_EVERY = timedelta(minutes=1)
# The suite's catalog is read this often for the suggested rules marked enabled.
SUGGEST_EVERY = timedelta(minutes=10)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def judge(
    draft: RuleDraft,
    subject: engine.Subject,
    state: dict[str, Any],
    *,
    series: dict[str, Any],
    events: list[dict[str, Any]],
    end: datetime,
    open_now: list[dict[str, Any]] | None = None,
    members: list[engine.Subject] | None = None,
    python: Callable | None = python_block.run,
) -> engine.Outcome:
    """One alarm's next state: its rule's diagram on its subject, or, for one alarm over many
    assets (``members``), on each of them, raised while any is."""

    if not members:
        return engine.run(
            draft.diagram,
            subject,
            state,
            series=series,
            events=events,
            end=end,
            open_now=open_now,
            python=python,
        )
    state = dict(state or {})
    before = bool(state.get("active"))
    kept = dict(state.get("members") or {})
    outcome = engine.Outcome(state)
    raised: list[datetime] = []
    cleared: list[datetime] = []
    active: list[str] = []
    unknown = []
    for member in members:
        found = engine.run(
            draft.diagram,
            member,
            kept.get(member.key) or {"evaluated_until": state.get("evaluated_until")},
            series=series,
            events=events,
            end=end,
            open_now=open_now,
            python=python,
        )
        kept[member.key] = found.state
        outcome.counted |= found.counted
        if found.unknown:
            unknown.append(found.unknown)
        if found.state.get("active"):
            active.append(member.label or member.key)
            if outcome.value is None:
                outcome.value, outcome.unit, outcome.signal = found.value, found.unit, found.signal
        raised += [moment for kind, moment in found.transitions if kind == "raised"]
        cleared += [moment for kind, moment in found.transitions if kind == "cleared"]
    state["members"] = kept
    state["active"] = bool(active)
    state["evaluated_until"] = end.isoformat()
    state["members_active"] = active[:50]
    if active and not before:
        outcome.transitions = [("raised", min(raised) if raised else end)]
    elif before and not active:
        outcome.transitions = [("cleared", max(cleared) if cleared else end)]
    if active:
        outcome.message = t("Active on {assets}", assets=", ".join(active[:5]))
    if len(unknown) == len(members):
        outcome.unknown = unknown[0]
    return outcome


class Monitor:
    def __init__(
        self,
        alarms: AlarmStore,
        client: Any | None,
        *,
        root_path: str = "/alarm",
        clock: Callable[[], datetime] = utcnow,
        cycle_seconds: float = 10.0,
        data_lag_seconds: float = 5.0,
        asset_cache: dict | None = None,
        notifier: Notifier | None = None,
        rules: RuleStore | None = None,
        incoming: IncomingStore | None = None,
        sync: RuleSync | None = None,
    ):
        self.alarms = alarms
        self.rules = rules
        self.sync = sync
        self.incoming = (
            Incoming(rules, incoming, client, clock=clock)
            if rules is not None and incoming is not None
            else None
        )
        self._synced: datetime | None = None
        self._suggested: datetime | None = None
        self.client = client
        self.root_path = root_path
        self.clock = clock
        self.cycle_seconds = cycle_seconds
        self.data_lag_seconds = data_lag_seconds
        self.asset_cache: dict = {} if asset_cache is None else asset_cache
        self.notifier = notifier
        self.lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error = ""
        self.publish_error = ""
        self.cycles = 0
        self.last_cycle: datetime | None = None
        self._published: tuple[Any, datetime] | None = None
        self._day: dict[str, Any] = {}

    # Background loop -----------------------------------------------------------------

    def start(self) -> None:
        if self.client is None or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="alarmcraft-monitor", daemon=True)
        self._thread.start()
        self.publish_schedules()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _loop(self) -> None:
        while not self._stop.wait(TICK_SECONDS):
            try:
                last = self.last_cycle
                if last is None or (self.clock() - last).total_seconds() >= self.cycle_seconds:
                    self.run_cycle()
            except Exception as exc:  # noqa: BLE001 - the loop never dies
                LOGGER.exception("Alarm cycle failed")
                self.last_error = str(exc)[:300]

    # One cycle -----------------------------------------------------------------------

    @property
    def url(self) -> str:
        return f"{self.root_path}/alarms"

    def _rules(self) -> dict[str, tuple[dict[str, Any], RuleDraft]]:
        found = {}
        for rule in self.rules.list() if self.rules is not None else []:
            draft = draft_of(rule)
            if draft is not None and draft.enabled:
                found[rule["rule_id"]] = (rule, draft)
        return found

    def _anywhere(
        self,
        rules: dict[str, tuple[dict[str, Any], RuleDraft]],
        events: list[dict[str, Any]],
        assets: dict[str, dict],
    ) -> None:
        """Make the alarm of each asset a rule ``anywhere`` hears about for the first time."""

        if self.sync is None:
            return
        for rule, draft in rules.values():
            if not draft.where.anywhere:
                continue
            kinds = [
                kind
                for node in nodes(draft.diagram, EVENT_BLOCKS)
                for kind in (node.get("parameters") or {}).get("kinds") or []
            ]
            for event in events:
                if not kind_matches(kinds, str(event.get("kind") or "")):
                    continue
                if str(event.get("phase") or "") == "end":
                    continue
                for asset_id in scope.event_assets(event, assets):
                    subject = scope.asset_subject(assets, asset_id, single=False)
                    self.sync.alarm_for(rule, draft, subject, owner_of(event))

    def run_cycle(self) -> dict[str, Any]:
        """Judge every enabled alarm now; record and publish what changed."""

        with self.lock:
            now = self.clock()
            self.last_cycle = now
            end = now - timedelta(seconds=self.data_lag_seconds)
            counts = {"evaluated": 0, "raised": 0, "cleared": 0, "unknown": 0}
            if self.client is None:
                self.last_error = t("Alarms has no app key to read the plant.")
                return counts
            if self.sync is not None and (self._synced is None or now - self._synced >= SYNC_EVERY):
                self.sync.sync_all()
                self._synced = now
            if self.rules is not None and (
                self._suggested is None or now - self._suggested >= SUGGEST_EVERY
            ):
                self._suggested = now
                self._suggest()
            events = self.incoming.read() if self.incoming is not None else []
            open_now = self.incoming.store.open_conditions() if self.incoming is not None else []
            rules = self._rules()
            assets = self.sync.tree.assets() if self.sync is not None else {}
            if events:
                self._anywhere(rules, events, assets)
            schedules = self.sync.schedules() if self.sync is not None else []
            stored = [
                alarm
                for alarm in self.alarms.list()
                if alarm.get("enabled", True) and alarm.get("rule_enabled", True)
            ]
            plans: dict[str, tuple[AlarmDraft | None, RuleDraft | None, Any, list, str]] = {}
            wanted: set[str] = set()
            for alarm in stored:
                alarm_id = alarm["alarm_id"]
                try:
                    draft = AlarmDraft.model_validate(config_of(alarm))
                except ValueError as exc:
                    why = t("Its configuration is not valid: {why}", why=exc)
                    plans[alarm_id] = (None, None, None, [], why)
                    continue
                rule = rules.get(draft.rule_id)
                if rule is None:
                    plans[alarm_id] = (draft, None, None, [], t("Its rule is off or not valid."))
                    continue
                subject = subject_of(alarm, assets)
                members: list[engine.Subject] = []
                if rule[1].where.per == "rule" and not rule[1].where.empty:
                    members = scope.subjects(rule[1], assets, schedules)
                why = ""
                for one in members or [subject]:
                    signals, problem = engine.signals_of(rule[1].diagram, one)
                    wanted |= signals
                    why = why or problem
                plans[alarm_id] = (draft, rule[1], subject, members, why)
            start = self._read_start(stored, end)
            reader = ApiReader(self.client, cache=self.asset_cache)
            columns, errors = self._read(reader, wanted, start, end)
            entries = []
            noted: list[tuple[dict[str, Any], str, datetime, Any, str]] = []
            counted: dict[int, list[str]] = {}
            for alarm in stored:
                alarm_id = alarm["alarm_id"]
                draft, rule, subject, members, why = plans[alarm_id]
                if draft is None or rule is None:
                    counts["unknown"] += 1
                    state = {**(alarm.get("state") or {}), "known": False, "reason": why}
                    self.alarms.set_state(alarm_id, state)
                    continue
                state = dict(alarm.get("state") or {})
                if not state.get("evaluated_until"):
                    # A new alarm judges the plant from now on, not the minutes before it existed.
                    fresh_start = end - timedelta(seconds=max(2 * self.cycle_seconds, 30.0))
                    state["evaluated_until"] = max(start, fresh_start).isoformat()
                elif state["evaluated_until"] < start.isoformat():
                    state["evaluated_until"] = start.isoformat()
                outcome = judge(
                    rule,
                    subject,
                    state,
                    series=columns,
                    events=events,
                    end=end,
                    open_now=open_now,
                    members=members,
                )
                state = outcome.state
                for event_id in outcome.counted:
                    counted.setdefault(event_id, []).append(draft.rule_id)
                failure = outcome.unknown or why or (errors.get(outcome.signal or "") or "")
                known = not failure
                state.update(
                    known=known,
                    reason=failure,
                    value=outcome.value,
                    value_at=end.isoformat()
                    if outcome.value is not None
                    else state.get("value_at"),
                    unit=outcome.unit,
                    signal=outcome.signal,
                    message=outcome.message,
                )
                state.update({key: value for key, value in outcome.heard.items() if value})
                named = outcome.heard.get("responsible")
                if named and named != draft.owner and self.sync is not None and subject is not None:
                    # The app named who answers (Link: the execution's owner).
                    self.sync.alarm_for(rules[draft.rule_id][0], rule, subject, named)
                if subject is not None and subject.kind == "execution":
                    state["schedule_id"] = subject.id
                counts["evaluated" if known else "unknown"] += 1
                shelved = status_of(alarm, now) == "shelved"
                raised = False
                for kind, at in outcome.transitions:
                    if shelved:
                        continue
                    if kind == "raised":
                        state["raised_at"] = at.isoformat()
                        state["occurrence"] = self.alarms.open_occurrence(
                            {**config_of(alarm), "alarm_id": alarm_id},
                            at.isoformat(),
                            outcome.value,
                        )
                        state["peak"] = outcome.value
                        raised = True
                        counts["raised"] += 1
                    else:
                        if state.get("occurrence"):
                            self.alarms.close_occurrence(
                                int(state["occurrence"]), at.isoformat(), state.get("peak")
                            )
                        state["occurrence"] = None
                        counts["cleared"] += 1
                    detail = publish.describe(draft, outcome.value, outcome.unit, outcome.message)
                    self.alarms.log(
                        {**alarm, "priority": draft.priority},
                        kind,
                        at=at.isoformat(),
                        value=outcome.value,
                        detail=detail,
                    )
                    self._post_event(alarm_id, draft, outcome, kind, at)
                    if self.notifier is not None:
                        noted.append(
                            (
                                {**alarm, **draft.config(), "state": state},
                                kind,
                                at,
                                outcome.value,
                                publish.reading(draft, outcome.value, outcome.unit),
                            )
                        )
                if state.get("active") and state.get("occurrence"):
                    peak = state.get("peak")
                    if outcome.value is not None and (peak is None or outcome.value > peak):
                        state["peak"] = outcome.value
                    self.alarms.set_peak(int(state["occurrence"]), state.get("peak"))
                # A notice needs no acknowledgement.
                raised = raised and draft.creates == "alarm"
                self.alarms.set_state(alarm_id, state, raised=raised)
                fresh = {**alarm, "state": state, "acked": False if raised else alarm.get("acked")}
                entries.append(self._entry(fresh, draft, state, now, known=known))
            if self.incoming is not None:
                self.incoming.keep(events, counted, now)
            self.cycles += 1
            self.last_error = ""
            self._notify(noted, now)
            self._publish_results(entries, now)
            self._publish_run(counts, now)
            return counts

    @staticmethod
    def _read(
        reader: ApiReader, wanted: set[str], start: datetime, end: datetime
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Every value the rules need. An app's series (``app-<app>:``, a point per run, written
        when the run ends) is read further back, so a point stamped before the last cycle
        still counts."""

        columns: dict[str, Any] = {}
        errors: dict[str, str] = {}
        plant = sorted(item for item in wanted if not item.startswith("app-"))
        apps = sorted(item for item in wanted if item.startswith("app-"))
        for signals, since in ((plant, start), (apps, start - APP_LOOKBACK)):
            if signals:
                found, failed = reader.read(signals, since, end, None)
                columns.update(found)
                errors.update(failed)
        return columns, errors

    def _read_start(self, stored: list[dict[str, Any]], end: datetime) -> datetime:
        floor = end - MAX_BACKFILL
        marks = []
        for alarm in stored:
            mark = (alarm.get("state") or {}).get("evaluated_until")
            try:
                marks.append(datetime.fromisoformat(mark) if mark else end - FIRST_WINDOW)
            except ValueError:
                marks.append(end - FIRST_WINDOW)
        return max(floor, min(marks)) if marks else end - FIRST_WINDOW

    @staticmethod
    def _entry(
        alarm: dict[str, Any],
        draft: AlarmDraft,
        state: dict[str, Any],
        now: datetime,
        *,
        known: bool,
    ) -> dict[str, Any]:
        return {
            "alarm_id": alarm["alarm_id"],
            "alarm": draft,
            "signal": state.get("signal"),
            "status": status_of({**alarm, "state": state}, now),
            "value": state.get("value"),
            "unit": state.get("unit") or "",
            "known": known,
        }

    def _notify(self, noted: list[tuple], now: datetime) -> None:
        """Queue this cycle's raises and clears, the reminders due, and send what is ready."""

        if self.notifier is None:
            return
        try:
            for alarm, kind, at, value, detail in noted:
                self.notifier.record(alarm, kind, at, value, detail, now=now)
            self.notifier.remind(now)
            self.notifier.flush(now)
        except Exception as exc:  # noqa: BLE001 - telling people never stops the alarms
            LOGGER.exception("Alarm notifications failed")
            self.notifier.last_error = str(exc)[:300]

    def _suggest(self) -> None:
        """Create the suggested rules the apps mark enabled (once each; ``monitor.suggest``)."""

        try:
            catalog = suggest.catalog_of(self.client)
            taken = {alarm["alarm_id"] for alarm in self.alarms.list()}
            for rule in suggest.apply_enabled(self.rules, catalog, taken=taken):
                LOGGER.info("Suggested rule %s created", rule["rule_id"])
                if self.sync is not None:
                    self.sync.sync(rule, by=suggest.SYSTEM_USER)
        except (PlantCraftError, ValueError, TypeError, KeyError) as exc:
            LOGGER.warning("Suggested rules not read: %s", exc)

    # Publishing ----------------------------------------------------------------------

    def _post_event(
        self, alarm_id: str, draft: AlarmDraft, outcome: engine.Outcome, kind: str, at: datetime
    ) -> None:
        body = publish.event(alarm_id, draft, outcome.signal, kind, at, outcome.value, outcome.unit)
        if body is None:
            return
        try:
            self.client.post_event(
                body["kind"],
                body["subject"],
                summary=body["summary"],
                refs=body["refs"],
                payload=body["payload"],
                severity=body["severity"],
                key=body["key"],
                phase=body["phase"],
            )
        except (PlantCraftError, ValueError, TypeError) as exc:
            self.publish_error = t("events: {why}", why=exc)[:500]
            LOGGER.warning("Alarm event not published: %s", exc)

    def _publish_results(self, entries: list[dict[str, Any]], now: datetime) -> None:
        rows = publish.results(entries, now=now, url=self.url)
        fingerprint = [(row["subject"], row["status"], row["summary"]) for row in rows]
        if self._published is not None:
            last, at = self._published
            if last == fingerprint and now - at < RESULTS_EVERY:
                return
        try:
            if rows:
                self.client.put_results(rows)
            self._published = (fingerprint, now)
            self.publish_error = ""
        except (PlantCraftError, ValueError) as exc:
            self.publish_error = t("results: {why}", why=exc)[:500]
            LOGGER.warning("Alarm results not published: %s", exc)

    def _publish_run(self, counts: dict[str, int], now: datetime) -> None:
        day = now.strftime("%Y-%m-%d")
        if self._day.get("day") != day:
            self._day = {"day": day, "cycles": 0, "raised": 0, "published": None}
        self._day["cycles"] += 1
        self._day["raised"] += counts["raised"]
        last = self._day.get("published")
        if last is not None and not counts["raised"] and now - last < RESULTS_EVERY:
            return
        try:
            self.client.put_runs(
                [
                    {
                        "id": f"alarms-{now.strftime('%Y%m%d')}",
                        "name": t("Alarm monitoring {day}", day=day),
                        "status": "running",
                        "trigger": "schedule",
                        "started_at": now.replace(
                            hour=0, minute=0, second=0, microsecond=0
                        ).isoformat(),
                        "subjects": [],
                        "summary": t(
                            "{cycles} cycles, {raised} alarms raised today.",
                            cycles=self._day["cycles"],
                            raised=self._day["raised"],
                        ),
                        "url": self.url,
                    }
                ]
            )
            self._day["published"] = now
        except (PlantCraftError, ValueError) as exc:
            self.publish_error = t("runs: {why}", why=exc)[:500]

    def publish_schedules(self) -> None:
        """Tell PlantCraft the evaluation cycle (its Executions page lists it)."""

        if self.client is None:
            return
        enabled = [alarm for alarm in self.alarms.list() if alarm.get("enabled", True)]
        try:
            self.client.put_schedules(
                [
                    {
                        "id": "alarm-monitor",
                        "name": t("Alarm evaluation ({count} alarms)", count=len(enabled)),
                        "cadence": t("every {seconds} s", seconds=f"{self.cycle_seconds:g}"),
                        "next_run": (
                            self.clock() + timedelta(seconds=self.cycle_seconds)
                        ).isoformat(),
                        "enabled": True,
                        "url": self.url,
                    }
                ]
            )
        except PlantCraftError as exc:
            self.publish_error = t("schedules: {why}", why=exc)
            LOGGER.warning("Schedules not published: %s", exc)


def wait_until(predicate: Callable[[], bool], seconds: float) -> bool:
    """Poll ``predicate`` up to ``seconds`` (tests of the background loop)."""

    limit = time.monotonic() + seconds
    while time.monotonic() < limit:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()
