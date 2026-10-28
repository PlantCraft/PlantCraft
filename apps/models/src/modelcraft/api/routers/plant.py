"""The plant as Models sees it: signals to feed a simulation with (read as the editor), and the
suite's ``assets/<id>`` page (the simulations that used the asset's signals)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from plantcraft_sdk.server.picker import signal_choices

from modelcraft.api.deps import CurrentUser, EditorUser, RuntimeDep, guarded, seen_runs
from modelcraft.i18n import t

router = APIRouter(prefix="/api", tags=["plant"])


@router.get("/signals")
def list_signals(
    rt: RuntimeDep,
    user: EditorUser,
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=30, ge=1, le=200),
) -> list[dict[str, Any]]:
    client = rt.user_client(user)
    found = guarded(lambda: client.signals(q.strip() or None), service=False)
    return signal_choices(found, q, limit=limit, numbers_only=True)


@router.get("/asset-runs")
def asset_runs(
    rt: RuntimeDep, user: CurrentUser, asset: str = Query(max_length=300)
) -> dict[str, Any]:
    """The suite's page of one asset: simulations fed by, or compared with, its signals."""

    client = rt.user_client(user)
    try:
        found = guarded(lambda: client.asset(asset), service=False)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(404, t("Asset not found.")) from exc
        raise
    signals = set((found.get("signals") or {}).values())
    runs = []
    for run in seen_runs(rt, user, rt.runs.list(kind="simulate", limit=1000)):
        plant = (run.get("options") or {}).get("plant") or {}
        used = set((plant.get("inputs") or {}).values()) | set(
            (plant.get("compare") or {}).values()
        )
        if used & signals:
            runs.append(run)
    return {
        "asset": {"id": found.get("id"), "name": found.get("name"), "kind": found.get("kind")},
        "signals": sorted(signals),
        "runs": runs[:200],
    }
