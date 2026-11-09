"""The report PDF's look: the suite's light theme darkened for print, page sizes and text styles."""

from __future__ import annotations

from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm

# The suite's light theme (ui/src/brandTheme.ts), darkened where print needs more contrast.
INK = colors.HexColor("#1d1d1f")
TEXT2 = colors.HexColor("#424245")
MUTED = colors.HexColor("#6e6e73")
GRID = colors.HexColor("#e8e8ed")
AXIS = colors.HexColor("#d2d2d7")
PALE = colors.HexColor("#f5f5f7")
BRAND = colors.HexColor("#3442a6")  # View's Chart Indigo
SERIES = [
    colors.HexColor(value)
    for value in (
        "#1762b6",
        "#e06d00",
        "#00958f",
        "#654db6",
        "#cfa529",
        "#913e20",
        "#ca488f",
        "#438f31",
    )
]
STATE_COLORS = {
    "ok": colors.HexColor("#1f8f3f"),
    "warning": colors.HexColor("#b86e00"),
    "alarm": colors.HexColor("#d92d20"),
    "unknown": MUTED,
}
STATE_WORDS = {"ok": "OK", "warning": "Attention", "alarm": "Alarm", "unknown": "Unknown"}
SEVERITY_COLORS = {
    "critical": STATE_COLORS["alarm"],
    "warning": STATE_COLORS["warning"],
    "ok": STATE_COLORS["ok"],
    "info": MUTED,
}
PALETTE = {
    "blue": "#1762b6",
    "green": "#1f8f3f",
    "yellow": "#cfa529",
    "orange": "#e06d00",
    "red": "#d92d20",
    "purple": "#654db6",
    "teal": "#00958f",
    "grey": "#8e8e93",
}
PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 16 * mm
# The frame keeps 6 pt of padding on each side: the width flowables really get.
FRAME_PAD = 6
CONTENT = PAGE_WIDTH - 2 * MARGIN - 2 * FRAME_PAD
GUTTER = 6 * mm
NO_VALUE = "–"


def _style(name: str, **kw: Any) -> ParagraphStyle:
    return ParagraphStyle(name, **{"fontName": "Helvetica", "textColor": INK, **kw})


STYLES = {
    "eyebrow": _style(
        "eyebrow", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=BRAND
    ),
    "title": _style("title", fontName="Helvetica-Bold", fontSize=20, leading=24, spaceAfter=2),
    "lead": _style("lead", fontSize=9.5, leading=13, textColor=TEXT2),
    "meta_label": _style("meta_label", fontSize=7, leading=9, textColor=MUTED),
    "meta": _style("meta", fontName="Helvetica-Bold", fontSize=8.5, leading=11),
    "h1": _style(
        "h1",
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=18,
        spaceBefore=8,
        spaceAfter=4,
        keepWithNext=1,
    ),
    "h2": _style(
        "h2",
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        spaceBefore=6,
        spaceAfter=3,
        keepWithNext=1,
    ),
    "h3": _style(
        "h3", fontName="Helvetica-Bold", fontSize=10, leading=13, spaceAfter=1, keepWithNext=1
    ),
    "h4": _style(
        "h4",
        fontName="Helvetica-BoldOblique",
        fontSize=9.5,
        leading=12.5,
        spaceAfter=1,
        keepWithNext=1,
    ),
    "quote": _style(
        "quote",
        fontName="Helvetica-Oblique",
        fontSize=9,
        leading=12.5,
        leftIndent=10,
        textColor=TEXT2,
        spaceAfter=4,
    ),  # fmt: skip
    "body": _style("body", fontSize=9, leading=12.5, spaceAfter=4),
    "note": _style("note", fontSize=7.5, leading=10, textColor=MUTED),
    "problem": _style("problem", fontSize=7.5, leading=10, textColor=STATE_COLORS["alarm"]),
    "cell": _style("cell", fontSize=8, leading=10.5),
    "cell_right": _style("cell_right", fontSize=8, leading=10.5, alignment=TA_RIGHT),
    "head": _style("head", fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=MUTED),
    "head_right": _style(
        "head_right",
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=10,
        textColor=MUTED,
        alignment=TA_RIGHT,
    ),
    "tile_label": _style("tile_label", fontSize=7.5, leading=9.5, textColor=TEXT2),
    "tile_value": _style("tile_value", fontName="Helvetica-Bold", fontSize=17, leading=20),
    "tile_detail": _style("tile_detail", fontSize=7, leading=9, textColor=MUTED),
}
