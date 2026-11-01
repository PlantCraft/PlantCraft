"""SVG drawings into a :class:`Page`: the format CAD tools and our own sample sheets export.

Read with the standard library's XML parser after refusing any DOCTYPE or ENTITY (no external
entities, no entity expansion). Transforms (``matrix``, ``translate``, ``scale``, ``rotate``) are
applied; curves keep their end and middle points, enough to place them.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET

from pidcraft.plantmap.reader.primitives import Page, Text, add_path

Matrix = tuple[float, float, float, float, float, float]  # a b c d e f
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
MAX_ELEMENTS = 400_000


class DrawingError(ValueError):
    """The file cannot be read as a drawing; the message says why, for a person."""


def read_svg(data: bytes) -> Page:
    head = data[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in data.lower():
        raise DrawingError("This SVG declares a DOCTYPE or entities, which are not read.")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise DrawingError(f"This is not a readable SVG file ({exc}).") from exc
    if _local(root.tag) != "svg":
        raise DrawingError("This XML file is not an SVG drawing.")
    width, height, base = _viewport(root)
    page = Page(width=width, height=height)
    count = 0
    stack: list[tuple[ET.Element, Matrix, dict[str, str]]] = [(root, base, {})]
    while stack:
        el, matrix, inherited = stack.pop()
        count += 1
        if count > MAX_ELEMENTS:
            raise DrawingError("This SVG has too many elements to read.")
        tag = _local(el.tag)
        if tag in {"defs", "clipPath", "mask", "symbol", "style", "script", "metadata", "title"}:
            continue
        style = {**inherited, **_style(el)}
        m = _mul(matrix, _transform(el.get("transform", "")))
        if tag in {"svg", "g", "a"}:
            for child in reversed(list(el)):
                stack.append((child, m, style))
            continue
        if tag == "text":
            _text(page, el, m, style)
            continue
        _shape(page, tag, el, m, style)
    return page


def _shape(page: Page, tag: str, el: ET.Element, m: Matrix, style: dict[str, str]) -> None:
    dashed = style.get("stroke-dasharray", "none") not in {"none", "", "0"}
    fill = style.get("fill", "black").strip().lower()
    filled = fill not in {"none", "transparent"} and style.get("fill-opacity", "1") != "0"

    def emit(points, closed, curved=False, is_filled=filled):
        pts = [_apply(m, x, y) for x, y in points]
        add_path(
            page, pts, closed=closed, filled=is_filled and closed, dashed=dashed, curved=curved
        )

    num = _num
    if tag == "line":
        emit([(num(el, "x1"), num(el, "y1")), (num(el, "x2"), num(el, "y2"))], False)
    elif tag in {"polyline", "polygon"}:
        values = [float(v) for v in re.findall(r"-?[\d.]+(?:e-?\d+)?", el.get("points", ""))]
        pts = list(zip(values[0::2], values[1::2], strict=False))
        emit(pts, tag == "polygon")
    elif tag == "rect":
        x, y, w, h = num(el, "x"), num(el, "y"), num(el, "width"), num(el, "height")
        if w > 0 and h > 0:
            emit([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], True)
    elif tag in {"circle", "ellipse"}:
        cx, cy = num(el, "cx"), num(el, "cy")
        rx = num(el, "r") if tag == "circle" else num(el, "rx")
        ry = num(el, "r") if tag == "circle" else num(el, "ry")
        if rx > 0 and ry > 0:
            pts = [
                (cx + rx * math.cos(a), cy + ry * math.sin(a))
                for a in (i * math.pi / 8 for i in range(16))
            ]
            emit(pts, True, curved=True)
    elif tag == "path":
        for pts, closed, curved in _path(el.get("d", "")):
            emit(pts, closed, curved)


def _text(page: Page, el: ET.Element, m: Matrix, style: dict[str, str]) -> None:
    size = _size(style.get("font-size", "10"))
    anchor = style.get("text-anchor", "start")
    x, y = _num(el, "x"), _num(el, "y")
    parts = [(el.text or "", x, y)]
    for span in el:
        if _local(span.tag) == "tspan":
            sx = float(span.get("x", x) or x)
            sy = float(span.get("y", y) or y)
            if span.get("dy"):
                sy = y + _size(span.get("dy", "0"))
            parts.append((span.text or "", sx, sy))
            x, y = sx, sy
    for text, tx, ty in parts:
        text = " ".join(text.split())
        if not text:
            continue
        width = 0.58 * size * len(text)
        x0 = tx - width / 2 if anchor == "middle" else tx - width if anchor == "end" else tx
        corners = [_apply(m, x0, ty - 0.8 * size), _apply(m, x0 + width, ty + 0.2 * size)]
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        page.texts.append(Text(text, (min(xs), min(ys), max(xs), max(ys))))


def _path(d: str):
    """Subpaths of an SVG path: (points, closed, curved)."""

    tokens = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", d)
    out = []
    pts: list[tuple[float, float]] = []
    curved = False
    x = y = sx = sy = 0.0
    cmd = ""
    i = 0

    def take(n):
        nonlocal i
        values = [float(v) for v in tokens[i : i + n]]
        i += n
        return values

    def flush(closed):
        nonlocal pts, curved
        if len(pts) >= 2:
            out.append((pts, closed, curved))
        pts, curved = [], False

    while i < len(tokens):
        if re.fullmatch(r"[A-Za-z]", tokens[i]):
            cmd = tokens[i]
            i += 1
            if cmd in "Zz":
                flush(True)
                x, y = sx, sy
                continue
        elif not cmd:
            break
        rel = cmd.islower()
        c = cmd.upper()
        try:
            if c == "M":
                flush(False)
                dx, dy = take(2)
                x, y = (x + dx, y + dy) if rel else (dx, dy)
                sx, sy = x, y
                pts = [(x, y)]
                cmd = "l" if rel else "L"
            elif c == "L" or c == "T":
                dx, dy = take(2)
                x, y = (x + dx, y + dy) if rel else (dx, dy)
                pts.append((x, y))
            elif c == "H":
                (v,) = take(1)
                x = x + v if rel else v
                pts.append((x, y))
            elif c == "V":
                (v,) = take(1)
                y = y + v if rel else v
                pts.append((x, y))
            elif c in "CSQ":
                n = {"C": 6, "S": 4, "Q": 4}[c]
                v = take(n)
                ex, ey = (x + v[-2], y + v[-1]) if rel else (v[-2], v[-1])
                cx_, cy_ = (x + v[0], y + v[1]) if rel else (v[0], v[1])
                pts.append(((x + 2 * cx_ + ex) / 4 * 1.0, (y + 2 * cy_ + ey) / 4 * 1.0))
                x, y = ex, ey
                pts.append((x, y))
                curved = True
            elif c == "A":
                v = take(7)
                ex, ey = (x + v[5], y + v[6]) if rel else (v[5], v[6])
                pts.extend(_arc(x, y, v[0], v[1], v[3], v[4], ex, ey))
                x, y = ex, ey
                curved = True
            else:
                break
        except ValueError:
            break
        if pts == [] and c != "M":
            pts = [(x, y)]
    flush(False)
    return out


def _arc(x1, y1, rx, ry, large, sweep, x2, y2):
    """Points along an elliptical arc (no x-rotation), so a circle drawn with arcs is a circle."""

    rx, ry = abs(rx), abs(ry)
    if rx == 0 or ry == 0:
        return [(x2, y2)]
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    lam = (dx / rx) ** 2 + (dy / ry) ** 2
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * dy * dy - ry * ry * dx * dx
    den = rx * rx * dy * dy + ry * ry * dx * dx
    coef = math.sqrt(max(num / den, 0)) if den else 0
    if large == sweep:
        coef = -coef
    cxp, cyp = coef * rx * dy / ry, -coef * ry * dx / rx
    cx, cy = cxp + (x1 + x2) / 2, cyp + (y1 + y2) / 2
    a1 = math.atan2((y1 - cy) / ry, (x1 - cx) / rx)
    a2 = math.atan2((y2 - cy) / ry, (x2 - cx) / rx)
    da = a2 - a1
    if sweep and da < 0:
        da += 2 * math.pi
    elif not sweep and da > 0:
        da -= 2 * math.pi
    steps = max(2, int(abs(da) / (math.pi / 8)))
    return [
        (cx + rx * math.cos(a1 + da * k / steps), cy + ry * math.sin(a1 + da * k / steps))
        for k in range(1, steps + 1)
    ]


def _viewport(root: ET.Element) -> tuple[float, float, Matrix]:
    vb = [float(v) for v in re.findall(r"-?[\d.]+", root.get("viewBox", ""))]
    width = _size(root.get("width", "")) if root.get("width") else 0.0
    height = _size(root.get("height", "")) if root.get("height") else 0.0
    if len(vb) == 4 and vb[2] > 0 and vb[3] > 0:
        width = width or vb[2]
        height = height or vb[3]
        sx, sy = width / vb[2], height / vb[3]
        return width, height, (sx, 0.0, 0.0, sy, -vb[0] * sx, -vb[1] * sy)
    return width or 1000.0, height or 1000.0, IDENTITY


def _style(el: ET.Element) -> dict[str, str]:
    out = {}
    for key in ("fill", "stroke", "stroke-dasharray", "font-size", "text-anchor", "fill-opacity"):
        if el.get(key) is not None:
            out[key] = el.get(key, "")
    for item in el.get("style", "").split(";"):
        if ":" in item:
            k, v = item.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _transform(text: str) -> Matrix:
    m = IDENTITY
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", text):
        v = [float(a) for a in re.findall(r"-?[\d.]+(?:e-?\d+)?", args)]
        if name == "matrix" and len(v) == 6:
            t = tuple(v)
        elif name == "translate" and v:
            t = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0)
        elif name == "scale" and v:
            t = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        elif name == "rotate" and v:
            a = math.radians(v[0])
            r = (math.cos(a), math.sin(a), -math.sin(a), math.cos(a), 0, 0)
            if len(v) == 3:
                t = _mul(_mul((1, 0, 0, 1, v[1], v[2]), r), (1, 0, 0, 1, -v[1], -v[2]))
            else:
                t = r
        else:
            continue
        m = _mul(m, t)  # type: ignore[arg-type]
    return m


def _mul(p: Matrix, q: Matrix) -> Matrix:
    a, b, c, d, e, f = p
    A, B, C, D, E, F = q
    return (
        a * A + c * B,
        b * A + d * B,
        a * C + c * D,
        b * C + d * D,
        a * E + c * F + e,
        b * E + d * F + f,
    )


def _apply(m: Matrix, x: float, y: float) -> tuple[float, float]:
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def _num(el: ET.Element, key: str) -> float:
    try:
        return float(re.sub(r"[a-z%]+$", "", el.get(key, "0") or "0"))
    except ValueError:
        return 0.0


def _size(value: str) -> float:
    match = re.match(r"\s*(-?[\d.]+)\s*(px|pt|mm|cm|in)?", value or "")
    if not match:
        return 10.0
    n = float(match.group(1))
    return n * {"mm": 2.8346, "cm": 28.346, "in": 72.0}.get(match.group(2) or "", 1.0)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""
