"""Settings › Installation (the installation's time zone) and each person's Preferences
(``/api/me/preferences``: the language and the time zone their screens show).

Times are stored and computed in UTC and shown in local time. "Local time"
is the installation's zone, chosen here; each person may show UTC or their own device's
instead.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from plantcraft.api.deps import AdminUser, CurrentUser, Runtime, open_to
from plantcraft.apps.manager import AppError
from plantcraft.config import plant_timezone
from plantcraft.i18n import t

router = APIRouter()

PREFERENCES_KEY = "general"
TimeZoneMode = Literal["plant", "utc", "device"]
DEFAULTS: dict[str, Any] = {"time_zone": "plant", "language": None}


class InstallationPayload(BaseModel):
    time_zone: str = Field(min_length=1, max_length=64)


class PreferencesPayload(BaseModel):
    time_zone: TimeZoneMode = "plant"
    language: str | None = Field(
        default=None, max_length=10, pattern=r"^[A-Za-z]{2}(-[A-Za-z]{2})?$"
    )


def _installation(rt: Any) -> dict[str, Any]:
    settings = rt.workspace.installation.settings()
    now = datetime.now(plant_timezone(fresh=True))
    return {**settings, "now": now.isoformat(timespec="seconds")}


@router.get("/api/setup/installation")
def installation(_admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    return _installation(rt)


@router.put("/api/setup/installation")
def save_installation(
    payload: InstallationPayload, admin: AdminUser, rt: Runtime
) -> dict[str, Any]:
    before = rt.workspace.installation.settings()["time_zone"]
    try:
        rt.workspace.installation.save_time_zone(payload.time_zone, actor=admin)
    except PermissionError as exc:
        raise HTTPException(
            status_code=409,
            detail=t(
                "The installation file fixed the time zone. Change it on the server: edit "
                "/etc/plantcraft/installation.conf and run install.sh again."
            ),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=t("Unknown time zone: {zone}.", zone=payload.time_zone)
        ) from exc
    after = _installation(rt)
    # Backups at "local" time follow: the installer reads the zone from the schedule's file.
    try:
        rt.operations.set_schedule({})
    except (AppError, OSError):
        pass  # no installer here (a development run): nothing reads the file
    rt.workspace.audit.record(
        admin,
        "installation.time_zone",
        "setting:installation",
        {"from": before, "to": after["time_zone"]},
        app_id="processcraft",
    )
    return after


def preferences(rt: Any, username: str) -> dict[str, Any]:
    stored = rt.workspace.preferences.get(username, PREFERENCES_KEY)
    found = {**DEFAULTS, **(stored if isinstance(stored, dict) else {})}
    if found["time_zone"] not in ("plant", "utc", "device"):
        found["time_zone"] = "plant"
    return {"time_zone": found["time_zone"], "language": found["language"]}


@router.get("/api/me/preferences")
@open_to("dashboards")
def my_preferences(user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    return {**preferences(rt, user), "installation_time_zone": plant_timezone().key}


@router.put("/api/me/preferences")
@open_to("dashboards")
def save_my_preferences(
    payload: PreferencesPayload, user: CurrentUser, rt: Runtime
) -> dict[str, Any]:
    rt.workspace.preferences.put(user, PREFERENCES_KEY, payload.model_dump())
    return {**preferences(rt, user), "installation_time_zone": plant_timezone().key}
