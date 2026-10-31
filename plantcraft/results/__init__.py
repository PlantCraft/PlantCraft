"""What the apps of the suite publish about the plant and what they run (API v1).

- **Results**: the latest value an app computed about a subject (an asset or a
  signal), one row per (app, subject, kind), replaced on every write. Each change
  of ``status`` is also kept in a history for 90 days.
- **Runs**: an app's executions, one row per (app, run id), kept 90 days.
- **Schedules**: an app's list of schedules, replaced as a whole.

Events are the ``events`` module's. Rows here are written only through API v1
(``api/routers/v1_links.py``), which validates them; ``docs/app-standard.md``
(section 6) says what they are for. Times are stored as
``YYYY-MM-DDTHH:MM:SS+00:00`` so they sort as text.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from typing import Any

from plantcraft.db import Database, Migration, Store, add_columns, list_index


def _bool(value: Any) -> bool | None:
    return None if value is None else bool(value)


# Runs by subject (an asset's runs): app_run_subjects, kept by triggers (plantcraft.db.list_index).
_RUN_SUBJECTS, _FILL_RUN_SUBJECTS = list_index(
    "app_runs", ("app_id", "run_id"), "subjects_json", "app_run_subjects"
)


class ResultStore(Store):
    SCHEMA = (
        """
    CREATE TABLE IF NOT EXISTS app_results (
        app_id TEXT NOT NULL,
        subject TEXT NOT NULL,
        kind TEXT NOT NULL,
        status TEXT NOT NULL,
        score REAL,
        usable INTEGER,
        value REAL,
        summary TEXT NOT NULL DEFAULT '',
        detail_json TEXT NOT NULL DEFAULT '{}',
        at TEXT NOT NULL,
        expires_at TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (app_id, subject, kind)
    );

    CREATE INDEX IF NOT EXISTS idx_app_results_subject ON app_results(subject, kind);

    CREATE TABLE IF NOT EXISTS app_result_history (
        change_id INTEGER PRIMARY KEY AUTOINCREMENT,
        app_id TEXT NOT NULL,
        subject TEXT NOT NULL,
        kind TEXT NOT NULL,
        status TEXT NOT NULL,
        score REAL,
        usable INTEGER,
        value REAL,
        summary TEXT NOT NULL DEFAULT '',
        at TEXT NOT NULL,
        recorded_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_app_result_history_subject
        ON app_result_history(subject, at);
    CREATE INDEX IF NOT EXISTS idx_app_result_history_recorded
        ON app_result_history(recorded_at);

    CREATE TABLE IF NOT EXISTS app_runs (
        app_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL,
        trigger TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        subjects_json TEXT NOT NULL DEFAULT '[]',
        summary TEXT NOT NULL DEFAULT '',
        url TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (app_id, run_id)
    );

    CREATE INDEX IF NOT EXISTS idx_app_runs_updated ON app_runs(updated_at);

    CREATE TABLE IF NOT EXISTS app_schedules (
        app_id TEXT NOT NULL,
        schedule_id TEXT NOT NULL,
        position INTEGER NOT NULL DEFAULT 0,
        name TEXT NOT NULL DEFAULT '',
        cadence TEXT NOT NULL DEFAULT '',
        next_run TEXT,
        enabled INTEGER NOT NULL DEFAULT 1,
        url TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (app_id, schedule_id)
    );
    """
        + _RUN_SUBJECTS
    )

    # What each schedule runs on (API v1 ``subjects``, 2026-10-26).
    MIGRATIONS = (
        Migration(
            "schedule-subjects",
            add_columns("app_schedules", {"subjects_json": "TEXT NOT NULL DEFAULT '[]'"}),
        ),
        # Who started a run, how far it went and how to cancel it, for the suite's Queue
        # (docs/quick-access.md, 2026-10-26).
        Migration(
            "run-queue-fields",
            add_columns(
                "app_runs",
                {
                    "by_user": "TEXT",
                    "progress": "REAL",
                    "step": "TEXT NOT NULL DEFAULT ''",
                    "cancel_url": "TEXT",
                },
            ),
        ),
        # The side table of runs by subject, filled once from the runs already kept (2026-10-31).
        _FILL_RUN_SUBJECTS,
    )

    def __init__(self, db: Database):
        super().__init__(db)

    # Results ----------------------------------------------------------------

    @staticmethod
    def _result(row: Any) -> dict[str, Any]:
        item = dict(row)
        return {
            "app": item["app_id"],
            "subject": item["subject"],
            "kind": item["kind"],
            "status": item["status"],
            "score": item["score"],
            "usable": _bool(item["usable"]),
            "value": item["value"],
            "summary": item["summary"],
            "detail": Store._loads(item.get("detail_json"), {}),
            "at": item["at"],
            "expires_at": item["expires_at"],
            "updated_at": item["updated_at"],
        }

    def put_results(self, items: Iterable[dict[str, Any]], *, now: str, cutoff: str) -> int:
        """Write results (one per app, subject and kind); a changed status joins the history.

        ``items`` hold ``app, subject, kind, status, score, usable, value, summary,
        detail, at, expires_at``; history older than ``cutoff`` is dropped.
        """

        count = 0
        with self._lock, self._write() as connection:
            for item in items:
                key = (item["app"], item["subject"], item["kind"])
                previous = connection.execute(
                    "SELECT status FROM app_results WHERE app_id = ? AND subject = ? AND kind = ?",
                    key,
                ).fetchone()
                usable = None if item["usable"] is None else int(bool(item["usable"]))
                values = (
                    item["status"],
                    item["score"],
                    usable,
                    item["value"],
                    item["summary"],
                )
                connection.execute(
                    """
                    INSERT INTO app_results (app_id, subject, kind, status, score, usable, value,
                        summary, detail_json, at, expires_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (app_id, subject, kind) DO UPDATE SET
                        status = excluded.status, score = excluded.score,
                        usable = excluded.usable, value = excluded.value,
                        summary = excluded.summary, detail_json = excluded.detail_json,
                        at = excluded.at, expires_at = excluded.expires_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        *key,
                        *values,
                        self._json(item["detail"]),
                        item["at"],
                        item["expires_at"],
                        now,
                    ),
                )
                if previous is None or previous["status"] != item["status"]:
                    connection.execute(
                        """
                        INSERT INTO app_result_history (app_id, subject, kind, status, score,
                            usable, value, summary, at, recorded_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (*key, *values, item["at"], now),
                    )
                count += 1
            connection.execute("DELETE FROM app_result_history WHERE recorded_at < ?", (cutoff,))
        return count

    def results(
        self,
        *,
        subjects: list[str] | None = None,
        app: str | None = None,
        kind: str | None = None,
        limit: int = 5000,
        after: tuple[str, str, str] | None = None,
        apps: Collection[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Results about ``subjects`` (all when None), by subject, app and kind; ``after`` (a
        ``(subject, app, kind)`` already read) starts past it, for the next page. ``apps``
        keeps those of these apps (what a person reads)."""

        clauses, values = self._filters(app=app, kind=kind, apps=apps)
        if subjects is not None:
            if not subjects:
                return []
            clauses.append(f"subject IN ({','.join('?' for _ in subjects)})")
            values.extend(subjects)
        if after is not None:
            clauses.append("(subject, app_id, kind) > (?, ?, ?)")
            values.extend(after)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM app_results{where} ORDER BY subject, app_id, kind LIMIT ?",
                [*values, limit],
            ).fetchall()
        return [self._result(row) for row in rows]

    def not_ok(self, apps: list[str], ok: tuple[str, ...]) -> list[dict[str, Any]]:
        """Every result of ``apps`` whose status is not one of ``ok`` (what needs attention),
        uncut: a list cut at 5,000 by subject left out whatever sorted after the bench loops."""

        if not apps:
            return []
        marks = ",".join("?" for _ in apps)
        okays = ",".join("?" for _ in ok) or "''"
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM app_results WHERE app_id IN ({marks}) AND status NOT IN ({okays})",
                [*apps, *ok],
            ).fetchall()
        return [self._result(row) for row in rows]

    def status_counts(self, *, now: str | None = None) -> dict[str, dict[str, int]]:
        """Subjects per app by their worst current status (alarm, warning, unknown, ok): the
        home page. Results past ``expires_at`` (when ``now`` is given) are left out."""

        where, values = "", []
        if now:
            where, values = " WHERE expires_at IS NULL OR expires_at > ?", [now]
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT app_id, subject, MAX(CASE status WHEN 'alarm' THEN 3 WHEN 'warning' "
                "THEN 2 WHEN 'unknown' THEN 1 ELSE 0 END) AS worst "
                f"FROM app_results{where} GROUP BY app_id, subject",
                values,
            ).fetchall()
        names = {3: "alarm", 2: "warning", 1: "unknown", 0: "ok"}
        found: dict[str, dict[str, int]] = {}
        for row in rows:
            counts = found.setdefault(row["app_id"], {})
            status = names[int(row["worst"])]
            counts[status] = counts.get(status, 0) + 1
        return found

    def attention(self, *, now: str | None = None, limit: int = 8) -> list[dict[str, Any]]:
        """The current results that need someone (alarm first, then warning; lowest score first
        within each), across every app: the home page's list. Expired results are left out."""

        where = "status IN ('alarm', 'warning')"
        values: list[Any] = []
        if now:
            where += " AND (expires_at IS NULL OR expires_at > ?)"
            values.append(now)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM app_results WHERE {where} "
                "ORDER BY CASE status WHEN 'alarm' THEN 0 ELSE 1 END, "
                "COALESCE(score, 101), at DESC LIMIT ?",
                [*values, limit],
            ).fetchall()
        return [self._result(row) for row in rows]

    def history(
        self,
        subject: str,
        *,
        app: str | None = None,
        kind: str | None = None,
        after: str | None = None,
        limit: int = 100,
        apps: Collection[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Status changes of results about ``subject``, oldest first, ``at`` after ``after``."""

        clauses, values = self._filters(app=app, kind=kind, apps=apps)
        clauses.append("subject = ?")
        values.append(subject)
        if after:
            clauses.append("at > ?")
            values.append(after)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM app_result_history WHERE {' AND '.join(clauses)} "
                "ORDER BY at, change_id LIMIT ?",
                [*values, limit],
            ).fetchall()
        return [
            {
                "app": row["app_id"],
                "subject": row["subject"],
                "kind": row["kind"],
                "status": row["status"],
                "score": row["score"],
                "usable": _bool(row["usable"]),
                "value": row["value"],
                "summary": row["summary"],
                "at": row["at"],
            }
            for row in rows
        ]

    @staticmethod
    def _filters(
        apps: Collection[str] | None = None, **fields: str | None
    ) -> tuple[list[str], list[Any]]:
        columns = {"app": "app_id", "kind": "kind", "status": "status"}
        clauses, values = [], []
        for name, value in fields.items():
            if value is not None:
                clauses.append(f"{columns[name]} = ?")
                values.append(value)
        if apps is not None:
            clauses.append(f"app_id IN ({','.join('?' for _ in apps) or 'NULL'})")
            values.extend(sorted(apps))
        return clauses, values

    # Runs -------------------------------------------------------------------

    @staticmethod
    def _run(row: Any) -> dict[str, Any]:
        return {
            "app": row["app_id"],
            "id": row["run_id"],
            "name": row["name"],
            "status": row["status"],
            "trigger": row["trigger"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "subjects": Store._loads(row["subjects_json"], []),
            "summary": row["summary"],
            "url": row["url"],
            "by": row["by_user"],
            "progress": row["progress"],
            "step": row["step"],
            "cancel": row["cancel_url"],
            "updated_at": row["updated_at"],
        }

    def put_runs(self, items: Iterable[dict[str, Any]], *, now: str, cutoff: str) -> int:
        """Write runs (one per app and run id); runs not updated since ``cutoff`` are dropped."""

        count = 0
        with self._lock, self._write() as connection:
            for item in items:
                connection.execute(
                    """
                    INSERT INTO app_runs (app_id, run_id, name, status, trigger, started_at,
                        finished_at, subjects_json, summary, url, by_user, progress, step,
                        cancel_url, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (app_id, run_id) DO UPDATE SET
                        name = excluded.name, status = excluded.status,
                        trigger = excluded.trigger, started_at = excluded.started_at,
                        finished_at = excluded.finished_at,
                        subjects_json = excluded.subjects_json, summary = excluded.summary,
                        url = excluded.url, by_user = excluded.by_user,
                        progress = excluded.progress, step = excluded.step,
                        cancel_url = excluded.cancel_url, updated_at = excluded.updated_at
                    """,
                    (
                        item["app"],
                        item["id"],
                        item["name"],
                        item["status"],
                        item["trigger"],
                        item["started_at"],
                        item["finished_at"],
                        self._json(item["subjects"]),
                        item["summary"],
                        item["url"],
                        item.get("by"),
                        item.get("progress"),
                        item.get("step") or "",
                        item.get("cancel"),
                        now,
                    ),
                )
                count += 1
            connection.execute("DELETE FROM app_runs WHERE updated_at < ?", (cutoff,))
        return count

    def runs(
        self,
        *,
        app: str | None = None,
        status: str | None = None,
        subject: str | None = None,
        by: str | None = None,
        limit: int = 100,
        apps: Collection[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Runs, newest first (by start, else by last update)."""

        clauses, values = self._filters(app=app, status=status, apps=apps)
        if by is not None:
            clauses.append("by_user = ?")
            values.append(by)
        if subject is not None:
            clauses.append(
                "(app_id, run_id) IN (SELECT app_id, run_id FROM app_run_subjects WHERE subject = ?)"
            )
            values.append(subject)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM app_runs{where} "
                "ORDER BY COALESCE(started_at, updated_at) DESC, app_id, run_id LIMIT ?",
                [*values, limit],
            ).fetchall()
        return [self._run(row) for row in rows]

    def run(self, app: str, run_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM app_runs WHERE app_id = ? AND run_id = ?", (app, run_id)
            ).fetchone()
        return self._run(row) if row else None

    # Renamed subjects ---------------------------------------------------------

    def signal_subjects(self) -> list[str]:
        """Every ``signal:`` subject stored in results, their history and runs."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT subject FROM app_results WHERE subject LIKE 'signal:%'
                UNION SELECT subject FROM app_result_history WHERE subject LIKE 'signal:%'
                UNION SELECT value FROM app_runs, json_each(
                    CASE WHEN json_valid(app_runs.subjects_json)
                         THEN app_runs.subjects_json ELSE '[]' END)
                    WHERE value LIKE 'signal:%'
                """
            ).fetchall()
        return sorted(row[0] for row in rows if isinstance(row[0], str))

    def rename_subjects(self, mapping: dict[str, str]) -> dict[str, int]:
        """Subjects renamed (``old -> new``) in results, their history and runs' subjects.

        A result whose new name is already taken keeps its old one. Counts the rows changed.
        """

        counts = {"results": 0, "result_history": 0, "runs": 0}
        if not mapping:
            return counts
        with self._lock, self._write() as connection:
            for old, new in mapping.items():
                counts["results"] += connection.execute(
                    "UPDATE OR IGNORE app_results SET subject = ? WHERE subject = ?", (new, old)
                ).rowcount
                counts["result_history"] += connection.execute(
                    "UPDATE app_result_history SET subject = ? WHERE subject = ?", (new, old)
                ).rowcount
            rows = connection.execute(
                "SELECT app_id, run_id, subjects_json FROM app_runs WHERE subjects_json LIKE ?",
                ("%signal:%",),
            ).fetchall()
            for row in rows:
                subjects = self._loads(row["subjects_json"], [])
                if not isinstance(subjects, list):
                    continue
                renamed = list(
                    dict.fromkeys(
                        mapping.get(item, item) if isinstance(item, str) else item
                        for item in subjects
                    )
                )
                if renamed != subjects:
                    connection.execute(
                        "UPDATE app_runs SET subjects_json = ? WHERE app_id = ? AND run_id = ?",
                        (self._json(renamed), row["app_id"], row["run_id"]),
                    )
                    counts["runs"] += 1
        return counts

    # Schedules --------------------------------------------------------------

    def replace_schedules(self, app: str, items: list[dict[str, Any]], *, now: str) -> int:
        """The app's schedules become ``items`` (in that order)."""

        with self._lock, self._write() as connection:
            connection.execute("DELETE FROM app_schedules WHERE app_id = ?", (app,))
            connection.executemany(
                """
                INSERT INTO app_schedules (app_id, schedule_id, position, name, cadence,
                    next_run, enabled, url, subjects_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        app,
                        item["id"],
                        position,
                        item["name"],
                        item["cadence"],
                        item["next_run"],
                        int(bool(item["enabled"])),
                        item["url"],
                        self._json(list(item.get("subjects") or [])),
                        now,
                    )
                    for position, item in enumerate(items)
                ],
            )
        return len(items)

    def schedules(
        self, *, app: str | None = None, apps: Collection[str] | None = None
    ) -> list[dict[str, Any]]:
        clauses, values = self._filters(app=app, apps=apps)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM app_schedules{where} ORDER BY app_id, position", values
            ).fetchall()
        return [
            {
                "app": row["app_id"],
                "id": row["schedule_id"],
                "name": row["name"],
                "cadence": row["cadence"],
                "next_run": row["next_run"],
                "enabled": bool(row["enabled"]),
                "url": row["url"],
                "subjects": Store._loads(row["subjects_json"], []),
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]


__all__ = ["ResultStore"]
