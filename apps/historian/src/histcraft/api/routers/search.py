"""HTTP routes: the Historian's part of the suite's search (Ctrl+K, PlantCraft's
docs/app-standard.md section 10): its points and its sources, each ``href`` a page of this app."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Query
from plantcraft_sdk.server.search import SearchItem, matches, search_answer, search_text

from histcraft.api.deps import RuntimeDep, Scope
from histcraft.i18n import t

router = APIRouter()


@router.get("/api/search")
def search(
    runtime: RuntimeDep,
    scope: Scope,
    q: str = Query("", max_length=120),
    limit: int = Query(6, ge=1, le=20),
) -> dict[str, Any]:
    text = search_text(q)
    if not text:
        return search_answer([])
    # The catalog narrows by its longest word in SQL; every word must then match.
    longest = max(text.split(), key=len)
    found = [
        SearchItem(
            point["tag"],
            f"/points/{quote(point['signal'], safe='')}",
            type=t("Signal"),
            detail=" · ".join(
                part
                for part in (point.get("name"), point.get("description"))
                if part and part != point["tag"]
            ),
        )
        for point in runtime.catalog.points(q=longest)
        if matches(text, point["tag"], point.get("name"), point.get("description"))
        and scope.signal(point["signal"])
    ]
    found += [
        SearchItem(
            source["name"],
            f"/sources/{quote(source['id'], safe='')}",
            type=t("Source"),
            detail=source.get("kind"),
        )
        for source in runtime.catalog.sources()
        if matches(text, source["id"], source["name"], source.get("kind"))
    ]
    return search_answer(found, text, limit=limit)
