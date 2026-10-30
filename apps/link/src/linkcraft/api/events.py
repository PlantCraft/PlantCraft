"""What Link tells the Alarms app about its schedules (only
changes since Alarms round 11, 2026-10-26).

Link does not decide who is notified: it publishes events and the Alarms app turns them into
alarms by its rules. Link publishes when something changes, never to repeat that it is still
the same: what each execution computed (a loop's health, an algorithm's outputs) is written as
series (``loops/suite.py``), and an Alarms rule reads those ("health under 50 for 5 runs").
Every event carries the schedule (``schedule_id``, ``schedule_name``), the algorithm and the
version that ran, the schedule's ``owner`` (``user:<name>`` or ``group:<id>``), a ``severity``
and the page that shows it (``url``):

- ``linkcraft.status.changed``: a subject's state in a schedule changed (``previous_status``);
  a condition keyed ``<schedule id>:<subject>``, phase ``start`` for warning or critical and
  ``end`` (severity ``ok``) when it is back to ok, which clears the alarm;
- ``linkcraft.run.failed``: a scheduled run failed, once per run of the schedule however many
  of its subjects failed (``failed`` counts them, the first one is the subject);
- ``linkcraft.schedule.stalled``: a schedule has not run for two of its periods: one condition
  per schedule (subject ``app:linkcraft``, key ``stalled:<schedule id>``), ``end`` when it ran.

Each kind is declared in ``app.toml`` (``[[publishes.events]]``).

The PlantCraft events API names assets and signals only, so the events of a schedule name each
of its subjects. Signal quality publishes its own (``signals.publish``) and is left out here.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from plantcraft_sdk.refs import RefError, asset_ref, run_ref

from linkcraft import APP_ID
from linkcraft.api.subjects import kind_of, subject_rows, subjects_of
from linkcraft.catalog.loop_types import algorithm_id as current_id
from linkcraft.db import Store
from linkcraft.i18n import t
from linkcraft.loops.suite import DEFAULT_ALGORITHM

LOGGER = logging.getLogger(__name__)

STATUS_CHANGED = f"{APP_ID}.status.changed"
RUN_FAILED = f"{APP_ID}.run.failed"
SCHEDULE_STALLED = f"{APP_ID}.schedule.stalled"
# A subject's state -> the event's severity (the Alarms app clears on ``ok``).
SEVERITY = {"ok": "ok", "warning": "warning", "alarm": "critical"}
# How long a schedule may go without running, in its periods, before it is stalled.
STALLED_PERIODS = 2
STALL_GRACE = timedelta(minutes=5)
PERIOD_MINUTES = {"daily": 1440, "weekly": 10080}


class EventStateStore(Store):
    """Each subject's last state Link published per schedule, and the schedules said stalled."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS schedule_subject_states (
        schedule_id TEXT NOT NULL,
        subject TEXT NOT NULL,
        state TEXT NOT NULL,
        at TEXT NOT NULL,
        PRIMARY KEY (schedule_id, subject)
    );

    CREATE TABLE IF NOT EXISTS schedule_stalls (
        schedule_id TEXT PRIMARY KEY,
        since TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS schedule_failures (
        schedule_id TEXT NOT NULL,
        run_at TEXT NOT NULL,
        failed INTEGER NOT NULL,
        PRIMARY KEY (schedule_id, run_at)
    );
    """

    def states(self, schedule_id: str) -> dict[str, str]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT subject, state FROM schedule_subject_states WHERE schedule_id = ?",
                (schedule_id,),
            ).fetchall()
        return {row["subject"]: row["state"] for row in rows}

    def save_state(self, schedule_id: str, subject: str, state: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO schedule_subject_states VALUES (?, ?, ?, ?)",
                (schedule_id, subject, state, self._now()),
            )

    def stalled(self) -> set[str]:
        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT schedule_id FROM schedule_stalls").fetchall()
        return {row["schedule_id"] for row in rows}

    def set_stalled(self, schedule_id: str, stalled: bool) -> None:
        with self._lock, self._connect() as connection:
            if stalled:
                connection.execute(
                    "INSERT OR IGNORE INTO schedule_stalls VALUES (?, ?)",
                    (schedule_id, self._now()),
                )
            else:
                connection.execute(
                    "DELETE FROM schedule_stalls WHERE schedule_id = ?", (schedule_id,)
                )

    def note_failure(self, schedule_id: str, run_at: str) -> int:
        """Count a failed subject of one run of a schedule; answers how many failed so far
        (1: the first, the one that is told)."""

        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO schedule_failures VALUES (?, ?, 1)"
                " ON CONFLICT(schedule_id, run_at) DO UPDATE SET failed = failed + 1",
                (schedule_id, run_at),
            )
            row = connection.execute(
                "SELECT failed FROM schedule_failures WHERE schedule_id = ? AND run_at = ?",
                (schedule_id, run_at),
            ).fetchone()
            # A week of runs is enough to know a run was already told.
            connection.execute(
                "DELETE FROM schedule_failures WHERE run_at < ?",
                ((datetime.now(UTC) - timedelta(days=7)).isoformat(),),
            )
        return int(row["failed"])

    def forget(self, schedule_ids: set[str]) -> None:
        """Drop what Link kept about schedules that no longer exist."""

        with self._lock, self._connect() as connection:
            for table in ("schedule_subject_states", "schedule_stalls", "schedule_failures"):
                rows = connection.execute(f"SELECT DISTINCT schedule_id FROM {table}")  # noqa: S608
                gone = [
                    row["schedule_id"] for row in rows if row["schedule_id"] not in schedule_ids
                ]
                connection.executemany(
                    f"DELETE FROM {table} WHERE schedule_id = ?",  # noqa: S608
                    [(item,) for item in gone],
                )


def owner_ref(value: str | None) -> str:
    """A schedule's owner as the Alarms app addresses it (older schedules kept a bare name)."""

    value = (value or "").strip()
    if not value or value.startswith(("user:", "group:")):
        return value
    return f"user:{value}"


def _subject(subject: str, kind: str) -> str | None:
    if kind == "signal":
        return None
    try:
        return asset_ref(subject)
    except RefError:
        return None


class ScheduleEvents:
    """Publishes D6's events after each execution and when a schedule stalls."""

    def __init__(self, runtime: Any, db: Any):
        self.rt = runtime
        self.store = EventStateStore(db)

    # After an execution ----------------------------------------------------------------

    def after(self, job_id: str) -> int:
        """The events one ended execution gives; the number PlantCraft took."""

        job = self.rt.jobs.get_job(job_id)
        if not job or not job.get("schedule_id") or job["status"] not in {"completed", "failed"}:
            return 0
        schedule = self.rt.jobs.get_schedule(job["schedule_id"])
        if schedule is None or kind_of(schedule) == "signal" or job.get("work") == "replay":
            return 0
        only = None if job.get("work") == "round" else [job["loop_id"]]
        if job["status"] == "failed":
            return self._failed(schedule, job, only)
        return self._statuses(schedule, job, subject_rows(self.rt, schedule, only))

    def _failed(self, schedule: dict[str, Any], job: dict[str, Any], only: Any) -> int:
        """One event per run of the schedule that failed: the first failed subject tells it."""

        subjects = only or subjects_of(self.rt, schedule)
        run_at = str(job.get("scheduled_for") or job.get("requested_at") or "")[:16]
        if not subjects or self.store.note_failure(schedule["schedule_id"], run_at) > 1:
            return 0
        event = self._event(
            RUN_FAILED,
            schedule,
            subjects[0],
            job,
            severity="warning",
            summary=t(
                "{schedule} did not run: {why}",
                schedule=schedule["name"],
                why=job.get("error_message") or t("the run failed"),
            ),
        )
        if event is not None:
            event["payload"]["run_at"] = run_at
        return self._send([event])

    def _statuses(
        self, schedule: dict[str, Any], job: dict[str, Any], rows: list[dict[str, Any]]
    ) -> int:
        known = self.store.states(schedule["schedule_id"])
        kind = kind_of(schedule)
        loops = (
            {
                loop.loop_id: current_id(loop.profile_id or DEFAULT_ALGORITHM)
                for loop in self.rt.loops.list_loops()
            }
            if kind == "loop"
            else {}
        )
        pending: list[tuple[dict[str, Any], Any]] = []
        for row in rows:
            state = row["state"]
            if state not in SEVERITY:
                continue  # not judged this time: nothing changed
            algorithm = loops.get(row["id"]) if kind == "loop" else None
            before = known.get(row["id"])
            if before == state or (before is None and state == "ok"):
                if before is None:
                    pending.append((None, (schedule["schedule_id"], row["id"], state)))
                continue
            pending.append(
                (
                    self._event(
                        STATUS_CHANGED,
                        schedule,
                        row["id"],
                        job,
                        severity=SEVERITY[state],
                        phase="end" if state == "ok" else "start",
                        status=state,
                        previous_status=before,
                        algorithm=algorithm,
                        summary=t(
                            "{subject} is {status} in {schedule}",
                            subject=row["name"],
                            status=row["status_label"],
                            schedule=schedule["name"],
                        ),
                    ),
                    (schedule["schedule_id"], row["id"], state),
                )
            )
        events = [event for event, _ in pending if event is not None]
        taken = iter(self._post(events))
        sent = 0
        for event, record in pending:
            ok = next(taken) if event is not None else True
            sent += int(bool(ok and event is not None))
            if ok and record is not None:
                self.store.save_state(*record)
        return sent

    # A schedule that stopped -------------------------------------------------------------

    def check_stalled(self, now: datetime | None = None) -> int:
        """Say once that a schedule has not run for two of its periods; forget it once it runs."""

        now = now or datetime.now(UTC)
        schedules = self.rt.jobs.list_schedules()
        self.store.forget({item["schedule_id"] for item in schedules})
        said = self.store.stalled()
        pending = []
        for schedule in schedules:
            schedule_id = schedule["schedule_id"]
            late = self._late(schedule, now)
            if not late:
                if schedule_id in said:
                    summary = t("{schedule} runs again", schedule=schedule["name"])
                    self._post([self._stall(schedule, "end", summary)])
                    self.store.set_stalled(schedule_id, False)
                continue
            if schedule_id in said or kind_of(schedule) == "signal":
                continue
            summary = t(
                "{schedule} has not run since {when}",
                schedule=schedule["name"],
                when=schedule.get("last_run_at") or t("it was made"),
            )
            pending.append((schedule_id, [self._stall(schedule, "start", summary)]))
        sent = 0
        for schedule_id, events in pending:
            taken = self._post(events)
            sent += sum(taken)
            if events and all(taken):
                self.store.set_stalled(schedule_id, True)
        return sent

    @staticmethod
    def _late(schedule: dict[str, Any], now: datetime) -> bool:
        if not schedule.get("enabled"):
            return False
        cadence = schedule.get("cadence") or "interval"
        period = (
            schedule.get("interval_minutes")
            if cadence == "interval"
            else PERIOD_MINUTES.get(cadence)
        )
        since = schedule.get("last_run_at") or schedule.get("created_at")
        if not period or not since:
            return False
        last = datetime.fromisoformat(str(since).replace("Z", "+00:00"))
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        return now - last > timedelta(minutes=float(period) * STALLED_PERIODS) + STALL_GRACE

    def _stall(self, schedule: dict[str, Any], phase: str, summary: str) -> dict[str, Any]:
        """The schedule's one stall condition, about Link itself (a schedule is no subject of
        PlantCraft's events) with the schedule in its payload."""

        event = self._event(
            SCHEDULE_STALLED,
            schedule,
            "",
            None,
            severity="ok" if phase == "end" else "warning",
            summary=summary,
        )
        event = event or {}
        event.update(
            subject=f"app:{APP_ID}",
            refs=[],
            phase=phase,
            key=f"stalled:{schedule['schedule_id']}"[:200],
        )
        event["payload"]["subjects"] = len(subjects_of(self.rt, schedule))
        event["payload"]["url"] = event["payload"]["url"].rsplit("/", 1)[0]
        return event

    # The events ----------------------------------------------------------------------------

    def _event(
        self,
        kind: str,
        schedule: dict[str, Any],
        subject: str,
        job: dict[str, Any] | None,
        *,
        severity: str,
        summary: str,
        phase: str | None = None,
        status: str | None = None,
        previous_status: str | None = None,
        algorithm: str | None = None,
    ) -> dict[str, Any] | None:
        ref = _subject(subject, kind_of(schedule)) if subject else f"app:{APP_ID}"
        if ref is None:
            return None
        algorithm_id = algorithm or str(
            schedule.get("profile_id") or (job or {}).get("profile_id") or ""
        )
        version = ((job or {}).get("summary") or {}).get("algorithm_version")
        if version is None and algorithm_id:
            version = (self.rt.presets.get_profile(algorithm_id) or {}).get("version")
        root = (
            getattr(self.rt.monitor.publisher, "root", "/link")
            if self.rt.monitor.publisher
            else "/link"
        )
        payload: dict[str, Any] = {
            "schedule_id": schedule["schedule_id"],
            "schedule_name": schedule["name"],
            "algorithm_id": algorithm_id,
            "algorithm_version": version,
            "owner": owner_ref(schedule.get("owner") or schedule.get("created_by")),
            "severity": severity,
            "url": f"{root}/executions/{quote(schedule['schedule_id'], safe='')}/{quote(subject, safe='')}",
        }
        for key, item in (
            ("status", status),
            ("previous_status", previous_status),
        ):
            if item is not None:
                payload[key] = item
        refs = [ref]
        if job:
            try:
                refs.append(run_ref(APP_ID, job["job_id"]))
            except RefError:
                pass
        event = {
            "kind": kind,
            "subject": ref,
            "summary": summary[:500],
            "refs": refs,
            "payload": payload,
            "severity": severity,
        }
        if phase is not None:
            # One condition per schedule and subject: its start and end share the key.
            event.update(phase=phase, key=f"{schedule['schedule_id']}:{subject}"[:200])
        return event

    def _post(self, events: list[dict[str, Any] | None]) -> list[bool]:
        real = [event for event in events if event is not None]
        if not real or not self.rt.suite.available("events"):
            return [False] * len(events) if real else [event is None for event in events]
        taken = iter(self.rt.suite.post_events(real))
        return [next(taken) if event is not None else True for event in events]

    def _send(self, events: list[dict[str, Any] | None]) -> int:
        return sum(1 for event, ok in zip(events, self._post(events)) if ok and event is not None)


__all__ = [
    "RUN_FAILED",
    "SCHEDULE_STALLED",
    "STATUS_CHANGED",
    "ScheduleEvents",
    "owner_ref",
]
