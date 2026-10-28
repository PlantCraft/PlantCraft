"""Everything one DashCraft server holds: settings, the dashboard store and PlantCraft clients.

Who reads plant data:

- **Saved dashboards and public links** read with DashCraft's service token
  (``PLANTCRAFT_APP_KEY``), like a published report: whoever may open the
  dashboard sees what its editors put on it, and one read per card serves every
  viewer for ``DASHCRAFT_CACHE_SECONDS``. Without an app key, signed-in people
  still see dashboards, read with their own token (no public links then).
- **Editors building cards** (asset and signal pickers, card previews) read with
  their own token, so PlantCraft's permissions decide what they can pick.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx
from plantcraft_sdk.asset_scope import limited
from plantcraft_sdk.auth import TokenVerifier, User
from plantcraft_sdk.client import PlantCraftClient
from plantcraft_sdk.server.lease import FileLease
from plantcraft_sdk.server.platform import PlatformRuntime
from plantcraft_sdk.server.store import Database

from dashcraft import APP_ID
from dashcraft.config import Settings
from dashcraft.dashboards import suite_health
from dashcraft.dashboards.folders import FolderStore
from dashcraft.dashboards.store import DashboardStore
from dashcraft.dashboards.trends import TrendStore
from dashcraft.delivery.service import ReportScheduler, ReportService
from dashcraft.diagrams.store import DiagramStore
from dashcraft.query.cache import TtlCache
from dashcraft.query.cards import Reader
from dashcraft.query.signal_ids import migrate_signal_ids
from dashcraft.reports.store import ReportStore
from dashcraft.suite import Suite

LOGGER = logging.getLogger(__name__)
# Asset and signal metadata change rarely; values change every few seconds.
META_SECONDS = 60.0
# How often View looks whether the Historian's "System" signals changed (dashboard Suite health).
SUITE_HEALTH_SECONDS = 600.0


class Runtime(PlatformRuntime):
    def __init__(
        self,
        settings: Settings,
        *,
        verifier: TokenVerifier | None = None,
        service_client: PlantCraftClient | None = None,
        http_client: httpx.Client | None = None,
        clock: Any = None,
    ):
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = Database(settings.database_path)
        self.dashboards = DashboardStore(self.db)
        self.folders = FolderStore(self.db)
        self.trends = TrendStore(self.db)
        self.reports = ReportStore(self.db)
        self.diagrams = DiagramStore(self.db)
        self.connect(
            APP_ID,
            settings,
            verifier=verifier,
            service_client=service_client,
            http_client=http_client,
        )
        self.data_cache = TtlCache(settings.cache_seconds)
        self.meta_cache = TtlCache(max(META_SECONDS, settings.cache_seconds))
        self._clock = clock
        self._suite_health_at = 0.0
        self._suite_health_lock = threading.Lock()
        # Reports: what View sends the suite about them, their rules and the thread that sends
        # them on time (one process at a time: the lease in the data folder).
        self.suite = Suite(lambda: self.service_client)
        self.report_service = ReportService(
            self.reports, self.suite, root=settings.root_path, clock=clock
        )
        self.report_scheduler = ReportScheduler(
            self.report_service,
            self.report_reader,
            FileLease(settings.data_dir / "reports.lease"),
            every=settings.report_seconds or 30.0,
        )

    def _reader(self, client: Any, *, cached: bool) -> Reader:
        options: dict[str, Any] = {}
        if self._clock is not None:
            options["clock"] = self._clock
        if cached:
            options.update(data_cache=self.data_cache, meta_cache=self.meta_cache)
        return Reader(client, **options)

    # PlantCraft --------------------------------------------------------------

    def user_reader(self, user: User) -> Reader:
        """Reads as the person (pickers, previews): never cached across people."""

        return self._reader(self.user_client(user), cached=False)

    def dashboard_reader(self, user: User | None) -> tuple[Reader, bool]:
        """The reader for saved dashboards, and whether it is the app's own (service) reader."""

        if user is not None and limited(user):
            # A person who sees only part of the plant reads as themselves: PlantCraft answers
            # them only about that part (docs/asset-scope.md).
            return self.user_reader(user), False
        if self.service_client is not None:
            return self._reader(self.service_client, cached=True), True
        if user is None:
            raise LookupError("no service key")
        return self.user_reader(user), False

    def report_reader(self) -> Reader | None:
        """What scheduled reports read with: View's service token, never cached (None without
        an app key)."""

        if self.service_client is None:
            return None
        return self._reader(self.service_client, cached=False)

    def start_reports(self) -> None:
        """The scheduler of reports (off when ``DASHCRAFT_REPORT_SECONDS`` is 0)."""

        if self.settings.report_seconds > 0:
            self.report_scheduler.start()

    def groups_of(self, user: User) -> set[str]:
        """The ids of the platform's groups ``user`` belongs to (``GET /api/v1/groups``, read
        once a minute). Unreadable: none, so a folder kept for some groups stays closed."""

        service = self.service_client is not None
        client = self.service_client if service else self.user_client(user)
        key = ("groups",) if service else ("groups", user.username)
        try:
            groups = self.meta_cache.get(key, client.groups)
        except Exception:  # noqa: BLE001 - a folder's access never breaks the page
            LOGGER.warning("Groups not read from PlantCraft", exc_info=True)
            return set()
        return {
            str(group.get("id"))
            for group in groups or []
            if user.username in (group.get("members") or [])
        }

    def migrate_signal_ids(self) -> dict[str, Any]:
        """Move saved cards from bare tags to API v1 signal ids (needs the app key)."""

        if self.service_client is None:
            return {"renamed": {}, "dashboards": 0, "error": "no service key"}
        return migrate_signal_ids(self.dashboards, self.service_client)

    def ensure_suite_health(self, *, force: bool = False) -> dict[str, Any] | None:
        """The dashboard "Suite health", created or redrawn from the Historian's source
        ``system`` at most every 10 minutes (``dashboards.suite_health``); needs the app key."""

        if self.service_client is None:
            return None
        with self._suite_health_lock:
            if not force and time.monotonic() - self._suite_health_at < SUITE_HEALTH_SECONDS:
                return None
            self._suite_health_at = time.monotonic()
            try:
                return suite_health.ensure(self.dashboards, self.service_client, self.folders)
            except Exception:  # noqa: BLE001 - never stops the dashboards list
                LOGGER.exception("Suite health dashboard not updated")
                return None

    def shutdown(self) -> None:
        self.report_scheduler.stop()
        self.close_platform()

    def status(self) -> dict[str, Any]:
        return {
            "service_key": self.has_service_key,
            "public_links": self.settings.public_links and self.has_service_key,
            "dashboards": len(self.dashboards.list()),
            "reports": self.reports.count(),
            "diagrams": self.diagrams.count(),
            "cache": {"hits": self.data_cache.hits, "misses": self.data_cache.misses},
        }
