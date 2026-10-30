"""How much one person may ask API v1 for at once: requests per minute and reads in flight.

Notebooks, scripts on a person's computer and assistants read the plant through API v1 with that
person's own access (docs/en/notebooks.md). A loop that asks for a year of a hundred signals,
again and again, must slow down that person alone: never Link, Alarms or the other apps, whose
own requests are never counted here (``plantcraft.api.usage`` says which requests count).

In the database, not in memory, so every server process counts the same requests (a browser
keeps one connection, which lands on one process, while a script's may land on any). One row per
request in ``usage_slots``: ``finished`` stays empty while it runs. Rows older than two minutes
are deleted as new ones arrive, and a row a crashed process left open stops counting after
``STALE_SECONDS``.
"""

from __future__ import annotations

import math
import secrets
import time
from dataclasses import dataclass
from typing import Any

from plantcraft.db import Database, Store

WINDOW_SECONDS = 60.0
# A request that has not finished after this long no longer holds its place (a dead process).
STALE_SECONDS = 300.0
DEFAULT_PER_MINUTE = 120
DEFAULT_CONCURRENT = 2
PER_MINUTE_RANGE = (10, 6000)
CONCURRENT_RANGE = (1, 32)


@dataclass(frozen=True)
class Refusal:
    """Why a request waits: ``rate`` (too many this minute) or ``busy`` (too many at once)."""

    reason: str
    retry_after: int


class UsageStore(Store):
    """The installation's limits (one row) and the requests being counted."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS usage_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        per_minute INTEGER NOT NULL,
        concurrent INTEGER NOT NULL,
        updated_by TEXT,
        updated_at TEXT
    );

    CREATE TABLE IF NOT EXISTS usage_slots (
        slot_id TEXT PRIMARY KEY,
        key TEXT NOT NULL,
        started REAL NOT NULL,
        finished REAL
    );

    CREATE INDEX IF NOT EXISTS idx_usage_slots_key ON usage_slots(key, started);
    """

    def __init__(self, db: Database):
        super().__init__(db)

    # Settings -------------------------------------------------------------------------

    def settings(self) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM usage_settings WHERE id = 1").fetchone()
        stored = dict(row) if row else {}
        return {
            "per_minute": int(stored.get("per_minute") or DEFAULT_PER_MINUTE),
            "concurrent": int(stored.get("concurrent") or DEFAULT_CONCURRENT),
            "default_per_minute": DEFAULT_PER_MINUTE,
            "default_concurrent": DEFAULT_CONCURRENT,
            "updated_by": stored.get("updated_by"),
            "updated_at": stored.get("updated_at"),
        }

    def save_settings(self, *, per_minute: int, concurrent: int, actor: str) -> dict[str, Any]:
        """Raises ValueError for a value outside ``PER_MINUTE_RANGE`` or ``CONCURRENT_RANGE``."""

        low, high = PER_MINUTE_RANGE
        if not low <= per_minute <= high:
            raise ValueError("per_minute")
        low, high = CONCURRENT_RANGE
        if not low <= concurrent <= high:
            raise ValueError("concurrent")
        with self._lock, self._write() as connection:
            connection.execute(
                """
                INSERT INTO usage_settings (id, per_minute, concurrent, updated_by, updated_at)
                VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET per_minute = excluded.per_minute,
                    concurrent = excluded.concurrent, updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
                (per_minute, concurrent, actor, self._now()),
            )
        return self.settings()

    # Counting -------------------------------------------------------------------------

    def begin(
        self, key: str, *, per_minute: int, concurrent: int, now: float | None = None
    ) -> str | Refusal:
        """A slot id for a request that may run now, else why it waits and for how long."""

        now = time.time() if now is None else now
        since = now - WINDOW_SECONDS
        with self._lock, self._write() as connection:
            connection.execute(
                "DELETE FROM usage_slots WHERE started <= ? AND (finished IS NOT NULL OR started <= ?)",
                (now - 2 * WINDOW_SECONDS, now - STALE_SECONDS),
            )
            running = connection.execute(
                "SELECT COUNT(*) FROM usage_slots WHERE key = ? AND finished IS NULL AND started > ?",
                (key, now - STALE_SECONDS),
            ).fetchone()[0]
            if running >= concurrent:
                return Refusal("busy", 1)
            recent = connection.execute(
                "SELECT started FROM usage_slots WHERE key = ? AND started > ? ORDER BY started",
                (key, since),
            ).fetchall()
            if len(recent) >= per_minute:
                # Free again when the oldest request of the minute leaves the window.
                oldest = float(recent[len(recent) - per_minute]["started"])
                return Refusal("rate", max(1, math.ceil(oldest + WINDOW_SECONDS - now)))
            slot = secrets.token_hex(8)
            connection.execute(
                "INSERT INTO usage_slots (slot_id, key, started) VALUES (?, ?, ?)", (slot, key, now)
            )
        return slot

    def end(self, slot: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock, self._write() as connection:
            connection.execute("UPDATE usage_slots SET finished = ? WHERE slot_id = ?", (now, slot))
