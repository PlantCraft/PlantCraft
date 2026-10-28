"""The PDF's charts as PNG pictures (for the Word file), drawn with Pillow.

``pdf.py`` draws a chart as a reportlab ``Drawing`` of plain shapes: lines, polylines,
rectangles and strings. This walks those shapes onto a Pillow image, scaled up for print, so the
Word file shows the very chart the PDF does, without another drawing library (Pillow comes with
reportlab; reportlab's own bitmap renderer needs Cairo, which the image does not carry).
"""

from __future__ import annotations

import io
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from reportlab.graphics.shapes import Drawing, Group, Line, PolyLine, Rect, String
from reportlab.lib import colors

SCALE = 3


def _rgb(color: Any) -> tuple[int, int, int] | None:
    if color is None or not isinstance(color, colors.Color):
        return None
    return (round(color.red * 255), round(color.green * 255), round(color.blue * 255))


def _font(size: float) -> Any:
    try:
        return ImageFont.load_default(size=max(6, size * SCALE))
    except (TypeError, OSError):  # an old Pillow without FreeType: its fixed bitmap font
        return ImageFont.load_default()


def png(drawing: Drawing) -> bytes:
    """``drawing`` as a PNG, ``SCALE`` times its size in points, on white."""

    width, height = int(drawing.width * SCALE), int(drawing.height * SCALE)
    image = Image.new("RGB", (max(width, 1), max(height, 1)), "white")
    canvas = ImageDraw.Draw(image)

    def at(x: float, y: float) -> tuple[float, float]:
        return x * SCALE, height - y * SCALE

    def walk(shapes: list[Any]) -> None:
        for shape in shapes:
            if isinstance(shape, Group):
                walk(list(shape.contents))
            elif isinstance(shape, Rect):
                fill, line = _rgb(shape.fillColor), _rgb(shape.strokeColor)
                x0, y1 = at(shape.x, shape.y)
                x1, y0 = at(shape.x + shape.width, shape.y + shape.height)
                box = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
                radius = (shape.rx or 0) * SCALE
                canvas.rounded_rectangle(box, radius=radius, fill=fill, outline=line)
            elif isinstance(shape, PolyLine):
                points = list(shape.points)
                pairs = [at(points[i], points[i + 1]) for i in range(0, len(points) - 1, 2)]
                if len(pairs) > 1:
                    width_px = max(1, round((shape.strokeWidth or 1) * SCALE))
                    canvas.line(pairs, fill=_rgb(shape.strokeColor), width=width_px, joint="curve")
            elif isinstance(shape, Line):
                width_px = max(1, round((shape.strokeWidth or 1) * SCALE))
                start, end = at(shape.x1, shape.y1), at(shape.x2, shape.y2)
                if shape.strokeDashArray:
                    _dashed(canvas, start, end, _rgb(shape.strokeColor), width_px)
                else:
                    canvas.line([start, end], fill=_rgb(shape.strokeColor), width=width_px)
            elif isinstance(shape, String):
                font = _font(shape.fontSize or 7)
                anchor = {"start": "ls", "middle": "ms", "end": "rs"}.get(shape.textAnchor, "ls")
                canvas.text(
                    at(shape.x, shape.y), shape.text, fill=_rgb(shape.fillColor), font=font,
                    anchor=anchor,
                )  # fmt: skip

    walk(list(drawing.contents))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _dashed(
    canvas: Any, start: tuple[float, float], end: tuple[float, float], fill: Any, width: int
):
    (x0, y0), (x1, y1) = start, end
    length = max(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5, 1)
    dash, gap = 3 * SCALE, 2 * SCALE
    done = 0.0
    while done < length:
        a, b = done / length, min(done + dash, length) / length
        canvas.line(
            [(x0 + (x1 - x0) * a, y0 + (y1 - y0) * a), (x0 + (x1 - x0) * b, y0 + (y1 - y0) * b)],
            fill=fill,
            width=width,
        )
        done += dash + gap


__all__ = ["SCALE", "png"]
