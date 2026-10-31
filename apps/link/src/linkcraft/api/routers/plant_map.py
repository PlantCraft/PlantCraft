"""The plant map (A6): each loop's KPIs for the heat map and the treemap, ``engine.plant_map``."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from linkcraft.api.deps import RuntimeDep
from linkcraft.api.scope import Scope, sees_loop
from linkcraft.engine.plant_map import plant_map
from linkcraft.i18n import t
from linkcraft.loops.analysis import CRITICALITY_WEIGHTS
from linkcraft.loops.monitor import APPLICATION_ID, SUBJECT_KIND

router = APIRouter(prefix="/api")


@router.get("/plant-map")
def plant_map_route(scope: Scope, rt: RuntimeDep) -> dict[str, Any]:
    """Every loop the person sees, with each KPI's value and colour band."""

    loops = {
        loop.loop_id: loop
        for loop in rt.loops.list_loops()
        if loop.enabled and sees_loop(scope, rt, loop.loop_id, loop)
    }
    found = plant_map(
        loops,
        rt.latest.summaries(APPLICATION_ID, SUBJECT_KIND),
        rt.latest.results(APPLICATION_ID, SUBJECT_KIND),
        CRITICALITY_WEIGHTS,
    )
    for kpi in found["kpis"]:
        kpi["label"] = t(kpi["label"])
    return found
