"""Retention: each point's values, runs, qualities and rollups past their cutoffs deleted, and
everything the archive keeps of deleted points. Part of ``ArchiveStore`` (``archive.store``)."""

from __future__ import annotations

import time
from collections.abc import Iterable

from histcraft.archive.common import _POINT_TABLES, HOUR_MS, _marks
from histcraft.clock import now_ms

DELETE_BATCH = 500
DELETE_TRIES = 5


class Retention:
    """``ArchiveStore``'s retention."""

    def prune(
        self, cutoffs: dict[int, int], rollup_cutoffs: dict[str, dict[int, int]] | None = None
    ) -> int:
        """Delete each point's chunks that end before its cutoff (ms); chunks deleted.

        ``rollup_cutoffs`` (H9) gives each rollup level its own: ``{"hour": {point: ms},
        "day": ..., "month": ...}``; a rollup goes once it ends by its level's cutoff, and a
        point missing from a level keeps that level. Without it the hourly rollups go with the
        raw values (up to the first value left) and the daily and monthly ones are kept.

        In PostgreSQL a past month whose every chunk is past retention is dropped first, as one
        table. Then one short transaction per point, like ``compact``."""

        deleted, dropped_points = 0, set()
        levels = rollup_cutoffs or {}
        if self.partitions is not None:
            deleted, dropped_points = self.partitions.drop_expired(
                cutoffs, now_ms(), levels.get("hour") if rollup_cutoffs is not None else None
            )
        for point, cutoff in cutoffs.items():
            with self._lock, self._connect() as connection:
                removed = connection.execute(
                    "DELETE FROM chunks WHERE point = ? AND t1 < ?", (point, cutoff)
                ).rowcount
                # A runs point's executions go by their run time.
                connection.execute(
                    "DELETE FROM run_series WHERE point = ? AND run_at < ?", (point, cutoff)
                )
                if rollup_cutoffs is None and (removed or point in dropped_points):
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
        # Each rollup level past its own retention: the hourly rows kept past the raw values
        # stay true (they were summed when the values were there) until then.
        statements = (
            ("hour", "DELETE FROM rollups WHERE point = ? AND hour <= ?", HOUR_MS),
            ("day", "DELETE FROM rollups_coarse WHERE point = ? AND level = 1 AND t1 <= ?", 0),
            ("month", "DELETE FROM rollups_coarse WHERE point = ? AND level = 2 AND t1 <= ?", 0),
        )
        for level, statement, shift in statements:
            for point, cutoff in levels.get(level, {}).items():
                with self._lock, self._connect() as connection:
                    connection.execute(statement, (point, cutoff - shift))
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


def _contended(exc: BaseException) -> bool:
    """A PostgreSQL deadlock or serialization failure: the transaction may simply be retried."""

    return getattr(exc, "sqlstate", None) in ("40P01", "40001")
