"""History replay: each alarm's past judged over the archive the historian already holds.

An alarm created today has an empty journal and no performance figures, although the plant's
data of the last days is there. ``HistoryReplay`` judges each enabled alarm over the hours
before it was created with the same judge as the editor's Test (``monitor.service.judge``) and keeps
what it finds as occurrences and journal lines at their own moments. With ``acknowledged_by``
each past occurrence is also acknowledged by that person a short while after it was raised, as
an operator on shift would have. Nothing is replayed for an alarm that already has occurrences
before it was created, so running it again changes nothing. Events are not sent to PlantCraft:
those are news, not history.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from alarmcraft.alarms.model import AlarmDraft
from alarmcraft.alarms.records import config_of
from alarmcraft.engine import run as engine
from alarmcraft.engine import scope
from alarmcraft.monitor import publish
from alarmcraft.monitor.reader import ApiReader
from alarmcraft.monitor.service import Monitor, judge
from alarmcraft.monitor.sync import subject_of

LOGGER = logging.getLogger(__name__)
MAX_HOURS = 24 * 7
STEP_SECONDS = 60.0
BATCH = 20
# An acknowledgement comes 20 seconds to 7 minutes after the raise (the same for the same moment).
ACK_SECONDS = (20, 420)


def ack_delay(alarm_id: str, started: str) -> timedelta:
    digest = hashlib.sha256(f"{alarm_id}|{started}".encode()).digest()
    low, high = ACK_SECONDS
    return timedelta(seconds=low + int.from_bytes(digest[:4], "big") % (high - low))


class HistoryReplay:
    """One replay at a time over every enabled alarm, in a background thread."""

    def __init__(self, monitor: Monitor):
        self.monitor = monitor
        self._lock = threading.Lock()
        self.state: dict[str, Any] = {"running": False}

    def start(self, hours: float, acknowledged_by: str = "") -> bool:
        if not self._lock.acquire(blocking=False):
            return False
        self.state = {"running": True, "hours": hours, "alarms": {}}

        def work() -> None:
            try:
                self.run(hours, acknowledged_by)
            except Exception as exc:  # the state says why; the live cycles go on
                LOGGER.exception("Alarm history replay failed")
                self.state["error"] = f"{type(exc).__name__}: {exc}"
            finally:
                self.state["running"] = False
                self._lock.release()

        threading.Thread(target=work, name="alarmcraft-replay", daemon=True).start()
        return True

    def run(self, hours: float, acknowledged_by: str = "") -> dict[str, Any]:
        """Replay every enabled alarm (in the calling thread); the occurrences written per alarm."""

        monitor = self.monitor
        self.state.setdefault("alarms", {})
        if monitor.client is None or monitor.sync is None:
            return {}
        reader = ApiReader(monitor.client, cache=monitor.asset_cache)
        span = timedelta(hours=min(max(float(hours), 1.0), MAX_HOURS))
        latest = monitor.clock() - timedelta(seconds=monitor.data_lag_seconds)
        rules = monitor._rules()
        assets = monitor.sync.tree.assets()
        schedules = monitor.sync.schedules()
        planned = []
        for alarm in monitor.alarms.list():
            if not alarm.get("enabled", True) or alarm.get("rule_enabled") is False:
                continue
            try:
                draft = AlarmDraft.model_validate(config_of(alarm))
            except ValueError as exc:
                self.state["alarms"][alarm["alarm_id"]] = {"occurrences": 0, "problem": str(exc)}
                continue
            found = rules.get(draft.rule_id)
            if found is None:
                continue
            rule = found[1]
            # Up to its creation: from then on the live monitor judges it.
            end = min(datetime.fromisoformat(alarm["created_at"]), latest)
            if monitor.alarms.occurrences(
                end=(end - timedelta(seconds=1)).isoformat(), alarm_id=alarm["alarm_id"], limit=1
            ):
                self.state["alarms"][alarm["alarm_id"]] = {"occurrences": 0, "skipped": True}
                continue
            subject = subject_of(alarm, assets)
            members = (
                scope.subjects(rule, assets, schedules)
                if rule.where.per == "rule" and not rule.where.empty
                else []
            )
            signals: set[str] = set()
            for one in members or [subject]:
                signals |= engine.signals_of(rule.diagram, one)[0]
            planned.append((alarm, draft, rule, subject, members, signals, end))
        events = []
        if monitor.incoming is not None and planned:
            start = min(item[-1] for item in planned) - span
            events = monitor.incoming.store.since(start.isoformat())
        for index in range(0, len(planned), BATCH):
            group = planned[index : index + BATCH]
            start = min(item[-1] for item in group) - span
            stop = max(item[-1] for item in group)
            wanted = sorted(set().union(*(item[5] for item in group)))
            columns, _errors = (
                reader.read(wanted, start, stop, STEP_SECONDS) if wanted else ({}, {})
            )
            for alarm, draft, rule, subject, members, _signals, end in group:
                window = [item for item in events if end - span <= _at(item) <= end]
                outcome = judge(
                    rule,
                    subject,
                    {"evaluated_until": (end - span).isoformat()},
                    series=columns,
                    events=window,
                    end=end,
                    members=members,
                    python=None,
                )
                written = self.replay_one(alarm, draft, outcome, end, acknowledged_by)
                self.state["alarms"][alarm["alarm_id"]] = {"occurrences": written}
        return self.state["alarms"]

    def replay_one(
        self,
        alarm: dict[str, Any],
        draft: AlarmDraft,
        outcome: Any,
        end: datetime,
        acknowledged_by: str,
    ) -> int:
        store = self.monitor.alarms
        row = {**config_of(alarm), "alarm_id": alarm["alarm_id"], "priority": draft.priority}
        found = engine.occurrences(outcome.transitions, end)
        detail = publish.describe(draft, None)
        for item in found:
            began = item["start"]
            ended = item["end"] or end.isoformat()  # the live monitor judges from its creation on
            occurrence = store.open_occurrence(row, began, None)
            store.close_occurrence(occurrence, ended, None)
            store.log(row, "raised", at=began, value=None, detail=detail)
            store.log(row, "cleared", at=ended, value=None, detail=detail)
            if acknowledged_by:
                acked = min(
                    datetime.fromisoformat(began) + ack_delay(alarm["alarm_id"], began), end
                ).isoformat()
                store.acknowledge_occurrence(occurrence, by=acknowledged_by, at=acked)
                store.log(row, "acknowledged", at=acked, by=acknowledged_by)
        return len(found)


def _at(event: dict[str, Any]) -> datetime:
    moment = datetime.fromisoformat(str(event.get("at")))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
