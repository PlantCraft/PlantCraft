"""History replay: LinkCraft fills its past from the plant data the historian already holds.

A new installation (or a algorithm scheduled today) shows one round and empty run lists, although
the historian may already hold days of the plant's data. ``HistoryReplay`` runs, over that
archive:

- the **monitoring round** at past moments (every ``step_minutes``): only the loops' health
  history is written, so the latest results, open findings and messages stay the live round's.
  Each replayed round is reported to PlantCraft as a finished run at its moment;
- each **algorithm schedule**'s past occurrences, as completed runs stamped at their slot; their
  outputs (results, series, messages) are not published, those are for the present.

Moments already in the history are skipped, so running it again only fills the gaps. The
Signal quality algorithm's verdicts are not replayed: the loops' built-in data gate decides.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
from plantcraft_sdk.refs import asset_ref

from linkcraft.db import recorded_at
from linkcraft.engine.jobs import PRIORITIES
from linkcraft.engine.suite_compute import priority
from linkcraft.engine.zones import zone_of
from linkcraft.i18n import t
from linkcraft.loops.analysis import analyze_loop_task
from linkcraft.loops.monitor import APPLICATION_ID, READ_BATCH, SUBJECT_KIND, MonitorService

LOGGER = logging.getLogger(__name__)
MAX_HOURS = 24 * 31
# The monitoring round's schedule (``Runtime``): its replay is the rounds' history.
ROUND_SCHEDULE = f"round-{APPLICATION_ID}"
# Past occurrences replayed per schedule, at most (a 5-minute interval over a month is 8,928).
MAX_SLOTS = 400
# How long a replayed run is said to have taken (its rows are stamped at slot + this).
RUN_SECONDS = 20


def _aware(moment: pd.Timestamp) -> datetime:
    return moment.tz_localize(UTC).to_pydatetime() if moment.tzinfo is None else moment


def _stored(moment: datetime) -> str:
    """A moment as the health history stores it: naive UTC, like ``str(raw.index.max())``."""

    return str(pd.Timestamp(moment).tz_convert(None))


def past_slots(schedule: dict[str, Any], start: datetime, end: datetime) -> list[datetime]:
    """The occurrences of a recurring schedule in ``(start, end]`` (aware UTC datetimes)."""

    cadence = schedule.get("cadence")
    zone = zone_of(schedule.get("timezone"))
    slots: list[datetime] = []
    if cadence in {"hourly", "interval"}:
        minutes = float(schedule.get("interval_minutes") or 60) if cadence == "interval" else 60
        step = max(60.0, minutes * 60)
        first = (int(start.timestamp() // step) + 1) * step
        moment = first
        while moment <= end.timestamp():
            slots.append(datetime.fromtimestamp(moment, UTC))
            moment += step
    elif cadence in {"daily", "weekly"}:
        hour, _, minute = str(schedule.get("time_local") or "00:00").partition(":")
        day = start.astimezone(zone).date()
        while day <= end.astimezone(zone).date():
            if cadence == "daily" or day.weekday() == int(schedule.get("weekday") or 0):
                local = datetime(
                    day.year, day.month, day.day, int(hour), int(minute or 0), tzinfo=zone
                )
                moment = local.astimezone(UTC)
                if start < moment <= end:
                    slots.append(moment)
            day += timedelta(days=1)
    return slots[-MAX_SLOTS:]


class HistoryReplay:
    """One replay at a time, in a background thread; ``status`` says how far it got."""

    def __init__(
        self,
        monitor: MonitorService,
        *,
        resolve_selector: Callable[[dict[str, Any]], list[str]],
        publish_run: Callable[[dict[str, Any]], Any],
    ):
        self.monitor = monitor
        self.jobs = monitor.jobs
        self.latest = monitor.latest
        self.resolve_selector = resolve_selector
        self.publish_run = publish_run
        self._lock = threading.Lock()
        self.state: dict[str, Any] = {"running": False}

    @property
    def running(self) -> bool:
        return self._lock.locked()

    def start(self, hours: float, step_minutes: float = 60.0) -> bool:
        if not self._lock.acquire(blocking=False):
            return False
        self._reset(hours, step_minutes)

        def work() -> None:
            try:
                # Last in the compute workers' queue: the live rounds go first (D7).
                with priority("backfill"):
                    self.replay(hours, step_minutes)
            except Exception as exc:  # the state says why; the live work goes on
                LOGGER.exception("History replay failed")
                self.state["error"] = f"{type(exc).__name__}: {exc}"
            finally:
                self.state["running"] = False
                self.state["finished_at"] = datetime.now(UTC).isoformat(timespec="seconds")
                self._lock.release()

        threading.Thread(target=work, name="linkcraft-replay", daemon=True).start()
        return True

    def _reset(self, hours: float, step_minutes: float) -> None:
        self.state = {
            "running": True,
            "hours": hours,
            "step_minutes": step_minutes,
            "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "rounds": 0,
            "runs": 0,
            "skipped": 0,
        }

    def replay(
        self, hours: float, step_minutes: float = 60.0, schedule_id: str | None = None
    ) -> dict[str, Any]:
        """Replay the rounds, then the schedules, over the last ``hours`` of data; only one
        schedule's occurrences (or only the rounds, for the round's schedule) with
        ``schedule_id``."""

        direct = not self.running  # called directly (tests, the CLI), not through ``start``
        if direct:
            self._reset(hours, step_minutes)
        loops = self.monitor.loops
        if loops:
            hours = min(max(float(hours), 1.0), MAX_HOURS)
            end = _aware(self.monitor.round_end(loops))
            begin = end - timedelta(hours=hours)
            if schedule_id in (None, ROUND_SCHEDULE):
                self.replay_rounds(loops, begin, end, step_minutes)
            if schedule_id != ROUND_SCHEDULE:
                self.replay_schedules(begin, end, schedule_id)
        if direct:
            self.state["running"] = False
        return self.state

    # The monitoring round -------------------------------------------------------------

    def replay_rounds(
        self, loops: list[Any], begin: datetime, end: datetime, step_minutes: float
    ) -> None:
        window = timedelta(minutes=self.monitor.analysis.window_minutes)
        step = timedelta(minutes=max(5.0, float(step_minutes)))
        seen = [
            _aware(pd.Timestamp(value))
            for value in self.latest.history_ends(
                APPLICATION_ID, SUBJECT_KIND, _stored(begin - step), _stored(end)
            )
        ]
        slots = []
        moment = datetime.fromtimestamp(
            (int((begin + window).timestamp() // step.total_seconds()) + 1) * step.total_seconds(),
            UTC,
        )
        # The present is the live round's: stop one step before the newest data.
        while moment <= end - step:
            if any(abs(moment - other) < step / 2 for other in seen):
                self.state["skipped"] += 1
            else:
                slots.append(moment)
            moment += step
        self.state["total_rounds"] = len(slots)
        for moment in slots:
            self._round_at(loops, moment - window, moment)
            self.state["rounds"] += 1

    def _round_at(self, loops: list[Any], start: datetime, end: datetime) -> None:
        began = time.monotonic()
        cache: dict[Any, Any] = {}
        futures: dict[Future, Any] = {}
        for offset in range(0, len(loops), READ_BATCH):
            batch = loops[offset : offset + READ_BATCH]
            try:
                raw = self.monitor._read(self.monitor.plant, batch, start, end)
            except Exception as exc:  # a gap in the archive: that batch has no point here
                LOGGER.info("Replay: no data for %d loops at %s: %s", len(batch), end, exc)
                continue
            for loop in batch:
                config = self.monitor._round_config(loop, cache)
                task = self.monitor._task(
                    loop,
                    raw,
                    parameter_overrides=config.get("overrides"),
                    parameter_defaults=config.get("defaults"),
                    diagram=config.get("diagram"),
                    algorithm_id=config.get("profile_id"),
                    compute=config.get("compute"),
                )
                futures[self.monitor.compute.submit(analyze_loop_task, task)] = loop
        rows, counts, payloads = [], {}, {}
        for future, error in self.monitor.compute.as_completed(futures):
            if error is not None:
                continue
            loop = futures[future]
            summary = future.result()["summary"]
            status = summary.get("status")
            if status in {"no_data", "incomplete"}:
                continue
            counts[status] = counts.get(status, 0) + 1
            payloads[loop.loop_id] = {"summary": summary, "config": {"name": loop.name}}
            rows.append(
                {
                    "subject_id": loop.loop_id,
                    "source_end": _stored(end),
                    "status": status,
                    "health": summary.get("health"),
                }
            )
        if not rows:
            return
        self.latest.add_history(APPLICATION_ID, SUBJECT_KIND, rows)
        origins = self.monitor.loop_store.origins()
        publisher = self.monitor.publisher
        if publisher is not None:  # the health trend other apps read (DashCraft's cards)
            assets = [loop_id for loop_id in payloads if origins.get(loop_id) == "processcraft"]
            try:
                publisher._series(payloads, assets, end)
            except Exception:  # the history is kept; the trend is a report
                LOGGER.warning("Replayed health series at %s not sent", end, exc_info=True)
        took = max(1, round(time.monotonic() - began))
        self.publish_run(
            {
                "id": f"round-{end.strftime('%Y%m%dT%H%M%S')}Z-replay",
                "name": t("Control loop performance"),
                "status": "done",
                "trigger": "schedule",
                "started_at": end.isoformat(timespec="seconds"),
                "finished_at": (end + timedelta(seconds=took)).isoformat(timespec="seconds"),
                "subjects": [
                    asset_ref(row["subject_id"])
                    for row in rows
                    if origins.get(row["subject_id"]) == "processcraft"
                ],
                "summary": t(
                    "{count} loops analysed: {counts}. Replayed over the archive.",
                    count=len(rows),
                    counts=", ".join(f"{key} {value}" for key, value in sorted(counts.items())),
                ),
            }
        )

    # Algorithm schedules ---------------------------------------------------------------

    def replay_schedules(
        self, begin: datetime, end: datetime, schedule_id: str | None = None
    ) -> None:
        planned = []
        for schedule in self.jobs.list_schedules(enabled_only=True):
            if schedule.get("kind") == "round" or schedule.get("subject_kind") != SUBJECT_KIND:
                continue
            if schedule_id and schedule["schedule_id"] != schedule_id:
                continue
            lookback = timedelta(minutes=float(schedule.get("lookback_minutes") or 60))
            subjects = (
                self.resolve_selector(schedule["selector"])
                if schedule.get("selector") is not None
                else [schedule["loop_id"]]
            )
            for slot in past_slots(schedule, begin + lookback, end):
                planned += [(schedule, slot, lookback, subject) for subject in subjects]
        self.state["total_runs"] = len(planned)
        for schedule, slot, lookback, subject in planned:
            if self._job_at(schedule, slot, lookback, subject):
                self.state["runs"] += 1
            else:
                self.state["skipped"] += 1

    def _job_at(
        self, schedule: dict[str, Any], slot: datetime, lookback: timedelta, subject: str
    ) -> bool:
        local = slot.astimezone(zone_of(schedule.get("timezone")))
        with recorded_at(local):
            try:
                job_id = self.jobs.create_job(
                    loop_id=subject,
                    name=schedule["name"],
                    kind="scheduled",
                    scheduled_for=local.isoformat(timespec="seconds"),
                    range_start=(slot - lookback).isoformat(timespec="seconds"),
                    range_end=slot.isoformat(timespec="seconds"),
                    lookback_minutes=schedule.get("lookback_minutes"),
                    profile_id=schedule.get("profile_id"),
                    method_config=schedule.get("method_config"),
                    schedule_id=schedule["schedule_id"],
                    created_by="System",
                    application_id=schedule.get("application_id") or APPLICATION_ID,
                    subject_kind=SUBJECT_KIND,
                    # Run here, now: never one for the queue's workers (they would publish it).
                    status="running",
                    priority=PRIORITIES["replay"],
                )
            except sqlite3.IntegrityError:  # this occurrence already ran
                return False
        with recorded_at(local + timedelta(seconds=RUN_SECONDS)):
            job = self.monitor.execute_job(job_id, publish=False, claimed=True)
        return job.get("status") == "completed"
