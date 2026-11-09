"""Desk's notes: private until shared with people or groups, with ``#`` mentions."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import HTTPException, Query
from pydantic import BaseModel, Field

from plantcraft.api.deps import CurrentUser, Runtime, open_to
from plantcraft.api.routers.desk.common import _bad, _my_groups, _present_note, _with_refs, router
from plantcraft.i18n import t

# Notes ----------------------------------------------------------------------------------------


class NoteIn(BaseModel):
    title: str = Field(default="", max_length=200)
    body: dict[str, Any] = Field(default_factory=dict)
    text: str = Field(default="", max_length=100_000)
    shared: list[Annotated[str, Field(max_length=80)]] = Field(default_factory=list, max_length=50)
    event_ref: str | None = Field(default=None, max_length=200)


class NoteChange(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    body: dict[str, Any] | None = None
    text: str | None = Field(default=None, max_length=100_000)
    shared: list[Annotated[str, Field(max_length=80)]] | None = Field(default=None, max_length=50)
    pinned: bool | None = None
    event_ref: str | None = Field(default=None, max_length=200)


def _check_shares(rt: Any, shared: list[str]) -> None:
    for item in shared:
        kind, _, name = item.partition(":")
        known = (
            rt.workspace.users.is_person(name)
            if kind == "user"
            else kind == "group" and rt.workspace.groups.get(name) is not None
        )
        if not known:
            raise HTTPException(
                status_code=422, detail=t("{name} is not a person or a group.", name=item)
            )


def _note_for(rt: Any, user: str, note_id: int) -> dict[str, Any]:
    note = rt.desk.note(note_id)
    if note is None or not rt.desk.note_visible(note, user, _my_groups(rt, user)):
        raise HTTPException(status_code=404, detail=t("Note not found."))
    return note


@router.get("/api/desk/notes")
def notes(
    user: CurrentUser,
    rt: Runtime,
    q: Annotated[str, Query(max_length=200)] = "",
    event: Annotated[str | None, Query(max_length=200)] = None,
) -> dict[str, Any]:
    """The person's notes and those shared with them (no bodies), pinned first; ``q`` searches
    titles and text, ``event`` finds a calendar event's note."""

    items = rt.desk.notes(user, _my_groups(rt, user), q=q, event_ref=event)
    return {
        "items": [
            {**_present_note(rt, user, item), "body_text": item["body_text"][:160]}
            for item in items
        ]
    }


@router.get("/api/desk/notes/{note_id}")
def note(note_id: int, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    return _with_refs(rt, user, _note_for(rt, user, note_id))


@router.post("/api/desk/notes", status_code=201)
@open_to("viewer")
def create_note(body: NoteIn, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """A note, private unless ``shared`` names people (``user:ana``) or groups (``group:x``)."""

    _check_shares(rt, body.shared)
    try:
        made = rt.desk.create_note(
            user,
            title=body.title,
            body=body.body,
            text=body.text,
            shared=body.shared,
            event_ref=body.event_ref,
        )
    except ValueError as exc:
        raise _bad(exc) from exc
    return _with_refs(rt, user, made)


@router.patch("/api/desk/notes/{note_id}")
@open_to("viewer")
def change_note(note_id: int, body: NoteChange, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """Whoever sees a note writes in it; only its owner shares it, pins it or ties it to an
    event."""

    current = _note_for(rt, user, note_id)
    change = {key: value for key, value in body.model_dump(include=body.model_fields_set).items()}
    if current["owner"] != user and {"shared", "pinned", "event_ref"} & set(change):
        raise HTTPException(status_code=403, detail=t("Only the note's owner shares it."))
    if change.get("shared") is not None:
        _check_shares(rt, change["shared"])
    if change.get("body") is None:
        change.pop("body", None)
        change.pop("text", None)
    try:
        updated = rt.desk.update_note(note_id, change, user)
    except ValueError as exc:
        raise _bad(exc) from exc
    return _with_refs(rt, user, updated or current)


@router.delete("/api/desk/notes/{note_id}")
@open_to("viewer")
def delete_note(note_id: int, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    current = _note_for(rt, user, note_id)
    if current["owner"] != user:
        raise HTTPException(status_code=403, detail=t("Only the note's owner deletes it."))
    rt.desk.delete_note(note_id)
    return {"deleted": note_id}
