"""The PlantCraft Models web application: API and built interface under ``/model``.

The endpoints every app serves, the interface and its sign-in redirects come from
``plantcraft_sdk.server.web``; this module adds Models' routers. Starting the application reads
the library index (once per runner version) in the background.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from plantcraft_sdk.auth import User
from plantcraft_sdk.server import web

from modelcraft import APP_ID, __version__
from modelcraft.api.routers import (
    blocks,
    folders,
    model,
    models,
    objects,
    plant,
    projects,
    prompts,
    runs,
    search,
    studies,
    widgets,
)
from modelcraft.api.runtime import Runtime
from modelcraft.config import Settings
from modelcraft.meta import FILES

SOURCE_ROOT = Path(__file__).resolve().parents[3]


def ui_folder() -> Path | None:
    """The built interface: ``MODELCRAFT_UI_DIR``, else ``frontend/dist`` of a source checkout."""

    return web.ui_folder(APP_ID, SOURCE_ROOT)


def create_app(runtime: Runtime | None = None) -> FastAPI:
    runtime = runtime or Runtime(Settings.from_environment())

    def me(_user: User) -> dict[str, Any]:
        return {"service_key": runtime.has_service_key}

    api = web.suite_api(
        runtime,
        title="PlantCraft Models",
        version=__version__,
        files=FILES,
        routers=(
            projects.router,
            model.router,
            models.router,
            runs.router,
            studies.router,
            blocks.router,
            folders.router,
            plant.router,
            widgets.router,
            prompts.router,
            search.router,
            objects.router,
            objects.notebooks(),
        ),
        ui=ui_folder(),
        me=me,
    )
    return web.mount(api, runtime, version=__version__)
