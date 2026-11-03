"""Analysis jobs, their results and recurring schedules.

The queue is one store, ``JobStore``, written in parts: ``executions`` (the rows), ``queue``
(claiming and ending them), ``schedules`` (what queues them), ``schema`` and ``common``."""

from __future__ import annotations

from typing import Any

from linkcraft.db import Store
from linkcraft.engine.jobs import schema
from linkcraft.engine.jobs.common import (
    DEFAULT_RETRY,
    JOB_KINDS,
    JOB_STATUSES,
    OPEN_STATUSES,
    OUTPUT_KEY_LENGTH,
    PRIORITIES,
    RENAMED_ROUNDS,
    SCHEDULE_CADENCES,
    WORKS,
    lean_summary,
    output_key_of,
)
from linkcraft.engine.jobs.executions import ExecutionRecords
from linkcraft.engine.jobs.queue import JobQueue
from linkcraft.engine.jobs.schedules import ScheduleRecords, schedule_work
from linkcraft.engine.samples import RunSampleStore

__all__ = [
    "DEFAULT_RETRY",
    "JOB_KINDS",
    "JOB_STATUSES",
    "OPEN_STATUSES",
    "OUTPUT_KEY_LENGTH",
    "PRIORITIES",
    "RENAMED_ROUNDS",
    "SCHEDULE_CADENCES",
    "WORKS",
    "JobStore",
    "lean_summary",
    "output_key_of",
    "schedule_work",
]


class JobStore(ExecutionRecords, JobQueue, ScheduleRecords, Store):
    """Queue of analysis jobs and the schedules that materialize them."""

    SCHEMA = schema.SCHEMA
    MIGRATIONS = schema.MIGRATIONS

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
