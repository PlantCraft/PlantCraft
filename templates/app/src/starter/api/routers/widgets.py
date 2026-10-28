"""HTTP routes: StarterCraft's widgets, for its Overview and Desk's Today (PlantCraft's
docs/widgets.md). Declared in app.toml ``[[contributes.widgets]]``; each answer is one of the
suite's shapes, built by ``plantcraft_sdk.widgets``."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from plantcraft_sdk import widgets as w

from starter.api.deps import CurrentUser, RuntimeDep
from starter.i18n import t
from starter.meta import FILES

router = APIRouter(prefix="/api/widgets")


@router.get("")
def widgets(_user: CurrentUser) -> dict[str, Any]:
    return w.catalog(FILES.manifest(), t)


@router.get("/{widget_id}")
def widget(widget_id: str, rt: RuntimeDep, _user: CurrentUser) -> dict[str, Any]:
    root = rt.settings.root_path
    notes = rt.notes.list()
    if widget_id == "count":
        return w.number(len(notes), label=t("notes"), href=f"{root}/notes")
    if widget_id == "latest":
        return w.items(
            [
                w.item(
                    note["text"][:80],
                    detail=note["asset_id"],
                    href=f"{root}/notes/{note['note_id']}",
                )
                for note in notes[:8]
            ],
            href=f"{root}/notes",
            empty=t("No note yet."),
        )
    raise HTTPException(status_code=404, detail=t("Widget not found."))
