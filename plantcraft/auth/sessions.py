"""Sessions that were signed out, so their cookie stops working at once.

The session lives in a signed cookie (Starlette's ``SessionMiddleware``); the server keeps no copy,
so without this list a cookie copied before sign-out would keep working until it expires
(``PLANTCRAFT_SESSION_DAYS``). Every sign-in gives the session a random id (``cpm_sid``); sign-out
writes it here until the cookie would have expired anyway, and ``api.deps.session_user`` refuses a
session whose id is here. Rows past their expiry are deleted as new ones arrive.
"""

from __future__ import annotations

import secrets
import time

from plantcraft.db import Store


def new_session_id() -> str:
    return secrets.token_urlsafe(18)


class EndedSessions(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS ended_sessions (
        sid TEXT PRIMARY KEY,
        until REAL NOT NULL
    );
    """

    def end(self, sid: str, lasts_seconds: float, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock, self._write() as connection:
            connection.execute("DELETE FROM ended_sessions WHERE until <= ?", (now,))
            connection.execute(
                "INSERT OR REPLACE INTO ended_sessions (sid, until) VALUES (?, ?)",
                (sid[:64], now + lasts_seconds),
            )

    def ended(self, sid: str) -> bool:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM ended_sessions WHERE sid = ?", (sid[:64],)
            ).fetchone()
        return row is not None
