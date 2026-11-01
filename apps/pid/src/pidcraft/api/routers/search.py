"""HTTP routes: PlantCraft PID's part of the suite's search (Ctrl+K, PlantCraft's
docs/app-standard.md section 10): its drawings by number, title or unit, and the tags drawn on
them, each ``href`` the drawing or the sheet that draws the tag."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from plantcraft_sdk.server.search import SearchItem, matches, search_answer, search_text

from pidcraft.api.deps import CurrentUser, RuntimeDep
from pidcraft.i18n import t

router = APIRouter()


@router.get("/api/search")
def search(
    rt: RuntimeDep,
    _user: CurrentUser,
    q: str = Query("", max_length=120),
    limit: int = Query(6, ge=1, le=20),
) -> dict[str, Any]:
    text = search_text(q)
    if not text:
        return search_answer([])
    found = [
        SearchItem(
            drawing["number"],
            f"/drawings/{drawing['drawing_id']}",
            type=t("Drawing"),
            detail=drawing["title"] or drawing["unit"],
        )
        for drawing in rt.drawings.list()
        if matches(text, drawing["number"], drawing["title"], drawing["unit"])
    ]
    for page in rt.store.diagrams(full=True):
        for item in page["result"].get("items") or []:
            tag = item.get("tag")
            if tag and matches(text, tag):
                found.append(
                    SearchItem(
                        tag,
                        f"/diagrams/{page['rev_id']}/{page['page']}/{tag}",
                        type=t("Tag on a drawing"),
                        detail=page["sheet"] or page["doc_number"],
                    )
                )
    return search_answer(found, text, limit=limit)
