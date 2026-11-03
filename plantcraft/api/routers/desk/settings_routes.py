"""Desk's settings: published calendar links and the team page."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, Field

from plantcraft.api.deps import AdminUser, CurrentUser, Runtime
from plantcraft.api.routers.desk.common import _bad, router

# Settings -------------------------------------------------------------------------------------


class DeskSettingsIn(BaseModel):
    enabled: bool = False
    hosts: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list, max_length=20)


@router.get("/api/desk/settings")
def desk_settings(_admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    return rt.desk.settings()


class TeamPageIn(BaseModel):
    enabled: bool


@router.get("/api/desk/team-page")
def team_page(_user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """Whether Desk shows its Team page (off until an administrator turns it on)."""

    return {"enabled": rt.desk.team_page()}


@router.put("/api/desk/team-page")
def save_team_page(body: TeamPageIn, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    enabled = rt.desk.save_team_page(body.enabled, actor=admin)
    rt.workspace.audit.record(
        admin, "desk.team_page", "setting:team_page", {"enabled": enabled}, app_id="processcraft"
    )
    return {"enabled": enabled}


@router.put("/api/desk/settings")
def save_desk_settings(body: DeskSettingsIn, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    try:
        saved = rt.desk.save_settings(enabled=body.enabled, hosts=body.hosts, actor=admin)
    except ValueError as exc:
        raise _bad(exc) from exc
    rt.workspace.audit.record(
        admin,
        "desk.calendar_links",
        "setting:calendar_links",
        {"enabled": saved["enabled"], "hosts": saved["hosts"]},
        app_id="processcraft",
    )
    return saved
