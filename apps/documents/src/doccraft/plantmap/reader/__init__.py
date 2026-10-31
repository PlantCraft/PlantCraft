"""The drawing reader: a P&ID file in, the plant it shows out (``graph.Result``).

``read_drawing(data, filename)`` picks the format from the file's first bytes (SVG, PDF, PNG,
JPEG, TIFF), reads every page and recognises each; never raises on a bad drawing other than
``DrawingError`` with a message a person can act on.
"""

from __future__ import annotations

from typing import Any

from doccraft.plantmap.reader.graph import recognise
from doccraft.plantmap.reader.svg import DrawingError

MAX_BYTES = 40 * 1024 * 1024

__all__ = ["DrawingError", "kind_of", "read_drawing"]


def kind_of(data: bytes, filename: str = "") -> str:
    head = data[:16]
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"\x89PNG"):
        return "png"
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[:4] in {b"II*\x00", b"MM\x00*"}:
        return "tiff"
    text = data[:2048].lstrip().lower()
    if text.startswith(b"<?xml") or text.startswith(b"<svg") or b"<svg" in text:
        return "svg"
    raise DrawingError("Send a P&ID as PDF, SVG, PNG, JPEG or TIFF.")


def read_drawing(data: bytes, filename: str = "") -> list[dict[str, Any]]:
    if len(data) > MAX_BYTES:
        raise DrawingError("The file is larger than 40 MB.")
    kind = kind_of(data, filename)
    if kind == "svg":
        from doccraft.plantmap.reader.svg import read_svg

        pages = [read_svg(data)]
    elif kind == "pdf":
        from doccraft.plantmap.reader.pdf import read_pdf

        pages = read_pdf(data)
    else:
        from doccraft.plantmap.reader.raster import read_image

        pages = [read_image(data)]
    out = []
    for number, page in enumerate(pages, start=1):
        result = recognise(page).as_dict()
        result["page"] = number
        result["source"] = page.source
        result["width"] = page.width
        result["height"] = page.height
        out.append(result)
    return out
