"""The archive's writes (collector only, docs/boundary.md): chunks, the recent values between
flushes, rewrites and people's edits, runs, qualities, lab samples, snapshots and the
collector's state. Part of ``ArchiveStore`` (``archive.store``)."""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from typing import Any

import numpy as np

from histcraft.archive import codec
from histcraft.archive.common import (
    _COUNT,
    _COUNT_MANY,
    _PUT_CHUNK,
    _PUT_CHUNKS_MANY,
    CHUNK_VALUES,
    HOUR_MS,
    _blobs,
    _hour_counts,
    _hour_counts_many,
    _ints,
    _joined,
    _marks,
    _merge,
)
from histcraft.clock import now_ms

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

# The daily and monthly rollups (H9) holding an hour the statement above drops: those ending
# after the bound (their last hour starts past ``bound - 1 h``). Same parameters.
_DROP_COARSE = (
    "DELETE FROM rollups_coarse WHERE point = ? AND t1 > COALESCE("
    "(SELECT CASE WHEN t1 >= ? THEN t0 ELSE t1 END FROM chunks WHERE point = ? AND t0 < ?"
    " ORDER BY t0 DESC LIMIT 1), ?)"
)


# The same for many points in one statement (PostgreSQL): the bound of each point first, then
# its rollups past it, through the primary key, the daily and monthly ones with them.
_DROP_ROLLUPS_MANY = """
    WITH f AS (
        SELECT p.point, COALESCE((
            SELECT CASE WHEN c.t1 >= p.first THEN c.t0 ELSE c.t1 END FROM chunks c
            WHERE c.point = p.point AND c.t0 < p.first ORDER BY c.t0 DESC LIMIT 1
        ), p.first) - 3600000 AS low
        FROM unnest(?::bigint[], ?::bigint[]) AS p(point, first)
    )
    , hourly AS (DELETE FROM rollups r USING f WHERE r.point = f.point AND r.hour > f.low)
    DELETE FROM rollups_coarse c USING f WHERE c.point = f.point AND c.t1 > f.low + 3600000
"""


class Writing:
    """``ArchiveStore``'s writes."""

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
        drops = [(point, first, point, first, first) for point, first in firsts.items()]
        connection.executemany(_DROP_ROLLUPS, drops)
        connection.executemany(_DROP_COARSE, drops)
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

    def replace(self, point: int, kind: str, samples: list[tuple[int, Any]]) -> int:
        """Store ``(ms, value)`` pairs given in time order, replacing stored values at those times.

        For values written as they are (an app's derived series, a backfill from the source):
        chunks that overlap the new values are merged with them, the new value winning on
        equal times, and rewritten as chunks of up to ``CHUNK_VALUES`` values.
        """

        if not samples:
            return 0
        return self._writing(lambda: self._replace(point, kind, samples))

    def edit(
        self, point: int, kind: str, samples: list[tuple[int, Any]], drop: Iterable[int] = ()
    ) -> int:
        """A person's edit (``api.routers.edits``): ``samples`` written as ``replace`` does and
        the values at the times in ``drop`` removed. The values not settled yet are settled
        first, so an edit never races the collector's buffer."""

        drop = sorted({int(at) for at in drop})
        if not samples and not drop:
            return 0
        self.settle()
        samples = sorted(samples, key=lambda item: item[0])
        return self._writing(lambda: self._replace(point, kind, samples, drop))

    def _replace(
        self, point: int, kind: str, samples: list[tuple[int, Any]], drop: list[int] = ()
    ) -> int:
        times = np.fromiter((at for at, _ in samples), dtype=np.int64, count=len(samples))
        values = [value for _, value in samples]
        bounds = [*times.tolist(), *drop]
        first, last = int(min(bounds)), int(max(bounds))
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
            high = int(after) if after is not None else 2**62
            connection.execute(
                "DELETE FROM rollups WHERE point = ? AND hour > ? AND hour <= ?",
                (point, low - HOUR_MS, high),
            )
            # Days and months go from there on, as after an append: they are summed in order
            # from the newest one kept (``rollup.build_coarse``).
            connection.execute(
                "DELETE FROM rollups_coarse WHERE point = ? AND t1 > ?", (point, low)
            )
            if rows:
                connection.executemany(
                    "DELETE FROM chunks WHERE point = ? AND t0 = ?",
                    [(point, int(row["t0"])) for row in rows],
                )
            order = np.argsort(times, kind="stable")
            times = times[order]
            values = [values[i] for i in order]
            if len(drop):
                keep = ~np.isin(times, np.asarray(drop, dtype=np.int64))
                values = [value for value, kept in zip(values, keep.tolist(), strict=True) if kept]
                times = times[keep]
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
        return len(samples) + len(drop)

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

    def put_qualities(self, changes: Iterable[tuple]) -> None:
        """Store ``(point, ms, quality)``, or ``(point, ms, quality, status, name)``, changes of
        quality (``status``: the source's whole status code, ``name`` its sub-code's; or None)."""

        rows = [(*change[:3], *(tuple(change[3:5]) + (None, None))[:2]) for change in changes]
        with self._lock, self._connect() as connection:
            connection.executemany(
                "INSERT INTO qualities (point, t, quality, status, status_name)"
                " VALUES (?, ?, ?, ?, ?) ON CONFLICT(point, t) DO UPDATE"
                " SET quality = excluded.quality, status = excluded.status,"
                " status_name = excluded.status_name",
                rows,
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

    def put_edits(self, rows: Iterable[tuple[Any, ...]]) -> None:
        """Keep ``(point, t, action, old, new, author, at, reason)`` of people's edits (``old``
        and ``new`` as JSON text, or None)."""

        with self._lock, self._connect() as connection:
            connection.executemany(
                "INSERT INTO edits (point, t, action, old_value, new_value, author, at, reason)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                list(rows),
            )

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
