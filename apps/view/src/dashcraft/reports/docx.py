"""A report as a Word file (.docx), to change and pass on: written directly as WordprocessingML.

The headings of the text cells are Word's own Heading 1 to 4, so Word's navigation pane and its
table of contents find them; tables are Word tables (values a reader can edit and copy), charts
are the PDF's pictures (``raster.png``), and colours mean what they mean in the PDF: a value is
coloured only by its state. Nothing but the standard library and Pillow: the file is a zip of
XML parts, the smallest set Word, LibreOffice and Google Docs open.
"""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from typing import Any
from xml.sax.saxutils import escape, quoteattr

from dashcraft.i18n import t
from dashcraft.reports import markdown as md
from dashcraft.reports import pdf, raster
from dashcraft.reports.document import CardPart, Document, Part, Table

EMU = 12700  # per point
# A4 with 2 cm margins: the width the body has, in points (and in twentieths of a point).
BODY_PT = 595.3 - 2 * 56.7
BODY_TW = round(BODY_PT * 20)
STATE_FILL = {"warning": "FFF4E5", "alarm": "FDECEA"}
STATE_TEXT = {"ok": "1F8F3F", "warning": "B86E00", "alarm": "D92D20", "unknown": "6E6E73"}


def _attr(value: str) -> str:
    return quoteattr(value)


class _Writer:
    def __init__(self) -> None:
        self.body: list[str] = []
        self.media: list[tuple[str, bytes]] = []
        self.links: list[str] = []
        self.bookmark = 0

    # Runs and paragraphs ----------------------------------------------------------------

    def run(
        self,
        text: str,
        *,
        bold: bool = False,
        italic: bool = False,
        code: bool = False,
        color: str = "",
        size: float = 0,
        style: str = "",
    ) -> str:
        props = []
        if style:
            props.append(f"<w:rStyle w:val={_attr(style)}/>")
        if code:
            props.append('<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:cs="Consolas"/>')
        if bold:
            props.append("<w:b/>")
        if italic:
            props.append("<w:i/>")
        if color:
            props.append(f'<w:color w:val="{color}"/>')
        if size:
            props.append(f'<w:sz w:val="{round(size * 2)}"/>')
        rpr = f"<w:rPr>{''.join(props)}</w:rPr>" if props else ""
        return f'<w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'

    def spans(self, spans: list[md.Span], **kw: Any) -> str:
        out = []
        for span in spans:
            if span.style == "link":
                self.links.append(span.href)
                rid = f"rIdLink{len(self.links)}"
                out.append(
                    f'<w:hyperlink r:id="{rid}">{self.run(span.text, style="Hyperlink", **kw)}'
                    "</w:hyperlink>"
                )
            else:
                out.append(
                    self.run(
                        span.text,
                        bold=span.style == "bold" or kw.get("bold", False),
                        italic=span.style == "italic",
                        code=span.style == "code",
                        color=kw.get("color", ""),
                        size=kw.get("size", 0),
                    )
                )
        return "".join(out)

    def paragraph(self, runs: str, style: str = "", extra: str = "") -> None:
        ppr = f'<w:pStyle w:val="{style}"/>' if style else ""
        props = f"<w:pPr>{ppr}{extra}</w:pPr>" if ppr or extra else ""
        self.body.append(f"<w:p>{props}{runs}</w:p>")

    def text(self, value: str, style: str = "", **kw: Any) -> None:
        self.paragraph(self.run(value, **kw), style)

    def heading(self, level: int, spans: list[md.Span], anchor: str = "") -> None:
        self.bookmark += 1
        mark = (
            f'<w:bookmarkStart w:id="{self.bookmark}" w:name={_attr(("_" + anchor)[:40])}/>'
            f'<w:bookmarkEnd w:id="{self.bookmark}"/>'
            if anchor
            else ""
        )
        self.paragraph(mark + self.spans(spans), f"Heading{min(max(level, 1), 4)}")

    def page_break(self) -> None:
        self.body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')

    # Pictures and tables -----------------------------------------------------------------

    def picture(self, png: bytes, width_pt: float, height_pt: float, name: str) -> None:
        self.media.append((f"image{len(self.media) + 1}.png", png))
        index = len(self.media)
        rid = f"rIdImg{index}"
        if width_pt > BODY_PT:
            height_pt, width_pt = height_pt * BODY_PT / width_pt, BODY_PT
        cx, cy = round(width_pt * EMU), round(height_pt * EMU)
        self.body.append(
            "<w:p><w:r><w:drawing>"
            f'<wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
            f'<wp:docPr id="{index}" name={_attr(name[:60] or "Chart")}/>'
            '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            f'<pic:nvPicPr><pic:cNvPr id="{index}" name="image{index}.png"/><pic:cNvPicPr/>'
            f'</pic:nvPicPr><pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/>'
            '</a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/>'
            f'<a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/>'
            "</a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline>"
            "</w:drawing></w:r></w:p>"
        )

    def table(self, table: Table, *, widths: list[float] | None = None) -> None:
        columns = len(table.head)
        if not columns:
            return
        widths = widths or [1.0] * columns
        total = sum(widths) or 1
        grid = [round(BODY_TW * w / total) for w in widths]
        out = [
            '<w:tbl><w:tblPr><w:tblStyle w:val="ReportTable"/><w:tblW w:w="0" w:type="auto"/>'
            '<w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="0" '
            'w:lastColumn="0" w:noHBand="1" w:noVBand="1"/></w:tblPr><w:tblGrid>'
            + "".join(f'<w:gridCol w:w="{w}"/>' for w in grid)
            + "</w:tblGrid>"
        ]

        def cell(text: str | list[md.Span], index: int, *, head: bool, fill: str = "") -> str:
            align = (table.align[index] if index < len(table.align) else "left") or "left"
            jc = {"right": "right", "center": "center"}.get(align, "left")
            shade = f'<w:shd w:val="clear" w:color="auto" w:fill="{fill}"/>' if fill else ""
            runs = (
                self.spans(text, bold=head, size=8.5)
                if isinstance(text, list)
                else self.run(text, bold=head, size=8.5, color="6E6E73" if head else "")
            )
            return (
                f'<w:tc><w:tcPr><w:tcW w:w="{grid[index]}" w:type="dxa"/>{shade}</w:tcPr>'
                f'<w:p><w:pPr><w:pStyle w:val="TableText"/><w:jc w:val="{jc}"/></w:pPr>{runs}'
                "</w:p></w:tc>"
            )

        out.append(
            "<w:tr><w:trPr><w:tblHeader/></w:trPr>"
            + "".join(cell(text, i, head=True) for i, text in enumerate(table.head))
            + "</w:tr>"
        )
        for row_index, row in enumerate(table.rows):
            state = table.states[row_index] if row_index < len(table.states) else ""
            fill = STATE_FILL.get(state, "")
            cells = (list(row) + [""] * columns)[:columns]
            out.append(
                "<w:tr>" + "".join(cell(text, i, head=False, fill=fill) for i, text in enumerate(cells))
                + "</w:tr>"
            )  # fmt: skip
        out.append("</w:tbl>")
        self.body.append("".join(out))
        self.paragraph("", extra='<w:spacing w:after="60"/>')

    # Report parts ------------------------------------------------------------------------

    def blocks(self, blocks: list[md.Block]) -> None:
        for block in blocks:
            if block.kind == "heading":
                self.heading(block.level, block.spans, block.anchor)
            elif block.kind == "paragraph":
                self.paragraph(self.spans(block.spans))
            elif block.kind == "quote":
                self.paragraph(self.spans(block.spans), "Quote")
            elif block.kind == "rule":
                self.paragraph(
                    "",
                    extra='<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" '
                    'w:color="D2D2D7"/></w:pBdr>',
                )
            elif block.kind == "list":
                num = "2" if block.numbered else "1"
                for item in block.items:
                    self.paragraph(
                        self.spans(item),
                        "ListParagraph",
                        f'<w:numPr><w:ilvl w:val="0"/><w:numId w:val="{num}"/></w:numPr>',
                    )
            elif block.kind == "table":
                self.table(Table(head=[md.plain(c) for c in block.head], rows=block.rows,
                                 align=block.align))  # type: ignore[arg-type]  # fmt: skip

    def card(self, part: CardPart, clock: pdf.Clock) -> None:
        if part.title:
            self.text(part.title, "CardTitle")
        if part.description:
            self.text(part.description, "Note")
        if part.show == "empty":
            self.text(part.empty, "Note")
        elif part.show in ("chart", "scatter"):
            drawing, _ = pdf.trend_drawing(
                part.card, part.data or {}, BODY_PT, clock, scatter=part.show == "scatter"
            )
            self.picture(raster.png(drawing), drawing.width, drawing.height, part.title)
            if part.legend is not None:
                self.table(part.legend, widths=[3.2, 1, 1, 1, 1])
        elif part.show == "bars":
            drawing = pdf.bars(part.card, (part.data or {}).get("rows") or [], BODY_PT)
            self.picture(raster.png(drawing), drawing.width, drawing.height, part.title)
        elif part.show == "tiles":
            self.tiles(part)
        elif part.show == "table" and part.table is not None:
            self.table(part.table, widths=[3, *[1] * (len(part.table.head) - 1)])
        for note in part.notes:
            self.text(note, "Note")
        for problem in part.problems:
            self.text(problem, "Note", color=STATE_TEXT["alarm"])

    def tiles(self, part: CardPart) -> None:
        per_row = max(1, min(len(part.tiles), 4))
        width = round(BODY_TW / per_row)
        rows = [part.tiles[i : i + per_row] for i in range(0, len(part.tiles), per_row)]
        out = [
            '<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/><w:tblCellSpacing w:w="40" '
            'w:type="dxa"/></w:tblPr><w:tblGrid>'
            + "".join(f'<w:gridCol w:w="{width}"/>' for _ in range(per_row))
            + "</w:tblGrid>"
        ]
        for row in rows:
            out.append("<w:tr>")
            for tile in (row + [None] * per_row)[:per_row]:
                if tile is None:
                    out.append(
                        f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/></w:tcPr><w:p/></w:tc>'
                    )
                    continue
                color = STATE_TEXT.get(tile.state, "1D1D1F") if tile.state != "none" else "1D1D1F"
                bar = STATE_TEXT.get(tile.state, "D2D2D7")
                value = self.run(tile.value, bold=True, size=16, color=color) + (
                    self.run(f" {tile.unit}", size=9, color="6E6E73") if tile.unit else ""
                )
                share = f" · {round(tile.share * 100)}%" if tile.share is not None else ""
                detail = (tile.detail + share).strip(" ·")
                out.append(
                    f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>'
                    '<w:shd w:val="clear" w:color="auto" w:fill="F5F5F7"/>'
                    f'<w:tcBorders><w:left w:val="single" w:sz="18" w:color="{bar}"/></w:tcBorders>'
                    "</w:tcPr>"
                    f'<w:p><w:pPr><w:pStyle w:val="TableText"/></w:pPr>'
                    f"{self.run(tile.label, size=8, color='424245')}</w:p>"
                    f'<w:p><w:pPr><w:pStyle w:val="TableText"/></w:pPr>{value}</w:p>'
                    + (
                        f'<w:p><w:pPr><w:pStyle w:val="TableText"/></w:pPr>'
                        f"{self.run(detail, size=7.5, color=STATE_TEXT['alarm'] if tile.error else '6E6E73')}</w:p>"
                        if detail
                        else ""
                    )
                    + "</w:tc>"
                )
            out.append("</w:tr>")
        out.append("</w:tbl>")
        self.body.append("".join(out))
        self.paragraph("", extra='<w:spacing w:after="60"/>')

    def events(self, part: Part) -> None:
        self.text(part.title, "CardTitle")
        if part.error:
            self.text(part.error, "Note", color=STATE_TEXT["alarm"])
            return
        if part.counts:
            self.text(part.counts, "Note")
        if part.empty:
            self.text(part.empty, "Note")
        elif part.table is not None:
            # A list of events, or the ranked groups of a section that counts them.
            four = len(part.table.head) == 4
            widths = [1.1, 1.6, 1.6, 3.2] if four else [0.35, 1.6, 0.6, 0.6, 1.0, 3.0]
            self.table(part.table, widths=widths)
        if part.note:
            self.text(part.note, "Note")


def _document_xml(body: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
        f"<w:body>{body}"
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" '
        'w:bottom="1134" w:left="1134" w:header="567" w:footer="567" w:gutter="0"/></w:sectPr>'
        "</w:body></w:document>"
    )


def _style(sid: str, name: str, *, kind: str = "paragraph", ppr: str = "", rpr: str = "",
           based: str = "Normal", extra: str = "") -> str:  # fmt: skip
    base = f'<w:basedOn w:val="{based}"/>' if based and sid != "Normal" else ""
    return (
        f'<w:style w:type="{kind}" w:styleId="{sid}"><w:name w:val="{name}"/>{base}{extra}'
        f"<w:qFormat/><w:pPr>{ppr}</w:pPr><w:rPr>{rpr}</w:rPr></w:style>"
    )


def _heading(level: int, size: float, before: int) -> str:
    return _style(
        f"Heading{level}",
        f"heading {level}",
        ppr=f'<w:keepNext/><w:spacing w:before="{before}" w:after="80"/>'
        f'<w:outlineLvl w:val="{level - 1}"/>',
        rpr=f'<w:b/><w:color w:val="1D1D1F"/><w:sz w:val="{round(size * 2)}"/>',
        extra='<w:next w:val="Normal"/>',
    )


STYLES_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" '
    'w:cs="Calibri" w:eastAsia="Calibri"/><w:sz w:val="20"/><w:lang w:val="en-US"/></w:rPr>'
    '</w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="100" w:line="264" '
    'w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
    + _style("Normal", "Normal", rpr='<w:color w:val="1D1D1F"/>', based="")
    + _style(
        "Title",
        "Title",
        ppr='<w:spacing w:after="60"/>',
        rpr='<w:b/><w:sz w:val="44"/>',
        extra='<w:next w:val="Normal"/>',
    )  # fmt: skip
    + _style("Eyebrow", "Eyebrow", rpr='<w:b/><w:color w:val="3442A6"/><w:sz w:val="16"/>')
    + _style("Subtitle", "Subtitle", rpr='<w:color w:val="424245"/><w:sz w:val="21"/>')
    + _heading(1, 15, 280)
    + _heading(2, 13, 220)
    + _heading(3, 11.5, 180)
    + _heading(4, 10.5, 140)
    + _style(
        "CardTitle",
        "Card title",
        ppr='<w:keepNext/><w:spacing w:before="160" w:after="40"/>',
        rpr='<w:b/><w:sz w:val="20"/>',
    )  # fmt: skip
    + _style(
        "Note",
        "Note",
        ppr='<w:spacing w:after="60"/>',
        rpr='<w:color w:val="6E6E73"/><w:sz w:val="16"/>',
    )  # fmt: skip
    + _style(
        "Quote",
        "Quote",
        ppr='<w:ind w:left="360"/><w:pBdr><w:left w:val="single" '
        'w:sz="12" w:space="8" w:color="D2D2D7"/></w:pBdr>',
        rpr='<w:i/><w:color w:val="424245"/>',
    )  # fmt: skip
    + _style(
        "ListParagraph", "List Paragraph", ppr='<w:spacing w:after="40"/><w:ind w:left="360"/>'
    )
    + _style(
        "TableText",
        "Table text",
        ppr='<w:spacing w:before="20" w:after="20"/>',
        rpr='<w:sz w:val="17"/>',
    )  # fmt: skip
    + '<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/>'
    '<w:rPr><w:color w:val="1762B6"/><w:u w:val="single"/></w:rPr></w:style>'
    '<w:style w:type="table" w:styleId="ReportTable"><w:name w:val="Report table"/><w:tblPr>'
    '<w:tblBorders><w:top w:val="single" w:sz="4" w:color="D2D2D7"/><w:bottom w:val="single" '
    'w:sz="4" w:color="D2D2D7"/><w:insideH w:val="single" w:sz="4" w:color="E8E8ED"/>'
    '</w:tblBorders><w:tblCellMar><w:left w:w="80" w:type="dxa"/><w:right w:w="80" '
    'w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>'
    "</w:styles>"
)

NUMBERING_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:start w:val="1"/>'
    '<w:numFmt w:val="bullet"/><w:lvlText w:val="•"/><w:lvlJc w:val="left"/><w:pPr>'
    '<w:ind w:left="360" w:hanging="240"/></w:pPr></w:lvl></w:abstractNum>'
    '<w:abstractNum w:abstractNumId="1"><w:lvl w:ilvl="0"><w:start w:val="1"/>'
    '<w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/><w:lvlJc w:val="left"/><w:pPr>'
    '<w:ind w:left="360" w:hanging="300"/></w:pPr></w:lvl></w:abstractNum>'
    '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
    '<w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num>'
    "</w:numbering>"
)

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Default Extension="png" ContentType="image/png"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
    'officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-'
    'officedocument.wordprocessingml.styles+xml"/>'
    '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-'
    'officedocument.wordprocessingml.numbering+xml"/>'
    '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-'
    'package.core-properties+xml"/>'
    "</Types>"
)

PACKAGE_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/officeDocument" Target="word/document.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/'
    'metadata/core-properties" Target="docProps/core.xml"/>'
    "</Relationships>"
)

REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _document_rels(writer: _Writer) -> str:
    rels = [
        f'<Relationship Id="rIdStyles" Type="{REL}/styles" Target="styles.xml"/>',
        f'<Relationship Id="rIdNumbering" Type="{REL}/numbering" Target="numbering.xml"/>',
    ]
    for index, (name, _) in enumerate(writer.media, start=1):
        rels.append(f'<Relationship Id="rIdImg{index}" Type="{REL}/image" Target="media/{name}"/>')
    for index, href in enumerate(writer.links, start=1):
        rels.append(
            f'<Relationship Id="rIdLink{index}" Type="{REL}/hyperlink" Target={_attr(href)} '
            'TargetMode="External"/>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(rels)
        + "</Relationships>"
    )


def _core(document: Document, now: datetime) -> str:
    stamp = now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/'
        'core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>{escape(document.name)}</dc:title>"
        f"<dc:subject>{escape(t('Report from {period}', period=document.period))}</dc:subject>"
        "<dc:creator>PlantCraft View</dc:creator>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{stamp}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{stamp}</dcterms:modified>'
        "</cp:coreProperties>"
    )


def render(document: Document, zone: str | None, now: datetime | None = None) -> bytes:
    """The .docx of ``document`` (``document.build``)."""

    clock = pdf.Clock(zone)
    writer = _Writer()
    writer.text(t("PLANTCRAFT VIEW · REPORT"), "Eyebrow")
    writer.text(document.name, "Title")
    if document.description:
        writer.text(document.description, "Subtitle")
    writer.paragraph(
        "".join(
            writer.run(f"{label}: ", color="6E6E73", size=8.5)
            + writer.run(value, bold=True, size=8.5)
            + writer.run("    ", size=8.5)
            for label, value in document.meta
            if value
        ),
        extra='<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="6" w:color="D2D2D7"/></w:pBdr>',
    )
    if document.problems:
        writer.text(document.problems, "Note", color=STATE_TEXT["alarm"])
    for part in document.parts:
        if part.kind == "text":
            writer.blocks(part.blocks)
        elif part.kind == "card" and part.card is not None:
            writer.card(part.card, clock)
        elif part.kind == "events":
            writer.events(part)
        elif part.kind == "break":
            writer.page_break()
    if not document.parts:
        writer.text(t("This report has no sections yet."), "Note")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", CONTENT_TYPES)
        package.writestr("_rels/.rels", PACKAGE_RELS)
        package.writestr("docProps/core.xml", _core(document, now or datetime.now(UTC)))
        package.writestr("word/document.xml", _document_xml("".join(writer.body)))
        package.writestr("word/styles.xml", STYLES_XML)
        package.writestr("word/numbering.xml", NUMBERING_XML)
        package.writestr("word/_rels/document.xml.rels", _document_rels(writer))
        for name, data in writer.media:
            package.writestr(f"word/media/{name}", data)
    return buffer.getvalue()


MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

__all__ = ["MEDIA_TYPE", "render"]
