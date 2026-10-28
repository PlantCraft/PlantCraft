"""Analysis jobs, their results and recurring schedules."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from plantcraft_sdk.utc import utc_iso

from linkcraft.catalog.registry import describe_result
from linkcraft.db import Migration, Store, add_columns
from linkcraft.engine.recurrence import Recurrence, next_after
from linkcraft.engine.samples import ROUND_SCOPE, RunSampleStore
from linkcraft.engine.zones import zone_of
from linkcraft.i18n import t

# English labels; whoever serves them translates them with t().
JOB_STATUSES = {
    "scheduled": "Scheduled",
    "waiting_data": "Waiting for data",
    "queued": "Queued",
    "running": "Running",
    "completed": "Completed",
    "failed": "Failed",
    "cancelled": "Cancelled",
    "skipped": "Skipped",
}

# What an execution runs: one loop's algorithm, a whole round (every loop, or Signal quality on
# every signal), an algorithm on one asset, or the archive replayed.
WORKS = {
    "loop": "Algorithm on a loop",
    "round": "Every target in turn",
    "asset": "Algorithm on an asset",
    "replay": "Replay of the past",
}

# The queue's order (owner, 2026-10-23): what a person asked for first, then the schedules,
# then the past replayed. Higher runs first; equal priorities run in the order they were due.
PRIORITIES = {"manual": 100, "test": 100, "baseline": 60, "scheduled": 50, "replay": 10}
OPEN_STATUSES = ("scheduled", "waiting_data", "queued", "running")

# Names the loops' round had before; it is renamed at start (``ensure_round_schedule``).
RENAMED_ROUNDS = frozenset({"Loop monitor", "Monitoring round", "Loop monitoring round"})

JOB_KINDS = {
    "baseline": "Initial",
    "manual": "Manual analysis",
    "test": "Manual test",
    "scheduled": "Scheduled",
}

SCHEDULE_CADENCES = {
    "interval": "Every N minutes",
    "once": "Once",
    "hourly": "Hourly",
    "daily": "Daily",
    "weekly": "Weekly",
    # A calendar rule (``recurrence``): every N minutes on some days, several times a day, chosen
    # weekdays, a day of the month (owner, 2026-10-24).
    "calendar": "Calendar",
}

# What a schedule does when an execution cannot read the plant or finds no data (owner,
# 2026-10-25, as Elipse EPM's scheduled calculations): try again, a few times, a few minutes
# apart, and give up when the next occurrence comes first.
DEFAULT_RETRY = {"enabled": True, "count": 2, "wait_minutes": 5.0, "abort_on_next": True}
# A schedule's part in the ids of the points it records (``<asset>.<key>.<output>``).
OUTPUT_KEY_LENGTH = 40


def output_key_of(name: str, taken: set[str]) -> str:
    """A short stable key from a schedule's name ("Revisão diária" → ``revisao-diaria``),
    unique among ``taken``; kept when the schedule is renamed."""

    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")[:OUTPUT_KEY_LENGTH].strip("-")
    base = base or "schedule"
    key, number = base, 2
    while key in taken:
        suffix = f"-{number}"
        key = f"{base[: OUTPUT_KEY_LENGTH - len(suffix)]}{suffix}"
        number += 1
    return key


def lean_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """A summary as kept with its execution: each recorded series without its points, and
    without the wires' samples (``engine.samples`` keeps those of the last runs).

    An algorithm on an asset records its series over the whole window (hundreds of points
    each, tens of kB per execution); the Historian keeps the points, the execution each
    series' last value."""

    if not isinstance(summary, dict):
        return summary
    # The wires' samples are kept apart, for the last runs only (``engine.samples``).
    summary = {key: value for key, value in summary.items() if key != "samples"}
    recorded = summary.get("recorded")
    if not recorded:
        return summary
    return {
        **summary,
        "recorded": [
            {key: value for key, value in entry.items() if key != "points"}
            if isinstance(entry, dict)
            else entry
            for entry in recorded
        ],
    }


class JobStore(Store):
    """Queue of analysis jobs and the schedules that materialize them."""

    def _keep_samples(self, entries: list[tuple[str, dict[str, Any] | None]]) -> None:
        """The wires' samples of ended runs (``job_id``, summary), kept for the newest
        ``SAMPLES_KEPT`` of each subject and schedule (``engine.samples``)."""

        wanted = {
            job_id: summary["samples"]
            for job_id, summary in entries
            if isinstance(summary, dict) and summary.get("samples")
        }
        if not wanted:
            return
        marks = ",".join("?" * len(wanted))
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT job_id, loop_id, schedule_id, completed_at, requested_at FROM analysis_jobs WHERE job_id IN ({marks})",  # noqa: S608
                list(wanted),
            ).fetchall()
        self.samples.save(
            [
                {
                    "run_key": row["job_id"],
                    "scope": row["schedule_id"] or "",
                    "subject_id": row["loop_id"],
                    "at": row["completed_at"] or row["requested_at"],
                    "detail": {"wires": wanted[row["job_id"]]},
                }
                for row in rows
            ]
        )

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS analysis_schedules (
        schedule_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        loop_id TEXT NOT NULL,
        cadence TEXT NOT NULL,
        timezone TEXT NOT NULL,
        time_local TEXT,
        weekday INTEGER,
        scheduled_for TEXT,
        lookback_minutes INTEGER NOT NULL,
        profile_id TEXT,
        method_config_json TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        next_run_at TEXT,
        last_run_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        application_id TEXT NOT NULL DEFAULT 'cpm',
        subject_kind TEXT NOT NULL DEFAULT 'loop',
        selector_json TEXT,
        kind TEXT NOT NULL DEFAULT 'protocol',
        interval_minutes REAL,
        last_summary_json TEXT,
        created_by TEXT NOT NULL DEFAULT 'Engineering'
    );

    CREATE TABLE IF NOT EXISTS analysis_jobs (
        job_id TEXT PRIMARY KEY,
        loop_id TEXT NOT NULL,
        schedule_id TEXT,
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        status TEXT NOT NULL,
        requested_at TEXT NOT NULL,
        scheduled_for TEXT,
        started_at TEXT,
        completed_at TEXT,
        range_start TEXT,
        range_end TEXT,
        lookback_minutes INTEGER,
        profile_id TEXT,
        method_config_json TEXT NOT NULL,
        config_snapshot_json TEXT,
        summary_json TEXT,
        error_message TEXT,
        source_start TEXT,
        source_end TEXT,
        created_by TEXT NOT NULL DEFAULT 'Engineering',
        application_id TEXT NOT NULL DEFAULT 'cpm',
        subject_kind TEXT NOT NULL DEFAULT 'loop',
        FOREIGN KEY(schedule_id) REFERENCES analysis_schedules(schedule_id)
    );

    CREATE TABLE IF NOT EXISTS analysis_job_results (
        job_id TEXT NOT NULL,
        method_id TEXT NOT NULL,
        result_json TEXT NOT NULL,
        PRIMARY KEY(job_id, method_id),
        FOREIGN KEY(job_id) REFERENCES analysis_jobs(job_id)
            ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_jobs_loop_requested
    ON analysis_jobs(loop_id, requested_at DESC);

    CREATE INDEX IF NOT EXISTS idx_jobs_loop_started
    ON analysis_jobs(loop_id, started_at DESC);

    CREATE INDEX IF NOT EXISTS idx_jobs_status_scheduled
    ON analysis_jobs(status, scheduled_for);

    CREATE INDEX IF NOT EXISTS idx_schedules_due
    ON analysis_schedules(enabled, next_run_at);

    CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_schedule_slot
    ON analysis_jobs(schedule_id, scheduled_for, loop_id);
    """

    # Added in 0.4.0 (the queue, Link round 6) and Link round 8 (the calendar, the retries;
    # D6: what each execution records and the schedule's key in point ids).
    MIGRATIONS = (
        Migration(
            "columns-before-0.5-jobs",
            add_columns(
                "analysis_jobs",
                {
                    "priority": "INTEGER NOT NULL DEFAULT 50",
                    "attempts": "INTEGER NOT NULL DEFAULT 0",
                    "due_at": "TEXT",
                    "work": "TEXT NOT NULL DEFAULT 'loop'",
                    "payload_json": "TEXT",
                    "progress_done": "INTEGER",
                    "progress_total": "INTEGER",
                    "worker": "TEXT",
                },
            ),
        ),
        Migration(
            "columns-before-0.5-schedules",
            add_columns(
                "analysis_schedules",
                {
                    "priority": "INTEGER NOT NULL DEFAULT 50",
                    "spread_minutes": "REAL NOT NULL DEFAULT 0",
                    "owner": "TEXT",
                    "recurrence_json": "TEXT",
                    "retry_json": "TEXT",
                    "outputs_json": "TEXT",
                    "output_key": "TEXT",
                },
            ),
        ),
        # When a person last ran it by hand ("Run now"), apart from the calendar's last slot.
        Migration(
            "last-manual-run",
            add_columns("analysis_schedules", {"last_manual_at": "TEXT"}),
        ),
    )

    def __init__(self, db: Any):
        super().__init__(db)
        self.samples = RunSampleStore(db)
        with self._lock, self._connect() as connection:
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_queue "
                "ON analysis_jobs(status, priority DESC, due_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_finished ON analysis_jobs(completed_at)"
            )
            # Each subject's newest run in a schedule, and of the runs people started
            # (``latest_finished``): covering, so the answer never reads a run's row. A run's
            # row is ~7 KB of JSON; reading 1,500 of them per monitor, cold, through Docker
            # Desktop's bind mount took ~0.15 s each on the Mac mini (2026-10-27).
            connection.execute("DROP INDEX IF EXISTS idx_jobs_schedule_subject")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_schedule_latest ON analysis_jobs("
                "schedule_id, loop_id, status, work, started_at, requested_at, job_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_kind_latest ON analysis_jobs("
                "kind, loop_id, status, schedule_id, work, started_at, requested_at, job_id)"
            )
            # Schedules made before output keys get one from their name (once).
            rows = connection.execute(
                "SELECT schedule_id, name, output_key FROM analysis_schedules ORDER BY created_at"
            ).fetchall()
            taken = {row["output_key"] for row in rows if row["output_key"]}
            for row in rows:
                if not row["output_key"]:
                    key = output_key_of(row["name"] or "", taken)
                    taken.add(key)
                    connection.execute(
                        "UPDATE analysis_schedules SET output_key = ? WHERE schedule_id = ?",
                        (key, row["schedule_id"]),
                    )

    def create_job(
        self,
        *,
        loop_id: str,
        name: str,
        kind: str,
        status: str = "queued",
        scheduled_for: str | None = None,
        range_start: str | None = None,
        range_end: str | None = None,
        lookback_minutes: int | None = None,
        profile_id: str | None = None,
        method_config: dict[str, Any] | None = None,
        schedule_id: str | None = None,
        created_by: str = "Engineering",
        job_id: str | None = None,
        application_id: str = "cpm",
        subject_kind: str = "loop",
        work: str = "loop",
        priority: int | None = None,
        due_at: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        """Queue one execution of one subject (``loop_id`` holds the subject id; ``*`` for a
        round or a replay, which cover many). The priority follows ``kind`` unless given."""

        job_id = job_id or str(uuid.uuid4())
        now = self._now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO analysis_jobs
                (job_id, loop_id, schedule_id, name, kind, status,
                 requested_at, scheduled_for, range_start, range_end,
                 lookback_minutes, profile_id, method_config_json, created_by,
                 application_id, subject_kind, work, priority, due_at, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    loop_id,
                    schedule_id,
                    name.strip() or t("Analysis of {subject}", subject=loop_id),
                    kind,
                    status,
                    now,
                    scheduled_for,
                    range_start,
                    range_end,
                    lookback_minutes,
                    profile_id,
                    self._json(method_config or {}),
                    created_by,
                    application_id,
                    subject_kind,
                    work,
                    PRIORITIES.get(kind, 50) if priority is None else priority,
                    due_at or self.utc_now(),
                    self._json(payload) if payload is not None else None,
                ),
            )
        return job_id

    def subjects_with_jobs(self, subject_kind: str = "loop") -> set[str]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT loop_id FROM analysis_jobs WHERE subject_kind = ?", (subject_kind,)
            ).fetchall()
        return {row[0] for row in rows}

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM analysis_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return self._job_row(row) if row else None

    def _job_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = self._row_with_json(
            row,
            {
                "method_config": ("method_config_json", {}),
                "config_snapshot": ("config_snapshot_json", {}),
                "summary": ("summary_json", {}),
                "payload": ("payload_json", {}),
            },
        )
        item["subject_id"] = item["loop_id"]
        return item

    def list_jobs(
        self,
        *,
        loop_id: str | None = None,
        loop_ids: list[str] | None = None,
        statuses: set[str] | None = None,
        kinds: set[str] | None = None,
        since: str | None = None,
        until: str | None = None,
        query: str | None = None,
        application_id: str | None = None,
        subject_kind: str | None = None,
        schedule_id: str | None = None,
        works: set[str] | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where, parameters = self._job_filter(
            loop_id=loop_id,
            loop_ids=loop_ids,
            statuses=statuses,
            kinds=kinds,
            since=since,
            until=until,
            query=query,
            application_id=application_id,
            subject_kind=subject_kind,
            schedule_id=schedule_id,
            works=works,
        )
        parameters.extend([limit, offset])
        with self._lock, self._connect() as connection:
            # The order on the ids alone, then the rows: sorting whole rows (summaries included)
            # spills to SQLite's temporary files, and the container's /tmp is small (64 MB).
            ids = [
                row[0]
                for row in connection.execute(
                    f"""
                    SELECT job_id FROM analysis_jobs
                    {where}
                    ORDER BY COALESCE(started_at, requested_at) DESC,
                             requested_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    parameters,
                )
            ]
            found: dict[str, sqlite3.Row] = {}
            for start in range(0, len(ids), 500):
                chunk = ids[start : start + 500]
                marks = ",".join("?" * len(chunk))
                for row in connection.execute(
                    f"SELECT * FROM analysis_jobs WHERE job_id IN ({marks})",  # noqa: S608
                    chunk,
                ):
                    found[row["job_id"]] = row
        return [self._job_row(found[job_id]) for job_id in ids if job_id in found]

    def latest_finished(
        self, schedule_id: str | None, subjects: list[str] | None = None
    ) -> dict[str, dict[str, Any]]:
        """Each subject's newest ended run in a schedule (``None``: the runs people started),
        rounds and replays aside. One row per subject straight from SQLite: reading every run
        to keep the newest decoded ~15,000 summaries for 25 rows on the Mac mini (4-12 s)."""

        query, parameters = self._latest_query(schedule_id, subjects)
        with self._lock, self._connect() as connection:
            ids = [row[0] for row in connection.execute(query, parameters)]
            rows: list[sqlite3.Row] = []
            for start in range(0, len(ids), 500):
                chunk = ids[start : start + 500]
                marks = ",".join("?" * len(chunk))
                rows += connection.execute(
                    f"SELECT * FROM analysis_jobs WHERE job_id IN ({marks})",  # noqa: S608
                    chunk,
                ).fetchall()
        found = [self._job_row(row) for row in rows]
        return {job["loop_id"]: job for job in found}

    @staticmethod
    def _latest_query(schedule_id: str | None, subjects: list[str] | None) -> tuple[str, list[Any]]:
        """The ids of ``latest_finished``'s runs, answered from an index alone."""

        clauses = [
            "status IN ('completed', 'failed')",
            "COALESCE(work, '') NOT IN ('round', 'replay')",
        ]
        parameters: list[Any] = []
        if schedule_id is None:
            clauses += ["kind = 'manual'", "COALESCE(schedule_id, '') = ''"]
        else:
            clauses.append("schedule_id = ?")
            parameters.append(schedule_id)
        if subjects:
            clauses.append(f"loop_id IN ({','.join('?' for _ in subjects)})")
            parameters.extend(subjects)
        query = f"""
            SELECT job_id FROM (
                SELECT job_id, ROW_NUMBER() OVER (
                    PARTITION BY loop_id
                    ORDER BY COALESCE(started_at, requested_at) DESC, requested_at DESC
                ) AS place
                FROM analysis_jobs WHERE {" AND ".join(clauses)}
            ) WHERE place = 1
            """  # noqa: S608
        return query, parameters

    def count_jobs(self, **filters: Any) -> int:
        where, parameters = self._job_filter(**filters)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS total FROM analysis_jobs {where}", parameters
            ).fetchone()
        return int(row["total"])

    @staticmethod
    def _job_filter(
        *,
        loop_id: str | None = None,
        loop_ids: list[str] | None = None,
        statuses: set[str] | None = None,
        kinds: set[str] | None = None,
        since: str | None = None,
        until: str | None = None,
        query: str | None = None,
        application_id: str | None = None,
        subject_kind: str | None = None,
        schedule_id: str | None = None,
        works: set[str] | None = None,
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        for column, value in (
            ("application_id", application_id),
            ("subject_kind", subject_kind),
            ("schedule_id", schedule_id),
        ):
            if value:
                clauses.append(f"{column} = ?")
                parameters.append(value)
        if loop_id:
            clauses.append("loop_id = ?")
            parameters.append(loop_id)
        if loop_ids:
            clauses.append(f"loop_id IN ({','.join('?' for _ in loop_ids)})")
            parameters.extend(loop_ids)
        for column, values in (("status", statuses), ("kind", kinds), ("work", works)):
            if values:
                placeholders = ",".join("?" for _ in values)
                clauses.append(f"{column} IN ({placeholders})")
                parameters.extend(sorted(values))
        if since:
            clauses.append("COALESCE(started_at, requested_at) >= ?")
            parameters.append(since)
        if until:
            clauses.append("COALESCE(started_at, requested_at) <= ?")
            parameters.append(until)
        if query:
            clauses.append(
                "(name LIKE ? ESCAPE '\\' OR loop_id LIKE ? ESCAPE '\\' OR created_by LIKE ? ESCAPE '\\')"
            )
            literal = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            parameters.extend([f"%{literal}%"] * 3)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        return where, parameters

    def prune_jobs(self, *, days: float = 90) -> int:
        """Delete finished runs requested more than ``days`` ago, with their results; runs deleted.

        Every schedule makes one run per subject at each occurrence, so without this the table
        grows for ever (2,000 loops every hour: 48,000 runs a day). Queued and running runs stay,
        and so does each subject's newest run whatever its age.
        """

        cutoff = utc_iso(datetime.now(UTC) - timedelta(days=days))
        with self._lock, self._connect() as connection:
            # analysis_job_results follow (ON DELETE CASCADE).
            deleted = connection.execute(
                """
                DELETE FROM analysis_jobs
                WHERE requested_at < ?
                  AND status NOT IN ('queued', 'running', 'scheduled', 'waiting_data')
                  AND job_id NOT IN (
                      SELECT job_id FROM (
                          SELECT job_id, ROW_NUMBER() OVER (
                              PARTITION BY loop_id ORDER BY requested_at DESC
                          ) AS position
                          FROM analysis_jobs
                      ) WHERE position = 1
                  )
                """,
                (cutoff,),
            ).rowcount
            # The samples of runs gone with them (a deleted schedule's), not a loop's rounds.
            connection.execute(
                "DELETE FROM run_samples WHERE scope != ? "
                "AND run_key NOT IN (SELECT job_id FROM analysis_jobs)",
                (ROUND_SCOPE,),
            )
        return deleted

    def thin_summaries(self, *, batch: int = 200) -> int:
        """Take the recorded points out of summaries kept before 0.4.1, a batch at a time (an
        upgraded install holds thousands, tens of kB each). Summaries thinned."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT job_id, summary_json FROM analysis_jobs "
                """WHERE summary_json LIKE '%"points"%' LIMIT ?""",
                (batch,),
            ).fetchall()
            for row in rows:
                summary = json.loads(row["summary_json"])
                connection.execute(
                    "UPDATE analysis_jobs SET summary_json = ? WHERE job_id = ?",
                    (self._json(lean_summary(summary)), row["job_id"]),
                )
        return len(rows)

    def prune_detail(self, *, keep: int = 50) -> int:
        """Keep the full detail (each method's result, the configuration it ran with) of the
        newest ``keep`` ended runs per subject and schedule; older runs keep their summary
        (owner decision D7: the long history is in the Historian). Runs thinned."""

        with self._lock, self._connect() as connection:
            old = [
                row["job_id"]
                for row in connection.execute(
                    """
                    SELECT job_id FROM (
                        SELECT job_id, config_snapshot_json, ROW_NUMBER() OVER (
                            PARTITION BY loop_id, COALESCE(schedule_id, '')
                            ORDER BY requested_at DESC
                        ) AS position
                        FROM analysis_jobs
                        WHERE status NOT IN ('queued', 'running', 'scheduled', 'waiting_data')
                    ) WHERE position > ? AND config_snapshot_json IS NOT NULL
                    """,
                    (keep,),
                )
            ]
            for start in range(0, len(old), 500):
                chunk = old[start : start + 500]
                marks = ",".join("?" * len(chunk))
                connection.execute(
                    f"DELETE FROM analysis_job_results WHERE job_id IN ({marks})",  # noqa: S608
                    chunk,
                )
                connection.execute(
                    "UPDATE analysis_jobs SET config_snapshot_json = NULL "  # noqa: S608
                    f"WHERE job_id IN ({marks})",
                    chunk,
                )
        return len(old)

    def requeue_interrupted(self) -> list[str]:
        """Put back in the queue jobs a stopped process left running; their ids."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "UPDATE analysis_jobs SET status = 'queued', started_at = NULL "
                "WHERE status = 'running' RETURNING job_id"
            ).fetchall()
        return [row[0] for row in rows]

    # The queue ---------------------------------------------------------------------------

    @staticmethod
    def utc_now() -> str:
        """The queue's clock: UTC in the suite's one form, so due times compare as text."""

        return utc_iso()

    def claim_next(self, worker: str, works: set[str] | None = None) -> dict[str, Any] | None:
        """Take the next execution due, highest priority first, then the longest waiting; it
        is marked running in the same statement, so two workers never take the same one."""

        work_clause = ""
        parameters: list[Any] = [self._now(), worker, self.utc_now()]
        if works:
            work_clause = f" AND work IN ({','.join('?' for _ in works)})"
            parameters.extend(sorted(works))
        with self._lock, self._connect() as connection:
            row = connection.execute(
                f"""
                UPDATE analysis_jobs
                SET status = 'running', started_at = ?, attempts = attempts + 1, worker = ?
                WHERE job_id = (
                    SELECT job_id FROM analysis_jobs
                    WHERE status = 'queued' AND (due_at IS NULL OR due_at <= ?){work_clause}
                    ORDER BY priority DESC, COALESCE(due_at, requested_at), requested_at
                    LIMIT 1
                ) AND status = 'queued'
                RETURNING *
                """,
                parameters,
            ).fetchone()
        return self._job_row(row) if row else None

    def next_due_at(self) -> str | None:
        """When the earliest execution waiting for a later moment becomes due."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT MIN(due_at) AS due FROM analysis_jobs WHERE status = 'queued' AND due_at > ?",
                (self.utc_now(),),
            ).fetchone()
        return row["due"] if row else None

    def requeue_later(self, job_id: str, due_at: str, reason: str) -> None:
        """Put a running execution back in the queue until ``due_at`` (a retry)."""

        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE analysis_jobs
                SET status = 'queued', due_at = ?, started_at = NULL, worker = NULL,
                    error_message = ?
                WHERE job_id = ? AND status = 'running'
                """,
                (due_at, reason, job_id),
            )

    def set_progress(self, job_id: str, done: int, total: int) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE analysis_jobs SET progress_done = ?, progress_total = ? WHERE job_id = ?",
                (int(done), int(total), job_id),
            )

    def finish(
        self, job_id: str, status: str, *, summary: dict[str, Any] | None = None, error: str = ""
    ) -> None:
        """End an execution that keeps no results per method (a round, a replay, an asset)."""

        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE analysis_jobs
                SET status = ?, completed_at = ?, summary_json = COALESCE(?, summary_json),
                    error_message = ?
                WHERE job_id = ?
                """,
                (
                    status,
                    self._now(),
                    self._json(lean_summary(summary)) if summary is not None else None,
                    error or None,
                    job_id,
                ),
            )
        self._keep_samples([(job_id, summary)])

    def open_work(
        self, work: str, subject: str = "*", schedule_id: str | None = None
    ) -> dict[str, Any] | None:
        """The execution of this work (and schedule) still queued or running, if any."""

        clause, parameters = "", [work, subject]
        if schedule_id:
            clause, parameters = " AND schedule_id = ?", [*parameters, schedule_id]
        with self._lock, self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM analysis_jobs
                WHERE work = ? AND loop_id = ? AND status IN ('queued', 'running'){clause}
                ORDER BY requested_at DESC LIMIT 1
                """,
                parameters,
            ).fetchone()
        return self._job_row(row) if row else None

    def latest_work(self, work: str) -> dict[str, Any] | None:
        """The newest execution of this work, whatever its state."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM analysis_jobs WHERE work = ? ORDER BY requested_at DESC LIMIT 1",
                (work,),
            ).fetchone()
        return self._job_row(row) if row else None

    def queue_counts(self, since: str) -> dict[str, Any]:
        """What the queue holds now and what ended since ``since`` (local time, like
        ``completed_at``), for the queue's samples."""

        hour = utc_iso(datetime.now(UTC) - timedelta(hours=1))
        now = self.utc_now()
        with self._lock, self._connect() as connection:
            open_rows = connection.execute(
                """
                SELECT status, COUNT(*) AS total,
                       MIN(CASE WHEN status = 'queued' AND (due_at IS NULL OR due_at <= ?)
                           THEN COALESCE(due_at, requested_at) END) AS oldest
                FROM analysis_jobs WHERE status IN ('queued', 'running') GROUP BY status
                """,
                (now,),
            ).fetchall()
            ended = connection.execute(
                """
                SELECT status, COUNT(*) AS total,
                       SUM(CASE WHEN completed_at >= ? THEN 1 ELSE 0 END) AS recent
                FROM analysis_jobs
                WHERE completed_at >= ? AND status IN ('completed', 'failed', 'cancelled', 'skipped')
                GROUP BY status
                """,
                (since, min(since, hour)),
            ).fetchall()
            timed = connection.execute(
                """
                SELECT started_at, completed_at FROM analysis_jobs
                WHERE completed_at >= ? AND status = 'completed' AND started_at IS NOT NULL
                """,
                (since,),
            ).fetchall()
            hourly = connection.execute(
                """
                SELECT status, COUNT(*) AS total FROM analysis_jobs
                WHERE completed_at >= ? GROUP BY status
                """,
                (hour,),
            ).fetchall()
        counts = {row["status"]: row["total"] for row in open_rows}
        oldest = next((row["oldest"] for row in open_rows if row["oldest"]), None)
        recent = {row["status"]: row["recent"] or 0 for row in ended}
        last_hour = {row["status"]: row["total"] for row in hourly}
        durations = []
        for row in timed:
            try:
                durations.append(
                    (
                        datetime.fromisoformat(row["completed_at"])
                        - datetime.fromisoformat(row["started_at"])
                    ).total_seconds()
                )
            except ValueError:
                continue
        delay = 0.0
        if oldest:
            try:
                waited = datetime.fromisoformat(oldest)
                waited = waited if waited.tzinfo else waited.replace(tzinfo=UTC)
                delay = max(0.0, (datetime.now(UTC) - waited).total_seconds())
            except ValueError:
                delay = 0.0
        return {
            "queued": counts.get("queued", 0),
            "running": counts.get("running", 0),
            "done": recent.get("completed", 0),
            "failed": recent.get("failed", 0),
            "cancelled": recent.get("cancelled", 0),
            "done_hour": last_hour.get("completed", 0),
            "failed_hour": last_hour.get("failed", 0),
            "cancelled_hour": last_hour.get("cancelled", 0),
            "skipped_hour": last_hour.get("skipped", 0),
            "delay_seconds": round(delay, 1),
            "average_seconds": round(sum(durations) / len(durations), 3) if durations else None,
        }

    def claim_job(self, job_id: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE analysis_jobs
                SET status = 'running', started_at = ?
                WHERE job_id = ? AND status IN ('queued', 'scheduled', 'waiting_data')
                """,
                (self._now(), job_id),
            )
        return cursor.rowcount > 0

    def complete_job(
        self,
        job_id: str,
        *,
        results: list[dict[str, Any]],
        summary: dict[str, Any],
        config_snapshot: dict[str, Any],
        source_start: str | None,
        source_end: str | None,
    ) -> None:
        now = self._now()
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM analysis_job_results WHERE job_id = ?",
                (job_id,),
            )
            connection.executemany(
                """
                INSERT INTO analysis_job_results
                (job_id, method_id, result_json) VALUES (?, ?, ?)
                """,
                [(job_id, result["method_id"], self._json(result)) for result in results],
            )
            connection.execute(
                """
                UPDATE analysis_jobs
                SET status = 'completed', completed_at = ?,
                    config_snapshot_json = ?, summary_json = ?,
                    source_start = ?, source_end = ?, error_message = NULL
                WHERE job_id = ?
                """,
                (
                    now,
                    self._json(config_snapshot),
                    self._json(lean_summary(summary)),
                    source_start,
                    source_end,
                    job_id,
                ),
            )
        self._keep_samples([(job_id, summary)])

    def record_completed_jobs(self, entries: list[dict[str, Any]]) -> list[str]:
        """Write finished jobs in one transaction (baselines of a whole portfolio at once).

        Each entry has ``loop_id``, ``name``, ``kind``, ``profile_id``,
        ``method_config``, ``created_by``, ``range_start``, ``range_end``,
        ``results``, ``summary``, ``config_snapshot``, ``source_start`` and
        ``source_end``; the rows end as ``create_job`` + ``claim_job`` +
        ``complete_job`` would leave them.
        """

        now = self._now()
        jobs, results, ids = [], [], []
        for entry in entries:
            job_id = str(uuid.uuid4())
            ids.append(job_id)
            jobs.append(
                (
                    job_id,
                    entry["loop_id"],
                    entry["name"].strip() or t("Analysis of {subject}", subject=entry["loop_id"]),
                    entry["kind"],
                    now,
                    now,
                    now,
                    entry.get("range_start"),
                    entry.get("range_end"),
                    entry.get("profile_id"),
                    self._json(entry.get("method_config") or {}),
                    self._json(entry.get("config_snapshot") or {}),
                    self._json(lean_summary(entry.get("summary") or {})),
                    entry.get("source_start"),
                    entry.get("source_end"),
                    entry.get("created_by") or "Engineering",
                    entry.get("application_id") or "cpm",
                    entry.get("subject_kind") or "loop",
                )
            )
            results += [
                (job_id, result["method_id"], self._json(result))
                for result in entry.get("results") or []
            ]
        if not jobs:
            return ids
        with self._lock, self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO analysis_jobs
                (job_id, loop_id, name, kind, status, requested_at, started_at, completed_at,
                 range_start, range_end, profile_id, method_config_json, config_snapshot_json,
                 summary_json, source_start, source_end, created_by, application_id,
                 subject_kind)
                VALUES (?, ?, ?, ?, 'completed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                jobs,
            )
            connection.executemany(
                "INSERT INTO analysis_job_results (job_id, method_id, result_json) VALUES (?, ?, ?)",
                results,
            )
        self._keep_samples(list(zip(ids, [entry.get("summary") for entry in entries], strict=True)))
        return ids

    def fail_job(self, job_id: str, error: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE analysis_jobs
                SET status = 'failed', completed_at = ?, error_message = ?
                WHERE job_id = ?
                """,
                (self._now(), error, job_id),
            )

    def cancel_job(self, job_id: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE analysis_jobs SET status = 'cancelled', completed_at = ?
                WHERE job_id = ? AND status IN ('scheduled', 'queued', 'waiting_data')
                """,
                (self._now(), job_id),
            )
        return cursor.rowcount > 0

    def job_results(self, job_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT result_json FROM analysis_job_results
                WHERE job_id = ? ORDER BY method_id
                """,
                (job_id,),
            ).fetchall()
        results = [self._loads(row["result_json"], {}) for row in rows]
        for item in results:
            item["finding"] = describe_result(item)
        return results

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
            # The loops' round is "Control loop performance" (owner, 2026-10-27), also where it
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
                # No pile-up (owner, 2026-10-23): a subject whose previous occurrence has not
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
        """A schedule's record over its latest executions (owner, 2026-10-25, as Elipse EPM's
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
