"""Shared SQLite database and the base class for module stores.

Every module owns its tables and declares them in a ``SCHEMA`` string. The
``Database`` applies each module schema once, in dependency order, so a fresh
file and an existing installation converge on the same structure.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path

from plantcraft_sdk.server.store import Database as _AppDatabase
from plantcraft_sdk.server.store import Migration as Migration  # stores import these from here
from plantcraft_sdk.server.store import Store as _AppStore
from plantcraft_sdk.server.store import add_columns as add_columns
from plantcraft_sdk.server.store import journal_mode
from plantcraft_sdk.utc import normalize_times as _normalize
from plantcraft_sdk.utc import utc_iso

_CLOCK: ContextVar[datetime | None] = ContextVar("processcraft_clock", default=None)


@contextmanager
def recorded_at(moment: datetime) -> Iterator[None]:
    """Stamp every row written in this block with ``moment`` (demo story only)."""

    token = _CLOCK.set(moment)
    try:
        yield
    finally:
        _CLOCK.reset(token)


def utc_text(value: datetime | str | None = None) -> str:
    """``value`` (now without it, or the demo's clock) as ``2026-10-23T14:05:09.123Z``
    (``plantcraft_sdk.utc``): every time PlantCraft stores or answers is in that form."""

    return utc_iso(_CLOCK.get() if value is None else value)


def normalize_times(db: Database) -> int:
    """Rewrite, once, the instants stored before 2026-10-23 with the server's local offset."""

    with db.lock, db.write() as connection:
        return _normalize(connection)


class Database(_AppDatabase):
    """One SQLite file shared by all module stores of an installation.

    Several server processes may open it at once (``PLANTCRAFT_WORKERS``, docs/operations.md):
    the file is in WAL mode, so readers never wait for a writer, and ``self.lock`` only orders the
    threads of one process. Writers of every process take turns through SQLite itself: a block
    that writes opens its transaction with ``BEGIN IMMEDIATE`` (``write``), so what it read and
    what it writes stay one step even with another process writing, and a busy file is waited
    for (``busy_timeout``) instead of failing.

    The SDK's ``Database`` (an app's own file) with PlantCraft's differences: no schema stamp, the
    UTC rewrite is ``normalize_times`` (run by the server once), and writes take the lock at once.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._applied: set[str] = set()
        self._idle = threading.local()

    def connect(self) -> sqlite3.Connection:
        """A connection of this thread that no block is using, or a new one.

        A request asks the stores for 20 to 40 connections (the user, their groups, the apps,
        the feed...), and opening one costs about a millisecond of CPU: a third of PlantCraft's
        time under load (load test, 2026-10-27). A block that ends (``with``, ``close``) gives
        its connection back to its thread, rolled back if it left a transaction open; a block
        inside another gets its own, as before."""

        idle: list[_Pooled] = self._idle.__dict__.setdefault("connections", [])
        while idle:
            connection = idle.pop()
            try:
                connection.reuse()
                return connection
            except sqlite3.Error:
                connection.close_for_good()
        connection = sqlite3.connect(self.path, timeout=30, factory=_Pooled)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute(f"PRAGMA journal_mode = {journal_mode(self.path.parent)}")
        connection.idle = idle
        connection.reuse()
        return connection

    def write(self) -> sqlite3.Connection:
        """A connection already in a write transaction: for a block that reads, then writes."""

        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
        except sqlite3.Error:
            connection.close()
            raise
        return connection


class _Pooled(sqlite3.Connection):
    """A connection that goes back to its thread's idle list when its block ends."""

    # Idle connections kept per thread beyond the ones in use.
    KEEP = 4
    idle: list[_Pooled] | None = None

    def reuse(self) -> None:
        self.row_factory = sqlite3.Row
        # A transaction Python opens before a write takes the write lock at once (never a read
        # snapshot that another process's commit would make stale).
        self.isolation_level = "IMMEDIATE"
        self.taken = True

    def __exit__(self, *exc: object) -> bool:
        result = super().__exit__(*exc)
        self.close()
        return result

    def close(self) -> None:
        if not getattr(self, "taken", False):
            return
        self.taken = False
        try:
            if self.in_transaction:
                self.rollback()
        except sqlite3.Error:
            self.close_for_good()
            return
        if self.idle is not None and len(self.idle) < self.KEEP:
            self.idle.append(self)
        else:
            self.close_for_good()

    def close_for_good(self) -> None:
        self.taken = False
        super().close()


class Store(_AppStore):
    """Base class giving module stores the shared connection helpers (the SDK's ``Store``, with
    PlantCraft's clock and ``_write``)."""

    db: Database

    def _write(self) -> sqlite3.Connection:
        """``_connect`` for a block that writes (``Database.write``)."""

        return self.db.write()

    @classmethod
    def _now(cls) -> str:
        return utc_text()
