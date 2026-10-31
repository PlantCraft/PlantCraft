"""The PlantCraft Analytics web application: API and built interface under ``/link``.

The endpoints every app serves, the interface and its sign-in redirects come from
``plantcraft_sdk.server.web``; this module adds Link's routers. Link serves its own help
(``routers/help_pages.py``: guides and a page per method, with this site's defaults) and its own
``/api/status`` (the engine's), and reads ``app.toml`` where ``config.manifest_path`` finds it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from plantcraft_sdk.server import web

from linkcraft import APP_ID, __version__
from linkcraft.api.routers import (
    apc,
    assets,
    assistant,
    blocks,
    catalog,
    engine,
    executions,
    folders,
    groups,
    help_pages,
    loops,
    losses,
    models,
    objects,
    oscillations,
    prompts,
    results,
    runs,
    search,
    signal_quality,
    signals,
    widgets,
)
from linkcraft.api.runtime import Runtime
from linkcraft.config import Settings, app_manifest, revision

SOURCE_ROOT = Path(__file__).resolve().parents[3]


def ui_folder() -> Path | None:
    """The built interface: ``LINKCRAFT_UI_DIR``, else ``frontend/dist`` of a source checkout."""

    return web.ui_folder(APP_ID, SOURCE_ROOT)


class Files:
    """What ``/api/meta`` answers: ``app.toml`` plus the source revision."""

    app_id = APP_ID  # /api/ops/metrics names the app with it

    @staticmethod
    def manifest() -> dict[str, Any]:
        """``app.toml``: the SDK sends its contributions to PlantCraft from it at start."""
        return app_manifest()

    @staticmethod
    def meta() -> dict[str, Any]:
        return {**app_manifest(), "revision": revision()}


def create_app(runtime: Runtime | None = None) -> FastAPI:
    runtime = runtime or Runtime(Settings.from_environment())
    api = web.suite_api(
        runtime,
        title="PlantCraft Analytics",
        version=__version__,
        files=Files,
        routers=(
            loops.router,
            catalog.router,
            blocks.router,
            engine.router,
            help_pages.router,
            signal_quality.router,
            signals.router,
            results.router,
            losses.router,
            apc.router,
            oscillations.router,
            runs.router,
            groups.router,
            folders.router,
            executions.router,
            widgets.router,
            assistant.router,
            assets.router,
            models.router,
            prompts.router,
            search.router,
            objects.router,
            objects.notebooks(),
        ),
        ui=ui_folder(),
        help_routes=False,
        status_route=False,
    )
    return web.mount(api, runtime, version=__version__)
