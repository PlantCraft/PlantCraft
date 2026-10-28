"""A Word file as a page a browser shows (owner, 2026-10-27: "seria bom conseguir ver os arquivos
Word"): its headings, paragraphs (bold and italic kept), lists and tables, in document order.

The file is untrusted: the page is built from its text only, every piece escaped, with a fixed
set of tags (no attribute, style, link or image of the file reaches it), so it is shown inside
the app's own page as it is. A PDF opens in the browser's viewer instead; the other formats are
read on the document's page as their text.
"""

from __future__ import annotations

import html
import io
import re

from doccraft.library.extract import Unreadable, _check_zip

MAX_BLOCKS = 20_000  # a page of a few MB at most, whatever the file holds


def docx_html(data: bytes) -> str:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    _check_zip(data)
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as error:  # a reader's own error on a broken file
        raise Unreadable(f"The file could not be read as DOCX: {type(error).__name__}.") from error
    out: list[str] = []
    listing = False
    for count, child in enumerate(document.element.body.iterchildren()):
        if count >= MAX_BLOCKS:
            out.append("<p><em>…</em></p>")
            break
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = Paragraph(child, document)
            style = (paragraph.style.name if paragraph.style is not None else "") or ""
            text = _runs(paragraph)
            item = style.startswith("List") or child.find(".//{*}numPr") is not None
            if listing and not item:
                out.append("</ul>")
                listing = False
            if not text:
                continue
            level = re.match(r"(?:Heading|Título)\s*(\d)", style)
            if style == "Title" or level:
                depth = min(4, int(level.group(1)) + 1 if level else 1)
                out.append(f"<h{depth}>{text}</h{depth}>")
            elif item:
                if not listing:
                    out.append("<ul>")
                    listing = True
                out.append(f"<li>{text}</li>")
            else:
                out.append(f"<p>{text}</p>")
        elif tag == "tbl":
            if listing:
                out.append("</ul>")
                listing = False
            table = Table(child, document)
            rows = []
            for index, row in enumerate(table.rows):
                cell = "th" if index == 0 else "td"
                cells = "".join(
                    f"<{cell}>{html.escape(item.text.strip())}</{cell}>" for item in row.cells
                )
                rows.append(f"<tr>{cells}</tr>")
            out.append(f"<table>{''.join(rows)}</table>")
    if listing:
        out.append("</ul>")
    return "\n".join(out)


def _runs(paragraph) -> str:
    parts, plain = [], ""
    for run in paragraph.runs:
        plain += run.text
        text = html.escape(run.text)
        if not text:
            continue
        if run.bold:
            text = f"<strong>{text}</strong>"
        if run.italic:
            text = f"<em>{text}</em>"
        parts.append(text)
    # Text outside runs (fields, hyperlinks): the paragraph's own text, escaped, unformatted.
    if len(plain.strip()) < len(paragraph.text.strip()):
        return html.escape(paragraph.text.strip())
    return "".join(parts).strip()
