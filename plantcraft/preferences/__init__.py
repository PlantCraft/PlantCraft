"""What each person arranges for themselves: the widgets of their Overview, in their order.

One row per (person, key), the value a small JSON document replaced on every write.
"""

from __future__ import annotations

from typing import Any

from plantcraft.db import Store

MAX_BYTES = 8000


class PreferenceStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS user_preferences (
        username TEXT NOT NULL,
        key TEXT NOT NULL,
        value_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (username, key)
    );
    """

    def get(self, username: str, key: str) -> Any:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM user_preferences WHERE username = ? AND key = ?",
                (username, key),
            ).fetchone()
        return self._loads(row["value_json"], None) if row else None

    def put(self, username: str, key: str, value: Any) -> None:
        text = self._json(value)
        if len(text.encode()) > MAX_BYTES:
            raise ValueError("preference too large")
        with self._lock, self._write() as connection:
            connection.execute(
                "INSERT INTO user_preferences (username, key, value_json, updated_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(username, key) DO UPDATE SET "
                "value_json = excluded.value_json, updated_at = excluded.updated_at",
                (username, key, text, self._now()),
            )

    def delete(self, username: str, key: str) -> None:
        with self._lock, self._write() as connection:
            connection.execute(
                "DELETE FROM user_preferences WHERE username = ? AND key = ?", (username, key)
            )
