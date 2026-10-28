"""HTTP routes: the notes, and the asset each one is on (read from PlantCraft as the person)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from plantcraft_sdk.auth import User
from plantcraft_sdk.client import PlantCraftError

from starter.api.deps import CurrentUser, EditorUser, RuntimeDep, guarded, note_or_404
from starter.api.runtime import Runtime
from starter.i18n import t
from starter.notes.models import NoteDraft
from starter.suite.llm import NoModel

router = APIRouter(prefix="/api", tags=["notes"])


def _asset_name(rt: Runtime, user: User, asset_id: str) -> str:
    """The asset's name in PlantCraft, or 422 when the person cannot see such an asset."""

    try:
        asset = guarded(lambda: rt.user_client(user).asset(asset_id), service=False)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        raise HTTPException(422, t("No asset {asset} in PlantCraft.", asset=asset_id)) from exc
    return asset.get("name") or asset_id


@router.get("/notes")
def list_notes(
    rt: RuntimeDep, _user: CurrentUser, asset: str | None = Query(None, max_length=120)
) -> list[dict[str, Any]]:
    return rt.notes.list(asset)


@router.post("/notes", status_code=201)
def create_note(draft: NoteDraft, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    name = _asset_name(rt, user, draft.asset_id)
    note = rt.notes.create(draft, user.username, name)
    rt.audit(user, "note.created", note["note_id"], {"asset": draft.asset_id})
    return {**note, "asset_name": name}


@router.get("/notes/{note_id}")
def get_note(note_id: str, rt: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    note = note_or_404(rt, note_id)
    try:
        name = _asset_name(rt, user, note["asset_id"])
    except HTTPException:
        name = note["asset_id"]
    return {**note, "asset_name": name}


@router.put("/notes/{note_id}")
def update_note(note_id: str, draft: NoteDraft, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    note_or_404(rt, note_id)
    name = _asset_name(rt, user, draft.asset_id)
    note = rt.notes.update(note_id, draft, user.username, name)
    rt.audit(user, "note.changed", note_id, {"asset": draft.asset_id})
    return {**note, "asset_name": name}


@router.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: str, rt: RuntimeDep, user: EditorUser) -> None:
    note_or_404(rt, note_id)
    rt.notes.delete(note_id)
    rt.audit(user, "note.deleted", note_id)


@router.post("/notes/{note_id}/summary")
def summarise_note(note_id: str, rt: RuntimeDep, _user: CurrentUser) -> dict[str, Any]:
    """One sentence on the note, from the model PlantCraft gives the use ``summary``; 409 while
    it has none (an administrator chooses one in Setup › Language models)."""

    note_or_404(rt, note_id)
    try:
        return {"note_id": note_id, "summary": rt.notes.summary(note_id)}
    except NoModel as exc:
        raise HTTPException(
            409, t("No language model for summaries: an administrator chooses one in Setup.")
        ) from exc
    except PlantCraftError as exc:
        raise HTTPException(502, t("PlantCraft did not answer: {error}", error=str(exc))) from exc
