"""The PlantCraft View web application: API and built interface under ``/dash``.

The endpoints every app serves, the interface and its sign-in redirects come from
``plantcraft_sdk.server.web``; this module adds Dashboards' routers. Pages need a signed-in
person, except ``share/<token>``: a public link checks its token in the API.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from plantcraft_sdk.auth import User
from plantcraft_sdk.server import web

from dashcraft import APP_ID, __version__
from dashcraft.api.routers import (
    dashboards,
    diagram_drafts,
    diagrams,
    folders,
    objects,
    picker,
    public,
    reports,
    search,
    trends,
    widgets,
)
from dashcraft.api.runtime import Runtime
from dashcraft.config import Settings
from dashcraft.meta import FILES

LOGGER = logging.getLogger(__name__)
SOURCE_ROOT = Path(__file__).resolve().parents[3]


def ui_folder() -> Path | None:
    """The built interface: ``DASHCRAFT_UI_DIR``, else ``frontend/dist`` of a source checkout."""

    return web.ui_folder(APP_ID, SOURCE_ROOT)


def _migrate(runtime: Runtime) -> None:
    try:
        runtime.migrate_signal_ids()
    except Exception:  # noqa: BLE001 - a failed rename leaves the cards as they were
        LOGGER.exception("Signal ids of saved cards not migrated")
    runtime.ensure_suite_health(force=True)


def create_app(runtime: Runtime | None = None) -> FastAPI:
    runtime = runtime or Runtime(Settings.from_environment())

    def me(_user: User) -> dict[str, Any]:
        return {"public_links": runtime.settings.public_links and runtime.has_service_key}

    def start() -> None:
        # Cards saved with bare tags move to API v1 signal ids; never holds up the start.
        threading.Thread(target=_migrate, args=(runtime,), daemon=True).start()
        runtime.start_reports()

    api = web.suite_api(
        runtime,
        title="PlantCraft View",
        version=__version__,
        files=FILES,
        routers=(
            dashboards.router,
            diagram_drafts.router,
            diagrams.router,
            folders.router,
            objects.router,
            picker.router,
            public.router,
            public.pages,
            reports.router,
            trends.router,
            widgets.router,
            search.router,
        ),
        ui=ui_folder(),
        me=me,
        public_pages=("share/",),
    )
    return web.mount(api, runtime, version=__version__, on_start=start)
