"""Everything one PlantCraft PID server holds: settings, the drawings, the licence and the
PlantCraft clients.

The pages read with the person's own token, so PlantCraft's permissions decide who reaches the
app. The app key (``PLANTCRAFT_APP_KEY``) is for what the app does on its own: reading its
licence and asking the model of ``diagram-read``.
"""

from __future__ import annotations

from typing import Any

import httpx
from plantcraft_sdk.auth import TokenVerifier
from plantcraft_sdk.client import PlantCraftClient
from plantcraft_sdk.server.platform import PlatformRuntime
from plantcraft_sdk.server.store import Database

from pidcraft import APP_ID, __version__
from pidcraft.config import Settings
from pidcraft.drawings.service import DrawingService
from pidcraft.drawings.store import DrawingStore
from pidcraft.licence import Licence
from pidcraft.suite import Suite


class Runtime(PlatformRuntime):
    def __init__(
        self,
        settings: Settings,
        *,
        verifier: TokenVerifier | None = None,
        service_client: PlantCraftClient | None = None,
        http_client: httpx.Client | None = None,
        licence: Licence | None = None,
        background: bool = True,
    ):
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = Database(settings.database_path, version=__version__)
        self.suite = Suite(lambda: self.service_client)
        self.store = DrawingStore(self.db, settings.data_dir / "files")
        self.drawings = DrawingService(self.store)
        self.licence = licence or Licence()
        self.background = background
        self.connect(
            APP_ID,
            settings,
            verifier=verifier,
            service_client=service_client,
            http_client=http_client,
        )

    def start(self) -> None:
        """The licence check and the reader of queued drawings."""

        self.licence.start(self.service_client)
        if self.background:
            self.drawings.start()

    def shutdown(self) -> None:
        self.drawings.stop()
        self.licence.stop()
        self.close_platform()

    def read_diagram_with_model(self, png: bytes, result: dict[str, Any]) -> dict[str, Any]:
        return self.suite.read_with_model(png, result)

    def status(self) -> dict[str, Any]:
        return {
            "service_key": self.has_service_key,
            "drawings": len(self.drawings.list()),
            "licence": self.licence.state.status,
        }
