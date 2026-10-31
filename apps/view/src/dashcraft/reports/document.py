"""A report read over its period, as one document every file format writes (Word, HTML,
Markdown; the PDF draws the same reading itself, in ``pdf.py``).

``build`` turns what ``delivery.read_sections`` read into plain parts: the cover lines, the
outline (the headings of the text cells), and each cell as text blocks, a chart (its lines as
times and values, the colours the PDF gives them), tiles, a table, an event list or a page break.
Values are written as the PDF writes them (``pdf.shown``: the card's decimals, mappings and
units), so a number reads the same in every format.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from reportlab.lib import colors

from dashcraft.dashboards.fields import effective, finite_number
from dashcraft.dashboards.model import Card
from dashcraft.i18n import t
from dashcraft.reports import alarm_performance
from dashcraft.reports import groups as grouped
from dashcraft.reports import markdown as md
from dashcraft.reports.pdf import (
    CONTENT,
    NO_VALUE,
    STATE_WORDS,
    TABLE_HEADS,
    Clock,
    _instant,
    _label,
    _range,
    _state,
    _steps_of,
    shown,
    trend_drawing,
    unit_of,
)

# Points of one line kept in a file: enough to read a day minute by minute.
MAX_POINTS = 1500
STATE_HEX = {"ok": "#1f8f3f", "warning": "#b86e00", "alarm": "#d92d20", "unknown": "#6e6e73"}


def hex_of(color: Any) -> str:
    """``#rrggbb`` of a reportlab colour (or the text itself when it already is one)."""

    if isinstance(color, str):
        return color
    if isinstance(color, colors.Color):
        return "#" + color.hexval()[2:].rjust(6, "0")[-6:]
    return "#6e6e73"


@dataclass
class Series:
    label: str
    unit: str
    color: str
    right: bool
    # Milliseconds since 1970 (UTC) and the values (None where missing).
    times: list[int]
    values: list[float | None]
    stats: dict[str, str]


@dataclass
class Table:
    head: list[str]
    rows: list[list[str]]
    # "right" for numbers; a row's state colours it (warning, alarm) where the card says so.
    align: list[str] = field(default_factory=list)
    states: list[str] = field(default_factory=list)


@dataclass
class Tile:
    label: str
    value: str
    unit: str
    state: str
    detail: str
    error: bool = False
    # Where the value sits in its range, 0 to 1 (a gauge), else None.
    share: float | None = None


@dataclass
class Bar:
    label: str
    value: float | None
    text: str
    color: str


@dataclass
class CardPart:
    title: str
    description: str
    kind: str
    show: Literal["chart", "scatter", "bars", "tiles", "table", "empty"]
    card: Card
    data: dict[str, Any] | None
    series: list[Series] = field(default_factory=list)
    thresholds: list[tuple[float, str]] = field(default_factory=list)
    start: int = 0
    end: int = 0
    bars: list[Bar] = field(default_factory=list)
    tiles: list[Tile] = field(default_factory=list)
    table: Table | None = None
    legend: Table | None = None
    empty: str = ""
    notes: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


@dataclass
class Part:
    kind: Literal["text", "card", "events", "break"]
    half: bool = False
    blocks: list[md.Block] = field(default_factory=list)
    card: CardPart | None = None
    title: str = ""
    counts: str = ""
    table: Table | None = None
    empty: str = ""
    note: str = ""
    error: str = ""


@dataclass
class Document:
    name: str
    description: str
    meta: list[tuple[str, str]]
    outline: list[md.Heading]
    parts: list[Part]
    problems: str = ""
    period: str = ""
    made: str = ""


def _ms(value: Any) -> int | None:
    moment = _instant(value)
    return int(moment.timestamp() * 1000) if moment else None


def _thin(times: list[int], values: list[float | None]) -> tuple[list[int], list[float | None]]:
    if len(times) <= MAX_POINTS:
        return times, values
    step = len(times) / MAX_POINTS
    picks = sorted({int(index * step) for index in range(MAX_POINTS)} | {len(times) - 1})
    return [times[i] for i in picks], [values[i] for i in picks]


def _stats(card: Card, line: dict[str, Any]) -> dict[str, str]:
    config = effective(card.field, card.overrides, line)
    numbers = [n for value in line.get("v") or [] if (n := finite_number(value)) is not None]
    return {
        "min": shown(config, min(numbers) if numbers else None),
        "mean": shown(config, sum(numbers) / len(numbers) if numbers else None),
        "max": shown(config, max(numbers) if numbers else None),
        "last": shown(config, numbers[-1] if numbers else None),
    }


def _chart(part: CardPart, card: Card, data: dict[str, Any], clock: Clock) -> None:
    scatter = card.kind == "scatter"
    # The PDF's own drawing gives each line its colour and axis (``_color``, ``_right``).
    _drawing, lines = trend_drawing(card, data, CONTENT, clock, scatter=scatter)
    window = data.get("range") or {}
    part.start = _ms(window.get("start")) or 0
    part.end = _ms(window.get("end")) or 0
    part.thresholds = [(value, hex_of(color)) for value, color in _steps_of(card.field)]
    for index, line in enumerate(lines):
        config = effective(card.field, card.overrides, line)
        pairs = [
            (ms, finite_number(value))
            for at, value in zip(line.get("t") or [], line.get("v") or [], strict=False)
            if (ms := _ms(at)) is not None
        ]
        times, values = _thin([p[0] for p in pairs], [p[1] for p in pairs])
        part.series.append(
            Series(
                label=_label(config, line),
                unit=unit_of(config, line),
                color=hex_of(line.get("_color") or ("#1762b6", "#e06d00")[index % 2]),
                right=bool(line.get("_right")),
                times=times,
                values=values,
                stats=_stats(card, line),
            )
        )
    if not any(value is not None for item in part.series for value in item.values):
        part.show, part.empty = "empty", t("No data in the period.")
        return
    part.show = "scatter" if scatter else "chart"
    if not scatter:
        part.legend = Table(
            head=[t("Signal"), t("Min"), t("Mean"), t("Max"), t("Last")],
            rows=[
                [
                    item.label + (f" ({item.unit})" if item.unit else ""),
                    item.stats["min"],
                    item.stats["mean"],
                    item.stats["max"],
                    item.stats["last"],
                ]
                for item in part.series
            ],
            align=["left", "right", "right", "right", "right"],
        )
    if window.get("shifted"):
        part.notes.append(
            t(
                "No data in the period: the chart shows the latest data, up to {end}.",
                end=clock.text(window.get("end")),
            )
        )


def _tiles(part: CardPart, card: Card, rows: list[dict[str, Any]]) -> None:
    meter = card.kind == "gauge" or (card.kind == "bar" and card.options.bar_style == "gauge")
    for row in rows:
        config = effective(card.field, card.overrides, row)
        state = _state(row)
        value = finite_number(row.get("value"))
        share = None
        if meter and value is not None:
            low, high = _range(config, row)
            share = min(max((value - low) / ((high - low) or 1), 0.0), 1.0)
        detail = (
            row.get("error")
            or row.get("summary")
            or (t(STATE_WORDS[state]) if state in STATE_WORDS and state != "unknown" else "")
        )
        part.tiles.append(
            Tile(
                label=_label(config, row),
                value=shown(config, row.get("value")),
                unit=unit_of(config, row) if row.get("value") is not None else "",
                state=state if card.options.color_by != "none" else "none",
                detail=str(detail or ""),
                error=bool(row.get("error")),
                share=share,
            )
        )
    part.show = "tiles"


def _bars(part: CardPart, card: Card, rows: list[dict[str, Any]]) -> None:
    rows = list(rows)
    if card.options.sort != "none":
        rows.sort(
            key=lambda row: finite_number(row.get("value")) or 0.0,
            reverse=card.options.sort == "desc",
        )
    for row in rows:
        config = effective(card.field, card.overrides, row)
        value = finite_number(row.get("value"))
        state = _state(row)
        unit = unit_of(config, row)
        part.bars.append(
            Bar(
                label=_label(config, row),
                value=value,
                text=(f"{shown(config, value)} {unit}".strip() if value is not None else "")
                or str(row.get("error") or NO_VALUE),
                color=STATE_HEX.get(state, "#1762b6")
                if state not in ("none", "unknown")
                # Bars without a state are the first colour of the palette.
                else "#1762b6",
            )
        )
    part.show = "bars"


def _table(part: CardPart, card: Card, rows: list[dict[str, Any]], clock: Clock) -> None:
    columns = list(card.options.columns)
    results = any(row.get("kind") == "result" for row in rows)
    head = [t("Subject") if results else t("Signal"), *[t(TABLE_HEADS[c]) for c in columns]]
    align = [
        "left",
        *["right" if c in ("last", "mean", "min", "max", "std") else "left" for c in columns],
    ]
    if results:
        head.append(t("Summary"))
        align.append("left")
    body: list[list[str]] = []
    states: list[str] = []
    for row in rows:
        config = effective(card.field, card.overrides, row)
        state = _state(row)
        values = row.get("values") or {}
        line = [_label(config, row)]
        for column in columns:
            if column in ("last", "mean", "min", "max", "std"):
                value = (
                    values.get(column) if row.get("kind") != "result" or column == "last" else None
                )
                line.append(
                    NO_VALUE if row.get("error") and column == "last" else shown(config, value)
                )
            elif column == "unit":
                line.append(unit_of(config, row))
            elif column == "time":
                line.append(clock.text(row.get("at"), "%d %b %H:%M"))
            else:
                line.append(t(STATE_WORDS.get(state, "")) if state in STATE_WORDS else "")
        if results:
            line.append(str(row.get("error") or row.get("summary") or ""))
        elif row.get("error"):
            line[0] = f"{line[0]} ({row['error']})"
        body.append(line)
        states.append(state if card.options.row_color and state in ("warning", "alarm") else "")
    part.table = Table(head=head, rows=body, align=align, states=states)
    part.show = "table"


def card_part(card: Card, data: dict[str, Any] | None, error: str | None, clock: Clock) -> CardPart:
    part = CardPart(card.title, card.description, card.kind, "empty", card, data)
    if error or data is None:
        part.empty = error or t("This section could not be read.")
        return part
    rows = data.get("rows") or []
    if card.kind in ("trend", "scatter"):
        _chart(part, card, data, clock)
        part.problems = [
            f"{row.get('label') or row.get('signal') or t('Signal')}: {row['error']}"
            for row in (data.get("lines") or [])
            if row.get("error")
        ][:8]
        return part
    if not rows:
        part.empty = t("Nothing to show.")
        return part
    if card.kind == "table":
        _table(part, card, rows, clock)
    elif card.kind == "bar" and card.options.bar_style != "gauge":
        _bars(part, card, rows)
    else:
        _tiles(part, card, rows)
    return part


def _events(section: dict[str, Any], item: dict[str, Any], clock: Clock) -> Part:
    part = Part("events", title=section.get("title") or t("Events"))
    data, error = item.get("data"), item.get("error")
    if error or data is None:
        part.error = error or t("This section could not be read.")
        return part
    counts = data.get("counts") or []
    part.counts = " · ".join(
        f"{c['title']}: {c['count']}{'+' if c.get('more') else ''}" for c in counts
    )
    events = data.get("events") or []
    total = int(data.get("total") or 0)
    if not total:
        part.empty = t("No event in the period.")
        return part
    if data.get("group_by"):
        head, rows, states = grouped.table(data, clock)
        part.counts = grouped.lead(data) or part.counts
        part.table = Table(
            head=head,
            rows=rows,
            align=["right", "left", "right", "right", "left", "left"],
            states=states,
        )
        part.note = grouped.more(data)
        return part
    part.table = Table(
        head=[t("Time"), t("Event"), t("About"), t("What happened")],
        rows=[
            [
                clock.text(event.get("at"), "%d %b %H:%M"),
                str(event.get("title") or event.get("kind") or ""),
                str(event.get("subject_name") or event.get("subject") or ""),
                str(event.get("summary") or ""),
            ]
            for event in events
        ],
        states=[
            {"critical": "alarm", "error": "alarm", "warning": "warning"}.get(
                str(event.get("severity") or ""), ""
            )
            for event in events
        ],
    )
    if total > len(events):
        part.note = t("The {n} newest of {total} are listed.", n=len(events), total=total)
    return part


def _alarms(section: dict[str, Any], item: dict[str, Any], clock: Clock) -> list[Part]:
    """An alarm performance section as parts every format draws like an events list: the
    figures under the section's title and the EEMUA 191 line, then one table each."""

    title = section.get("title") or t("Alarm performance (ISA-18.2)")
    data, error = item.get("data") or {}, item.get("error")
    if not data.get("reading"):
        return [Part("events", title=title, error=error or t("This section could not be read."))]
    found = alarm_performance.tables(data, clock)
    parts = []
    for index, table in enumerate(found):
        part = Part(
            "events",
            title=title if index == 0 else table["title"],
            counts=alarm_performance.lead(data) if index == 0 else "",
            note=table["note"],
            error=(error or "") if index == 0 else "",
        )
        if table["rows"]:
            part.table = Table(
                head=table["head"], rows=table["rows"], align=table["align"], states=table["states"]
            )
        else:
            part.empty = table["empty"]
        parts.append(part)
    return parts


def build(report: dict[str, Any], items: list[dict[str, Any]], info: dict[str, Any]) -> Document:
    """The document of ``report``: ``items`` as ``delivery.read_sections`` gives them, ``info``
    as ``pdf.render`` takes it."""

    clock = Clock(info.get("zone"))
    parts: list[Part] = []
    texts: list[list[md.Block]] = []
    for item in items:
        section = item["section"]
        kind = section.get("kind")
        half = section.get("width") == "half"
        if kind == "text":
            blocks = md.parse(section.get("text") or "")
            texts.append(blocks)
            parts.append(Part("text", blocks=blocks))
        elif kind == "card":
            card = Card.model_validate(section["card"])
            parts.append(
                Part(
                    "card",
                    half=half,
                    card=card_part(card, item.get("data"), item.get("error"), clock),
                )
            )
        elif kind == "events":
            part = _events(section, item, clock)
            part.half = half
            parts.append(part)
        elif kind == "alarms":
            parts.extend(_alarms(section, item, clock))
        elif kind == "break":
            parts.append(Part("break"))
    period = t("{start} to {end}", start=clock.text(info["start"]), end=clock.text(info["end"]))
    made = clock.text(info["made_at"])
    problems = int(info.get("problems") or 0)
    return Document(
        name=str(report.get("name") or ""),
        description=str(report.get("description") or ""),
        meta=[
            (t("Period"), period),
            (t("Made"), made),
            (t("Schedule"), str(info.get("cadence") or "")),
            (t("Time zone"), clock.name),
        ],
        outline=md.outline_of(texts),
        parts=parts,
        problems=(
            ""
            if not problems
            else t("1 section could not be read in full: it says why where it is.")
            if problems == 1
            else t("{n} sections could not be read in full: each says why where it is.", n=problems)
        ),
        period=period,
        made=made,
    )


def file_stem(report: dict[str, Any], made_at: datetime | str | None, zone: str | None) -> str:
    """``u-100-daily-report-2026-10-26``: the report's name and the day it ends."""

    stem = re.sub(r"[^A-Za-z0-9]+", "-", report.get("name") or "report").strip("-").lower()
    day = Clock(zone).text(made_at, "%Y-%m-%d")
    return f"{stem[:60] or 'report'}-{day}"


__all__ = ["Document", "Part", "build", "card_part", "file_stem", "hex_of"]
