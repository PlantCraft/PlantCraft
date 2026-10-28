"""HTTP routes: StarterCraft's part of the suite's search (Ctrl+K, PlantCraft's
docs/app-standard.md section 10): its notes, by text or asset, each ``href`` the note's page."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from plantcraft_sdk.server.search import SearchItem, matches, search_answer, search_text

from starter.api.deps import CurrentUser, RuntimeDep
from starter.i18n import t

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
            note["text"][:80], f"/notes/{note['note_id']}", type=t("Note"), detail=note["asset_id"]
        )
        for note in rt.notes.list()
        if matches(text, note["text"], note["asset_id"])
    ]
    return search_answer(found, text, limit=limit)
