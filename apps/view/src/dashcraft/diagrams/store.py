"""Saved diagrams and their last saves, shared by everyone in the installation."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Any

from plantcraft_sdk.server.store import Store

from dashcraft.dashboards.model import Conflict

# The saves kept per diagram, to look at and restore.
MAX_VERSIONS = 30
# What the columns hold; everything else of a diagram (canvas, elements) is ``body_json``.
_COLUMNS = ("name", "description", "folder_id")


class DiagramStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS diagrams (
        diagram_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        folder_id TEXT NOT NULL DEFAULT '',
        tags_json TEXT NOT NULL DEFAULT '[]',
        body_json TEXT NOT NULL,
        created_by TEXT,
        created_at TEXT NOT NULL,
        updated_by TEXT,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_diagrams_folder ON diagrams(folder_id);

    CREATE TABLE IF NOT EXISTS diagram_versions (
        diagram_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        saved_by TEXT,
        saved_at TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        PRIMARY KEY (diagram_id, version)
    );
    """

    def _diagram(self, row: sqlite3.Row) -> dict[str, Any]:
        body = self._loads(row["body_json"], {})
        return {
            **(body if isinstance(body, dict) else {}),
            "diagram_id": row["diagram_id"],
            "name": row["name"],
            "description": row["description"],
            "folder_id": row["folder_id"],
            "tags": self._loads(row["tags_json"], []),
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "updated_by": row["updated_by"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _body(payload: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in payload.items() if key not in (*_COLUMNS, "tags")}

    def list(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM diagrams ORDER BY updated_at DESC, rowid"
            ).fetchall()
        return [self._diagram(row) for row in rows]

    def get(self, diagram_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM diagrams WHERE diagram_id = ?", (diagram_id,)
            ).fetchone()
        return self._diagram(row) if row else None

    def create(self, payload: dict[str, Any], user: str | None) -> dict[str, Any]:
        diagram_id = uuid.uuid4().hex[:12]
        now = self._now()
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO diagrams (diagram_id, name, description, folder_id, tags_json, "
                "body_json, created_by, created_at, updated_by, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    diagram_id,
                    payload["name"],
                    payload.get("description") or "",
                    payload.get("folder_id") or "",
                    self._json(payload.get("tags") or []),
                    self._json(self._body(payload)),
                    user,
                    now,
                    user,
                    now,
                ),
            )
            self._record_version(connection, diagram_id, payload, user, now)
        return self.get(diagram_id) or {}

    def update(
        self,
        diagram_id: str,
        payload: dict[str, Any],
        user: str | None,
        *,
        base_updated_at: str | None = None,
    ) -> dict[str, Any] | None:
        """Save a diagram; with ``base_updated_at``, refuse when someone saved it since."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT updated_at FROM diagrams WHERE diagram_id = ?", (diagram_id,)
            ).fetchone()
            if row is None:
                return None
            if base_updated_at and row["updated_at"] != base_updated_at:
                current = connection.execute(
                    "SELECT * FROM diagrams WHERE diagram_id = ?", (diagram_id,)
                ).fetchone()
                raise Conflict(self._diagram(current))
            at = self._after(row["updated_at"])
            connection.execute(
                "UPDATE diagrams SET name = ?, description = ?, folder_id = ?, tags_json = ?, "
                "body_json = ?, updated_by = ?, updated_at = ? WHERE diagram_id = ?",
                (
                    payload["name"],
                    payload.get("description") or "",
                    payload.get("folder_id") or "",
                    self._json(payload.get("tags") or []),
                    self._json(self._body(payload)),
                    user,
                    at,
                    diagram_id,
                ),
            )
            self._record_version(connection, diagram_id, payload, user, at)
        return self.get(diagram_id)

    def delete(self, diagram_id: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM diagrams WHERE diagram_id = ?", (diagram_id,))
            connection.execute("DELETE FROM diagram_versions WHERE diagram_id = ?", (diagram_id,))
        return bool(cursor.rowcount)

    def in_folder(self, folder_id: str) -> int:
        with self._lock, self._connect() as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM diagrams WHERE folder_id = ?", (folder_id,)
                ).fetchone()[0]
            )

    def count(self) -> int:
        with self._lock, self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM diagrams").fetchone()[0])

    # Versions -------------------------------------------------------------------

    def _record_version(
        self,
        connection: sqlite3.Connection,
        diagram_id: str,
        payload: dict[str, Any],
        user: str | None,
        at: str,
    ) -> None:
        last = connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM diagram_versions WHERE diagram_id = ?",
            (diagram_id,),
        ).fetchone()[0]
        kept = {key: value for key, value in payload.items() if key != "folder_id"}
        connection.execute(
            "INSERT INTO diagram_versions (diagram_id, version, saved_by, saved_at, payload_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (diagram_id, int(last) + 1, user, at, self._json(kept)),
        )
        connection.execute(
            "DELETE FROM diagram_versions WHERE diagram_id = ? AND version <= ?",
            (diagram_id, int(last) + 1 - MAX_VERSIONS),
        )

    def versions(self, diagram_id: str) -> list[dict[str, Any]]:
        """The saves kept of one diagram, newest first (without their content)."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT version, saved_by, saved_at, payload_json FROM diagram_versions "
                "WHERE diagram_id = ? ORDER BY version DESC",
                (diagram_id,),
            ).fetchall()
        out = []
        for row in rows:
            kept = self._loads(row["payload_json"], {})
            out.append(
                {
                    "version": row["version"],
                    "saved_by": row["saved_by"],
                    "saved_at": row["saved_at"],
                    "name": kept.get("name") or "",
                    "elements": len(kept.get("elements") or []),
                }
            )
        return out

    def version(self, diagram_id: str, version: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT version, saved_by, saved_at, payload_json FROM diagram_versions "
                "WHERE diagram_id = ? AND version = ?",
                (diagram_id, version),
            ).fetchone()
        if row is None:
            return None
        return {
            "version": row["version"],
            "saved_by": row["saved_by"],
            "saved_at": row["saved_at"],
            "diagram": self._loads(row["payload_json"], {}),
        }

    def _after(self, previous: str) -> str:
        """Now, or 1 ms after ``previous``: every save gets a new ``updated_at``."""

        now = self._now()
        last = datetime.fromisoformat(previous)
        if datetime.fromisoformat(now) > last:
            return now
        return (last + timedelta(milliseconds=1)).isoformat(timespec="milliseconds")
