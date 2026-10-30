"""What each asset import changed, so the last one can be undone (importing a
file into a plant already set up must never leave it worse with no way back).

``platform/assetfile.py`` writes one row per applied import: the assets it created, the values
it overwrote, the signals it bound and the relations it added. ``undo`` there reads it back.
"""

from __future__ import annotations

from typing import Any

from plantcraft.db import Store


class AssetImportStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS asset_imports (
        import_id INTEGER PRIMARY KEY AUTOINCREMENT,
        at TEXT NOT NULL,
        actor TEXT NOT NULL,
        summary_json TEXT NOT NULL DEFAULT '{}',
        undo_json TEXT NOT NULL,
        undone_at TEXT,
        undone_by TEXT
    );
    """

    def record(self, actor: str, summary: dict[str, Any], undo: dict[str, Any]) -> int:
        with self._lock, self._write() as connection:
            cursor = connection.execute(
                "INSERT INTO asset_imports (at, actor, summary_json, undo_json) VALUES (?, ?, ?, ?)",
                (self._now(), actor, self._json(summary), self._json(undo)),
            )
        return int(cursor.lastrowid)

    def last(self) -> dict[str, Any] | None:
        """The newest import, with what undoing it would take back."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM asset_imports ORDER BY import_id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return {
            "import_id": row["import_id"],
            "at": row["at"],
            "actor": row["actor"],
            "summary": self._loads(row["summary_json"], {}),
            "undo": self._loads(row["undo_json"], {}),
            "undone_at": row["undone_at"],
            "undone_by": row["undone_by"],
        }

    def mark_undone(self, import_id: int, actor: str) -> None:
        with self._lock, self._write() as connection:
            connection.execute(
                "UPDATE asset_imports SET undone_at = ?, undone_by = ? WHERE import_id = ?",
                (self._now(), actor, import_id),
            )
