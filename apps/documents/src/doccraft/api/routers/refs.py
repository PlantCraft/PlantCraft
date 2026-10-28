"""HTTP routes: what a ``#doc:<id>`` names, for the person asking (PlantCraft
``docs/app-standard.md``, 4b, ``[[contributes.refs]]``): its title, revision and page."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from doccraft.api.deps import CurrentUser, RuntimeDep, document_or_404

router = APIRouter()
KIND = "doc"


@router.get(f"/api/refs/{KIND}/{{doc_id}}")
def document_ref(doc_id: str, rt: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    doc = document_or_404(rt, doc_id, user)
    current = doc.get("current") or {}
    title = " ".join(part for part in (doc["number"], doc["title"]) if part)
    return {
        "title": title,
        "status": f"Rev. {current['revision']}" if current.get("revision") else None,
        "url": f"{rt.settings.root_path}/documents/{doc['doc_id']}",
    }
