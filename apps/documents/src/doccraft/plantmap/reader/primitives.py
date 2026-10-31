"""What a drawing is made of once read: words, strokes, circles and closed shapes on a page.

Every format (SVG, vector PDF, a scanned image) is read into the same :class:`Page`, so the
recognition in ``graph.py`` never knows where a drawing came from. Coordinates are points with
the origin at the top left and ``y`` growing downwards, like SVG and pdfplumber.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

Box = tuple[float, float, float, float]  # x0, y0, x1, y1


@dataclass
class Text:
    text: str
    box: Box

    @property
    def cx(self) -> float:
        return (self.box[0] + self.box[2]) / 2

    @property
    def cy(self) -> float:
        return (self.box[1] + self.box[3]) / 2

    @property
    def height(self) -> float:
        return self.box[3] - self.box[1]


@dataclass
class Seg:
    """One straight stroke. ``dashed`` marks signal lines (ISA-5.1)."""

    x1: float
    y1: float
    x2: float
    y2: float
    dashed: bool = False

    @property
    def length(self) -> float:
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1)

    @property
    def box(self) -> Box:
        return (
            min(self.x1, self.x2),
            min(self.y1, self.y2),
            max(self.x1, self.x2),
            max(self.y1, self.y2),
        )


@dataclass
class Circle:
    cx: float
    cy: float
    r: float
    filled: bool = False

    @property
    def box(self) -> Box:
        return (self.cx - self.r, self.cy - self.r, self.cx + self.r, self.cy + self.r)


@dataclass
class Shape:
    """A closed outline that is not a circle: a vessel, a valve's triangle, an arrowhead."""

    points: list[tuple[float, float]]
    filled: bool = False

    @property
    def box(self) -> Box:
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return (min(xs), min(ys), max(xs), max(ys))

    @property
    def size(self) -> float:
        x0, y0, x1, y1 = self.box
        return max(x1 - x0, y1 - y0)


@dataclass
class Page:
    width: float
    height: float
    texts: list[Text] = field(default_factory=list)
    segs: list[Seg] = field(default_factory=list)
    circles: list[Circle] = field(default_factory=list)
    shapes: list[Shape] = field(default_factory=list)
    # How the page was read: "vector" (SVG, PDF with drawing commands) or "raster" (OCR).
    source: str = "vector"
    notes: list[str] = field(default_factory=list)


def add_path(
    page: Page,
    points: list[tuple[float, float]],
    *,
    closed: bool,
    filled: bool,
    dashed: bool,
    curved: bool = False,
) -> None:
    """Sort one drawn path into the page: a circle, a closed shape, or straight strokes."""

    pts = [p for i, p in enumerate(points) if i == 0 or _far(p, points[i - 1])]
    if len(pts) < 2:
        return
    if closed and len(pts) > 2 and not _far(pts[0], pts[-1]):
        pts = pts[:-1]
    if closed and len(pts) >= 3:
        circle = as_circle(pts) if curved else None
        if circle is not None:
            page.circles.append(Circle(*circle, filled=filled))
            return
        # A closed outline is a symbol's body; its edges are not lines of the process.
        page.shapes.append(Shape(pts, filled=filled))
        return
    for a, b in zip(pts, pts[1:], strict=False):
        page.segs.append(Seg(a[0], a[1], b[0], b[1], dashed=dashed))


def as_circle(pts: list[tuple[float, float]]) -> tuple[float, float, float] | None:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    if w <= 0 or h <= 0 or abs(w - h) > 0.12 * max(w, h):
        return None
    cx, cy, r = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2, (w + h) / 4
    if all(abs(math.hypot(x - cx, y - cy) - r) <= 0.15 * r for x, y in pts):
        return cx, cy, r
    return None


def _far(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return abs(a[0] - b[0]) > 0.01 or abs(a[1] - b[1]) > 0.01


def box_distance(a: Box, b: Box) -> float:
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return math.hypot(dx, dy)


def grow(box: Box, by: float) -> Box:
    return (box[0] - by, box[1] - by, box[2] + by, box[3] + by)


def inside(x: float, y: float, box: Box) -> bool:
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]
