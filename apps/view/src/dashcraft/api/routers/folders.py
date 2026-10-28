"""Folders of dashboards and reports: list, create, change who sees and edits them, delete an empty one;
and the people and groups of the platform a folder's pickers offer."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Response
from plantcraft_sdk.client import PlantCraftError

from dashcraft.api.deps import CurrentUser, EditorUser, EditorView, RuntimeDep, guarded, permissions
from dashcraft.dashboards.folders import MAX_FOLDERS, FolderPayload, may_edit
from dashcraft.i18n import t

router = APIRouter(prefix="/api", tags=["folders"])


def _shown(rt: RuntimeDep, user: Any) -> list[dict[str, Any]]:
    perms = permissions(rt, user)
    counts: dict[str, int] = {}
    reports: dict[str, int] = {}
    for item in rt.dashboards.list():
        if perms.sees(item):
            counts[item.get("folder_id") or ""] = counts.get(item.get("folder_id") or "", 0) + 1
    for item in rt.reports.list():
        if perms.sees(item):
            reports[item.get("folder_id") or ""] = reports.get(item.get("folder_id") or "", 0) + 1
    return [
        {
            **folder,
            "dashboards": counts.get(folder["folder_id"], 0),
            "reports": reports.get(folder["folder_id"], 0),
            "can_edit": perms.edits_folder(folder["folder_id"]),
        }
        for folder in perms.folders.values()
        if perms.sees_folder(folder["folder_id"])
    ]


def _editable(rt: RuntimeDep, user: Any, folder_id: str) -> dict[str, Any]:
    perms = permissions(rt, user)
    folder = perms.folder(folder_id)
    if folder is None or not perms.sees_folder(folder_id):
        raise HTTPException(status_code=404, detail=t("Folder not found."))
    if not perms.edits_folder(folder_id):
        raise HTTPException(status_code=403, detail=t("Only the editors of this folder change it."))
    return folder


def _keeps_access(rt: RuntimeDep, user: Any, payload: FolderPayload) -> None:
    """Nobody but an administrator takes themselves off the folder's editors."""

    if user.is_admin or not payload.editors:
        return
    groups = rt.groups_of(user)
    folder = payload.model_dump()
    if not may_edit(folder, username=user.username, groups=groups, admin=False, editor=True):
        raise HTTPException(
            status_code=422,
            detail=t("Keep yourself among the editors, or you could no longer change it."),
        )


@router.get("/folders")
def list_folders(rt: RuntimeDep, user: CurrentUser) -> list[dict[str, Any]]:
    return _shown(rt, user)


@router.post("/folders", status_code=201)
def create_folder(payload: FolderPayload, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    if rt.folders.count() >= MAX_FOLDERS:
        raise HTTPException(status_code=422, detail=t("At most {n} folders.", n=MAX_FOLDERS))
    if rt.folders.by_name(payload.name):
        raise HTTPException(status_code=409, detail=t("There is a folder with that name."))
    _keeps_access(rt, user, payload)
    created = rt.folders.create(payload.model_dump(), user.username)
    rt.audit(
        user,
        "folder.create",
        created["folder_id"],
        {"name": created["name"], "viewers": created["viewers"], "editors": created["editors"]},
    )
    return {**created, "dashboards": 0, "reports": 0, "can_edit": True}


@router.put("/folders/{folder_id}")
def update_folder(
    folder_id: str, payload: FolderPayload, rt: RuntimeDep, user: EditorUser
) -> dict[str, Any]:
    _editable(rt, user, folder_id)
    other = rt.folders.by_name(payload.name)
    if other and other["folder_id"] != folder_id:
        raise HTTPException(status_code=409, detail=t("There is a folder with that name."))
    _keeps_access(rt, user, payload)
    saved = rt.folders.update(folder_id, payload.model_dump(), user.username) or {}
    rt.audit(
        user,
        "folder.update",
        folder_id,
        {"name": saved["name"], "viewers": saved["viewers"], "editors": saved["editors"]},
    )
    return next(item for item in _shown(rt, user) if item["folder_id"] == folder_id)


@router.delete("/folders/{folder_id}", status_code=204)
def delete_folder(folder_id: str, rt: RuntimeDep, user: EditorUser) -> Response:
    folder = _editable(rt, user, folder_id)
    if (
        rt.dashboards.in_folder(folder_id)
        or rt.reports.in_folder(folder_id)
        or rt.diagrams.in_folder(folder_id)
    ):
        raise HTTPException(
            status_code=409,
            detail=t(
                "Move or delete its dashboards, reports and process displays first: the folder is not "
                "empty."
            ),
        )
    rt.folders.delete(folder_id)
    rt.audit(user, "folder.delete", folder_id, {"name": folder["name"]})
    return Response(status_code=204)


@router.get("/directory")
def directory(rt: RuntimeDep, user: EditorView) -> dict[str, Any]:
    """The people and groups a folder's "who sees" and "who edits" pick from (as the person)."""

    client = rt.user_client(user)
    if user.demo is not None:
        # The visitor tries the folder and report dialogs; an empty list is enough to pick from.
        try:
            return {"people": client.people(), "groups": client.groups()}
        except PlantCraftError:
            return {"people": [], "groups": []}
    return {
        "people": guarded(client.people, service=False),
        "groups": guarded(client.groups, service=False),
    }
