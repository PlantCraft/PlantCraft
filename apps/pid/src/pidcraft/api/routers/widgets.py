"""HTTP routes: PlantCraft PID's widgets, for its Overview and Desk's Today (PlantCraft's
docs/widgets.md). Declared in app.toml ``[[contributes.widgets]]``; each answer is one of the
suite's shapes, built by ``plantcraft_sdk.widgets``."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from plantcraft_sdk import widgets as w

from pidcraft.api.deps import CurrentUser, RuntimeDep
from pidcraft.i18n import t
from pidcraft.meta import FILES

router = APIRouter(prefix="/api/widgets")


@router.get("")
def widgets(_user: CurrentUser) -> dict[str, Any]:
    return w.catalog(FILES.manifest(), t)


@router.get("/{widget_id}")
def widget(widget_id: str, rt: RuntimeDep, _user: CurrentUser) -> dict[str, Any]:
    root = rt.settings.root_path
    drawings = rt.drawings.list()
    if widget_id == "count":
        return w.number(len(drawings), label=t("drawings"), href=f"{root}/drawings")
    if widget_id == "latest":
        latest = sorted(drawings, key=lambda d: d.get("uploaded_at") or "", reverse=True)[:8]
        return w.items(
            [
                w.item(
                    drawing["number"],
                    detail=drawing["title"] or drawing["unit"],
                    href=f"{root}/drawings/{drawing['drawing_id']}",
                )
                for drawing in latest
            ],
            href=f"{root}/drawings",
            empty=t("No drawing yet."),
        )
    raise HTTPException(status_code=404, detail=t("Widget not found."))
