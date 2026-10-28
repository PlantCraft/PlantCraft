"""HTTP routes: Alarms' part of the suite's search (Ctrl+K, PlantCraft's docs/app-standard.md
section 10): its alarms, by name, signal, asset or area, each ``href`` the alarm's page."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Query
from plantcraft_sdk.server.search import SearchItem, matches, search_answer, search_text

from alarmcraft.api.deps import CurrentUser, RuntimeDep
from alarmcraft.api.scope import seen
from alarmcraft.i18n import t

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
    found = []
    for alarm in seen(rt.asset_scope(user), rt.alarms.list()):
        source = alarm.get("source") if isinstance(alarm.get("source"), dict) else {}
        signal = source.get("signal_id") or source.get("asset_id")
        if matches(
            text, alarm["alarm_id"], alarm["name"], signal, alarm.get("asset_id"), alarm.get("area")
        ):
            found.append(
                SearchItem(
                    alarm["name"],
                    f"/alarms/{quote(alarm['alarm_id'], safe='')}",
                    type=t("Alarm"),
                    detail=" · ".join(
                        str(part)
                        for part in (alarm.get("priority"), signal or alarm.get("asset_id"))
                        if part
                    ),
                )
            )
    return search_answer(found, text, limit=limit)
