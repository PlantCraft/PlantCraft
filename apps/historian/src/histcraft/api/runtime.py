"""Everything one HistCraft server holds: settings, stores, the reader and the token verifier.

With ``HISTCRAFT_COLLECTOR=embedded`` (the default outside Docker) the server
also runs the collector in a background thread; in the suite's compose file a
separate ``histcraft collect`` container does (docs/boundary.md).
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any

import httpx
import numpy as np
from plantcraft_sdk.auth import TokenVerifier
from plantcraft_sdk.server import ops
from plantcraft_sdk.server.platform import PlatformRuntime
from plantcraft_sdk.server.queue import QueueMetrics, QueueNow, QueueSampler
from plantcraft_sdk.server.store import Database as QueueDatabase

from histcraft import APP_ID
from histcraft.api import queue
from histcraft.api.read_budget import ReadBudget
from histcraft.archive.query import PointRef, Reader, SourceUnavailable
from histcraft.archive.store import ArchiveStore
from histcraft.catalog.store import CatalogStore
from histcraft.collector.service import Collector, CollectorThread, source_password
from histcraft.conditions import open_conditions
from histcraft.config import Settings
from histcraft.db import Database
from histcraft.export.saved import SavedExports
from histcraft.i18n import t
from histcraft.sources.cache import RecentReads
from histcraft.vault import Vault

LOGGER = logging.getLogger(__name__)
# Sources whose recent reads are kept in memory (``sources.cache``).
CACHED_KINDS = ("pi_web_api", "opcua")


def point_ref(point: dict[str, Any]) -> PointRef:
    return PointRef(
        int(point["id"]),
        point["signal"],
        point["kind"],
        bool(point["step"]),
        point.get("mode") or "archive",
    )


class Runtime(PlatformRuntime):
    # Changes made with a service token (the apps' derived series) are not a person's.
    audit_service_users = False

    def __init__(
        self,
        settings: Settings,
        *,
        verifier: TokenVerifier | None = None,
        http_client: httpx.Client | None = None,
        collector: Collector | None = None,
    ):
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        password = settings.database_password()
        self.catalog = CatalogStore(Database(settings.config_target, password=password))
        # Sources of apps dropped from the suite go (the collector deletes their archive).
        self.catalog.drop_retired()
        self.archive = ArchiveStore(Database(settings.archive_target, password=password))
        # Export choices kept under a name, beside the catalog (``export.saved``).
        self.saved_exports = SavedExports(self.catalog.db)
        self.vault = Vault(settings.secret_key_path)
        self.reader = Reader(self.archive, self.source_read)
        self.read_budget = ReadBudget(settings.read_values, settings.query_timeout)
        self._sources: dict[str, tuple[tuple, Any]] = {}
        self._sources_lock = threading.Lock()
        self.recent = RecentReads(settings.source_cache_seconds)
        self.connect(APP_ID, settings, verifier=verifier, http_client=http_client, service=False)
        self.collector = collector
        if self.collector is None and settings.collector == "embedded":
            self.collector = Collector(settings, self.catalog, self.archive)
        self._thread: CollectorThread | None = None
        # The imports' numbers for the suite's work queue (api/queue.py), sampled every 15 s and
        # kept 30 days in their own small SQLite file, also with PostgreSQL (it only draws the
        # queue's history).
        self.queue_metrics = QueueMetrics(QueueDatabase(settings.data_dir / "queue.sqlite3"))
        self.queue_sampler = QueueSampler(self.queue_metrics, self.queue_now)

    def queue_now(self, since: datetime | None = None) -> QueueNow:
        return queue.queue_now(self.catalog, self.archive, self.settings.data_dir, since)

    # Reading plant sources (mode source and both) ---------------------------------------

    def source_history(self, source_id: str) -> Any:
        """The open history reader of a plant source, rebuilt when the source changes."""

        from histcraft.sources.history import open_source

        source = self.catalog.source(source_id)
        signature = (source["updated"], source["enabled"])
        with self._sources_lock:
            cached = self._sources.get(source_id)
            if cached is not None and cached[0] == signature:
                return cached[1]
        if not source["enabled"]:
            raise SourceUnavailable(t("Source {id} is disabled.", id=source_id))
        reader = open_source(source, source_password(source, self.catalog, self.vault))
        with self._sources_lock:
            self._sources[source_id] = (signature, reader)
        return reader

    def recorded(
        self, points: list[dict[str, Any]], start_ms: int, end_ms: int
    ) -> dict[int, tuple[np.ndarray, Any] | str]:
        """Recorded values of points from their sources, one call per source; errors as text."""

        out: dict[int, tuple[np.ndarray, Any] | str] = {}
        by_source: dict[str, list[dict[str, Any]]] = {}
        for point in points:
            by_source.setdefault(point["source_id"], []).append(point)
        for source_id, members in by_source.items():
            try:
                history = self.source_history(source_id)
                source = self.catalog.source(source_id)
                addresses = sorted({p["address"] for p in members})
                # A CSV file is already held in memory by its reader (read again when it
                # changes); remote historians answer from the recent reads (gap G20).
                if source["kind"] in CACHED_KINDS:
                    answers = self.recent.recorded(
                        (source_id, source["updated"]),
                        addresses,
                        start_ms,
                        end_ms,
                        history.recorded,
                    )
                else:
                    answers = history.recorded(addresses, start_ms, end_ms)
            except Exception as exc:  # noqa: BLE001 - the plant system's own words
                LOGGER.warning("Source %s did not answer: %s", source_id, exc)
                for point in members:
                    out[int(point["id"])] = str(exc) or type(exc).__name__
                continue
            for point in members:
                answer = answers.get(point["address"])
                out[int(point["id"])] = (
                    answer if answer is not None else t("The source sent no values.")
                )
        return out

    def source_read(self, ref: PointRef, start_ms: int, end_ms: int) -> tuple[np.ndarray, Any]:
        """``Reader``'s hook: one point's recorded values from its source."""

        point = self.catalog.find(ref.tag)
        if point is None:
            raise SourceUnavailable(t("Signal {id} not found.", id=ref.tag))
        answer = self.recorded([point], start_ms, end_ms)[int(point["id"])]
        if isinstance(answer, str):
            raise SourceUnavailable(answer)
        return answer

    def start(self) -> None:
        # What is open now (a stalled collector, a source down), for PlantCraft's monitor.
        ops.report_conditions(lambda: open_conditions(self.catalog, self.archive))
        self.queue_sampler.start()
        if self.collector is not None and self._thread is None:
            self._thread = CollectorThread(self.collector)
            self._thread.start()

    def shutdown(self) -> None:
        ops.report_conditions(None)
        self.queue_sampler.stop()
        if self._thread is not None:
            self._thread.stop()
            self._thread = None
        self.close_platform()
