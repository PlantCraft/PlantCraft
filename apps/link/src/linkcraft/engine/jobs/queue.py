"""The queue: who runs next, progress, and how an execution ends."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from plantcraft_sdk.utc import utc_iso

from linkcraft.catalog.registry import describe_result
from linkcraft.engine.jobs.common import lean_summary
from linkcraft.i18n import t


class JobQueue:
    """The queue: claim, requeue, progress, finish, fail and cancel executions."""

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
