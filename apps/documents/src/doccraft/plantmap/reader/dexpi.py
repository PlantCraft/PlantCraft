"""A DEXPI file (Proteus XML, dexpi.org) read straight into what the drawing reader gives.

A P&ID tool (AVEVA, Hexagon Smart P&ID, Siemens COMOS...) can save its drawing as DEXPI, the
open exchange format for P&IDs. It holds the plant's data, not only lines: each piece of
equipment with its class and tag, each piping segment with what it connects, and each
instrument function with its sensor and its valve. So nothing is guessed: every item and
relation is certain ("high"), and the page is the same shape as a drawing read by
``graph.recognise`` (items with boxes, relations), so the plant map, the search and the review
page treat it like any other sheet.

Our own reader: pyDEXPI is AGPL-3.0 and is not used. Tested on the public DEXPI training test
cases (gitlab.com/dexpi/TrainingTestCases, CC BY 4.0).

What is read:

* **Equipment** with a tag (``TagName``), its kind from its DEXPI class.
* **Instruments**: each process instrumentation function (``PICSA 4712.02``), and its valve
  (the actuating function, ``PV-4712.02``).
* **Hand valves** with a tag on the piping.
* **Relations**: equipment ``feeds`` equipment when piping joins them (through valves and tees);
  an instrument ``measures`` the equipment its sensor sits on, or the equipment upstream of the
  line it sits on; an instrument ``controls`` its valve; a valve is ``on`` the line leaving the
  equipment upstream.

``draw_svg`` draws the sheet (its lines, circles and texts, and a box for each item) so the
review page has a picture; the file itself is never sent to the browser.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET  # noqa: S405 - a DOCTYPE (entities) is refused before parsing
from collections import defaultdict
from html import escape
from typing import Any

from doccraft.plantmap.reader import tags as isa
from doccraft.plantmap.reader.svg import DrawingError

MM = 1000.0  # DEXPI coordinates are in metres; the page is drawn in millimetres
# DEXPI equipment classes (by the end of the name) to the map's kinds.
KINDS = (
    ("Pump", "pump"),
    ("Compressor", "compressor"),
    ("Blower", "blower"),
    ("Fan", "blower"),
    ("HeatExchanger", "heat_exchanger"),
    ("Cooler", "heat_exchanger"),
    ("Heater", "heat_exchanger"),
    ("Furnace", "furnace"),
    ("Column", "column"),
    ("Tank", "tank"),
    ("Silo", "tank"),
    ("Vessel", "vessel"),
    ("Separator", "separator"),
    ("Reactor", "reactor"),
    ("Filter", "filter"),
    ("Agitator", "mixer"),
    ("Mixer", "mixer"),
)
PARTS = {"Nozzle", "Chamber", "Impeller", "Displacer", "TubeBundle"}
SPACE = re.compile(r"\s+")


def is_dexpi(data: bytes) -> bool:
    return b"<PlantModel" in data[:4096]


def _root(data: bytes) -> ET.Element:
    head = data[:4096].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in data.upper():
        raise DrawingError("A DEXPI file with a DOCTYPE or entities is not read.")
    try:
        root = ET.fromstring(data)  # noqa: S314 - no DOCTYPE, so no entity can expand
    except ET.ParseError as error:
        raise DrawingError(f"The DEXPI file is not valid XML: {error}.") from error
    if root.tag != "PlantModel":
        raise DrawingError("The XML file is not DEXPI (no PlantModel).")
    return root


def _attrs(element: ET.Element) -> dict[str, str]:
    return {
        g.get("Name") or "": g.get("Value") or ""
        for g in element.findall("GenericAttributes/GenericAttribute")
    }


def _tag(text: str, *, instrument: bool = False) -> isa.Tag | None:
    """``P4711``, ``HV 4750.01``, ``PICSA 4712.02``, ``H-1007`` -> the normalised tag."""

    word = SPACE.sub("", (text or "").strip())
    if not word:
        return None
    return isa.parse(word, in_bubble=instrument) or isa.parse(word)


def _own_tag(text: str, component_class: str) -> isa.Tag | None:
    """A tag that is not ISA-shaped (``006``, ``D-02-B``): the P&ID tool named it, so keep it."""

    word = SPACE.sub("", (text or "").strip()).upper()
    if not word or len(word) > 30 or word.endswith("?"):
        return None
    return isa.Tag(word, "", word, "equipment", _kind(component_class))


def _kind(component_class: str) -> str:
    for end, kind in KINDS:
        if component_class.endswith(end):
            return kind
    return "equipment"


class _Sheet:
    """Coordinates: DEXPI's (metres, y up) to the page's (millimetres, y down)."""

    def __init__(self, root: ET.Element) -> None:
        extent = root.find("Drawing/Extent")
        if extent is None:
            extent = root.find("Extent")
        x0 = y0 = 0.0
        x1, y1 = 0.841, 0.594  # A1 when the file gives no size
        if extent is not None and extent.find("Max") is not None:
            lo, hi = extent.find("Min"), extent.find("Max")
            x0, y0 = float(lo.get("X", 0)), float(lo.get("Y", 0))
            x1, y1 = float(hi.get("X", x1)), float(hi.get("Y", y1))
        self.x0, self.y1 = x0, y1
        self.width = max((x1 - x0) * MM, 1.0)
        self.height = max((y1 - y0) * MM, 1.0)

    def point(self, element: ET.Element) -> tuple[float, float]:
        return (
            (float(element.get("X", 0)) - self.x0) * MM,
            (self.y1 - float(element.get("Y", 0))) * MM,
        )

    def box(self, element: ET.Element) -> list[float] | None:
        extent = element.find("Extent")
        if extent is not None and extent.find("Min") is not None:
            ax, ay = self.point(extent.find("Min"))
            bx, by = self.point(extent.find("Max"))
            if (ax, ay) != (bx, by):
                return [min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)]
        location = element.find("Position/Location")
        if location is not None:
            x, y = self.point(location)
            return [x - 5, y - 5, x + 5, y + 5]
        for child in element:
            if child.tag in {"Label", "PipingComponent", "ActuatingSystemComponent"}:
                found = self.box(child)
                if found:
                    return found
        return None


def _instances(root: ET.Element) -> list[ET.Element]:
    """Every element outside the shape catalogue (which only holds symbol definitions)."""

    out = []
    for child in root:
        if child.tag != "ShapeCatalogue":
            out.extend(child.iter())
    return out


def read_dexpi(data: bytes) -> list[dict[str, Any]]:
    """The one sheet of a DEXPI file, as ``read_drawing`` gives a page."""

    root = _root(data)
    sheet = _Sheet(root)
    elements = _instances(root)
    by_id = {e.get("ID"): e for e in elements if e.get("ID")}
    items: dict[str, dict[str, Any]] = {}
    relations: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add(tag: isa.Tag, family: str, cls: str, element: ET.Element | None, why: str) -> str:
        if tag.tag not in items:
            box = (sheet.box(element) if element is not None else None) or [0.0, 0.0, 0.0, 0.0]
            items[tag.tag] = {
                "id": tag.tag,
                "tag": tag.tag,
                "family": family,
                "cls": cls,
                "label": "",
                "box": [round(v, 1) for v in box],
                "confidence": "high",
                "why": why,
            }
        return tag.tag

    def relate(frm: str, kind: str, to: str, why: str) -> None:
        if frm != to:
            relations.setdefault(
                (frm, kind, to),
                {"from": frm, "type": kind, "to": to, "confidence": "high", "why": why},
            )

    # Equipment, and which IDs (nozzles, parts) belong to each.
    owner: dict[str, tuple[str, str]] = {}  # ID -> ("eq", tag) or ("seg", segment ID)
    for e in root.findall("Equipment"):
        stack = [e]
        while stack:
            eq = stack.pop()
            cls = eq.get("ComponentClass") or ""
            tag = _tag(eq.get("TagName") or "") or _own_tag(eq.get("TagName") or "", cls)
            if tag and cls not in PARTS:
                name = add(tag, "equipment", _kind(cls), eq, f"equipment in the DEXPI file ({cls})")
                for n in eq.iter():
                    if n.get("ID"):
                        owner.setdefault(n.get("ID"), ("eq", name))
            stack.extend(eq.findall("Equipment"))
    segments = [e for e in elements if e.tag == "PipingNetworkSegment"]
    for s in segments:
        for n in s.iter():
            if n.get("ID") and n.get("ID") not in owner:
                owner[n.get("ID")] = ("seg", s.get("ID"))
    for s in elements:
        if s.tag == "PipingNetworkSystem":
            for n in s.iter():
                if n.get("ID") and n.get("ID") not in owner:
                    owner[n.get("ID")] = ("seg", s.get("ID"))

    # The piping as a directed graph: segment -> what its connections lead to.
    after: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    before: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    for s in segments:
        sid = ("seg", s.get("ID"))
        for c in s.findall("Connection"):
            frm, to = c.get("FromID"), c.get("ToID")
            if frm in owner and owner[frm] != sid:
                after[owner[frm]].add(sid)
                before[sid].add(owner[frm])
            if to in owner and owner[to] != sid:
                after[sid].add(owner[to])
                before[owner[to]].add(sid)

    def reach(start: tuple[str, str], edges: dict) -> set[str]:
        """The equipment met first walking the piping from ``start`` (valves and tees pass)."""

        found, seen, stack = set(), {start}, list(edges[start])
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            if node[0] == "eq":
                found.add(node[1])
                continue
            stack.extend(edges[node])
        return found

    for node in list(after):
        if node[0] == "eq":
            for to in reach(node, after):
                relate(node[1], "feeds", to, "piping joins them in the DEXPI file")

    def upstream(item_id: str) -> set[str]:
        place = owner.get(item_id)
        if place is None:
            return set()
        if place[0] == "eq":
            return {place[1]}
        return reach(place, before)

    def located(element: ET.Element) -> str:
        for a in element.findall("Association"):
            if a.get("Type") == "is located in":
                return a.get("ItemID") or ""
        return ""

    # Instruments: the function (the bubble), its sensor and its valve.
    for pif in (e for e in elements if e.tag == "ProcessInstrumentationFunction"):
        ga = _attrs(pif)
        category = ga.get("ProcessInstrumentationFunctionCategoryAssignmentClass", "")
        modifier = ga.get("ProcessInstrumentationFunctionModifierAssignmentClass", "")
        number = ga.get("ProcessInstrumentationFunctionNumberAssignmentClass", "")
        number = number.split("-", 1)[1] if "-" in number else number
        tag = (
            _tag(f"{category}{modifier}-{number}", instrument=True) if category and number else None
        )
        tag = tag or _tag(pif.get("TagName") or "", instrument=True)
        if tag is None:
            continue
        name = add(tag, "instrument", tag.cls, pif, "instrument function in the DEXPI file")
        for sensor in pif.findall("ProcessSignalGeneratingFunction"):
            for equipment in sorted(upstream(located(sensor))):
                relate(name, "measures", equipment, "its sensor sits there in the DEXPI file")
        for act in pif.findall("ActuatingFunction"):
            valve_tag = _tag(
                _attrs(act).get("ActuatingFunctionNumberAssignmentClass", ""), instrument=True
            )
            if valve_tag is None:
                continue
            where = by_id.get(located(act))
            drawn = _valve_element(act, by_id)
            valve = add(
                valve_tag,
                "instrument",
                "valve",
                drawn if drawn is not None else where,
                "valve of an instrument function in the DEXPI file",
            )
            relate(name, "controls", valve, "the instrument function acts on it in the DEXPI file")
            for equipment in sorted(upstream(located(act))):
                relate(valve, "on", equipment, "it sits on the line leaving it in the DEXPI file")

    # Hand valves with a tag on the piping.
    for pc in (e for e in elements if e.tag == "PipingComponent"):
        cls = pc.get("ComponentClass") or ""
        if "Valve" not in cls or not pc.get("TagName"):
            continue
        tag = _tag(pc.get("TagName") or "", instrument=True)
        if tag is None or tag.tag in items:
            continue
        valve = add(
            tag, "instrument", "valve", pc, f"valve on the piping in the DEXPI file ({cls})"
        )
        for equipment in sorted(upstream(pc.get("ID") or "")):
            relate(valve, "on", equipment, "it sits on the line leaving it in the DEXPI file")

    drawing = root.find("Drawing")
    ga = _attrs(drawing) if drawing is not None else {}
    title = ga.get("Title") or ""
    sheet_number = (
        ga.get("DrawingNumber") or (drawing.get("Name") if drawing is not None else "") or ""
    )
    return [
        {
            "sheet": sheet_number,
            "unit": "",
            "title": title,
            "items": list(items.values()),
            "relations": list(relations.values()),
            "notes": ["Read from a DEXPI file: the tool that drew it says what joins what."],
            "stats": {"segments": len(segments)},
            "page": 1,
            "source": "dexpi",
            "width": round(sheet.width, 1),
            "height": round(sheet.height, 1),
        }
    ]


def _valve_element(act: ET.Element, by_id: dict[str, ET.Element]) -> ET.Element | None:
    """The drawn valve an actuating function is fulfilled by (its actuating system's valve)."""

    for a in act.findall("Association"):
        if a.get("Type") != "is fulfilled by":
            continue
        system = by_id.get(a.get("ItemID") or "")
        if system is None:
            continue
        for part in system.iter("Association"):
            if part.get("Type") == "refers to" and part.get("ItemID") in by_id:
                return by_id[part.get("ItemID")]
    return None


def draw_svg(data: bytes) -> bytes:
    """The sheet drawn as SVG: its lines, circles and texts, and a box on each tagged item."""

    root = _root(data)
    sheet = _Sheet(root)
    page = read_dexpi(data)[0]
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {sheet.width:.1f} {sheet.height:.1f}" '
        f'width="{sheet.width:.1f}mm" height="{sheet.height:.1f}mm">',
        f'<rect width="{sheet.width:.1f}" height="{sheet.height:.1f}" fill="#fff"/>',
        '<g fill="none" stroke="#222" stroke-width="0.35">',
    ]
    for element in _instances(root):
        if element.tag in {"Line", "PolyLine", "CenterLine"}:
            points = [sheet.point(c) for c in element.findall("Coordinate")]
            if len(points) >= 2:
                path = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
                out.append(f'<polyline points="{path}"/>')
        elif element.tag == "Circle":
            location = element.find("Position/Location")
            if location is not None:
                x, y = sheet.point(location)
                r = float(element.get("Radius", 0)) * MM
                if r > 0:
                    out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}"/>')
    out.append("</g>")
    out.append('<g fill="#222" font-family="sans-serif">')
    for element in _instances(root):
        if element.tag == "Text" and element.get("String"):
            location = element.find("Position/Location")
            if location is not None:
                x, y = sheet.point(location)
                size = max(float(element.get("Height", 0.0025)) * MM, 1.5)
                out.append(
                    f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size:.1f}">'
                    f"{escape(element.get('String') or '')}</text>"
                )
    out.append("</g>")
    out.append('<g fill="none" stroke="#2f7d6b" stroke-width="0.5">')
    for item in page["items"]:
        x0, y0, x1, y1 = item["box"]
        if x1 > x0 and y1 > y0:
            out.append(f'<rect x="{x0}" y="{y0}" width="{x1 - x0:.1f}" height="{y1 - y0:.1f}"/>')
    out.append("</g></svg>")
    return "\n".join(out).encode()
