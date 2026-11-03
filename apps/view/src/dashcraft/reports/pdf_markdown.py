"""The report PDF's text cells: Markdown (``reports.markdown``) as reportlab flowables."""

from __future__ import annotations

from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    Flowable,
    ListFlowable,
    ListItem,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from dashcraft.reports import markdown as md
from dashcraft.reports.pdf_style import AXIS, CONTENT, GRID, STYLES, TEXT2

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
