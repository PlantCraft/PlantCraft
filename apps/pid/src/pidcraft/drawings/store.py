"""Drawings and their store: the app's own SQLite database and a folder of the original files.

| Table | Holds |
|---|---|
| ``drawings`` | one P&ID (a number such as ``PID-U200-001``, a title, a unit) and its current file |
| ``revisions`` | each file sent for a drawing: name, format, SHA-256, who sent it, and whether it was read |
| ``diagrams`` | the pages of a revision the reader recognised as diagrams: sheet, unit and what was read on them (items and relations, as JSON) |
| ``map_reviews`` | the plant map's items and relations a person approved or rejected |

The original files are kept apart, under ``files/`` of the data folder, named by their SHA-256.
The rows keep the names the plant map reads (``doc_id`` is the drawing, ``rev_id`` its file),
the same shapes the map had inside PlantCraft Documents up to 0.5.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

from plantcraft_sdk.server.store import Store

DRAWING_ID = re.compile(r"^[a-f0-9]{12}$")
STATUSES = ("queued", "reading", "read", "failed", "superseded")


class DrawingStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS drawings (
        drawing_id TEXT PRIMARY KEY,
        number TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        unit TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS drawings_number ON drawings (number);
    CREATE TABLE IF NOT EXISTS revisions (
        rev_id TEXT PRIMARY KEY,
        drawing_id TEXT NOT NULL REFERENCES drawings(drawing_id) ON DELETE CASCADE,
        filename TEXT NOT NULL,
        format TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        size INTEGER NOT NULL,
        status TEXT NOT NULL,
        error TEXT NOT NULL DEFAULT '',
        pages INTEGER NOT NULL DEFAULT 0,
        uploaded_by TEXT NOT NULL,
        uploaded_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS revisions_drawing ON revisions (drawing_id, uploaded_at);
    CREATE TABLE IF NOT EXISTS diagrams (
        rev_id TEXT NOT NULL REFERENCES revisions(rev_id) ON DELETE CASCADE,
        doc_id TEXT NOT NULL,
        page INTEGER NOT NULL,
        sheet TEXT NOT NULL DEFAULT '',
        title TEXT NOT NULL DEFAULT '',
        unit TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT '',
        items INTEGER NOT NULL DEFAULT 0,
        relations INTEGER NOT NULL DEFAULT 0,
        result TEXT NOT NULL,
        PRIMARY KEY (rev_id, page)
    );
    CREATE INDEX IF NOT EXISTS diagrams_doc ON diagrams (doc_id);
    CREATE TABLE IF NOT EXISTS map_reviews (
        key TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        verdict TEXT NOT NULL,
        by TEXT NOT NULL DEFAULT '',
        at TEXT NOT NULL
    );
    """

    def __init__(self, db: Any, files: Path):
        super().__init__(db)
        self.files = files
        self.files.mkdir(parents=True, exist_ok=True)

    # Files -------------------------------------------------------------------------------

    def save_file(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        path = self.file_path(digest)
        if not path.is_file():
            partial = path.with_suffix(".partial")
            partial.write_bytes(data)
            partial.replace(path)
        return digest

    def file_path(self, sha256: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", sha256 or ""):
            return self.files / "missing"
        return self.files / sha256

    # Drawings ----------------------------------------------------------------------------

    def drawings(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT d.*, r.rev_id, r.filename, r.format, r.size, r.status, r.error, r.pages, "
                "r.uploaded_at, r.uploaded_by, "
                "(SELECT COUNT(*) FROM diagrams g WHERE g.rev_id = r.rev_id) AS diagrams "
                "FROM drawings d LEFT JOIN revisions r ON r.rev_id = ("
                "  SELECT rev_id FROM revisions WHERE drawing_id = d.drawing_id "
                "  AND status != 'superseded' ORDER BY uploaded_at DESC LIMIT 1) "
                "ORDER BY d.unit, d.number"
            ).fetchall()
        return [dict(row) for row in rows]

    def drawing(self, drawing_id: str) -> dict[str, Any] | None:
        if not DRAWING_ID.match(drawing_id or ""):
            return None
        return next((d for d in self.drawings() if d["drawing_id"] == drawing_id), None)

    def by_number(self, number: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT drawing_id FROM drawings WHERE number = ?", (number,)
            ).fetchone()
        return self.drawing(row["drawing_id"]) if row else None

    def create_drawing(self, number: str, title: str, unit: str, by: str) -> str:
        drawing_id, now = uuid.uuid4().hex[:12], self._now()
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO drawings (drawing_id, number, title, unit, created_at, created_by, "
                "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (drawing_id, number, title, unit, now, by, now),
            )
        return drawing_id

    def update_drawing(self, drawing_id: str, **fields: str) -> None:
        allowed = {key: value for key, value in fields.items() if key in {"title", "unit"}}
        if not allowed:
            return
        assignments = ", ".join(f"{key} = ?" for key in allowed)
        with self._lock, self._connect() as connection:
            connection.execute(
                f"UPDATE drawings SET {assignments}, updated_at = ? WHERE drawing_id = ?",
                [*allowed.values(), self._now(), drawing_id],
            )

    def delete_drawing(self, drawing_id: str) -> list[str]:
        """Removes a drawing, its revisions and diagrams; returns the files no one uses now."""

        with self._lock, self._connect() as connection:
            shas = [
                row[0]
                for row in connection.execute(
                    "SELECT sha256 FROM revisions WHERE drawing_id = ?", (drawing_id,)
                )
            ]
            connection.execute("DELETE FROM diagrams WHERE doc_id = ?", (drawing_id,))
            connection.execute("DELETE FROM revisions WHERE drawing_id = ?", (drawing_id,))
            connection.execute("DELETE FROM drawings WHERE drawing_id = ?", (drawing_id,))
            used = {row[0] for row in connection.execute("SELECT sha256 FROM revisions")}
        return [sha for sha in set(shas) if sha not in used]

    # Revisions ---------------------------------------------------------------------------

    def add_revision(
        self, drawing_id: str, filename: str, fmt: str, sha256: str, size: int, by: str
    ) -> str:
        rev_id = uuid.uuid4().hex[:12]
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO revisions (rev_id, drawing_id, filename, format, sha256, size, "
                "status, uploaded_by, uploaded_at) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?)",
                (rev_id, drawing_id, filename, fmt, sha256, size, by, self._now()),
            )
        return rev_id

    def revision(self, rev_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM revisions WHERE rev_id = ?", (rev_id,)
            ).fetchone()
        return dict(row) if row else None

    def set_status(self, rev_id: str, status: str, error: str = "", pages: int = 0) -> None:
        assert status in STATUSES
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE revisions SET status = ?, error = ?, pages = ? WHERE rev_id = ?",
                (status, error[:500], pages, rev_id),
            )
            if status == "read":
                row = connection.execute(
                    "SELECT drawing_id FROM revisions WHERE rev_id = ?", (rev_id,)
                ).fetchone()
                if row:
                    connection.execute(
                        "UPDATE revisions SET status = 'superseded' WHERE drawing_id = ? "
                        "AND rev_id != ? AND status = 'read'",
                        (row[0], rev_id),
                    )

    def queued(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM revisions WHERE status IN ('queued', 'reading') ORDER BY uploaded_at"
            ).fetchall()
        return [dict(row) for row in rows]

    # Diagrams (the pages read as P&IDs) ---------------------------------------------------

    def store_diagrams(self, rev_id: str, pages: list[dict[str, Any]]) -> None:
        rev = self.revision(rev_id)
        if rev is None:
            return
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM diagrams WHERE rev_id = ?", (rev_id,))
            for page in pages:
                connection.execute(
                    "INSERT INTO diagrams (rev_id, doc_id, page, sheet, title, unit, source, "
                    "items, relations, result) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        rev_id,
                        rev["drawing_id"],
                        int(page.get("page") or 1),
                        page.get("sheet") or "",
                        page.get("title") or "",
                        page.get("unit") or "",
                        page.get("source") or "",
                        len(page.get("items") or []),
                        len(page.get("relations") or []),
                        json.dumps(page),
                    ),
                )

    def update_diagram(self, rev_id: str, page: int, result: dict[str, Any]) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE diagrams SET items = ?, relations = ?, result = ? "
                "WHERE rev_id = ? AND page = ?",
                (
                    len(result.get("items") or []),
                    len(result.get("relations") or []),
                    json.dumps(result),
                    rev_id,
                    page,
                ),
            )

    _ROW = (
        "d.title AS doc_title, d.number AS doc_number, r.format AS format, "
        "r.filename AS filename FROM diagrams g "
        "JOIN revisions r ON r.rev_id = g.rev_id JOIN drawings d ON d.drawing_id = g.doc_id "
    )

    def diagrams(self, *, full: bool = False) -> list[dict[str, Any]]:
        """The diagram pages of the drawings' current files."""

        columns = (
            "g.*"
            if full
            else "g.rev_id, g.doc_id, g.page, g.sheet, g.title, g.unit, g.source, g.items, "
            "g.relations"
        )
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT {columns}, {self._ROW}"
                "WHERE r.status = 'read' ORDER BY g.unit, g.sheet, d.number, g.page"
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            if full:
                item["result"] = json.loads(item["result"])
            out.append(item)
        return out

    def diagram(self, rev_id: str, page: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                f"SELECT g.*, r.sha256 AS sha256, {self._ROW}WHERE g.rev_id = ? AND g.page = ?",
                (rev_id, page),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["result"] = json.loads(item["result"])
        return item

    # Reviews of the map ------------------------------------------------------------------

    def map_reviews(self) -> dict[str, dict[str, Any]]:
        """What people checked on the plant map, kept by name so it survives a new file."""

        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM map_reviews").fetchall()
        return {row["key"]: dict(row) for row in rows}

    def set_map_review(self, key: str, kind: str, verdict: str, by: str) -> None:
        with self._lock, self._connect() as connection:
            if not verdict:
                connection.execute("DELETE FROM map_reviews WHERE key = ?", (key,))
                return
            connection.execute(
                "INSERT INTO map_reviews (key, kind, verdict, by, at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET kind = excluded.kind, verdict = excluded.verdict, "
                "by = excluded.by, at = excluded.at",
                (key, kind, verdict, by, self._now()),
            )
