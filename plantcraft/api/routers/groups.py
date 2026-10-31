"""HTTP routes: groups of people (docs/groups.md).

Everyone signed in reads the groups (an app's picker, a person's profile); administrators create,
change and delete them; a group's coordinator changes its members.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from plantcraft.api.deps import (
    AdminUser,
    CurrentUser,
    Runtime,
    asset_roots,
    open_to,
    user_access,
)
from plantcraft.groups import kind_labels
from plantcraft.i18n import t
from plantcraft.platform.asset_scope import MAX_SCOPE_ROOTS

router = APIRouter()


class GroupPayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    group_id: str | None = Field(default=None, max_length=60)
    kind: Literal["department", "area", "discipline", "team", "company"] = "team"
    parent_id: str | None = Field(default=None, max_length=60)
    description: str = Field(default="", max_length=500)
    asset_id: str | None = Field(default=None, max_length=300)
    coordinator: str | None = Field(default=None, max_length=60)
    members: list[str] = Field(default_factory=list, max_length=500)
    # The roots of the asset tree members see (docs/asset-scope.md); null: the group limits
    # nothing. Left out of an update: kept as it is.
    asset_scope: list[Annotated[str, Field(min_length=1, max_length=200)]] | None = Field(
        default=None, max_length=MAX_SCOPE_ROOTS
    )
    # A company's last day of access (YYYY-MM-DD) and its sponsor at the plant (plantcraft.groups).
    access_until: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    sponsor: str | None = Field(default=None, max_length=60)


class MembersPayload(BaseModel):
    members: list[str] = Field(default_factory=list, max_length=500)


def _found(rt: Any, group_id: str) -> dict[str, Any]:
    group = rt.workspace.groups.get(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail=t("Group not found."))
    return group


def _audit(rt: Any, username: str, action: str, group_id: str, detail: Any) -> None:
    rt.workspace.audit.record(username, action, f"group:{group_id}", detail, app_id="processcraft")


@router.get("/api/groups")
@open_to("dashboards")
def groups(_user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """Every group with its members, and the kinds to choose from."""

    return {
        "groups": rt.workspace.groups.list(),
        "kinds": [{"id": key, "label": label} for key, label in kind_labels().items()],
    }


@router.get("/api/groups/{group_id}")
@open_to("dashboards")
def group(group_id: str, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    found = _found(rt, group_id)
    access = user_access(rt, user)
    names = {item["group_id"]: item["name"] for item in rt.workspace.groups.list()}
    return {
        **found,
        "path": [
            {"group_id": item, "name": names.get(item, item)}
            for item in reversed(rt.workspace.groups.ancestors(group_id))
        ],
        "subgroups": [
            {"group_id": item, "name": names.get(item, item)} for item in found["children"]
        ],
        "can_manage": bool(access and access.is_admin),
        "can_edit_members": bool(access and access.is_admin)
        or (found["coordinator"] == user and found["asset_scope"] is None),
        "is_member": any(member["username"] == user for member in found["members"]),
    }


@router.post("/api/groups", status_code=201)
def create_group(payload: GroupPayload, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    scope = asset_roots(rt, payload.asset_scope)
    try:
        created = rt.workspace.groups.create(
            payload.name,
            group_id=payload.group_id,
            kind=payload.kind,
            description=payload.description,
            asset_id=payload.asset_id,
            coordinator=payload.coordinator,
            members=payload.members,
            parent_id=payload.parent_id,
        )
        if scope is not None:
            created = rt.workspace.groups.set_asset_scope(created["group_id"], scope)
        if payload.kind == "company":
            created = rt.workspace.groups.set_company(
                created["group_id"], access_until=payload.access_until, sponsor=payload.sponsor
            )
    except KeyError as exc:
        raise HTTPException(
            status_code=409, detail=t("A group with this id already exists.")
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _audit(rt, admin, "group.created", created["group_id"], payload.model_dump())
    return created


@router.put("/api/groups/{group_id}")
def update_group(
    group_id: str, payload: GroupPayload, admin: AdminUser, rt: Runtime
) -> dict[str, Any]:
    _found(rt, group_id)
    scope_given = "asset_scope" in payload.model_fields_set
    scope = asset_roots(rt, payload.asset_scope) if scope_given else None
    try:
        updated = rt.workspace.groups.update(
            group_id,
            name=payload.name,
            kind=payload.kind,
            description=payload.description,
            asset_id=payload.asset_id,
            coordinator=payload.coordinator,
            members=payload.members,
            parent_id=payload.parent_id,
        )
        if scope_given:
            updated = rt.workspace.groups.set_asset_scope(group_id, scope)
        updated = rt.workspace.groups.set_company(
            group_id, access_until=payload.access_until, sponsor=payload.sponsor
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _audit(rt, admin, "group.updated", group_id, payload.model_dump())
    rt.workspace.messages.group_changed(group_id, rt.workspace.groups.members(group_id))
    return updated


@router.put("/api/groups/{group_id}/members")
@open_to("viewer")
def set_members(
    group_id: str, payload: MembersPayload, user: CurrentUser, rt: Runtime
) -> dict[str, Any]:
    """The coordinator (or an administrator) chooses the members."""

    found = _found(rt, group_id)
    access = user_access(rt, user)
    if not (access and access.is_admin) and found["coordinator"] != user:
        raise HTTPException(
            status_code=403,
            detail=t("Only the group's coordinator or an administrator changes its members."),
        )
    if not (access and access.is_admin) and found["asset_scope"] is not None:
        # Joining it changes what of the plant a person sees: access is an administrator's.
        raise HTTPException(
            status_code=403,
            detail=t(
                "This group limits the assets its members see: an administrator changes its members."
            ),
        )
    try:
        updated = rt.workspace.groups.set_members(group_id, payload.members)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _audit(rt, user, "group.members", group_id, {"members": payload.members})
    rt.workspace.messages.group_changed(group_id, rt.workspace.groups.members(group_id))
    return updated


@router.delete("/api/groups/{group_id}")
def delete_group(group_id: str, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    _found(rt, group_id)
    rt.workspace.groups.delete(group_id)
    rt.workspace.messages.group_changed(group_id, None)
    _audit(rt, admin, "group.deleted", group_id, None)
    return {"deleted": group_id}
