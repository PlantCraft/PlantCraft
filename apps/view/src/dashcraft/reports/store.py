"""Saved reports and every PDF they made (``report_runs``), shared by the installation.

A run is one making of a report: on its schedule, or by a person (Send now, Download). It keeps
the period it covered, who asked, how many sections could not be read, who it went to and the
PDF itself, so what was sent reads the same months later. The newest ``MAX_RUNS`` of each report
are kept.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Any

from plantcraft_sdk.server.store import Migration, Store
from plantcraft_sdk.utc import utc_iso

from dashcraft.dashboards.model import Conflict
from dashcraft.reports.model import text_with_heading

MAX_RUNS = 100
MAX_REPORTS = 500
_JSON = {
    "schedule": ("schedule_json", {}),
    "recipients": ("recipients_json", []),
    "sections": ("sections_json", []),
}
_RUN_COLUMNS = (
    "run_id, report_id, report_name, trigger, status, requested_by, started_at, finished_at, "
    "period_start, period_end, period, sections, problems, summary, error, recipients_json, "
    "delivered, pdf_bytes"
)


def _text_cells(connection: sqlite3.Connection) -> None:
    """Text sections saved with a heading field (before 2026-10-26) become one Markdown cell."""

    rows = connection.execute("SELECT report_id, sections_json FROM reports").fetchall()
    for report_id, raw in rows:
        try:
            sections = json.loads(raw or "[]")
        except ValueError:
            continue
        changed = False
        for section in sections:
            if isinstance(section, dict) and section.get("kind") == "text" and section.get("title"):
                section["text"] = text_with_heading(section["title"], section.get("text") or "")
                section["title"] = ""
                changed = True
        if changed:
            connection.execute(
                "UPDATE reports SET sections_json = ? WHERE report_id = ?",
                (json.dumps(sections, ensure_ascii=False), report_id),
            )


class ReportStore(Store):
    MIGRATIONS = (Migration("2026-10-26-text-cells", _text_cells),)

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS reports (
        report_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        folder_id TEXT NOT NULL DEFAULT '',
        period TEXT NOT NULL DEFAULT '24h',
        schedule_json TEXT NOT NULL DEFAULT '{}',
        recipients_json TEXT NOT NULL DEFAULT '[]',
        email INTEGER NOT NULL DEFAULT 0,
        sections_json TEXT NOT NULL DEFAULT '[]',
        -- The next scheduled send (UTC), '' when the schedule is off.
        next_run_at TEXT NOT NULL DEFAULT '',
        created_by TEXT,
        created_at TEXT NOT NULL,
        updated_by TEXT,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS report_runs (
        run_id TEXT PRIMARY KEY,
        report_id TEXT NOT NULL,
        report_name TEXT NOT NULL,
        trigger TEXT NOT NULL,
        status TEXT NOT NULL,
        requested_by TEXT,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        period_start TEXT NOT NULL,
        period_end TEXT NOT NULL,
        period TEXT NOT NULL,
        sections INTEGER NOT NULL DEFAULT 0,
        problems INTEGER NOT NULL DEFAULT 0,
        summary TEXT NOT NULL DEFAULT '',
        error TEXT NOT NULL DEFAULT '',
        recipients_json TEXT NOT NULL DEFAULT '[]',
        delivered INTEGER NOT NULL DEFAULT 0,
        pdf BLOB,
        pdf_bytes INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_report_runs_report ON report_runs(report_id, started_at);

    -- What the assistant wrote in each run (``reports.assistant``), to show, export and comment.
    CREATE TABLE IF NOT EXISTS assistant_drafts (
        run_id TEXT NOT NULL,
        report_id TEXT NOT NULL,
        section_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        text TEXT NOT NULL,
        facts_json TEXT NOT NULL DEFAULT '{}',
        written_at TEXT NOT NULL,
        PRIMARY KEY (run_id, section_id)
    );
    CREATE INDEX IF NOT EXISTS idx_assistant_drafts ON assistant_drafts(report_id, section_id, written_at);

    -- Each version of an assistant section's requirements, and the feedback that made it.
    CREATE TABLE IF NOT EXISTS assistant_versions (
        report_id TEXT NOT NULL,
        section_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        requirements TEXT NOT NULL,
        feedback TEXT NOT NULL DEFAULT '',
        run_id TEXT,
        created_by TEXT,
        created_at TEXT NOT NULL,
        PRIMARY KEY (report_id, section_id, version)
    );
    """

    # Assistant sections -------------------------------------------------------------

    def keep_draft(self, report_id: str, run_id: str, written: dict[str, Any]) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO assistant_drafts VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    report_id,
                    written["section_id"],
                    int(written.get("version") or 1),
                    written["text"],
                    json.dumps(written.get("facts") or {}),
                    utc_iso(datetime.now().astimezone()),
                ),
            )

    def last_draft(
        self, report_id: str, section_id: str, *, run_id: str | None = None
    ) -> dict[str, Any] | None:
        query = "SELECT * FROM assistant_drafts WHERE report_id = ? AND section_id = ?"
        params: list[Any] = [report_id, section_id]
        if run_id:
            query += " AND run_id = ?"
            params.append(run_id)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                query + " ORDER BY written_at DESC, rowid DESC LIMIT 1", params
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["facts"] = json.loads(item.pop("facts_json") or "{}")
        return item

    def drafts(self, report_id: str, section_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM assistant_drafts WHERE report_id = ? AND section_id = ? "
                "ORDER BY written_at DESC, rowid DESC LIMIT ?",
                (report_id, section_id, limit),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["facts"] = json.loads(item.pop("facts_json") or "{}")
            out.append(item)
        return out

    def keep_version(
        self,
        report_id: str,
        section_id: str,
        version: int,
        requirements: str,
        feedback: str,
        run_id: str | None,
        by: str | None,
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO assistant_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    report_id,
                    section_id,
                    version,
                    requirements,
                    feedback,
                    run_id,
                    by,
                    utc_iso(datetime.now().astimezone()),
                ),
            )

    def assistant_versions(self, report_id: str, section_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM assistant_versions WHERE report_id = ? AND section_id = ? "
                "ORDER BY version",
                (report_id, section_id),
            ).fetchall()
        return [dict(row) for row in rows]

    # Reports -------------------------------------------------------------------

    def _report(self, row: sqlite3.Row) -> dict[str, Any]:
        item = self._row_with_json(row, _JSON)
        item["email"] = bool(item.get("email"))
        item["next_run_at"] = item.get("next_run_at") or None
        return item

    def list(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM reports ORDER BY name COLLATE NOCASE, rowid"
            ).fetchall()
        return [self._report(row) for row in rows]

    def get(self, report_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM reports WHERE report_id = ?", (report_id,)
            ).fetchone()
        return self._report(row) if row else None

    def count(self) -> int:
        with self._lock, self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM reports").fetchone()[0])

    def in_folder(self, folder_id: str) -> int:
        with self._lock, self._connect() as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM reports WHERE folder_id = ?", (folder_id,)
                ).fetchone()[0]
            )

    def _values(self, payload: dict[str, Any]) -> tuple[Any, ...]:
        return (
            payload["name"],
            payload.get("description") or "",
            payload.get("folder_id") or "",
            payload.get("period") or "24h",
            self._json(payload.get("schedule") or {}),
            self._json(payload.get("recipients") or []),
            int(bool(payload.get("email"))),
            self._json(payload.get("sections") or []),
        )

    def create(
        self, payload: dict[str, Any], user: str | None, next_run_at: datetime | None
    ) -> dict[str, Any]:
        report_id = uuid.uuid4().hex[:12]
        now = self._now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO reports (report_id, name, description, folder_id, period,
                    schedule_json, recipients_json, email, sections_json, next_run_at,
                    created_by, created_at, updated_by, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    *self._values(payload),
                    _stamp(next_run_at),
                    user,
                    now,
                    user,
                    now,
                ),
            )
        return self.get(report_id) or {}

    def update(
        self,
        report_id: str,
        payload: dict[str, Any],
        user: str | None,
        next_run_at: datetime | None,
        *,
        base_updated_at: str | None = None,
    ) -> dict[str, Any] | None:
        """Save a report; with ``base_updated_at``, refuse when someone saved it since."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT updated_at FROM reports WHERE report_id = ?", (report_id,)
            ).fetchone()
            if row is None:
                return None
            if base_updated_at and row["updated_at"] != base_updated_at:
                raise Conflict(self.get(report_id) or {})
            connection.execute(
                """
                UPDATE reports SET name = ?, description = ?, folder_id = ?, period = ?,
                    schedule_json = ?, recipients_json = ?, email = ?, sections_json = ?,
                    next_run_at = ?, updated_by = ?, updated_at = ?
                WHERE report_id = ?
                """,
                (
                    *self._values(payload),
                    _stamp(next_run_at),
                    user,
                    self._after(row["updated_at"]),
                    report_id,
                ),
            )
        return self.get(report_id)

    def _after(self, previous: str) -> str:
        now = self._now()
        if datetime.fromisoformat(now) > datetime.fromisoformat(previous):
            return now
        later = datetime.fromisoformat(previous) + timedelta(milliseconds=1)
        return later.isoformat(timespec="milliseconds")

    def set_next_run(self, report_id: str, next_run_at: datetime | None) -> None:
        """When the report is sent next; not a save of the report (``updated_at`` stays)."""

        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE reports SET next_run_at = ? WHERE report_id = ?",
                (_stamp(next_run_at), report_id),
            )

    def due(self, now: datetime) -> list[dict[str, Any]]:
        """The reports whose next send is now or past, the oldest first."""

        stamp = _stamp(now)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM reports WHERE next_run_at != '' AND next_run_at <= ? "
                "ORDER BY next_run_at",
                (stamp,),
            ).fetchall()
        return [self._report(row) for row in rows]

    def delete(self, report_id: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM reports WHERE report_id = ?", (report_id,))
            connection.execute("DELETE FROM report_runs WHERE report_id = ?", (report_id,))
        return bool(cursor.rowcount)

    # Runs ----------------------------------------------------------------------

    def _run(self, row: sqlite3.Row) -> dict[str, Any]:
        item = self._row_with_json(row, {"recipients": ("recipients_json", [])})
        item.pop("pdf", None)
        item["finished_at"] = item.get("finished_at") or None
        return item

    def start_run(
        self,
        report: dict[str, Any],
        *,
        trigger: str,
        by: str | None,
        period_start: datetime,
        period_end: datetime,
    ) -> dict[str, Any]:
        run_id = uuid.uuid4().hex[:16]
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO report_runs (run_id, report_id, report_name, trigger, status,
                    requested_by, started_at, period_start, period_end, period, sections)
                VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    report["report_id"],
                    report["name"],
                    trigger,
                    by,
                    self._now(),
                    _stamp(period_start),
                    _stamp(period_end),
                    report.get("period") or "24h",
                    len(report.get("sections") or []),
                ),
            )
        return self.run(run_id) or {}

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        pdf: bytes | None = None,
        problems: int = 0,
        summary: str = "",
        error: str = "",
    ) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE report_runs SET status = ?, finished_at = ?, pdf = ?, pdf_bytes = ?,
                    problems = ?, summary = ?, error = ?
                WHERE run_id = ?
                """,
                (
                    status,
                    self._now(),
                    pdf,
                    len(pdf or b""),
                    problems,
                    summary[:300],
                    error[:500],
                    run_id,
                ),
            )
            report = connection.execute(
                "SELECT report_id FROM report_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if report is not None:
                self._trim(connection, report["report_id"])
        return self.run(run_id) or {}

    def delivered(self, run_id: str, recipients: list[str], count: int) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE report_runs SET recipients_json = ?, delivered = ? WHERE run_id = ?",
                (self._json(recipients), count, run_id),
            )

    def _trim(self, connection: sqlite3.Connection, report_id: str) -> None:
        connection.execute(
            """
            DELETE FROM report_runs WHERE report_id = ? AND run_id NOT IN (
                SELECT run_id FROM report_runs WHERE report_id = ?
                ORDER BY started_at DESC, rowid DESC LIMIT ?)
            """,
            (report_id, report_id, MAX_RUNS),
        )

    def run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                f"SELECT {_RUN_COLUMNS} FROM report_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return self._run(row) if row else None

    def runs(self, report_id: str | None = None, limit: int = MAX_RUNS) -> list[dict[str, Any]]:
        """The runs of one report (every report's without one), newest first."""

        where, params = ("WHERE report_id = ?", [report_id]) if report_id else ("", [])
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT {_RUN_COLUMNS} FROM report_runs {where} "
                "ORDER BY started_at DESC, rowid DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [self._run(row) for row in rows]

    def last_runs(self) -> dict[str, dict[str, Any]]:
        """The newest run of each report, by report id."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT {_RUN_COLUMNS} FROM report_runs r WHERE rowid = (
                    SELECT rowid FROM report_runs WHERE report_id = r.report_id
                    ORDER BY started_at DESC, rowid DESC LIMIT 1)
                """
            ).fetchall()
        return {row["report_id"]: self._run(row) for row in rows}

    def pdf(self, run_id: str) -> bytes | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT pdf FROM report_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return bytes(row["pdf"]) if row and row["pdf"] else None

    def fail_unfinished(self) -> int:
        """Runs left running by a server that stopped: failed, so nothing waits on them."""

        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE report_runs SET status = 'failed', finished_at = ?, "
                "error = 'The server stopped while the report was being made.' "
                "WHERE status = 'running'",
                (self._now(),),
            )
        return int(cursor.rowcount)


def _stamp(moment: datetime | None) -> str:
    """UTC with milliseconds and ``Z``, the store's format: sortable as text."""

    return utc_iso(moment) if moment is not None else ""
