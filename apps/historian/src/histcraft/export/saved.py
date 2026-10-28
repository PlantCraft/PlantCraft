"""Saved exports: a choice of tags (and the assets they came from), a period and a resolution,
kept under a name to run again later ("the same package for the last day"), as View keeps
trends. A relative period ("last 24 hours") reads up to the moment it runs."""

from __future__ import annotations

import secrets
from typing import Any

from histcraft.db import Store


class SavedExports(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS saved_exports (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        payload TEXT NOT NULL,
        created_by TEXT NOT NULL DEFAULT '',
        updated_by TEXT NOT NULL DEFAULT '',
        created TEXT NOT NULL,
        updated TEXT NOT NULL
    );
    """
    TIMES = (("saved_exports", "id", ("created", "updated")),)

    def list(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM saved_exports ORDER BY name").fetchall()
        return [self._item(row) for row in rows]

    def get(self, export_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM saved_exports WHERE id = ?", (export_id,)
            ).fetchone()
        return self._item(row) if row else None

    def create(self, name: str, payload: dict[str, Any], user: str) -> dict[str, Any]:
        export_id = secrets.token_hex(6)
        now = self._now()
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO saved_exports VALUES (?, ?, ?, ?, ?, ?, ?)",
                (export_id, name, self._json(payload), user, user, now, now),
            )
        return self.get(export_id) or {}

    def update(
        self, export_id: str, name: str, payload: dict[str, Any], user: str
    ) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            changed = connection.execute(
                "UPDATE saved_exports SET name = ?, payload = ?, updated_by = ?, updated = ?"
                " WHERE id = ?",
                (name, self._json(payload), user, self._now(), export_id),
            ).rowcount
        return self.get(export_id) if changed else None

    def delete(self, export_id: str) -> bool:
        with self._lock, self._connect() as connection:
            return bool(
                connection.execute("DELETE FROM saved_exports WHERE id = ?", (export_id,)).rowcount
            )

    def _item(self, row: Any) -> dict[str, Any]:
        item = dict(row)
        payload = self._loads(item.pop("payload"), {})
        return {**payload, **item}
