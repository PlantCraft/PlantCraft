"""HTTP routes: industrial data (sources, connection, signals, history).

With HistCraft as the data layer (``HISTCRAFT_URL``), sources live in HistCraft: these routes
check the person, then forward through ``rt.datalayer`` (``platform/datalayer/histcraft.py``),
so PlantCraft opens no connection to a plant source. Without it, nothing changes.
"""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from processcraft.api.deps import AdminUser, CurrentUser, Runtime
from processcraft.i18n import t
from processcraft.industrial_data.registry import EDITABLE, PRIMARY, source_id_for
from processcraft.platform.datalayer import DataLayerError
from processcraft.platform.datalayer.histcraft import BROWSE_MAX

router = APIRouter(prefix="/api/data")

MAX_HISTORY_HOURS = 24 * 31
MAX_TAGS = 12
MAX_SELECTION = 2000


class SourcePayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: Literal["opcua", "pi_web_api", "csv"]
    settings: dict[str, Any] = Field(default_factory=dict)
    # None keeps the stored password; "" clears it.
    password: str | None = Field(default=None, max_length=500)


class SourceTest(BaseModel):
    type: Literal["opcua", "pi_web_api", "csv"]
    settings: dict[str, Any] = Field(default_factory=dict)
    password: str | None = Field(default=None, max_length=500)
    source_id: str | None = Field(default=None, max_length=64)


class SignalSelection(BaseModel):
    tags: list[str] = Field(min_length=1, max_length=MAX_SELECTION)
    monitored: bool = True


class SignalBinding(BaseModel):
    tags: list[str] = Field(min_length=1, max_length=MAX_SELECTION)
    asset_id: str = Field(min_length=1, max_length=128)
    role: str = Field(default="", max_length=40)


def _registry(rt: Any) -> Any:
    return rt.platform.sources


def _remote(rt: Any) -> Any:
    """The data layer when it keeps the sources (HistCraft), else None."""

    layer = rt.datalayer
    return layer if layer.manages_sources else None


def _forward(call: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return call(*args, **kwargs)
    except DataLayerError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc


def _remote_body(rt: Any, type: str, settings: dict[str, Any], password: str | None) -> dict:
    """Source settings checked as PlantCraft checks its own (422 worded for people)."""

    try:
        config = _registry(rt).validate(type, settings, password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return config.model_dump(
        mode="json", include=set(EDITABLE[type]) | {"timezone", "history_cache_hours"}
    )


def _require_source(rt: Any, source_id: str) -> dict[str, Any]:
    remote = _remote(rt)
    if remote is not None:
        found = _forward(remote.source, source_id)
        if found is None:
            raise HTTPException(status_code=404, detail=t("Source not found."))
        return found
    item = _registry(rt).get(source_id)
    if item is None:
        raise HTTPException(status_code=404, detail=t("Source not found."))
    return item


def _data(rt: Any, source_id: str) -> Any:
    _require_source(rt, source_id)
    return _registry(rt).data(source_id)


def _source_signals(rt: Any, source_id: str, refresh: bool = False) -> list[dict[str, Any]]:
    try:
        return _data(rt, source_id).signals(refresh=refresh)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=t("Failed to browse the source: {error}", error=exc)
        ) from exc


def source_variables(rt: Any, source_id: str) -> list[dict[str, Any]]:
    """Every variable a source lists (its browse): ``{tag, name, description, unit}``."""

    remote = _remote(rt)
    if remote is not None:
        _require_source(rt, source_id)
        return _forward(remote.browse_source, source_id, limit=BROWSE_MAX)["items"]
    return _source_signals(rt, source_id)


# Sources ----------------------------------------------------------------------


@router.get("/sources")
def list_sources(_user: CurrentUser, rt: Runtime) -> list[dict[str, Any]]:
    """The scenario's source first, then the ones added here. Passwords never leave the server."""

    remote = _remote(rt)
    if remote is not None:
        return _forward(remote.sources)
    return _registry(rt).list()


@router.get("/sources/{source_id}/status")
def source_status(
    source_id: str, _user: CurrentUser, rt: Runtime, refresh: bool = False
) -> dict[str, Any]:
    remote = _remote(rt)
    if remote is not None:
        _require_source(rt, source_id)
        return _forward(remote.source_status, source_id)
    return _data(rt, source_id).status(refresh=refresh)


@router.post("/sources/test")
def test_source(payload: SourceTest, _user: AdminUser, rt: Runtime) -> dict[str, Any]:
    """Try the connection settings before saving them."""

    remote = _remote(rt)
    if remote is not None:
        settings = _remote_body(rt, payload.type, payload.settings, payload.password)
        return _forward(
            remote.test_source,
            payload.source_id,
            type=payload.type,
            settings=settings,
            password=payload.password,
        )
    return _registry(rt).test(payload.type, payload.settings, payload.password, payload.source_id)


@router.post("/sources", status_code=201)
def create_source(payload: SourcePayload, user: AdminUser, rt: Runtime) -> dict[str, Any]:
    registry = _registry(rt)
    source_id = source_id_for(payload.name)
    remote = _remote(rt)
    if remote is not None:
        settings = _remote_body(rt, payload.type, payload.settings, payload.password)
        return _forward(
            remote.save_source,
            source_id,
            name=payload.name,
            type=payload.type,
            settings=settings,
            password=payload.password or None,
            create=True,
        )
    if registry.known(source_id):
        raise HTTPException(status_code=409, detail=t("A source with this name already exists."))
    try:
        return registry.save(
            source_id,
            name=payload.name,
            type=payload.type,
            settings=payload.settings,
            password=payload.password or None,
            actor=user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/sources/{source_id}")
def update_source(
    source_id: str, payload: SourcePayload, user: AdminUser, rt: Runtime
) -> dict[str, Any]:
    if source_id == PRIMARY:
        raise HTTPException(
            status_code=422, detail=t("The scenario's source is set in the scenario file.")
        )
    _require_source(rt, source_id)
    remote = _remote(rt)
    if remote is not None:
        settings = _remote_body(rt, payload.type, payload.settings, payload.password)
        return _forward(
            remote.save_source,
            source_id,
            name=payload.name,
            type=payload.type,
            settings=settings,
            password=payload.password,
            create=False,
        )
    try:
        return _registry(rt).save(
            source_id,
            name=payload.name,
            type=payload.type,
            settings=payload.settings,
            password=payload.password,
            actor=user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/sources/{source_id}")
def delete_source(source_id: str, _user: AdminUser, rt: Runtime) -> dict[str, Any]:
    if source_id == PRIMARY:
        raise HTTPException(status_code=422, detail=t("The scenario's source cannot be removed."))
    _require_source(rt, source_id)
    remote = _remote(rt)
    if remote is not None:
        return _forward(remote.remove_source, source_id)
    removed = _registry(rt).remove(source_id)
    rt.sync_assets()
    return {"removed": source_id, "signals": removed}


# Signals of one source ----------------------------------------------------------


@router.get("/sources/{source_id}/signals")
def source_signals(
    source_id: str,
    _user: CurrentUser,
    rt: Runtime,
    q: str = Query(default="", max_length=200),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    refresh: bool = False,
) -> dict[str, Any]:
    """The source's signals as one flat list, with the asset each is bound to and whether the platform uses it."""

    remote = _remote(rt)
    if remote is not None:
        _require_source(rt, source_id)
        page = _forward(remote.browse_source, source_id, q=q, offset=offset, limit=limit)
        bound = rt.workspace.assets.signal_assets([item["tag"] for item in page["items"]])
        for item in page["items"]:
            item["assets"] = bound.get(item["tag"], [])
        return page
    items = _source_signals(rt, source_id, refresh)
    needle = q.strip().lower()
    if needle:
        items = [
            item
            for item in items
            if needle
            in f"{item['tag']} {item['name']} {item['asset']} {item['description']}".lower()
        ]
    page = items[offset : offset + limit]
    registry = _registry(rt)
    routes = registry.routes()
    used = _platform_tags(rt)
    bound = rt.workspace.assets.signal_assets([item["tag"] for item in page])
    rows = []
    for item in page:
        route = routes.get(item["tag"])
        owner = route["source_id"] if route and registry.known(route["source_id"]) else PRIMARY
        rows.append(
            {
                **item,
                "path": item["asset"],
                "assets": bound.get(item["tag"], []),
                "monitored": owner == source_id and item["tag"] in used,
                "read_from": owner,
            }
        )
    return {"items": rows, "total": len(items), "offset": offset, "limit": limit}


def _platform_tags(rt: Any) -> set[str]:
    """Tags the platform reads: the scenario's, the ones people added, and the loops' signals."""

    return (
        set(rt.scenario.source.tags)
        | set(_registry(rt).monitored_tags())
        | set(rt.workspace.assets.signal_roles("loop"))
    )


def _selected(rt: Any, source_id: str, tags: list[str]) -> list[dict[str, Any]]:
    catalog = {item["tag"]: item for item in _source_signals(rt, source_id)}
    missing = [tag for tag in tags if tag not in catalog]
    if (
        missing
        and source_id != PRIMARY
        and _registry(rt).data(source_id).config.type != "pi_web_api"
    ):
        raise HTTPException(
            status_code=422,
            detail=t("Tags not in the source: {tags}.", tags=", ".join(missing[:5])),
        )
    return [catalog.get(tag, {"tag": tag}) for tag in tags]


@router.post("/sources/{source_id}/signals/use")
def use_signals(
    source_id: str, payload: SignalSelection, _user: AdminUser, rt: Runtime
) -> dict[str, Any]:
    """Add the signals to the platform (read from this source and followed by data quality), or take them out."""

    remote = _remote(rt)
    if remote is not None:
        _require_source(rt, source_id)
        if not payload.monitored:  # HistCraft stops collecting them and keeps their history
            stopped = _forward(remote.stop_signals, source_id, payload.tags)
            return {"updated": stopped["updated"], "kept_by_scenario": []}
        answer = _forward(remote.add_signals, source_id, payload.tags)
        return {"updated": len(answer.get("added") or []), "kept_by_scenario": []}
    _require_source(rt, source_id)
    registry = _registry(rt)
    signals = _selected(rt, source_id, payload.tags)
    count = registry.use(source_id, signals, monitored=payload.monitored)
    kept = (
        [tag for tag in payload.tags if tag in rt.scenario.source.tags]
        if not payload.monitored
        else []
    )
    rt.sync_assets()
    return {"updated": count, "kept_by_scenario": kept}


@router.post("/sources/{source_id}/signals/bind")
def bind_signals(
    source_id: str, payload: SignalBinding, _user: AdminUser, rt: Runtime
) -> dict[str, Any]:
    """Place the signals on an asset with a role; they are read from this source from then on."""

    _require_source(rt, source_id)
    if rt.workspace.assets.get(payload.asset_id) is None:
        raise HTTPException(status_code=404, detail=t("Asset not found."))
    if _remote(rt) is not None:
        # HistCraft's source: the binding records it; nothing is routed here.
        rt.workspace.assets.bind_signals(
            payload.asset_id,
            [
                {"signal_id": tag, "role": payload.role, "source_id": source_id}
                for tag in payload.tags
            ],
        )
        rt.sync_assets()
        return {"bound": len(payload.tags), "asset_id": payload.asset_id}
    signals = _selected(rt, source_id, payload.tags)
    registry = _registry(rt)
    if source_id != PRIMARY:
        registry.use(source_id, signals, monitored=None)
    rt.workspace.assets.bind_signals(
        payload.asset_id,
        [
            {
                "signal_id": item["tag"],
                "role": payload.role,
                "name": item.get("name") or "",
                "unit": item.get("unit") or "",
            }
            for item in signals
        ],
    )
    rt.sync_assets()
    return {"bound": len(signals), "asset_id": payload.asset_id}


# History ------------------------------------------------------------------------


@router.get("/history")
def history(
    _user: CurrentUser,
    rt: Runtime,
    tag: list[str] = Query(default_factory=list),
    hours: float = Query(default=48, gt=0, le=MAX_HISTORY_HOURS),
    end: str | None = None,
    max_points: int = Query(default=1500, ge=50, le=20000),
    source: str | None = Query(default=None, max_length=64),
) -> dict[str, Any]:
    """Samples of up to 12 tags; ``source`` reads from that source even before a tag is used."""

    if not tag:
        raise HTTPException(status_code=422, detail=t("Enter at least one tag."))
    if len(tag) > MAX_TAGS:
        raise HTTPException(
            status_code=422, detail=t("Select at most {count} tags.", count=MAX_TAGS)
        )
    timezone = rt.scenario.source.timezone
    remote = _remote(rt)
    if remote is not None:
        try:
            end_stamp = pd.Timestamp(end) if end else pd.Timestamp.now(tz=timezone)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=t("Invalid end date.")) from exc
        if end_stamp.tzinfo is not None:
            end_stamp = end_stamp.tz_convert(timezone).tz_localize(None)
        return _forward(
            remote.history,
            tag,
            start=end_stamp - pd.Timedelta(hours=hours),
            end=end_stamp,
            sample_seconds=rt.scenario.analysis.resample_seconds,
            max_points=max_points,
            source=source if source and source != PRIMARY else None,
        )
    data = rt.data if not source or source == PRIMARY else _data(rt, source)
    try:
        end_stamp = pd.Timestamp(end) if end else pd.Timestamp.now(tz=timezone)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=t("Invalid end date.")) from exc
    if end_stamp.tzinfo is not None:
        end_stamp = end_stamp.tz_convert(timezone).tz_localize(None)
    if data.config.type == "csv" and not end:
        # Recorded files end in the past: anchor the window on their last sample.
        try:
            frame = data.source.read_window(1, rt.scenario.analysis.resample_seconds)
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail=t("Failed to read history: {error}", error=exc)
            ) from exc
        if not frame.empty:
            end_stamp = frame.index.max()
    start_stamp = end_stamp - pd.Timedelta(hours=hours)
    try:
        return rt.datalayer.history(
            tag,
            start=start_stamp,
            end=end_stamp,
            sample_seconds=rt.scenario.analysis.resample_seconds,
            max_points=max_points,
            source=source,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=t("Failed to read history: {error}", error=exc)
        ) from exc
