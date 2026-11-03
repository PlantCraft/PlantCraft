"""The tables of the queue and the schedules, and their migrations."""

from __future__ import annotations

from linkcraft.db import Migration, add_columns

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
