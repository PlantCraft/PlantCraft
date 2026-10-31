"""PDF drawings into pages: the words and the drawing commands of each page (pdfplumber, MIT).

A page with no text and almost no drawing commands is a scan: it is rendered to an image
(pypdfium2) and read like one (``raster.py``).
"""

from __future__ import annotations

import io

from doccraft.plantmap.reader.primitives import Page, Text, add_path
from doccraft.plantmap.reader.svg import DrawingError

MAX_PAGES = 60


def read_pdf(data: bytes, *, ocr: bool = True) -> list[Page]:
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - the image has it
        raise DrawingError("Reading PDF needs pdfplumber.") from exc
    pages: list[Page] = []
    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception as exc:  # pdfminer raises many kinds on a broken file
        raise DrawingError("This is not a readable PDF file.") from exc
    with pdf:
        if len(pdf.pages) > MAX_PAGES:
            raise DrawingError(f"This PDF has more than {MAX_PAGES} pages.")
        for number, source in enumerate(pdf.pages):
            page = Page(width=float(source.width), height=float(source.height))
            try:
                _vector(page, source)
            except Exception as exc:  # a broken page never stops the others
                page.notes.append(f"Page {number + 1} could not be read: {type(exc).__name__}.")
            if not page.texts and len(page.segs) < 10 and ocr:
                page = _scan(data, number, page)
            pages.append(page)
    return pages


def _vector(page: Page, source) -> None:
    # Turned text on drawings mostly reads bottom to top (a label along a vertical line).
    words = source.extract_words(
        x_tolerance=1.5,
        y_tolerance=2,
        keep_blank_chars=False,
        char_dir_rotated="btt",
        line_dir_rotated="ltr",
    )
    for word in words:
        page.texts.append(Text(word["text"], (word["x0"], word["top"], word["x1"], word["bottom"])))
    for obj in source.lines:
        add_path(page, _pts(obj), closed=False, filled=False, dashed=_dashed(obj))
    for obj in source.curves:
        pts = _pts(obj)
        closed = len(pts) > 2 and _same(pts[0], pts[-1])
        add_path(
            page, pts, closed=closed, filled=bool(obj.get("fill")), dashed=_dashed(obj), curved=True
        )
    for obj in source.rects:
        x0, y0, x1, y1 = obj["x0"], obj["top"], obj["x1"], obj["bottom"]
        if x1 - x0 < 0.5 or y1 - y0 < 0.5:
            # A hairline rectangle is a line (some exporters draw lines this way).
            add_path(page, [(x0, y0), (x1, y1)], closed=False, filled=False, dashed=False)
            continue
        add_path(
            page,
            [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
            closed=True,
            filled=bool(obj.get("fill")) and not obj.get("stroke"),
            dashed=_dashed(obj),
        )


def _scan(data: bytes, number: int, page: Page) -> Page:
    from doccraft.plantmap.reader.raster import read_image_array

    try:
        import pypdfium2
    except ImportError:  # pragma: no cover
        page.notes.append("This page is a scan and pypdfium2 is not installed.")
        return page
    pdf = pypdfium2.PdfDocument(data)
    try:
        scale = 200 / 72
        image = pdf[number].render(scale=scale).to_pil()
    finally:
        pdf.close()
    scanned = read_image_array(image, scale=scale)
    scanned.notes.insert(0, "This page has no text layer: it was read with OCR.")
    return scanned


def _pts(obj) -> list[tuple[float, float]]:
    return [(float(x), float(y)) for x, y in obj.get("pts") or []]


def _dashed(obj) -> bool:
    dash = obj.get("dash")
    if not dash:
        return False
    pattern = dash[0] if isinstance(dash, (tuple, list)) else None
    return bool(pattern) and any(float(v) > 0 for v in pattern)


def _same(a, b) -> bool:
    return abs(a[0] - b[0]) < 0.01 and abs(a[1] - b[1]) < 0.01
