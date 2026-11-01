"""PlantCraft PID' licence check (PlantCraft docs/app-package.md, section 8).

PID is a closed app: it works on an installation that holds a licence signed by its
publisher, PlantCraft. The administrator adds the ``.pclicense`` in PlantCraft (Apps › Licences);
the app reads it through API v1 at start and every hour, and checks the signature here with the
publisher's public key, which lives in this module (compiled into the image), never in a setting.

Without a usable licence the pages still open and say why; the API answers 402 for everything
but the app's meta, help, health and licence routes. After the licence ends, the app keeps
working ``grace_days`` (app.toml ``[license]``) and warns. Limits the licence names
(``sheets``: drawings) are held when a drawing is sent.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from plantcraft_sdk.licensing import LicenseGuard, LicenseState

from pidcraft import APP_ID

LOG = logging.getLogger(__name__)

# PlantCraft's publisher key (deploy/trusted-publishers/processcraft.pub): the one that signs
# PlantCraft's packages and licences.
PUBLISHER_KEY = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAzCGLOZ93xplDXMelUukiuuDG/9iVP+597AIG547SGcQ=
-----END PUBLIC KEY-----
"""
GRACE_DAYS = 14
REFRESH_SECONDS = 3600
# What answers without a licence: the frame needs these to draw the page that explains.
OPEN_PATHS = ("/api/meta", "/api/help", "/api/license", "/api/me", "/healthz")


class Licence:
    """The app's licence state, read from PlantCraft and checked with the publisher's key."""

    def __init__(self, guard: LicenseGuard | None = None):
        self.guard = guard or LicenseGuard(
            app_id=APP_ID, public_key=PUBLISHER_KEY, grace_days=GRACE_DAYS
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def state(self) -> LicenseState:
        return self.guard.current

    def refresh(self, client: Any) -> LicenseState:
        if client is None:
            return self.guard.check(None, None)
        state = self.guard.refresh(client)
        LOG.info("licence: %s", state.status)
        return state

    def start(self, client: Any) -> None:
        self.refresh(client)
        if self._thread is not None:
            return

        def loop() -> None:
            while not self._stop.wait(REFRESH_SECONDS):
                try:
                    self.refresh(client)
                except Exception:  # noqa: BLE001 - keep the last state
                    LOG.exception("licence refresh failed")

        self._thread = threading.Thread(target=loop, name="pidcraft-licence", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def allows(self, path: str) -> bool:
        return self.state.usable or not path.startswith("/api/") or path.startswith(OPEN_PATHS)

    def limit(self, name: str) -> int | None:
        return self.state.limit(name)
