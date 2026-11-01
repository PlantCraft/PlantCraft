"""Export: a data package (``export.package``) of the tags someone chooses, over a period, for a
consultant or a colleague to analyse in their own tools or their own PlantCraft.

The page searches tags and assets of any kind together (a loop is one kind of asset among
others), and "Add" puts the tags of what is ticked in the list that is
exported (``/resolve`` lists an asset's tags, with everything under it). The assets they came
from travel as metadata (``assets.csv``, ``plant-map.json``). A choice can be saved under a
name and run again (``/saved``). The series come from the Historian's archive; the plant's
structure from PlantCraft's asset tree, read with the person's own token, so a package never
names an asset they may not see. Everyone with access to the Historian may export (owner,
2026-10-21); each export is in PlantCraft's audit log.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from plantcraft_sdk.asset_scope import AssetScope
from plantcraft_sdk.auth import User
from plantcraft_sdk.client import PlantCraftError
from plantcraft_sdk.contract import ContractError
from pydantic import BaseModel, Field, StringConstraints

from histcraft import __version__
from histcraft.api.deps import CurrentUser, RuntimeDep, Scope
from histcraft.api.runtime import Runtime, point_ref
from histcraft.archive.query import SourceUnavailable
from histcraft.export import package
from histcraft.i18n import t

router = APIRouter(prefix="/api/export", tags=["export"])

MAX_DAYS = 31
# As recorded, a package covers at most this many days (a step makes longer periods small).
MAX_RAW_DAYS = 7
MAX_SIGNALS = 500
Id = Annotated[str, StringConstraints(min_length=1, max_length=300)]
Aggregate = Literal["mean", "first", "last", "min", "max"]


class ExportRequest(BaseModel):
    # Signal ids (``<source id>:<tag>``) and asset ids (loops, groups, units: each with all
    # that is under it).
    signals: list[Id] = Field(default_factory=list, max_length=MAX_SIGNALS)
    assets: list[Id] = Field(default_factory=list, max_length=500)
    start: str | None = Field(default=None, max_length=64)
    end: str | None = Field(default=None, max_length=64)
    hours: float | None = Field(default=24.0, gt=0, le=MAX_DAYS * 24)
    step_seconds: int | None = Field(default=None, ge=1, le=86400)
    # What each step keeps: the time-weighted mean, or the first, last,
    # lowest or highest value recorded in it.
    aggregate: Aggregate = "mean"
    anonymize: bool = False
    # True: an asset brings every tag under it. False (the page): only ``signals`` are
    # exported, and the assets describe where they come from.
    expand_assets: bool = True


class ResolveRequest(BaseModel):
    assets: list[Id] = Field(min_length=1, max_length=500)


class SavedExport(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    signals: list[Id] = Field(default_factory=list, max_length=MAX_SIGNALS)
    assets: list[Id] = Field(default_factory=list, max_length=500)
    hours: float | None = Field(default=24.0, gt=0, le=MAX_DAYS * 24)
    start: str | None = Field(default=None, max_length=64)
    end: str | None = Field(default=None, max_length=64)
    step_seconds: int | None = Field(default=None, ge=1, le=86400)
    aggregate: Aggregate = "mean"
    anonymize: bool = False


def _person(user: User) -> None:
    if user.is_service:
        raise HTTPException(403, t("Exports are made by people."))


def _saves(user: User) -> None:
    """A public demo's visitors share one account: they export, but save no choice."""

    _person(user)
    if user.demo is not None:
        raise HTTPException(
            403,
            t("This is a public demo: for security, this part is locked, and nothing is saved."),
        )


def _assets(runtime: Runtime, user: User) -> list[dict[str, Any]]:
    try:
        return list(runtime.user_client(user).assets())
    except PlantCraftError as exc:
        raise HTTPException(502, t("PlantCraft did not answer: {error}", error=exc)) from exc


def _children(assets: list[dict[str, Any]]) -> dict[str | None, list[dict[str, Any]]]:
    found: dict[str | None, list[dict[str, Any]]] = {}
    for item in assets:
        found.setdefault(item.get("parent_id"), []).append(item)
    return found


def _subtree(asset_id: str, children: dict[str | None, list[dict[str, Any]]]) -> list[str]:
    ids, queue = [], [asset_id]
    while queue:
        current = queue.pop()
        ids.append(current)
        queue.extend(item["id"] for item in children.get(current, []))
    return ids


def _archived(runtime: Runtime, scope: AssetScope) -> dict[str, dict[str, Any]]:
    """The points archived here that the caller's part of the plant holds, by signal id."""

    return {
        item["signal"]: item for item in runtime.catalog.points() if scope.signal(item["signal"])
    }


def _selection(
    runtime: Runtime, user: User, request: ExportRequest, scope: AssetScope
) -> package.Selection:
    points = _archived(runtime, scope)
    chosen: dict[str, dict[str, Any]] = {}
    unknown = [signal for signal in request.signals if signal not in points]
    if unknown:
        raise HTTPException(
            422, t("Not in the Historian: {signals}", signals=", ".join(unknown[:5]))
        )
    for signal in request.signals:
        chosen[signal] = points[signal]
    assets: list[dict[str, Any]] = []
    missing: dict[str, str] = {}
    if request.assets:
        tree = _assets(runtime, user)
        by_id = {item["id"]: item for item in tree}
        absent = [item for item in request.assets if item not in by_id]
        if absent:
            raise HTTPException(422, t("Unknown assets: {assets}", assets=", ".join(absent[:5])))
        children = _children(tree)
        ids = dict.fromkeys(
            asset_id for root in request.assets for asset_id in _subtree(root, children)
        )
        for asset_id in ids:
            asset = by_id[asset_id]
            signals = [signal for signal in (asset.get("signals") or {}).values() if signal]
            if not request.expand_assets:
                # Only the tags in the list: an asset describes them when it uses one of them.
                if asset_id in request.assets or any(signal in chosen for signal in signals):
                    assets.append(asset)
                continue
            assets.append(asset)
            for signal in signals:
                if signal in points:
                    chosen.setdefault(signal, points[signal])
                else:
                    missing[signal] = t("Not archived by the Historian.")
    selection = package.Selection(signals=list(chosen.values()), assets=assets, missing=missing)
    if not selection.signals:
        raise HTTPException(
            422, t("Nothing to export: the choice has no tag archived by the Historian.")
        )
    if len(selection.signals) > MAX_SIGNALS:
        raise HTTPException(
            422,
            t(
                "A package holds at most {count} tags: this choice has {found}.",
                count=MAX_SIGNALS,
                found=len(selection.signals),
            ),
        )
    return selection


def _utc(text: str) -> datetime:
    stamp = pd.Timestamp(text)
    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
    return stamp.to_pydatetime()


def _period(request: ExportRequest) -> tuple[datetime, datetime]:
    try:
        end = _utc(request.end) if request.end else datetime.now(timezone.utc)
        start = _utc(request.start) if request.start else end - timedelta(hours=request.hours or 24)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, t("Times must be ISO 8601.")) from exc
    if start >= end:
        raise HTTPException(422, t("The start must be before the end."))
    if end - start > timedelta(days=MAX_DAYS):
        raise HTTPException(422, t("A package covers at most {days} days.", days=MAX_DAYS))
    if request.step_seconds is None and end - start > timedelta(days=MAX_RAW_DAYS):
        raise HTTPException(
            422,
            t(
                "As recorded, a package covers at most {days} days: choose an average.",
                days=MAX_RAW_DAYS,
            ),
        )
    return start, end


def bucketed(series: pd.Series, start: datetime, step: int, aggregate: str) -> pd.Series:
    """The recorded values on a ``step`` grid from ``start``: each step's first, last, lowest or
    highest value, stamped at the step's start; steps with no value are left out. A text signal
    has no lowest or highest: it keeps the step's last."""

    if series.empty:
        return series
    how = aggregate if series.dtype != object or aggregate in {"first", "last"} else "last"
    grid = series.resample(
        f"{step}s", origin=pd.Timestamp(start).tz_convert("UTC"), label="left", closed="left"
    )
    return getattr(grid, how)().dropna()


def _samples(
    runtime: Runtime,
    selection: package.Selection,
    start: datetime,
    end: datetime,
    step: int | None,
    aggregate: str = "mean",
) -> tuple[dict[str, pd.Series], dict[str, str]]:
    samples: dict[str, pd.Series] = {}
    failed: dict[str, str] = {}
    # The mean is the reader's (time-weighted, from the roll-ups when there are some); the other
    # aggregates come from the recorded values.
    read_step = float(step) if step and aggregate == "mean" else None
    for point in selection.signals:
        try:
            stamps, values = runtime.reader.series(point_ref(point), start, end, read_step)
        except (SourceUnavailable, ContractError) as exc:
            failed[point["signal"]] = str(exc)
            continue
        index = pd.to_datetime(stamps, utc=True, format="ISO8601")
        series = pd.Series(
            values, index=index, dtype=float if point["kind"] == "number" else object
        )
        series = series.dropna()
        if step and aggregate != "mean":
            # The same steps as the mean's: from start, up to (not including) end.
            inside = (series.index >= pd.Timestamp(start)) & (series.index < pd.Timestamp(end))
            series = bucketed(series[inside], start, step, aggregate)
        samples[point["signal"]] = series
    return samples, failed


@router.get("/options")
def options(runtime: RuntimeDep, user: CurrentUser, scope: Scope) -> dict[str, Any]:
    """The asset tree to choose loops, groups and units from, with what each would export."""

    _person(user)
    archived = set(_archived(runtime, scope))
    try:
        tree = list(runtime.user_client(user).assets())
        problem = None
    except PlantCraftError as exc:
        tree, problem = [], str(exc)
    children = _children(tree)
    by_id = {item["id"]: item for item in tree}
    rows = []

    def walk(parent: str | None, depth: int) -> None:
        for item in sorted(children.get(parent, []), key=lambda asset: asset["name"].lower()):
            ids = _subtree(item["id"], children)
            signals = {
                signal
                for asset_id in ids
                for signal in (by_id[asset_id].get("signals") or {}).values()
                if signal
            }
            rows.append(
                {
                    "id": item["id"],
                    "name": item["name"],
                    "kind": item.get("kind") or "",
                    "kind_label": (item.get("attributes") or {}).get("kind_label") or "",
                    "parent_id": item.get("parent_id"),
                    "depth": depth,
                    "loop": package.is_loop(item),
                    "loops": sum(1 for asset_id in ids if package.is_loop(by_id[asset_id])),
                    "signals": len(signals & archived),
                    "missing": len(signals - archived),
                }
            )
            walk(item["id"], depth + 1)

    roots = [item for item in tree if item.get("parent_id") not in by_id]
    for root in roots:
        children.setdefault("__roots__", []).append(root)
    walk("__roots__", 0)
    return {
        "assets": rows,
        "assets_error": problem,
        "points": len(archived),
        "max_days": MAX_DAYS,
        "max_raw_days": MAX_RAW_DAYS,
        "max_signals": MAX_SIGNALS,
    }


@router.post("/resolve")
def resolve(
    request: ResolveRequest, runtime: RuntimeDep, user: CurrentUser, scope: Scope
) -> dict[str, Any]:
    """The tags of these assets and of everything under them: what "Add" puts in the list."""

    _person(user)
    points = _archived(runtime, scope)
    tree = _assets(runtime, user)
    by_id = {item["id"]: item for item in tree}
    children = _children(tree)
    found: dict[str, dict[str, Any]] = {}
    for root in request.assets:
        if root not in by_id:
            continue
        for asset_id in _subtree(root, children):
            asset = by_id[asset_id]
            for role, signal in (asset.get("signals") or {}).items():
                if not signal or signal in found:
                    continue
                point = points.get(signal)
                found[signal] = {
                    "signal": signal,
                    "tag": package.tag_of(signal),
                    "name": (point or {}).get("name") or (point or {}).get("description") or "",
                    "unit": (point or {}).get("unit") or "",
                    "archived": point is not None,
                    "asset_id": asset_id,
                    "asset_name": asset["name"],
                    "role": role,
                }
    return {"tags": list(found.values())}


@router.get("/saved")
def saved_exports(runtime: RuntimeDep, user: CurrentUser) -> list[dict[str, Any]]:
    _person(user)
    return runtime.saved_exports.list()


@router.post("/saved", status_code=201)
def save_export(body: SavedExport, runtime: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    """Anyone who exports may save a choice; its author or an editor changes it."""

    _saves(user)
    return runtime.saved_exports.create(body.name, _payload(body), user.username)


@router.put("/saved/{export_id}")
def update_export(
    export_id: str, body: SavedExport, runtime: RuntimeDep, user: CurrentUser
) -> dict[str, Any]:
    _owned(runtime, export_id, user)
    return runtime.saved_exports.update(export_id, body.name, _payload(body), user.username) or {}


@router.delete("/saved/{export_id}")
def delete_export(export_id: str, runtime: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    _owned(runtime, export_id, user)
    runtime.saved_exports.delete(export_id)
    return {"deleted": export_id}


def _payload(body: SavedExport) -> dict[str, Any]:
    payload = body.model_dump(exclude={"name"})
    if payload["start"] or payload["end"]:
        if not (payload["start"] and payload["end"]):
            raise HTTPException(422, t("A fixed period needs a start and an end."))
        payload["hours"] = None
    return payload


def _owned(runtime: Runtime, export_id: str, user: User) -> dict[str, Any]:
    _saves(user)
    found = runtime.saved_exports.get(export_id)
    if found is None:
        raise HTTPException(404, t("Saved export not found."))
    if found["created_by"] != user.username and not user.can_edit:
        raise HTTPException(403, t("Only its author or an editor changes a saved export."))
    return found


@router.post("/preview")
def preview(
    request: ExportRequest, runtime: RuntimeDep, user: CurrentUser, scope: Scope
) -> dict[str, Any]:
    """What a choice exports, before the file is made."""

    _person(user)
    selection = _selection(runtime, user, request, scope)
    return {
        "signals": len(selection.signals),
        "assets": len(selection.assets),
        "loops": sum(1 for item in selection.assets if package.is_loop(item)),
        "missing": len(selection.missing),
        "tags": [package.tag_of(item) for item in selection.signal_ids()[:12]],
    }


@router.post("")
def export(
    request: ExportRequest, runtime: RuntimeDep, user: CurrentUser, scope: Scope
) -> Response:
    """The package as a ZIP download."""

    _person(user)
    selection = _selection(runtime, user, request, scope)
    start, end = _period(request)
    samples, failed = _samples(
        runtime, selection, start, end, request.step_seconds, request.aggregate
    )
    body = package.build(
        selection=selection,
        samples=samples,
        start=start,
        end=end,
        anonymize=request.anonymize,
        step_seconds=request.step_seconds,
        aggregate=request.aggregate,
        made_by=f"PlantCraft Historian {__version__}",
        failed=failed,
    )
    runtime.audit(
        user,
        "export",
        "export:package",
        {
            "signals": len(selection.signals),
            "assets": len(selection.assets),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "step_seconds": request.step_seconds,
            "aggregate": request.aggregate if request.step_seconds else None,
            "anonymized": request.anonymize,
        },
    )
    name = f"historian-package-{start:%Y%m%d}{'-anonymized' if request.anonymize else ''}.zip"
    # What the package holds, for the page to say after the download ("the
    # zip is so small; is everything there?").
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    return Response(
        body,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Package-Signals": str(manifest["counts"]["signals"]),
            "X-Package-Rows": str(manifest["counts"]["rows"]),
            "X-Package-Not-Read": str(len(manifest["not_read"])),
        },
    )


@router.post("/key")
def export_key(
    request: ExportRequest, runtime: RuntimeDep, user: CurrentUser, scope: Scope
) -> Response:
    """The anonymization key of the same choice: alias -> real tag or asset (stays here)."""

    _person(user)
    selection = _selection(runtime, user, request, scope)
    stamp = re.sub(r"[^0-9]", "", datetime.now(timezone.utc).isoformat())[:8]
    return Response(
        package.key_csv(selection),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="historian-package-key-{stamp}.csv"'
        },
    )
