"""The central audit log: who changed what, in PlantCraft and in every app of the suite.

Apps record their users' changes with ``POST /api/v1/audit``; PlantCraft
records its own security changes (app keys, settings) and every sign-in, failed sign-in and
sign-out here too (``session.*``, IEC 62443-4-2 CR 2.8). Rows are only added; administrators
read them on Settings › Audit log (``GET /api/audit``).
"""

from __future__ import annotations

from typing import Any

from plantcraft.db import Database, Store

MAX_DETAIL_CHARS = 20_000
# Rows one read returns at most (the Audit page reads a period, newest first).
MAX_ROWS = 5_000
# The quick filters of the audit log page: what people changed, who signed in
# and out, and the sign-ins that failed or were blocked.
KINDS = ("changes", "sign_ins", "failed")
FAILED = ("session.sign_in_failed", "session.sign_in_blocked")


class AuditStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS audit_log (
        audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
        at TEXT NOT NULL,
        username TEXT NOT NULL,
        app_id TEXT,
        action TEXT NOT NULL,
        subject TEXT NOT NULL DEFAULT '',
        detail_json TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_audit_log_at ON audit_log(at);
    """

    def __init__(self, db: Database):
        super().__init__(db)

    def record(
        self,
        username: str,
        action: str,
        subject: str = "",
        detail: Any = None,
        *,
        app_id: str | None = None,
    ) -> int:
        detail_json = None if detail is None else self._json(detail)[:MAX_DETAIL_CHARS]
        with self._lock, self._write() as connection:
            cursor = connection.execute(
                """
                INSERT INTO audit_log (at, username, app_id, action, subject, detail_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (self._now(), username, app_id, action, subject, detail_json),
            )
        return int(cursor.lastrowid)

    def list(
        self,
        *,
        limit: int = 100,
        username: str | None = None,
        app_id: str | None = None,
        action: str | None = None,
        since: str | None = None,
        until: str | None = None,
        kind: str | None = None,
        before_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Newest first. ``action`` keeps that action and its family (``session`` keeps
        ``session.sign_in``...); ``since`` and ``until`` are ISO times, compared as stored;
        ``kind`` is one of ``KINDS``; ``before_id`` reads on from an earlier page's last row."""

        clauses, values = self._where(username, app_id, action, since, until, kind)
        if before_id:
            clauses.append("audit_id < ?")
            values.append(before_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM audit_log{where} ORDER BY audit_id DESC LIMIT ?",
                [*values, max(1, min(limit, MAX_ROWS))],
            ).fetchall()
        return [self._row_with_json(row, {"detail": ("detail_json", None)}) for row in rows]

    def signed_in(self, since: str) -> int:
        """How many people signed in since ``since`` (an ISO time), each counted once."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(DISTINCT username) FROM audit_log "
                "WHERE action = 'session.sign_in' AND at >= ?",
                (since,),
            ).fetchone()
        return int(row[0] or 0)

    def volume(
        self,
        *,
        bucket: str = "day",
        username: str | None = None,
        app_id: str | None = None,
        action: str | None = None,
        since: str | None = None,
        until: str | None = None,
        kind: str | None = None,
    ) -> dict[str, Any]:
        """How many rows per hour or day (UTC), the failed sign-ins apart, and who and which
        apps wrote them: the chart and the filters of the audit log page."""

        clauses, values = self._where(username, app_id, action, since, until, kind)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        width = 13 if bucket == "hour" else 10
        failed = "', '".join(FAILED)
        with self._lock, self._connect() as connection:
            buckets = connection.execute(
                f"SELECT substr(at, 1, {width}) AS bucket, COUNT(*) AS total, "
                f"SUM(action IN ('{failed}')) AS failed FROM audit_log{where} "
                "GROUP BY bucket ORDER BY bucket",
                values,
            ).fetchall()
            people = connection.execute(
                f"SELECT username, COUNT(*) FROM audit_log{where} GROUP BY username "
                "ORDER BY COUNT(*) DESC LIMIT 200",
                values,
            ).fetchall()
            apps = connection.execute(
                f"SELECT COALESCE(app_id, ''), COUNT(*) FROM audit_log{where} GROUP BY app_id "
                "ORDER BY COUNT(*) DESC LIMIT 100",
                values,
            ).fetchall()
        suffix = ":00:00Z" if bucket == "hour" else "T00:00:00Z"
        return {
            "bucket": bucket,
            "buckets": [
                {"at": f"{row[0]}{suffix}", "total": row[1], "failed": row[2] or 0}
                for row in buckets
            ],
            "people": [{"username": row[0], "count": row[1]} for row in people],
            "apps": [{"app_id": row[0] or None, "count": row[1]} for row in apps],
        }

    @staticmethod
    def _where(
        username: str | None,
        app_id: str | None,
        action: str | None,
        since: str | None,
        until: str | None,
        kind: str | None,
    ) -> tuple[list[str], list[Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if username:
            clauses.append("username = ?")
            values.append(username)
        if app_id:
            clauses.append("app_id = ?")
            values.append(app_id)
        if action:
            clauses.append("(action = ? OR action LIKE ? ESCAPE '\\')")
            escaped = action.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            values += [action, f"{escaped}.%"]
        if since:
            clauses.append("at >= ?")
            values.append(since)
        if until:
            clauses.append("at <= ?")
            values.append(until)
        if kind == "changes":
            clauses.append("action NOT LIKE 'session.%'")
        elif kind == "sign_ins":
            clauses.append("action IN ('session.sign_in', 'session.sign_out')")
        elif kind == "failed":
            clauses.append(f"action IN ({', '.join('?' for _ in FAILED)})")
            values += list(FAILED)
        return clauses, values
