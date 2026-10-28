"""Diagrams that start from somewhere: drawn from a unit's assets, drafted by a language model
from what a person describes, or drawn for every unit of a new plant (``[[contributes.start]]``).
Plus a diagram as a reference (``#diagram:<id>``, ``[[contributes.refs]]``).

The drafts are not saved: the editor opens them and a person saves. Assets are read as the
editor (``Runtime.user_reader``), so PlantCraft's permissions decide what a draft can bind.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from plantcraft_sdk.client import PlantCraftError
from plantcraft_sdk.contributes import StartIn, StartOut
from pydantic import BaseModel, Field

from dashcraft.api.deps import CurrentUser, EditorUser, EditorView, RuntimeDep, guarded
from dashcraft.api.routers.diagrams import diagram_or_404
from dashcraft.diagrams.autodraw import draw_unit, plant_display
from dashcraft.diagrams.draft import candidates, prompt, read_answer
from dashcraft.diagrams.symbols import library
from dashcraft.i18n import t
from dashcraft.suite.llm import DIAGRAM_DRAFT, NoModel

router = APIRouter(prefix="/api", tags=["diagrams"])


class DrawIn(BaseModel):
    unit_id: str = Field(min_length=1, max_length=300)


class DraftIn(BaseModel):
    description: str = Field(min_length=1, max_length=2000)
    unit_id: str | None = Field(default=None, max_length=300)


def _assets(rt: Any, user: Any) -> list[dict[str, Any]]:
    reader = rt.user_reader(user)
    found = guarded(lambda: reader.assets(None), service=False)
    return [item for item in found or [] if isinstance(item, dict)]


def _unit(assets: list[dict[str, Any]], unit_id: str) -> dict[str, Any]:
    found = next((item for item in assets if item.get("id") == unit_id), None)
    if found is None:
        raise HTTPException(status_code=404, detail=t("Unit not found."))
    return found


@router.post("/diagrams/draw-from-assets")
def draw_from_assets(body: DrawIn, rt: RuntimeDep, user: EditorView) -> dict[str, Any]:
    """The unit's diagram laid out from its assets and relations (``diagrams/autodraw.py``):
    ``{diagram, notes}``, not saved."""

    assets = _assets(rt, user)
    _unit(assets, body.unit_id)
    drawn = draw_unit(assets, body.unit_id, library=library())
    if drawn is None:  # pragma: no cover - the unit was found above
        raise HTTPException(status_code=404, detail=t("Unit not found."))
    diagram, notes = drawn
    return {"diagram": diagram, "notes": notes}


@router.post("/diagrams/draft")
def draft_diagram(body: DraftIn, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    """A diagram drafted by the model PlantCraft gives the use ``diagram-draft``, from what the
    person describes, checked against the format and the unit's assets: ``{diagram, notes}``."""

    description = body.description.strip()
    if not description:
        raise HTTPException(status_code=422, detail=t("Say what the process display should show."))
    assets = _assets(rt, user)
    unit_name = None
    if body.unit_id:
        unit_name = str(_unit(assets, body.unit_id).get("name") or body.unit_id)
    offered = candidates(assets, body.unit_id or None)
    symbols = [str(item["id"]) for item in library()]
    system, question = prompt(description, symbols, offered, unit_name)
    try:
        answer = rt.suite.ask_model(DIAGRAM_DRAFT, question, system=system)
    except NoModel as exc:
        raise HTTPException(
            status_code=409,
            detail=t(
                "No language model drafts process displays here: an administrator gives View's use "
                "{use} a model in Setup › Language models. ({reason})",
                use=DIAGRAM_DRAFT,
                reason=str(exc)[:200],
            ),
        ) from exc
    except PlantCraftError as exc:
        raise HTTPException(
            status_code=502,
            detail=t("The language model could not answer: {reason}", reason=str(exc.detail)[:300]),
        ) from exc
    known = {item["id"]: set(item["roles"]) for item in offered}
    diagram, notes = read_answer(
        answer,
        known=known,
        symbols=set(symbols),
        fallback_name=(unit_name and t("{unit} process display", unit=unit_name))
        or description[:60],
    )
    return {"diagram": diagram, "notes": notes}


@router.post("/start/unit-diagrams")
def start_unit_diagrams(body: StartIn, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    """A new plant's first step here (``[[contributes.start]]``): one process display of the
    plant with a page for each of its units, drawn from the assets as this person, in General.
    A display of that name in General is kept."""

    assets = _assets(rt, user)
    name = t("Plant process")
    taken = {item["name"] for item in rt.diagrams.list() if not item.get("folder_id")}
    created = kept = pages = 0
    if name in taken:
        kept = 1
    else:
        draft = plant_display(assets, body.units, name=name, library=library())
        if draft is not None:
            item = rt.diagrams.create(draft, user.username)
            rt.audit(user, "diagram.create", item["diagram_id"], {"name": item["name"]})
            created, pages = 1, len(draft.get("pages") or [])
    summary = t(
        "The plant's process display was drawn in General, a page per unit ({pages}).", pages=pages
    )
    if kept:
        summary = t("The plant's process display was there already.")
    elif not created:
        summary = t("No unit had equipment to draw.")
    counts = {"created": created, "kept": kept, "pages": pages}
    return StartOut(summary=summary, counts=counts, open="/dash/diagrams").model_dump()


@router.get("/refs/diagram/{diagram_id}")
def diagram_ref(diagram_id: str, rt: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    """What ``#diagram:<id>`` names, for whoever reads it (a closed folder answers 404)."""

    found = diagram_or_404(rt, diagram_id, user)
    return {
        "title": found["name"],
        "status": t("{n} elements", n=len(found.get("elements") or [])),
        "url": f"{rt.settings.root_path}/diagrams/{diagram_id}",
    }
