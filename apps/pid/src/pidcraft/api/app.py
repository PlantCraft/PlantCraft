"""The PlantCraft PID web application: API and built interface under ``/pid``.

The endpoints every app serves (``/healthz``, ``/api/meta``, ``/api/help``, ``assets/<id>``),
the interface and its sign-in redirects come from ``plantcraft_sdk.server.web``; this module
adds the app's own routers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from plantcraft_sdk.auth import User
from plantcraft_sdk.server import web

from pidcraft import APP_ID, __version__
from pidcraft.api.routers import drawings, plantmap, refs, search, widgets
from pidcraft.api.runtime import Runtime
from pidcraft.config import Settings
from pidcraft.meta import FILES

SOURCE_ROOT = Path(__file__).resolve().parents[3]


def ui_folder() -> Path | None:
    """The built interface: ``PIDCRAFT_UI_DIR``, else ``frontend/dist`` of a source checkout."""

    return web.ui_folder(APP_ID, SOURCE_ROOT)


def create_app(runtime: Runtime | None = None) -> FastAPI:
    runtime = runtime or Runtime(Settings.from_environment())

    def me(_user: User) -> dict[str, Any]:
        return {"service_key": runtime.has_service_key}

    api = web.suite_api(
        runtime,
        title="PlantCraft PID",
        version=__version__,
        files=FILES,
        routers=(drawings.router, plantmap.router, search.router, refs.router, widgets.router),
        ui=ui_folder(),
        me=me,
    )

    @api.middleware("http")
    async def licensed(request: Request, call_next: Any) -> Any:
        """Without a usable licence only the frame's own routes answer (pidcraft.licence)."""

        path = request.scope.get("path", "")
        root = runtime.settings.root_path.rstrip("/")
        local = path[len(root) :] if root and path.startswith(root) else path
        if not runtime.licence.allows(local):
            state = runtime.licence.state
            return JSONResponse(
                {"detail": state.message, "license": state.to_json()}, status_code=402
            )
        return await call_next(request)

    return web.mount(api, runtime, version=__version__)
