"""Settings › Apps: each app's installation settings and its own Settings pages (administrators).

PlantCraft draws what the apps declare (``[[contributes.settings]]``, ``[[contributes.setup]]``,
``docs/app-standard.md`` 4b) without knowing them: a new app's settings appear here when it
starts. A secret value is never sent back, only whether it is set.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from processcraft.api.deps import AdminUser, Runtime
from processcraft.i18n import t

router = APIRouter()


class SettingsIn(BaseModel):
    # key -> value; null puts the default back.
    values: dict[str, Any] = Field(max_length=100)


def _app_entry(rt: Any, row: dict[str, Any], name: str) -> dict[str, Any]:
    contributes = row.get("contributes") or {}
    specs = contributes.get("settings", [])
    chosen = rt.app_settings.stored(row["app"])
    settings = []
    for spec in specs:
        key = spec["key"]
        entry = {**spec, "changed": key in chosen}
        if spec.get("secret"):
            entry["value"] = None
            entry["set"] = key in chosen
            entry.pop("default", None)
        else:
            entry["value"] = chosen.get(key, spec.get("default"))
        settings.append(entry)
    return {
        "app": row["app"],
        "name": name,
        "version": row.get("version", ""),
        "settings": settings,
        "pages": contributes.get("setup", []),
    }


def _apps(rt: Any) -> list[dict[str, Any]]:
    installed = rt.suite_apps()
    names = {item.id: item.name for item in installed}
    rows = rt.contributions.listing([item.id for item in installed])
    return [
        _app_entry(rt, row, names.get(row["app"], row["app"]))
        for row in rows
        if (row.get("contributes") or {}).get("settings")
        or (row.get("contributes") or {}).get("setup")
    ]


@router.get("/api/setup/apps")
def setup_apps(_admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """The apps that declare installation settings or Settings pages, in the suite's order."""

    return {"apps": _apps(rt)}


@router.put("/api/setup/apps/{app}")
def save_setup_app(app: str, body: SettingsIn, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """Some of ``app``'s settings changed; the app reads them at its next
    ``GET /api/v1/contributions/settings``."""

    row = rt.contributions.get(app) if app in {item.id for item in rt.suite_apps()} else None
    if row is None:
        raise HTTPException(status_code=404, detail=t("No such app."))
    specs = (row.get("contributes") or {}).get("settings", [])
    try:
        changed = rt.app_settings.save(app, specs, body.values, admin)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    secret = {spec["key"] for spec in specs if spec.get("secret")}
    rt.workspace.audit.record(
        admin,
        "app.settings",
        f"app:{app}",
        {key: ("(secret)" if key in secret else value) for key, value in changed.items()},
        app_id="processcraft",
    )
    names = {item.id: item.name for item in rt.suite_apps()}
    return _app_entry(rt, rt.contributions.get(app) or row, names.get(app, app))
