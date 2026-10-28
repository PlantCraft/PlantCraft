"""HTTP routes: health and the help pages."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from processcraft.api.deps import CurrentUser, Runtime
from processcraft.api.help import DOCS, document_index, read_document
from processcraft.i18n import t

router = APIRouter()


@router.get("/healthz")
def healthcheck(rt: Runtime) -> dict[str, Any]:
    return {
        "status": "ok",
        "scenario": rt.scenario.name,
        "source_type": rt.scenario.source.type,
        "interface": "react",
    }


@router.get("/api/help")
def help_index(_user: CurrentUser, rt: Runtime) -> list[dict[str, Any]]:
    return document_index()


@router.get("/api/help/{document_id}")
def help_document(document_id: str, _user: CurrentUser, rt: Runtime) -> dict[str, str]:
    if document_id not in DOCS:
        raise HTTPException(status_code=404, detail=t("Document not found."))
    return {"document_id": document_id, "content": read_document(document_id)}
