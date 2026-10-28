"""Runs: every simulation and every FMU export, with what it was asked and what it answered.

A run keeps a copy of the project's files as they were when it started (``files.json`` in its
folder), so its results always match the model that made them, even after the text changed.
Results (the variables' values) and FMUs live in ``<data>/runs/<run id>/``.

Every simulation belongs to a study (``studies``): what a person wants to learn from a model,
either a single simulation or a sweep of parameter values (one simulation per combination). A
quick simulation from the workbench goes to the model's "Quick simulations" study. FMU exports
belong to no study. Runs wait in the queue (``status = 'queued'``) until the dispatcher
(``runs/queue.py``) hands them to the runner, the highest ``priority`` first.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from plantcraft_sdk.server.store import Migration, Store, add_columns

from modelcraft.runs.models import (
    STATUSES,
)

PRIORITY_SINGLE = 10
PRIORITY_SWEEP = 0


def _parse_stamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class RunStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS runs (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        project_name TEXT NOT NULL DEFAULT '',
        model TEXT NOT NULL,
        kind TEXT NOT NULL,
        status TEXT NOT NULL,
        options_json TEXT NOT NULL DEFAULT '{}',
        messages_json TEXT NOT NULL DEFAULT '[]',
        result_json TEXT NOT NULL DEFAULT '{}',
        summary TEXT NOT NULL DEFAULT '',
        seconds REAL,
        label TEXT NOT NULL DEFAULT '',
        created_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT
    );
    CREATE INDEX IF NOT EXISTS runs_project ON runs (project_id, created_at);
    CREATE TABLE IF NOT EXISTS studies (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        project_name TEXT NOT NULL DEFAULT '',
        model TEXT NOT NULL,
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        spec_json TEXT NOT NULL DEFAULT '{}',
        created_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS studies_project ON studies (project_id, created_at);
    """
    # Columns added after the first release: (name, declaration), one migration step.
    ADDED = (
        ("study_id", "TEXT NOT NULL DEFAULT ''"),
        ("variant_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("priority", "INTEGER NOT NULL DEFAULT 0"),
        ("job_id", "TEXT NOT NULL DEFAULT ''"),
    )
    MIGRATIONS = (Migration("columns-before-0.5", add_columns("runs", dict(ADDED))),)
    FIELDS = {
        "options": ("options_json", {}),
        "messages": ("messages_json", []),
        "result": ("result_json", {}),
        "variant": ("variant_json", {}),
    }
    STUDY_FIELDS = {"spec": ("spec_json", {})}

    def __init__(self, db):
        super().__init__(db)
        with self._lock, self._connect() as connection:
            connection.execute(
                "CREATE INDEX IF NOT EXISTS runs_queue ON runs (status, priority, created_at)"
            )
            connection.execute("CREATE INDEX IF NOT EXISTS runs_study ON runs (study_id)")

    def create(
        self,
        *,
        project: dict[str, Any],
        model: str,
        kind: str,
        options: dict[str, Any],
        by: str,
        label: str = "",
        study_id: str = "",
        variant: dict[str, Any] | None = None,
        priority: int = PRIORITY_SINGLE,
    ) -> dict[str, Any]:
        return self.create_many(
            project=project,
            model=model,
            kind=kind,
            options=options,
            by=by,
            labels=[label],
            study_id=study_id,
            variants=[variant or {}],
            priority=priority,
        )[0]

    def create_many(
        self,
        *,
        project: dict[str, Any],
        model: str,
        kind: str,
        options: dict[str, Any],
        by: str,
        labels: list[str],
        study_id: str = "",
        variants: list[dict[str, Any]],
        priority: int = PRIORITY_SINGLE,
    ) -> list[dict[str, Any]]:
        ids = [f"{kind[:3]}-{uuid.uuid4().hex[:10]}" for _ in variants]
        now = self._now()
        with self._lock, self._connect() as connection:
            connection.executemany(
                "INSERT INTO runs (id, project_id, project_name, model, kind, status, options_json, "
                "label, created_by, created_at, study_id, variant_json, priority) "
                "VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        project["id"],
                        project["name"],
                        model,
                        kind,
                        self._json(options),
                        label[:120],
                        by,
                        now,
                        study_id,
                        self._json(variant),
                        priority,
                    )
                    for run_id, label, variant in zip(ids, labels, variants, strict=True)
                ],
            )
        return [self.get(run_id) for run_id in ids]  # type: ignore[misc]

    def get(self, run_id: str) -> dict[str, Any] | None:
        if not run_id or len(run_id) > 40:
            return None
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return self._row_with_json(row, self.FIELDS) if row else None

    def list(
        self,
        *,
        project_id: str | None = None,
        model: str | None = None,
        kind: str | None = None,
        study_id: str | None = None,
        statuses: tuple[str, ...] | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM runs WHERE 1 = 1"
        params: list[Any] = []
        if study_id:
            query += " AND study_id = ?"
            params.append(study_id)
        if statuses:
            query += f" AND status IN ({', '.join('?' for _ in statuses)})"
            params.extend(statuses)
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        if model:
            query += " AND model = ?"
            params.append(model)
        if kind:
            query += " AND kind = ?"
            params.append(kind)
        query += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        params.append(max(1, min(limit, 5000)))
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._row_with_json(row, self.FIELDS) for row in rows]

    def started(self, run_ids: list[str], job_id: str = "") -> None:
        now = self._now()
        with self._lock, self._connect() as connection:
            connection.executemany(
                "UPDATE runs SET status = 'running', started_at = ?, job_id = ? "
                "WHERE id = ? AND status = 'queued'",
                [(now, job_id, run_id) for run_id in run_ids],
            )

    def next_batch(self, size: int, exclude: set[str]) -> list[dict[str, Any]]:
        """The next runs to hand to the runner: the oldest queued run of the highest priority,
        and with it up to ``size`` queued runs of the same sweep (built once)."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM runs WHERE status = 'queued' ORDER BY priority DESC, created_at, rowid "
                "LIMIT 200"
            ).fetchall()
        first = next((row for row in rows if row["id"] not in exclude), None)
        if first is None:
            return []
        if not first["study_id"] or first["priority"] != PRIORITY_SWEEP:
            return [self._row_with_json(first, self.FIELDS)]
        same = [
            row
            for row in rows
            if row["study_id"] == first["study_id"]
            and row["priority"] == PRIORITY_SWEEP
            and row["id"] not in exclude
        ]
        return [self._row_with_json(row, self.FIELDS) for row in same[: max(1, size)]]

    def requeue(self, run_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE runs SET status = 'queued', started_at = NULL, job_id = '' WHERE id = ?",
                (run_id,),
            )

    def cancel_queued(self, *, run_id: str | None = None, study_id: str | None = None) -> int:
        """Cancel runs still waiting; running ones are stopped by the dispatcher."""

        query, params = (
            "UPDATE runs SET status = 'cancelled', summary = ?, finished_at = ? WHERE status = 'queued'",
            [
                "Cancelled.",
                self._now(),
            ],
        )
        if run_id:
            query += " AND id = ?"
            params.append(run_id)
        if study_id:
            query += " AND study_id = ?"
            params.append(study_id)
        with self._lock, self._connect() as connection:
            return connection.execute(query, params).rowcount

    def project_counts(self) -> dict[str, dict[str, int]]:
        with self._connect() as connection:
            runs = connection.execute(
                "SELECT project_id, SUM(kind = 'simulate') AS simulations, SUM(kind = 'fmu') AS exports "
                "FROM runs GROUP BY project_id"
            ).fetchall()
            studies = connection.execute(
                "SELECT project_id, SUM(kind != 'quick') AS studies FROM studies GROUP BY project_id"
            ).fetchall()
        found: dict[str, dict[str, int]] = {}
        for row in runs:
            found[row["project_id"]] = {
                "simulations": int(row["simulations"] or 0),
                "exports": int(row["exports"] or 0),
            }
        for row in studies:
            found.setdefault(row["project_id"], {})["studies"] = int(row["studies"] or 0)
        return found

    def queue_counts(self, since: str, hour: str) -> dict[str, Any]:
        """The queue's numbers for the suite's queue panel: waiting and running now, finished
        since ``since`` and in the last hour (from ``hour``), the oldest wait and the mean run
        time of those done since ``since``."""

        with self._connect() as connection:
            now = {
                row["status"]: row["n"]
                for row in connection.execute(
                    "SELECT status, COUNT(*) AS n FROM runs WHERE status IN ('queued', 'running') "
                    "GROUP BY status"
                )
            }
            finished = connection.execute(
                "SELECT "
                "SUM(status = 'done' AND finished_at >= :since) AS done, "
                "SUM(status = 'failed' AND finished_at >= :since) AS failed, "
                "SUM(status = 'cancelled' AND finished_at >= :since) AS cancelled, "
                "SUM(status = 'done') AS done_hour, SUM(status = 'failed') AS failed_hour, "
                "SUM(status = 'cancelled') AS cancelled_hour, "
                "AVG(CASE WHEN status = 'done' AND finished_at >= :since THEN seconds END) AS average "
                "FROM runs WHERE finished_at >= :hour",
                {"since": since, "hour": hour},
            ).fetchone()
            oldest = connection.execute(
                "SELECT MIN(created_at) AS at FROM runs WHERE status = 'queued'"
            ).fetchone()["at"]
        delay = 0.0
        if oldest:
            delay = max(0.0, (_parse_stamp(self._now()) - _parse_stamp(oldest)).total_seconds())
        return {
            "queued": int(now.get("queued", 0)),
            "running": int(now.get("running", 0)),
            "done": int(finished["done"] or 0),
            "failed": int(finished["failed"] or 0),
            "cancelled": int(finished["cancelled"] or 0),
            "done_hour": int(finished["done_hour"] or 0),
            "failed_hour": int(finished["failed_hour"] or 0),
            "cancelled_hour": int(finished["cancelled_hour"] or 0),
            "delay_seconds": delay,
            "average_seconds": float(finished["average"])
            if finished["average"] is not None
            else None,
        }

    def simulations_since(self, since: str) -> list[dict[str, Any]]:
        """The simulations started since ``since`` (an ISO instant): their status, when they
        started and their options (whose plant signals say who sees them), the newest first."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, status, created_at, options_json FROM runs "
                "WHERE kind = 'simulate' AND created_at >= ? ORDER BY created_at DESC",
                (since,),
            ).fetchall()
        return [self._row_with_json(row, {"options": self.FIELDS["options"]}) for row in rows]

    def counts(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS n FROM runs WHERE kind = 'simulate' GROUP BY status"
            ).fetchall()
        return {row["status"]: row["n"] for row in rows}

    def finished(
        self,
        run_id: str,
        *,
        status: str,
        messages: list[dict[str, Any]],
        result: dict[str, Any],
        summary: str,
        seconds: float | None,
    ) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE runs SET status = ?, messages_json = ?, result_json = ?, summary = ?, seconds = ?, "
                "finished_at = ?, job_id = '' WHERE id = ?",
                (
                    status,
                    self._json(messages),
                    self._json(result),
                    summary[:300],
                    seconds,
                    self._now(),
                    run_id,
                ),
            )
        return self.get(run_id)  # type: ignore[return-value]

    def set_label(self, run_id: str, label: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            connection.execute("UPDATE runs SET label = ? WHERE id = ?", (label[:120], run_id))
        return self.get(run_id)

    def delete(self, run_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM runs WHERE id = ?", (run_id,))

    def interrupted(self) -> int:
        """Runs a stopped server left running wait in the queue again at the next start (their
        files are kept in their folder); FMU exports a restart stopped are marked failed."""

        with self._lock, self._connect() as connection:
            failed = connection.execute(
                "UPDATE runs SET status = 'failed', summary = 'Stopped: the server restarted during the run.', "
                "finished_at = ? WHERE status IN ('queued', 'running') AND kind = 'fmu'",
                (self._now(),),
            ).rowcount
            again = connection.execute(
                "UPDATE runs SET status = 'queued', started_at = NULL, job_id = '' "
                "WHERE status = 'running' AND kind = 'simulate'"
            ).rowcount
        return failed + again

    # Studies -------------------------------------------------------------------------------

    def create_study(
        self,
        *,
        project: dict[str, Any],
        model: str,
        name: str,
        kind: str,
        spec: dict[str, Any],
        by: str,
        description: str = "",
    ) -> dict[str, Any]:
        study_id = f"stu-{uuid.uuid4().hex[:10]}"
        now = self._now()
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO studies (id, project_id, project_name, model, name, kind, description, "
                "spec_json, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    study_id,
                    project["id"],
                    project["name"],
                    model,
                    name[:120],
                    kind,
                    description[:2000],
                    self._json(spec),
                    by,
                    now,
                    now,
                ),
            )
        return self.study(study_id)  # type: ignore[return-value]

    def quick_study(self, project: dict[str, Any], model: str, *, by: str) -> dict[str, Any]:
        """The model's "Quick simulations" study (made the first time it is needed)."""

        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT id FROM studies WHERE project_id = ? AND model = ? AND kind = 'quick'",
                    (project["id"], model),
                ).fetchone()
            if row:
                return self.study(row["id"])  # type: ignore[return-value]
            return self.create_study(
                project=project,
                model=model,
                name=f"Quick simulations of {model.rpartition('.')[2]}",
                kind="quick",
                spec={},
                by=by,
            )

    def study(self, study_id: str) -> dict[str, Any] | None:
        if not study_id or len(study_id) > 40:
            return None
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM studies WHERE id = ?", (study_id,)).fetchone()
        return self._study(row) if row else None

    def studies(
        self, *, project_id: str | None = None, model: str | None = None
    ) -> list[dict[str, Any]]:
        query = (
            "SELECT s.*, "
            "SUM(r.status = 'queued') AS queued, SUM(r.status = 'running') AS running, "
            "SUM(r.status = 'done') AS done, SUM(r.status = 'failed') AS failed, "
            "SUM(r.status = 'cancelled') AS cancelled, COUNT(r.id) AS total, "
            "MAX(r.created_at) AS last_run_at "
            "FROM studies s LEFT JOIN runs r ON r.study_id = s.id WHERE 1 = 1"
        )
        params: list[Any] = []
        if project_id:
            query += " AND s.project_id = ?"
            params.append(project_id)
        if model:
            query += " AND s.model = ?"
            params.append(model)
        query += " GROUP BY s.id ORDER BY COALESCE(MAX(r.created_at), s.created_at) DESC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._study(row) for row in rows]

    def _study(self, row) -> dict[str, Any]:
        item = self._row_with_json(row, self.STUDY_FIELDS)
        for key in ("queued", "running", "done", "failed", "cancelled", "total"):
            item[key] = int(item.get(key) or 0)
        return item

    def study_names(self, study_ids: set[str]) -> dict[str, dict[str, str]]:
        """The name and kind of each of these studies, by id."""

        ids = [item for item in study_ids if item][:5000]
        if not ids:
            return {}
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT id, name, kind FROM studies WHERE id IN ({', '.join('?' for _ in ids)})",
                ids,
            ).fetchall()
        return {
            row["id"]: {"id": row["id"], "name": row["name"], "kind": row["kind"]} for row in rows
        }

    def study_counts(self, study_id: str) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS n FROM runs WHERE study_id = ? GROUP BY status",
                (study_id,),
            ).fetchall()
        counts = {status: 0 for status in STATUSES}
        counts.update({row["status"]: row["n"] for row in rows})
        counts["total"] = sum(counts[status] for status in STATUSES)
        return counts

    def rename_study(self, study_id: str, name: str, description: str | None) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE studies SET name = ?, description = COALESCE(?, description), updated_at = ? "
                "WHERE id = ?",
                (name[:120], description, self._now(), study_id),
            )

    def delete_study(self, study_id: str) -> list[str]:
        """Delete the study and its runs; the ids of the runs (their folders go too)."""

        with self._lock, self._connect() as connection:
            ids = [
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM runs WHERE study_id = ?", (study_id,)
                ).fetchall()
            ]
            connection.execute("DELETE FROM runs WHERE study_id = ?", (study_id,))
            connection.execute("DELETE FROM studies WHERE id = ?", (study_id,))
        return ids

    def adopt_loose_runs(self) -> int:
        """Simulations made before studies existed join their model's "Quick simulations"."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT project_id, project_name, model, created_by FROM runs "
                "WHERE kind = 'simulate' AND study_id = ''"
            ).fetchall()
        moved = 0
        for row in rows:
            study = self.quick_study(
                {"id": row["project_id"], "name": row["project_name"]},
                row["model"],
                by=row["created_by"],
            )
            with self._lock, self._connect() as connection:
                moved += connection.execute(
                    "UPDATE runs SET study_id = ? WHERE kind = 'simulate' AND study_id = '' "
                    "AND project_id = ? AND model = ?",
                    (study["id"], row["project_id"], row["model"]),
                ).rowcount
        return moved
