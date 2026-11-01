"""The asset deep link (app standard): what ``assets/<id>`` opens in Link."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from plantcraft_sdk.client import PlantCraftError

from linkcraft.api.deps import CurrentUser, RuntimeDep
from linkcraft.api.routers.catalog import asset_run_row
from linkcraft.api.scope import Scope, require, sees_subject
from linkcraft.i18n import t
from linkcraft.signals.publish import asset_result

router = APIRouter()


@router.get("/api/asset-choices")
def asset_choices(user: CurrentUser, rt: RuntimeDep) -> list[dict[str, Any]]:
    """Every asset of PlantCraft as the person sees it, for an algorithm on assets to name:
    its id, name, type, the path of its parents' names and the roles of its signals."""

    try:
        items = list(rt.user_client(user).assets())
    except PlantCraftError as exc:
        raise HTTPException(status_code=502, detail=str(exc.detail or exc)) from exc
    names = {str(item.get("id")): str(item.get("name") or item.get("id")) for item in items}
    parents = {str(item.get("id")): item.get("parent_id") for item in items}

    def path(asset_id: str) -> str:
        found, seen = [], set()
        parent = parents.get(asset_id)
        while parent and parent not in seen and len(found) < 12:
            seen.add(parent)
            found.append(names.get(str(parent), str(parent)))
            parent = parents.get(str(parent))
        return " / ".join(reversed(found))

    return sorted(
        (
            {
                "id": str(item.get("id")),
                "name": names[str(item.get("id"))],
                "kind": str(item.get("kind") or ""),
                "path": path(str(item.get("id"))),
                "roles": sorted((item.get("signals") or {}).keys()),
            }
            for item in items
            if item.get("id")
        ),
        key=lambda row: (row["path"], row["name"]),
    )


@router.get("/api/asset-type-choices")
def asset_type_choices(user: CurrentUser, rt: RuntimeDep) -> list[dict[str, Any]]:
    """PlantCraft's asset types, for an algorithm on assets to run on every asset of a type
    (A20): each type's id, name, parent type and the roles its assets' signals take."""

    try:
        items = list(rt.user_client(user).asset_types())
    except PlantCraftError as exc:
        raise HTTPException(status_code=502, detail=str(exc.detail or exc)) from exc
    return sorted(
        (
            {
                "id": str(item.get("id")),
                "name": str(item.get("name") or item.get("id")),
                "parent": item.get("parent") or item.get("parent_id"),
                "roles": sorted(
                    str(role.get("key")) for role in item.get("roles") or [] if role.get("key")
                ),
            }
            for item in items
            if item.get("id")
        ),
        key=lambda row: row["name"].casefold(),
    )


@router.get("/api/assets/{asset_id:path}")
def asset_link(asset_id: str, scope: Scope, rt: RuntimeDep) -> dict[str, Any]:
    """What ``assets/<id>`` opens: the asset's page in Link, with the latest result of every
    algorithm that runs on it (its loop's algorithm, Signal quality on its signals, the
    algorithms on assets that name it), the quality of its signals, or why Link has none."""

    from linkcraft.api.routers.results import _key, scoped_rows

    require(sees_subject(scope, rt, asset_id), t("Asset {id} not found.", id=asset_id))

    # The algorithms on assets that run on it, beside whatever else Link says about it.
    runs = [asset_run_row(row) for row in rt.asset_runs.list(asset_id=asset_id)]
    loop = rt.loops.get_loop(asset_id)
    origin = rt.loops.origins().get(asset_id) if loop is not None else None
    loop_id = loop.loop_id if loop is not None and origin == "processcraft" else None
    asset = next(
        (item for item in rt.quality_engine.assets if str(item.get("id")) == asset_id),
        None,
    )
    roles = {
        str(role): str(signal)
        for role, signal in ((asset or {}).get("signals") or {}).items()
        if signal
    }
    if loop is not None and not roles:
        roles = {
            role: str(signal)
            for role, signal in loop.signals.model_dump().items()
            if isinstance(signal, str) and signal
        }
    signals = set(roles.values())
    results = sorted(
        (
            row
            for row in scoped_rows(rt, scope)
            if (row["kind"] == "loop" and row["id"] == loop_id)
            or (row["kind"] == "signal" and row["id"] in signals)
            or (row["kind"] == "asset" and row["caption"] == asset_id)
        ),
        key=_key,
    )
    for row in results:
        row.pop("group_id", None)
    latest = rt.quality_results.latest_many(sorted(signals)) if signals else {}
    quality = asset_result(asset, latest, expires_at="") if asset and latest else None
    name = (
        (asset or {}).get("name")
        or (loop.name if loop is not None else None)
        or (runs[0]["asset_name"] if runs else None)
        or asset_id
    )
    if loop_id or quality is not None or runs or results:
        return {
            "asset_id": asset_id,
            "covered": True,
            "loop_id": loop_id,
            "reason": None,
            "name": name,
            "runs": runs,
            "results": results,
            "quality": (
                {key: quality[key] for key in ("status", "score", "usable", "summary")}
                if quality is not None
                else None
            ),
            "signals": [
                {
                    "role": role,
                    "signal": signal,
                    "status": (latest.get(signal) or {}).get("status"),
                    "quality": (latest.get(signal) or {}).get("quality"),
                    "message": (latest.get(signal) or {}).get("message") or "",
                }
                for role, signal in sorted(roles.items())
            ],
        }
    return {
        "asset_id": asset_id,
        "covered": False,
        "loop_id": None,
        "reason": t(
            "No algorithm of Analytics runs on this asset yet: monitor one on it, or give it signals "
            "for Signal quality to check."
        ),
        "runs": [],
        "results": [],
    }
