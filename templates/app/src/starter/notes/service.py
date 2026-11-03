"""The notes' rules, without HTTP. The routers validate, call these and answer; only this module
touches the store.

This is where an app grows: when a change to a note must also do something else (write an event
for Alarms, put a to-do in Desk), the service calls it here, never the router. The recipes in
``docs/recipes/`` show each one.
"""

from __future__ import annotations

from typing import Any

from starter.notes.models import NoteDraft
from starter.notes.store import NoteStore


class NoteService:
    def __init__(self, store: NoteStore):
        self.store = store

    def list(self, asset_id: str | None = None) -> list[dict[str, Any]]:
        return self.store.list(asset_id)

    def get(self, note_id: str) -> dict[str, Any] | None:
        return self.store.get(note_id)

    def create(self, draft: NoteDraft, by: str) -> dict[str, Any]:
        return self.store.create(draft, by)

    def update(self, note_id: str, draft: NoteDraft, by: str) -> dict[str, Any] | None:
        return self.store.update(note_id, draft, by)

    def delete(self, note_id: str) -> bool:
        return self.store.delete(note_id)
