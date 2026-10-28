"""HTTP routes: Link's part of the suite's search (Ctrl+K, PlantCraft's docs/app-standard.md
section 10): its loops, algorithms and blocks, each ``href`` a page of this app."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Query
from plantcraft_sdk.server.search import SearchItem, matches, search_answer, search_text

from linkcraft.api.deps import RuntimeDep
from linkcraft.api.scope import Scope, sees_loop
from linkcraft.blocks.catalog import catalog_items
from linkcraft.i18n import t

router = APIRouter()


@router.get("/api/search")
def search(
    scope: Scope,
    rt: RuntimeDep,
    q: str = Query("", max_length=120),
    limit: int = Query(6, ge=1, le=20),
) -> dict[str, Any]:
    text = search_text(q)
    if not text:
        return search_answer([])
    found = [
        SearchItem(
            loop.loop_id,
            f"/loops/{quote(loop.loop_id)}",
            type=t("Loop"),
            detail=" · ".join(part for part in (loop.name, loop.area) if part),
        )
        for loop in rt.loops.list_loops()
        if matches(text, loop.loop_id, loop.name, loop.area, loop.service)
        and sees_loop(scope, rt, loop.loop_id, loop)
    ]
    found += [
        SearchItem(
            item["name"],
            f"/algorithms/{quote(item['profile_id'])}",
            type=t("Algorithm"),
            detail=item.get("description"),
        )
        for item in rt.presets.list_profiles()
        if matches(text, item["profile_id"], item["name"], item.get("description"))
    ]
    found += [
        SearchItem(
            item["name"],
            f"/blocks/{quote(item['block_id'])}",
            type=t("Block"),
            detail=item.get("summary") or item.get("library"),
        )
        for item in catalog_items()
        if matches(text, item["block_id"], item["name"], item.get("summary"), item.get("library"))
    ]
    return search_answer(found, text, limit=limit)
