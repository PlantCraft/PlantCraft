"""The latest analysis of every subject (loop, signal...) and a compact health history.

The monitoring round writes here instead of keeping the whole portfolio in
memory, so lists and panels read one indexed table whatever the number of
subjects, and a restarted server shows the last round at once.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from plantcraft_sdk.utc import utc_iso

from linkcraft.db import Store


class LatestStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS subject_latest (
        application_id TEXT NOT NULL,
        subject_kind TEXT NOT NULL,
        subject_id TEXT NOT NULL,
        status TEXT,
        health REAL,
        priority REAL,
        summary_json TEXT NOT NULL,
        results_json TEXT NOT NULL,
        source_start TEXT,
        source_end TEXT,
        analyzed_at TEXT NOT NULL,
        PRIMARY KEY (application_id, subject_kind, subject_id)
    );

    CREATE INDEX IF NOT EXISTS idx_subject_latest_status
    ON subject_latest(application_id, subject_kind, status);

    -- Counts the writes to subject_latest, from any process: the readers' cache stamp
    -- (``version``) without reading every summary.
    CREATE TABLE IF NOT EXISTS subject_latest_writes (id INTEGER PRIMARY KEY, n INTEGER NOT NULL);
    INSERT OR IGNORE INTO subject_latest_writes (id, n) VALUES (1, 0);
    CREATE TRIGGER IF NOT EXISTS subject_latest_inserted AFTER INSERT ON subject_latest
    BEGIN UPDATE subject_latest_writes SET n = n + 1 WHERE id = 1; END;
    CREATE TRIGGER IF NOT EXISTS subject_latest_updated AFTER UPDATE ON subject_latest
    BEGIN UPDATE subject_latest_writes SET n = n + 1 WHERE id = 1; END;
    CREATE TRIGGER IF NOT EXISTS subject_latest_deleted AFTER DELETE ON subject_latest
    BEGIN UPDATE subject_latest_writes SET n = n + 1 WHERE id = 1; END;

    CREATE TABLE IF NOT EXISTS subject_health (
        application_id TEXT NOT NULL,
        subject_kind TEXT NOT NULL,
        subject_id TEXT NOT NULL,
        source_end TEXT NOT NULL,
        status TEXT,
        health REAL,
        PRIMARY KEY (application_id, subject_kind, subject_id, source_end)
    );

    CREATE INDEX IF NOT EXISTS idx_subject_health_time
    ON subject_health(application_id, subject_kind, source_end);

    -- Each subject's mean health and last status of a closed day (UTC), kept once the day is
    -- over: the week of the Analytics home reads closed days here, the open edges in
    -- subject_health (2,000 loops every 10 minutes are 2 million rows a week).
    CREATE TABLE IF NOT EXISTS subject_health_days (
        application_id TEXT NOT NULL,
        subject_kind TEXT NOT NULL,
        day TEXT NOT NULL,
        subject_id TEXT NOT NULL,
        health REAL,
        status TEXT,
        PRIMARY KEY (application_id, subject_kind, day, subject_id)
    );
    CREATE TABLE IF NOT EXISTS subject_health_days_done (
        application_id TEXT NOT NULL,
        subject_kind TEXT NOT NULL,
        day TEXT NOT NULL,
        PRIMARY KEY (application_id, subject_kind, day)
    );
    """

    # Bumped on every write here, so readers can cache what they build from the table.
    writes = 0

    @property
    def version(self) -> tuple[Any, ...]:
        """Changes on every write, also one by the engine in its own process (``engine.process``):
        this process's writes and what the table holds."""

        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT n FROM subject_latest_writes WHERE id = 1").fetchone()
        return (self.writes, *tuple(row))

    def save_many(self, application_id: str, subject_kind: str, rows: list[dict[str, Any]]) -> None:
        """Replace the latest analysis of each subject; append its health point."""

        now = self._now()
        latest = [
            (
                application_id,
                subject_kind,
                row["subject_id"],
                row.get("status"),
                row.get("health"),
                row.get("priority"),
                self._json(row.get("summary") or {}),
                self._json(row.get("results") or []),
                row.get("source_start"),
                row.get("source_end"),
                now,
            )
            for row in rows
        ]
        history = [
            (
                application_id,
                subject_kind,
                row["subject_id"],
                row["source_end"],
                row.get("status"),
                row.get("health"),
            )
            for row in rows
            if row.get("source_end")
        ]
        with self._lock, self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO subject_latest
                (application_id, subject_kind, subject_id, status, health, priority,
                 summary_json, results_json, source_start, source_end, analyzed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(application_id, subject_kind, subject_id) DO UPDATE SET
                    status = excluded.status, health = excluded.health,
                    priority = excluded.priority, summary_json = excluded.summary_json,
                    results_json = excluded.results_json, source_start = excluded.source_start,
                    source_end = excluded.source_end, analyzed_at = excluded.analyzed_at
                """,
                latest,
            )
            connection.executemany(
                """
                INSERT OR REPLACE INTO subject_health
                (application_id, subject_kind, subject_id, source_end, status, health)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                history,
            )
            _forget_days(connection, application_id, subject_kind, {row[3] for row in history})
        self.writes += 1

    def forget_missing(self, application_id: str, subject_kind: str, keep: list[str]) -> None:
        """Drop subjects that no longer exist (a loop removed, a tag unconfigured)."""

        with self._lock, self._connect() as connection:
            current = {
                row[0]
                for row in connection.execute(
                    "SELECT subject_id FROM subject_latest WHERE application_id = ? AND subject_kind = ?",
                    (application_id, subject_kind),
                )
            }
            gone = sorted(current - set(keep))
            connection.executemany(
                "DELETE FROM subject_latest WHERE application_id = ? AND subject_kind = ? AND subject_id = ?",
                [(application_id, subject_kind, subject_id) for subject_id in gone],
            )
        self.writes += 1

    def get(self, application_id: str, subject_kind: str, subject_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM subject_latest
                WHERE application_id = ? AND subject_kind = ? AND subject_id = ?
                """,
                (application_id, subject_kind, subject_id),
            ).fetchone()
        return self._row(row, results=True) if row else None

    def summaries(self, application_id: str, subject_kind: str) -> dict[str, dict[str, Any]]:
        """subject_id -> latest summary, for every subject (no method results: cheap)."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT subject_id, status, health, priority, summary_json,
                       source_start, source_end, analyzed_at
                FROM subject_latest WHERE application_id = ? AND subject_kind = ?
                """,
                (application_id, subject_kind),
            ).fetchall()
        return {row["subject_id"]: self._row(row) for row in rows}

    def results(self, application_id: str, subject_kind: str) -> dict[str, list[dict[str, Any]]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT subject_id, results_json FROM subject_latest
                WHERE application_id = ? AND subject_kind = ?
                """,
                (application_id, subject_kind),
            ).fetchall()
        return {row["subject_id"]: self._loads(row["results_json"], []) for row in rows}

    def count(self, application_id: str, subject_kind: str) -> int:
        with self._lock, self._connect() as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM subject_latest WHERE application_id = ? AND subject_kind = ?",
                    (application_id, subject_kind),
                ).fetchone()[0]
            )

    def status_counts(self, application_id: str, subject_kind: str) -> dict[str, int]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT COALESCE(status, 'sem_dados') AS status, COUNT(*) AS total
                FROM subject_latest WHERE application_id = ? AND subject_kind = ?
                GROUP BY status
                """,
                (application_id, subject_kind),
            ).fetchall()
        return {row["status"]: int(row["total"]) for row in rows}

    def history(
        self, application_id: str, subject_kind: str, subject_id: str, *, days: float = 30
    ) -> list[dict[str, Any]]:
        since = utc_iso(datetime.now(UTC) - timedelta(days=days))
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT source_end, status, health FROM subject_health
                WHERE application_id = ? AND subject_kind = ? AND subject_id = ?
                  AND source_end >= ?
                ORDER BY source_end
                """,
                (application_id, subject_kind, subject_id, since),
            ).fetchall()
        return [dict(row) for row in rows]

    def statuses_between(
        self, application_id: str, subject_kind: str, start: str, end: str
    ) -> dict[str, str | None]:
        """subject_id -> the status of its last health point in ``[start, end)`` (stored
        format): how each subject ended a day. One indexed read, whatever the subjects."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT subject_id, status, MAX(source_end) FROM subject_health
                WHERE application_id = ? AND subject_kind = ? AND source_end >= ? AND source_end < ?
                GROUP BY subject_id
                """,
                (application_id, subject_kind, start, end),
            ).fetchall()
        return {row[0]: row[1] for row in rows}

    def health_buckets(
        self, application_id: str, subject_kind: str, start: str, end: str, bucket_seconds: int
    ) -> list[dict[str, Any]]:
        """Mean health and last status of every subject per time bucket (epoch seconds).

        ``start``/``end`` are in the stored ``source_end`` format; the grouping
        runs in SQLite, so a month of rounds over thousands of objects stays small. Day buckets
        of closed days are summed up once (``subject_health_days``).
        """

        size = max(60, int(bucket_seconds))
        with self._lock, self._connect() as connection:
            if size != DAY_SECONDS:
                rows = _buckets(connection, application_id, subject_kind, start, end, size)
            else:
                rows = self._day_buckets(connection, application_id, subject_kind, start, end)
        return [
            {
                "subject_id": row["subject_id"],
                "bucket": row["bucket"],
                "health": row["health"],
                "status": row["status"],
            }
            for row in rows
            if row["bucket"] is not None
        ]

    def _day_buckets(
        self, connection: Any, application_id: str, subject_kind: str, start: str, end: str
    ) -> list[Any]:
        """Day buckets from ``start`` to ``end``: the whole closed days between them from
        ``subject_health_days`` (summed up at their first read), the edges and today from
        ``subject_health``. Stored times are UTC text, so day ``D`` is from ``D`` up to the next
        day as text, whatever the separator."""

        try:
            first = datetime.fromisoformat(start.replace("Z", "+00:00")[:10]).date()
            last = datetime.fromisoformat(end.replace("Z", "+00:00")[:10]).date()
        except ValueError:
            return _buckets(connection, application_id, subject_kind, start, end, DAY_SECONDS)
        today = datetime.now(UTC).date()
        whole = [
            first + timedelta(days=offset)
            for offset in range(1, (last - first).days)
            if first + timedelta(days=offset) < today
        ]
        if not whole:
            return _buckets(connection, application_id, subject_kind, start, end, DAY_SECONDS)
        rows = _buckets(
            connection, application_id, subject_kind, start, whole[0].isoformat(), DAY_SECONDS, True
        )
        for day in whole:
            text = day.isoformat()
            done = connection.execute(
                "SELECT 1 FROM subject_health_days_done"
                " WHERE application_id = ? AND subject_kind = ? AND day = ?",
                (application_id, subject_kind, text),
            ).fetchone()
            if done:
                bucket = int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())
                rows += [
                    {**dict(row), "bucket": bucket}
                    for row in connection.execute(
                        "SELECT subject_id, health, status FROM subject_health_days"
                        " WHERE application_id = ? AND subject_kind = ? AND day = ?",
                        (application_id, subject_kind, text),
                    )
                ]
                continue
            following = (day + timedelta(days=1)).isoformat()
            found = _buckets(
                connection, application_id, subject_kind, text, following, DAY_SECONDS, True
            )
            connection.executemany(
                "INSERT OR REPLACE INTO subject_health_days (application_id, subject_kind, day,"
                " subject_id, health, status) VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        application_id,
                        subject_kind,
                        text,
                        row["subject_id"],
                        row["health"],
                        row["status"],
                    )
                    for row in found
                ],
            )
            connection.execute(
                "INSERT OR IGNORE INTO subject_health_days_done (application_id, subject_kind, day)"
                " VALUES (?, ?, ?)",
                (application_id, subject_kind, text),
            )
            rows += found
        following = (whole[-1] + timedelta(days=1)).isoformat()
        return rows + _buckets(
            connection, application_id, subject_kind, following, end, DAY_SECONDS
        )

    def add_history(
        self, application_id: str, subject_kind: str, rows: list[dict[str, Any]]
    ) -> None:
        """Health points of past moments (``loops.replay``); the latest analysis stays."""

        with self._lock, self._connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO subject_health
                (application_id, subject_kind, subject_id, source_end, status, health)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        application_id,
                        subject_kind,
                        row["subject_id"],
                        row["source_end"],
                        row.get("status"),
                        row.get("health"),
                    )
                    for row in rows
                ],
            )
            _forget_days(
                connection, application_id, subject_kind, {str(row["source_end"]) for row in rows}
            )
        self.writes += 1

    def history_ends(
        self, application_id: str, subject_kind: str, start: str, end: str
    ) -> list[str]:
        """The moments with health points between ``start`` and ``end`` (stored format)."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT source_end FROM subject_health
                WHERE application_id = ? AND subject_kind = ? AND source_end >= ? AND source_end <= ?
                """,
                (application_id, subject_kind, start, end),
            ).fetchall()
        return [row[0] for row in rows]

    def last_source_end(self, application_id: str, subject_kind: str) -> str | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT MAX(source_end) FROM subject_health WHERE application_id = ? AND subject_kind = ?",
                (application_id, subject_kind),
            ).fetchone()
        return row[0] if row else None

    def prune_history(self, *, days: float = 90) -> int:
        """Drop health older than ``days`` before each application's newest data.

        Measured from the data, not the clock: a recorded or replayed source
        (a CSV from last year) keeps its history.
        """

        removed = 0
        with self._lock, self._connect() as connection:
            groups = connection.execute(
                "SELECT application_id, subject_kind, MAX(source_end) AS newest FROM subject_health "
                "GROUP BY application_id, subject_kind"
            ).fetchall()
            for group in groups:
                try:
                    newest = datetime.fromisoformat(str(group["newest"]))
                except ValueError:
                    continue
                # Same text format as the stored values, so the comparison is chronological.
                separator = "T" if "T" in str(group["newest"]) else " "
                cutoff = (newest - timedelta(days=days)).isoformat(
                    sep=separator, timespec="seconds"
                )
                removed += connection.execute(
                    "DELETE FROM subject_health WHERE application_id = ? AND subject_kind = ? AND source_end < ?",
                    (group["application_id"], group["subject_kind"], cutoff),
                ).rowcount
                for table in ("subject_health_days", "subject_health_days_done"):
                    connection.execute(
                        f"DELETE FROM {table} WHERE application_id = ? AND subject_kind = ?"  # noqa: S608
                        " AND day < ?",
                        (group["application_id"], group["subject_kind"], cutoff[:10]),
                    )
        return removed

    def _row(self, row: Any, *, results: bool = False) -> dict[str, Any]:
        item = dict(row)
        item["summary"] = self._loads(item.pop("summary_json", None), {})
        if results:
            item["results"] = self._loads(item.pop("results_json", None), [])
        else:
            item.pop("results_json", None)
        return item


DAY_SECONDS = 86400


def _buckets(
    connection: Any,
    application_id: str,
    subject_kind: str,
    start: str,
    end: str,
    size: int,
    before_end: bool = False,
) -> list[Any]:
    """Mean health and last status per subject and ``size`` bucket from ``start`` to ``end``
    (included, or excluded with ``before_end``)."""

    return connection.execute(
        f"""
        SELECT subject_id,
               (CAST(strftime('%s', source_end) AS INTEGER) / ?) * ? AS bucket,
               AVG(health) AS health, status, MAX(source_end) AS last_end
        FROM subject_health
        WHERE application_id = ? AND subject_kind = ? AND source_end >= ?
          AND source_end {"<" if before_end else "<="} ?
        GROUP BY subject_id, bucket
        """,  # noqa: S608
        (size, size, application_id, subject_kind, start, end),
    ).fetchall()


def _forget_days(connection: Any, application_id: str, subject_kind: str, ends: set[str]) -> None:
    """Closed days that got health points again are summed up again at the next read."""

    for day in {end[:10] for end in ends if end}:
        for table in ("subject_health_days", "subject_health_days_done"):
            connection.execute(
                f"DELETE FROM {table} WHERE application_id = ? AND subject_kind = ? AND day = ?",  # noqa: S608
                (application_id, subject_kind, day),
            )
