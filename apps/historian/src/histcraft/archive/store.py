"""The archive database: chunks of archived values, snapshots and the collector's state.

Only the collector writes these tables (docs/boundary.md); the server reads them.
Each flush adds one chunk per point with the values archived since the last
flush; ``compact`` later merges a point's small chunks into larger ones (up to
``CHUNK_VALUES`` values) by tiers of time: a closed hour, then day, then month, so a year of one
point is a few hundred rows and a value is rewritten three times at most.

``rollups`` keep, per point and hour, the time with data and the integral of the rebuilt
signal, the lowest and highest value and the values archived (``archive.rollup``): a year-long
trend on an hourly or coarser grid, its min/max band and a window's mean, min or max read them
instead of every chunk. Every write here drops the hours it may change; the collector fills
them again.

In PostgreSQL ``chunks`` and ``rollups`` are partitioned by month (``archive.partitions``):
retention drops a past month whose every value is past it, instead of deleting row by row.

``point_totals`` holds what the archive keeps of each point (chunks, values, bytes, first and
last time), refreshed by the collector every few minutes (``refresh_totals``) so a page never
scans the whole archive; ``point_hours`` counts the values written per point and hour of their
time, kept a week, for "values per day".

``run_series`` holds the points of kind ``runs`` (H2): one compressed row per execution of an
app (``run_at``, the run's time), each a whole series of its own. A point keeps its newest
``keep`` runs (the write prunes the rest) and retention drops runs older than its cutoff.

``recent`` holds what the collector archived since its last flush to ``chunks``: one row per
write (every few seconds), every point's new values in one blob (``codec.encode_batch``), so a
write is one statement whatever the number of points. Once a minute ``settle`` moves them into
``chunks`` (one chunk per point, a few statements for all points) and deletes the rows; reads
add them to the chunks (``read_many``), so they reach the present all the same. The rows of a
stopped collector stay and are settled by the next one.

Points are referred to by their integer id from the configuration database.

This module holds the schema and puts ``ArchiveStore`` together; its methods live by
responsibility in ``archive.writing``, ``archive.reading``, ``archive.compaction``,
``archive.retention`` and ``archive.rollup_store``, with what they share in ``archive.common``.
The names other modules import from here stay here.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable
from typing import Any

import numpy as np

from histcraft.archive import partitions
from histcraft.archive.common import CHUNK_VALUES, COUNT_HOURS, DAY_MS, HOUR_MS
from histcraft.archive.compaction import COMPACT_BATCH, COMPACT_CHUNKS, Compaction, compaction_start
from histcraft.archive.reading import Reading
from histcraft.archive.retention import DELETE_BATCH, DELETE_TRIES, Retention
from histcraft.archive.rollup_store import Rollups
from histcraft.archive.writing import Writing
from histcraft.clock import now_ms
from histcraft.db import Database, Store, _postgres_schema

# The names other modules import from here, from before the store was split.
__all__ = [
    "CHUNK_VALUES",
    "COMPACT_BATCH",
    "COMPACT_CHUNKS",
    "COUNT_HOURS",
    "DAY_MS",
    "DELETE_BATCH",
    "DELETE_TRIES",
    "HOUR_MS",
    "ArchiveStore",
    "compaction_start",
    "now_ms",
]


_CHUNKS = """
    CREATE TABLE IF NOT EXISTS chunks (
        point INTEGER NOT NULL,
        t0 INTEGER NOT NULL,
        t1 INTEGER NOT NULL,
        n INTEGER NOT NULL,
        data BLOB NOT NULL,
        PRIMARY KEY(point, t0)
    )"""
_ROLLUPS = """
    CREATE TABLE IF NOT EXISTS rollups (
        point INTEGER NOT NULL,
        hour INTEGER NOT NULL,
        step INTEGER NOT NULL,
        cover REAL NOT NULL,
        area REAL NOT NULL,
        PRIMARY KEY(point, hour)
    )"""


class ArchiveStore(Writing, Reading, Compaction, Retention, Rollups, Store):
    SCHEMA = (
        f"{_CHUNKS} WITHOUT ROWID;\n{_ROLLUPS} WITHOUT ROWID;\n"
        + """

    -- Daily (level 1) and monthly (level 2) rollups (H9): a day's hourly rows and a month's
    -- daily rows summed, ``[t0, t1)`` the UTC day or month. Each level has its own retention,
    -- longer than the raw values' (``archive.rollup``).
    CREATE TABLE IF NOT EXISTS rollups_coarse (
        point INTEGER NOT NULL,
        level INTEGER NOT NULL,
        t0 INTEGER NOT NULL,
        t1 INTEGER NOT NULL,
        step INTEGER NOT NULL,
        cover REAL NOT NULL,
        area REAL NOT NULL,
        low REAL,
        high REAL,
        n INTEGER NOT NULL,
        PRIMARY KEY(point, level, t0)
    );

    CREATE TABLE IF NOT EXISTS snapshots (
        point INTEGER PRIMARY KEY,
        ts INTEGER,
        value {ANY},
        status TEXT NOT NULL DEFAULT 'ok',
        detail TEXT NOT NULL DEFAULT '',
        reads INTEGER NOT NULL DEFAULT 0,
        archived INTEGER NOT NULL DEFAULT 0,
        updated INTEGER NOT NULL
    );

    -- Where a point's quality changed (G5): the quality holds from t to the next row; a point
    -- with no row before a time is good there. Rare rows: only changes are kept.
    CREATE TABLE IF NOT EXISTS qualities (
        point INTEGER NOT NULL,
        t INTEGER NOT NULL,
        quality TEXT NOT NULL,
        PRIMARY KEY(point, t)
    );

    CREATE TABLE IF NOT EXISTS point_totals (
        point INTEGER PRIMARY KEY,
        chunks INTEGER NOT NULL,
        n INTEGER NOT NULL,
        bytes INTEGER NOT NULL,
        first INTEGER,
        last INTEGER
    );

    -- Values written per point and hour of their time (a rewrite counts again); a week kept.
    CREATE TABLE IF NOT EXISTS point_hours (
        point INTEGER NOT NULL,
        hour INTEGER NOT NULL,
        n INTEGER NOT NULL,
        PRIMARY KEY(point, hour)
    );

    -- A runs point's executions (H2): t0, t1 the run's first and last time, data its series.
    CREATE TABLE IF NOT EXISTS run_series (
        point INTEGER NOT NULL,
        run_at INTEGER NOT NULL,
        t0 INTEGER NOT NULL,
        t1 INTEGER NOT NULL,
        n INTEGER NOT NULL,
        data BLOB NOT NULL,
        PRIMARY KEY(point, run_at)
    );

    -- Values the collector archived since its last flush to chunks (``hold``, ``settle``):
    -- one row per write, ``at`` its order, ``data`` every point's values (codec.encode_batch).
    CREATE TABLE IF NOT EXISTS recent (
        at INTEGER PRIMARY KEY,
        data BLOB NOT NULL
    );

    CREATE TABLE IF NOT EXISTS collector_state (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    -- A laboratory point's samples (lab:<analysis>): the value lives in chunks at the sampling
    -- time ``t``; here when it reached the laboratory and was approved, its status, when it was
    -- written here and by whom, and how many times it was written (a retest writes again).
    CREATE TABLE IF NOT EXISTS lab_samples (
        point INTEGER NOT NULL,
        t INTEGER NOT NULL,
        received INTEGER,
        approved INTEGER,
        status TEXT NOT NULL,
        written INTEGER NOT NULL,
        author TEXT NOT NULL DEFAULT '',
        writes INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY(point, t)
    );

    -- People's edits of archived values (H7): each value inserted, edited or deleted by hand,
    -- with the value it replaced (JSON, NULL when there was none), who and when, and why.
    -- The value read carries the mark; the original stays here.
    CREATE TABLE IF NOT EXISTS edits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        point INTEGER NOT NULL,
        t INTEGER NOT NULL,
        action TEXT NOT NULL,
        old_value TEXT,
        new_value TEXT,
        author TEXT NOT NULL DEFAULT '',
        at INTEGER NOT NULL,
        reason TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS edits_point_t ON edits (point, t);

    CREATE TABLE IF NOT EXISTS request_results (
        id INTEGER PRIMARY KEY,
        status TEXT NOT NULL,
        result TEXT NOT NULL,
        finished INTEGER NOT NULL
    );
    """
    )
    # Historian 0.5: each hour's lowest and highest value and how many values it holds. Rows
    # written before have none: ``rollup.build`` computes those hours again.
    COLUMNS = (
        ("rollups", "low", "REAL"),
        ("rollups", "high", "REAL"),
        ("rollups", "n", "INTEGER"),
        # The source's whole status code at a change of quality (OPC UA sub-code and LimitBits,
        # H6, ``histcraft.opc_status``); NULL when it said nothing more than the quality.
        ("qualities", "status", "BIGINT"),
        ("qualities", "status_name", "TEXT"),
    )

    def __init__(self, db: Database):
        # Decoded ``recent`` rows by ``at``: a row never changes, so each process decodes it once.
        self._recent: dict[int, dict[int, tuple[str, np.ndarray, Any]]] = {}
        self._recent_lock = threading.Lock()
        # Values per (point, hour) settled and not yet in ``point_hours`` (``settle``).
        self._counts: dict[tuple[int, int], int] = {}
        self._counted = time.monotonic()
        self.partitions = partitions.Partitions(db) if db.postgres else None
        if db.postgres:
            db.once(
                "ArchiveStore:partitions",
                lambda: partitions.prepare(
                    db, {"chunks": _postgres_schema(_CHUNKS), "rollups": _postgres_schema(_ROLLUPS)}
                ),
            )
        super().__init__(db)
        if db.postgres:
            db.once("ArchiveStore:unlogged", self._unlogged_snapshots)

    def _unlogged_snapshots(self) -> None:
        """``snapshots`` is UNLOGGED in PostgreSQL: the collector rewrites every point's row
        every few seconds, and logging those writes was most of the archive's WAL (a few GB a
        day per 1,000 points, for a row that is stale 5 s later). A crash or a restored
        ``pg_basebackup`` empties it: the next flush writes the live points again and
        ``refill_snapshots`` the others (imports, apps' series) from the archive."""

        with self._lock, self._connect() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(?)", (partitions.SCHEMA_LOCK,))
            row = connection.execute(
                "SELECT relpersistence FROM pg_class WHERE oid = to_regclass('snapshots')"
            ).fetchone()
            if row is not None and row[0] == "p":
                connection.execute("ALTER TABLE snapshots SET UNLOGGED")

    def _ensure(self, table: str, times: Iterable[int]) -> None:
        if self.partitions is not None:
            self.partitions.ensure(table, times)

    def _writing(self, write: Any) -> Any:
        return write() if self.partitions is None else self.partitions.writing(write)
