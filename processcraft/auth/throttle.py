"""Failed sign-ins per username and per address, kept in the database.

In the database, not in memory, so every server process counts the same attempts and a flood of
made-up usernames cannot grow a process's memory: rows older than the window are deleted as new
ones arrive.
"""

from __future__ import annotations

import time
from collections.abc import Iterable

from processcraft.db import Database, Store

WINDOW_SECONDS = 300
LIMIT = 10


class LoginThrottle(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS login_failures (
        key TEXT NOT NULL,
        at REAL NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_login_failures_key ON login_failures(key, at);
    """

    def __init__(self, db: Database, *, window: float = WINDOW_SECONDS, limit: int = LIMIT):
        super().__init__(db)
        self.window = window
        self.limit = limit

    def blocked(self, keys: Iterable[str], now: float | None = None) -> bool:
        """True when any key failed ``limit`` times within the window."""

        since = (time.time() if now is None else now) - self.window
        keys = list(keys)
        with self._lock, self._connect() as connection:
            for key in keys:
                count = connection.execute(
                    "SELECT COUNT(*) FROM login_failures WHERE key = ? AND at > ?", (key, since)
                ).fetchone()[0]
                if count >= self.limit:
                    return True
        return False

    def record(self, keys: Iterable[str], now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock, self._write() as connection:
            connection.execute("DELETE FROM login_failures WHERE at <= ?", (now - self.window,))
            connection.executemany(
                "INSERT INTO login_failures (key, at) VALUES (?, ?)", [(key, now) for key in keys]
            )
