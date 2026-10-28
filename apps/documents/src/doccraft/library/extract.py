"""A file into sections: each with its page (or sheet, or slide) and the headings above it.

Every reader is a mature, permissively licensed library (pypdf, python-docx, openpyxl,
python-pptx) or the standard library. A file is untrusted: limits on size, pages and zip
expansion are checked before a reader opens it, and a file that cannot be read gives a
``Unreadable`` with a reason a person can act on, never an exception.
"""

from __future__ import annotations

import csv
import html
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePath

MAX_PAGES = 5000
MAX_ZIP_RATIO = 100  # an Office file that expands more than this is refused (zip bomb)
MAX_ZIP_BYTES = 500 * 1024 * 1024

FORMATS = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".docm": "docx",
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
    ".pptx": "pptx",
    ".txt": "text",
    ".md": "markdown",
    ".markdown": "markdown",
    ".csv": "csv",
    ".html": "html",
    ".htm": "html",
}


@dataclass
class Section:
    text: str
    page: int | None = None  # 1-based page, sheet or slide
    heading: list[str] = field(default_factory=list)  # the headings above, outermost first


@dataclass
class Extracted:
    format: str
    sections: list[Section]
    pages: int
    title: str = ""


class Unreadable(Exception):
    """A file the app cannot read, with the reason shown to the person."""


def format_of(filename: str) -> str | None:
    return FORMATS.get(PurePath(filename).suffix.lower())


def extract(data: bytes, filename: str) -> Extracted:
    kind = format_of(filename)
    if kind is None:
        raise Unreadable(
            f"{PurePath(filename).suffix or 'This'} files are not read; send PDF, Word, Excel, PowerPoint, text, Markdown, CSV or HTML."
        )
    if kind in ("docx", "xlsx", "pptx"):
        _check_zip(data)
    try:
        return READERS[kind](data)
    except Unreadable:
        raise
    except Exception as error:  # a reader's own error on a broken file
        raise Unreadable(
            f"The file could not be read as {kind.upper()}: {type(error).__name__}."
        ) from error


def _check_zip(data: bytes) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise Unreadable("The file is not a valid Office document.") from error
    expanded = sum(info.file_size for info in archive.infolist())
    if expanded > MAX_ZIP_BYTES or expanded > MAX_ZIP_RATIO * max(len(data), 1):
        raise Unreadable("The file expands to too much data to be read safely.")


def _pdf(data: bytes) -> Extracted:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as error:
            raise Unreadable("The PDF is protected by a password.") from error
    if len(reader.pages) > MAX_PAGES:
        raise Unreadable(f"The PDF has more than {MAX_PAGES} pages.")
    # Headings are the lines set in a larger type than the body: the body's size is the one most
    # characters use, and each larger size is one heading level, the largest first.
    # A run's style is (size, bold); a bold run of the body's size is the smallest heading.
    pages: list[tuple[str, list[tuple[tuple[float, bool], str]]]] = []
    weight: dict[tuple[float, bool], int] = {}
    for page in reader.pages:
        runs: list[tuple[tuple[float, bool], str]] = []

        def visit(text, _cm, tm, font, size, runs=runs):
            name = str((font or {}).get("/BaseFont", ""))
            key = (round(abs(size * (tm[0] or 1)), 1), "Bold" in name or "bold" in name)
            if text.strip():
                runs.append((key, text.strip()))
                weight[key] = weight.get(key, 0) + len(text)

        text = page.extract_text(visitor_text=visit) or ""
        pages.append((_clean(text), runs))
    body = max(weight, key=weight.get) if weight else (0.0, False)
    levels = sorted(
        {
            style
            for style in weight
            if style[0] > body[0] + 0.5
            or (abs(style[0] - body[0]) <= 0.5 and style[1] and not body[1])
        },
        reverse=True,
    )
    sections: list[Section] = []
    path: list[str] = []
    title = ""
    for number, (text, runs) in enumerate(pages, 1):
        headings = {
            _clean(run): levels.index(size) + 1
            for size, run in runs
            if size in levels and 2 < len(run) <= 140
        }
        buffer: list[str] = []
        last = None  # the level of the line before, when it was a heading
        for line in text.splitlines():
            level = headings.get(line.strip())
            if level is None:
                buffer.append(line)
                last = None
                continue
            if last == level and path:  # a heading wrapped on two lines
                path[-1] = f"{path[-1]} {line.strip()}"
                continue
            if "\n".join(buffer).strip():
                sections.append(Section("\n".join(buffer).strip(), number, list(path)))
            buffer = []
            path = path[: level - 1] + [line.strip()]
            last = level
        if number == 1 and path:
            title = path[0]
        if "\n".join(buffer).strip():
            sections.append(Section("\n".join(buffer).strip(), number, list(path)))
    meta = reader.metadata
    title = str(meta.get("/Title") or "") if meta and meta.get("/Title") else title
    return Extracted("pdf", sections, len(reader.pages), title)


def _docx(data: bytes) -> Extracted:
    import docx

    document = docx.Document(io.BytesIO(data))
    sections: list[Section] = []
    heading: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            sections.append(Section("\n".join(buffer), None, list(heading)))
            buffer.clear()

    for block in _docx_blocks(document):
        if isinstance(block, tuple):  # a heading: (level, text)
            flush()
            level, text = block
            heading[:] = heading[: level - 1] + [text]
        elif block:
            buffer.append(block)
    flush()
    title = document.core_properties.title or ""
    return Extracted("docx", sections, 0, title)


def _docx_blocks(document):  # paragraphs and tables in document order
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = Paragraph(child, document)
            text = _clean(paragraph.text)
            style = (paragraph.style.name if paragraph.style is not None else "") or ""
            level = re.match(r"(?:Heading|Título)\s*(\d)", style)
            if text and (level or style == "Title"):
                yield (int(level.group(1)) if level else 1, text)
            else:
                yield text
        elif tag == "tbl":
            table = Table(child, document)
            rows = []
            for row in table.rows:
                cells = [_clean(cell.text) for cell in row.cells]
                rows.append(" | ".join(cells))
            yield "\n".join(rows)


def _xlsx(data: bytes) -> Extracted:
    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    sections = []
    for number, sheet in enumerate(book.worksheets, 1):
        header: list[str] | None = None
        lines = []
        for row in sheet.iter_rows(values_only=True):
            values = ["" if value is None else str(value) for value in row]
            if not any(values):
                continue
            filled = [value for value in values if value]
            if header is None and len(filled) >= 2:
                header = values
                continue
            if header and len(filled) >= 2:  # one row as "column: value" pairs
                lines.append("; ".join(f"{h}: {v}" for h, v in zip(header, values) if h and v))
            else:
                lines.append(" ".join(filled))
        if lines:
            sections.append(Section("\n".join(lines), number, [sheet.title]))
    book.close()
    return Extracted("xlsx", sections, len(sections))


def _pptx(data: bytes) -> Extracted:
    from pptx import Presentation

    deck = Presentation(io.BytesIO(data))
    sections = []
    for number, slide in enumerate(deck.slides, 1):
        texts = [shape.text_frame.text for shape in slide.shapes if shape.has_text_frame]
        text = _clean("\n".join(texts))
        if text:
            title = slide.shapes.title.text_frame.text if slide.shapes.title is not None else ""
            sections.append(Section(text, number, [_clean(title)] if title else []))
    return Extracted("pptx", sections, len(deck.slides))


def _text(data: bytes) -> Extracted:
    return Extracted("text", [Section(_clean(_decode(data)), None, [])], 0)


def _markdown(data: bytes) -> Extracted:
    sections: list[Section] = []
    heading: list[str] = []
    buffer: list[str] = []
    title = ""
    for line in _decode(data).splitlines():
        match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if match:
            if buffer and "".join(buffer).strip():
                sections.append(Section(_clean("\n".join(buffer)), None, list(heading)))
            buffer = []
            level, text = len(match.group(1)), match.group(2).strip()
            title = title or text
            heading[:] = heading[: level - 1] + [text]
        else:
            buffer.append(line)
    if buffer and "".join(buffer).strip():
        sections.append(Section(_clean("\n".join(buffer)), None, list(heading)))
    return Extracted("markdown", sections, 0, title)


def _csv(data: bytes) -> Extracted:
    rows = list(csv.reader(io.StringIO(_decode(data))))
    if not rows:
        return Extracted("csv", [], 0)
    header, lines = rows[0], []
    for row in rows[1:]:
        lines.append("; ".join(f"{h}: {v}" for h, v in zip(header, row) if h and v))
    return Extracted("csv", [Section("\n".join(lines), None, [])], 0)


def _html(data: bytes) -> Extracted:
    text = _decode(data)
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text)
    text = re.sub(r"(?i)<h([1-6])[^>]*>", lambda m: "\n" + "#" * int(m.group(1)) + " ", text)
    text = re.sub(r"(?i)</h[1-6]>|<br\s*/?>|</p>|</li>|</tr>", "\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    extracted = _markdown(text.encode())
    extracted.format = "html"
    return extracted


READERS = {
    "pdf": _pdf,
    "docx": _docx,
    "xlsx": _xlsx,
    "pptx": _pptx,
    "text": _text,
    "markdown": _markdown,
    "csv": _csv,
    "html": _html,
}


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _clean(text: str) -> str:
    text = text.replace("\x00", "").replace("\r", "")
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
