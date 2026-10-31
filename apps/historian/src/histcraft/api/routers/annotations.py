"""Notes on a signal at an instant or over an interval (``catalog.annotations``, gap H8).

``GET /api/v1/annotations`` reads the notes of a window (of one signal, or of every signal the
caller sees); editors add one with ``POST`` and remove their own (administrators any) with
``DELETE``. A note added answers, beside it, the PlantCraft event that tells it (``event``):
the page posts it to ``POST /api/v1/events`` in the person's name.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from histcraft.api.deps import EditorUser, RuntimeDep, Scope, in_scope
from histcraft.archive.query import iso_ms
from histcraft.catalog.models import CatalogError
from histcraft.clock import now_ms
from histcraft.i18n import t
from histcraft.lab import DAY_MS
from histcraft.lab import stamp_ms as _ms

router = APIRouter(prefix="/api/v1/annotations", tags=["annotations"])
MAX_NOTES = 1000
EVENT_KIND = "histcraft.annotation.added"


class AnnotationIn(BaseModel):
    signal: str = Field(min_length=3, max_length=340)
    # The instant it is about, or where the interval starts (ISO 8601 with an offset).
    at: str
    # Where the interval ends; None: one instant.
    end: str | None = None
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def stripped(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError(t("The note is empty."))
        return value


def _iso(at: Any) -> str | None:
    return None if at is None else iso_ms(np.asarray([int(at)]))[0]


def _note(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "signal": row["signal"],
        "at": _iso(row["start_ms"]),
        "end": _iso(row["end_ms"]),
        "text": row["text"],
        "author": row["author"],
        "created_at": _iso(row["created_ms"]),
    }


def _event(note: dict[str, Any]) -> dict[str, Any]:
    """The PlantCraft event that tells ``note`` (``POST /api/v1/events``)."""

    when = note["at"] if not note["end"] else f"{note['at']} – {note['end']}"
    return {
        "app": "histcraft",
        "kind": EVENT_KIND,
        "subject": f"signal:{note['signal']}",
        "summary": note["text"][:200],
        "payload": {
            "annotation": note["id"],
            "signal": note["signal"],
            "at": note["at"],
            "end": note["end"],
            "text": note["text"],
            "when": when,
        },
    }


@router.get("")
def notes(
    runtime: RuntimeDep,
    scope: Scope,
    signal: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """The notes that touch ``[start, end]`` (default: the last 30 days), of ``signal`` or of
    every signal the caller sees, oldest first (at most 1,000)."""

    try:
        end_ms = _ms(end, "end") or now_ms()
        start_ms = _ms(start, "start") or end_ms - 30 * DAY_MS
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if signal is not None:
        in_scope(scope, signal)
    rows = runtime.annotations.between(
        None if signal is None else [signal], start_ms, end_ms, MAX_NOTES + 1
    )
    if signal is None:
        rows = [row for row in rows if scope.signal(row["signal"])]
    return {
        "notes": [_note(row) for row in rows[:MAX_NOTES]],
        "truncated": len(rows) > MAX_NOTES,
    }


@router.post("", status_code=201)
def add(body: AnnotationIn, user: EditorUser, runtime: RuntimeDep, scope: Scope) -> dict[str, Any]:
    """Keep a note on a signal; answers it and the event that tells it to PlantCraft."""

    in_scope(scope, body.signal)
    try:
        runtime.catalog.point(body.signal)
    except CatalogError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    try:
        start_ms = _ms(body.at, "at")
        end_ms = _ms(body.end, "end")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    assert start_ms is not None
    if end_ms is not None and end_ms < start_ms:
        raise HTTPException(422, t("The note ends before it starts."))
    if end_ms == start_ms:
        end_ms = None
    row = runtime.annotations.add(body.signal, start_ms, end_ms, body.text, user.username, now_ms())
    note = _note(row)
    return {**note, "event": _event(note)}


@router.delete("/{annotation_id}", status_code=204)
def remove(annotation_id: int, user: EditorUser, runtime: RuntimeDep, scope: Scope) -> None:
    """Remove a note: its author, or an administrator."""

    row = runtime.annotations.get(annotation_id)
    if row is None or not scope.signal(row["signal"]):
        raise HTTPException(404, t("Note {id} not found.", id=annotation_id))
    if row["author"] != user.username and not user.is_admin:
        raise HTTPException(403, t("Only its author or an administrator removes a note."))
    runtime.annotations.remove(annotation_id)
