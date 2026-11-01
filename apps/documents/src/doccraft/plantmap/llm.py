"""A diagram read again with a language model that reads images (``[[contributes.llm]]``
``diagram-read`` in ``app.toml``), asked through PlantCraft (``POST /api/v1/llm/{use}``):
PlantCraft picks the model, keeps the key and counts the calls; Documents never sees either.
The use ships off until an administrator gives it a model in Setup › Language models.

The page's image goes with what the drawing reader found on it ("hybrid": on scans of the demo
plant, gpt-5-mini read the lines with precision 0.93 and recall 0.97, where OCR reads none).
What the model adds is marked as the model's and of medium certainty at most: people check it
on the map (Correct / Wrong)."""

from __future__ import annotations

import io
import json
import re
from typing import Any

from plantcraft_sdk.client import PlantCraftError

from doccraft.i18n import t
from doccraft.plantmap.reader import tags as isa

USE = "diagram-read"
KINDS = ("feeds", "measures", "controls", "signal", "on")
# The longest side of the page sent to the model, in pixels: enough to read a tag on an A1 sheet.
MAX_SIDE = 2400

PROMPT = """You read a P&ID (piping and instrumentation diagram, ISA-5.1 or DIN/ISO 10628).
Return JSON only, with this shape:
{"items": [{"tag": "P-1001", "family": "equipment|instrument", "cls": "pump|vessel|column|
 heat_exchanger|reactor|tank|furnace|compressor|controller|transmitter|valve|indicator|other"}],
 "relations": [{"from": "TAG", "type": "feeds|measures|controls|signal|on", "to": "TAG"}]}
Rules: feeds = process line from equipment to equipment (through valves, following arrows, or
to the equipment named by an off-page connector). measures = instrument to the equipment it
measures. controls = controller to its valve. signal = transmitter to its controller (dashed
line). on = valve to the equipment upstream on its line. Line numbers and sheet numbers are not
tags. Do not invent anything that is not drawn."""


class NoModel(Exception):
    """No model for this use now (off, or none set up), or Documents has no app key."""


def page_image(png: bytes) -> bytes:
    """The page, at most ``MAX_SIDE`` pixels on its longest side, as PNG."""

    from PIL import Image

    image = Image.open(io.BytesIO(png))
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    image.convert("L").save(out, format="PNG", optimize=True)
    return out.getvalue()


def ask(client: Any, png: bytes, result: dict[str, Any]) -> dict[str, Any]:
    """The model's reading of the page: ``{"items", "relations"}`` (raises NoModel when there is
    no model, PlantCraftError when PlantCraft could not answer, ValueError on an answer that is
    not the JSON asked for)."""

    if client is None:
        raise NoModel(t("This installation gave Documents no app key, so it cannot ask a model."))
    found = {
        "items": [{"tag": i["tag"], "cls": i["cls"]} for i in result["items"] if i.get("tag")],
        "relations": [{k: r[k] for k in ("from", "type", "to")} for r in result["relations"]],
    }
    question = (
        "A classical reader found this on the page; it may miss or misread tags and lines. "
        "Correct and complete it:\n" + json.dumps(found)
    )
    try:
        answer = client.llm(USE, question, system=PROMPT, images=[page_image(png)])
    except PlantCraftError as exc:
        if exc.status_code in (404, 409):
            raise NoModel(str(exc.detail)) from exc
        raise
    text = str((answer or {}).get("text") or "")
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(t("The model's answer is not JSON."))
    return json.loads(match.group(0))


def _tag(text: Any) -> isa.Tag | None:
    word = str(text or "").upper()
    return isa.parse(word) or isa.parse(word, in_bubble=True)


def merge(result: dict[str, Any], answer: dict[str, Any], model: str = "") -> dict[str, Any]:
    """The page's result with what the model adds: tags and relations the reader did not find,
    each of medium certainty and named as the model's. What the reader found stays as it was."""

    why = "read by the language model" + (f" ({model})" if model else "") + "; check it"
    items = list(result["items"])
    known = {i["tag"] for i in items if i.get("tag")}
    for raw in answer.get("items") or []:
        if not isinstance(raw, dict):
            continue
        parsed = _tag(raw.get("tag"))
        if parsed is None or parsed.tag in known:
            continue
        known.add(parsed.tag)
        items.append(
            {
                "id": parsed.tag,
                "family": parsed.family,
                "cls": parsed.cls,
                "box": [0, 0, 0, 0],
                "tag": parsed.tag,
                "label": parsed.tag,
                "confidence": "medium",
                "why": why,
            }
        )
    relations = list(result["relations"])
    seen = {(r["from"], r["type"], r["to"]) for r in relations}
    for raw in answer.get("relations") or []:
        if not isinstance(raw, dict) or raw.get("type") not in KINDS:
            continue
        ends = [_tag(raw.get(k)) for k in ("from", "to")]
        if None in ends:
            continue
        key = (ends[0].tag, raw["type"], ends[1].tag)
        if key in seen or key[0] == key[2] or not {key[0], key[2]} <= known:
            continue
        seen.add(key)
        relations.append(
            {"from": key[0], "type": key[1], "to": key[2], "confidence": "medium", "why": why}
        )
    notes = [n for n in result.get("notes") or [] if not n.startswith("Read again with")]
    added = (len(items) - len(result["items"]), len(relations) - len(result["relations"]))
    notes.append(f"Read again with the language model: {added[0]} tags and {added[1]} lines added.")
    return {**result, "items": items, "relations": relations, "notes": notes, "llm": model or "yes"}
