"""The plant as alarms see it: assets and signals to pick (read as the editor), and the alarms
of one asset (the suite's ``assets/<id>`` page)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from plantcraft_sdk.server.picker import signal_choices

from alarmcraft.api.deps import CurrentUser, EditorView, RuntimeDep, guarded
from alarmcraft.api.routers.alarms import summary
from alarmcraft.api.scope import seen
from alarmcraft.i18n import t

router = APIRouter(prefix="/api", tags=["plant"])
MAX_ASSETS = 500


@router.get("/assets")
def list_assets(
    rt: RuntimeDep,
    user: EditorView,
    kind: str | None = Query(default=None, max_length=60),
    q: str = Query(default="", max_length=120),
) -> list[dict[str, Any]]:
    client = rt.user_client(user)
    everything = guarded(lambda: client.assets(), service=False)
    names = {item.get("id"): item.get("name") or item.get("id") for item in everything}
    query = q.strip().lower()
    found = []
    for item in everything:
        if kind and item.get("kind") != kind:
            continue
        text = f"{item.get('id')} {item.get('name')} {names.get(item.get('parent_id')) or ''}"
        if query and query not in text.lower():
            continue
        found.append(
            {
                "id": item.get("id"),
                "name": item.get("name") or item.get("id"),
                "kind": item.get("kind"),
                "parent": names.get(item.get("parent_id")) if item.get("parent_id") else None,
                "signals": item.get("signals") or {},
            }
        )
    found.sort(key=lambda item: (str(item["parent"] or ""), str(item["name"])))
    return found[:MAX_ASSETS]


@router.get("/signals")
def list_signals(
    rt: RuntimeDep,
    user: EditorView,
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=30, ge=1, le=200),
) -> list[dict[str, Any]]:
    client = rt.user_client(user)
    found = guarded(lambda: client.signals(q.strip() or None), service=False)
    return signal_choices(found, q, limit=limit, numbers_only=True)


@router.get("/explore")
def explore(
    rt: RuntimeDep,
    user: CurrentUser,
    asset: str | None = Query(default=None, max_length=200),
    q: str = Query(default="", max_length=120),
) -> dict[str, Any]:
    """The suite's Explorer (PlantCraft ``GET /api/v1/explore``), read as the person: the plant
    as folders, each asset with its signals, the series apps computed and the events about it."""

    client = rt.user_client(user)
    return guarded(lambda: client.explore(asset, q=q), service=False)


@router.get("/value")
def last_value(
    rt: RuntimeDep, user: CurrentUser, signal: str = Query(max_length=320)
) -> dict[str, Any]:
    """A value's last sample (the Explorer's preview), read as the person."""

    client = rt.user_client(user)
    found = guarded(lambda: client.value(signal, window="7d"), service=False)
    return {"value": found.get("value"), "at": found.get("at"), "unit": found.get("unit")}


@router.get("/executions")
def executions(rt: RuntimeDep, _user: CurrentUser) -> list[dict[str, Any]]:
    """The suite's executions a rule may cover (``<app>:<id>``), with how many assets each runs."""

    return [
        {
            "id": f"{item.get('app')}:{item.get('id')}",
            "app": item.get("app"),
            "name": item.get("name") or item.get("id"),
            "cadence": item.get("cadence") or "",
            "assets": sum(1 for ref in item.get("subjects") or [] if str(ref).startswith("asset:")),
        }
        for item in rt.executions.list()
        if item.get("app") != "alarmcraft"
    ]


@router.get("/asset-types")
def asset_types(rt: RuntimeDep, user: CurrentUser) -> list[dict[str, Any]]:
    """The asset types a rule may cover (every pump, every loop)."""

    client = rt.user_client(user)
    found = guarded(lambda: client.asset_types(), service=False)
    return [{"id": item.get("id"), "name": item.get("name") or item.get("id")} for item in found]


@router.get("/asset-alarms")
def asset_alarms(
    rt: RuntimeDep, user: CurrentUser, asset: str = Query(max_length=300)
) -> dict[str, Any]:
    """The suite's page of one asset: the alarms configured on it."""

    try:
        reader, service = rt.reader(user)
    except LookupError:
        reader, service = rt.user_reader(user), False
    try:
        found = guarded(lambda: reader.client.asset(asset), service=service)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(404, t("Asset not found.")) from exc
        raise
    alarms = [
        summary(rt, alarm)
        for alarm in seen(rt.asset_scope(user), rt.alarms.list())
        if alarm.get("asset_id") == asset
    ]
    return {
        "asset": {"id": found.get("id"), "name": found.get("name"), "kind": found.get("kind")},
        "alarms": alarms,
    }
