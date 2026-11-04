"""The report PDF's charts, drawn with plain shapes: ticks, trends, axes and legends."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from reportlab.graphics.shapes import Drawing, Line, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.platypus import Flowable, Paragraph, Table, TableStyle

from dashcraft.dashboards.fields import FieldConfig, effective, finite_number
from dashcraft.dashboards.model import Card
from dashcraft.i18n import t
from dashcraft.reports.pdf_style import AXIS, CONTENT, GRID, MUTED, PALE, SERIES, STYLES
from dashcraft.reports.pdf_values import (
    Clock,
    _color,
    _esc,
    _instant,
    _label,
    number_text,
    shown,
    unit_of,
)

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
