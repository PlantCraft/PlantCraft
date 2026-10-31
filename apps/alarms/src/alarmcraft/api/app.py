"""The PlantCraft Alarms web application: API and built interface under ``/alarm``.

The endpoints every app serves, the interface and its sign-in redirects come from
``plantcraft_sdk.server.web``; this module adds Alarms' routers. The monitor starts with the
application and stops with it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from plantcraft_sdk.auth import User
from plantcraft_sdk.server import web

from alarmcraft import APP_ID, __version__
from alarmcraft.api.routers import (
    alarmlist,
    alarms,
    catalog,
    history,
    incoming,
    notices,
    objects,
    operate,
    plant,
    rules,
    search,
    widgets,
)
from alarmcraft.api.runtime import Runtime
from alarmcraft.config import Settings
from alarmcraft.meta import FILES

SOURCE_ROOT = Path(__file__).resolve().parents[3]


def ui_folder() -> Path | None:
    """The built interface: ``ALARMCRAFT_UI_DIR``, else ``frontend/dist`` of a source checkout."""

    return web.ui_folder(APP_ID, SOURCE_ROOT)


def create_app(runtime: Runtime | None = None) -> FastAPI:
    runtime = runtime or Runtime(Settings.from_environment())

    def me(_user: User) -> dict[str, Any]:
        return {"service_key": runtime.has_service_key, "email_ready": runtime.email_ready()}

    api = web.suite_api(
        runtime,
        title="PlantCraft Alarms",
        version=__version__,
        files=FILES,
        routers=(
            catalog.router,  # before rules: /rules/from-catalog is not a rule id
            rules.router,
            alarmlist.router,
            alarms.router,
            incoming.router,
            history.router,
            notices.router,
            operate.router,
            plant.router,
            widgets.router,
            search.router,
            objects.router,
            objects.notebooks(),
        ),
        ui=ui_folder(),
        me=me,
    )
    return web.mount(api, runtime, version=__version__)
