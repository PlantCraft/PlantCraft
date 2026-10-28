"""The notes' rules, without HTTP: what a change to a note sends to PlantCraft (``starter.suite``).

The routers validate, call these and answer; only this module touches the store."""

from __future__ import annotations

from typing import Any

from starter.notes.models import NoteDraft
from starter.notes.store import NoteStore
from starter.suite import Suite


class NoteService:
    def __init__(self, store: NoteStore, suite: Suite):
        self.store = store
        self.suite = suite

    def list(self, asset_id: str | None = None) -> list[dict[str, Any]]:
        return self.store.list(asset_id)

    def get(self, note_id: str) -> dict[str, Any] | None:
        return self.store.get(note_id)

    def create(self, draft: NoteDraft, by: str, asset_name: str) -> dict[str, Any]:
        note = self.store.create(draft, by)
        self.suite.note_written(note, asset_name)
        self._follow_up(note, asset_name)
        return note

    def update(self, note_id: str, draft: NoteDraft, by: str, asset_name: str) -> dict[str, Any]:
        note = self.store.update(note_id, draft, by) or {}
        if note:
            self._follow_up(note, asset_name)
        return note

    def delete(self, note_id: str) -> None:
        if self.store.delete(note_id):
            self.suite.close_follow_up(note_id)
            self.suite.follow_ups(self.store.follow_ups())

    def summary(self, note_id: str) -> str:
        note = self.store.get(note_id) or {}
        return self.suite.summary(note.get("text") or "")

    def _follow_up(self, note: dict[str, Any], asset_name: str) -> None:
        self.suite.follow_up_todo(note, asset_name)
        self.suite.follow_ups(self.store.follow_ups())
