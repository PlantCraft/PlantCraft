"""Everything one PlantCraft Alarms server holds: settings, the alarm store, the PlantCraft
clients and the monitor.

Who reads plant data:

- **The monitor and the alarm summary** read with Alarms' service token
  (``PLANTCRAFT_APP_KEY``): an alarm is a published judgement, whoever may open Alarms sees
  what its editors set up. Without an app key the monitor does not run.
- **Editors building an alarm** (asset and signal pickers, "Try it") read with their own
  token, so PlantCraft's permissions decide what they can pick.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from plantcraft_sdk.asset_scope import limited
from plantcraft_sdk.auth import TokenVerifier, User
from plantcraft_sdk.client import PlantCraftClient, PlantCraftError
from plantcraft_sdk.server.platform import PlatformRuntime
from plantcraft_sdk.server.store import Database
from plantcraft_sdk.utc import use_installation_zone

from alarmcraft import APP_ID
from alarmcraft.alarms.incoming import IncomingStore
from alarmcraft.alarms.notices import NoticeStore
from alarmcraft.alarms.philosophy import PhilosophyStore
from alarmcraft.alarms.rules import RuleStore
from alarmcraft.alarms.store import AlarmStore
from alarmcraft.config import Settings
from alarmcraft.i18n import t
from alarmcraft.monitor.history import HistoryReplay
from alarmcraft.monitor.notifier import Notifier
from alarmcraft.monitor.reader import ApiReader, AssetTree, Directory, Executions
from alarmcraft.monitor.service import Monitor, utcnow
from alarmcraft.monitor.suggest import catalog_of
from alarmcraft.monitor.sync import RuleSync

LOGGER = logging.getLogger(__name__)


# How long the platform's answer on email is kept (seconds).
EMAIL_EVERY = 60


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
        self.alarms = AlarmStore(self.db)
        self.notices = NoticeStore(self.db)
        self.rules = RuleStore(self.db)
        self.incoming = IncomingStore(self.db)
        self.philosophy = PhilosophyStore(self.db)
        self.connect(
            APP_ID,
            settings,
            verifier=verifier,
            service_client=service_client,
            http_client=http_client,
        )
        service_client = self.service_client
        # "Local time" in a rule or the philosophy is the installation's zone, as PlantCraft says it.
        reader = getattr(service_client, "installation_time_zone", None)
        if callable(reader):
            use_installation_zone(reader)
        self.clock = clock or utcnow
        self.asset_cache: dict = {}
        # The asset tree (areas) and the platform's people and groups, read with the app's key.
        self.tree = AssetTree(service_client)
        self.directory = Directory(service_client)
        self.executions = Executions(service_client)
        self.sync = RuleSync(
            self.rules, self.alarms, self.tree, self.clock, schedules=self.executions.list
        )
        self.notifier = Notifier(
            self.alarms,
            self.notices,
            service_client,
            self.tree,
            root_path=settings.root_path,
            directory=self.directory,
            rules=self.rules,
            philosophy=self.philosophy,
            conditions=self.incoming.open_conditions,
        )
        self.monitor = Monitor(
            self.alarms,
            service_client,
            root_path=settings.root_path,
            clock=self.clock,
            cycle_seconds=settings.cycle_seconds,
            data_lag_seconds=settings.data_lag_seconds,
            asset_cache=self.asset_cache,
            notifier=self.notifier,
            rules=self.rules,
            incoming=self.incoming,
            sync=self.sync,
        )
        self.replay = HistoryReplay(self.monitor)
        self._email: tuple[bool, Any] | None = None

    # PlantCraft (connection, user_client and audit: PlatformRuntime) ----------

    def reader(self, user: User | None) -> tuple[ApiReader, bool]:
        """The reader for alarm pages: the app's own when it has a key, else the person's. Who
        sees only part of the plant reads as themselves (PlantCraft answers them about it)."""

        if user is not None and limited(user):
            return ApiReader(self.user_client(user)), False
        if self.service_client is not None:
            return ApiReader(self.service_client, cache=self.asset_cache), True
        if user is None:
            raise LookupError("no service key")
        return ApiReader(self.user_client(user)), False

    def user_reader(self, user: User) -> ApiReader:
        return ApiReader(self.user_client(user))

    def event_catalog(self) -> tuple[list[dict[str, Any]], str]:
        """Every event the apps declare (PlantCraft's catalog), and why it is empty when it is."""

        if self.service_client is None:
            return [], t("Alarms has no app key yet: it cannot read the suite's catalog.")
        try:
            return catalog_of(self.service_client), ""
        except (PlantCraftError, ValueError) as exc:
            return [], t("The catalog could not be read: {why}", why=exc)[:300]

    def email_ready(self) -> bool:
        """Whether PlantCraft can send email now (its Setup, Email), read at most once a minute:
        a rule's email output shows only then."""

        now = self.clock()
        if self._email is not None and (now - self._email[1]).total_seconds() < EMAIL_EVERY:
            return self._email[0]
        ready = False
        if self.service_client is not None:
            try:
                ready = bool(self.service_client.notification_settings().get("email"))
            except (PlantCraftError, ValueError, AttributeError):
                ready = False
        self._email = (ready, now)
        return ready

    def start(self) -> None:
        if self.settings.monitor:
            self.monitor.start()

    def shutdown(self) -> None:
        self.monitor.stop()
        self.close_platform()

    def status(self) -> dict[str, Any]:
        alarms = self.alarms.list()
        return {
            "service_key": self.has_service_key,
            "monitor": {
                "enabled": self.settings.monitor,
                "running": self.monitor.running,
                "cycles": self.monitor.cycles,
                "cycle_seconds": self.settings.cycle_seconds,
                "last_cycle": self.monitor.last_cycle.isoformat()
                if self.monitor.last_cycle
                else None,
                "last_error": self.monitor.last_error,
                "publish_error": self.monitor.publish_error,
                "notify_error": self.notifier.last_error,
                "events_error": self.monitor.incoming.last_error if self.monitor.incoming else "",
                "events_read": self.monitor.incoming.read_count if self.monitor.incoming else 0,
            },
            "rules": len(self.rules.list()),
            "alarms": len(alarms),
            "enabled": sum(1 for alarm in alarms if alarm.get("enabled", True)),
        }
