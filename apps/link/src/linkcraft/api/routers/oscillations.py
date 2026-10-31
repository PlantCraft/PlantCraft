"""Oscillating loops grouped by period, with where each plant-wide oscillation likely starts (A11):
``engine.oscillation_groups``."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from linkcraft.api.deps import RuntimeDep
from linkcraft.api.scope import Scope, sees_loop
from linkcraft.engine.oscillation_groups import group_by_period
from linkcraft.i18n import t
from linkcraft.loops.monitor import APPLICATION_ID, SUBJECT_KIND

router = APIRouter(prefix="/api")


@router.get("/oscillation-groups")
def oscillation_groups(
    scope: Scope, rt: RuntimeDep, tolerance: float = Query(default=0.15, gt=0, le=0.5)
) -> dict[str, Any]:
    """The loops the last runs found oscillating, grouped by period (relative ``tolerance``)."""

    loops = {
        loop.loop_id: loop
        for loop in rt.loops.list_loops()
        if sees_loop(scope, rt, loop.loop_id, loop)
    }
    found = group_by_period(rt.latest.results(APPLICATION_ID, SUBJECT_KIND), loops, tolerance)
    for group in found["groups"]:
        group["why"] = [t(item) for item in group["why"]]
    return found
