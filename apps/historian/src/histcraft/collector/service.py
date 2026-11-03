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

This module puts ``Collector`` together: its configuration, its tasks per source, the lease and
the loop, and ``CollectorThread``. The rest lives by subject: ``collector.state`` (the
collector's sizes and periods, and each point's state), and the collector's methods in the
mixins ``collector.archiving.Archiving`` (writing, held values and housekeeping),
``collector.answers.Answers`` (the requests people make from the pages),
``collector.sparkplug_intake.SparkplugIntake`` and ``collector.gateway_intake.GatewayIntake``.
The names other modules import from here stay importable from here.
"""

from __future__ import annotations

import asyncio
import dataclasses
import math
import threading
import time
from collections import defaultdict
from typing import Any

from histcraft.archive.store import ArchiveStore, now_ms
from histcraft.catalog.models import GATEWAY_KINDS, LIVE_KINDS, PUSHED_KINDS
from histcraft.catalog.store import CatalogStore
from histcraft.collector.answers import Answers
from histcraft.collector.archiving import Archiving
from histcraft.collector.gateway_intake import GatewayIntake
from histcraft.collector.lease import Lease, lease_for
from histcraft.collector.reading import Reading
from histcraft.collector.sparkplug_intake import SparkplugIntake
from histcraft.collector.state import (
    COMPACT_AGE_MS,
    COMPACT_SECONDS,
    COUNT_SECONDS,
    GATEWAY_STALE_SECONDS,
    HELD_LIMIT,
    LAKE_SECONDS,
    LOGGER,
    MAX_BACKOFF,
    REQUEST_WINDOW_MS,
    SEEN_LIMIT,
    SPARKPLUG_TICK,
    SUBSCRIPTION_CHECK_SECONDS,
    TEXT_BACKFILL_HOURS,
    TEXT_READS,
    TOTALS_SECONDS,
    PointState,
    _births_detail,
    _compressor,
    _describe,
    _identity,
    _pushed_value,
    _text,
    source_password,
)
from histcraft.config import Settings
from histcraft.export import lake
from histcraft.export.saved import SavedExports
from histcraft.i18n import t
from histcraft.sources.csv_watch import CsvWatcher
from histcraft.sparkplug import Births
from histcraft.vault import Vault

# The names other modules import from here, from before the split.
__all__ = [
    "COMPACT_AGE_MS",
    "COMPACT_SECONDS",
    "COUNT_SECONDS",
    "GATEWAY_STALE_SECONDS",
    "HELD_LIMIT",
    "LAKE_SECONDS",
    "LOGGER",
    "MAX_BACKOFF",
    "PointState",
    "REQUEST_WINDOW_MS",
    "SEEN_LIMIT",
    "SPARKPLUG_TICK",
    "SUBSCRIPTION_CHECK_SECONDS",
    "TEXT_BACKFILL_HOURS",
    "TEXT_READS",
    "TOTALS_SECONDS",
    "_births_detail",
    "_compressor",
    "_describe",
    "_identity",
    "_pushed_value",
    "_text",
    "source_password",
]
# A standby collector asks for the lease this often.
LEASE_RETRY_SECONDS = 5.0


class Collector(Archiving, Answers, SparkplugIntake, GatewayIntake):
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
        # The saved exports a data lake feed sends, and where each feed is (``export.lake``).
        self.saved_exports = SavedExports(catalog.db)
        self.lake_feeds = lake.LakeFeeds(catalog.db)
        self.reader_factory = reader_factory or self._reader
        self.points: dict[int, PointState] = {}
        self.sources: dict[str, dict[str, Any]] = {}
        self.source_status: dict[str, dict[str, Any]] = {}
        # The state last written to each source's history (``catalog.source_events``, H13);
        # read from the catalog at the first flush.
        self._noted: dict[str, str] | None = None
        # The gateway's disk buffer (store and forward, H3), measured once a minute.
        self._buffer_bytes = 0
        self._buffer_checked = -math.inf
        self._tasks: dict[str, asyncio.Task] = {}
        self._signatures: dict[str, tuple] = {}
        self._version = -1
        self._started_ms = now_ms()
        self._last_compact = time.monotonic()
        self._last_totals = -math.inf
        self._last_lake = -math.inf
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
        # Sparkplug B sources (``collector.sparkplug``): what each learnt from the births, kept
        # across reconnects (aliases hold until the node is born again).
        self.births: dict[str, Births] = {}

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
        if source["kind"] == "sparkplug":
            from histcraft.collector.sparkplug import SparkplugListener

            return SparkplugListener(
                source, password=self.password(source), timeout=self.settings.opcua_timeout
            )
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
                if state.point["source_kind"] in PUSHED_KINDS:
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
        keys = ("endpoint", "username", "password_env", "has_password", "namespace_uri", "updated")
        if source.get("kind") in PUSHED_KINDS:
            # Values find their points as they arrive: a point added keeps the subscription.
            return (tuple(source.get(key) for key in keys),)
        groups = sorted(
            (state.id, state.point["address"], float(state.point["scan_seconds"]))
            for state in self._source_points(source_id)
        )
        return (tuple(source.get(key) for key in keys), tuple(groups))

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
                elif source["kind"] == "sparkplug":
                    await self._listen(source_id, reader)
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
        options = (self.sources.get(source_id) or {}).get("options") or {}
        if options.get("subscribe") and hasattr(reader, "subscribe"):
            await self._monitor(source_id, reader, groups)
            return
        await asyncio.gather(
            *(self._scan(reader, period, states) for period, states in groups.items())
        )

    async def _monitor(
        self, source_id: str, reader: Any, groups: dict[float, list[PointState]]
    ) -> None:
        """An OPC UA source that opts in (``subscribe``, H4): the server reports each change,
        sampled at the point's scan period. A value that holds is taken again every scan period
        here, as a scan would read it, so compression and the longest interval work alike.
        Addresses the server refuses to monitor are read on a scan instead."""

        by_address: dict[str, list[PointState]] = defaultdict(list)
        period_of: dict[str, float] = {}
        for period, states in groups.items():
            for state in states:
                address = state.point["address"]
                by_address[address].append(state)
                period_of[address] = min(period, period_of.get(address, period))
        latest: dict[str, Reading] = {}

        def take(address: str, reading: Reading) -> None:
            latest[address] = reading
            with self._lock:
                for state in by_address.get(address, []):
                    if state.last is None or reading.at_ms > state.last[0] or not reading.good:
                        state.take(reading)

        wanted: dict[float, list[str]] = defaultdict(list)
        for address, period in period_of.items():
            wanted[period].append(address)
        try:
            refused = await asyncio.wait_for(
                reader.subscribe(dict(wanted), take), max(self.settings.opcua_timeout * 10, 60)
            )
        except (asyncio.CancelledError, ConnectionError, TimeoutError):
            raise
        except Exception as exc:  # noqa: BLE001 - a server without subscriptions is scanned
            LOGGER.warning("Source %s: no subscription (%s), scanned", source_id, _describe(exc))
            refused = {address: None for address in period_of}
        scanned: dict[float, list[PointState]] = defaultdict(list)
        for period, states in groups.items():
            for state in states:
                if state.point["address"] in refused:
                    scanned[period].append(state)
        monitored = {a: p for a, p in period_of.items() if a not in refused}
        self.source_status[source_id] = {
            **(self.source_status.get(source_id) or {}),
            "reading": "subscription",
            "monitored": len(monitored),
            "scanned": len(refused),
        }
        await asyncio.gather(
            self._take_held_values(reader, monitored, latest, take),
            *(self._scan(reader, period, states) for period, states in scanned.items()),
        )

    async def _take_held_values(
        self,
        reader: Any,
        periods: dict[str, float],
        latest: dict[str, Reading],
        take: Any,
    ) -> None:
        """Take again each monitored value that held for its scan period; check the server
        answers every few seconds (a quiet subscription is not a dead one)."""

        tick = max(min(periods.values(), default=1.0), 0.1)
        checked = time.monotonic()
        while True:
            await asyncio.sleep(tick)
            now = now_ms()
            for address, period in periods.items():
                reading = latest.get(address)
                if reading is not None and reading.good and now - reading.at_ms >= period * 1000:
                    take(address, dataclasses.replace(reading, at_ms=now))
            if time.monotonic() - checked >= SUBSCRIPTION_CHECK_SECONDS:
                await asyncio.wait_for(reader.alive(), self.settings.opcua_timeout + 5)
                checked = time.monotonic()

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
