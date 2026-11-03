"""The StarterCraft web application: API and built interface under ``/starter``.

The endpoints every app serves (``/healthz``, ``/api/meta``, ``/api/help``, ``assets/<id>``),
the interface and its sign-in redirects come from ``plantcraft_sdk.server.web``; this module
adds the app's own routers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from plantcraft_sdk.auth import User
from plantcraft_sdk.server import web

from starter import APP_ID, __version__
from starter.api.routers import notes
from starter.api.runtime import Runtime
from starter.config import Settings
from starter.meta import FILES

SOURCE_ROOT = Path(__file__).resolve().parents[3]


def ui_folder() -> Path | None:
    """The built interface: ``STARTER_UI_DIR``, else ``frontend/dist`` of a source checkout."""

    return web.ui_folder(APP_ID, SOURCE_ROOT)


def create_app(runtime: Runtime | None = None) -> FastAPI:
    runtime = runtime or Runtime(Settings.from_environment())

    def me(_user: User) -> dict[str, Any]:
        return {"service_key": runtime.has_service_key}

    api = web.suite_api(
        runtime,
        title="StarterCraft",
        version=__version__,
        files=FILES,
        routers=(notes.router,),
        ui=ui_folder(),
        me=me,
    )
    return web.mount(api, runtime, version=__version__)
