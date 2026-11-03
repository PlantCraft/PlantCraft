"""A report as an A4 PDF (reportlab): the cover lines, then each section as View draws it.

Built only from what the sections read (``delivery.read``): the card data of
``query.cards.read_card`` and the events of the period. Charts are drawn here with plain shapes
(lines, bars, tiles), in the suite's colours on white paper; a value is coloured only by its
state (ok, warning, alarm), never as decoration. Everything that comes from data is escaped
before it reaches a ``Paragraph``. Fonts are the PDF's own (Helvetica): nothing is fetched.

This module puts the document together: the sections, the cover, numbered pages and the outline
(``render``). What it draws lives by subject: ``reports.pdf_style`` (colours, sizes and text
styles), ``reports.pdf_values`` (values as written, the report's clock), ``reports.pdf_markdown``
(the text cells), ``reports.pdf_charts`` (trends, axes, legends) and ``reports.pdf_cards`` (each
card's body, events, alarms and groups). The names other modules import from here stay
importable from here.
"""

from __future__ import annotations

import io
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    CondPageBreak,
    Flowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from dashcraft.dashboards.model import Card
from dashcraft.i18n import t
from dashcraft.reports.pdf_cards import (
    TABLE_HEADS,
    _groups_table,
    _meter,
    _plain_table,
    _problems,
    _range,
    _state,
    alarms_flowables,
    bars,
    card_flowables,
    events_flowables,
    tiles,
    value_table,
)
from dashcraft.reports.pdf_charts import (
    _axes,
    _empty,
    _legend,
    _segments,
    _steps_of,
    _time_ticks,
    nice_ticks,
    trend_drawing,
)
from dashcraft.reports.pdf_markdown import Heading, _md_table, _Rule, inline, markdown, spans_markup
from dashcraft.reports.pdf_style import (
    AXIS,
    BRAND,
    CONTENT,
    FRAME_PAD,
    GRID,
    GUTTER,
    INK,
    MARGIN,
    MUTED,
    NO_VALUE,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    PALE,
    PALETTE,
    SERIES,
    SEVERITY_COLORS,
    STATE_COLORS,
    STATE_WORDS,
    STYLES,
    TEXT2,
    _style,
)
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

# The names other modules import from here, from before the split (the old list named Clock,
# markdown, nice_ticks, number_text and render; every moved name stays importable).
__all__ = [
    "AXIS",
    "BRAND",
    "CONTENT",
    "Clock",
    "render",
    "FRAME_PAD",
    "GRID",
    "GUTTER",
    "Heading",
    "INK",
    "MARGIN",
    "MUTED",
    "NO_VALUE",
    "PAGE_HEIGHT",
    "PAGE_WIDTH",
    "PALE",
    "PALETTE",
    "SERIES",
    "SEVERITY_COLORS",
    "STATE_COLORS",
    "STATE_WORDS",
    "STYLES",
    "TABLE_HEADS",
    "TEXT2",
    "_Rule",
    "_axes",
    "_color",
    "_empty",
    "_esc",
    "_groups_table",
    "_instant",
    "_label",
    "_legend",
    "_md_table",
    "_meter",
    "_plain_table",
    "_problems",
    "_range",
    "_segments",
    "_state",
    "_steps_of",
    "_style",
    "_time_ticks",
    "alarms_flowables",
    "bars",
    "card_flowables",
    "events_flowables",
    "inline",
    "markdown",
    "nice_ticks",
    "number_text",
    "shown",
    "spans_markup",
    "tiles",
    "trend_drawing",
    "unit_of",
    "value_table",
]


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
