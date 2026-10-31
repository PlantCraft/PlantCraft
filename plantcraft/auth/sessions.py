"""Sessions that were signed out, so their cookie stops working at once.

The session lives in a signed cookie (Starlette's ``SessionMiddleware``); the server keeps no copy,
so without this list a cookie copied before sign-out would keep working until it expires
(``PLANTCRAFT_SESSION_DAYS``). Every sign-in gives the session a random id (``cpm_sid``); sign-out
writes it here until the cookie would have expired anyway, and ``api.deps.session_user`` refuses a
session whose id is here. Rows past their expiry are deleted as new ones arrive.

The browser's 12-minute token carries the SHA-256 of the session id (``sid`` claim). The apps read
the sessions ended in the last 12 minutes from ``GET /api/v1/auth/revoked`` (``ended_since``), so a
token copied before sign-out stops opening them within seconds too.
"""

from __future__ import annotations

import hashlib
import secrets
import time

from plantcraft.db import Migration, Store, add_columns


def new_session_id() -> str:
    return secrets.token_urlsafe(18)


def session_digest(sid: str) -> str:
    """How tokens and the revocation list name a session: never the id itself."""

    return hashlib.sha256(sid[:64].encode("utf-8")).hexdigest()


class EndedSessions(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS ended_sessions (
        sid TEXT PRIMARY KEY,
        until REAL NOT NULL
    );
    """
    # When it ended and its digest, for the apps' revocation list (2026-10-31).
    MIGRATIONS = (
        Migration(
            "ended-at",
            add_columns(
                "ended_sessions",
                {"ended_at": "REAL NOT NULL DEFAULT 0", "digest": "TEXT NOT NULL DEFAULT ''"},
            ),
        ),
    )

    def end(self, sid: str, lasts_seconds: float, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock, self._write() as connection:
            connection.execute("DELETE FROM ended_sessions WHERE until <= ?", (now,))
            connection.execute(
                """INSERT OR REPLACE INTO ended_sessions (sid, until, ended_at, digest)
                   VALUES (?, ?, ?, ?)""",
                (sid[:64], now + lasts_seconds, now, session_digest(sid)),
            )

    def ended(self, sid: str) -> bool:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM ended_sessions WHERE sid = ?", (sid[:64],)
            ).fetchone()
        return row is not None

    def digest_ended(self, digest: str) -> bool:
        """Whether the session a token names (``sid`` claim) was signed out."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM ended_sessions WHERE digest = ? AND digest != ''", (digest[:64],)
            ).fetchone()
        return row is not None

    def ended_since(self, moment: float) -> list[tuple[str, int]]:
        """``(digest, ended_at)`` of the sessions signed out after ``moment``."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """SELECT digest, ended_at FROM ended_sessions
                   WHERE ended_at >= ? AND digest != '' ORDER BY ended_at""",
                (moment,),
            ).fetchall()
        return [(str(row[0]), int(row[1])) for row in rows]
