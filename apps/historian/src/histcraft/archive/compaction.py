"""Compaction: a point's small chunks merged by tiers of time (closed hour, day, month), and
PostgreSQL's closed months rewritten. Part of ``ArchiveStore`` (``archive.store``)."""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any

from histcraft.archive import codec, partitions
from histcraft.archive.common import (
    _PUT_CHUNK,
    _PUT_CHUNKS_MANY,
    CHUNK_VALUES,
    DAY_MS,
    HOUR_MS,
    _blobs,
    _ints,
    _joined,
    _marks,
)
from histcraft.clock import now_ms

# Points compacted per transaction.
COMPACT_BATCH = 200
# Small chunks whose bytes are held at once while they merge: a point's backlog (90 days of
# minute chunks after a backfill is 130,000 of them) goes in steps, never all in memory.
COMPACT_CHUNKS = 20_000


class Compaction:
    """``ArchiveStore``'s compaction."""

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
