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
"""

from __future__ import annotations

import json
import math
import threading
import time
from collections.abc import Iterable
from typing import Any

import numpy as np

from histcraft.archive import codec, partitions
from histcraft.clock import now_ms
from histcraft.db import Database, Store, _postgres_schema

CHUNK_VALUES = 10_000
# Points compacted per transaction.
COMPACT_BATCH = 200
# Small chunks whose bytes are held at once while they merge: a point's backlog (90 days of
# minute chunks after a backfill is 130,000 of them) goes in steps, never all in memory.
COMPACT_CHUNKS = 20_000
HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS
# Hours of ``point_hours`` kept: a week, for "values per day" and its trend.
COUNT_HOURS = 7 * 24
_COUNT = (
    "INSERT INTO point_hours VALUES (?, ?, ?) ON CONFLICT(point, hour) DO UPDATE"
    " SET n = point_hours.n + excluded.n"
)
# Hours an append may change: from the hour of the stored value before its first one (the
# segment from there to the new value is rebuilt) on: the start of a stored chunk that holds
# it, else the end of the last chunk before.
# The rollups a flush changes: from the hour before the stored value just ahead of the new ones,
# the end of the last chunk before them or the start of the one they fall in (chunks of a point
# never overlap). Only the last chunk starting before them is read, through the primary key, so a
# flush costs the same with 10 or 10,000 chunks per point still waiting for compaction.
_DROP_ROLLUPS = (
    "DELETE FROM rollups WHERE point = ? AND hour > COALESCE("
    "(SELECT CASE WHEN t1 >= ? THEN t0 ELSE t1 END FROM chunks WHERE point = ? AND t0 < ?"
    " ORDER BY t0 DESC LIMIT 1), ?) - 3600000"
)


# The same for many points in one statement (PostgreSQL): the bound of each point first, then
# its rollups past it, through the primary key.
_DROP_ROLLUPS_MANY = """
    WITH f AS (
        SELECT p.point, COALESCE((
            SELECT CASE WHEN c.t1 >= p.first THEN c.t0 ELSE c.t1 END FROM chunks c
            WHERE c.point = p.point AND c.t0 < p.first ORDER BY c.t0 DESC LIMIT 1
        ), p.first) - 3600000 AS low
        FROM unnest(?::bigint[], ?::bigint[]) AS p(point, first)
    )
    DELETE FROM rollups r USING f WHERE r.point = f.point AND r.hour > f.low
"""
_PUT_CHUNK = (
    "INSERT INTO chunks VALUES (?, ?, ?, ?, ?) ON CONFLICT(point, t0) DO UPDATE"
    " SET t1 = excluded.t1, n = excluded.n, data = excluded.data"
)
_PUT_CHUNKS_MANY = (
    "INSERT INTO chunks SELECT * FROM unnest(?::bigint[], ?::bigint[], ?::bigint[], ?::bigint[],"
    " ?::bytea[]) ON CONFLICT(point, t0) DO UPDATE"
    " SET t1 = excluded.t1, n = excluded.n, data = excluded.data"
)
_COUNT_MANY = (
    "INSERT INTO point_hours SELECT * FROM unnest(?::bigint[], ?::bigint[], ?::bigint[])"
    " ON CONFLICT(point, hour) DO UPDATE SET n = point_hours.n + excluded.n"
)


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


class ArchiveStore(Store):
    SCHEMA = (
        f"{_CHUNKS} WITHOUT ROWID;\n{_ROLLUPS} WITHOUT ROWID;\n"
        + """

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

    # Writes (collector only) -------------------------------------------------------

    def append(self, batch: dict[int, tuple[str, list[tuple[int, Any]]]]) -> int:
        """Store each point's newly archived ``(ms, value)`` pairs as one chunk; values written."""

        return self._writing(lambda: self._append(batch))

    def _append(self, batch: dict[int, tuple[str, list[tuple[int, Any]]]]) -> int:
        runs: dict[int, tuple[str, np.ndarray, Any]] = {}
        for point, (kind, samples) in batch.items():
            if samples:
                times = np.fromiter((at for at, _ in samples), dtype=np.int64, count=len(samples))
                runs[point] = (kind, times, [value for _, value in samples])
        with self._lock, self._connect() as connection:
            return self._append_runs(connection, runs)

    def _append_runs(
        self, connection: Any, runs: dict[int, tuple[str, np.ndarray, Any]], counted: bool = True
    ) -> int:
        """Store one chunk per point of ``runs`` (``point: (kind, times, values)``, in time
        order) inside an open transaction: a few statements for all points, not a few per
        point (PostgreSQL gets each table's rows as arrays, ``unnest``)."""

        if not runs:
            return 0
        written = sum(len(times) for _, times, _ in runs.values())
        firsts = {point: int(times[0]) for point, (_, times, _) in runs.items()}
        # A run starting where a stored chunk starts (a repeated flush) merges into it.
        for row in self._chunks_at(connection, list(firsts.items())):
            point = int(row["point"])
            if firsts.get(point) == int(row["t0"]):
                kind, times, values = runs[point]
                old_times, old_values = codec.decode(bytes(row["data"]))
                runs[point] = (kind, *_merge(old_times, list(old_values), times, list(values)))
        self._ensure("chunks", firsts.values())
        chunks = [
            (point, firsts[point], int(times[-1]), len(times), codec.encode(times, values, kind))
            for point, (kind, times, values) in runs.items()
        ]
        counts = _hour_counts_many(runs) if counted else []
        if self.db.postgres:
            connection.execute(_DROP_ROLLUPS_MANY, (_ints(firsts), _ints(firsts.values())))
            points, starts, ends, sizes, blobs = zip(*chunks)
            connection.execute(
                _PUT_CHUNKS_MANY,
                (_ints(points), _ints(starts), _ints(ends), _ints(sizes), _blobs(blobs)),
            )
            if counts:
                connection.execute(_COUNT_MANY, tuple(_ints(column) for column in zip(*counts)))
            return written
        connection.executemany(
            _DROP_ROLLUPS,
            [(point, first, point, first, first) for point, first in firsts.items()],
        )
        connection.executemany(_PUT_CHUNK, chunks)
        connection.executemany(_COUNT, counts)
        return written

    def _chunks_at(self, connection: Any, keys: list[tuple[int, int]]) -> list[Any]:
        """The stored chunks starting at ``(point, t0)`` of ``keys``."""

        if self.db.postgres:
            points, starts = zip(*keys)
            return connection.execute(
                "SELECT c.point, c.t0, c.data FROM unnest(?::bigint[], ?::bigint[]) AS k(point, t0)"
                " JOIN chunks c ON c.point = k.point AND c.t0 = k.t0",
                (_ints(points), _ints(starts)),
            ).fetchall()
        rows: list[Any] = []
        for offset in range(0, len(keys), 500):
            part = keys[offset : offset + 500]
            points = sorted({point for point, _ in part})
            starts = sorted({t0 for _, t0 in part})
            rows += connection.execute(
                f"SELECT point, t0, data FROM chunks WHERE point IN ({_marks(points)})"
                f" AND t0 IN ({_marks(starts)})",
                (*points, *starts),
            ).fetchall()
        return rows

    # The recent values (the collector's, between flushes to chunks) -----------------------

    def hold(self, batch: dict[int, tuple[str, list[tuple[int, Any]]]]) -> int:
        """Keep every point's newly archived ``(ms, value)`` pairs as one ``recent`` row (one
        statement, whatever the number of points); values kept. ``settle`` moves them into
        chunks."""

        kept = sum(len(samples) for _, samples in batch.values())
        if not kept:
            return 0
        blob = codec.encode_batch(batch)
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT MAX(at) AS at FROM recent").fetchone()
            at = max(now_ms(), int(row["at"] or 0) + 1)
            connection.execute("INSERT INTO recent VALUES (?, ?)", (at, blob))
        return kept

    def settle(self, count_every: float = 0.0) -> int:
        """Move every ``recent`` row into chunks, in one transaction; values moved.

        With ``count_every`` (seconds; the collector's settles, every minute) the values per
        point and hour add up in memory and go to ``point_hours`` that often only: rewriting
        each point's row of the hour every minute was a third of a settle's WAL. A crash
        loses those minutes of counts (a statistic, "values per day"), never a value."""

        return self._writing(lambda: self._settle(count_every))

    def _settle(self, count_every: float = 0.0) -> int:
        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT at, data FROM recent ORDER BY at").fetchall()
            if rows:
                runs = _settled(rows)
                written = self._append_runs(connection, runs, counted=False)
                for point, hour, n in _hour_counts_many(runs):
                    self._counts[(point, hour)] = self._counts.get((point, hour), 0) + n
                connection.execute("DELETE FROM recent WHERE at <= ?", (int(rows[-1]["at"]),))
            else:
                written = 0
            if self._counts and time.monotonic() - self._counted >= count_every:
                counts = [(point, hour, n) for (point, hour), n in self._counts.items()]
                if self.db.postgres:
                    connection.execute(_COUNT_MANY, tuple(_ints(column) for column in zip(*counts)))
                else:
                    connection.executemany(_COUNT, counts)
                self._counts.clear()
                self._counted = time.monotonic()
        return written

    def _recent_parts(self, connection: Any) -> list[dict[int, tuple[str, np.ndarray, Any]]]:
        """The ``recent`` rows, decoded, oldest first; each row is fetched once per process."""

        ats = [int(row["at"]) for row in connection.execute("SELECT at FROM recent ORDER BY at")]
        with self._recent_lock:
            missing = [at for at in ats if at not in self._recent]
        if missing:
            rows = connection.execute(
                f"SELECT at, data FROM recent WHERE at IN ({_marks(missing)})", missing
            ).fetchall()
            decoded = {int(row["at"]): _decoded(bytes(row["data"])) for row in rows}
        else:
            decoded = {}
        with self._recent_lock:
            self._recent.update(decoded)
            for at in set(self._recent) - set(ats):
                del self._recent[at]
            return [self._recent[at] for at in ats if at in self._recent]

    def replace(self, point: int, kind: str, samples: list[tuple[int, Any]]) -> int:
        """Store ``(ms, value)`` pairs given in time order, replacing stored values at those times.

        For values written as they are (an app's derived series, a backfill from the source):
        chunks that overlap the new values are merged with them, the new value winning on
        equal times, and rewritten as chunks of up to ``CHUNK_VALUES`` values.
        """

        if not samples:
            return 0
        return self._writing(lambda: self._replace(point, kind, samples))

    def _replace(self, point: int, kind: str, samples: list[tuple[int, Any]]) -> int:
        times = np.fromiter((at for at, _ in samples), dtype=np.int64, count=len(samples))
        values = [value for _, value in samples]
        first, last = int(times.min()), int(times.max())
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT t0, data FROM chunks WHERE point = ? AND t0 <= ? AND t1 >= ?",
                (point, last, first),
            ).fetchall()
            # The stored values around the new ones bound the hours they change.
            before = connection.execute(
                "SELECT MAX(t1) AS at FROM chunks WHERE point = ? AND t1 < ?", (point, first)
            ).fetchone()["at"]
            after = connection.execute(
                "SELECT MIN(t0) AS at FROM chunks WHERE point = ? AND t0 > ?", (point, last)
            ).fetchone()["at"]
            for row in rows:
                old_times, old_values = codec.decode(bytes(row["data"]))
                earlier, later = old_times[old_times < first], old_times[old_times > last]
                if len(earlier):
                    before = max(int(earlier[-1]), int(before or earlier[-1]))
                if len(later):
                    after = min(int(later[0]), int(after if after is not None else later[0]))
                times, values = _merge(old_times, list(old_values), times, values)
            low = int(before if before is not None else first)
            connection.execute(
                "DELETE FROM rollups WHERE point = ? AND hour > ? AND hour <= ?",
                (point, low - HOUR_MS, int(after) if after is not None else 2**62),
            )
            if rows:
                connection.executemany(
                    "DELETE FROM chunks WHERE point = ? AND t0 = ?",
                    [(point, int(row["t0"])) for row in rows],
                )
            order = np.argsort(times, kind="stable")
            times = times[order]
            values = [values[i] for i in order]
            self._ensure("chunks", times[::CHUNK_VALUES].tolist())
            connection.executemany(
                _PUT_CHUNK,
                [
                    (
                        point,
                        int(times[i]),
                        int(times[min(i + CHUNK_VALUES, len(times)) - 1]),
                        len(times[i : i + CHUNK_VALUES]),
                        codec.encode(
                            times[i : i + CHUNK_VALUES], values[i : i + CHUNK_VALUES], kind
                        ),
                    )
                    for i in range(0, len(times), CHUNK_VALUES)
                ],
            )
            connection.executemany(_COUNT, _hour_counts(point, [at for at, _ in samples]))
        return len(samples)

    def put_run(self, point: int, run_at: int, samples: list[tuple[int, float]], keep: int) -> int:
        """Store one execution of a runs point (the same ``run_at`` replaces it) and keep only the
        newest ``keep`` runs; the values written. An empty run stores nothing."""

        if not samples:
            return 0
        times = np.fromiter((at for at, _ in samples), dtype=np.int64, count=len(samples))
        values = np.fromiter((v for _, v in samples), dtype=float, count=len(samples))
        blob = codec.encode_numbers(times, values)
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO run_series VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(point, run_at)"
                " DO UPDATE SET t0 = excluded.t0, t1 = excluded.t1, n = excluded.n,"
                " data = excluded.data",
                (point, run_at, int(times[0]), int(times[-1]), len(samples), blob),
            )
            connection.execute(
                "DELETE FROM run_series WHERE point = ? AND run_at < COALESCE((SELECT MIN(run_at)"
                " FROM (SELECT run_at FROM run_series WHERE point = ? ORDER BY run_at DESC"
                " LIMIT ?) AS kept), 0)",
                (point, point, max(1, int(keep))),
            )
            hour = int(times[0]) - int(times[0]) % HOUR_MS
            connection.execute(_COUNT, (point, hour, len(samples)))
        return len(samples)

    def run_list(self, point: int, limit: int = 50) -> list[dict[str, int]]:
        """A runs point's executions, newest first: ``run_at``, ``start``, ``end`` (ms), ``n``."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT run_at, t0, t1, n FROM run_series WHERE point = ?"
                " ORDER BY run_at DESC LIMIT ?",
                (point, int(limit)),
            ).fetchall()
        return [
            {
                "run_at": int(r["run_at"]),
                "start": int(r["t0"]),
                "end": int(r["t1"]),
                "n": int(r["n"]),
            }
            for r in rows
        ]

    def runs(
        self, point: int, *, run_at: int | None = None, count: int = 1
    ) -> list[tuple[int, np.ndarray, np.ndarray]]:
        """``(run_at, times ms, values)`` of the run at ``run_at``, else of the newest ``count``
        runs, newest first."""

        with self._connect() as connection:
            if run_at is not None:
                rows = connection.execute(
                    "SELECT run_at, data FROM run_series WHERE point = ? AND run_at = ?",
                    (point, int(run_at)),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT run_at, data FROM run_series WHERE point = ?"
                    " ORDER BY run_at DESC LIMIT ?",
                    (point, int(count)),
                ).fetchall()
        out = []
        for row in rows:
            times, values = codec.decode(bytes(row["data"]))
            out.append((int(row["run_at"]), times, np.asarray(values, dtype=float)))
        return out

    def put_qualities(self, changes: Iterable[tuple[int, int, str]]) -> None:
        """Store ``(point, ms, quality)`` changes of quality (the collector's)."""

        with self._lock, self._connect() as connection:
            connection.executemany(
                "INSERT INTO qualities VALUES (?, ?, ?) ON CONFLICT(point, t) DO UPDATE"
                " SET quality = excluded.quality",
                list(changes),
            )

    def put_lab_samples(self, rows: Iterable[tuple[Any, ...]]) -> None:
        """Store ``(point, t, received, approved, status, written, author)`` of laboratory
        samples; a sample written again keeps the newest and counts the writes."""

        with self._lock, self._connect() as connection:
            connection.executemany(
                "INSERT INTO lab_samples (point, t, received, approved, status, written, author)"
                " VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(point, t) DO UPDATE SET"
                " received = excluded.received, approved = excluded.approved,"
                " status = excluded.status, written = excluded.written,"
                " author = excluded.author, writes = lab_samples.writes + 1",
                list(rows),
            )

    def lab_samples(self, point: int, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT t, received, approved, status, written, author, writes FROM lab_samples"
                " WHERE point = ? AND t >= ? AND t <= ? ORDER BY t",
                (point, start_ms, end_ms),
            ).fetchall()
        return [dict(row) for row in rows]

    def put_snapshots(self, rows: Iterable[dict[str, Any]]) -> None:
        stamp = now_ms()
        with self._lock, self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO snapshots (point, ts, value, status, detail, reads, archived, updated)
                VALUES (:point, :ts, :value, :status, :detail, :reads, :archived, :updated)
                ON CONFLICT(point) DO UPDATE SET
                    ts = excluded.ts, value = excluded.value, status = excluded.status,
                    detail = excluded.detail, reads = excluded.reads,
                    archived = excluded.archived, updated = excluded.updated
                """,
                [
                    {
                        "detail": "",
                        "reads": 0,
                        "archived": 0,
                        **row,
                        "value": self.db.any(row.get("value")),
                        "updated": stamp,
                    }
                    for row in rows
                ],
            )

    def refill_snapshots(self) -> int:
        """Give a snapshot to every point with archived values and none (the table is emptied
        by a crash, ``_unlogged_snapshots``): its last archived value. Points given one."""

        with self._connect() as connection:
            have = {int(row[0]) for row in connection.execute("SELECT point FROM snapshots")}
            totals = {int(row[0]) for row in connection.execute("SELECT point FROM point_totals")}
        missing = sorted(totals - have)
        if not missing:
            return 0
        stamp = now_ms()
        rows = []
        with self._connect() as connection:
            for point in missing:
                row = connection.execute(
                    "SELECT data FROM chunks WHERE point = ? ORDER BY t0 DESC LIMIT 1", (point,)
                ).fetchone()
                if row is None:
                    continue
                times, values = codec.decode(bytes(row["data"]))
                if len(times):
                    value = values[-1]
                    value = value.item() if hasattr(value, "item") else value
                    rows.append((point, int(times[-1]), self.db.any(value), stamp))
        if rows:
            with self._lock, self._connect() as connection:
                connection.executemany(
                    "INSERT INTO snapshots (point, ts, value, updated) VALUES (?, ?, ?, ?)"
                    " ON CONFLICT(point) DO NOTHING",
                    rows,
                )
        return len(rows)

    def set_state(self, key: str, value: Any) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO collector_state VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value, default=str)),
            )

    def finish_request(self, request_id: int, status: str, result: Any) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO request_results VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE"
                " SET status = excluded.status, result = excluded.result,"
                " finished = excluded.finished",
                (request_id, status, json.dumps(result, default=str), now_ms()),
            )

    def compact(
        self, older_than_ms: int, points: Iterable[int] | None = None, since_ms: int | None = None
    ) -> int:
        """Merge a point's small chunks by tiers of time; chunks removed.

        Only chunks that end before ``older_than_ms`` (and start at ``since_ms`` or later, when
        given: the collector looks back to the start of the previous month) merge, and only
        with the chunks of the same closed UTC hour, then day, then month (``_bucket``): the
        minute chunks of an hour become one chunk once the hour is closed, the hours of a day
        one (or a few, ``CHUNK_VALUES`` values at most) once the day is closed, the days of a
        month once the month is. Each value is so rewritten three times at most, instead of at
        every hourly run while its chunk grows to ``CHUNK_VALUES`` (the WAL that made: ~18x the
        values archived). A run of chunks merges when two neighbours together fit in
        ``CHUNK_VALUES``: full chunks are never read again.

        ``COMPACT_BATCH`` points per short transaction, a few statements each: the collector's
        flushes wait for one batch at most, never for the whole archive. Only the sizes of a
        point's chunks are read, then the bytes of the chunks that merge, ``COMPACT_CHUNKS`` at
        a time: a long backlog (a backfill) never holds all its chunks in memory at once.
        """

        low = -(2**62) if since_ms is None else int(since_ms)
        with self._connect() as connection:
            if points is None:
                # Points with two neighbouring chunks that fit together (whatever their tiers:
                # the exact runs are found per point below).
                points = [
                    row["point"]
                    for row in connection.execute(
                        "SELECT DISTINCT point FROM (SELECT point, n + LEAD(n) OVER"
                        " (PARTITION BY point ORDER BY t0) AS pair FROM chunks"
                        " WHERE t0 >= ? AND t1 < ?) AS pairs WHERE pair <= ?",
                        (low, older_than_ms, CHUNK_VALUES),
                    )
                ]
            # How many chunks each would read, so a backlog goes in bounded batches.
            ids = sorted({int(point) for point in points})
            found = [
                row
                for offset in range(0, len(ids), COMPACT_BATCH)
                for row in connection.execute(
                    "SELECT point, COUNT(*) AS n FROM chunks WHERE point IN"
                    f" ({_marks(ids[offset : offset + COMPACT_BATCH])}) AND t0 >= ? AND t1 < ?"
                    " GROUP BY point HAVING COUNT(*) > 1",
                    (*ids[offset : offset + COMPACT_BATCH], low, older_than_ms),
                )
            ]
        counts = sorted((int(row["point"]), int(row["n"])) for row in found)
        # Batches of COMPACT_BATCH points, fewer when their chunks are many (a backfill).
        batches: list[list[int]] = []
        part, held = [], 0
        for point, count in counts:
            if part and (len(part) >= COMPACT_BATCH or held + count > 2 * COMPACT_CHUNKS):
                batches.append(part)
                part, held = [], 0
            part.append(point)
            held += count
        if part:
            batches.append(part)
        removed = 0
        for part in batches:
            with self._lock, self._connect() as connection:
                removed += self._compact_points(connection, part, older_than_ms, low)
            # Python's lock is not fair: without a pause this thread takes it again at once and
            # a waiting flush sits behind thousands of points.
            time.sleep(0.001)
        return removed

    def _compact_points(
        self, connection: Any, points: list[int], older_than_ms: int, low: int
    ) -> int:
        rows = connection.execute(
            f"SELECT point, t0, n FROM chunks WHERE point IN ({_marks(points)})"
            " AND t0 >= ? AND t1 < ? ORDER BY point, t0",
            (*points, low, older_than_ms),
        ).fetchall()
        tiers = _Tiers(older_than_ms)
        runs: list[tuple[int, list[int]]] = []
        current, bucket, run, count = None, None, [], 0
        for row in [*rows, None]:
            point = None if row is None else int(row["point"])
            here = None if row is None else tiers.bucket(int(row["t0"]))
            if (
                row is not None
                and here is not None
                and (point, here) == (current, bucket)
                and count + row["n"] <= CHUNK_VALUES
            ):
                run.append(int(row["t0"]))
                count += row["n"]
                continue
            if len(run) > 1:
                runs.append((current, run))
            current, bucket = point, here
            run, count = ([int(row["t0"])], row["n"]) if row is not None else ([], 0)
        if not runs:
            return 0
        removed, step, held = 0, [], 0
        for item in runs:
            step.append(item)
            held += len(item[1])
            if held >= COMPACT_CHUNKS:
                removed += self._merge_runs(connection, step)
                step, held = [], 0
        if step:
            removed += self._merge_runs(connection, step)
        return removed

    def _merge_runs(self, connection: Any, runs: list[tuple[int, list[int]]]) -> int:
        """Each run of a point's small chunks as one chunk; chunks removed."""

        keys = [(point, t0) for point, starts in runs for t0 in starts]
        wanted = set(keys)
        data = {
            (int(row["point"]), int(row["t0"])): bytes(row["data"])
            for row in self._chunks_at(connection, keys)
            if (int(row["point"]), int(row["t0"])) in wanted
        }
        merged = []
        for point, starts in runs:
            times, values = _joined(*zip(*(codec.decode(data[(point, t0)]) for t0 in starts)))
            kind = "text" if isinstance(values, list) else "number"
            merged.append(
                (
                    point,
                    int(times[0]),
                    int(times[-1]),
                    len(times),
                    codec.encode(times, values, kind),
                )
            )
        if self.db.postgres:
            points_, starts_ = zip(*keys)
            connection.execute(
                "DELETE FROM chunks c USING unnest(?::bigint[], ?::bigint[]) AS k(point, t0)"
                " WHERE c.point = k.point AND c.t0 = k.t0",
                (_ints(points_), _ints(starts_)),
            )
            columns = list(zip(*merged))
            connection.execute(
                _PUT_CHUNKS_MANY, (*(_ints(column) for column in columns[:4]), _blobs(columns[4]))
            )
        else:
            connection.executemany("DELETE FROM chunks WHERE point = ? AND t0 = ?", keys)
            connection.executemany(_PUT_CHUNK, merged)
        return len(keys) - len(runs)

    def rewrite_closed(self, current_ms: int | None = None) -> str | None:
        """Rewrite the oldest closed month of ``chunks``, then of ``rollups``, not rewritten
        yet (PostgreSQL; ``partitions.rewrite_month``): it gives back the space compaction left
        in it and puts each point's rows side by side (the collector writes every point's hour
        at once, so a point's year of rollups was one page per hour). Its name, or None. One
        month per call: the hourly housekeeping goes through a backlog by the hour."""

        if self.partitions is None:
            return None
        for table in partitions.MONTHLY:
            for name, start, end in partitions.closed_months(
                self.db, table, current_ms or now_ms()
            ):
                if partitions.rewrite_month(self.db, table, name, start, end):
                    return name
                return None
        return None

    def prune(self, cutoffs: dict[int, int]) -> int:
        """Delete each point's chunks that end before its cutoff (ms); chunks deleted.

        In PostgreSQL a past month whose every chunk is past retention is dropped first, as one
        table. Then one short transaction per point, like ``compact``."""

        deleted, dropped_points = 0, set()
        if self.partitions is not None:
            deleted, dropped_points = self.partitions.drop_expired(cutoffs, now_ms())
        for point, cutoff in cutoffs.items():
            with self._lock, self._connect() as connection:
                removed = connection.execute(
                    "DELETE FROM chunks WHERE point = ? AND t1 < ?", (point, cutoff)
                ).rowcount
                # A runs point's executions go by their run time.
                connection.execute(
                    "DELETE FROM run_series WHERE point = ? AND run_at < ?", (point, cutoff)
                )
                if removed or point in dropped_points:
                    # Hours up to the first value left lose the segment that led to it.
                    connection.execute(
                        "DELETE FROM rollups WHERE point = ? AND hour <= COALESCE("
                        "(SELECT MIN(t0) FROM chunks WHERE point = ?), ?)",
                        (point, point, cutoff),
                    )
                deleted += removed
                # Quality changes before the cutoff go, but the one in effect there stays.
                connection.execute(
                    "DELETE FROM qualities WHERE point = ? AND t < COALESCE((SELECT MAX(t)"
                    " FROM qualities WHERE point = ? AND t <= ?), ?)",
                    (point, point, cutoff, cutoff),
                )
        return deleted

    def delete_points(self, points: Iterable[int]) -> None:
        """Delete everything the archive keeps of ``points``.

        In batches of ``DELETE_BATCH`` points, each its own short transaction, the points in
        order and the tables in the order writes take them (``_append``: rollups, chunks, then
        ``point_hours``), so a write by another process waits rather than deadlocks. A batch that
        PostgreSQL still ends as a deadlock is tried again (``DELETE_TRIES``); one that fails
        for good leaves its rows to the next sweep, which finds them (``point_ids``).
        """

        ids = sorted({int(point) for point in points})
        for offset in range(0, len(ids), DELETE_BATCH):
            part = ids[offset : offset + DELETE_BATCH]
            for attempt in range(1, DELETE_TRIES + 1):
                try:
                    with self._lock, self._connect() as connection:
                        for table in _POINT_TABLES:
                            connection.execute(
                                f"DELETE FROM {table} WHERE point IN ({_marks(part)})", part
                            )
                    break
                except Exception as exc:
                    if not _contended(exc) or attempt == DELETE_TRIES:
                        raise
                    time.sleep(0.05 * 2**attempt)

    # Hourly rollups -----------------------------------------------------------------

    def span(self, point: int) -> tuple[int, int] | None:
        """The first and last archived times of a point (ms), or None."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT MIN(t0) AS first, MAX(t1) AS last FROM chunks WHERE point = ?", (point,)
            ).fetchone()
        if row is None or row["first"] is None:
            return None
        return int(row["first"]), int(row["last"])

    def rollups(
        self, point: int, step: bool, start_ms: int, end_ms: int
    ) -> dict[int, tuple[float, float, float | None, float | None, int | None]]:
        """``{hour: (cover, area, low, high, n)}`` of the hours in ``[start, end)`` kept for
        ``step`` (``n`` None: kept before the hours had their extremes)."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT hour, cover, area, low, high, n FROM rollups WHERE point = ? AND step = ?"
                " AND hour >= ? AND hour < ?",
                (point, int(step), start_ms, end_ms),
            ).fetchall()
        return {
            int(row["hour"]): (
                float(row["cover"]),
                float(row["area"]),
                _real(row["low"]),
                _real(row["high"]),
                None if row["n"] is None else int(row["n"]),
            )
            for row in rows
        }

    def put_rollups(self, point: int, step: bool, rows: list[tuple[Any, ...]]) -> None:
        """Keep ``(hour, cover, area, low, high, n)`` rows; rows kept for the other ``step`` are
        dropped."""

        self._writing(lambda: self._put_rollups(point, step, rows))

    def _put_rollups(self, point: int, step: bool, rows: list[tuple[Any, ...]]) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM rollups WHERE point = ? AND step <> ?", (point, int(step))
            )
            self._ensure("rollups", (row[0] for row in rows))
            connection.executemany(
                "INSERT INTO rollups (point, hour, step, cover, area, low, high, n)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(point, hour) DO UPDATE"
                " SET step = excluded.step, cover = excluded.cover, area = excluded.area,"
                " low = excluded.low, high = excluded.high, n = excluded.n",
                [(point, row[0], int(step), *row[1:3], *_extremes(row)) for row in rows],
            )

    # Reads ----------------------------------------------------------------------

    def read(
        self, point: int, start_ms: int, end_ms: int
    ) -> tuple[np.ndarray, np.ndarray | list[Any]]:
        """Archived values in ``[start, end]`` plus the one just before and the one just after.

        The neighbours let a reader rebuild the signal at the edges of the range.
        Times are milliseconds; values a float array (numbers) or a list (text).
        """

        return self.read_many([point], start_ms, end_ms)[point]

    def read_many(
        self, points: Iterable[int], start_ms: int, end_ms: int
    ) -> dict[int, tuple[np.ndarray, np.ndarray | list[Any]]]:
        """``read`` of many points in one database round trip (PostgreSQL) or one connection.

        A batch of 500 signals is one query, not 500: on PostgreSQL each point's neighbour
        chunks come from a ``LATERAL`` lookup on the primary key, as ``read`` of one point does.
        """

        ids = sorted({int(point) for point in points})
        found: dict[int, dict[int, bytes]] = {point: {} for point in ids}
        if not ids:
            return {}
        with self._connect() as connection:
            # The recent values first: a settle that commits in between leaves them in both
            # (kept once), never in neither.
            recent = self._recent_parts(connection)
            if self.db.postgres:
                rows = connection.execute(
                    _READ_MANY, (ids, start_ms, end_ms, ids, start_ms, ids, end_ms)
                ).fetchall()
            else:
                rows = []
                for point in ids:
                    rows += connection.execute(
                        _READ_ONE, (point, start_ms, end_ms, point, start_ms, point, end_ms)
                    ).fetchall()
        for row in rows:
            # A chunk both inside the range and a neighbour comes back twice: kept once.
            found[int(row["point"])][int(row["t0"])] = bytes(row["data"])
        return {
            point: _assemble(
                chunks, [part[point] for part in recent if point in part], start_ms, end_ms
            )
            for point, chunks in found.items()
        }

    def qualities(self, point: int, start_ms: int, end_ms: int) -> list[tuple[int, str]]:
        """The quality in effect at ``start`` (when not good) and its changes up to ``end``."""

        with self._connect() as connection:
            before = connection.execute(
                "SELECT t, quality FROM qualities WHERE point = ? AND t <= ? ORDER BY t DESC"
                " LIMIT 1",
                (point, start_ms),
            ).fetchone()
            rows = connection.execute(
                "SELECT t, quality FROM qualities WHERE point = ? AND t > ? AND t <= ? ORDER BY t",
                (point, start_ms, end_ms),
            ).fetchall()
        out = [(int(row["t"]), str(row["quality"])) for row in rows]
        if before is not None and before["quality"] != "good":
            out.insert(0, (int(before["t"]), str(before["quality"])))
        return out

    def qualities_many(
        self, points: Iterable[int], start_ms: int, end_ms: int
    ) -> dict[int, list[tuple[int, str]]]:
        """``qualities`` of many points: one round trip on PostgreSQL (one query per point on
        SQLite); a point whose quality stayed good has an empty list."""

        ids = sorted({int(point) for point in points})
        if not ids:
            return {}
        if not self.db.postgres:
            return {point: self.qualities(point, start_ms, end_ms) for point in ids}
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT point, t, quality FROM qualities WHERE point = ANY(?) AND t > ? AND t <= ?"
                " UNION ALL SELECT q.point, q.t, q.quality FROM unnest(?::bigint[]) AS p(point)"
                " CROSS JOIN LATERAL (SELECT point, t, quality FROM qualities WHERE point = p.point"
                " AND t <= ? ORDER BY t DESC LIMIT 1) q ORDER BY 1, 2",
                (ids, start_ms, end_ms, ids, start_ms),
            ).fetchall()
        found: dict[int, list[tuple[int, str]]] = {point: [] for point in ids}
        for row in rows:
            point, at, code = int(row["point"]), int(row["t"]), str(row["quality"])
            changes = found[point]
            if at <= start_ms and code == "good":
                continue  # good at the start: nothing to say
            changes.append((at, code))
        return found

    def point_ids(self) -> set[int]:
        with self._connect() as connection:
            rows = connection.execute(
                " UNION ".join(f"SELECT DISTINCT point FROM {table}" for table in _POINT_TABLES)
            ).fetchall()
        return {int(row[0]) for row in rows}

    def snapshots(self, points: Iterable[int] | None = None) -> dict[int, dict[str, Any]]:
        with self._connect() as connection:
            if points is None:
                rows = connection.execute("SELECT * FROM snapshots").fetchall()
            else:
                ids = list(points)
                if not ids:
                    return {}
                marks = ",".join("?" for _ in ids)
                rows = connection.execute(
                    f"SELECT * FROM snapshots WHERE point IN ({marks})", ids
                ).fetchall()
        return {row["point"]: dict(row) for row in rows}

    def state(self) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute("SELECT key, value FROM collector_state").fetchall()
        return {row["key"]: self._loads(row["value"], None) for row in rows}

    def request_result(self, request_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM request_results WHERE id = ?", (request_id,)
            ).fetchone()
        if row is None:
            return None
        return {**dict(row), "result": self._loads(row["result"], None)}

    def done_requests(self, ids: Iterable[int]) -> set[int]:
        ids = list(ids)
        if not ids:
            return set()
        marks = ",".join("?" for _ in ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT id FROM request_results WHERE id IN ({marks})", ids
            ).fetchall()
        return {row["id"] for row in rows}

    def refresh_totals(self) -> int:
        """Count again what the archive keeps of each point (the collector, every few minutes);
        drop the hour counts older than a week. Points counted."""

        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM point_totals")
            connection.execute(f"INSERT INTO point_totals {_TOTALS}")
            connection.execute(
                "DELETE FROM point_hours WHERE hour < ?", (now_ms() - COUNT_HOURS * HOUR_MS,)
            )
            counted = connection.execute("SELECT COUNT(*) FROM point_totals").fetchone()[0]
        self.set_state("totals_at", now_ms())
        return int(counted)

    def point_stats(self) -> dict[int, dict[str, int]]:
        """Per point: chunks, values, bytes, first and last time (as of the last refresh, or
        counted now before the first one) and ``day``, the values written for the last 24 h."""

        since = now_ms() - DAY_MS
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM point_totals").fetchall()
            if not rows:
                rows = connection.execute(_TOTALS).fetchall()
            days = connection.execute(
                "SELECT point, SUM(n) AS n FROM point_hours WHERE hour >= ? GROUP BY point",
                (since - since % HOUR_MS,),
            ).fetchall()
        day = {int(row["point"]): int(row["n"]) for row in days}
        return {
            int(row["point"]): {
                "chunks": int(row["chunks"]),
                "values": int(row["n"]),
                "bytes": int(row["bytes"]),
                "first": row["first"],
                "last": row["last"],
                "day": day.get(int(row["point"]), 0),
            }
            for row in rows
        }

    def hour_counts(self, since: int, points: Iterable[int] | None = None) -> dict[int, int]:
        """Values written per hour of their time from the hour of ``since`` on (``point_hours``,
        a week kept: a row per point and hour, never a read of the archive); ``points`` keeps
        only those points' values (``None``: every point's)."""

        start = since - since % HOUR_MS
        with self._connect() as connection:
            if points is None:
                rows = connection.execute(
                    "SELECT hour, SUM(n) AS n FROM point_hours WHERE hour >= ? GROUP BY hour",
                    (start,),
                ).fetchall()
                return {int(row["hour"]): int(row["n"]) for row in rows}
            rows = connection.execute(
                "SELECT point, hour, n FROM point_hours WHERE hour >= ?", (start,)
            ).fetchall()
        kept = {int(point) for point in points}
        counts: dict[int, int] = {}
        for row in rows:
            if int(row["point"]) in kept:
                counts[int(row["hour"])] = counts.get(int(row["hour"]), 0) + int(row["n"])
        return counts

    def file_bytes(self) -> int:
        """Bytes the archive takes on disk (in PostgreSQL: its tables with indexes and TOAST)."""

        if self.db.postgres:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT (SELECT SUM(pg_total_relation_size(relid))"
                    " FROM pg_partition_tree('chunks')) + pg_total_relation_size('snapshots')"
                    " + pg_total_relation_size('recent')"
                ).fetchone()
            return int(row[0])
        assert self.path is not None
        total = 0
        for suffix in ("", "-wal"):
            path = self.path.with_name(self.path.name + suffix)
            if path.exists():
                total += path.stat().st_size
        return total


def compaction_start(older_than_ms: int) -> int:
    """Where the collector's hourly compaction looks from: the start of the month before the
    one holding ``older_than_ms`` (that month's days still merge in its first hours). Older
    months are done: their chunks are full, or a month's worth."""

    month = partitions.month_of(older_than_ms)
    if month is None:
        return -(2**62)
    year, number = month
    return partitions.bounds(*((year - 1, 12) if number == 1 else (year, number - 1)))[0]


class _Tiers:
    """The tier a chunk merges in, by its start (``t0``), as of ``older_than_ms``: its UTC month
    once the month is closed, else its day once the day is, else its hour once the hour is;
    None while its hour is still open (it waits)."""

    def __init__(self, older_than_ms: int):
        self.hour = older_than_ms - older_than_ms % HOUR_MS
        self.day = older_than_ms - older_than_ms % DAY_MS
        month = partitions.month_of(older_than_ms)
        self.month = partitions.bounds(*month)[0] if month else self.day

    def bucket(self, t0: int) -> tuple[Any, ...] | None:
        if t0 < self.month:
            return ("month", partitions.month_of(t0))
        if t0 < self.day:
            return ("day", t0 // DAY_MS)
        if t0 < self.hour:
            return ("hour", t0 // HOUR_MS)
        return None


# Chunks and a runs point's executions (each run counts as a chunk).
_TOTALS = (
    "SELECT point, SUM(c) AS chunks, SUM(n) AS n, SUM(b) AS bytes, MIN(f) AS first,"
    " MAX(l) AS last FROM ("
    "SELECT point, COUNT(*) AS c, SUM(n) AS n, SUM(LENGTH(data)) AS b, MIN(t0) AS f,"
    " MAX(t1) AS l FROM chunks GROUP BY point UNION ALL "
    "SELECT point, COUNT(*), SUM(n), SUM(LENGTH(data)), MIN(t0), MAX(t1) FROM run_series"
    " GROUP BY point) AS parts GROUP BY point"
)

# A point's chunks never overlap, so the chunks a range needs are those starting inside it, the
# last one starting before it (it reaches into the range, or holds the value just before) and
# the first one after it. Every bound is on ``t0``: the primary key finds them, and PostgreSQL
# opens only the months that hold them, however long the point's history.
_READ_ONE = """
    SELECT point, t0, data FROM chunks WHERE point = ? AND t0 >= ? AND t0 <= ?
    UNION
    SELECT * FROM (
        SELECT point, t0, data FROM chunks WHERE point = ? AND t0 < ?
        ORDER BY t0 DESC LIMIT 1
    ) AS before_range
    UNION
    SELECT * FROM (
        SELECT point, t0, data FROM chunks WHERE point = ? AND t0 > ?
        ORDER BY t0 LIMIT 1
    ) AS after_range
"""
# PostgreSQL: the same for many points in one statement.
_READ_MANY = """
    SELECT point, t0, data FROM chunks WHERE point = ANY(?) AND t0 >= ? AND t0 <= ?
    UNION ALL
    SELECT b.point, b.t0, b.data FROM unnest(?::bigint[]) AS p(id) CROSS JOIN LATERAL (
        SELECT point, t0, data FROM chunks WHERE point = p.id AND t0 < ?
        ORDER BY t0 DESC LIMIT 1
    ) AS b
    UNION ALL
    SELECT a.point, a.t0, a.data FROM unnest(?::bigint[]) AS p(id) CROSS JOIN LATERAL (
        SELECT point, t0, data FROM chunks WHERE point = p.id AND t0 > ?
        ORDER BY t0 LIMIT 1
    ) AS a
"""


def _assemble(
    chunks: dict[int, bytes],
    recent: list[tuple[str, np.ndarray, Any]],
    start_ms: int,
    end_ms: int,
) -> tuple[np.ndarray, np.ndarray | list[Any]]:
    """One point's decoded chunks, then its recent values, as times and values in
    ``[start, end]`` with a neighbour on each side."""

    parts = [codec.decoded_chunks.decode(chunks[t0]) for t0 in sorted(chunks)]
    parts += [(times, values) for _, times, values in recent]
    if not parts:
        return np.empty(0, dtype=np.int64), np.empty(0)
    times, values = _joined([part[0] for part in parts], [part[1] for part in parts])
    text = isinstance(values, list)
    order = np.argsort(times, kind="stable")
    times = times[order]
    values = [values[i] for i in order] if text else values[order]
    before = np.searchsorted(times, start_ms, side="left") - 1
    after = np.searchsorted(times, end_ms, side="right")
    lo, hi = max(int(before), 0), min(int(after) + 1, len(times))
    return times[lo:hi], values[lo:hi]


def _hour_counts(point: int, times: list[int]) -> list[tuple[int, int, int]]:
    """``(point, hour, values)`` rows of ``point_hours`` for values at ``times`` (ms)."""

    if not times:
        return []
    hours, counts = np.unique(np.asarray(times, dtype=np.int64) // HOUR_MS, return_counts=True)
    return [(point, int(hour) * HOUR_MS, int(count)) for hour, count in zip(hours, counts)]


# Every table keyed by point, in the order writes take them (``delete_points``).
_POINT_TABLES = (
    "rollups",
    "chunks",
    "point_hours",
    "snapshots",
    "qualities",
    "point_totals",
    "run_series",
    "lab_samples",
)
DELETE_BATCH = 500
DELETE_TRIES = 5


def _contended(exc: BaseException) -> bool:
    """A PostgreSQL deadlock or serialization failure: the transaction may simply be retried."""

    return getattr(exc, "sqlstate", None) in ("40P01", "40001")


def _marks(items: list[Any]) -> str:
    return ",".join("?" for _ in items)


def _merge(
    old_times: np.ndarray, old_values: list[Any], new_times: np.ndarray, new_values: list[Any]
) -> tuple[np.ndarray, list[Any]]:
    """Two runs of one point as one, newest value winning on equal times."""

    merged: dict[int, Any] = {}
    for at, value in zip(old_times.tolist(), old_values, strict=True):
        merged[at] = value
    for at, value in zip(new_times.tolist(), new_values, strict=True):
        merged[at] = value
    times = sorted(merged)
    return np.asarray(times, dtype=np.int64), [merged[at] for at in times]


def _settled(rows: list[Any]) -> dict[int, tuple[str, np.ndarray, Any]]:
    """``recent`` rows (oldest first) as one run per point, in time order, a later row winning
    on equal times: the number points sorted all at once, not point by point."""

    numbers: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    labelled: dict[int, tuple[str, list[np.ndarray], list[Any]]] = {}
    for row in rows:
        try:
            points, times, values, labels = codec.decode_batch_arrays(bytes(row["data"]))
        except codec.CodecError:
            continue  # a damaged row: skipped, as reads skip it
        numbers.append((points, times, values))
        for point, (kind, stamps, found) in labels.items():
            entry = labelled.setdefault(point, (kind, [], []))
            entry[1].append(stamps)
            entry[2].append(found)
    runs: dict[int, tuple[str, np.ndarray, Any]] = {}
    if numbers:
        points = np.concatenate([part[0] for part in numbers])
        times = np.concatenate([part[1] for part in numbers])
        values = np.concatenate([part[2] for part in numbers])
        order = np.lexsort((times, points))  # stable: rows keep their order on equal keys
        points, times, values = points[order], times[order], values[order]
        last = np.ones(len(points), dtype=bool)
        last[:-1] = (points[1:] != points[:-1]) | (times[1:] != times[:-1])
        points, times, values = points[last], times[last], values[last]
        for point, start, end in codec.point_runs(points):
            runs[point] = ("number", times[start:end], values[start:end])
    for point, (kind, stamp_parts, label_parts) in labelled.items():
        runs[point] = (kind, *_joined(stamp_parts, label_parts))
    return runs


def _hour_counts_many(runs: dict[int, tuple[str, np.ndarray, Any]]) -> list[tuple[int, int, int]]:
    """``(point, hour, values)`` rows of ``point_hours`` for every run, counted at once."""

    if not runs:
        return []
    points = np.concatenate(
        [np.full(len(times), point, dtype=np.int64) for point, (_, times, _) in runs.items()]
    )
    hours = np.concatenate([times // HOUR_MS for _, times, _ in runs.values()])
    order = np.lexsort((hours, points))
    points, hours = points[order], hours[order]
    edge = np.ones(len(points), dtype=bool)
    edge[1:] = (points[1:] != points[:-1]) | (hours[1:] != hours[:-1])
    starts = np.flatnonzero(edge)
    sizes = np.diff(np.append(starts, len(points)))
    return list(
        zip(
            points[starts].tolist(),
            (hours[starts] * HOUR_MS).tolist(),
            sizes.tolist(),
            strict=True,
        )
    )


def _ints(values: Iterable[int]) -> str:
    """A PostgreSQL array literal of integers (``?::bigint[]``): tens of thousands of them
    are sent as one text, many times faster than psycopg adapting a list item by item."""

    return "{" + ",".join(map(str, values)) + "}"


def _blobs(values: Iterable[bytes]) -> str:
    """A PostgreSQL array literal of bytes in hex (``?::bytea[]``), as ``_ints``."""

    return "{" + ",".join('"\\\\x' + value.hex() + '"' for value in values) + "}"


def _decoded(blob: bytes) -> dict[int, tuple[str, np.ndarray, Any]]:
    """A ``recent`` row's values by point; a damaged row is skipped, never a failed read."""

    try:
        return codec.decode_batch(blob)
    except codec.CodecError:
        return {}


def _joined(times_parts: list[np.ndarray], value_parts: list[Any]) -> tuple[np.ndarray, Any]:
    """Parts of one point's values as one run in time order, the later part winning on equal
    times. Number parts are float arrays; once one part is labels, all are."""

    text = any(isinstance(part, list) for part in value_parts)
    times = np.concatenate(times_parts) if times_parts else np.empty(0, dtype=np.int64)
    if text:
        values: Any = [v for part in value_parts for v in _plain(part)]
    else:
        values = (
            np.concatenate([np.asarray(part, dtype=float) for part in value_parts])
            if value_parts
            else np.empty(0)
        )
    if len(times) < 2 or (np.diff(times) > 0).all():
        return times, values
    # Stable sort, then the last of each equal time (the later part's).
    order = np.argsort(times, kind="stable")
    times = times[order]
    last = np.append(times[1:] != times[:-1], True)
    keep = order[last]
    times = times[last]
    values = [values[i] for i in keep] if text else values[keep]
    return times, values


def _plain(values: Any) -> list[Any]:
    """Values as Python objects (floats from an array, labels as they are)."""

    return values.tolist() if isinstance(values, np.ndarray) else list(values)


def _extremes(row: tuple[Any, ...]) -> tuple[float | None, float | None, int | None]:
    """A rollup row's ``low``, ``high`` and ``n`` (a row of three values has none)."""

    if len(row) < 6:
        return None, None, None
    return _real(row[3]), _real(row[4]), None if row[5] is None else int(row[5])


def _real(value: Any) -> float | None:
    """A finite float, else None (SQLite keeps NaN as NULL; PostgreSQL would keep it)."""

    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None
