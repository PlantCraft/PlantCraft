"""A report as an A4 PDF (reportlab): the cover lines, then each section as View draws it.

Built only from what the sections read (``delivery.read``): the card data of
``query.cards.read_card`` and the events of the period. Charts are drawn here with plain shapes
(lines, bars, tiles), in the suite's colours on white paper; a value is coloured only by its
state (ok, warning, alarm), never as decoration. Everything that comes from data is escaped
before it reaches a ``Paragraph``. Fonts are the PDF's own (Helvetica): nothing is fetched.
"""

from __future__ import annotations

import io
import math
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Line, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    CondPageBreak,
    Flowable,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from dashcraft.dashboards.fields import FieldConfig, effective, finite_number
from dashcraft.dashboards.model import Card
from dashcraft.i18n import t
from dashcraft.reports import alarm_performance
from dashcraft.reports import groups as grouped
from dashcraft.reports import markdown as md
from dashcraft.reports.schedule import zone

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


# Values ------------------------------------------------------------------------------------


def _color(name: str | None, fallback: colors.Color) -> colors.Color:
    if not name:
        return fallback
    if name.startswith("#"):
        return colors.HexColor(name)
    if name in PALETTE:
        return colors.HexColor(PALETTE[name])
    return STATE_COLORS.get(name, fallback)


def number_text(value: Any, decimals: int | None = None) -> str:
    """A value as people read it: thousands separated, decimals as the card says or by size."""

    number = finite_number(value)
    if number is None:
        return str(value) if isinstance(value, str) and value else NO_VALUE
    if decimals is None:
        size = abs(number)
        decimals = 0 if size >= 1000 else 1 if size >= 100 else 2 if size >= 1 else 3
        if number == int(number) and size < 1e15:
            decimals = 0
    return f"{number:,.{decimals}f}"


def shown(config: FieldConfig, value: Any) -> str:
    """The value with the card's mappings ("1" reads "Running"), decimals and empty text."""

    for mapping in config.mappings or []:
        if mapping.matches(value) and mapping.text:
            return mapping.text
    if value is None:
        return config.no_value or NO_VALUE
    return number_text(value, config.decimals)


def unit_of(config: FieldConfig, row: dict[str, Any]) -> str:
    return config.unit if config.unit is not None else str(row.get("unit") or "")


def _label(config: FieldConfig, row: dict[str, Any]) -> str:
    return config.display_name or str(row.get("label") or row.get("signal") or "")


def _instant(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


class Clock:
    """Instants on the installation's wall clock."""

    def __init__(self, zone_name: str | None):
        self.zone = zone(zone_name)
        self.name = zone_name or "UTC"

    def local(self, value: Any) -> datetime | None:
        moment = _instant(value)
        return moment.astimezone(self.zone) if moment else None

    def text(self, value: Any, form: str = "%d %b %Y %H:%M") -> str:
        moment = self.local(value)
        return moment.strftime(form) if moment else NO_VALUE


def _esc(value: Any) -> str:
    return escape(str(value or ""))


# Markdown (``reports.markdown``: what the text cells and the suite's help pages use) -------


def spans_markup(spans: list[md.Span]) -> str:
    """Spans as reportlab markup; every text escaped."""

    out: list[str] = []
    for span in spans:
        text = escape(span.text)
        if span.style == "bold":
            out.append(f"<b>{text}</b>")
        elif span.style == "italic":
            out.append(f"<i>{text}</i>")
        elif span.style == "code":
            out.append(f'<font name="Courier">{text}</font>')
        elif span.style == "link" and span.href.lower().startswith(("http://", "https://")):
            out.append(f'<link href="{escape(span.href)}" color="#1762b6">{text}</link>')
        else:
            out.append(text)
    return "".join(out)


def inline(text: str) -> str:
    """``**bold**``, ``*italic*``, ``code`` and links as reportlab markup; the rest escaped."""

    return spans_markup(md.inline(text))


class Heading(Paragraph):
    """A text cell's heading: also an entry of the PDF's bookmarks (its outline)."""

    def __init__(self, text: str, style: ParagraphStyle, level: int, title: str):
        super().__init__(text, style)
        self.level = level
        self.title = title


def _md_table(block: md.Block) -> Flowable:
    head = [
        Paragraph(spans_markup(cell), STYLES["head_right" if a == "right" else "head"])
        for cell, a in zip(block.head, block.align, strict=False)
    ]
    rows: list[list[Any]] = [head]
    for row in block.rows:
        rows.append(
            [
                Paragraph(spans_markup(cell), STYLES["cell_right" if a == "right" else "cell"])
                for cell, a in zip(row, block.align, strict=False)
            ]
        )
    table = Table(rows, repeatRows=1, hAlign="LEFT", colWidths=[CONTENT / len(head)] * len(head))
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.7, AXIS),
                ("LINEBELOW", (0, 1), (-1, -1), 0.4, GRID),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def markdown(text: str) -> list[Flowable]:
    """Headings (# to ####, also bookmarks), lists, tables, quotes, rules and paragraphs."""

    flowables: list[Flowable] = []
    for block in md.parse(text):
        if block.kind == "heading":
            flowables.append(
                Heading(
                    spans_markup(block.spans), STYLES[f"h{block.level}"], block.level, block.text
                )
            )
        elif block.kind == "rule":
            flowables.append(_Rule())
        elif block.kind == "list":
            flowables.append(
                ListFlowable(
                    [
                        ListItem(Paragraph(spans_markup(item), STYLES["body"]))
                        for item in block.items
                    ],
                    bulletType="1" if block.numbered else "bullet",
                    bulletFontSize=7 if not block.numbered else 8.5,
                    leftIndent=12,
                    bulletColor=TEXT2,
                    start=None if block.numbered else "•",
                )
            )
        elif block.kind == "table":
            flowables.extend([_md_table(block), Spacer(1, 4)])
        elif block.kind == "quote":
            flowables.append(Paragraph(spans_markup(block.spans), STYLES["quote"]))
        else:
            flowables.append(Paragraph(spans_markup(block.spans), STYLES["body"]))
    return flowables


class _Rule(Flowable):
    def __init__(self, color: colors.Color = GRID, space: float = 4):
        super().__init__()
        self.color, self.space = color, space

    def wrap(self, width: float, _height: float) -> tuple[float, float]:
        self.width = width
        return width, self.space * 2

    def draw(self) -> None:
        self.canv.setStrokeColor(self.color)
        self.canv.setLineWidth(0.6)
        self.canv.line(0, self.space, self.width, self.space)


# Charts ------------------------------------------------------------------------------------


def nice_ticks(low: float, high: float, count: int = 5) -> list[float]:
    """Round values covering ``low`` to ``high`` (about ``count`` of them)."""

    if not (math.isfinite(low) and math.isfinite(high)):
        return [0.0, 1.0]
    if high <= low:
        spread = abs(low) * 0.1 or 1.0
        low, high = low - spread, high + spread
    raw = (high - low) / max(count, 1)
    power = 10 ** math.floor(math.log10(raw))
    step = next(factor * power for factor in (1, 2, 2.5, 5, 10) if factor * power >= raw)
    first = math.floor(low / step) * step
    ticks = []
    value = first
    while value <= high + step * 0.5 and len(ticks) < 20:
        ticks.append(round(value, 10))
        value += step
    if ticks[-1] < high:
        ticks.append(round(ticks[-1] + step, 10))
    return ticks


def _time_ticks(start: float, end: float, clock: Clock) -> list[tuple[float, str]]:
    """About six instants with round wall-clock times between ``start`` and ``end`` (epochs)."""

    span = max(end - start, 1)
    hour = 3600
    for step in (
        300,
        900,
        1800,
        hour,
        2 * hour,
        3 * hour,
        6 * hour,
        12 * hour,
        24 * hour,
        2 * 86400,
        7 * 86400,
        14 * 86400,
        30 * 86400,
    ):
        if span / step <= 7:
            break
    form = "%H:%M" if step < 86400 else "%d %b"
    ticks: list[tuple[float, str]] = []
    first = datetime.fromtimestamp(start, clock.zone)
    offset = first.utcoffset().total_seconds() if first.utcoffset() else 0
    at = math.ceil((start + offset) / step) * step - offset
    while at <= end and len(ticks) < 10:
        label = datetime.fromtimestamp(at, clock.zone).strftime(form)
        if step < 86400 and label == "00:00":
            label = datetime.fromtimestamp(at, clock.zone).strftime("%d %b")
        ticks.append((at, label))
        at += step
    return ticks


def _segments(times: list[float], values: list[Any]) -> list[list[tuple[float, float]]]:
    """The points of a line, broken where a value is missing."""

    out: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    for at, value in zip(times, values, strict=False):
        number = finite_number(value)
        if number is None:
            if current:
                out.append(current)
            current = []
            continue
        current.append((at, number))
    if current:
        out.append(current)
    return out


def _steps_of(config: FieldConfig) -> list[tuple[float, colors.Color]]:
    thresholds = config.thresholds
    if thresholds is None or thresholds.mode != "absolute" or thresholds.show == "off":
        return []
    return [
        (step.value, _color(step.color or step.level, MUTED))
        for step in thresholds.steps
        if step.value is not None and step.level != "none"
    ]


def trend_drawing(
    card: Card, data: dict[str, Any], width: float, clock: Clock, *, scatter: bool = False
) -> tuple[Flowable, list[dict[str, Any]]]:
    """A time chart (or PV against OP for a scatter card) and the lines it drew."""

    height = 150 if width > CONTENT * 0.7 else 128
    drawing = Drawing(width, height)
    lines = [line for line in data.get("lines") or [] if not line.get("error")]
    parsed: list[tuple[dict[str, Any], list[float], list[Any]]] = []
    for line in lines:
        times = [
            moment.timestamp() if (moment := _instant(at)) else math.nan
            for at in line.get("t") or []
        ]
        parsed.append((line, times, list(line.get("v") or [])))
    left, bottom, right, top = 38, 18, 6, 6
    plot_w, plot_h = width - left - right, height - bottom - top
    if scatter:
        if len(parsed) < 2:
            return _empty(width, t("No data in the period.")), lines
        xv, yv = parsed[0][2], parsed[1][2]
        pairs = [
            (finite_number(x), finite_number(y))
            for x, y in zip(xv, yv, strict=False)
            if finite_number(x) is not None and finite_number(y) is not None
        ]
        if not pairs:
            return _empty(width, t("No data in the period.")), lines
        xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
        x_ticks, y_ticks = nice_ticks(min(xs), max(xs)), nice_ticks(min(ys), max(ys))
        x0, x1, y0, y1 = x_ticks[0], x_ticks[-1], y_ticks[0], y_ticks[-1]
        _axes(drawing, left, bottom, plot_w, plot_h, y_ticks, y0, y1)
        for value in x_ticks:
            x = left + (value - x0) / ((x1 - x0) or 1) * plot_w
            drawing.add(
                String(
                    x,
                    bottom - 10,
                    number_text(value),
                    fontName="Helvetica",
                    fontSize=6.5,
                    fillColor=MUTED,
                    textAnchor="middle",
                )
            )
        for x_value, y_value in pairs[:: max(1, len(pairs) // 800)]:
            x = left + (x_value - x0) / ((x1 - x0) or 1) * plot_w
            y = bottom + (y_value - y0) / ((y1 - y0) or 1) * plot_h
            drawing.add(Rect(x - 0.9, y - 0.9, 1.8, 1.8, fillColor=SERIES[0], strokeColor=None))
        return drawing, lines
    segments_by_line = [(line, _segments(times, values)) for line, times, values in parsed]
    # A line of another unit than the first (OP % beside a PV in bar) reads on a right axis, as
    # on the page; a line set to the right goes there too.
    first_unit = unit_of(effective(card.field, card.overrides, lines[0]), lines[0]) if lines else ""
    on_right = []
    for line, _ in segments_by_line:
        config = effective(card.field, card.overrides, line)
        on_right.append(
            config.axis == "right"
            or (config.axis in (None, "auto") and unit_of(config, line) != first_unit)
        )
    if all(on_right):
        on_right = [False] * len(on_right)
    numbers = [
        y
        for (_, segments), right_side in zip(segments_by_line, on_right, strict=True)
        if not right_side
        for segment in segments
        for _, y in segment
    ]
    right_numbers = [
        y
        for (_, segments), right_side in zip(segments_by_line, on_right, strict=True)
        if right_side
        for segment in segments
        for _, y in segment
    ]
    if right_numbers:
        right = 30
        plot_w = width - left - right
    window = data.get("range") or {}
    start = (_instant(window.get("start")) or datetime.now(UTC)).timestamp()
    end = (_instant(window.get("end")) or datetime.now(UTC)).timestamp()
    if not numbers:
        return _empty(width, t("No data in the period.")), lines
    steps = [value for config in [card.field] for value, _ in _steps_of(config)]
    low = min(numbers)
    high = max(numbers)
    soft_min, soft_max = card.options.soft_min, card.options.soft_max
    low = min(low, soft_min) if soft_min is not None else low
    high = max(high, soft_max) if soft_max is not None else high
    if card.field.min is not None:
        low = card.field.min
    if card.field.max is not None:
        high = card.field.max
    for value in steps:
        if low - (high - low) * 0.3 <= value <= high + (high - low) * 0.3:
            low, high = min(low, value), max(high, value)
    y_ticks = nice_ticks(low, high)
    y0, y1 = y_ticks[0], y_ticks[-1]
    _axes(drawing, left, bottom, plot_w, plot_h, y_ticks, y0, y1)

    def x_of(at: float) -> float:
        return left + (at - start) / ((end - start) or 1) * plot_w

    def y_of(value: float) -> float:
        return bottom + (value - y0) / ((y1 - y0) or 1) * plot_h

    r_ticks = nice_ticks(min(right_numbers), max(right_numbers)) if right_numbers else []

    def y_right(value: float) -> float:
        return bottom + (value - r_ticks[0]) / ((r_ticks[-1] - r_ticks[0]) or 1) * plot_h

    for value in r_ticks:
        drawing.add(
            String(
                left + plot_w + 4,
                y_right(value) - 2.2,
                number_text(value),
                fontName="Helvetica",
                fontSize=6.5,
                fillColor=MUTED,
                textAnchor="start",
            )
        )

    for at, label in _time_ticks(start, end, clock):
        x = x_of(at)
        drawing.add(Line(x, bottom, x, bottom - 2, strokeColor=AXIS, strokeWidth=0.5))
        drawing.add(
            String(
                x,
                bottom - 10,
                label,
                fontName="Helvetica",
                fontSize=6.5,
                fillColor=MUTED,
                textAnchor="middle",
            )
        )
    for value, color in _steps_of(card.field):
        if y0 <= value <= y1:
            y = y_of(value)
            drawing.add(
                Line(
                    left,
                    y,
                    left + plot_w,
                    y,
                    strokeColor=color,
                    strokeWidth=0.7,
                    strokeDashArray=[3, 2],
                )
            )
    for index, (line, segments) in enumerate(segments_by_line):
        config = effective(card.field, card.overrides, line)
        color = (
            _color(config.color, SERIES[index % len(SERIES)])
            if config.color_mode == "fixed"
            else SERIES[index % len(SERIES)]
        )
        width_line = config.line_width or 1.1
        y_at = y_right if on_right[index] else y_of
        for segment in segments:
            points = [coordinate for at, value in segment for coordinate in (x_of(at), y_at(value))]
            if len(points) == 2:
                drawing.add(
                    Rect(points[0] - 1, points[1] - 1, 2, 2, fillColor=color, strokeColor=None)
                )
            elif points:
                drawing.add(
                    PolyLine(points, strokeColor=color, strokeWidth=width_line, strokeLineJoin=1)
                )
        line["_color"] = color
        line["_right"] = on_right[index]
    return drawing, lines


def _axes(
    drawing: Drawing,
    left: float,
    bottom: float,
    plot_w: float,
    plot_h: float,
    y_ticks: list[float],
    y0: float,
    y1: float,
) -> None:
    for value in y_ticks:
        y = bottom + (value - y0) / ((y1 - y0) or 1) * plot_h
        drawing.add(Line(left, y, left + plot_w, y, strokeColor=GRID, strokeWidth=0.5))
        drawing.add(
            String(
                left - 4,
                y - 2.2,
                number_text(value),
                fontName="Helvetica",
                fontSize=6.5,
                fillColor=MUTED,
                textAnchor="end",
            )
        )
    drawing.add(Line(left, bottom, left + plot_w, bottom, strokeColor=AXIS, strokeWidth=0.7))


def _empty(width: float, text: str) -> Flowable:
    drawing = Drawing(width, 46)
    drawing.add(Rect(0, 0, width, 46, fillColor=PALE, strokeColor=None, rx=4, ry=4))
    drawing.add(
        String(
            width / 2,
            20,
            text,
            fontName="Helvetica",
            fontSize=8,
            fillColor=MUTED,
            textAnchor="middle",
        )
    )
    return drawing


def _legend(card: Card, lines: list[dict[str, Any]], width: float) -> Flowable | None:
    """Each line's colour, name and unit, with its lowest, mean and highest in the period."""

    rows = [
        [
            Paragraph("", STYLES["head"]),
            Paragraph(t("Signal"), STYLES["head"]),
            Paragraph(t("Min"), STYLES["head_right"]),
            Paragraph(t("Mean"), STYLES["head_right"]),
            Paragraph(t("Max"), STYLES["head_right"]),
            Paragraph(t("Last"), STYLES["head_right"]),
        ]
    ]
    for line in lines:
        values = [
            number for value in line.get("v") or [] if (number := finite_number(value)) is not None
        ]
        config = effective(card.field, card.overrides, line)
        unit = unit_of(config, line)
        label = _label(config, line) + (f" ({unit})" if unit else "")
        if line.get("_right"):
            label += " · " + t("right axis")

        def cell(value: Any, config: FieldConfig = config) -> Paragraph:
            return Paragraph(_esc(shown(config, value)), STYLES["cell_right"])

        swatch = Drawing(8, 8)
        swatch.add(Rect(0, 0, 8, 3, fillColor=line.get("_color") or MUTED, strokeColor=None))
        rows.append(
            [
                swatch,
                Paragraph(_esc(label), STYLES["cell"]),
                cell(min(values) if values else None),
                cell(sum(values) / len(values) if values else None),
                cell(max(values) if values else None),
                cell(values[-1] if values else None),
            ]
        )
    if len(rows) == 1:
        return None
    number_w = 48 if width > 300 else 40
    table = Table(rows, colWidths=[12, width - 12 - 4 * number_w, *[number_w] * 4], hAlign="LEFT")
    style = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, GRID),
    ]
    table.setStyle(TableStyle(style))
    return table


# Card bodies -------------------------------------------------------------------------------


def _state(row: dict[str, Any]) -> str:
    state = str(row.get("state") or "none")
    return state if state in STATE_COLORS else "none"


def tiles(card: Card, rows: list[dict[str, Any]], width: float, *, meter: bool) -> Flowable:
    """Stat and gauge cards: one tile per value, coloured by its state; a gauge adds its meter."""

    per_row = max(1, min(len(rows), 4 if width > CONTENT * 0.7 else 2))
    tile_w = (width - (per_row - 1) * 4) / per_row
    cells: list[list[Any]] = []
    styles: list[tuple] = []
    current: list[Any] = []
    for index, row in enumerate(rows):
        config = effective(card.field, card.overrides, row)
        state = _state(row)
        color = STATE_COLORS.get(state, INK) if card.options.color_by != "none" else INK
        unit = unit_of(config, row)
        value = shown(config, row.get("value"))
        parts: list[Flowable] = [Paragraph(_esc(_label(config, row)), STYLES["tile_label"])]
        value_style = ParagraphStyle("v", parent=STYLES["tile_value"], textColor=color)
        unit_text = (
            f' <font size="8.5" color="#6e6e73">{_esc(unit)}</font>'
            if unit and row.get("value") is not None
            else ""
        )
        parts.append(Paragraph(_esc(value) + unit_text, value_style))
        if meter and finite_number(row.get("value")) is not None:
            parts.append(_meter(config, row, tile_w - 12, color))
        detail = (
            row.get("error")
            or row.get("summary")
            or (t(STATE_WORDS[state]) if state in STATE_WORDS and state != "unknown" else "")
        )
        if detail:
            parts.append(
                Paragraph(_esc(detail), STYLES["problem" if row.get("error") else "tile_detail"])
            )
        current.append(parts)
        column, line = index % per_row, len(cells)
        styles.append(
            (
                "LINEBEFORE",
                (column, line),
                (column, line),
                2.2,
                STATE_COLORS.get(state, AXIS) if state != "none" else AXIS,
            )
        )
        if len(current) == per_row:
            cells.append(current)
            current = []
    if current:
        cells.append(current + [""] * (per_row - len(current)))
    table = Table(cells, colWidths=[tile_w] * per_row, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, -1), PALE),
                ("LINEBELOW", (0, 0), (-1, -1), 3, colors.white),
                ("LINEAFTER", (0, 0), (-1, -1), 3, colors.white),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                *styles,
            ]
        )
    )
    return table


def _range(config: FieldConfig, row: dict[str, Any]) -> tuple[float, float]:
    low = config.min if config.min is not None else finite_number(row.get("low"))
    high = config.max if config.max is not None else finite_number(row.get("high"))
    if row.get("kind") == "result" or row.get("unit") == "/100":
        low, high = (0.0 if low is None else low), (100.0 if high is None else high)
    value = finite_number(row.get("value")) or 0.0
    low = low if low is not None else min(0.0, value)
    high = high if high is not None and high > low else max(low + 1, value * 1.25 or 1)
    return low, high


def _meter(config: FieldConfig, row: dict[str, Any], width: float, color: colors.Color) -> Flowable:
    low, high = _range(config, row)
    value = finite_number(row.get("value")) or 0.0
    share = min(max((value - low) / ((high - low) or 1), 0.0), 1.0)
    drawing = Drawing(width, 12)
    drawing.add(Rect(0, 4, width, 4, fillColor=GRID, strokeColor=None, rx=2, ry=2))
    drawing.add(
        Rect(0, 4, max(width * share, 1.5), 4, fillColor=color, strokeColor=None, rx=2, ry=2)
    )
    for step_value, step_color in _steps_of(config):
        if low < step_value < high:
            x = (step_value - low) / (high - low) * width
            drawing.add(Line(x, 2, x, 10, strokeColor=step_color, strokeWidth=0.8))
    drawing.add(
        String(0, -4, number_text(low), fontName="Helvetica", fontSize=5.5, fillColor=MUTED)
    )
    drawing.add(
        String(
            width,
            -4,
            number_text(high),
            fontName="Helvetica",
            fontSize=5.5,
            fillColor=MUTED,
            textAnchor="end",
        )
    )
    return drawing


def bars(card: Card, rows: list[dict[str, Any]], width: float) -> Flowable:
    """Bar cards: one horizontal bar per value from zero (or the field's minimum)."""

    rows = list(rows)
    if card.options.sort != "none":
        rows.sort(
            key=lambda row: finite_number(row.get("value")) or 0.0,
            reverse=card.options.sort == "desc",
        )
    numbers = [number for row in rows if (number := finite_number(row.get("value"))) is not None]
    label_w = min(130, width * 0.36)
    bar_h, gap = 11, 5
    height = len(rows) * (bar_h + gap) + 14
    drawing = Drawing(width, height)
    low = min([0.0, *numbers]) if card.field.min is None else card.field.min
    high = max([0.0, *numbers]) if card.field.max is None else card.field.max
    ticks = nice_ticks(low, high, 4)
    x0, x1 = ticks[0], ticks[-1]
    plot_w = width - label_w - 44
    for value in ticks:
        x = label_w + (value - x0) / ((x1 - x0) or 1) * plot_w
        drawing.add(Line(x, 12, x, height, strokeColor=GRID, strokeWidth=0.5))
        drawing.add(
            String(
                x,
                3,
                number_text(value),
                fontName="Helvetica",
                fontSize=6.5,
                fillColor=MUTED,
                textAnchor="middle",
            )
        )
    zero = label_w + (max(x0, min(0.0, x1)) - x0) / ((x1 - x0) or 1) * plot_w
    for index, row in enumerate(rows):
        config = effective(card.field, card.overrides, row)
        y = height - (index + 1) * (bar_h + gap)
        label = _label(config, row)
        drawing.add(
            String(
                label_w - 5,
                y + 3,
                label[:34],
                fontName="Helvetica",
                fontSize=7,
                fillColor=TEXT2,
                textAnchor="end",
            )
        )
        value = finite_number(row.get("value"))
        if value is None:
            drawing.add(
                String(
                    label_w + 2,
                    y + 3,
                    row.get("error") or NO_VALUE,
                    fontName="Helvetica",
                    fontSize=6.5,
                    fillColor=MUTED,
                )
            )
            continue
        state = _state(row)
        color = STATE_COLORS.get(state) if state not in ("none", "unknown") else SERIES[0]
        x = label_w + (value - x0) / ((x1 - x0) or 1) * plot_w
        drawing.add(
            Rect(min(zero, x), y, max(abs(x - zero), 1), bar_h, fillColor=color, strokeColor=None)
        )
        unit = unit_of(config, row)
        drawing.add(
            String(
                max(zero, x) + 3,
                y + 3,
                f"{shown(config, value)} {unit}".strip(),
                fontName="Helvetica",
                fontSize=6.5,
                fillColor=INK,
            )
        )
    return drawing


TABLE_HEADS = {
    "last": "Last",
    "mean": "Mean",
    "min": "Min",
    "max": "Max",
    "std": "Std dev",
    "unit": "Unit",
    "time": "Time",
    "state": "State",
}


def value_table(card: Card, rows: list[dict[str, Any]], width: float, clock: Clock) -> Flowable:
    """Table cards: the card's columns for each signal (an app's result: its value and words)."""

    columns = list(card.options.columns)
    results = any(row.get("kind") == "result" for row in rows)
    head = [Paragraph(t("Signal") if not results else t("Subject"), STYLES["head"])]
    for column in columns:
        style = "head_right" if column in ("last", "mean", "min", "max", "std") else "head"
        head.append(Paragraph(t(TABLE_HEADS[column]), STYLES[style]))
    if results:
        head.append(Paragraph(t("Summary"), STYLES["head"]))
    body = [head]
    styles: list[tuple] = []
    for index, row in enumerate(rows, start=1):
        config = effective(card.field, card.overrides, row)
        state = _state(row)
        values = row.get("values") or {}
        line: list[Any] = [Paragraph(_esc(_label(config, row)), STYLES["cell"])]
        for column in columns:
            if column in ("last", "mean", "min", "max", "std"):
                value = (
                    values.get(column) if row.get("kind") != "result" or column == "last" else None
                )
                text = (
                    shown(config, value)
                    if not (row.get("error") and column == "last")
                    else NO_VALUE
                )
                style = ParagraphStyle("c", parent=STYLES["cell_right"])
                if column == "last" and state in STATE_COLORS and card.options.cell != "text":
                    style.textColor = STATE_COLORS[state]
                    style.fontName = "Helvetica-Bold"
                line.append(Paragraph(_esc(text), style))
            elif column == "unit":
                line.append(Paragraph(_esc(unit_of(config, row)), STYLES["cell"]))
            elif column == "time":
                line.append(
                    Paragraph(_esc(clock.text(row.get("at"), "%d %b %H:%M")), STYLES["cell"])
                )
            else:
                word = t(STATE_WORDS.get(state, "")) if state in STATE_WORDS else ""
                style = ParagraphStyle(
                    "s", parent=STYLES["cell"], textColor=STATE_COLORS.get(state, MUTED)
                )
                line.append(Paragraph(_esc(word), style))
        if results:
            line.append(
                Paragraph(
                    _esc(row.get("error") or row.get("summary") or ""),
                    STYLES["cell" if not row.get("error") else "problem"],
                )
            )
        elif row.get("error"):
            line[0] = Paragraph(
                f"{_esc(_label(config, row))}<br/><font size='6.5' color='#d92d20'>{_esc(row['error'])}</font>",
                STYLES["cell"],
            )
        body.append(line)
        if card.options.row_color and state in ("warning", "alarm"):
            styles.append(
                (
                    "BACKGROUND",
                    (0, index),
                    (-1, index),
                    colors.HexColor("#fff4e5" if state == "warning" else "#fdecea"),
                )
            )
    number_w = 50
    fixed = {"unit": 42, "time": 62, "state": 56}
    widths = [fixed.get(column, number_w) for column in columns]
    summary_w = width * 0.36 if results else 0
    first = max(width - sum(widths) - summary_w, 80)
    col_widths = [first, *widths] + ([width - first - sum(widths)] if results else [])
    table = Table(body, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.7, AXIS),
                ("LINEBELOW", (0, 1), (-1, -1), 0.4, GRID),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                *styles,
            ]
        )
    )
    return table


def _problems(rows: Iterable[dict[str, Any]], skip_rows: bool) -> list[Flowable]:
    if skip_rows:
        return []
    found = [row for row in rows if row.get("error")]
    return [
        Paragraph(
            _esc(f"{row.get('label') or row.get('signal') or t('Signal')}: {row['error']}"),
            STYLES["problem"],
        )
        for row in found[:8]
    ]


def card_flowables(
    card: Card, data: dict[str, Any] | None, error: str | None, width: float, clock: Clock
) -> list[Flowable]:
    """One card: its title, its description and what it shows over the report's period."""

    out: list[Flowable] = []
    if card.title:
        out.append(Paragraph(_esc(card.title), STYLES["h3"]))
    if card.description:
        out.append(Paragraph(_esc(card.description), STYLES["note"]))
    out.append(Spacer(1, 3))
    if error or data is None:
        out.append(_empty(width, error or t("This section could not be read.")))
        return out
    kind = card.kind
    if kind in ("trend", "scatter"):
        drawing, lines = trend_drawing(card, data, width, clock, scatter=kind == "scatter")
        out.append(drawing)
        if kind == "trend":
            legend = _legend(card, lines, width)
            if legend is not None:
                out.extend([Spacer(1, 3), legend])
        if (data.get("range") or {}).get("shifted"):
            out.append(
                Paragraph(
                    _esc(
                        t(
                            "No data in the period: the chart shows the latest data, up to {end}.",
                            end=clock.text((data.get("range") or {}).get("end")),
                        )
                    ),
                    STYLES["note"],
                )
            )
        out.extend(_problems(data.get("lines") or [], False))
    elif kind == "table":
        rows = data.get("rows") or []
        out.append(
            value_table(card, rows, width, clock) if rows else _empty(width, t("Nothing to show."))
        )
    elif kind == "bar" and card.options.bar_style != "gauge":
        rows = data.get("rows") or []
        out.append(bars(card, rows, width) if rows else _empty(width, t("Nothing to show.")))
    else:
        rows = data.get("rows") or []
        meter = kind == "gauge" or (kind == "bar" and card.options.bar_style == "gauge")
        out.append(
            tiles(card, rows, width, meter=meter) if rows else _empty(width, t("Nothing to show."))
        )
        if card.options.graph == "area" and data.get("lines"):
            drawing, _lines = trend_drawing(card, data, width, clock)
            out.extend([Spacer(1, 3), drawing])
    return out


def events_flowables(
    section: dict[str, Any],
    data: dict[str, Any] | None,
    error: str | None,
    width: float,
    clock: Clock,
) -> list[Flowable]:
    """The events of the period: how many of each kind, then the latest, newest first."""

    out: list[Flowable] = []
    title = section.get("title") or t("Events")
    out.append(Paragraph(_esc(title), STYLES["h3"]))
    if error or data is None:
        out.append(_empty(width, error or t("This section could not be read.")))
        return out
    counts = data.get("counts") or []
    total = int(data.get("total") or 0)
    words = grouped.lead(data) if total else ""
    if counts and not words:
        words = " · ".join(
            f"{item['title']}: {item['count']}{'+' if item.get('more') else ''}" for item in counts
        )
    if words:
        out.append(Paragraph(_esc(words), STYLES["note"]))
    out.append(Spacer(1, 3))
    events = data.get("events") or []
    if not total:
        out.append(_empty(width, t("No event in the period.")))
        return out
    if data.get("group_by"):
        out.append(_groups_table(data, width, clock))
        if note := grouped.more(data):
            out.append(Paragraph(_esc(note), STYLES["note"]))
        return out
    head = [
        Paragraph(t(name), STYLES["head"]) for name in ("Time", "Event", "About", "What happened")
    ]
    rows: list[list[Any]] = [head]
    styles: list[tuple] = []
    for index, event in enumerate(events, start=1):
        severity = str(event.get("severity") or "info")
        rows.append(
            [
                Paragraph(_esc(clock.text(event.get("at"), "%d %b %H:%M")), STYLES["cell"]),
                Paragraph(_esc(event.get("title") or event.get("kind")), STYLES["cell"]),
                Paragraph(
                    _esc(event.get("subject_name") or event.get("subject") or ""), STYLES["cell"]
                ),
                Paragraph(_esc(event.get("summary") or ""), STYLES["cell"]),
            ]
        )
        styles.append(
            ("LINEBEFORE", (0, index), (0, index), 2, SEVERITY_COLORS.get(severity, MUTED))
        )
    widths = [58, width * 0.2, width * 0.2]
    widths.append(width - sum(widths))
    table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.7, AXIS),
                ("LINEBELOW", (0, 1), (-1, -1), 0.4, GRID),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                *styles,
            ]
        )
    )
    out.append(table)
    if total > len(events):
        out.append(
            Paragraph(
                _esc(t("The {n} newest of {total} are listed.", n=len(events), total=total)),
                STYLES["note"],
            )
        )
    return out


def _plain_table(table: dict[str, Any], width: float) -> Flowable:
    """A table of ``alarm_performance.tables``: text cells, numbers to the right, and a mark
    before each row in its state's colour (warning, alarm)."""

    right = {index for index, side in enumerate(table["align"]) if side == "right"}
    body: list[list[Any]] = [
        [
            Paragraph(_esc(name), STYLES["head_right" if index in right else "head"])
            for index, name in enumerate(table["head"])
        ]
    ]
    styles: list[tuple] = []
    for number, (row, state) in enumerate(zip(table["rows"], table["states"], strict=True), 1):
        body.append(
            [
                Paragraph(_esc(cell), STYLES["cell_right" if index in right else "cell"])
                for index, cell in enumerate(row)
            ]
        )
        if state:
            styles.append(
                ("LINEBEFORE", (0, number), (0, number), 2, STATE_COLORS.get(state, MUTED))
            )
    columns = len(table["head"])
    narrow = [index for index in range(columns) if index in right]
    wide = [index for index in range(columns) if index not in right]
    each = min(64.0, width / (columns * 1.6))
    rest = (width - each * len(narrow)) / max(1, len(wide))
    widths = [each if index in right else rest for index in range(columns)]
    out = Table(body, colWidths=widths, repeatRows=1, hAlign="LEFT")
    out.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.7, AXIS),
                ("LINEBELOW", (0, 1), (-1, -1), 0.4, GRID),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                *styles,
            ]
        )
    )
    return out


def alarms_flowables(
    section: dict[str, Any],
    data: dict[str, Any] | None,
    error: str | None,
    width: float,
    clock: Clock,
) -> list[Flowable]:
    """Alarm performance (ISA-18.2): the EEMUA 191 line, the figures, then the floods, the most
    frequent alarms, the time to acknowledge and the fleeting alarms (``alarm_performance``)."""

    out: list[Flowable] = [
        Paragraph(_esc(section.get("title") or t("Alarm performance (ISA-18.2)")), STYLES["h3"])
    ]
    data = data or {}
    if not data.get("reading"):
        out.append(_empty(width, error or t("This section could not be read.")))
        return out
    if error:
        out.append(Paragraph(_esc(error), STYLES["problem"]))
    out.append(Paragraph(_esc(alarm_performance.lead(data)), STYLES["note"]))
    for index, table in enumerate(alarm_performance.tables(data, clock)):
        block: list[Flowable] = [Spacer(1, 4)]
        if index:
            block.append(Paragraph(_esc(table["title"]), STYLES["h4"]))
        if table["rows"]:
            block.append(_plain_table(table, width))
        else:
            block.append(_empty(width, table["empty"]))
        if table["note"]:
            block.append(Paragraph(_esc(table["note"]), STYLES["note"]))
        out.append(KeepTogether(block) if len(table["rows"]) <= 12 else block[0])
        if len(table["rows"]) > 12:
            out.extend(block[1:])
    return out


def _groups_table(data: dict[str, Any], width: float, clock: Clock) -> Flowable:
    """The ranked groups of an events section that counts its events."""

    head, rows, states = grouped.table(data, clock)
    right = {0, 2, 3}
    body: list[list[Any]] = [
        [
            Paragraph(_esc(name), STYLES["head_right" if index in right else "head"])
            for index, name in enumerate(head)
        ]
    ]
    styles: list[tuple] = []
    for number, (row, state) in enumerate(zip(rows, states, strict=True), start=1):
        body.append(
            [
                Paragraph(_esc(cell), STYLES["cell_right" if index in right else "cell"])
                for index, cell in enumerate(row)
            ]
        )
        styles.append(("LINEBEFORE", (0, number), (0, number), 2, STATE_COLORS.get(state, MUTED)))
    widths = [20, width * 0.24, 38, 38, 58]
    widths.append(width - sum(widths))
    table = Table(body, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.7, AXIS),
                ("LINEBELOW", (0, 1), (-1, -1), 0.4, GRID),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                *styles,
            ]
        )
    )
    return table


# The document ------------------------------------------------------------------------------


def _section_flowables(
    item: dict[str, Any], width: float, clock: Clock, *, keep: bool = True
) -> list[Flowable]:
    """A section's flowables; a card kept on one page (``keep``), except inside a table cell."""

    section = item["section"]
    kind = section.get("kind")
    if kind == "text":
        return markdown(section.get("text") or "")
    if kind == "card":
        card = Card.model_validate(section["card"])
        body = card_flowables(card, item.get("data"), item.get("error"), width, clock)
        return [KeepTogether(body)] if keep else body
    if kind == "events":
        return events_flowables(section, item.get("data"), item.get("error"), width, clock)
    if kind == "alarms":
        return alarms_flowables(section, item.get("data"), item.get("error"), width, clock)
    return []


def _cover(report: dict[str, Any], info: dict[str, Any], clock: Clock) -> list[Flowable]:
    period = t("{start} to {end}", start=clock.text(info["start"]), end=clock.text(info["end"]))
    meta = [
        (t("Period"), period),
        (t("Made"), clock.text(info["made_at"])),
        (t("Schedule"), info.get("cadence") or ""),
        (t("Time zone"), clock.name),
    ]
    cells = [
        [Paragraph(_esc(label.upper()), STYLES["meta_label"]) for label, _ in meta],
        [Paragraph(_esc(value), STYLES["meta"]) for _, value in meta],
    ]
    widths = [CONTENT * 0.42, CONTENT * 0.2, CONTENT * 0.2, CONTENT * 0.18]
    table = Table(cells, colWidths=widths, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ]
        )
    )
    out: list[Flowable] = [
        Paragraph(_esc(t("PLANTCRAFT VIEW · REPORT")), STYLES["eyebrow"]),
        Spacer(1, 3),
        Paragraph(_esc(report.get("name")), STYLES["title"]),
    ]
    if report.get("description"):
        out.append(Paragraph(_esc(report["description"]), STYLES["lead"]))
    out.extend([Spacer(1, 8), table, Spacer(1, 4), _Rule(AXIS, 5)])
    if info.get("problems"):
        words = (
            t("1 section could not be read in full: it says why where it is.")
            if info["problems"] == 1
            else t(
                "{n} sections could not be read in full: each says why where it is.",
                n=info["problems"],
            )
        )
        out.append(Paragraph(_esc(words), STYLES["problem"]))
    return out


def _numbered(name: str, made: str) -> type[Canvas]:
    """A canvas that writes "Page n of m" and the report's name at the foot of every page."""

    class NumberedCanvas(Canvas):
        def __init__(self, *args: Any, **kwargs: Any):
            super().__init__(*args, **kwargs)
            self._pages: list[dict[str, Any]] = []

        def showPage(self) -> None:  # noqa: N802 - reportlab's name
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self) -> None:
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                self._foot(total)
                super().showPage()
            super().save()

        def _foot(self, total: int) -> None:
            self.saveState()
            self.setStrokeColor(GRID)
            self.setLineWidth(0.6)
            left, right = MARGIN + FRAME_PAD, PAGE_WIDTH - MARGIN - FRAME_PAD
            self.line(left, 12 * mm, right, 12 * mm)
            self.setFont("Helvetica", 7)
            self.setFillColor(MUTED)
            self.drawString(left, 8 * mm, f"{name}  ·  {made}"[:120])
            self.drawRightString(
                right,
                8 * mm,
                t("Page {page} of {total}", page=self._pageNumber, total=total),
            )
            self.restoreState()

    return NumberedCanvas


class _Outlined(SimpleDocTemplate):
    """The document, with each text heading in the PDF's bookmarks (the reader's outline)."""

    def afterFlowable(self, flowable: Flowable) -> None:  # noqa: N802 - reportlab's name
        if isinstance(flowable, Heading):
            key = f"h{id(flowable)}"
            if self._level < 0:
                self.canv.showOutline()
            self.canv.bookmarkPage(key)
            # Levels may skip (# then ###): an outline entry is never deeper than one below.
            level = min(flowable.level - 1, self._level + 1)
            self.canv.addOutlineEntry(flowable.title[:120], key, level=max(level, 0))
            self._level = max(level, 0)

    def build(self, flowables: list[Flowable], **kwargs: Any) -> None:
        self._level = -1
        super().build(flowables, **kwargs)


def render(report: dict[str, Any], sections: list[dict[str, Any]], info: dict[str, Any]) -> bytes:
    """The PDF of ``report``: ``sections`` as ``delivery.read_sections`` gives them, ``info``
    with ``start``, ``end`` and ``made_at`` (UTC), ``zone``, ``cadence`` and ``problems``."""

    clock = Clock(info.get("zone"))
    story: list[Flowable] = _cover(report, info, clock)
    index = 0
    while index < len(sections):
        item = sections[index]
        section = item["section"]
        if section.get("kind") == "break":
            story.append(PageBreak())
            index += 1
            continue
        pair = (
            section.get("width") == "half"
            and index + 1 < len(sections)
            and sections[index + 1]["section"].get("width") == "half"
            and sections[index + 1]["section"].get("kind") in ("card", "events")
        )
        story.append(Spacer(1, 8))
        if pair:
            half = (CONTENT - GUTTER) / 2
            left = _section_flowables(item, half, clock, keep=False)
            right = _section_flowables(sections[index + 1], half, clock, keep=False)
            row = Table(
                [[left, right]], colWidths=[half + GUTTER / 2, half + GUTTER / 2], hAlign="LEFT"
            )
            row.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (0, 0), GUTTER / 2),
                        ("LEFTPADDING", (1, 0), (1, 0), GUTTER / 2),
                        ("RIGHTPADDING", (1, 0), (1, 0), 0),
                    ]
                )
            )
            story.extend([CondPageBreak(60 * mm), row])
            index += 2
            continue
        story.extend(_section_flowables(item, CONTENT, clock))
        index += 1
    if not sections:
        story.append(Paragraph(_esc(t("This report has no sections yet.")), STYLES["note"]))
    buffer = io.BytesIO()
    made = clock.text(info["made_at"])
    document = _Outlined(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=18 * mm,
        title=str(report.get("name") or ""),
        author="PlantCraft View",
        subject=t(
            "Report from {start} to {end}",
            start=clock.text(info["start"]),
            end=clock.text(info["end"]),
        ),
        creator="PlantCraft View",
    )
    document.build(story, canvasmaker=_numbered(str(report.get("name") or ""), made))
    return buffer.getvalue()


__all__: list[str] = ["Clock", "markdown", "nice_ticks", "number_text", "render"]
