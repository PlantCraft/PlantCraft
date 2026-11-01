"""Which pages of a document are diagrams (P&IDs), what each one shows, and its text.

A page is a diagram when the reader (``reader/``) finds tags on it joined by lines: at least
three tagged items and one relation; a DEXPI file with one tagged item (it says what it is); or at least five tags among many strokes (lines not
traced); or, on a scan (no lines traced yet), at least five tags.
Each diagram page is kept with what was read (items, relations, sheet number, unit) and gets
a passage of its own, written in words ("P-1001 feeds E-1009"), so the search and the assistant
find what the drawing shows, not only the words printed on it.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from pidcraft.plantmap.reader import DrawingError, kind_of, read_drawing

LOG = logging.getLogger(__name__)
DRAWING_FORMATS = {
    ".svg": "svg",
    ".xml": "dexpi",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".tif": "image",
    ".tiff": "image",
}
MIN_ITEMS = 3
MIN_SCAN_TAGS = 5
# A drawing whose lines were not traced is still a diagram when it holds enough tags among
# enough strokes (a datasheet with tags has few strokes).
MIN_TAGS_WITHOUT_LINES = 5
MIN_STROKES = 150


def read_diagrams(data: bytes, filename: str) -> list[dict[str, Any]]:
    """The diagram pages of a file (PDF, SVG or image); never raises."""

    try:
        kind = kind_of(data, filename)
    except DrawingError:
        return []
    try:
        pages = read_drawing(data, filename)
    except DrawingError as error:
        LOG.info("%s: not read as a drawing: %s", filename, error)
        return []
    except Exception:  # noqa: BLE001 - a broken drawing never stops the indexing
        LOG.exception("%s: the drawing reader failed", filename)
        return []
    out = []
    for page in pages:
        tagged = [i for i in page["items"] if i.get("tag")]
        if page["source"] == "dexpi":
            if not tagged:
                continue
        elif page["source"] == "raster":
            if len(tagged) < MIN_SCAN_TAGS:
                continue
        elif len(tagged) < MIN_ITEMS:
            continue
        elif not page["relations"] and (
            len(tagged) < MIN_TAGS_WITHOUT_LINES
            or page.get("stats", {}).get("strokes", 0) < MIN_STROKES
        ):
            continue
        page["format"] = kind
        out.append(page)
    return out


NAMES = {
    "feeds": "feeds",
    "measures": "measures",
    "controls": "controls",
    "signal": "sends its signal to",
    "on": "is on the line leaving",
}


def describe(page: dict[str, Any]) -> str:
    """The diagram in words, for the search and the assistant."""

    lines = []
    head = " ".join(x for x in (page.get("sheet"), page.get("title")) if x)
    lines.append(
        f"Diagram {head}".strip() + (f", unit {page['unit']}" if page.get("unit") else "") + "."
    )
    by_cls: dict[str, list[str]] = defaultdict(list)
    for item in page["items"]:
        if item.get("tag") and item["family"] in {"equipment", "instrument"}:
            by_cls[item["cls"]].append(item["tag"])
    equipment = [i for i in page["items"] if i["family"] == "equipment" and i.get("tag")]
    if equipment:
        lines.append(
            "Equipment: "
            + ", ".join(f"{i['tag']} ({i['cls'].replace('_', ' ')})" for i in equipment)
            + "."
        )
    for cls in ("controller", "transmitter", "valve", "indicator", "element", "switch"):
        if by_cls.get(cls):
            lines.append(f"{cls.title()}s: " + ", ".join(sorted(by_cls[cls])) + ".")
    for rel in page["relations"]:
        if rel["from"].startswith("valve@") or rel["to"].startswith("valve@"):
            continue
        lines.append(f"{rel['from']} {NAMES.get(rel['type'], rel['type'])} {rel['to']}.")
    refs = [i for i in page["items"] if i["family"] == "connector" and i.get("ref_sheet")]
    for ref in refs:
        lines.append(
            f"Continues on sheet {ref['ref_sheet']}"
            + (f" ({ref['ref_tag']})" if ref.get("ref_tag") else "")
            + "."
        )
    return "\n".join(lines)
