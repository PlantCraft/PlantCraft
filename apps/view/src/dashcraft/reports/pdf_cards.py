"""The report PDF's card bodies (tiles, meters, bars, value tables), the period's events, the
alarms and the groups."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Flowable, KeepTogether, Paragraph, Spacer, Table, TableStyle

from dashcraft.dashboards.fields import FieldConfig, effective, finite_number
from dashcraft.dashboards.model import Card
from dashcraft.i18n import t
from dashcraft.reports import alarm_performance
from dashcraft.reports import groups as grouped
from dashcraft.reports.pdf_charts import _empty, _legend, _steps_of, nice_ticks, trend_drawing
from dashcraft.reports.pdf_style import (
    AXIS,
    CONTENT,
    GRID,
    INK,
    MUTED,
    NO_VALUE,
    PALE,
    SERIES,
    SEVERITY_COLORS,
    STATE_COLORS,
    STATE_WORDS,
    STYLES,
    TEXT2,
)
from dashcraft.reports.pdf_values import Clock, _esc, _label, number_text, shown, unit_of

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
