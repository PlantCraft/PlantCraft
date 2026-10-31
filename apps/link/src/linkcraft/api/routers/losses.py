"""Loop-hours lost by cause, by area or loop and period (A13), and each loop's effective control
(A7): ``engine.losses``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query

from linkcraft.api.deps import RuntimeDep
from linkcraft.api.scope import Scope, sees_loop
from linkcraft.engine.losses import CAUSE_LABELS, CAUSES, effective_control, losses_by
from linkcraft.i18n import t
from linkcraft.loops.monitor import APPLICATION_ID, SUBJECT_KIND

router = APIRouter(prefix="/api")


@router.get("/loop-losses")
def loop_losses(
    scope: Scope,
    rt: RuntimeDep,
    days: float = Query(default=7, gt=0, le=400),
    until: datetime | None = None,
    group_by: Literal["area", "loop"] = "area",
) -> dict[str, Any]:
    """Loop-hours lost per cause in the ``days`` before ``until`` (now), by area or by loop."""

    end = (until or datetime.now(UTC)).astimezone(UTC)
    start = end - timedelta(days=days)
    if end <= start:
        raise HTTPException(status_code=422, detail=t("The period is empty."))
    loops = {loop.loop_id: loop for loop in rt.loops.list_loops()}
    seen = {key: loop for key, loop in loops.items() if sees_loop(scope, rt, key, loop)}
    totals = rt.monitor.losses.totals(start, end)
    rows = losses_by(totals, seen, group_by)
    whole = losses_by(totals, seen, "all") if rows else []
    return {
        "since": start.isoformat().replace("+00:00", "Z"),
        "until": end.isoformat().replace("+00:00", "Z"),
        "group_by": group_by,
        "causes": [{"key": key, "label": t(CAUSE_LABELS[key])} for key in CAUSES],
        "rows": rows,
        "total": whole[0] if whole else None,
    }


@router.get("/loop-effective-control")
def loop_effective_control(scope: Scope, rt: RuntimeDep) -> list[dict[str, Any]]:
    """Each loop's effective control from its latest round: % in normal mode x % in its band x
    % with the output off its limits, worst first (unmeasured last)."""

    loops = {loop.loop_id: loop for loop in rt.loops.list_loops()}
    rows = []
    for loop_id, results in rt.monitor.latest.results(APPLICATION_ID, SUBJECT_KIND).items():
        loop = loops.get(loop_id)
        if loop is None or not sees_loop(scope, rt, loop_id, loop):
            continue
        rows.append(
            {"loop_id": loop_id, "name": loop.name, "area": loop.area, **effective_control(results)}
        )
    rows.sort(key=lambda row: (row["score"] is None, row["score"] or 0.0, row["loop_id"]))
    return rows
