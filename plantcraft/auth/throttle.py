"""Failed sign-ins, kept in the database, and how long the next try has to wait.

In the database, not in memory, so every server process counts the same attempts and a flood of
made-up usernames cannot grow a process's memory: rows older than the window are deleted as new
ones arrive.

Two kinds of key (``plantcraft.api.routers.session``):

- ``pair:<username>|<address>``: the same name from the same address. The first
  ``PAIR_FREE`` failures cost nothing; each one after doubles the wait (``PAIR_FIRST_WAIT``
  seconds, then twice that, up to ``PAIR_MAX_WAIT``). A wrong password typed from one desk never
  locks the same person out at another, and nobody can lock the administrator out from afar.
- ``addr:<address>``: every name from one address. ``ADDRESS_LIMIT`` failures in the window
  stop that address until the oldest one leaves the window, which ends spraying many names
  without blocking a whole plant that leaves through one address for a few typos.
"""

from __future__ import annotations

import time
from collections.abc import Iterable

from plantcraft.db import Database, Store

WINDOW_SECONDS = 900
PAIR_FREE = 5
PAIR_FIRST_WAIT = 15.0
PAIR_MAX_WAIT = 900.0
ADDRESS_LIMIT = 100
# Failures one name may have from one address before waiting (older name kept for callers).
LIMIT = PAIR_FREE


def pair_key(username: str, address: str) -> str:
    return f"pair:{username.lower()[:200]}|{address[:100]}"


def address_key(address: str) -> str:
    return f"addr:{address[:100]}"


class LoginThrottle(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS login_failures (
        key TEXT NOT NULL,
        at REAL NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_login_failures_key ON login_failures(key, at);
    """

    def __init__(
        self,
        db: Database,
        *,
        window: float = WINDOW_SECONDS,
        pair_free: int = PAIR_FREE,
        address_limit: int = ADDRESS_LIMIT,
    ):
        super().__init__(db)
        self.window = window
        self.pair_free = pair_free
        self.address_limit = address_limit

    def wait(self, keys: Iterable[str], now: float | None = None) -> float:
        """Seconds before another try is allowed (0: allowed now)."""

        now = time.time() if now is None else now
        since = now - self.window
        longest = 0.0
        with self._lock, self._connect() as connection:
            for key in keys:
                times = [
                    row[0]
                    for row in connection.execute(
                        "SELECT at FROM login_failures WHERE key = ? AND at > ? ORDER BY at",
                        (key, since),
                    )
                ]
                if key.startswith("addr:"):
                    if len(times) >= self.address_limit:
                        longest = max(longest, times[-self.address_limit] + self.window - now)
                elif len(times) >= self.pair_free:
                    extra = len(times) - self.pair_free
                    pause = min(PAIR_FIRST_WAIT * 2**extra, PAIR_MAX_WAIT)
                    longest = max(longest, times[-1] + pause - now)
        return max(longest, 0.0)

    def blocked(self, keys: Iterable[str], now: float | None = None) -> bool:
        """True when any key has to wait before another try."""

        return self.wait(keys, now) > 0

    def record(self, keys: Iterable[str], now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock, self._write() as connection:
            connection.execute("DELETE FROM login_failures WHERE at <= ?", (now - self.window,))
            connection.executemany(
                "INSERT INTO login_failures (key, at) VALUES (?, ?)", [(key, now) for key in keys]
            )
