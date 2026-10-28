"""Notes and their store: one table in the app's own SQLite database.

| Table | Holds |
|---|---|
| ``notes`` | a short text on one asset of PlantCraft's asset tree (``asset:<id>``), who wrote it and when, and the follow-up it asks for (a day and a person) |

The asset itself stays in PlantCraft: a note keeps only its id, and the pages ask PlantCraft for
its name. This is the pattern of every app: its own object in its own store, the plant's data
read through API v1.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from plantcraft_sdk.server.store import Store

from starter.notes.models import NoteDraft

NOTE_ID = re.compile(r"^[a-f0-9]{12}$")


class NoteStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS notes (
        note_id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL,
        text TEXT NOT NULL,
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL,
        follow_up TEXT,
        follow_up_by TEXT
    );
    CREATE INDEX IF NOT EXISTS notes_asset ON notes (asset_id, updated_at);
    """

    def __init__(self, db: Any):
        super().__init__(db)
        # A database of StarterCraft 0.1 has no follow-up yet.
        with self._lock, self._connect() as connection:
            known = {row[1] for row in connection.execute("PRAGMA table_info(notes)")}
            for column in ("follow_up", "follow_up_by"):
                if column not in known:
                    connection.execute(f"ALTER TABLE notes ADD COLUMN {column} TEXT")

    def list(self, asset_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM notes"
        params: tuple[Any, ...] = ()
        if asset_id:
            query += " WHERE asset_id = ?"
            params = (asset_id,)
        with self._lock, self._connect() as connection:
            rows = connection.execute(query + " ORDER BY updated_at DESC", params).fetchall()
        return [dict(row) for row in rows]

    def get(self, note_id: str) -> dict[str, Any] | None:
        if not NOTE_ID.match(note_id):
            return None
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM notes WHERE note_id = ?", (note_id,)).fetchone()
        return dict(row) if row else None

    def create(self, draft: NoteDraft, by: str) -> dict[str, Any]:
        note_id, now = uuid.uuid4().hex[:12], self._now()
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO notes (note_id, asset_id, text, created_at, created_by, updated_at, "
                "updated_by, follow_up, follow_up_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    note_id,
                    draft.asset_id,
                    draft.text,
                    now,
                    by,
                    now,
                    by,
                    draft.follow_up,
                    draft.follow_up_by,
                ),  # fmt: skip
            )
        return self.get(note_id) or {}

    def update(self, note_id: str, draft: NoteDraft, by: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            changed = connection.execute(
                "UPDATE notes SET asset_id = ?, text = ?, updated_at = ?, updated_by = ?, "
                "follow_up = ?, follow_up_by = ? WHERE note_id = ?",
                (
                    draft.asset_id,
                    draft.text,
                    self._now(),
                    by,
                    draft.follow_up,
                    draft.follow_up_by,
                    note_id,
                ),  # fmt: skip
            ).rowcount
        return self.get(note_id) if changed else None

    def follow_ups(self) -> list[dict[str, Any]]:
        """The notes that ask for a follow-up, by day."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM notes WHERE follow_up IS NOT NULL ORDER BY follow_up, note_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def delete(self, note_id: str) -> bool:
        with self._lock, self._connect() as connection:
            return (
                connection.execute("DELETE FROM notes WHERE note_id = ?", (note_id,)).rowcount > 0
            )
