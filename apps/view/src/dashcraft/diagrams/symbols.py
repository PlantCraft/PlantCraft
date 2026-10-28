"""The symbol library: one JSON file per symbol in ``symbols/<category>/<id>.json` (pumps, vessels, valves...)`.

A symbol is a small SVG drawing on its own ``viewBox`` (``0 0 w h``) with named **ports** where
lines join it, and optional **anchors** where the diagram writes its tag or value. The drawing
holds basic shapes only and no colours of its own: the page paints it from the suite's theme
(``fill: var(--pc-symbol-fill); stroke: currentColor``), and by class:

- ``pc-state``: the colour of the symbol's state (ok, warning, alarm, unknown);
- ``pc-run``: lit while the symbol is running;
- ``pc-level``: a rectangle over the part that fills (a tank's straight side), filled from the
  bottom by the level binding.

Every drawing passes ``clean_svg`` before it is served: elements and attributes outside the
lists below are dropped, so a symbol can never carry a script, a style sheet, a link or an
image (the same filter will guard symbols people import).
"""

from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dashcraft.diagrams.model import PORT_ID, SYMBOL_ID

LOGGER = logging.getLogger(__name__)
LIBRARY = Path(__file__).resolve().parent / "symbols"
SVG_NS = "http://www.w3.org/2000/svg"
MAX_SVG_LENGTH = 40_000
MAX_DEPTH = 8

TAGS = frozenset(
    {"g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text", "tspan"}
)
GEOMETRY = frozenset(
    {
        "d",
        "x",
        "y",
        "x1",
        "y1",
        "x2",
        "y2",
        "cx",
        "cy",
        "r",
        "rx",
        "ry",
        "width",
        "height",
        "points",
        "dx",
        "dy",
    }
)
PAINT = frozenset({"fill", "stroke"})
STYLE = frozenset(
    {
        "stroke-width",
        "stroke-linecap",
        "stroke-linejoin",
        "stroke-dasharray",
        "stroke-miterlimit",
        "opacity",
        "fill-opacity",
        "stroke-opacity",
        "fill-rule",
        "font-size",
        "font-weight",
        "text-anchor",
        "dominant-baseline",
    }
)
CLASS = re.compile(r"^[a-z][a-z0-9-]{0,30}( [a-z][a-z0-9-]{0,30}){0,5}$")
PAINT_VALUE = re.compile(r"^(none|currentColor|var\(--pc-[a-z0-9-]{1,40}\))$")
# Numbers, path commands, lists and units: never a url(), an expression or an entity.
SAFE_VALUE = re.compile(r"^[A-Za-z0-9 .,+\-#%]{0,4000}$")
TRANSFORM = re.compile(r"^((translate|rotate|scale)\([0-9 .,+\-]{1,60}\)\s*){1,4}$")


class Port(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(pattern=PORT_ID)
    x: float
    y: float
    dir: Literal["n", "s", "e", "w"] = "e"
    kind: Literal["process", "signal", "utility", "mechanical"] = "process"


class Anchor(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(pattern=PORT_ID)
    x: float
    y: float
    align: Literal["start", "middle", "end"] = "middle"


class Symbol(BaseModel):
    """One symbol as its file holds it; unknown fields are kept out, not refused."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(pattern=SYMBOL_ID)
    title: str = Field(min_length=1, max_length=80)
    category: str = Field(min_length=1, max_length=40)
    w: float = Field(gt=0, le=1000)
    h: float = Field(gt=0, le=1000)
    svg: str = Field(min_length=1, max_length=MAX_SVG_LENGTH)
    ports: list[Port] = Field(default_factory=list, max_length=24)
    anchors: list[Anchor] = Field(default_factory=list, max_length=12)
    keywords: list[str] = Field(default_factory=list, max_length=20)
    standard: str = Field(default="", max_length=80)
    # What a symbol of this kind usually draws (asset types of PlantCraft: pump, tank...).
    asset_types: list[str] = Field(default_factory=list, max_length=12)
    # A shape that may take any proportions (a unit block, an off-page connector); every other
    # drawing keeps its own, whatever box it is given.
    stretch: bool = False


class UnsafeSvg(ValueError):
    """The drawing is not well-formed, or holds nothing that can be drawn."""


def _clean(node: ET.Element, depth: int) -> ET.Element | None:
    tag = node.tag.split("}", 1)[-1]
    if tag not in TAGS or depth > MAX_DEPTH:
        return None
    out = ET.Element(tag)
    for name, value in node.attrib.items():
        name = name.split("}", 1)[-1] if name.startswith("{") else name
        value = value.strip()
        if name in GEOMETRY or name in STYLE:
            if SAFE_VALUE.match(value):
                out.set(name, value)
        elif name in PAINT:
            if PAINT_VALUE.match(value):
                out.set(name, value)
        elif name == "class":
            if CLASS.match(value):
                out.set(name, value)
        elif name == "transform":
            if TRANSFORM.match(value):
                out.set(name, value)
    if tag in ("text", "tspan"):
        out.text = (node.text or "")[:80]
    for child in node:
        cleaned = _clean(child, depth + 1)
        if cleaned is not None:
            out.append(cleaned)
    return out


def clean_svg(svg: str) -> str:
    """The drawing with only the shapes and attributes above (raises UnsafeSvg when nothing of
    it can be read). Entities and doctypes are refused before parsing."""

    if len(svg) > MAX_SVG_LENGTH:
        raise UnsafeSvg("The drawing is too long.")
    if "<!" in svg or "<?" in svg or "&" in svg:
        raise UnsafeSvg("The drawing holds a doctype, an entity or an instruction.")
    try:
        root = ET.fromstring(f'<svg xmlns="{SVG_NS}">{svg}</svg>')
    except ET.ParseError as exc:
        raise UnsafeSvg(f"The drawing is not well-formed: {exc}") from exc
    kept = [cleaned for child in root if (cleaned := _clean(child, 1)) is not None]
    if not kept:
        raise UnsafeSvg("The drawing has no shapes.")
    ET.register_namespace("", SVG_NS)
    return "".join(ET.tostring(node, encoding="unicode") for node in kept)


def load_symbol(path: Path) -> Symbol:
    """One file, checked and with its drawing cleaned (ValueError when it cannot be used)."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path.name}: not a JSON file ({exc})") from exc
    try:
        symbol = Symbol.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"{path.name}: {exc}") from exc
    for port in symbol.ports:
        if not (0 <= port.x <= symbol.w and 0 <= port.y <= symbol.h):
            raise ValueError(f"{path.name}: port {port.id} is outside the symbol")
    if len({port.id for port in symbol.ports}) != len(symbol.ports):
        raise ValueError(f"{path.name}: two ports have the same id")
    return symbol.model_copy(update={"svg": clean_svg(symbol.svg)})


@lru_cache(maxsize=4)
def _library(root: str) -> tuple[dict[str, Any], ...]:
    found: dict[str, dict[str, Any]] = {}
    for path in sorted(Path(root).glob("*/*.json")):
        try:
            symbol = load_symbol(path)
        except ValueError:
            # A broken file never stops the others (tests/test_diagram_symbols.py fails on it).
            LOGGER.warning("Symbol %s left out", path, exc_info=True)
            continue
        if symbol.id in found:
            LOGGER.warning("Symbol %s defined twice; %s left out", symbol.id, path)
            continue
        found[symbol.id] = symbol.model_dump()
    return tuple(sorted(found.values(), key=lambda item: (item["category"], item["title"])))


def library(root: Path = LIBRARY) -> list[dict[str, Any]]:
    """Every usable symbol, by category then title (read once per process)."""

    return list(_library(str(root)))


def symbol_ids(root: Path = LIBRARY) -> set[str]:
    return {item["id"] for item in library(root)}
