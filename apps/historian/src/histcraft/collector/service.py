"""The collector: reads every archived point on its scan, compresses and archives.

It reads the points whose mode is ``archive`` or ``both`` on sources it reads live
(OPC UA) and evaluates calculated points (``collector.calc``); points read from the source on request (``source``) and the derived
series apps write are not collected here.

One asyncio loop holds one task per source (one OPC UA connection each) and,
inside it, one schedule per scan period. Every ``flush_seconds`` the values
archived since the last flush are written as one row for all points (the archive's recent
values, which reads include), together with every point's snapshot and status; every
``archive_seconds`` those rows move into one chunk per point (``ArchiveStore.settle``).
A lost connection writes a "no data" marker for the source's points (the archive never
bridges an outage) and is retried with a growing pause (2 s up to 60 s).

It rereads the configuration database when its version changes, answers the
requests people make from the pages (browse a server, test a connection, backfill
the archive from the source's history, in the background), merges small chunks hourly and deletes values past their retention.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from plantcraft_sdk.contract import recorded_on_change

from histcraft.archive import forecast, rollup
from histcraft.archive.compression import Compressor
from histcraft.archive.store import ArchiveStore, compaction_start, now_ms
from histcraft.catalog import ranges
from histcraft.catalog.models import GATEWAY_KINDS, IMPORT_KIND, LIVE_KINDS, RETIRED_DAYS
from histcraft.catalog.store import CatalogStore
from histcraft.collector import held, imports
from histcraft.collector.backfill import MAX_HOURS, backfill
from histcraft.collector.lease import Lease, lease_for
from histcraft.collector.reading import FUTURE_MS, Reading
from histcraft.config import Settings
from histcraft.i18n import t
from histcraft.sources.csv_watch import CsvWatcher
from histcraft.vault import Vault

LOGGER = logging.getLogger(__name__)
COMPACT_SECONDS = 3600
# What the archive keeps of each point (pages read it, never the whole archive) is counted again
# this often.
TOTALS_SECONDS = 300
# Chunks are merged once they are this old (the newest hour stays in small, fresh chunks).
COMPACT_AGE_MS = 3600 * 1000
# How often the values counted per point and hour reach the archive (``ArchiveStore.settle``).
COUNT_SECONDS = 600.0
REQUEST_WINDOW_MS = 10 * 60 * 1000
MAX_BACKOFF = 60.0
# Good text readings in a row that make a number point a text one (a MODE reading AUTO).
TEXT_READS = 3
# Hours of the source's history a point made text reads again (its old archive held no value).
TEXT_BACKFILL_HOURS = 48
# A standby collector asks for the lease this often.
LEASE_RETRY_SECONDS = 5.0
# A gateway source with no value for this long (or three of its intervals) is disconnected.
GATEWAY_STALE_SECONDS = 60.0
# Series the gateway sent that no point archives, kept per source for Browse.
SEEN_LIMIT = 20_000
# Values a point keeps in memory while the archive cannot be written (a day at one per second);
# past it the oldest go first.
HELD_LIMIT = 86_400


@dataclass
class PointState:
    point: dict[str, Any]
    compressor: Compressor
    pending: list[tuple[int, Any]] = field(default_factory=list)
    reads: int = 0
    archived: int = 0
    status: str = "waiting"
    detail: str = ""
    last: tuple[int, Any] | None = None
    # Good readings in a row that were text while the point is a number (see ``reads_text``).
    texts: int = 0
    # The quality of the values archived now, and its changes not written yet ``(ms, quality)``.
    quality: str = "good"
    changes: list[tuple[int, str]] = field(default_factory=list)

    @property
    def id(self) -> int:
        return int(self.point["id"])

    def configure(self, point: dict[str, Any]) -> None:
        self.point = point
        self.compressor.deviation = float(point["deviation"])
        self.compressor.percent = point.get("deviation_percent")
        self.compressor.exception = float(point.get("exception") or 0.0)
        self.compressor.exception_percent = point.get("exception_percent")
        self.compressor.max_seconds = float(point["max_seconds"])

    @property
    def reads_text(self) -> bool:
        """A number point whose source keeps answering text: it was added as the wrong kind."""

        return self.point["kind"] == "number" and self.texts >= TEXT_READS

    def take(self, reading: Reading) -> None:
        self.reads += 1
        if self.point["kind"] == "number":
            self.texts = self.texts + 1 if reading.good and _text(reading.value) else 0
        quality = reading.quality if reading.good else "bad"
        changed = quality != self.quality
        if reading.good:
            self.status = "ok" if quality == "good" else quality
            self.detail = reading.detail if quality != "good" else ""
            self.last = (reading.at_ms, reading.value)
            out = self.compressor.feed(reading.at_ms, reading.value, keep=changed)
        else:
            self.status, self.detail = "bad", reading.detail
            out = self.compressor.gap(reading.at_ms)
        if changed and (out or not reading.good):
            # Kept only where the archive has a value (or the gap marker) at that time.
            self.quality = quality
            self.changes.append((reading.at_ms, quality))
        self.pending.extend(out)
        self.archived += len(out)

    def lost(self, at_ms: int, detail: str) -> None:
        self.status, self.detail = "disconnected", detail
        out = self.compressor.gap(at_ms)
        self.pending.extend(out)
        self.archived += len(out)


def _compressor(point: dict[str, Any]) -> Compressor:
    return Compressor(
        deviation=float(point["deviation"]),
        max_seconds=float(point["max_seconds"]),
        percent=point.get("deviation_percent"),
        exception=float(point.get("exception") or 0.0),
        exception_percent=point.get("exception_percent"),
        kind=point["kind"],
        step=bool(point["step"]),
    )


def _text(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        float(value)
    except ValueError:
        return True
    return False


def _identity(point: dict[str, Any]) -> tuple:
    return (point["source_id"], point["address"], point["kind"], bool(point["step"]))


class Collector:
    def __init__(
        self,
        settings: Settings,
        catalog: CatalogStore,
        archive: ArchiveStore,
        *,
        reader_factory: Any = None,
        lease: Lease | None = None,
    ):
        self.settings = settings
        # One collector per archive (``collector.lease``): a second one waits as a standby.
        self.lease = lease if lease is not None else lease_for(archive.db)
        self.catalog = catalog
        self.archive = archive
        self.reader_factory = reader_factory or self._reader
        self.points: dict[int, PointState] = {}
        self.sources: dict[str, dict[str, Any]] = {}
        self.source_status: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._signatures: dict[str, tuple] = {}
        self._version = -1
        self._started_ms = now_ms()
        self._last_compact = time.monotonic()
        self._last_totals = -math.inf
        # The recent values left by the last collector move into chunks at the first flush.
        self._last_settle = -math.inf
        # The hourly housekeeping, running beside the flushes (never in their way).
        self._housekeeping: asyncio.Task | None = None
        # CSV sources: the newest time archived per point (read from the archive once).
        self._csv_last: dict[int, int] = {}
        # The CSV import being written (``collector.imports``), one at a time.
        self._importing: asyncio.Task | None = None
        self._last_flush_reads = 0
        self._rate = 0.0
        # Values dropped past HELD_LIMIT, and since when (ms) the archive cannot be written.
        self.dropped = 0
        self.failing_since: int | None = None
        self._lock = threading.RLock()
        self._stop: asyncio.Event | None = None
        self._done_requests: set[int] = set()
        # Backfills run beside collection (they take minutes): request id -> its task.
        self._backfills: dict[int, asyncio.Task] = {}
        self.vault = Vault(settings.secret_key_path)
        # Totalizers' running state by formula (``collector.calc``): kept across reconnects.
        self.totals: dict[str, Any] = {}
        # The gateway's sources (``collector.ingest``): the points of each (source, address),
        # every series it sent (for Browse) and when each source last sent a value.
        self._pushed: dict[tuple[str, str], list[PointState]] = {}
        self.seen: dict[str, dict[str, dict[str, Any]]] = {}
        self._gateway_last: dict[str, int] = {}
        self.gateway_heartbeat: int | None = None
        self._gateway_config = ""

    def _reader_for(self, source: dict[str, Any]) -> Any:
        if source["kind"] == "csv":
            return CsvWatcher(source)
        if source["kind"] == "calc":
            from histcraft.collector.calc import CalcReader

            return CalcReader(self)
        return self.reader_factory(source)

    def calculated(self) -> list[PointState]:
        with self._lock:
            return [s for s in self.points.values() if s.point["source_kind"] == "calc"]

    def password(self, source: dict[str, Any]) -> str:
        return source_password(source, self.catalog, self.vault)

    def _reader(self, source: dict[str, Any]) -> Any:
        if source["kind"] != "opcua":
            raise RuntimeError(t("The collector reads OPC UA sources only."))
        from histcraft.collector.opcua import OpcUaReader

        return OpcUaReader(
            source,
            timeout=self.settings.opcua_timeout,
            batch=self.settings.read_batch,
            password=self.password(source),
            data_dir=self.settings.data_dir,
        )

    # Configuration ---------------------------------------------------------------------

    def reload(self) -> bool:
        """Apply the configuration if it changed; True when it did."""

        version = self.catalog.version()
        if version == self._version:
            return False
        self._version = version
        self.sources = {
            item["id"]: item
            for item in self.catalog.sources()
            if item["enabled"] and item["kind"] in LIVE_KINDS
        }
        wanted = {
            int(item["id"]): item
            for item in self.catalog.points(enabled_only=True, modes=("archive", "both"))
            if item["source_kind"] in LIVE_KINDS
        }
        with self._lock:
            for point_id in list(self.points):
                state = self.points[point_id]
                point = wanted.get(point_id)
                if point is None or _identity(point) != _identity(state.point):
                    state.pending.extend(state.compressor.flush())
                    self._write({point_id: state})
                if point is None:
                    del self.points[point_id]
                elif _identity(point) != _identity(state.point):
                    # The same object: the scan task reading this point holds it.
                    state.point, state.compressor, state.texts = point, _compressor(point), 0
            for point_id, point in wanted.items():
                if point_id in self.points:
                    self.points[point_id].configure(point)
                else:
                    self.points[point_id] = PointState(point, _compressor(point))
        pushed: dict[tuple[str, str], list[PointState]] = defaultdict(list)
        with self._lock:
            for state in self.points.values():
                if state.point["source_kind"] in GATEWAY_KINDS:
                    pushed[(state.point["source_id"], state.point["address"])].append(state)
            self._pushed = dict(pushed)
        self._write_gateway_config()
        # Points removed from the configuration take their archived values with them.
        # Retired points keep theirs until they are purged (``catalog.retire_points``).
        configured = {int(item["id"]) for item in self.catalog.points()}
        configured |= self.catalog.retired_ids()
        orphans = self.archive.point_ids() - configured
        if orphans:
            self.archive.delete_points(orphans)
        return True

    def heal_kinds(self) -> list[int]:
        """Number points whose source reads text become text points (the ids changed).

        A point added while its source could not describe it is a number by default; a MODE
        then archives only "no data" markers and every app finds it empty. Its archive (those
        markers) is dropped and the source's own history read again (a backfill of the point).
        """

        with self._lock:
            wrong = [state for state in self.points.values() if state.reads_text]
            for state in wrong:
                state.pending.clear()
                state.texts = 0
        if not wrong:
            return []
        ids = [state.id for state in wrong]
        self.catalog.make_text(ids)
        self.archive.delete_points(ids)
        by_source: dict[str, list[int]] = defaultdict(list)
        for state in wrong:
            by_source[state.point["source_id"]].append(state.id)
        for source_id, points in by_source.items():
            LOGGER.warning("Points %s read text: archived as text from now on", points)
            self.catalog.add_request(
                "backfill", source_id, "collector", {"hours": TEXT_BACKFILL_HOURS, "points": points}
            )
        return ids

    def _source_points(self, source_id: str) -> list[PointState]:
        with self._lock:
            return [s for s in self.points.values() if s.point["source_id"] == source_id]

    def _signature(self, source_id: str) -> tuple:
        source = self.sources.get(source_id) or {}
        groups = sorted(
            (state.id, state.point["address"], float(state.point["scan_seconds"]))
            for state in self._source_points(source_id)
        )
        keys = ("endpoint", "username", "password_env", "has_password", "namespace_uri", "updated")
        return (tuple(source.get(key) for key in keys), tuple(groups))

    # Writing ----------------------------------------------------------------------------

    def _write(self, states: dict[int, PointState]) -> int:
        """Archive the values pending; when the database fails they stay pending (and raise).

        ``hold`` is one statement, so a failed write stored nothing and the next flush sends the
        same values again.
        """

        batch = {}
        changes: list[tuple[int, int, str]] = []
        for point_id, state in states.items():
            if state.pending:
                batch[point_id] = (state.point["kind"], state.pending)
            changes += [(point_id, at, quality) for at, quality in state.changes]
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
        self.archive.set_state(
            "collector",
            {
                "heartbeat": now_ms(),
                "started": self._started_ms,
                "version": self._version,
                "points": len(states),
                "reads_per_second": round(self._rate, 1),
                "sources": self.source_status,
            },
        )
        return written

    def housekeeping(self, *, force: bool = False) -> dict[str, int]:
        """Merge small chunks and delete values past retention (hourly)."""

        if not force and time.monotonic() - self._last_compact < COMPACT_SECONDS:
            return {}
        self._last_compact = time.monotonic()
        current = now_ms()
        # Each point's retention in effect: its own, else its source's, else the general one.
        # An import is kept until it is deleted, unless it was given a retention of its own.
        # A retention of 0 days keeps the point forever.
        cutoffs = {
            int(point["id"]): current - int(point["retention_days"]) * 86400000
            for point in self.catalog.points()
            if int(point["retention_days"] or 0) > 0
            and (
                point["source_kind"] != IMPORT_KIND
                or point["origins"]["retention_days"] != "general"
            )
        }
        purged = self.catalog.purge_retired(older_than_ms=current - RETIRED_DAYS * 86400000)
        if purged:
            LOGGER.info("Retired points deleted for good after %s days: %s", RETIRED_DAYS, purged)
        pruned = self.archive.prune(cutoffs)
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

    async def _housekeep(self) -> None:
        try:
            await asyncio.to_thread(self.count_totals)
            await asyncio.to_thread(self.housekeeping)
        except Exception:  # noqa: BLE001 - the next hour tries again; collection goes on
            LOGGER.exception("Housekeeping failed")

    # Requests ---------------------------------------------------------------------------

    async def answer_requests(self) -> None:
        since = now_ms() - REQUEST_WINDOW_MS
        waiting = [r for r in self.catalog.requests(since) if r["id"] not in self._done_requests]
        if not waiting:
            return
        done = self.archive.done_requests([r["id"] for r in waiting])
        for request in waiting:
            if request["id"] in done:
                self._done_requests.add(request["id"])
                continue
            if request["kind"] == "backfill":
                if request["id"] not in self._backfills:
                    self._backfills[request["id"]] = asyncio.create_task(self._backfill(request))
                continue
            status, result = await self._answer(request)
            self.archive.finish_request(request["id"], status, result)
            self._done_requests.add(request["id"])

    async def _answer(self, request: dict[str, Any]) -> tuple[str, Any]:
        source = next((s for s in self.catalog.sources() if s["id"] == request["source_id"]), None)
        if source is None:
            return "error", {"detail": t("Source {id} not found.", id=request["source_id"])}
        if source["kind"] == "csv":
            return await asyncio.to_thread(self._answer_csv, source, request)
        if source["kind"] == "pi_web_api":
            return await asyncio.to_thread(self._answer_history, source, request)
        if source["kind"] in ("derived", "system", "lab"):
            return "error", {"detail": t("A derived source is written by its app.")}
        if source["kind"] in GATEWAY_KINDS:
            return self._answer_gateway(source, request)
        try:
            reader = self._reader_for(source)
        except Exception as exc:  # noqa: BLE001 - e.g. direct OPC UA turned off
            return "error", {"detail": _describe(exc)}
        try:
            await asyncio.wait_for(reader.connect(), self.settings.opcua_timeout + 5)
            if request["kind"] == "browse":
                detail = request.get("detail") or {}
                result = await asyncio.wait_for(
                    reader.browse(detail.get("root") or None),
                    max(self.settings.opcua_timeout * 30, 120),
                )
            elif request["kind"] == "read":
                addresses = list((request.get("detail") or {}).get("addresses") or [])[:100]
                readings = await reader.read(addresses)
                result = {
                    "values": {
                        address: {
                            "at": r.at_ms,
                            "value": r.value,
                            "good": r.good,
                            "detail": r.detail,
                        }
                        for address, r in readings.items()
                    }
                }
            else:
                result = await reader.test()
            return "ok", result
        except Exception as exc:  # noqa: BLE001 - the answer says what failed
            answer = {"detail": str(exc) if hasattr(exc, "certificate") else _describe(exc)}
            # A secure source not trusted yet: the page shows the certificate to trust.
            if hasattr(exc, "certificate"):
                answer["certificate"] = exc.certificate
            return "error", answer
        finally:
            await reader.close()

    async def _backfill(self, request: dict[str, Any]) -> None:
        try:
            status, result = await asyncio.to_thread(self._run_backfill, request)
        except Exception as exc:  # noqa: BLE001 - the answer says what failed
            LOGGER.exception("Backfill of %s failed", request["source_id"])
            status, result = "error", {"detail": _describe(exc)}
        self.archive.finish_request(request["id"], status, result)
        self._done_requests.add(request["id"])
        self._backfills.pop(request["id"], None)

    def _run_backfill(self, request: dict[str, Any]) -> tuple[str, Any]:
        """The source's history of its archived signals into the archive (collector/backfill.py)."""

        from histcraft.sources.history import open_source

        source = next((s for s in self.catalog.sources() if s["id"] == request["source_id"]), None)
        if source is None:
            return "error", {"detail": t("Source {id} not found.", id=request["source_id"])}
        points = self.catalog.points(
            source_id=source["id"], enabled_only=True, modes=("archive", "both")
        )
        detail = request.get("detail") or {}
        if detail.get("points"):
            only = {int(item) for item in detail["points"]}
            points = [point for point in points if int(point["id"]) in only]
        if not points:
            return "error", {"detail": t("The source has no archived signals to backfill.")}
        try:
            hours = min(max(float(detail.get("hours") or 24), 0.0), MAX_HOURS)
        except (TypeError, ValueError):
            hours = 24.0
        until = int(request["created_ms"])
        history = open_source(source, self.password(source))
        LOGGER.info("Backfill of %s: %d signals, %g h", source["id"], len(points), hours)
        result = backfill(history, self.archive, points, until - int(hours * 3600_000), until)
        return ("ok" if result["signals"] or not result["failed"] else "error"), result

    def _answer_csv(self, source: dict[str, Any], request: dict[str, Any]) -> tuple[str, Any]:
        """Browse or test a CSV source: the tags of its newest files, or what it finds."""

        try:
            watcher = CsvWatcher(source)
            if request["kind"] == "browse":
                return "ok", watcher.browse()
            if request["kind"] == "test":
                return "ok", watcher.test()
            return "error", {"detail": t("A CSV source is read when its files change.")}
        except Exception as exc:  # noqa: BLE001 - the answer says what failed
            return "error", {"detail": _describe(exc)}

    def _answer_history(self, source: dict[str, Any], request: dict[str, Any]) -> tuple[str, Any]:
        """Browse or test a source read by its history interface (PI Web API, CSV)."""

        from histcraft.sources.history import open_source

        try:
            history = open_source(source, self.password(source))
            if request["kind"] == "browse":
                return "ok", history.browse((request.get("detail") or {}).get("root") or None)
            if request["kind"] == "test":
                return "ok", history.test()
            return "error", {"detail": t("This source is read by history, not by value.")}
        except Exception as exc:  # noqa: BLE001 - the answer says what failed
            return "error", {"detail": _describe(exc)}

    # Running ------------------------------------------------------------------------------

    async def _source_task(self, source_id: str) -> None:
        backoff = 2.0
        while True:
            source = self.sources.get(source_id)
            if source is None:
                return
            reader = None
            try:
                reader = self._reader_for(source)
                await asyncio.wait_for(reader.connect(), self.settings.opcua_timeout + 5)
                self.source_status[source_id] = {
                    "status": "connected",
                    "detail": "",
                    "since": now_ms(),
                }
                backoff = 2.0
                if isinstance(reader, CsvWatcher):
                    await self._watch_csv(source_id, reader)
                else:
                    await self._poll(source_id, reader)
            except asyncio.CancelledError:
                if reader is not None:
                    await reader.close()
                raise
            except Exception as exc:  # noqa: BLE001 - every failure is a lost connection
                detail = _describe(exc)
                LOGGER.warning("Source %s: %s", source_id, detail)
                self.source_status[source_id] = {
                    "status": "disconnected",
                    "detail": detail,
                    "since": now_ms(),
                }
                with self._lock:
                    for state in self._source_points(source_id):
                        state.lost(now_ms(), detail)
            if reader is not None:
                await reader.close()
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)

    async def _watch_csv(self, source_id: str, reader: CsvWatcher) -> None:
        """Check a CSV source's files every ``check_minutes``; archive the rows after the newest
        value each point has."""

        period = (
            float((self.sources.get(source_id) or {}).get("options", {}).get("check_minutes") or 5)
            * 60
        )
        while True:
            found = await asyncio.to_thread(reader.check)
            await asyncio.to_thread(self._take_csv, source_id, found)
            detail = (
                t(
                    "{count} lines skipped: values or times that could not be read.",
                    count=reader.skipped,
                )
                if reader.skipped
                else ""
            )
            self.source_status[source_id] = {
                "status": "connected",
                "detail": detail,
                "since": (self.source_status.get(source_id) or {}).get("since") or now_ms(),
                "checked": now_ms(),
                "files": len(reader.seen),
            }
            await asyncio.sleep(period)

    def _take_csv(self, source_id: str, found: dict[str, Any]) -> None:
        for state in self._source_points(source_id):
            series = found.get(state.point["address"])
            if series is None or not len(series.times):
                continue
            if state.id not in self._csv_last:
                span = self.archive.span(state.id)
                self._csv_last[state.id] = span[1] if span else -(2**62)
            after = self._csv_last[state.id]
            fresh = [
                (int(at), value)
                for at, value in zip(series.times.tolist(), series.values, strict=True)
                if at > after
            ]
            if not fresh:
                continue
            with self._lock:
                state.pending.extend(fresh)
                state.changes += [(at, code) for at, code in series.qualities if at > after]
                state.reads += len(fresh)
                state.archived += len(fresh)
                state.last = fresh[-1]
                state.status, state.detail = "ok", ""
            self._csv_last[state.id] = fresh[-1][0]

    async def _poll(self, source_id: str, reader: Any) -> None:
        groups: dict[float, list[PointState]] = defaultdict(list)
        for state in self._source_points(source_id):
            groups[float(state.point["scan_seconds"])].append(state)
        if not groups:
            while True:  # nothing to read: keep the connection, wait for points
                await asyncio.sleep(3600)
        await asyncio.gather(
            *(self._scan(reader, period, states) for period, states in groups.items())
        )

    async def _scan(self, reader: Any, period: float, states: list[PointState]) -> None:
        by_address: dict[str, list[PointState]] = defaultdict(list)
        for state in states:
            by_address[state.point["address"]].append(state)
        addresses = list(by_address)
        next_at = time.monotonic()
        while True:
            readings = await asyncio.wait_for(
                reader.read(addresses), self.settings.opcua_timeout + 5
            )
            with self._lock:
                for address, reading in readings.items():
                    for state in by_address.get(address, []):
                        state.take(reading)
            next_at += period
            delay = next_at - time.monotonic()
            if delay < 0:  # reads take longer than the scan: skip, do not pile up
                next_at = time.monotonic()
                delay = 0
            await asyncio.sleep(delay)

    async def _sync_tasks(self) -> None:
        for source_id in list(self._tasks):
            signature = self._signature(source_id) if source_id in self.sources else None
            if signature != self._signatures.get(source_id):
                self._tasks.pop(source_id).cancel()
                self._signatures.pop(source_id, None)
                self.source_status.pop(source_id, None)
        for source_id, source in self.sources.items():
            if source["kind"] in GATEWAY_KINDS:
                continue  # pushed by the gateway: no task reads them
            if source_id not in self._tasks:
                self._signatures[source_id] = self._signature(source_id)
                self._tasks[source_id] = asyncio.create_task(self._source_task(source_id))

    # The gateway --------------------------------------------------------------------------

    def _ingest_server(self) -> Any:
        """The web server the gateway writes to (``collector.ingest``); None when it is off."""

        if not self.settings.ingest_port:
            return None
        import uvicorn

        from histcraft.collector.gateway import gateway_token
        from histcraft.collector.ingest import ingest_app

        app = ingest_app(self, gateway_token(self.settings.data_dir))
        config = uvicorn.Config(
            app,
            host="0.0.0.0",  # noqa: S104 - the collector's own container network
            port=self.settings.ingest_port,
            log_level="warning",
            access_log=False,
            lifespan="off",
        )
        server = uvicorn.Server(config)
        server.install_signal_handlers = lambda: None  # the collector handles its signals
        return server

    def ingest(self, metrics: list[Any]) -> int:
        """Values the gateway pushed: archived at their points, kept as seen; the count taken."""

        from histcraft.collector.ingest import GATEWAY_SOURCE, split

        now = now_ms()
        taken = 0
        with self._lock:
            for metric in metrics:
                source_id, values = split(metric)
                if source_id == GATEWAY_SOURCE:
                    self.gateway_heartbeat = now
                    continue
                source = self.sources.get(source_id)
                if source is None or source["kind"] not in GATEWAY_KINDS:
                    continue
                at = metric.at_ms if metric.at_ms is not None else now
                if at > now + FUTURE_MS:
                    at = now
                self._gateway_last[source_id] = now
                seen = self.seen.setdefault(source_id, {})
                for address, (value, series) in values.items():
                    if address in seen or len(seen) < SEEN_LIMIT:
                        seen[address] = {"at": at, "value": value, **series}
                    for state in self._pushed.get((source_id, address), []):
                        if state.last is not None and at <= state.last[0]:
                            continue  # the archive only moves forward
                        state.take(Reading(at, _pushed_value(value, state.point["kind"]), True))
                        taken += 1
        return taken

    def check_gateway(self) -> None:
        """Each gateway source connected while values arrive; a silence is a gap."""

        now = now_ms()
        with self._lock:
            for source_id, source in self.sources.items():
                if source["kind"] not in GATEWAY_KINDS:
                    continue
                last = self._gateway_last.get(source_id)
                interval = float(source.get("default_scan_seconds") or 0)
                stale = max(GATEWAY_STALE_SECONDS, 3 * interval) * 1000
                current = self.source_status.get(source_id) or {}
                if last is not None and now - last < stale:
                    if current.get("status") != "connected":
                        self.source_status[source_id] = {
                            "status": "connected",
                            "detail": "",
                            "since": now,
                        }
                    continue
                detail = (
                    t("No values from the gateway for {seconds} s.", seconds=int(stale / 1000))
                    if last is not None
                    else t("Waiting for the gateway's first values.")
                )
                if current.get("status") == "connected" or not current:
                    self.source_status[source_id] = {
                        "status": "disconnected",
                        "detail": detail,
                        "since": now,
                    }
                    for state in self._source_points(source_id):
                        if state.status not in ("waiting", "disconnected"):
                            state.lost(now, detail)

    def _write_gateway_config(self) -> None:
        if not self.settings.ingest_port:
            return
        from histcraft.collector.gateway import write_config

        try:
            self._gateway_config = write_config(
                self.settings, self.catalog.sources(), self.password, self._gateway_config
            )
        except Exception:  # noqa: BLE001 - one bad source must not stop collection
            LOGGER.exception("The gateway's configuration could not be written")

    def _answer_gateway(self, source: dict[str, Any], request: dict[str, Any]) -> tuple[str, Any]:
        """Browse or test a gateway source: what it has sent so far."""

        with self._lock:
            seen = dict(self.seen.get(source["id"], {}))
            last = self._gateway_last.get(source["id"])
        if not self.settings.ingest_port:
            return "error", {"detail": t("The gateway is not set up (HISTCRAFT_INGEST_PORT).")}
        if not seen:
            return "error", {
                "detail": t(
                    "No values received from the gateway yet. It sends every interval: check"
                    " the address, the credentials and that the histcraft-gateway service runs."
                )
            }
        if request["kind"] == "test":
            return "ok", {"series": len(seen), "last": last}
        from histcraft.collector.gateway import variable

        variables = [variable(source["kind"], address, item) for address, item in seen.items()]
        variables.sort(key=lambda item: item["tag"])
        return "ok", {
            "variables": variables,
            "truncated": len(seen) >= SEEN_LIMIT,
            "limit": SEEN_LIMIT,
        }

    async def _take_lease(self) -> bool:
        """Wait for the archive's lease; False when stopped first."""

        assert self._stop is not None
        waiting = False
        while not self._stop.is_set():
            try:
                if await asyncio.to_thread(self.lease.acquire):
                    if waiting:
                        LOGGER.info("The other collector stopped: this one takes over")
                    return True
            except Exception as exc:  # noqa: BLE001 - database not up yet: ask again
                LOGGER.warning("Collector lease not available yet: %s", _describe(exc))
            if not waiting:
                LOGGER.warning(
                    "Another collector is writing this archive: this one waits as a standby"
                )
                waiting = True
            try:
                await asyncio.wait_for(self._stop.wait(), LEASE_RETRY_SECONDS)
            except TimeoutError:
                pass
        return False

    async def run(self, stop: asyncio.Event | None = None) -> bool:
        """Collect until ``stop``; False when the lease was lost (another collector may write)."""

        self._stop = stop or asyncio.Event()
        if not await self._take_lease():
            return True
        try:
            return await self._collect()
        finally:
            self.lease.release()

    async def _flush_or_hold(self) -> bool:
        """One flush; when the database fails the values stay pending for the next one."""

        try:
            await asyncio.to_thread(self.flush)
        except Exception as exc:  # noqa: BLE001 - a database restart must not stop collection
            if self.failing_since is None:
                self.failing_since = now_ms()
            LOGGER.warning(
                "The archive could not be written (%s): values kept, retried", _describe(exc)
            )
            return False
        if self.failing_since is not None:
            LOGGER.info("The archive is written again")
            self.failing_since = None
        return True

    async def _collect(self) -> bool:
        assert self._stop is not None
        LOGGER.info("Historian collector started")
        lost = False
        last_flush = time.monotonic()
        last_config = -math.inf
        server = self._ingest_server()
        serving = asyncio.create_task(server.serve()) if server is not None else None
        try:
            while not self._stop.is_set():
                now = time.monotonic()
                if now - last_config >= self.settings.config_seconds:
                    last_config = now
                    if not await asyncio.to_thread(self.lease.alive):
                        # The lock went with its connection: stop before two collectors write.
                        LOGGER.error("Collector lease lost: stopping collection")
                        lost = True
                        break
                    try:
                        self.heal_kinds()
                        if self.reload():
                            await self._sync_tasks()
                        self.check_gateway()
                        await self.answer_requests()
                        self._start_imports()
                    except Exception:  # noqa: BLE001 - a bad config must not stop collection
                        LOGGER.exception("Configuration reload failed")
                if now - last_flush >= self.settings.flush_seconds:
                    last_flush = now
                    if await self._flush_or_hold():
                        # Compaction and rollups take minutes on a large archive (8,000 points:
                        # about two): they run in their own thread, so the flushes go on.
                        if self._housekeeping is None or self._housekeeping.done():
                            self._housekeeping = asyncio.create_task(self._housekeep())
                try:
                    await asyncio.wait_for(self._stop.wait(), 0.5)
                except TimeoutError:
                    pass
        finally:
            if server is not None and serving is not None:
                server.should_exit = True
                await asyncio.wait({serving}, timeout=10)
            for task in [*self._tasks.values(), *self._backfills.values()]:
                task.cancel()
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
            self._tasks.clear()
            if self._housekeeping is not None and not self._housekeeping.done():
                # Each point is compacted in its own transaction: stopping halfway loses nothing.
                await asyncio.wait({self._housekeeping}, timeout=20)
            self._signatures.clear()
            # A stop is a gap: the archive must not draw a line across the time nobody read.
            stopped = now_ms()
            with self._lock:
                for state in self.points.values():
                    state.lost(stopped, t("Collector stopped."))
            try:
                self.flush(settle=True)
            except Exception:  # noqa: BLE001 - the database that dropped the lease may be gone
                LOGGER.exception("Last flush failed")
                self.save_held()
            LOGGER.info("Historian collector stopped")
        return not lost


class CollectorThread:
    """The collector in a background thread of ``histcraft serve`` (embedded mode)."""

    def __init__(self, collector: Collector):
        self.collector = collector
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._main, name="histcraft-collector", daemon=True)
        self._thread.start()
        self._ready.wait(5)

    def _main(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._stop = asyncio.Event()
        self._ready.set()
        try:
            self._loop.run_until_complete(self.collector.run(self._stop))
        finally:
            self._loop.close()

    def stop(self, timeout: float = 15.0) -> None:
        if self._thread is None or self._loop is None or self._stop is None:
            return
        self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(timeout)
        self._thread = None


def _pushed_value(value: Any, kind: str) -> Any:
    if kind == "number" and isinstance(value, bool | int):
        return float(value)
    return value


def _describe(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError | asyncio.TimeoutError):
        return t("No answer from the server in time.")
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def source_password(source: dict[str, Any], catalog: CatalogStore, vault: Vault) -> str:
    """A source's password: its ``HISTCRAFT_SECRET_<NAME>`` variable, else the stored one."""

    if source.get("password_env"):
        return os.environ.get(source["password_env"], "")
    return vault.decrypt(catalog.secret(source["id"]))
