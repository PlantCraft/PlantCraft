"""Objects shared by every request: the scenario, sign-in settings, token keys and the kernel."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from plantcraft.api.help import document_index, read_document
from plantcraft.apps.contributions import ContributionStore
from plantcraft.apps.install_settings import AppSettingStore
from plantcraft.apps.manager import AppManager, AppSettings
from plantcraft.apps.operations_desk import OperationsDesk
from plantcraft.apps.scopes import AppScopes
from plantcraft.apps.store import InstalledAppStore
from plantcraft.assistant_access.app_tools import AppTools
from plantcraft.assistant_chat import ChatStore
from plantcraft.assistant_chat.engine import ChatEngine
from plantcraft.assistant_chat.evals import EvalStore
from plantcraft.assistant_works import WorkRegistry
from plantcraft.auth.config import AuthConfig
from plantcraft.auth.suite import FORMER_IDS, SuiteApp, suite_apps
from plantcraft.auth.tokens import KeyRing
from plantcraft.certificates import suite_https
from plantcraft.compute import ComputeStore, compute_max_bytes
from plantcraft.config import DashboardScenario, env_flag, load_scenario
from plantcraft.desk import DeskStore
from plantcraft.desk import register_refs as register_desk_refs
from plantcraft.desk.app_items import AppItemStore
from plantcraft.directory import CorporateLogin
from plantcraft.directory.settings import DirectorySecrets
from plantcraft.events.conditions import ConditionRelay
from plantcraft.i18n import t
from plantcraft.notify import NotificationCenter, SecretFile
from plantcraft.ops.workers import Leader, startup
from plantcraft.platform import Platform, Workspace
from plantcraft.platform.asset_scope import EVERYTHING, AssetScope, build_scope, scope_roots
from plantcraft.specialists import KeyFile, SpecialistChat, SpecialistStore
from plantcraft.watch import SuiteWatch
from plantcraft.watch.recorder import HealthRecorder, ServerMetrics

LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCENARIO = PROJECT_ROOT / "scenarios" / "generic_demo.json"
# History people and apps usually open first; filled in the background at start.
PREWARM_HOURS = 48
# How often the leader gives back the tasks of workers that stopped answering.
COMPUTE_TICK_SECONDS = 5.0


def _asset_types(value: Any) -> tuple[str, ...] | None:
    """An installed app's ``asset_types`` as stored with its manifest; None when not recorded."""

    if not isinstance(value, list):
        return None
    return tuple(item for item in value if isinstance(item, str))


# The order data flows through the suite, as @plantcraft/ui SUITE_ORDER:
# collect, analyse, model, run, and View last. Apps it does not know follow, as listed.
SUITE_ORDER = (
    "processcraft",
    "histcraft",
    "linkcraft",
    "modelcraft",
    "alarmcraft",
    "doccraft",
    "simcraft",
    "dashcraft",
)


def _suite_rank(app: SuiteApp) -> int:
    family = next(
        (name for name, former in FORMER_IDS.items() if app.id in former and name in SUITE_ORDER),
        app.id,
    )
    return SUITE_ORDER.index(family) if family in SUITE_ORDER else len(SUITE_ORDER)


class ApiRuntime:
    """The PlantCraft kernel for one installation, plus what the HTTP layer needs."""

    def __init__(self, scenario: DashboardScenario, auth: AuthConfig):
        self.scenario = scenario
        self.auth = auth
        # Signs the API v1 tokens apps verify (key kept beside the database).
        self.tokens = KeyRing.for_database(scenario.storage.sqlite_path)
        self.platform = Platform.open(scenario, issuer=self.tokens)
        self.sync_assets()
        # Apps installed from the Apps page (docs/app-package.md); Docker stays with the installer.
        self.apps = AppManager(
            InstalledAppStore(self.workspace.db),
            AppSettings.from_environment(scenario.storage.sqlite_path),
        )
        # Backups, restores and updates: requests to the installer (docs/operations.md).
        self.operations = OperationsDesk(self.apps.settings)
        # Specialists (docs/collaboration.md): model keys live beside the database, not in it.
        keys = os.environ.get("PLANTCRAFT_SPECIALIST_KEYS_FILE", "").strip() or Path(
            scenario.storage.sqlite_path
        ).with_name("specialist-keys.json")
        # Each person's day: to-dos, own events, followed assets, calendars (docs/desk.md).
        self.desk = DeskStore(self.workspace.db)
        register_desk_refs(self.platform.refs, self.desk)
        # What the apps put in Desk: calendar feeds and to-dos (plantcraft.desk.app_items).
        self.app_items = AppItemStore(self.workspace.db)
        self.specialists = SpecialistStore(self.workspace.db, self.workspace.users, KeyFile(keys))
        self.specialist_chat = SpecialistChat(
            self.workspace,
            self.specialists,
            self.workspace.messages,
            self.app_names,
            scope=self.readers_scope,
        )
        # The assistant's chats in Desk: each person's chats with a model (docs/assistant.md).
        self.assistant = ChatEngine(
            ChatStore(self.workspace.db),
            self.specialist_chat,
            self.workspace.audit,
            self.workspace.users,
            EvalStore(self.workspace.db),
            # The suite's Help, for the model's read_help tool.
            help_docs=(document_index, read_document),
        )
        # app:<id>: a whole app, for the assistant an app opens on its own page ("which loops
        # are worst?"): the specialists who read that app answer from all it published.
        self.platform.refs.register("app", self._app_ref, owner="platform")
        # chat:<id>: one of the assistant's chats, in an action or a message.
        # Like a note, the link says only its kind and number; opening it shows the chat to its
        # owner and to the people it is shared with.
        self.platform.refs.register("chat", self._chat_ref, owner="platform")
        # conversation:<id>: a conversation of Messages, in an action or a note (2026-10-27). Like
        # a chat, the link says only its kind and number; Messages opens it to its members.
        self.platform.refs.register("conversation", self._conversation_ref, owner="platform")
        # An action's title and state are for the people who see it (its owner, its group and
        # those above, admins): anyone else reads "Action 42" (security review, 2026-10-26).
        self.platform.refs.guard("action", self.action_reader)
        self.platform.refs.app_guard = self.app_reader
        # The part of the plant a person sees (docs/asset-scope.md): assets and signals out of
        # it read as their kind and id, like an action of another group.
        self.platform.refs.guard("asset", lambda viewer: self.asset_scope(viewer).asset)
        self.platform.refs.guard("signal", lambda viewer: self.asset_scope(viewer).signal)
        # A signal (a source of the assistant's answers) opens in the app that draws trends.
        self.platform.refs.register("signal", self._signal_ref, owner="platform")
        # What each app adds to PlantCraft, from its app.toml (docs/app-standard.md, 4b).
        self.contributions = ContributionStore(self.workspace.db)
        # The assistant's works on every page: PlantCraft's and the installed apps' (assistant_works).
        self.assistant.works = WorkRegistry(
            self.contributions.listing, lambda: {app.id: app.url for app in self.suite_apps()}
        )
        # The read-only tools the installed apps add to the assistant (docs/assistant.md).
        self.app_tools = AppTools(
            self.contributions.listing, lambda: [app.id for app in self.suite_apps()]
        )
        self.assistant.app_tools = self.app_tools
        # What each app's own token may do in API v1: its [permissions] (plantcraft.apps.scopes).
        # A suite app's are pinned by the installed bundle's signed release.json.
        self.app_scopes = AppScopes(
            self.apps.store,
            self.contributions,
            lambda: ((self.operations.read("release.json") or {}).get("release") or {}).get(
                "permissions"
            ),
        )
        # What the administrator chose for the apps' [[contributes.settings]] (Setup › Apps).
        self.app_settings = AppSettingStore(self.workspace.db)
        # #<kind>:<id> of the kinds the apps declare ([[contributes.refs]]) link to their pages.
        self.platform.refs.declared = self._declared_ref
        # The compute workers and their queue of tasks (docs/compute.md); the bytes beside the
        # database. The installation's own worker enrolls with the credential install.sh wrote.
        self.compute = ComputeStore(
            self.workspace.db,
            Path(scenario.storage.sqlite_path).parent / "compute",
            max_bytes=compute_max_bytes(),
        )
        self._local_worker()
        # The suite's watch: "System" tells the admins when a part of the suite stops.
        self.watch = SuiteWatch(
            self.workspace.db,
            self.workspace.users,
            self.workspace.messages,
            self.operations,
            self.admins,
            # The queues the servers reported to the recorder's last sample (below).
            queues=lambda: self.health_signals.queues,
            events=self.workspace.events,
            # The suite's HTTPS and the Historian's OPC UA certificates (Health › Certificates).
            certificates=lambda: [suite_https(), *self.datalayer.certificates()],
            # Tasks that wait with no compute worker able to run them (Settings › Compute).
            compute=self.compute.waiting_without_worker,
        )
        # The suite's health as signals of the Historian's source "System", every minute.
        self.health_signals = HealthRecorder(
            self.operations,
            lambda series: self.datalayer.put_system(series),
            ServerMetrics(self.tokens, self._own_metrics, running=self._running_services),
            # The conditions an app without an app key reports (the Historian), as its events.
            conditions=ConditionRelay(
                self.workspace.db, self.workspace.events, self.contributions
            ).apply,
        )
        # Notifications the apps send (docs/notifications.md); the SMTP password beside the database.
        secret = os.environ.get("PLANTCRAFT_MAIL_SECRET_FILE", "").strip() or Path(
            scenario.storage.sqlite_path
        ).with_name("mail-secret.json")
        self.notifications = NotificationCenter(
            self.workspace.db,
            self.workspace.users,
            self.workspace.groups,
            self.workspace.messages,
            self.workspace.preferences,
            SecretFile(secret),
        )
        # Corporate sign-in (docs/corporate-login.md): LDAP or AD, and OIDC; off by default.
        secrets_file = os.environ.get("PLANTCRAFT_DIRECTORY_SECRETS_FILE", "").strip() or Path(
            scenario.storage.sqlite_path
        ).with_name("directory-secrets.json")
        self.directory = CorporateLogin(
            self.workspace.db,
            self.workspace.users,
            self.workspace.groups,
            DirectorySecrets(secrets_file),
            Path(scenario.storage.sqlite_path).parent,
            audit=self.workspace.audit,
        )
        self._stopping = threading.Event()
        # Which server process runs the watch and the outbox (``ops.workers``).
        self.leader = Leader(Path(scenario.storage.sqlite_path).parent)
        self._prewarm: threading.Thread | None = None
        self._watching: threading.Thread | None = None

    def _local_worker(self) -> None:
        path = os.environ.get("PLANTCRAFT_COMPUTE_LOCAL_KEY_FILE", "").strip()
        if not path:
            return
        try:
            credential = Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            LOGGER.warning("The local compute worker's key file %s cannot be read.", path)
            return
        if credential:
            self.compute.ensure_local(credential)

    def _compute_upkeep(self, stop: threading.Event) -> None:
        """Tasks of workers that stopped answering go back to the queue; old bytes go."""

        ticks = 0
        while not stop.wait(COMPUTE_TICK_SECONDS):
            try:
                self.compute.expire()
                if ticks % 60 == 0:
                    self.compute.housekeeping()
            except Exception:  # the next tick tries again
                LOGGER.exception("compute upkeep failed")
            ticks += 1

    @classmethod
    def from_environment(cls) -> ApiRuntime:
        scenario_path = Path(os.environ.get("PLANTCRAFT_SCENARIO", str(DEFAULT_SCENARIO)))
        scenario = load_scenario(
            scenario_path,
            project_root=PROJECT_ROOT,
            data_override=os.environ.get("PLANTCRAFT_DATA_FILE") or None,
        )
        # Server processes start together: one at a time fills in what a first start writes.
        with startup(Path(scenario.storage.sqlite_path).parent):
            return cls(scenario, AuthConfig.from_environment())

    def sync_assets(self) -> None:
        """The scenario's loops in the asset tree (again after a map import or a source change)."""

        self.platform.sync_assets()

    def suite_apps(self) -> list[SuiteApp]:
        """The apps of the suite (``PLANTCRAFT_APPS`` and the ones installed here) in the
        suite's order, the one the menu draws (@plantcraft/ui ``SUITE_ORDER``)."""

        self.sync_apps()
        configured = suite_apps()
        ids = {app.id for app in configured}
        installed = [
            SuiteApp(
                row["app_id"],
                row["name"],
                row["url"],
                row.get("version"),
                _asset_types((row.get("manifest") or {}).get("asset_types")),
            )
            for row in self.apps.launchable()
            if row["app_id"] not in ids
        ]
        return sorted(configured + installed, key=_suite_rank)

    def _app_ref(self, app_id: str) -> dict[str, Any] | None:
        app = next((item for item in self.suite_apps() if item.id == app_id), None)
        if app is None:
            return None
        return {"title": app.name, "href": app.url, "status": None, "app": app.id}

    def readers_scope(
        self, people: list[str]
    ) -> tuple[set[str], Callable[[dict[str, Any]], bool], Callable[[str], bool]]:
        """What ``people`` may all read: the apps they all open (with the platform's own),
        whether they all see an action, and whether a subject is in all their asset scopes. A
        specialist's answer in a conversation reads no more."""

        from plantcraft.api.deps import action_visibility
        from plantcraft.api.identity import visible_apps

        apps: set[str] | None = None
        seen = []
        assets = EVERYTHING
        for username in people:
            mine = visible_apps(self, username)
            apps = mine if apps is None else apps & mine
            seen.append(action_visibility(self, username))
            assets = assets & self.asset_scope(username)
        return (
            apps or set(),
            lambda action: bool(seen) and all(item.sees(action) for item in seen),
            assets.subject if people else (lambda _subject: False),
        )

    def asset_scope(self, username: str | None) -> AssetScope:
        """The assets ``username`` sees (docs/asset-scope.md); the whole plant for an
        administrator, an app's own token (``app:<id>``) and nobody in particular (``None``)."""

        from plantcraft.api.deps import user_access

        if not username or username.startswith("app:"):
            return EVERYTHING
        access = user_access(self, username)
        if access is None:
            # Not a person who may sign in: nothing of the plant.
            return build_scope(self.workspace, ())
        if access.is_admin:
            return EVERYTHING
        roots = scope_roots(self.workspace, username)
        return build_scope(self.workspace, roots, derived_subject=self._derived_subject)

    def _derived_subject(self, signal_id: str) -> str | None:
        try:
            return str(self.datalayer.signal(signal_id).get("subject") or "") or None
        except Exception:  # an unknown signal, or the data layer down: no subject known
            return None

    def action_reader(self, username: str) -> Callable[[str], bool]:
        """Whether ``username`` sees an action, by its id (``docs/collaboration.md``, "Who sees
        an action"); their groups are read once."""

        from plantcraft.api.deps import action_visibility

        seen = action_visibility(self, username)
        if seen.everything:
            return lambda _action_id: True
        ids = self.workspace.actions.visible_ids(seen)
        return lambda action_id: action_id.isdigit() and int(action_id) in ids

    def app_reader(self, username: str) -> Callable[[str], bool]:
        """Whether ``username`` may open an app, by its id (their access read once)."""

        apps = self.apps_for(username)
        return lambda app_id: apps is None or app_id in apps

    def apps_for(self, username: str) -> set[str] | None:
        """The apps whose results, events, runs and schedules ``username`` reads (those they
        may open, with the platform's own); ``None`` for an administrator, who reads all.
        One rule for every way a person reads them: API v1, the asset's page, Desk, the
        assistant."""

        from plantcraft.api.deps import user_access
        from plantcraft.api.identity import visible_apps

        access = user_access(self, username)
        if access is not None and access.is_admin:
            return None
        return visible_apps(self, username)

    def events_for(self, username: str, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """``events`` without those ``username`` may not read: of an app they do not open, or
        about an item they do not see (an action of another group: its events carry its
        title)."""

        sees = self.platform.refs.reader(username)
        hidden = self.hidden_sources(username)
        return [
            event
            for event in events
            if event.get("source") not in hidden and sees(str(event.get("subject") or ""))
        ]

    def hidden_sources(self, username: str) -> set[str]:
        """The apps of the suite (and their former ids) whose events ``username`` does not read;
        the platform's own events (assets, actions, people) are not an app's."""

        from plantcraft.api.identity import FORMER_IDS

        apps = self.apps_for(username)
        if apps is None:
            return set()
        known = {app.id for app in self.suite_apps()}
        for app_id in list(known):
            known |= set(FORMER_IDS.get(app_id, ()))
        return known - apps

    def _chat_ref(self, item_id: str) -> dict[str, Any] | None:
        if not item_id.isdigit() or not self.assistant.store.exists(int(item_id)):
            return None
        return {
            "title": t("Assistant chat #{id}", id=item_id),
            "href": f"/assistant/{item_id}",
            "status": None,
        }

    def _conversation_ref(self, item_id: str) -> dict[str, Any] | None:
        if not item_id.isdigit() or self.workspace.messages.get(int(item_id)) is None:
            return None
        return {
            "title": t("Conversation #{id}", id=item_id),
            "href": f"/messages/{item_id}",
            "status": None,
        }

    def _signal_ref(self, signal_id: str) -> dict[str, Any] | None:
        """A signal opens a new trend of it in the app that declares the ``trend`` kind (View's
        /dash/trends?signal=), when one is installed."""

        if not signal_id:
            return None
        found = self._declared_ref("trend")
        page = str(found["url"]).replace("/{id}", "") if found else ""
        return {
            "title": signal_id,
            "href": f"{page}?{urlencode({'signal': signal_id})}" if page else None,
            "status": None,
        }

    def _declared_ref(self, kind: str) -> dict[str, Any] | None:
        """The installed app that declares ``kind`` in ``[[contributes.refs]]`` (the first in the
        suite's order), with the kind's title and page; a page outside the app's prefix is
        ignored."""

        prefixes = {app.id: app.url for app in self.suite_apps()}
        for row in self.contributions.listing(list(prefixes)):
            prefix = prefixes.get(row["app"]) or ""
            for item in (row.get("contributes") or {}).get("refs", []):
                if (
                    item["kind"] == kind
                    and prefix.startswith("/")
                    and item["url"].startswith(prefix)
                ):
                    return {"app": row["app"], "title": item["title"], "url": item["url"]}
        return None

    def app_names(self) -> dict[str, str]:
        return {app.id: app.name for app in self.suite_apps()}

    def sync_apps(self, *, force: bool = False) -> None:
        """Reads the installer's outcomes and records them in the audit log."""

        for event in self.apps.sync(force=force):
            if event.get("revoke_key"):  # an uninstalled app's key stops working
                self.workspace.app_keys.revoke(event["revoke_key"], actor=event["username"])
            self.workspace.audit.record(
                event["username"],
                event["action"],
                f"app:{event['app_id']}",
                event["detail"],
                app_id="processcraft",
            )

    @property
    def workspace(self) -> Workspace:
        return self.platform.workspace

    @property
    def datalayer(self) -> Any:
        """Where signals and series are read (``plantcraft.platform.datalayer``)."""

        return self.platform.datalayer

    @property
    def data(self) -> Any:
        return self.platform.data

    @property
    def source(self) -> Any:
        return self.platform.source

    @property
    def prewarming(self) -> bool:
        return self._prewarm is not None and self._prewarm.is_alive()

    def default_user(self) -> str:
        """Who acts when sign-in is off (local and demo use)."""

        configured = os.environ.get("PLANTCRAFT_DEFAULT_USER", "").strip()
        if configured and self.workspace.users.is_person(configured):
            return configured
        users = self.workspace.users.list_users(kind="person")
        return users[0]["username"] if users else "Engineering"

    def admins(self) -> list[str]:
        """The administrators, people only (the environment's account first)."""

        users = self.workspace.users
        default = "editor" if self.auth.enabled else "admin"
        names = [self.auth.username.strip().lower()] if self.auth.enabled else []
        for user in users.list_users(kind="person"):
            access = users.access(user["username"], default=default)
            if access is not None and access.is_admin:
                names.append(user["username"])
        return list(dict.fromkeys(names))

    @staticmethod
    def _own_metrics() -> dict[str, Any]:
        from plantcraft.api.app import platform_version
        from plantcraft_sdk.server.ops import metrics

        return metrics("processcraft", platform_version())

    def _running_services(self) -> set[str] | None:
        found = self.operations.read("metrics.json")
        if not isinstance(found, dict) or found.get("error"):
            return None
        return {
            str(item.get("service"))
            for item in found.get("services") or []
            if item.get("state") == "running"
        }

    def start(self) -> None:
        # With several server processes (PLANTCRAFT_WORKERS) one of them runs the
        # installation's once-only duties; the others stand by to take over.
        threading.Thread(target=self._lead, name="leader", daemon=True).start()
        # With HistCraft as the data layer, PlantCraft reads no plant source itself.
        if env_flag("PLANTCRAFT_PREWARM_HISTORY", True) and not self.datalayer.manages_sources:
            hours = min(PREWARM_HOURS, self.scenario.source.history_cache_hours)
            self._prewarm = threading.Thread(
                target=self.data.prewarm,
                args=(hours,),
                kwargs={
                    "stop": self._stopping,
                    "sample_seconds": self.scenario.analysis.resample_seconds,
                },
                name="history-prewarm",
                daemon=True,
            )
            self._prewarm.start()

    def _lead(self) -> None:
        if not self.leader.wait(self._stopping):
            return
        # After a restart no specialist is still writing a reply.
        self.workspace.messages.clear_busy()
        if env_flag("PLANTCRAFT_WATCH", True):
            self._watching = threading.Thread(
                target=self.watch.run, args=(self._stopping,), name="suite-watch", daemon=True
            )
            self._watching.start()
        if env_flag("PLANTCRAFT_HEALTH_SIGNALS", True) and self.datalayer.keeps_system:
            threading.Thread(
                target=self.health_signals.run,
                args=(self._stopping,),
                name="health-signals",
                daemon=True,
            ).start()
        threading.Thread(
            target=self._compute_upkeep, args=(self._stopping,), name="compute-upkeep", daemon=True
        ).start()
        if env_flag("PLANTCRAFT_MAIL_OUTBOX", True):
            threading.Thread(
                target=self.notifications.run,
                args=(self._stopping,),
                name="mail-outbox",
                daemon=True,
            ).start()

    def stop(self) -> None:
        self._stopping.set()
        self.leader.release()
        self.specialist_chat.shutdown()
        self.assistant.shutdown()
        self.datalayer.close()
