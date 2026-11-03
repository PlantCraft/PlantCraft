"""``Collector``'s writes to the archive: flushes, the values held while the archive cannot be
written, and housekeeping (compaction, retention, totals, ranges, imports and the data lake).
Part of ``Collector`` (``collector.service``)."""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any

from plantcraft_sdk.contract import recorded_on_change

from histcraft.archive import forecast, rollup
from histcraft.archive.query import Reader, point_ref
from histcraft.archive.store import compaction_start, now_ms
from histcraft.catalog import ranges
from histcraft.catalog.models import RETIRED_DAYS
from histcraft.collector import held, imports
from histcraft.collector.state import (
    COMPACT_AGE_MS,
    COMPACT_SECONDS,
    COUNT_SECONDS,
    HELD_LIMIT,
    LAKE_SECONDS,
    LOGGER,
    TOTALS_SECONDS,
    PointState,
)
from histcraft.export import lake


class Archiving:
    """``Collector``'s writes and housekeeping."""

    # Writing ----------------------------------------------------------------------------

    def _write(self, states: dict[int, PointState]) -> int:
        """Archive the values pending; when the database fails they stay pending (and raise).

        ``hold`` is one statement, so a failed write stored nothing and the next flush sends the
        same values again.
        """

        batch = {}
        changes: list[tuple] = []
        for point_id, state in states.items():
            if state.pending:
                batch[point_id] = (state.point["kind"], state.pending)
            changes += [(point_id, *change) for change in state.changes]
        try:
            written = self.archive.hold(batch) if batch else 0
        except Exception:
            self._hold(states)
            raise
        for state in states.values():
            state.pending = []
        if changes:
            self.archive.put_qualities(changes)
        for state in states.values():
            state.changes = []
        return written

    def _hold(self, states: dict[int, PointState]) -> None:
        """Keep at most ``HELD_LIMIT`` pending values per point (the newest)."""

        for state in states.values():
            extra = len(state.pending) - HELD_LIMIT
            if extra > 0:
                del state.pending[:extra]
                self.dropped += extra
                LOGGER.error(
                    "Point %s: %s values dropped while the archive could not be written",
                    state.id,
                    extra,
                )

    def _write_held(self) -> int:
        """Archive the values a previous collector kept on disk (see ``collector.held``)."""

        path = held.held_path(self.settings.data_dir)
        if not path.exists():
            return 0
        saved = held.load(path)
        batch = {point: item for point, item in saved.items() if point in self.points}
        written = self.archive.append(batch) if batch else 0
        path.unlink(missing_ok=True)
        LOGGER.info("Archived %s values kept on disk by the last collector", written)
        return written

    def save_held(self) -> int:
        """Write the values still pending to disk, for the next collector; values saved."""

        with self._lock:
            batch = {
                point_id: (state.point["kind"], list(state.pending))
                for point_id, state in self.points.items()
                if state.pending
            }
        if not batch:
            return 0
        count = held.save(held.held_path(self.settings.data_dir), batch)
        with self._lock:
            for point_id in batch:
                if point_id in self.points:
                    self.points[point_id].pending = []
        LOGGER.warning("The archive could not be written: %s values kept on disk", count)
        return count

    def flush(self, *, settle: bool = False) -> int:
        """Write archived values and every point's snapshot and status; every
        ``archive_seconds`` (or with ``settle``) move the recent values into chunks."""

        with self._lock:
            states = dict(self.points)
            self._write_held()
            written = self._write(states)
            rows = []
            reads = 0
            for state in states.values():
                reads += state.reads
                snap = state.compressor.snapshot or state.compressor.archived or state.last
                value = snap[1] if snap else None
                if isinstance(value, float) and not math.isfinite(value):
                    value = None
                rows.append(
                    {
                        "point": state.id,
                        "ts": snap[0] if snap else None,
                        "value": value,
                        "status": state.status,
                        "detail": state.detail[:300],
                        "reads": state.reads,
                        "archived": state.archived,
                    }
                )
        if rows:
            self.archive.put_snapshots(rows)
        if settle or time.monotonic() - self._last_settle >= self.settings.archive_seconds:
            # Outside the lock: the scans go on taking values while the rows move into chunks.
            # Counts of values per hour every few minutes, and at the last flush.
            self.archive.settle(count_every=0.0 if settle else COUNT_SECONDS)
            self._last_settle = time.monotonic()
        elapsed = max(self.settings.flush_seconds, 1e-3)
        self._rate = max(reads - self._last_flush_reads, 0) / elapsed
        self._last_flush_reads = reads
        self._note_changes()
        self._measure_buffer()
        self.archive.set_state(
            "collector",
            {
                "heartbeat": now_ms(),
                "started": self._started_ms,
                "version": self._version,
                "points": len(states),
                "reads_per_second": round(self._rate, 1),
                "sources": self.source_status,
                "gateway_buffer_bytes": self._buffer_bytes,
            },
        )
        return written

    def _measure_buffer(self) -> None:
        """What waits in the gateway's disk buffer, once a minute (only with a gateway)."""

        if not self.settings.ingest_port or time.monotonic() - self._buffer_checked < 60:
            return
        from histcraft.collector.gateway import buffer_bytes

        self._buffer_checked = time.monotonic()
        try:
            self._buffer_bytes = buffer_bytes(self.settings.data_dir)
        except OSError:
            self._buffer_bytes = 0

    def _note_changes(self) -> None:
        """Write each source whose state changed since the last flush to its history."""

        try:
            if self._noted is None:
                self._noted = self.catalog.last_source_statuses()
            changed = []
            for source_id, current in list(self.source_status.items()):
                status = str(current.get("status") or "")
                if status and self._noted.get(source_id) != status:
                    at = int(current.get("since") or now_ms())
                    changed.append((source_id, at, status, str(current.get("detail") or "")))
            self.catalog.add_source_events(changed)
            for source_id, _at, status, _detail in changed:
                self._noted[source_id] = status
        except Exception:  # noqa: BLE001 - the history never stops the values
            LOGGER.exception("Source history not written")

    def housekeeping(self, *, force: bool = False) -> dict[str, int]:
        """Merge small chunks and delete values past retention (hourly)."""

        if not force and time.monotonic() - self._last_compact < COMPACT_SECONDS:
            return {}
        self._last_compact = time.monotonic()
        current = now_ms()
        # Each point's retention in effect: its own, else its source's, else the general one.
        # An import is kept until it is deleted, unless it was given a retention of its own.
        # A retention of 0 days keeps the point forever. Each rollup level has its own (H9).
        cutoffs, rollup_cutoffs = forecast.cutoffs(
            self.catalog.points(), self.catalog.settings(), current
        )
        purged = self.catalog.purge_retired(older_than_ms=current - RETIRED_DAYS * 86400000)
        if purged:
            LOGGER.info("Retired points deleted for good after %s days: %s", RETIRED_DAYS, purged)
        pruned = self.archive.prune(cutoffs, rollup_cutoffs)
        # Snapshots a database crash emptied (an UNLOGGED table), from the archive.
        self.archive.refill_snapshots()
        older = current - COMPACT_AGE_MS
        merged = self.archive.compact(older, since_ms=compaction_start(older))
        # A month the collector no longer writes, copied once without compaction's dead space.
        rewritten = self.archive.rewrite_closed(current)
        if rewritten:
            LOGGER.info("%s: rewritten without dead space", rewritten)
        # Hourly rollups for long trends, each point's held or linear like its reads.
        rolled = rollup.build(
            self.archive,
            [
                (
                    int(point["id"]),
                    bool(point["step"]) or recorded_on_change(point["signal"], point["kind"]),
                )
                for point in self.catalog.points()
                if point["kind"] == "number"
            ],
        )
        suggested = self.suggest_ranges(current)
        self._last_totals = time.monotonic()
        self.archive.refresh_totals()
        # The disk forecast, for the Settings page and the archive.disk_low condition (D4).
        self.archive.set_state("forecast", self.forecast(current))
        return {
            "pruned_chunks": pruned,
            "merged_chunks": merged,
            "rewritten_months": 1 if rewritten else 0,
            "rollup_hours": rolled,
            "purged_points": len(purged),
            "suggested_ranges": suggested,
        }

    def forecast(self, current: int) -> dict[str, Any]:
        """How fast the archive grows and when the disk fills (``archive.forecast``)."""

        where = self.archive.path.parent if self.archive.path else self.settings.data_dir
        return forecast.forecast(
            self.catalog.points(), self.archive.point_stats(), forecast.free_bytes(where), current
        )

    def suggest_ranges(self, current: int) -> int:
        """Suggest a range for the number points that have none once they have a day of values
        (round 8 D2, ``catalog.ranges``); a person confirms it on the point page."""

        found: dict[int, tuple[float, float]] = {}
        for point in self.catalog.points():
            if (
                point["kind"] != "number"
                or point["step"]
                or point["range_origin"]
                or point.get("managed_by")
            ):
                continue
            span = self.archive.span(int(point["id"]))
            if span is None or current - span[0] < ranges.SUGGEST_AFTER_MS:
                continue
            end = span[0] + ranges.SUGGEST_AFTER_MS
            times, values = self.archive.read(int(point["id"]), span[0], end)
            # The read carries the value just after the day too: left out.
            bounds = ranges.suggest(values[times <= end])
            if bounds is not None:
                found[int(point["id"])] = bounds
        return self.catalog.suggest_ranges(found)

    def count_totals(self) -> None:
        """Count again what the archive keeps of each point, every ``TOTALS_SECONDS``."""

        if time.monotonic() - self._last_totals < TOTALS_SECONDS:
            return
        self._last_totals = time.monotonic()
        self.archive.refresh_totals()

    def _start_imports(self) -> None:
        """Write the values of confirmed CSV imports, one file at a time, beside collection;
        with none waiting, check the folder of a repeating import that is due."""

        if self._importing is not None and not self._importing.done():
            return
        files = imports.waiting(self.settings.data_dir)
        if files:
            self._importing = asyncio.create_task(
                asyncio.to_thread(imports.write_import, files[0], self.catalog, self.archive)
            )
            return
        source = next(
            (s for s in imports.repeating(self.catalog) if imports.due(s, self.archive)), None
        )
        if source is not None:
            self._importing = asyncio.create_task(
                asyncio.to_thread(imports.check_folder, source, self.catalog, self.archive)
            )

    def feed_lake(self, *, force: bool = False) -> list[Any]:
        """Write the saved exports' data lake files that are due (``export.lake``), every
        ``LAKE_SECONDS``; nothing when no export has a feed on."""

        if not force and time.monotonic() - self._last_lake < LAKE_SECONDS:
            return []
        self._last_lake = time.monotonic()
        exports = self.saved_exports.list()
        if not any(item.get("lake") in lake.SCHEDULES for item in exports):
            self.lake_feeds.forget(set())
            return []
        return lake.feed(
            self.settings.lake_path,
            exports,
            self.lake_feeds,
            self.catalog.points(),
            Reader(self.archive),
            point_ref,
            now_ms(),
            keep_days=self.settings.lake_keep_days,
        )

    async def _housekeep(self) -> None:
        try:
            # The lake first: compaction may take minutes, a period's file should not wait.
            await asyncio.to_thread(self.feed_lake)
            await asyncio.to_thread(self.count_totals)
            await asyncio.to_thread(self.housekeeping)
        except Exception:  # noqa: BLE001 - the next hour tries again; collection goes on
            LOGGER.exception("Housekeeping failed")
