"""Dashboards: list, open, build, save, copy, delete, share; and the data of their cards."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from plantcraft_sdk.contributes import StartIn, StartOut
from pydantic import BaseModel, Field, ValidationError

from dashcraft.api.deps import (
    CurrentUser,
    EditorUser,
    EditorView,
    Permissions,
    RuntimeDep,
    dashboard_or_404,
    editable_or_403,
    guarded,
    permissions,
    whole_plant,
)
from dashcraft.api.views import (
    card_data,
    context_options,
    dashboard_variable_options,
    diagram_card,
    raw_values,
    resolve_values,
    variable_options,
)
from dashcraft.dashboards.model import CardPreview as CardPreviewBody
from dashcraft.dashboards.model import Conflict, DashboardPayload
from dashcraft.dashboards.starter import starter_dashboards, templates, unit_overviews
from dashcraft.dashboards.variables import Variable
from dashcraft.i18n import t
from dashcraft.query.cards import card_window, read_card

router = APIRouter(prefix="/api", tags=["dashboards"])
LINK_DAYS = 90
MAX_LINK_DAYS = 366


class ShareBody(BaseModel):
    label: str = Field(default="", max_length=80)
    # How long the link opens (review decision D4, 2026-10-27): 90 days unless said
    # otherwise; ``None`` (until revoked, for a control room screen) is an administrator's.
    days: int | None = Field(default=LINK_DAYS, ge=1, le=MAX_LINK_DAYS)


def link_days(body: ShareBody, user: Any) -> int | None:
    """The days ``body`` asks for, refusing "until revoked" to anyone but an administrator."""

    if body.days is None and getattr(user, "level", "") != "admin":
        raise HTTPException(
            status_code=403, detail=t("Only an administrator makes a link that never expires.")
        )
    return body.days


def _summary(item: dict[str, Any], perms: Permissions) -> dict[str, Any]:
    return {**item, "card_count": len(item.get("cards") or []), "can_edit": perms.edits(item)}


def _folder_open(perms: Permissions, folder_id: str) -> str:
    """The folder a dashboard is saved into: one that exists and the person edits."""

    if folder_id and perms.folder(folder_id) is None:
        raise HTTPException(status_code=422, detail=t("That folder does not exist."))
    if not perms.edits_folder(folder_id):
        raise HTTPException(
            status_code=403, detail=t("Only the editors of that folder add dashboards to it.")
        )
    return folder_id


@router.get("/dashboards")
def list_dashboards(rt: RuntimeDep, user: CurrentUser) -> list[dict[str, Any]]:
    rt.ensure_suite_health()
    perms = permissions(rt, user)
    return [_summary(item, perms) for item in rt.dashboards.list() if perms.sees(item)]


@router.post("/dashboards", status_code=201)
def create_dashboard(payload: DashboardPayload, rt: RuntimeDep, user: EditorUser) -> dict:
    perms = permissions(rt, user)
    _folder_open(perms, payload.folder_id)
    created = rt.dashboards.create(payload.stored(), user.username)
    rt.audit(user, "dashboard.create", created["dashboard_id"], {"name": created["name"]})
    return _summary(created, perms)


@router.get("/templates")
def list_templates(rt: RuntimeDep, user: EditorView) -> list[dict[str, Any]]:
    """What a new dashboard can start from, built from the plant's assets (read as the person).
    Nothing is saved: the editor opens with the template and saves it like any new dashboard."""

    reader = rt.user_reader(user)
    assets = guarded(lambda: reader.assets(None), service=False)
    # Each draft as a saved dashboard reads: every card with its defaults filled in.
    return [
        {**item, "draft": DashboardPayload.model_validate(item["draft"]).stored()}
        for item in templates(assets)
    ]


@router.post("/dashboards/starter", status_code=201)
def create_starters(rt: RuntimeDep, user: EditorUser) -> list[dict[str, Any]]:
    """The templates saved as dashboards, each only once (a name already in General is kept).
    Kept for scripts that seeded an installation before the New dashboard dialog."""

    reader = rt.user_reader(user)
    assets = guarded(lambda: reader.assets(None), service=False)
    taken = {item["name"] for item in rt.dashboards.list() if not item.get("folder_id")}
    created = []
    for draft in starter_dashboards(assets):
        if draft["name"] in taken:
            continue
        payload = DashboardPayload.model_validate(draft)
        item = rt.dashboards.create(payload.stored(), user.username)
        rt.audit(user, "dashboard.create", item["dashboard_id"], {"name": item["name"]})
        created.append(item)
    return created


@router.post("/start/unit-overviews")
def start_unit_overviews(body: StartIn, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    """A new plant's first step here (``[[contributes.start]]``, sent by PlantCraft once an
    import is applied): one overview dashboard for each of its units, in General, read from the
    assets as this person. A dashboard of that name in General is kept."""

    reader = rt.user_reader(user)
    assets = guarded(lambda: reader.assets(None), service=False)
    taken = {item["name"] for item in rt.dashboards.list() if not item.get("folder_id")}
    created = kept = 0
    for draft in unit_overviews(assets, body.units):
        if draft["name"] in taken:
            kept += 1
            continue
        item = rt.dashboards.create(DashboardPayload.model_validate(draft).stored(), user.username)
        rt.audit(user, "dashboard.create", item["dashboard_id"], {"name": item["name"]})
        taken.add(item["name"])
        created += 1
    summary = t(
        "{created} unit overviews were drawn in General.",
        created=created,
    )
    if kept:
        summary += " " + t("{count} were there already.", count=kept)
    counts = {"created": created, "kept": kept}
    return StartOut(summary=summary, counts=counts, open="/dash/").model_dump()


@router.get("/dashboards/{dashboard_id}")
def get_dashboard(dashboard_id: str, rt: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    found = dashboard_or_404(rt, dashboard_id, user)
    return _summary(found, permissions(rt, user))


@router.put("/dashboards/{dashboard_id}", response_model=None)
def update_dashboard(
    dashboard_id: str, payload: DashboardPayload, rt: RuntimeDep, user: EditorUser
) -> dict[str, Any] | JSONResponse:
    found = editable_or_403(rt, dashboard_id, user)
    if payload.folder_id != found.get("folder_id", ""):
        _folder_open(permissions(rt, user), payload.folder_id)
    try:
        saved = rt.dashboards.update(
            dashboard_id,
            payload.stored(),
            user.username,
            base_updated_at=payload.base_updated_at,
        )
    except Conflict as conflict:
        who = conflict.current.get("updated_by") or t("someone")
        return JSONResponse(
            {
                "detail": t(
                    "{user} saved this dashboard after you opened it. Reload to see their "
                    "changes, or save again to replace them.",
                    user=who,
                ),
                "current": conflict.current,
            },
            status_code=409,
        )
    if saved is None:
        raise HTTPException(status_code=404, detail=t("Dashboard not found."))
    details: dict[str, Any] = {"name": saved["name"]}
    if saved.get("folder_id", "") != found.get("folder_id", ""):
        details["folder_id"] = saved.get("folder_id", "")
    rt.audit(user, "dashboard.update", dashboard_id, details)
    return _summary(saved, permissions(rt, user))


@router.delete("/dashboards/{dashboard_id}", status_code=204)
def delete_dashboard(dashboard_id: str, rt: RuntimeDep, user: EditorUser) -> Response:
    found = editable_or_403(rt, dashboard_id, user)
    rt.dashboards.delete(dashboard_id, user.username)
    rt.audit(user, "dashboard.delete", dashboard_id, {"name": found["name"]})
    return Response(status_code=204)


@router.post("/dashboards/{dashboard_id}/copy", status_code=201)
def copy_dashboard(dashboard_id: str, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    found = dashboard_or_404(rt, dashboard_id, user)
    perms = permissions(rt, user)
    # The copy stays beside the original when the person edits that folder, else in General.
    folder_id = found.get("folder_id", "") if perms.edits_folder(found.get("folder_id")) else ""
    name = t("{name} (copy)", name=found["name"])[:120]
    try:
        payload = DashboardPayload.model_validate(
            {**found, "name": name, "folder_id": folder_id, "base_updated_at": None}
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=t("This dashboard cannot be copied.")) from exc
    _folder_open(perms, folder_id)
    created = rt.dashboards.create(payload.stored(), user.username)
    rt.audit(user, "dashboard.copy", created["dashboard_id"], {"from": dashboard_id})
    return _summary(created, perms)


# Versions --------------------------------------------------------------------------


@router.get("/dashboards/{dashboard_id}/versions")
def list_versions(dashboard_id: str, rt: RuntimeDep, user: EditorView) -> list[dict[str, Any]]:
    """The last saves of a dashboard, newest first (who, when, how many cards)."""

    dashboard_or_404(rt, dashboard_id, user)
    return rt.dashboards.versions(dashboard_id)


@router.get("/dashboards/{dashboard_id}/versions/{version}")
def get_version(dashboard_id: str, version: int, rt: RuntimeDep, user: EditorView) -> dict:
    dashboard_or_404(rt, dashboard_id, user)
    found = rt.dashboards.version(dashboard_id, version)
    if found is None:
        raise HTTPException(status_code=404, detail=t("Version not found."))
    return found


@router.post("/dashboards/{dashboard_id}/versions/{version}/restore")
def restore_version(dashboard_id: str, version: int, rt: RuntimeDep, user: EditorUser) -> dict:
    """Save an old version again, as a new save; the folder stays where it is now."""

    current = editable_or_403(rt, dashboard_id, user)
    found = rt.dashboards.version(dashboard_id, version)
    if found is None:
        raise HTTPException(status_code=404, detail=t("Version not found."))
    try:
        payload = DashboardPayload.model_validate(
            {**found["dashboard"], "folder_id": current.get("folder_id", "")}
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=422, detail=t("This version no longer fits the dashboard's rules.")
        ) from exc
    saved = rt.dashboards.update(dashboard_id, payload.stored(), user.username) or {}
    rt.audit(user, "dashboard.restore", dashboard_id, {"version": version})
    return _summary(saved, permissions(rt, user))


# Card data -------------------------------------------------------------------------


@router.get("/dashboards/{dashboard_id}/cards/{card_id}")
def get_card_data(
    dashboard_id: str,
    card_id: str,
    request: Request,
    rt: RuntimeDep,
    user: CurrentUser,
    context: str | None = Query(default=None, max_length=300),
    window: str | None = Query(default=None, max_length=8),
) -> dict[str, Any]:
    """One card's data; the dashboard's variables come as ``var-<name>`` (repeated for several
    values, ``$__all`` for all)."""

    dashboard = dashboard_or_404(rt, dashboard_id, user)
    return card_data(
        rt,
        dashboard,
        card_id,
        user=user,
        context=context,
        window=window,
        raw=raw_values(request.query_params),
    )


@router.get("/dashboards/{dashboard_id}/variables/{name}")
def get_variable_options(
    dashboard_id: str,
    name: str,
    rt: RuntimeDep,
    user: CurrentUser,
    parent: list[str] = Query(default_factory=list, max_length=25),
) -> list[dict[str, Any]]:
    """What a variable's picker offers (an asset variable: under the ``parent`` values)."""

    dashboard = dashboard_or_404(rt, dashboard_id, user)
    return dashboard_variable_options(rt, dashboard, name, parent, user)


class VariableOptionsBody(BaseModel):
    variable: Variable
    parent: list[str] = Field(default_factory=list, max_length=25)


@router.post("/variable-options")
def draft_variable_options(
    body: VariableOptionsBody, rt: RuntimeDep, user: EditorView
) -> list[dict[str, Any]]:
    """The options of a variable being edited (not saved yet), read with the editor's token."""

    reader = rt.user_reader(user)
    return variable_options(reader, body.variable, body.parent, False)


@router.get("/dashboards/{dashboard_id}/context")
def get_context_options(dashboard_id: str, rt: RuntimeDep, user: CurrentUser) -> list[dict]:
    return context_options(rt, dashboard_or_404(rt, dashboard_id, user), user)


@router.post("/preview")
def preview_card(body: CardPreviewBody, rt: RuntimeDep, user: EditorView) -> dict[str, Any]:
    """An unsaved card, read with the editor's own token (PlantCraft's permissions apply)."""

    reader = rt.user_reader(user)
    context = (body.context or "").strip() or None
    values, labels, texts = resolve_values(
        reader, body.variables, body.values, context=context, service=False, check=False
    )
    if body.card.kind == "diagram":
        window = card_window(body.card, values, body.window)
        return diagram_card(rt, body.card, window, reader, False, user)
    return guarded(
        lambda: read_card(
            reader, body.card, context, body.window, values=values, labels=labels, texts=texts
        ),
        service=False,
    )


# Public links ----------------------------------------------------------------------


def links_on(rt: RuntimeDep) -> None:
    if not rt.settings.public_links:
        raise HTTPException(status_code=403, detail=t("Public links are turned off here."))
    if not rt.has_service_key:
        raise HTTPException(
            status_code=503,
            detail=t(
                "Public links need View's app key: an admin creates one in PlantCraft "
                "and sets PLANTCRAFT_APP_KEY for View."
            ),
        )


def _share_allowed(rt: RuntimeDep, dashboard_id: str, user: Any) -> dict[str, Any]:
    """Public links are managed by whoever edits the dashboard; the suite's own (Suite health)
    is shared by any View editor, as before."""

    found = dashboard_or_404(rt, dashboard_id, user)
    if not found.get("builtin") and not permissions(rt, user).edits(found):
        raise HTTPException(
            status_code=403, detail=t("Only the editors of its folder share this dashboard.")
        )
    return found


@router.get("/dashboards/{dashboard_id}/shares")
def list_shares(dashboard_id: str, rt: RuntimeDep, user: EditorView) -> list[dict[str, Any]]:
    if user.demo is not None:  # a demo visit sees the dialog; its links stay the editors'
        return []
    _share_allowed(rt, dashboard_id, user)
    return rt.dashboards.shares(dashboard_id)


@router.post("/dashboards/{dashboard_id}/shares", status_code=201)
def create_share(
    dashboard_id: str, body: ShareBody, rt: RuntimeDep, user: EditorUser
) -> dict[str, Any]:
    _share_allowed(rt, dashboard_id, user)
    whole_plant(user)
    links_on(rt)
    days = link_days(body, user)
    share, token = rt.dashboards.create_share(dashboard_id, user.username, body.label, days=days)
    rt.audit(user, "share.create", dashboard_id, {"share_id": share["share_id"], "days": days})
    return {**share, "path": f"{rt.settings.root_path}/share/{token}"}


@router.get("/shares")
def every_share(rt: RuntimeDep, user: EditorUser) -> list[dict[str, Any]]:
    """Every public link that still opens something, with what it opens: an administrator's
    review of the installation's links (review decision D4)."""

    _admin(user)
    names = {item["dashboard_id"]: item["name"] for item in rt.dashboards.list()}
    names.update({item["report_id"]: item["name"] for item in rt.reports.list()})
    names.update({item["diagram_id"]: item["name"] for item in rt.diagrams.list()})
    return [
        {**share, "name": names.get(share["dashboard_id"], share["dashboard_id"])}
        for share in rt.dashboards.active_shares()
    ]


@router.delete("/shares/{share_id}", status_code=204)
def revoke_any_share(share_id: str, rt: RuntimeDep, user: EditorUser) -> Response:
    _admin(user)
    found = rt.dashboards.share(share_id)
    if found is None or not rt.dashboards.revoke_share(
        found["dashboard_id"], share_id, user.username, found["target"]
    ):
        raise HTTPException(status_code=404, detail=t("Link not found."))
    rt.audit(user, "share.revoke", found["dashboard_id"], {"share_id": share_id})
    return Response(status_code=204)


def _admin(user: Any) -> None:
    if getattr(user, "level", "") != "admin":
        raise HTTPException(status_code=403, detail=t("Only an administrator sees every link."))


@router.delete("/dashboards/{dashboard_id}/shares/{share_id}", status_code=204)
def revoke_share(dashboard_id: str, share_id: str, rt: RuntimeDep, user: EditorUser) -> Response:
    _share_allowed(rt, dashboard_id, user)
    if not rt.dashboards.revoke_share(dashboard_id, share_id, user.username):
        raise HTTPException(status_code=404, detail=t("Link not found."))
    rt.audit(user, "share.revoke", dashboard_id, {"share_id": share_id})
    return Response(status_code=204)


@router.get("/asset-dashboards")
def asset_dashboards(
    rt: RuntimeDep, user: CurrentUser, asset: str = Query(min_length=1, max_length=200)
) -> dict[str, Any]:
    """The dashboards that show one asset: those picking assets of its kind, and those whose
    cards name it. Backs the suite's uniform ``assets/<id>`` page; the asset is read with the
    person's token, so PlantCraft decides whether they may see it."""

    reader = rt.user_reader(user)
    found = guarded(lambda: reader.asset(asset), service=False)
    kind = found.get("kind")
    perms = permissions(rt, user)
    shown = []
    for item in rt.dashboards.list():
        if not perms.sees(item):
            continue
        names_it = any(
            entry.get("asset_id") == asset
            for card in item.get("cards") or []
            for entry in card.get("items") or []
        )
        follows_kind = bool(kind) and any(
            variable.get("type") == "asset" and variable.get("asset_kind") == kind
            for variable in item.get("variables") or []
            if isinstance(variable, dict)
        )
        if names_it or follows_kind:
            shown.append(
                {
                    "dashboard_id": item["dashboard_id"],
                    "name": item["name"],
                    "description": item.get("description") or "",
                    "picks_asset": follows_kind,
                }
            )
    return {
        "asset": {
            "id": found.get("id") or asset,
            "name": found.get("name"),
            "kind": kind,
            # For the asset panel of a process display: what it is and what it measures.
            "kind_label": (found.get("attributes") or {}).get("kind_label") or "",
            "description": (found.get("attributes") or {}).get("description") or "",
            "signals": {
                str(role): str(signal)
                for role, signal in (found.get("signals") or {}).items()
                if signal
            },
        },
        "dashboards": shown,
    }
