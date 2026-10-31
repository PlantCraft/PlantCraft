"""The PlantCraft Historian web application: API and built interface under ``/hist``.

The endpoints every app serves, the interface and its sign-in redirects come from
``plantcraft_sdk.server.web``; this module adds Historian's routers.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from plantcraft_sdk.app_manifest import parse_manifest
from plantcraft_sdk.server import web
from plantcraft_sdk.server.objects import notebooks_router
from plantcraft_sdk.server.workers import startup

from histcraft import APP_ID, __version__
from histcraft.api.routers import (
    admin,
    certificates,
    data,
    export,
    imports,
    reads,
    search,
    start,
    widgets,
)
from histcraft.api.runtime import Runtime
from histcraft.config import Settings
from histcraft.db import ReadTimeout
from histcraft.meta import FILES
from histcraft.notebook_examples import EXAMPLES

SOURCE_ROOT = Path(__file__).resolve().parents[3]


def ui_folder() -> Path | None:
    """The built interface: ``HISTCRAFT_UI_DIR``, else ``frontend/dist`` of a source checkout."""

    return web.ui_folder(APP_ID, SOURCE_ROOT)


def _manifest():
    data = FILES.manifest()
    return parse_manifest(data) if data else None


def create_app(runtime: Runtime | None = None) -> FastAPI:
    if runtime is None:
        settings = Settings.from_environment()
        # Several server processes start together: one at a time opens the databases.
        with startup(settings.data_dir):
            runtime = Runtime(settings)
    api = web.suite_api(
        runtime,
        title="PlantCraft Historian",
        version=__version__,
        files=FILES,
        routers=(
            data.router,
            reads.router,
            certificates.router,
            admin.router,
            export.router,
            imports.router,
            widgets.router,
            search.router,
            start.router,
            # Its examples in Notebooks (Examples/Historian); it has no objects of its own.
            notebooks_router(EXAMPLES, _manifest()),
        ),
        ui=ui_folder(),
        status_route=False,
    )

    @api.exception_handler(ReadTimeout)
    def too_long(_request: Request, exc: ReadTimeout) -> JSONResponse:
        # PlantCraft passes it on to the caller as it is.
        return JSONResponse({"detail": str(exc)}, status_code=504)

    return web.mount(api, runtime, version=__version__)
