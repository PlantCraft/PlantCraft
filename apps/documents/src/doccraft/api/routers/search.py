"""HTTP routes: Documents' part of the suite's search (Ctrl+K, PlantCraft's
docs/app-standard.md section 10): documents by number or title, and the best passages."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Query
from plantcraft_sdk.server.search import SearchItem, matches, search_answer, search_text

from doccraft.api.deps import CurrentUser, RuntimeDep
from doccraft.i18n import t

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
    perms = rt.permissions(user)
    folders = perms.visible_folders()
    found = [
        SearchItem(
            f"{doc['number']} {doc['title']}".strip(),
            f"/documents/{doc['doc_id']}",
            type=t("Document"),
            detail=doc["kind"],
        )
        for doc in perms.docs(rt.store.documents(folders))
        if matches(text, doc["number"], doc["title"], doc.get("description", ""))
    ]
    for hit in rt.library.search(q, folders=folders, limit=3, scope=perms.scope):
        p = hit.passage
        found.append(
            SearchItem(
                p["section"] or p["title"],
                f"/documents/{p['doc_id']}?passage={p['passage_id']}&q={quote(q, safe='')}",
                type=t("Passage"),
                detail=f"{p['number']} · {p['text'][:80]}",
            )
        )
    return search_answer(found, text, limit=limit)
