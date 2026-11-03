"""Recurring schedules and the executions their occurrences queue."""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from plantcraft_sdk.utc import utc_iso

from linkcraft.engine.jobs.common import (
    DEFAULT_RETRY,
    OPEN_STATUSES,
    PRIORITIES,
    RENAMED_ROUNDS,
    SCHEDULE_CADENCES,
    output_key_of,
)
from linkcraft.engine.recurrence import Recurrence, next_after
from linkcraft.engine.zones import zone_of
from linkcraft.i18n import t


class ScheduleRecords:
    """The schedules: create, update, list, and materialize their occurrences."""

    @staticmethod
    def _next_occurrence(
        *,
        cadence: str,
        timezone: str,
        time_local: str | None,
        weekday: int | None,
        scheduled_for: str | None,
        interval_minutes: float | None = None,
        now: datetime | None = None,
        recurrence: dict[str, Any] | None = None,
    ) -> str | None:
        zone = zone_of(timezone)
        current = (now or datetime.now(zone)).astimezone(zone)
        if cadence == "calendar":
            if not recurrence:
                raise ValueError(t("Choose when it runs."))
            found = next_after(Recurrence.model_validate(recurrence), timezone, current)
            return utc_iso(found) if found else None
        if cadence == "interval":
            # The first run is right away; the following ones every N minutes.
            return utc_iso(current.replace(microsecond=0))
        if cadence == "once":
            if not scheduled_for:
                return None
            stamp = datetime.fromisoformat(scheduled_for)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=zone)
            return utc_iso(stamp)

        hour, minute = (int(part) for part in (time_local or "08:00").split(":"))
        candidate = current.replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )
        if cadence == "hourly":
            candidate = current.replace(
                minute=minute,
                second=0,
                microsecond=0,
            )
            if candidate <= current:
                candidate += timedelta(hours=1)
            return utc_iso(candidate)
        if cadence == "daily":
            if candidate <= current:
                candidate += timedelta(days=1)
            return utc_iso(candidate)

        target_weekday = weekday if weekday is not None else current.weekday()
        days_ahead = (target_weekday - current.weekday()) % 7
        candidate += timedelta(days=days_ahead)
        if candidate <= current:
            candidate += timedelta(days=7)
        return utc_iso(candidate)

    def create_schedule(
        self,
        *,
        name: str,
        loop_id: str,
        cadence: str,
        timezone: str,
        lookback_minutes: int,
        profile_id: str | None,
        method_config: dict[str, Any],
        time_local: str | None = None,
        weekday: int | None = None,
        scheduled_for: str | None = None,
        application_id: str = "cpm",
        subject_kind: str = "loop",
        selector: dict[str, Any] | None = None,
        interval_minutes: float | None = None,
        kind: str = "protocol",
        created_by: str = "Engineering",
        schedule_id: str | None = None,
        priority: int = PRIORITIES["scheduled"],
        spread_minutes: float = 0.0,
        owner: str | None = None,
        recurrence: dict[str, Any] | None = None,
        retry: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
    ) -> str:
        """A recurring analysis of one subject (``loop_id``) or of a selection rule.

        With ``selector`` the subjects are chosen again at every run (new loops
        enter on their own); ``loop_id`` is then ``"*"``. ``kind="round"`` is an
        application's monitoring round, run by the application itself.
        """

        if cadence not in SCHEDULE_CADENCES:
            raise ValueError(t("Invalid monitor frequency."))
        if cadence == "interval" and not (interval_minutes and interval_minutes > 0):
            raise ValueError(t("Enter the interval in minutes."))
        schedule_id = schedule_id or str(uuid.uuid4())
        now = self._now()
        next_run_at = self._next_occurrence(
            cadence=cadence,
            timezone=timezone,
            time_local=time_local,
            weekday=weekday,
            scheduled_for=scheduled_for,
            interval_minutes=interval_minutes,
            recurrence=recurrence,
        )
        with self._lock, self._connect() as connection:
            taken = {
                row["output_key"]
                for row in connection.execute("SELECT output_key FROM analysis_schedules")
                if row["output_key"]
            }
            connection.execute(
                """
                INSERT INTO analysis_schedules
                (schedule_id, name, loop_id, cadence, timezone, time_local,
                 weekday, scheduled_for, lookback_minutes, profile_id,
                 method_config_json, enabled, next_run_at, created_at, updated_at,
                 application_id, subject_kind, selector_json, kind, interval_minutes, created_by,
                 priority, spread_minutes, owner, recurrence_json, retry_json, outputs_json,
                 output_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?)
                """,
                (
                    schedule_id,
                    name.strip() or t("Monitor of {subject}", subject=loop_id),
                    "*" if selector is not None else loop_id,
                    cadence,
                    timezone,
                    time_local,
                    weekday,
                    scheduled_for,
                    lookback_minutes,
                    profile_id,
                    self._json(method_config),
                    next_run_at,
                    now,
                    now,
                    application_id,
                    subject_kind,
                    self._json(selector) if selector is not None else None,
                    kind,
                    interval_minutes,
                    created_by,
                    int(priority),
                    float(spread_minutes or 0),
                    owner or created_by,
                    self._json(recurrence) if recurrence else None,
                    self._json(retry) if retry else None,
                    self._json(outputs) if outputs else None,
                    output_key_of(name.strip() or str(loop_id), taken),
                ),
            )
        return schedule_id

    def ensure_round_schedule(
        self,
        application_id: str,
        *,
        name: str,
        subject_kind: str,
        interval_minutes: float,
        timezone: str,
    ) -> dict[str, Any]:
        """The application's monitoring round, visible and pausable like any schedule."""

        schedule_id = f"round-{application_id}"
        existing = self.get_schedule(schedule_id)
        if existing is not None and existing.get("name") in RENAMED_ROUNDS:
            # The loops' round is "Control loop performance", also where it
            # was made under an older name; a name a person gave it stays.
            self.update_schedule(schedule_id, name=name)
            existing = self.get_schedule(schedule_id)
        if existing is None:
            self.create_schedule(
                schedule_id=schedule_id,
                name=name,
                loop_id="*",
                cadence="interval",
                timezone=timezone,
                lookback_minutes=0,
                profile_id=None,
                method_config={},
                application_id=application_id,
                subject_kind=subject_kind,
                selector={"mode": "all"},
                interval_minutes=interval_minutes,
                kind="round",
                created_by="System",
            )
        return self.get_schedule(schedule_id) or {}

    def record_round(self, schedule_id: str, summary: dict[str, Any]) -> None:
        """Keep a finished round's summary (its header shows after a restart)."""

        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE analysis_schedules SET last_summary_json = ?, updated_at = ? "
                "WHERE schedule_id = ?",
                (self._json(summary), self._now(), schedule_id),
            )

    def update_schedule(self, schedule_id: str, **fields: Any) -> bool:
        """Change a schedule's name, interval, time, algorithm or selection; recomputes the next run."""

        allowed = {
            "name",
            "interval_minutes",
            "time_local",
            "weekday",
            "cadence",
            "lookback_minutes",
            "profile_id",
            "timezone",
            "priority",
            "spread_minutes",
            "owner",
            "kind",
            "scheduled_for",
        }
        schedule = self.get_schedule(schedule_id)
        if schedule is None:
            return False
        values = {
            key: value for key, value in fields.items() if key in allowed and value is not None
        }
        if (
            values.get("cadence") not in {None, "interval"}
            and fields.get("interval_minutes") is None
        ):
            # A step left from an earlier "every N minutes" would set how long results last.
            values["interval_minutes"] = None
        if "selector" in fields and fields["selector"] is not None:
            values["selector_json"] = self._json(fields["selector"])
        if fields.get("method_config") is not None:
            values["method_config_json"] = self._json(fields["method_config"])
        if fields.get("recurrence") is not None:
            values["recurrence_json"] = self._json(fields["recurrence"])
        if fields.get("retry") is not None:
            values["retry_json"] = self._json(fields["retry"])
        if fields.get("outputs") is not None:
            values["outputs_json"] = self._json(fields["outputs"])
        if not values:
            return True
        merged = {**schedule, **values}
        if "recurrence_json" in values:
            merged["recurrence"] = fields["recurrence"]
        if merged["cadence"] not in SCHEDULE_CADENCES:
            raise ValueError(t("Invalid monitor frequency."))
        if (
            merged["cadence"] == "interval"
            and schedule.get("kind") == "round"
            and schedule.get("last_run_at")
        ):
            last = datetime.fromisoformat(schedule["last_run_at"])
            values["next_run_at"] = utc_iso(
                last + timedelta(minutes=float(merged["interval_minutes"] or 10))
            )
        elif {
            "cadence",
            "time_local",
            "weekday",
            "interval_minutes",
            "timezone",
            "recurrence_json",
            "scheduled_for",
        } & set(values):
            values["next_run_at"] = self._next_occurrence(
                cadence=merged["cadence"],
                timezone=merged["timezone"],
                time_local=merged.get("time_local"),
                weekday=merged.get("weekday"),
                scheduled_for=merged.get("scheduled_for"),
                interval_minutes=merged.get("interval_minutes"),
                recurrence=merged.get("recurrence"),
            )
        values["updated_at"] = self._now()
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._lock, self._connect() as connection:
            connection.execute(
                f"UPDATE analysis_schedules SET {assignments} WHERE schedule_id = ?",
                [*values.values(), schedule_id],
            )
        return True

    def _schedule_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = self._row_with_json(
            row,
            {
                "method_config": ("method_config_json", {}),
                "selector": ("selector_json", None),
                "last_summary": ("last_summary_json", {}),
                "recurrence": ("recurrence_json", None),
                "retry": ("retry_json", None),
                "outputs": ("outputs_json", {}),
            },
        )
        item["retry"] = {**DEFAULT_RETRY, **(item.get("retry") or {})}
        item["subject_id"] = None if item.get("selector") is not None else item["loop_id"]
        return item

    def get_schedule(self, schedule_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM analysis_schedules WHERE schedule_id = ?", (schedule_id,)
            ).fetchone()
        return self._schedule_row(row) if row else None

    def list_schedules(
        self,
        *,
        enabled_only: bool = False,
        loop_id: str | None = None,
        application_id: str | None = None,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = []
        parameters: list[Any] = []
        if enabled_only:
            clauses.append("enabled = 1")
        if loop_id:
            clauses.append("loop_id = ?")
            parameters.append(loop_id)
        if application_id:
            clauses.append("application_id = ?")
            parameters.append(application_id)
        if kind:
            clauses.append("kind = ?")
            parameters.append(kind)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM analysis_schedules
                {where}
                ORDER BY kind = 'round' DESC, enabled DESC, next_run_at, name
                """,
                parameters,
            ).fetchall()
        return [self._schedule_row(row) for row in rows]

    def due_schedules(self, now: datetime | None = None) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM analysis_schedules
                WHERE enabled = 1
                  AND next_run_at IS NOT NULL
                ORDER BY next_run_at
                """,
            ).fetchall()
        schedules = [self._schedule_row(row) for row in rows]
        due: list[dict[str, Any]] = []
        for schedule in schedules:
            zone = zone_of(schedule["timezone"])
            current = now or datetime.now(zone)
            if current.tzinfo is None:
                current = current.replace(tzinfo=zone)
            scheduled = datetime.fromisoformat(schedule["next_run_at"])
            if scheduled.tzinfo is None:
                scheduled = scheduled.replace(tzinfo=zone)
            if scheduled.astimezone(UTC) <= current.astimezone(UTC):
                due.append(schedule)
        return sorted(
            due,
            key=lambda item: datetime.fromisoformat(item["next_run_at"]).timestamp(),
        )

    def run_schedule_now(
        self, schedule_id: str, subject_ids: list[str] | None = None, *, user: str = ""
    ) -> list[str]:
        """Queue one job per subject now, outside the calendar (the next run is kept): a
        person's request, so ahead of the schedules in the queue."""

        schedule = self.get_schedule(schedule_id)
        if schedule is None:
            return []
        subjects = subject_ids if schedule.get("selector") is not None else [schedule["loop_id"]]
        now = self._now()
        created = [
            self.create_job(
                loop_id=subject_id,
                name=schedule["name"],
                kind="scheduled",
                scheduled_for=now,
                lookback_minutes=schedule["lookback_minutes"],
                profile_id=schedule["profile_id"],
                method_config=schedule["method_config"],
                schedule_id=schedule_id,
                created_by=user or "System",
                application_id=schedule.get("application_id") or "cpm",
                subject_kind=schedule.get("subject_kind") or "loop",
                work=schedule_work(schedule),
                priority=PRIORITIES["manual"],
            )
            for subject_id in subjects or []
        ]
        if created:
            self.mark_manual_run(schedule_id, now)
        return created

    def mark_manual_run(self, schedule_id: str, at: str | None = None) -> None:
        """Note a person's "Run now": the schedules list shows it as the last run, while the
        calendar (its next slot, the stall warning) keeps counting from its own last slot."""

        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE analysis_schedules SET last_manual_at = ? WHERE schedule_id = ?",
                (at or self._now(), schedule_id),
            )

    def materialize_occurrence(
        self, schedule_id: str, subject_ids: list[str] | None = None, now: datetime | None = None
    ) -> list[str]:
        """Create one queued job per subject for the due occurrence and advance the schedule.

        ``subject_ids`` are the subjects the schedule's selector matched now; a
        single-subject schedule uses its own. Atomic: an occurrence is created
        once even if two schedulers race. Occurrences missed while the server
        was down or the schedule paused are not replayed: the next run is the
        first slot after now.
        """

        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM analysis_schedules
                WHERE schedule_id = ? AND enabled = 1
                """,
                (schedule_id,),
            ).fetchone()
            if row is None or not row["next_run_at"]:
                return []
            schedule = self._schedule_row(row)
            work = schedule_work(schedule)
            if work == "round":
                subjects = ["*"]
            else:
                subjects = (
                    subject_ids if schedule.get("selector") is not None else [schedule["loop_id"]]
                )
            requested = self._now()
            slot = _utc(schedule["next_run_at"])
            spread = max(0.0, float(schedule.get("spread_minutes") or 0)) * 60
            busy = {
                item["loop_id"]
                for item in connection.execute(
                    f"""
                    SELECT DISTINCT loop_id FROM analysis_jobs
                    WHERE schedule_id = ? AND work = ?
                      AND status IN ({",".join("?" for _ in OPEN_STATUSES)})
                    """,
                    (schedule_id, work, *OPEN_STATUSES),
                ).fetchall()
            }
            created: list[str] = []
            skipped = 0
            for subject_id in subjects or []:
                job_id = str(uuid.uuid4())
                # No pile-up: a subject whose previous occurrence has not
                # ended gets this one as skipped, with the reason, instead of a second in line.
                late = subject_id in busy
                offset = _spread(schedule_id, subject_id, spread) if spread else 0.0
                try:
                    connection.execute(
                        """
                        INSERT INTO analysis_jobs
                        (job_id, loop_id, schedule_id, name, kind, status,
                         requested_at, scheduled_for, lookback_minutes, profile_id,
                         method_config_json, created_by, application_id, subject_kind,
                         work, priority, due_at, completed_at, error_message)
                        VALUES (?, ?, ?, ?, 'scheduled', ?, ?, ?, ?, ?, ?, 'System', ?, ?,
                                ?, ?, ?, ?, ?)
                        """,
                        (
                            job_id,
                            subject_id,
                            schedule_id,
                            schedule["name"],
                            "skipped" if late else "queued",
                            requested,
                            schedule["next_run_at"],
                            schedule["lookback_minutes"],
                            schedule["profile_id"],
                            self._json(schedule["method_config"]),
                            schedule.get("application_id") or "cpm",
                            schedule.get("subject_kind") or "loop",
                            work,
                            int(schedule.get("priority") or PRIORITIES["scheduled"]),
                            utc_iso(slot + timedelta(seconds=offset)),
                            requested if late else None,
                            t("The previous occurrence had not ended yet.") if late else None,
                        ),
                    )
                except sqlite3.IntegrityError:
                    continue
                if late:
                    skipped += 1
                else:
                    created.append(job_id)
            # Even when every job already existed (a racing scheduler, a slot
            # re-enabled) the occurrence is done: advance, or it stays due forever.
            cadence = schedule["cadence"]
            if cadence == "once":
                next_run_at = None
                enabled = 0
            else:
                next_run_at = self._following_run(schedule, now)
                # A calendar past its last day has no next occurrence: it stops.
                enabled = 1 if next_run_at else 0
            connection.execute(
                """
                UPDATE analysis_schedules
                SET last_run_at = next_run_at, next_run_at = ?,
                    enabled = ?, updated_at = ?,
                    last_summary_json = COALESCE(?, last_summary_json)
                WHERE schedule_id = ?
                """,
                (
                    next_run_at,
                    enabled,
                    self._now(),
                    # A round keeps its last summary until it ends (``record_round``).
                    None
                    if work == "round"
                    else self._json({"jobs": len(created), "skipped": skipped}),
                    schedule_id,
                ),
            )
        return created

    def _following_run(self, schedule: dict[str, Any], now: datetime | None = None) -> str | None:
        """The first slot of a recurring schedule after the one just run and after now.

        Daily and weekly slots keep their local time across daylight saving
        changes; interval and hourly slots step in absolute time.
        """

        zone = zone_of(schedule["timezone"])
        current = (now or datetime.now(zone)).astimezone(zone)
        previous = datetime.fromisoformat(schedule["next_run_at"])
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=zone)
        cadence = schedule["cadence"]
        if cadence == "calendar":
            found = next_after(
                Recurrence.model_validate(schedule.get("recurrence") or {}),
                schedule["timezone"],
                max(previous, current),
            )
            return utc_iso(found) if found else None
        if cadence in {"daily", "weekly"}:
            # Wall-clock arithmetic in the schedule's zone keeps 08:00 at 08:00.
            local = previous.astimezone(zone)
            following = local + timedelta(days=1 if cadence == "daily" else 7)
            following = following.astimezone(UTC).astimezone(zone)
            if following <= current:
                return self._next_occurrence(
                    recurrence=schedule.get("recurrence"),
                    cadence=cadence,
                    timezone=schedule["timezone"],
                    time_local=schedule["time_local"],
                    weekday=schedule["weekday"],
                    scheduled_for=None,
                    now=current,
                ) or utc_iso(following)
            return utc_iso(following)
        step = (
            timedelta(minutes=float(schedule.get("interval_minutes") or 60))
            if cadence == "interval"
            else timedelta(hours=1)
        )
        following = previous.astimezone(UTC) + step
        if following <= current:
            following += step * ((current - following) // step + 1)
        return utc_iso(following)

    def upcoming(self, schedule: dict[str, Any], count: int = 5) -> list[str]:
        """The next ``count`` occurrences of a schedule (saved or not), in its local time."""

        first = self._next_occurrence(
            cadence=schedule["cadence"],
            timezone=schedule.get("timezone") or "UTC",
            time_local=schedule.get("time_local"),
            weekday=schedule.get("weekday"),
            scheduled_for=schedule.get("scheduled_for"),
            interval_minutes=schedule.get("interval_minutes"),
            recurrence=schedule.get("recurrence"),
        )
        found = [first] if first else []
        while found and len(found) < count and schedule["cadence"] != "once":
            previous = found[-1]
            following = self._following_run(
                {
                    **schedule,
                    "timezone": schedule.get("timezone") or "UTC",
                    "next_run_at": previous,
                },
                now=datetime.fromisoformat(previous),
            )
            if not following:
                break
            found.append(following)
        return found

    def schedule_stats(self, schedule_id: str, limit: int = 2000) -> dict[str, Any]:
        """A schedule's record over its latest executions (as Elipse EPM's
        statistics): how many ran, failed and needed another try, how long they took, and
        when the outcome last changed (completed to failed, or back)."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT status, attempts, started_at, completed_at FROM analysis_jobs
                WHERE schedule_id = ? AND status IN ('completed', 'failed')
                ORDER BY completed_at DESC LIMIT ?
                """,
                (schedule_id, limit),
            ).fetchall()
        took = []
        for row in rows:
            try:
                took.append(
                    (
                        datetime.fromisoformat(row["completed_at"])
                        - datetime.fromisoformat(row["started_at"])
                    ).total_seconds()
                )
            except (TypeError, ValueError):
                continue
        changed = None
        for newer, older in zip(rows, rows[1:], strict=False):
            if newer["status"] != older["status"]:
                changed = {"at": newer["completed_at"], "to": newer["status"]}
                break
        return {
            "executions": len(rows),
            "failed": sum(1 for row in rows if row["status"] == "failed"),
            "retried": sum(1 for row in rows if int(row["attempts"] or 0) > 1),
            "seconds_min": min(took) if took else None,
            "seconds_mean": sum(took) / len(took) if took else None,
            "seconds_max": max(took) if took else None,
            "last_status": rows[0]["status"] if rows else None,
            "last_change": changed,
            "limit": limit,
        }

    def mean_seconds(self, work: str, limit: int = 500) -> float | None:
        """How long the latest executions of this work took, on average."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT started_at, completed_at FROM analysis_jobs
                WHERE work = ? AND status = 'completed' AND started_at IS NOT NULL
                ORDER BY completed_at DESC LIMIT ?
                """,
                (work, limit),
            ).fetchall()
        took = []
        for row in rows:
            try:
                took.append(
                    (
                        datetime.fromisoformat(row["completed_at"])
                        - datetime.fromisoformat(row["started_at"])
                    ).total_seconds()
                )
            except (TypeError, ValueError):
                continue
        return sum(took) / len(took) if took else None

    def set_schedule_enabled(self, schedule_id: str, enabled: bool) -> bool:
        """Pause or resume a schedule; a resumed one runs from now on, without catching up."""

        schedule = self.get_schedule(schedule_id)
        if schedule is None:
            return False
        next_run_at = schedule["next_run_at"]
        if enabled and not (schedule["enabled"] and next_run_at):
            next_run_at = self._next_occurrence(
                cadence=schedule["cadence"],
                timezone=schedule["timezone"],
                time_local=schedule["time_local"],
                weekday=schedule["weekday"],
                scheduled_for=schedule["scheduled_for"],
                interval_minutes=schedule.get("interval_minutes"),
                recurrence=schedule.get("recurrence"),
            )
            if schedule["cadence"] == "once" and next_run_at:
                # A one-off whose moment has passed does not run again.
                if datetime.fromisoformat(next_run_at) <= datetime.now(UTC):
                    next_run_at = None
            enabled = next_run_at is not None
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE analysis_schedules
                SET enabled = ?, next_run_at = ?, updated_at = ?
                WHERE schedule_id = ?
                """,
                (int(enabled), next_run_at, self._now(), schedule_id),
            )
        return True

    def delete_schedule(self, schedule_id: str) -> bool:
        """Remove a user schedule; its past jobs stay in the history."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT kind FROM analysis_schedules WHERE schedule_id = ?", (schedule_id,)
            ).fetchone()
            if row is None or row["kind"] == "round":
                return False
            connection.execute(
                "UPDATE analysis_jobs SET schedule_id = NULL WHERE schedule_id = ?", (schedule_id,)
            )
            connection.execute(
                "DELETE FROM analysis_schedules WHERE schedule_id = ?", (schedule_id,)
            )
        return True


def schedule_work(schedule: dict[str, Any]) -> str:
    """What a schedule's occurrence queues: a round (one execution over every subject) or one
    execution of the algorithm per subject."""

    if schedule.get("kind") == "round":
        return "round"
    return "asset" if schedule.get("subject_kind") == "asset" else "loop"


def _utc(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).astimezone(UTC)


def _spread(schedule_id: str, subject_id: str, seconds: float) -> float:
    """Where in the spread window a subject's execution falls: the same place every time."""

    digest = hashlib.sha256(f"{schedule_id}/{subject_id}".encode()).digest()
    return int.from_bytes(digest[:4], "big") / 2**32 * seconds
