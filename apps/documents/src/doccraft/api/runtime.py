"""Everything one PlantCraft Documents server holds: settings, the library and the PlantCraft
clients.

Who reads what: the pages and the assistant's tools read as the person (their token), and the
folders decide which documents each person sees. The app key is for what the app does on its
own: reading the asset tree to know the plant's tags, and the groups behind folder access.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from plantcraft_sdk.auth import TokenVerifier, User
from plantcraft_sdk.client import PlantCraftClient
from plantcraft_sdk.server.platform import PlatformRuntime
from plantcraft_sdk.server.store import Database

from doccraft import APP_ID, __version__
from doccraft.config import Settings
from doccraft.library.access import Permissions
from doccraft.library.embed import embedder
from doccraft.library.service import LibraryService
from doccraft.library.store import DocumentStore
from doccraft.plantmap import llm as diagram_llm

LOGGER = logging.getLogger(__name__)
GROUPS_SECONDS = 60


class Runtime(PlatformRuntime):
    def __init__(
        self,
        settings: Settings,
        *,
        verifier: TokenVerifier | None = None,
        service_client: PlantCraftClient | None = None,
        http_client: httpx.Client | None = None,
        background: bool = True,
    ):
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = Database(settings.database_path, version=__version__)
        self.store = DocumentStore(self.db, settings.files_dir)
        self.library = LibraryService(
            self.store,
            embedder(settings.embedding_dir),
            self._known_ids,
            max_bytes=settings.max_file_mb * 1024 * 1024,
            quota_bytes=int(settings.quota_gb * 1024**3),
        )
        self.store.requeue_other_embedder(self.library.embedder.name)
        self.background = background
        self._groups: dict[str, tuple[float, set[str]]] = {}
        self.connect(
            APP_ID,
            settings,
            verifier=verifier,
            service_client=service_client,
            http_client=http_client,
        )

    def read_diagram_with_model(self, png: bytes, result: dict[str, Any]) -> dict[str, Any]:
        """The model of ``diagram-read`` reading a page (``doccraft.plantmap.llm.ask``)."""

        return diagram_llm.ask(self.service_client, png, result)

    def _known_ids(self) -> list[str]:
        if self.service_client is None:
            return []
        return [
            str(asset.get("id") or asset.get("asset_id")) for asset in self.service_client.assets()
        ]

    def groups_of(self, user: User) -> set[str]:
        """The ids of the platform's groups ``user`` belongs to, read once a minute. Unreadable:
        none, so a folder kept for some groups stays closed."""

        cached = self._groups.get(user.username)
        if cached and time.monotonic() - cached[0] < GROUPS_SECONDS:
            return cached[1]
        client = self.service_client or self.user_client(user)
        try:
            groups = {
                str(group.get("id"))
                for group in client.groups() or []
                if user.username in (group.get("members") or [])
            }
        except Exception:  # noqa: BLE001 - a folder's access never breaks the page
            LOGGER.warning("Groups not read from PlantCraft", exc_info=True)
            groups = set()
        self._groups[user.username] = (time.monotonic(), groups)
        return groups

    def permissions(self, user: User) -> Permissions:
        folders = {item["folder_id"]: item for item in self.store.folders()}
        restricted = any(item.get("viewers") or item.get("editors") for item in folders.values())
        return Permissions(
            username=user.username,
            admin=user.is_admin,
            editor=user.can_edit,
            groups=self.groups_of(user) if restricted and not user.is_admin else set(),
            folders=folders,
            scope=self.asset_scope(user),
        )

    def start(self) -> None:
        if self.background:
            self.library.start()

    def shutdown(self) -> None:
        self.library.stop()
        self.close_platform()

    def status(self) -> dict[str, Any]:
        return {
            "service_key": self.has_service_key,
            "embedder": self.library.embedder.name,
            **self.store.counts(),
        }
