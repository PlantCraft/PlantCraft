"""HTTP routes: what a ``#pid:<id>`` names, for the person asking (PlantCraft
``docs/app-standard.md``, 4b, ``[[contributes.refs]]``): the drawing's number, title and page."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from pidcraft.api.deps import CurrentUser, RuntimeDep, drawing_or_404

router = APIRouter()
KIND = "pid"


@router.get(f"/api/refs/{KIND}/{{drawing_id}}")
def drawing_ref(drawing_id: str, rt: RuntimeDep, _user: CurrentUser) -> dict[str, Any]:
    drawing = drawing_or_404(rt, drawing_id)
    title = drawing["number"] + (f" {drawing['title']}" if drawing["title"] else "")
    return {
        "title": title[:120],
        "status": drawing.get("status"),
        "url": f"/pid/drawings/{drawing['drawing_id']}",
    }
