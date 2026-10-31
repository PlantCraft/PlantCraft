"""What a ``#loop_result:<loop id>@<window end>`` names, for the person asking (PlantCraft
``docs/app-standard.md``, 4b, ``[[contributes.refs]]``): an action opened from a loop's result
(frontend ``loopResult.ts``) carries it, and it opens the loop's page."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException

from linkcraft.api.deps import RuntimeDep
from linkcraft.api.scope import Scope, sees_loop
from linkcraft.i18n import t
from linkcraft.loops.monitor import APPLICATION_ID, SUBJECT_KIND
from linkcraft.loops.suite import SUITE_STATUS

router = APIRouter()
KIND = "loop_result"


def split_ref(ref_id: str) -> tuple[str, str | None]:
    """``<loop id>@<window end>`` into its parts (a loop id may hold "@" itself)."""

    loop_id, at, end = ref_id.rpartition("@")
    if at and loop_id and end[:4].isdigit():
        return loop_id, end
    return ref_id, None


@router.get(f"/api/refs/{KIND}/{{ref_id:path}}")
def loop_result_ref(ref_id: str, scope: Scope, rt: RuntimeDep) -> dict[str, Any]:
    loop_id, end = split_ref(ref_id)
    loop = rt.loops.get_loop(loop_id)
    if loop is None or not sees_loop(scope, rt, loop_id, loop):
        raise HTTPException(status_code=404, detail=t("Loop not found."))
    summary = rt.monitor.latest.summaries(APPLICATION_ID, SUBJECT_KIND).get(loop_id) or {}
    when = f" · {end[:16].replace('T', ' ')} UTC" if end else ""
    return {
        "title": t("{loop}: result{when}", loop=loop.name or loop_id, when=when),
        "status": SUITE_STATUS.get(summary.get("status") or "", None),
        "url": f"{rt.root_path}/loops/{quote(loop_id, safe='')}",
    }
