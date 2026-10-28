"""A diagram drafted by a language model from what a person describes, then checked here.

``prompt`` tells the model the diagram format (``model.py``), the symbols it may use and the
unit's assets with their signal roles; ``read_answer`` takes its JSON and keeps what the
contract accepts: an element that cannot be drawn is left out, a binding to an asset or role
the unit does not have is dropped, and each repair is a note in words the person can act on.
The model never saves anything: the editor opens the draft, and a person saves it.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import TypeAdapter, ValidationError

from dashcraft.diagrams.model import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    ELEMENT_ID,
    MAX_SIZE,
    MIN_SIZE,
    PAGE_ELEMENTS,
    DiagramPayload,
    Element,
)
from dashcraft.i18n import t

# The symbols a draft may use when the library holds none (yet): common ids; any other id draws
# as a placeholder box.
COMMON_SYMBOLS = (
    "pump.centrifugal",
    "compressor.centrifugal",
    "vessel.tank",
    "vessel.vertical",
    "vessel.horizontal",
    "column.distillation",
    "reactor.stirred",
    "exchanger.shell_tube",
    "heater.furnace",
    "valve.gate",
    "valve.control",
    "valve.check",
    "instrument.bubble",
    "connector.offpage",
    "shape.panel",
)
MAX_ASSETS = 80
MAX_ROLES = 30
MAX_NOTES = 40
STRUCTURE = frozenset({"site", "unit", "area"})
_ELEMENTS: TypeAdapter[Any] = TypeAdapter(Element)
_ID = re.compile(ELEMENT_ID)

FORMAT = """\
Answer with one JSON object and nothing else:
{"name": str, "description": str, "width": 1600, "height": 900, "grid": 10, "elements": [...]}
Coordinates are canvas pixels, x to the right and y down, top-left of each element; keep them
on the grid (multiples of 10) and inside the canvas. Every element has a unique "id"
(letters, digits, - and _) and a "type":
- {"type": "symbol", "id", "symbol": <symbol id>, "x", "y", "w", "h", "label", "asset_id",
   "state": {"item": ITEM}, "level": {"item": ITEM, "min": 0, "max": 100},
   "running": {"item": ITEM, "above": 0.5}}  (bindings optional)
- {"type": "value", "id", "x", "y", "item": ITEM, "label": "PV"}
- {"type": "line", "id", "kind": "process"|"signal"|"utility", "start": {"element": <symbol id>},
   "end": {"element": <symbol id>}, "points": [[x, y], ...], "arrow": "end"}
   (orthogonal corners between the ends; process lines left to right in the flow's direction)
- {"type": "text", "id", "x", "y", "text", "size": 14}
ITEM is {"asset_id": <asset id>, "role": <one of its roles>}, or for a control loop's health
{"asset_id": <loop id>, "result": "linkcraft.loop_health"} (a symbol's state only).
Use only the asset ids and roles listed. Equipment flows left to right; put each loop's
instrument bubble (symbol instrument.bubble) above the equipment it controls, with its PV and SP
as values under it."""


def _parent(asset: dict[str, Any]) -> str | None:
    parent = asset.get("parent_id")
    return parent if isinstance(parent, str) and parent else None


def candidates(assets: list[dict[str, Any]], unit_id: str | None) -> list[dict[str, Any]]:
    """The assets a draft may bind (under ``unit_id``, or the whole plant), with their roles."""

    by_id = {
        asset["id"]: asset
        for asset in assets
        if isinstance(asset, dict) and isinstance(asset.get("id"), str) and asset["id"]
    }
    out = []
    for asset_id, asset in sorted(
        by_id.items(), key=lambda pair: (str(pair[1].get("name")), pair[0])
    ):
        kind = str(asset.get("kind") or "")
        if kind in STRUCTURE or kind == "result" or len(asset_id) > 300:
            continue
        if unit_id is not None:
            seen: set[str] = set()
            current = _parent(asset)
            while current and current != unit_id and current not in seen:
                seen.add(current)
                current = _parent(by_id.get(current) or {})
            if current != unit_id:
                continue
        signals = asset.get("signals") if isinstance(asset.get("signals"), dict) else {}
        out.append(
            {
                "id": asset_id,
                "name": str(asset.get("name") or asset_id)[:80],
                "kind": kind[:60],
                "roles": sorted(str(role) for role in signals)[:MAX_ROLES],
                "relations": [
                    {"type": item.get("type"), "to": item.get("to")}
                    for item in (
                        asset.get("relations") if isinstance(asset.get("relations"), list) else []
                    )
                    if isinstance(item, dict)
                ][:8],
            }
        )
        if len(out) >= MAX_ASSETS:
            break
    return out


def prompt(
    description: str, symbol_ids: list[str], assets: list[dict[str, Any]], unit: str | None
) -> tuple[str, str]:
    """The system text and the question for the model."""

    system = (
        "You draw process graphics (P&ID-like overview diagrams) for a plant's control room. "
        + FORMAT
    )
    symbols = symbol_ids or list(COMMON_SYMBOLS)
    question = "\n".join(
        [
            f"Draw this diagram: {description.strip()}",
            f"Unit: {unit}" if unit else "Unit: not given (bind only assets listed below).",
            "Symbol ids: " + ", ".join(symbols),
            "Assets (id, name, kind, signal roles, relations):",
            json.dumps(assets, ensure_ascii=False, separators=(",", ":")),
        ]
    )
    return system, question


def _json(text: str) -> Any:
    """The JSON object in a model's answer: bare, or inside a code fence or some words."""

    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object")
    return json.loads(text[start : end + 1])


def _reason(exc: ValidationError) -> str:
    first = exc.errors()[0] if exc.errors() else {}
    where = ".".join(str(part) for part in first.get("loc", ()) if not isinstance(part, int))
    message = str(first.get("msg", "")).removeprefix("Value error, ")
    return f"{where}: {message}" if where else message


def _number(value: Any, default: int, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    return int(min(high, max(low, value)))


class _Repair:
    def __init__(self, known: dict[str, set[str]] | None, symbols: set[str]):
        self.known = known
        self.symbols = symbols
        self.notes: list[str] = []

    def note(self, text: str) -> None:
        if len(self.notes) < MAX_NOTES:
            self.notes.append(text)

    def item_problem(self, item: Any) -> str | None:
        """Why a binding's item cannot stay (an asset or role the unit lacks), else None."""

        if not isinstance(item, dict) or self.known is None:
            return None
        asset_id = item.get("asset_id")
        if not asset_id or item.get("signal_id"):
            return None
        if asset_id not in self.known:
            return t("asset {asset} is not in the unit", asset=str(asset_id)[:60])
        role = item.get("role")
        if role and item.get("result") is None and role not in self.known[asset_id]:
            return t(
                "{asset} has no signal role {role}", asset=str(asset_id)[:60], role=str(role)[:40]
            )
        return None

    def element(self, raw: Any, index: int, taken: set[str]) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            self.note(t("Element {n} left out: it is not an object.", n=index + 1))
            return None
        element = dict(raw)
        given = element.get("id")
        if not isinstance(given, str) or not _ID.match(given) or given in taken:
            element["id"] = f"el-{index + 1}"
            while element["id"] in taken:
                element["id"] += "x"
        label = element["id"]
        kind = element.get("type")
        if kind == "symbol":
            for slot in ("state", "level", "running"):
                binding = element.get(slot)
                if binding is None:
                    continue
                problem = (
                    self.item_problem(binding.get("item"))
                    if isinstance(binding, dict)
                    else t("not a binding")
                )
                if problem is None and isinstance(binding, dict):
                    try:
                        _ELEMENTS.validate_python(
                            {"type": "symbol", "id": "x", "symbol": "a", slot: binding}
                        )
                    except ValidationError as exc:
                        problem = _reason(exc)
                if problem:
                    element.pop(slot, None)
                    self.note(
                        t(
                            "The {slot} of {element} was dropped: {reason}.",
                            slot=slot,
                            element=label,
                            reason=problem,
                        )
                    )
        elif kind == "value":
            problem = self.item_problem(element.get("item"))
            if problem:
                self.note(t("Value {element} left out: {reason}.", element=label, reason=problem))
                return None
        elif kind == "line" and isinstance(element.get("flow"), dict):
            problem = self.item_problem(element["flow"].get("item"))
            if problem:
                element.pop("flow")
                self.note(
                    t("The flow of {element} was dropped: {reason}.", element=label, reason=problem)
                )
        try:
            checked = _ELEMENTS.validate_python(element)
        except ValidationError as exc:
            self.note(
                t("Element {element} left out: {reason}.", element=label, reason=_reason(exc))
            )
            return None
        out = checked.model_dump(exclude_none=True)
        if out["type"] == "symbol" and self.symbols and out["symbol"] not in self.symbols:
            self.note(
                t(
                    "{element} uses the symbol {symbol}, which the library lacks: it draws as a box.",
                    element=label,
                    symbol=out["symbol"],
                )
            )
        return out


def read_answer(
    text: str,
    *,
    known: dict[str, set[str]] | None,
    symbols: set[str],
    fallback_name: str,
) -> tuple[dict[str, Any], list[str]]:
    """The draft a model's answer holds, repaired to the contract, and the notes on what changed.

    ``known`` maps the asset ids a binding may name to their roles (None: not checked).
    An answer that holds no diagram gives an empty one named ``fallback_name``.
    """

    repair = _Repair(known, symbols)
    try:
        raw = _json(text)
    except ValueError:
        raw = None
    if not isinstance(raw, dict):
        repair.note(
            t("The model's answer held no process display. Try again, or describe it differently.")
        )
        raw = {}
    name = raw.get("name") if isinstance(raw.get("name"), str) else ""
    name = (name.strip() or fallback_name.strip() or t("Draft process display"))[:80]
    description = raw.get("description") if isinstance(raw.get("description"), str) else ""
    elements_in = raw.get("elements") if isinstance(raw.get("elements"), list) else []
    if len(elements_in) > PAGE_ELEMENTS:
        repair.note(t("Only the first {n} elements were kept.", n=PAGE_ELEMENTS))
        elements_in = elements_in[:PAGE_ELEMENTS]
    elements: list[dict[str, Any]] = []
    taken: set[str] = set()
    for index, item in enumerate(elements_in):
        kept = repair.element(item, index, taken)
        if kept is not None:
            taken.add(kept["id"])
            elements.append(kept)
    # A line to a symbol left out loses that end, and the line when it cannot be drawn.
    symbol_ids = {item["id"] for item in elements if item["type"] == "symbol"}
    final: list[dict[str, Any]] = []
    for item in elements:
        if item["type"] == "line":
            for end in ("start", "end"):
                if item.get(end) and item[end]["element"] not in symbol_ids:
                    item.pop(end)
            ends = sum(1 for end in ("start", "end") if item.get(end))
            if len(item.get("points") or []) + ends < 2:
                repair.note(
                    t("Line {element} left out: it joins no symbol drawn.", element=item["id"])
                )
                continue
        final.append(item)
    payload = {
        "name": name,
        "description": description[:400],
        "width": _number(raw.get("width"), DEFAULT_WIDTH, MIN_SIZE, MAX_SIZE),
        "height": _number(raw.get("height"), DEFAULT_HEIGHT, MIN_SIZE, MAX_SIZE),
        "grid": _number(raw.get("grid"), 10, 0, 100),
        "elements": final,
    }
    try:
        diagram = DiagramPayload.model_validate(payload).stored()
    except ValidationError as exc:
        repair.note(t("The draft could not be kept as drawn: {reason}.", reason=_reason(exc)))
        diagram = DiagramPayload.model_validate({**payload, "elements": []}).stored()
    return diagram, repair.notes
