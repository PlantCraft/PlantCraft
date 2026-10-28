"""HTTP routes: View's part of the suite's search (Ctrl+K, PlantCraft's docs/app-standard.md
section 10): the dashboards and reports the person sees and the saved trends, each ``href`` a page here."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Query
from plantcraft_sdk.server.search import SearchItem, matches, search_answer, search_text

from dashcraft.api.deps import CurrentUser, RuntimeDep, permissions
from dashcraft.i18n import t

router = APIRouter()


@router.get("/api/search")
def search(
    rt: RuntimeDep,
    user: CurrentUser,
    q: str = Query("", max_length=120),
    limit: int = Query(6, ge=1, le=20),
) -> dict[str, Any]:
    text = search_text(q)
    if not text:
        return search_answer([])
    perms = permissions(rt, user)
    found = []
    for item in rt.dashboards.list():
        if not perms.sees(item):
            continue
        folder = perms.folder(item.get("folder_id"))
        if matches(text, item["name"], item.get("description"), folder and folder.get("name")):
            found.append(
                SearchItem(
                    item["name"],
                    f"/d/{quote(item['dashboard_id'], safe='')}",
                    type=t("Dashboard"),
                    detail=item.get("description") or (folder and folder.get("name")),
                )
            )
    for item in rt.reports.list():
        if perms.sees(item) and matches(text, item["name"], item.get("description")):
            found.append(
                SearchItem(
                    item["name"],
                    f"/reports/{quote(item['report_id'], safe='')}",
                    type=t("Report"),
                    detail=item.get("description") or None,
                )
            )
    for item in rt.diagrams.list():
        if not perms.sees(item):
            continue
        folder = perms.folder(item.get("folder_id"))
        if matches(
            text,
            item["name"],
            item.get("description"),
            folder and folder.get("name"),
            *(item.get("tags") or []),
        ):
            found.append(
                SearchItem(
                    item["name"],
                    f"/diagrams/{quote(item['diagram_id'], safe='')}",
                    type=t("Process display"),
                    detail=item.get("description") or (folder and folder.get("name")) or None,
                )
            )
    found += [
        SearchItem(
            item["name"],
            f"/trends/{quote(item['trend_id'], safe='')}",
            type=t("Trend"),
            detail=item.get("description"),
        )
        for item in rt.trends.list()
        if matches(text, item["name"], item.get("description"))
    ]
    return search_answer(found, text, limit=limit)
