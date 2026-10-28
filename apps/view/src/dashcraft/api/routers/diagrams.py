"""Diagrams: process graphics of the plant, their symbol library and their live data.

Who may do what follows the dashboards: viewers open diagrams, editors draw them, and a folder
decides who sees and who edits what is filed in it. Saved diagrams read plant data like saved
dashboards (``Runtime.dashboard_reader``): with View's own token, cached for every viewer,
except for a person who sees only part of the plant, who reads as themselves.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from dashcraft.api.deps import (
    CurrentUser,
    EditorUser,
    EditorView,
    Permissions,
    RuntimeDep,
    guarded,
    permissions,
    whole_plant,
)
from dashcraft.api.routers.dashboards import ShareBody, link_days, links_on
from dashcraft.dashboards.model import Conflict, check_window
from dashcraft.diagrams.model import DiagramPayload, on_page
from dashcraft.diagrams.read import asset_signals, read_diagram
from dashcraft.diagrams.symbols import library
from dashcraft.i18n import t

router = APIRouter(prefix="/api", tags=["diagrams"])


def _summary(item: dict[str, Any], perms: Permissions) -> dict[str, Any]:
    return {**item, "element_count": len(item.get("elements") or []), "can_edit": perms.edits(item)}


def _brief(item: dict[str, Any], perms: Permissions) -> dict[str, Any]:
    """A row of the list: no elements, only how many."""

    keep = ("diagram_id", "name", "description", "folder_id", "tags", "updated_by", "updated_at")
    return {
        **{key: item.get(key) for key in keep},
        "element_count": len(item.get("elements") or []),
        "can_edit": perms.edits(item),
    }


def diagram_or_404(rt: Any, diagram_id: str, user: Any) -> dict[str, Any]:
    """A diagram the person may see (else "not found", as for a dashboard in a closed folder)."""

    found = rt.diagrams.get(diagram_id) if len(diagram_id) <= 40 else None
    if found is not None and not permissions(rt, user).sees(found):
        found = None
    if found is None:
        raise HTTPException(status_code=404, detail=t("Process display not found."))
    return found


def _editable(rt: Any, diagram_id: str, user: Any) -> dict[str, Any]:
    found = diagram_or_404(rt, diagram_id, user)
    if not permissions(rt, user).edits(found):
        raise HTTPException(
            status_code=403, detail=t("Only the editors of its folder change this process display.")
        )
    return found


def _folder_open(perms: Permissions, folder_id: str) -> None:
    if folder_id and perms.folder(folder_id) is None:
        raise HTTPException(status_code=422, detail=t("That folder does not exist."))
    if not perms.edits_folder(folder_id):
        raise HTTPException(
            status_code=403, detail=t("Only the editors of that folder add process displays to it.")
        )


@router.get("/diagram-symbols")
def list_symbols(_user: CurrentUser) -> list[dict[str, Any]]:
    """The symbol library, each drawing already cleaned (``diagrams/symbols.py``)."""

    return library()


@router.get("/diagrams")
def list_diagrams(rt: RuntimeDep, user: CurrentUser) -> list[dict[str, Any]]:
    perms = permissions(rt, user)
    return [_brief(item, perms) for item in rt.diagrams.list() if perms.sees(item)]


@router.post("/diagrams", status_code=201)
def create_diagram(payload: DiagramPayload, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    perms = permissions(rt, user)
    _folder_open(perms, payload.folder_id)
    created = rt.diagrams.create(payload.stored(), user.username)
    rt.audit(user, "diagram.create", created["diagram_id"], {"name": created["name"]})
    return _summary(created, perms)


@router.get("/diagrams/{diagram_id}")
def get_diagram(diagram_id: str, rt: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    return _summary(diagram_or_404(rt, diagram_id, user), permissions(rt, user))


@router.put("/diagrams/{diagram_id}", response_model=None)
def update_diagram(
    diagram_id: str, payload: DiagramPayload, rt: RuntimeDep, user: EditorUser
) -> dict[str, Any] | JSONResponse:
    found = _editable(rt, diagram_id, user)
    if payload.folder_id != found.get("folder_id", ""):
        _folder_open(permissions(rt, user), payload.folder_id)
    try:
        saved = rt.diagrams.update(
            diagram_id, payload.stored(), user.username, base_updated_at=payload.base_updated_at
        )
    except Conflict as conflict:
        who = conflict.current.get("updated_by") or t("someone")
        return JSONResponse(
            {
                "detail": t(
                    "{user} saved this process display after you opened it. Reload to see their "
                    "changes, or save again to replace them.",
                    user=who,
                ),
                "current": conflict.current,
            },
            status_code=409,
        )
    if saved is None:
        raise HTTPException(status_code=404, detail=t("Process display not found."))
    rt.audit(user, "diagram.update", diagram_id, {"name": saved["name"]})
    return _summary(saved, permissions(rt, user))


@router.delete("/diagrams/{diagram_id}", status_code=204)
def delete_diagram(diagram_id: str, rt: RuntimeDep, user: EditorUser) -> Response:
    found = _editable(rt, diagram_id, user)
    rt.diagrams.delete(diagram_id)
    # A deleted diagram's public links stop working.
    rt.dashboards.revoke_all(diagram_id, user.username, "diagram")
    rt.audit(user, "diagram.delete", diagram_id, {"name": found["name"]})
    return Response(status_code=204)


@router.get("/diagrams/{diagram_id}/versions")
def list_versions(diagram_id: str, rt: RuntimeDep, user: CurrentUser) -> list[dict[str, Any]]:
    diagram_or_404(rt, diagram_id, user)
    return rt.diagrams.versions(diagram_id)


@router.get("/diagrams/{diagram_id}/versions/{version}")
def get_version(diagram_id: str, version: int, rt: RuntimeDep, user: CurrentUser) -> dict:
    diagram_or_404(rt, diagram_id, user)
    found = rt.diagrams.version(diagram_id, version)
    if found is None:
        raise HTTPException(status_code=404, detail=t("That version is not kept."))
    return found


def diagram_window(window: str | None) -> str | None:
    if window is None:
        return None
    try:
        return check_window(window)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def diagram_end(end: str | None) -> datetime | None:
    if not end:
        return None
    try:
        stamp = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=t("The end is not a date and time.")) from exc
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


@router.get("/diagrams/{diagram_id}/data")
def diagram_data(
    diagram_id: str,
    rt: RuntimeDep,
    user: CurrentUser,
    window: str | None = Query(default=None, max_length=8),
    end: str | None = Query(default=None, max_length=40),
    page: str | None = Query(default=None, max_length=40),
) -> dict[str, Any]:
    """Every binding's value now (or at ``end``) and the window's series for playback, of one
    page (``page``) or of every page."""

    found = on_page(diagram_or_404(rt, diagram_id, user), page)
    reader, service = rt.dashboard_reader(user)
    picked, until = diagram_window(window), diagram_end(end)
    return guarded(lambda: read_diagram(reader, found, picked, until), service=service)


class DraftData(BaseModel):
    """A diagram being drawn: its data read as the editor, before it is saved."""

    diagram: DiagramPayload
    window: str | None = Field(default=None, max_length=8)


@router.post("/diagrams/preview")
def preview_data(body: DraftData, rt: RuntimeDep, user: EditorView) -> dict[str, Any]:
    reader = rt.user_reader(user)
    picked = diagram_window(body.window)
    return guarded(lambda: read_diagram(reader, body.diagram.stored(), picked, None), service=False)


@router.get("/diagram-assets/{asset_id}/signals")
def signals_of_asset(asset_id: str, rt: RuntimeDep, user: EditorView) -> list[dict[str, Any]]:
    """The roles of an asset, for the editor's binding picker (read as the editor)."""

    if len(asset_id) > 300:
        raise HTTPException(status_code=404, detail=t("Asset not found."))
    reader = rt.user_reader(user)
    return guarded(lambda: asset_signals(reader, asset_id), service=False)


# Public links: the diagram read-only, live or played back, without signing in -------------
# The same links as dashboards and reports (``DashboardStore`` shares, ``target`` "diagram"),
# made and revoked by the diagram's editors, under the same switch and expiry rules.


@router.get("/diagrams/{diagram_id}/shares")
def list_shares(diagram_id: str, rt: RuntimeDep, user: EditorView) -> list[dict[str, Any]]:
    if user.demo is not None:  # a demo visit sees the dialog; its links stay the editors'
        return []
    _editable(rt, diagram_id, user)
    return rt.dashboards.shares(diagram_id, "diagram")


@router.post("/diagrams/{diagram_id}/shares", status_code=201)
def create_share(diagram_id: str, body: ShareBody, rt: RuntimeDep, user: EditorUser) -> dict:
    _editable(rt, diagram_id, user)
    whole_plant(user)
    links_on(rt)
    days = link_days(body, user)
    share, token = rt.dashboards.create_share(
        diagram_id, user.username, body.label, "diagram", days=days
    )
    rt.audit(
        user, "diagram.share.create", diagram_id, {"share_id": share["share_id"], "days": days}
    )
    return {**share, "path": f"{rt.settings.root_path}/share/diagram/{token}"}


@router.delete("/diagrams/{diagram_id}/shares/{share_id}", status_code=204)
def revoke_share(diagram_id: str, share_id: str, rt: RuntimeDep, user: EditorUser) -> Response:
    _editable(rt, diagram_id, user)
    if not rt.dashboards.revoke_share(diagram_id, share_id, user.username, "diagram"):
        raise HTTPException(status_code=404, detail=t("Link not found."))
    rt.audit(user, "diagram.share.revoke", diagram_id, {"share_id": share_id})
    return Response(status_code=204)
