"""The archive's reads: values of one or many points (the chunks plus the recent values),
qualities, runs, edits and lab samples, snapshots, the collector's state and requests, and what
the archive keeps of each point. Part of ``ArchiveStore`` (``archive.store``)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np

from histcraft.archive import codec
from histcraft.archive.common import (
    _POINT_TABLES,
    COUNT_HOURS,
    DAY_MS,
    HOUR_MS,
    _joined,
    _marks,
)
from histcraft.clock import now_ms


class Reading:
    """``ArchiveStore``'s reads."""

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

    def edits(
        self, points: Iterable[int], start_ms: int, end_ms: int
    ) -> dict[int, list[dict[str, Any]]]:
        """Per point, the edits of values in ``[start, end]``, by value time then edit order."""

        ids = sorted({int(point) for point in points})
        found: dict[int, list[dict[str, Any]]] = {point: [] for point in ids}
        if not ids:
            return found
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM edits WHERE point IN ({_marks(ids)}) AND t >= ? AND t <= ?"
                " ORDER BY point, t, id",
                (*ids, start_ms, end_ms),
            ).fetchall()
        for row in rows:
            found[int(row["point"])].append(dict(row))
        return found

    def lab_samples(self, point: int, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT t, received, approved, status, written, author, writes FROM lab_samples"
                " WHERE point = ? AND t >= ? AND t <= ? ORDER BY t",
                (point, start_ms, end_ms),
            ).fetchall()
        return [dict(row) for row in rows]

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

    def qualities(
        self, point: int, start_ms: int, end_ms: int, *, with_status: bool = False
    ) -> list[tuple]:
        """The quality in effect at ``start`` (when not good, or good with a status) and its
        changes up to ``end``: ``(ms, quality)``, or ``(ms, quality, status)``."""

        with self._connect() as connection:
            before = connection.execute(
                "SELECT t, quality, status, status_name FROM qualities WHERE point = ? AND t <= ?"
                " ORDER BY t DESC LIMIT 1",
                (point, start_ms),
            ).fetchone()
            rows = connection.execute(
                "SELECT t, quality, status, status_name FROM qualities"
                " WHERE point = ? AND t > ? AND t <= ?"
                " ORDER BY t",
                (point, start_ms, end_ms),
            ).fetchall()
        out = [_quality_row(row, with_status) for row in rows]
        if before is not None and (before["quality"] != "good" or before["status"]):
            out.insert(0, _quality_row(before, with_status))
        return out

    def qualities_many(
        self, points: Iterable[int], start_ms: int, end_ms: int, *, with_status: bool = False
    ) -> dict[int, list[tuple]]:
        """``qualities`` of many points: one round trip on PostgreSQL (one query per point on
        SQLite); a point whose quality stayed good has an empty list."""

        ids = sorted({int(point) for point in points})
        if not ids:
            return {}
        if not self.db.postgres:
            return {
                point: self.qualities(point, start_ms, end_ms, with_status=with_status)
                for point in ids
            }
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT point, t, quality, status, status_name FROM qualities"
                " WHERE point = ANY(?) AND t > ? AND t <= ?"
                " UNION ALL SELECT q.point, q.t, q.quality, q.status, q.status_name"
                " FROM unnest(?::bigint[]) AS p(point)"
                " CROSS JOIN LATERAL (SELECT point, t, quality, status, status_name FROM qualities"
                " WHERE point = p.point AND t <= ? ORDER BY t DESC LIMIT 1) q ORDER BY 1, 2",
                (ids, start_ms, end_ms, ids, start_ms),
            ).fetchall()
        found: dict[int, list[tuple]] = {point: [] for point in ids}
        for row in rows:
            point, at = int(row["point"]), int(row["t"])
            if at <= start_ms and row["quality"] == "good" and not row["status"]:
                continue  # plainly good at the start: nothing to say
            found[point].append(_quality_row(row, with_status))
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


def _decoded(blob: bytes) -> dict[int, tuple[str, np.ndarray, Any]]:
    """A ``recent`` row's values by point; a damaged row is skipped, never a failed read."""

    try:
        return codec.decode_batch(blob)
    except codec.CodecError:
        return {}


def _quality_row(row: Any, with_status: bool) -> tuple:
    if with_status:
        status = row["status"]
        code = None if status is None else int(status)
        return (int(row["t"]), str(row["quality"]), code, row["status_name"])
    return (int(row["t"]), str(row["quality"]))
