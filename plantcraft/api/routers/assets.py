"""HTTP routes: the plant's asset tree, signal values by aggregation, and references.

The interface of PlantCraft reads assets and values here; the apps of the
suite read the same data through API v1 (``routers/v1.py``).
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from plantcraft.actions import OPEN_STATUSES
from plantcraft.api.deps import AdminUser, CurrentUser, Runtime, Scope, action_visibility
from plantcraft.api.routers.asset_model import relations_view
from plantcraft.assets import asset_id_for
from plantcraft.i18n import t
from plantcraft.platform.datalayer import DataLayerError
from plantcraft_sdk.links import now_text, stale_view
from plantcraft_sdk.refs import split_signal_id

router = APIRouter()

WINDOW = re.compile(r"^(?P<amount>\d{1,4})(?P<unit>[mhd])$")
WINDOW_UNITS = {"m": "minutes", "h": "hours", "d": "days"}
MAX_WINDOW = pd.Timedelta(days=31)
Aggregation = Literal["last", "mean", "min", "max", "first", "delta"]


class AssetPayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(default="equipment", max_length=64)
    parent_id: str | None = Field(default=None, max_length=128)
    description: str = Field(default="", max_length=600)
    # The tag as people write it (FIC-2001); without it the id comes from the name.
    asset_id: str | None = Field(default=None, max_length=128)


class AssetPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=600)
    parent_id: str | None = Field(default=None, max_length=128)
    move: bool = False


class AssetKindPayload(BaseModel):
    label: str = Field(min_length=1, max_length=60)


def _window(text: str) -> pd.Timedelta:
    match = WINDOW.match(text.strip())
    if match is None:
        raise HTTPException(status_code=422, detail=t("Invalid window: use 15m, 1h, 24h or 7d."))
    window = pd.Timedelta(**{WINDOW_UNITS[match["unit"]]: int(match["amount"])})
    if window <= pd.Timedelta(0) or window > MAX_WINDOW:
        raise HTTPException(status_code=422, detail=t("The window goes from 1 minute to 31 days."))
    return window


def _require_asset(rt: Any, asset_id: str, scope: Any = None) -> dict[str, Any]:
    """The asset, or 404: also for one out of the person's asset scope (docs/asset-scope.md)."""

    asset = rt.workspace.assets.get(asset_id)
    if asset is None or (scope is not None and not scope.asset(asset_id)):
        raise HTTPException(status_code=404, detail=t("Asset not found."))
    return asset


# The tree ---------------------------------------------------------------------


@router.get("/api/assets")
def assets(
    _user: CurrentUser,
    rt: Runtime,
    scope: Scope,
    q: Annotated[str | None, Query(max_length=120)] = None,
    parent: Annotated[str | None, Query(max_length=128)] = None,
    kind: Annotated[list[str] | None, Query()] = None,
    type: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=20000)] = 5000,
) -> dict[str, Any]:
    """The tree as a flat list (``parent_id`` links), a search, or one level of it.

    ``type`` keeps the assets of a type and of its subtypes. Each item carries its
    ``attributes`` (the record, by key) for the table of one type.
    """

    store = rt.workspace.assets
    if q:
        items = store.search(q, limit=min(limit, 200))
    elif parent is not None:
        items = store.children(parent or None)
    else:
        items = store.list()
    if kind:
        items = [item for item in items if item["kind"] in kind]
    if type is not None:
        wanted = store.types.subtypes(type)
        items = [item for item in items if item["kind"] in wanted]
    items = scope.items(items)
    values = store.all_attributes()
    items = [{**item, "attributes": values.get(item["asset_id"], {})} for item in items]
    counts = store.counts()
    if not scope.everything:
        counts = {}
        for item in scope.items(store.list()):
            counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    return {
        "root_id": rt.platform.root_asset_id if scope.asset(rt.platform.root_asset_id) else None,
        "kinds": [{**item, "count": counts.get(item["kind"], 0)} for item in store.kinds()],
        "total": len(items),
        "items": items[:limit],
    }


@router.get("/api/assets/{asset_id}")
def asset_detail(asset_id: str, user: CurrentUser, rt: Runtime, scope: Scope) -> dict[str, Any]:
    """One asset: where it sits, what is under it, its signals and history."""

    store = rt.workspace.assets
    asset = scope.items([_require_asset(rt, asset_id, scope)])[0]
    try:
        timeline = rt.events_for(user, rt.workspace.events.timeline(f"asset:{asset_id}", limit=30))
    except ValueError:  # an id that is not a valid reference has no timeline
        timeline = []
    signals = store.signals(asset_id)
    # One signal may be on several assets (a loop's PV is its transmitter's measurement too):
    # each signal says where else it is used.
    uses = store.signal_assets([item["signal_id"] for item in signals])
    signals = [
        {
            **item,
            "used_in": [
                {key: other[key] for key in ("asset_id", "name", "kind", "role")}
                for other in uses.get(item["signal_id"], [])
                if other["asset_id"] != asset_id and scope.asset(other["asset_id"])
            ],
        }
        for item in signals
    ]
    return {
        "asset": asset,
        "type": store.types.resolved(asset["kind"]),
        "type_path": store.types.path(asset["kind"]),
        "attributes": store.attributes(asset_id),
        "missing": store.missing(asset_id),
        "relations": relations_view(rt, asset_id, scope),
        "path": [item for item in store.path(asset_id) if scope.asset(item["asset_id"])],
        "children": store.children(asset_id),
        "signals": signals,
        "timeline": timeline,
    }


@router.get("/api/assets/{asset_id}/contents")
def asset_contents(
    asset_id: str,
    _user: CurrentUser,
    rt: Runtime,
    scope: Scope,
    kind: Annotated[list[str] | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 300,
) -> dict[str, Any]:
    """Everything under an asset, at any depth, with where it sits.

    ``kinds`` sums the whole subtree (before the filters), so a unit's page can
    say how many areas, equipment and loops it has.
    """

    store = rt.workspace.assets
    _require_asset(rt, asset_id, scope)
    items = {item["asset_id"]: item for item in store.list()}
    inside = store.descendants(asset_id) - {asset_id}
    signal_counts = store.signal_counts()

    def where(item: dict[str, Any]) -> str:
        names, parent = [], item["parent_id"]
        while parent and parent != asset_id and parent in items:
            names.append(items[parent]["name"])
            parent = items[parent]["parent_id"]
        return " › ".join(reversed(names))

    kinds: dict[str, int] = {}
    rows = []
    needle = (q or "").strip().lower()
    for item_id in inside:
        item = items[item_id]
        kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
        if kind and item["kind"] not in kind:
            continue
        if needle and needle not in f"{item_id} {item['name']} {item['description']}".lower():
            continue
        rows.append({**item, "where": where(item), "signals": signal_counts.get(item_id, 0)})
    # Deepest first would bury units under loops: keep the tree order, then the name.
    rows.sort(
        key=lambda row: (store.depth(row["kind"]), row["where"], row["position"], row["name"])
    )
    return {"kinds": kinds, "total": len(rows), "items": rows[:limit]}


# The worst first: what needs someone comes to the top of an asset's situation.
STATUS_ORDER = {"alarm": 0, "warning": 1, "unknown": 2, "ok": 3}
# A unit's situation also gathers what the apps said about the assets inside it, up to this many.
SITUATION_INSIDE = 400


@router.get("/api/assets/{asset_id}/situation")
def asset_situation(
    asset_id: str,
    user: CurrentUser,
    rt: Runtime,
    inside: bool = True,
) -> dict[str, Any]:
    """Everything the suite's apps say about one asset, on one page: the
    results they published about it, its signals and (with ``inside``) the assets inside it,
    worst first and grouped by app (alarms, Link's diagnoses, models...); the latest events;
    the runs that covered it; the open actions about it."""

    store = rt.workspace.assets
    asset = _require_asset(rt, asset_id)
    names = {item["asset_id"]: item["name"] for item in store.list()}
    signals = store.signals(asset_id)
    subjects: dict[str, dict[str, Any]] = {
        f"asset:{asset_id}": {
            "title": asset["name"],
            "kind": "asset",
            "href": f"/assets/{asset_id}",
        }
    }
    for item in signals:
        subjects[f"signal:{item['signal_id']}"] = {
            "title": item.get("role_name") or item.get("role") or item["signal_id"],
            "detail": item["signal_id"],
            "kind": "signal",
            "href": f"/assets/{asset_id}?tab=signals",
        }
    descendants = sorted(store.descendants(asset_id) - {asset_id}) if inside else []
    for other in descendants[:SITUATION_INSIDE]:
        subjects[f"asset:{other}"] = {
            "title": names.get(other, other),
            "detail": other if names.get(other, other) != other else None,
            "kind": "inside",
            "href": f"/assets/{other}",
        }
    now = now_text()
    readable = rt.apps_for(user)
    rows = [
        stale_view(row, now)
        for row in rt.workspace.results.results(subjects=list(subjects), apps=readable)
    ]
    apps: dict[str, dict[str, Any]] = {}
    for row in rows:
        about = subjects.get(row["subject"], {"title": row["subject"], "kind": "other"})
        detail = row.get("detail") or {}
        url = detail.get("url") if isinstance(detail, dict) else None
        entry = apps.setdefault(
            row["app"], {"app": row["app"], "status": "ok", "counts": {}, "results": []}
        )
        entry["counts"][row["status"]] = entry["counts"].get(row["status"], 0) + 1
        if STATUS_ORDER.get(row["status"], 3) < STATUS_ORDER.get(entry["status"], 3):
            entry["status"] = row["status"]
        entry["results"].append(
            {
                "subject": row["subject"],
                "about": about,
                "kind": row["kind"],
                "status": row["status"],
                "score": row["score"],
                "summary": row["summary"],
                "at": row["at"],
                "stale": row["stale"],
                "url": url
                if isinstance(url, str) and url.startswith(("/", "http://", "https://"))
                else None,
            }
        )
    for entry in apps.values():
        entry["results"].sort(
            key=lambda item: (
                STATUS_ORDER.get(item["status"], 3),
                {"asset": 0, "signal": 1}.get(item["about"]["kind"], 2),
                item["score"] if item["score"] is not None else 101,
                item["about"]["title"],
            )
        )
    groups = sorted(
        apps.values(), key=lambda item: (STATUS_ORDER.get(item["status"], 3), item["app"])
    )
    worst = groups[0]["status"] if groups else None

    # The latest events about the asset or one of its signals, newest first.
    events: dict[int, dict[str, Any]] = {}
    for ref in [f"asset:{asset_id}", *(f"signal:{item['signal_id']}" for item in signals[:40])]:
        try:
            for event in rt.events_for(user, rt.workspace.events.timeline(ref, limit=15)):
                events[event["event_id"]] = event
        except ValueError:  # an id that is not a valid reference has no timeline
            continue
    latest = sorted(events.values(), key=lambda event: event["event_id"], reverse=True)[:20]

    runs = rt.workspace.results.runs(subject=f"asset:{asset_id}", limit=8, apps=readable)
    actions = rt.workspace.actions.list(
        statuses=list(OPEN_STATUSES),
        ref=f"asset:{asset_id}",
        visible=action_visibility(rt, user),
        limit=20,
    )
    return {
        "asset_id": asset_id,
        "status": worst,
        "counts": {
            status: sum(group["counts"].get(status, 0) for group in groups)
            for status in STATUS_ORDER
        },
        "inside": {"included": min(len(descendants), SITUATION_INSIDE), "total": len(descendants)},
        "apps": groups,
        "events": latest,
        "runs": runs,
        "actions": [
            {
                key: item.get(key)
                for key in ("action_id", "title", "status", "priority", "owner", "due_at")
            }
            for item in actions
        ],
    }


@router.get("/api/assets/{asset_id}/signals")
def asset_signals(
    asset_id: str, _user: CurrentUser, rt: Runtime, scope: Scope, deep: bool = False
) -> list[dict[str, Any]]:
    """The asset's signals by role; ``deep`` adds those of everything under it."""

    store = rt.workspace.assets
    _require_asset(rt, asset_id, scope)
    if not deep:
        return [{**item, "asset_id": asset_id} for item in store.signals(asset_id)]
    found: dict[str, dict[str, Any]] = {}
    for item_id in [asset_id, *sorted(store.descendants(asset_id) - {asset_id})]:
        for signal in store.signals(item_id):
            found.setdefault(signal["signal_id"], {**signal, "asset_id": item_id})
    return list(found.values())


@router.post("/api/assets", status_code=201)
def create_asset(payload: AssetPayload, _user: AdminUser, rt: Runtime) -> dict[str, Any]:
    """A hand-made asset (a unit, an area, an equipment); a later sync never overwrites it."""

    store = rt.workspace.assets
    if not store.is_kind(payload.kind):
        raise HTTPException(status_code=422, detail=t("Unknown asset type."))
    parent = payload.parent_id or rt.platform.root_asset_id
    _require_asset(rt, parent)
    asset_id = (payload.asset_id or "").strip() or asset_id_for(payload.name)
    if any(char.isspace() for char in asset_id):
        raise HTTPException(
            status_code=422,
            detail=t("The asset_id '{asset}' cannot have spaces.", asset=asset_id),
        )
    if store.get(asset_id) is not None:
        raise HTTPException(status_code=409, detail=t("An asset with this name already exists."))
    return store.save(
        asset_id,
        name=payload.name,
        kind=payload.kind,
        parent_id=parent,
        description=payload.description,
    )


@router.patch("/api/assets/{asset_id}")
def update_asset(
    asset_id: str, payload: AssetPatch, _user: AdminUser, rt: Runtime
) -> dict[str, Any]:
    store = rt.workspace.assets
    asset = _require_asset(rt, asset_id)
    if payload.move:
        if payload.parent_id is not None:
            _require_asset(rt, payload.parent_id)
        try:
            asset = store.move(asset_id, payload.parent_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload.kind is not None and not store.is_kind(payload.kind):
        raise HTTPException(status_code=422, detail=t("Unknown asset type."))
    if payload.name is not None or payload.description is not None or payload.kind is not None:
        asset = store.save(
            asset_id,
            name=payload.name if payload.name is not None else asset["name"],
            kind=payload.kind or asset["kind"],
            parent_id=asset["parent_id"],
            description=payload.description
            if payload.description is not None
            else asset["description"],
            origin="manual",
            position=asset["position"],
        )
    return asset


@router.delete("/api/assets/{asset_id}", status_code=204)
def delete_asset(asset_id: str, _user: AdminUser, rt: Runtime) -> None:
    asset = _require_asset(rt, asset_id)
    if asset_id == rt.platform.root_asset_id:
        raise HTTPException(
            status_code=422, detail=t("The site is the root of the tree and cannot be removed.")
        )
    if asset["origin"] not in {"manual", "map"}:
        raise HTTPException(
            status_code=422,
            detail=t(
                "This asset comes from the scenario file; it disappears on its own when the file stops listing it."
            ),
        )
    rt.workspace.assets.delete(asset_id)


@router.post("/api/asset-kinds", status_code=201)
def create_asset_kind(payload: AssetKindPayload, _user: AdminUser, rt: Runtime) -> dict[str, Any]:
    """A kind of asset the plant needs beyond the built-in ones (controller, compressor...)."""

    try:
        return rt.workspace.assets.add_kind(payload.label)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/api/asset-kinds/{kind}", status_code=204)
def delete_asset_kind(kind: str, _user: AdminUser, rt: Runtime) -> None:
    try:
        rt.workspace.assets.remove_kind(kind)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# Signal values ----------------------------------------------------------------


def _tag(rt: Any, given: str) -> str:
    """The tag of an API v1 signal id (``scenario:FIC-101.PV``); a tag stays as it is."""

    source_id, tag = split_signal_id(given)
    if rt.datalayer.manages_sources:
        return given  # HistCraft reads the id as given
    if source_id is not None and rt.platform.sources.source_of(tag) == source_id:
        return tag
    return given


def _require_signal(scope: Any, given: str) -> None:
    """404 for a signal out of the person's asset scope, as for one nobody knows."""

    if not scope.signal(given):
        raise HTTPException(status_code=404, detail=t("Signal not found."))


def _read(
    rt: Any, tag: str, window: pd.Timedelta, max_points: int
) -> tuple[pd.Timestamp, pd.Timestamp, list]:
    end = rt.platform.data_end()
    start = end - window
    try:
        history = rt.datalayer.history(
            [tag],
            start=start,
            end=end,
            sample_seconds=rt.scenario.analysis.resample_seconds,
            max_points=max_points,
        )
    except DataLayerError as exc:  # HistCraft: 502, or 504 when it did not answer in time
        raise HTTPException(
            status_code=exc.status if exc.status >= 500 else 502,
            detail=t("Failed to read the signal: {error}", error=exc.detail),
        ) from exc
    except Exception as exc:  # the historian may be offline
        raise HTTPException(
            status_code=502, detail=t("Failed to read the signal: {error}", error=exc)
        ) from exc
    return start, end, history["series"].get(tag, [])


@router.get("/api/signals/{tag:path}/value")
def signal_value(
    tag: str,
    _user: CurrentUser,
    rt: Runtime,
    scope: Scope,
    agg: Aggregation = "last",
    window: str = "1h",
) -> dict[str, Any]:
    """One number for a KPI card: the last value or an aggregate over a window."""

    _require_signal(scope, tag)
    tag = _tag(rt, tag)
    start, end, series = _read(rt, tag, _window(window), 20000)
    values = [
        value for _, value in series if isinstance(value, (int, float)) and not pd.isna(value)
    ]
    value = None
    if values:
        if agg == "last":
            value = values[-1]
        elif agg == "first":
            value = values[0]
        elif agg == "mean":
            value = sum(values) / len(values)
        elif agg == "min":
            value = min(values)
        elif agg == "max":
            value = max(values)
        else:
            value = values[-1] - values[0]
    return {
        "tag": tag,
        "agg": agg,
        "window": window,
        "value": None if value is None else float(value),
        "samples": len(values),
        "at": series[-1][0] if series else None,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "assets": [item for item in rt.workspace.assets.assets_of_signal(tag) if scope.asset(item)],
    }


@router.get("/api/signals/{tag:path}/series")
def signal_series(
    tag: str,
    _user: CurrentUser,
    rt: Runtime,
    scope: Scope,
    window: str = "1h",
    points: Annotated[int, Query(ge=10, le=5000)] = 600,
) -> dict[str, Any]:
    """The samples of one signal over a window, thinned to at most ``points``."""

    _require_signal(scope, tag)
    tag = _tag(rt, tag)
    start, end, series = _read(rt, tag, _window(window), points)
    return {
        "tag": tag,
        "window": window,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "series": series,
    }


# References -------------------------------------------------------------------


@router.get("/api/refs")
def resolve_refs(
    user: CurrentUser,
    rt: Runtime,
    ref: Annotated[list[str], Query(max_length=200)],
) -> dict[str, dict[str, Any]]:
    """Name, state and link of each reference (``asset:FIC-101``, ``user:ana.lima``), as the
    person may read them (an action out of their sight is only "Action 42")."""

    return rt.platform.refs.resolve_many(ref, viewer=user)


def _require_plant_ref(rt: Any, user: str, ref: str) -> None:
    """An asset or signal out of the person's asset scope has no history for them: 404."""

    if ref.partition(":")[0] in {"asset", "signal"} and not rt.platform.refs.reader(user)(ref):
        raise HTTPException(status_code=404, detail=t("Not found."))


@router.get("/api/refs/{ref:path}/timeline")
def ref_timeline(
    ref: str,
    user: CurrentUser,
    rt: Runtime,
    before: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    """What happened to (or mentioned) one item, newest first, with the other items resolved."""

    _require_plant_ref(rt, user, ref)
    try:
        events = rt.workspace.events.timeline(ref, before_id=before, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    events = rt.events_for(user, events)
    mentioned = sorted({item for event in events for item in event["refs"]})
    return {
        "ref": rt.platform.refs.resolve(ref, viewer=user),
        "events": events,
        "refs": rt.platform.refs.resolve_many(mentioned, viewer=user),
    }


@router.get("/api/refs/{ref:path}/backlinks")
def ref_backlinks(ref: str, user: CurrentUser, rt: Runtime) -> list[dict[str, Any]]:
    """The items whose history mentions this one (those the person may read)."""

    _require_plant_ref(rt, user, ref)
    try:
        subjects = rt.workspace.events.backlinks(ref)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    sees = rt.platform.refs.reader(user)
    subjects = [item for item in subjects if sees(item)]
    resolved = rt.platform.refs.resolve_many(subjects, viewer=user)
    return [resolved[item] for item in subjects if item in resolved]
