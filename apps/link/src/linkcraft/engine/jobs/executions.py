"""The executions (rows of ``analysis_jobs``): create, read, list, count and prune them."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from plantcraft_sdk.utc import utc_iso

from linkcraft.engine.jobs.common import PRIORITIES, lean_summary
from linkcraft.engine.samples import ROUND_SCOPE
from linkcraft.i18n import t


class ExecutionRecords:
    """The executions themselves: create, read, list, count and prune them."""

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
        (the long history is in the Historian). Runs thinned."""

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

    def running_count(self) -> int:
        """Executions running now (in any process)."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM analysis_jobs WHERE status = 'running'"
            ).fetchone()
        return int(row[0])
