"""From a read page to the plant it shows: items (equipment, instruments, valves, connectors) and
how they are joined (feeds, measures, controls, signal, on).

The classical way, no learning and no language model, in six steps:

1. **Tags.** Words that are whole ISA-5.1 or equipment tags; the letters and the number stacked
   in an instrument bubble are read together.
2. **Symbols.** Bubbles are small circles holding a tag; a valve is two triangles meeting at
   their tips; an arrowhead is a small filled triangle; an off-page connector is a closed shape
   holding text (a sheet number and a tag, or a destination); the rest of the closed shapes and
   big circles are equipment bodies, each given the nearest equipment tag.
3. **Lines.** The strokes that are not inside a symbol are joined end to end and at T-junctions
   into nets, solid (process and taps) apart from dashed (signals). Crossings never join.
4. **Touches.** Each end of a net that lands on a symbol joins the net to it.
5. **Flow.** An arrowhead at a net's end says which way it flows; without one, left to right
   (the drawing convention), with a lower confidence.
6. **Relations.** Valves are collapsed into the lines they sit on (``feeds`` between equipment,
   ``on`` for the valve), a transmitter tapped on a line ``measures`` the equipment upstream, a
   dashed net joins a transmitter to its controller (``signal``) and a controller to its valve
   (``controls``).

Every item and relation says how sure the reader is (high, medium, low) and why, so the review
page can show the doubtful ones first.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from doccraft.plantmap.reader import tags as isa
from doccraft.plantmap.reader.primitives import (
    Box,
    Circle,
    Page,
    Seg,
    Shape,
    Text,
    box_distance,
    grow,
    inside,
)

TOL = 2.5


@dataclass
class Item:
    id: str
    family: str  # equipment, instrument, connector, terminal
    cls: str  # pump, vessel..., controller, valve, transmitter..., sheet, destination
    box: Box
    tag: str = ""
    label: str = ""
    confidence: str = "high"
    why: str = ""
    region: Any = None  # ("circle", cx, cy, r) or ("box", x0, y0, x1, y1)
    ref_sheet: str = ""
    ref_tag: str = ""

    def touches(self, x: float, y: float, tol: float = TOL) -> bool:
        if self.region[0] == "circle":
            _, cx, cy, r = self.region
            return math.hypot(x - cx, y - cy) <= r + tol
        return inside(x, y, grow(self.region[1:], tol))

    def holds(self, seg: Seg) -> bool:
        """Both ends inside: a detail of the symbol (a bubble's line, a column's trays)."""
        return self.touches(seg.x1, seg.y1, 0.5) and self.touches(seg.x2, seg.y2, 0.5)


@dataclass
class Arrow:
    tip: tuple[float, float]
    direction: tuple[float, float]
    box: Box


@dataclass
class Result:
    items: list[Item] = field(default_factory=list)
    relations: list[dict[str, Any]] = field(default_factory=list)
    sheet: str = ""
    unit: str = ""
    title: str = ""
    notes: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "sheet": self.sheet,
            "unit": self.unit,
            "title": self.title,
            "items": [
                {
                    "id": i.id,
                    "tag": i.tag,
                    "family": i.family,
                    "cls": i.cls,
                    "label": i.label,
                    "box": [round(v, 1) for v in i.box],
                    "confidence": i.confidence,
                    "why": i.why,
                    **(
                        {"ref_sheet": i.ref_sheet, "ref_tag": i.ref_tag}
                        if i.ref_sheet or i.ref_tag
                        else {}
                    ),
                }
                for i in self.items
            ],
            "relations": self.relations,
            "notes": self.notes,
            "stats": self.stats,
        }


def recognise(page: Page) -> Result:
    result = Result(notes=list(page.notes))
    used_text: set[int] = set()
    items: list[Item] = []

    stacked_bubbles(page)
    bubbles = _bubbles(page, used_text, items)
    valves, valve_shapes = _valves(page)
    arrows, arrow_shapes = _arrows(page, valve_shapes)
    connectors = _connectors(page, used_text, valve_shapes | arrow_shapes, items)
    _loose_connectors(page, used_text, items)
    words = _words(page, used_text)
    _label_valves(valves, words, bubbles, items)
    _equipment(page, words, valve_shapes | arrow_shapes, connectors, bubbles, items)
    _sheet_info(page, result)

    nets = _nets(page, items)
    # An actuator's open arrowhead is part of its valve, not a flow arrow.
    arrows += [
        a
        for a in _chevrons(page)
        if not any(i.cls == "valve" and i.region and inside(*a.tip, i.region[1:]) for i in items)
    ]
    _relations(items, nets, arrows, result)
    result.items = items
    result.stats = {
        "texts": len(page.texts),
        "strokes": len(page.segs),
        "circles": len(page.circles),
        "shapes": len(page.shapes),
        "nets": len(nets),
        "arrows": len(arrows),
        "items": len(items),
        "relations": len(result.relations),
    }
    return result


# ---------------------------------------------------------------- 1-2: tags and symbols


def stacked_bubbles(page: Page) -> None:
    """ISA letters over a number make an instrument bubble, whatever its outline (a circle, a
    rounded box drawn as two arcs and two lines, or a ring the scan lost): one circle with both
    words inside is added, unless a circle already holds them."""

    letters = [
        t
        for t in page.texts
        if isa.LETTERS.match(t.text) and 2 <= len(t.text) <= 5 and isa.instrument_class(t.text)
    ]
    numbers = [t for t in page.texts if isa.NUMBER.match(t.text)]
    for top in letters:
        best = None
        for low in numbers:
            dy = low.cy - top.cy
            if 0.6 * top.height < dy < 2.6 * top.height and abs(low.cx - top.cx) < top.height:
                if best is None or dy < best[0]:
                    best = (dy, low)
        if best is None:
            continue
        low = best[1]
        if any(
            math.hypot(t.cx - c.cx, t.cy - c.cy) < c.r for c in page.circles for t in (top, low)
        ):
            continue
        cx = (top.cx + low.cx) / 2
        cy = (top.cy + low.cy) / 2
        r = max(top.box[2] - top.box[0], low.box[2] - low.box[0], low.cy - top.cy) * 0.75
        page.circles.append(Circle(cx, cy, r))


def _bubbles(page: Page, used: set[int], items: list[Item]) -> list[Item]:
    heights = sorted(t.height for t in page.texts) or [8.0]
    text_h = heights[len(heights) // 2]
    found = []
    for circle in page.circles:
        if circle.filled or circle.r < 1.2 * text_h or circle.r > 8 * text_h:
            continue
        inner = [
            k
            for k, t in enumerate(page.texts)
            if k not in used and math.hypot(t.cx - circle.cx, t.cy - circle.cy) < circle.r * 0.9
        ]
        if not inner:
            continue
        inner.sort(key=lambda k: (round(page.texts[k].cy / (text_h * 0.6)), page.texts[k].cx))
        words = [page.texts[k].text for k in inner]
        tag = isa.parse("".join(words), in_bubble=True) or isa.parse(
            "-".join(words), in_bubble=True
        )
        if not tag or tag.family != "instrument":
            continue
        used.update(inner)
        item = Item(
            id=tag.tag,
            family="instrument",
            cls=tag.cls,
            box=circle.box,
            tag=tag.tag,
            label=" ".join(words),
            why="ISA-5.1 tag in an instrument bubble",
            region=("circle", circle.cx, circle.cy, circle.r),
        )
        items.append(item)
        found.append(item)
    return found


def _valves(page: Page) -> tuple[list[Item], set[int]]:
    """Bow ties: two triangles whose tips meet."""

    triangles = [
        (k, s)
        for k, s in enumerate(page.shapes)
        if len(s.points) == 3 and not s.filled and s.size < 40
    ]
    out: list[Item] = []
    used: set[int] = set()
    for a in range(len(triangles)):
        ka, sa = triangles[a]
        if ka in used:
            continue
        for b in range(a + 1, len(triangles)):
            kb, sb = triangles[b]
            if kb in used:
                continue
            ta = next(
                (
                    p
                    for p in sa.points
                    for q in sb.points
                    if math.hypot(p[0] - q[0], p[1] - q[1]) <= 2.0
                ),
                None,
            )
            if ta is None or box_distance(sa.box, sb.box) > 2.0:
                continue
            x0 = min(sa.box[0], sb.box[0])
            y0 = min(sa.box[1], sb.box[1])
            x1 = max(sa.box[2], sb.box[2])
            y1 = max(sa.box[3], sb.box[3])
            horizontal = (x1 - x0) >= (y1 - y0)
            cx, cy = ta
            # The actuator sits on the stem, above (or beside) the body.
            reach = 2.4 * max(x1 - x0, y1 - y0) / 2
            region = (x0, cy - reach, x1, y1) if horizontal else (cx - reach, y0, x1, y1)
            out.append(
                Item(
                    id=f"valve@{cx:.0f},{cy:.0f}",
                    family="instrument",
                    cls="valve",
                    box=(x0, y0, x1, y1),
                    why="valve symbol (two triangles)",
                    region=("box", *region),
                )
            )
            used.update({ka, kb})
            break
    out += _stroked_valves(page, out)
    # The actuator's dome and any small outline on the stem belong to the valve.
    for k, s in enumerate(page.shapes):
        if k in used or s.size > 20:
            continue
        for v in out:
            if inside((s.box[0] + s.box[2]) / 2, (s.box[1] + s.box[3]) / 2, v.region[1:]):
                used.add(k)
                break
    return out, used


def _stroked_valves(page: Page, found: list[Item]) -> list[Item]:
    """Bow ties drawn as four loose strokes (CAD exports): two diagonals crossing at their
    middles, closed by two caps."""

    near = 1.0
    diagonals = [
        s
        for s in page.segs
        if 4 < s.length < 40
        and min(abs(s.x2 - s.x1), abs(s.y2 - s.y1)) > 0.3 * s.length
        and not s.dashed
    ]
    by_middle: dict[tuple[int, int], list[Seg]] = defaultdict(list)
    for s in diagonals:
        by_middle[(round((s.x1 + s.x2) / 2), round((s.y1 + s.y2) / 2))].append(s)
    ends: dict[tuple[int, int], list[Seg]] = defaultdict(list)
    for s in page.segs:
        if s.length < 40:
            for x, y in ((s.x1, s.y1), (s.x2, s.y2)):
                ends[(round(x), round(y))].append(s)

    def joined(p, q) -> bool:
        return any(
            math.hypot(o.x1 - q[0], o.y1 - q[1]) <= near
            or math.hypot(o.x2 - q[0], o.y2 - q[1]) <= near
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for o in ends.get((round(p[0]) + dx, round(p[1]) + dy), [])
            if math.hypot(o.x1 - p[0], o.y1 - p[1]) <= near
            or math.hypot(o.x2 - p[0], o.y2 - p[1]) <= near
        )

    out: list[Item] = []
    seen: set[tuple[int, int]] = set()
    for (mx, my), group in by_middle.items():
        pool = [
            o
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for o in by_middle.get((mx + dx, my + dy), [])
        ]
        for a in group:
            for b in pool:
                if b is a or abs(a.length - b.length) > 0.1 * a.length:
                    continue
                cx, cy = (a.x1 + a.x2) / 2, (a.y1 + a.y2) / 2
                if math.hypot((b.x1 + b.x2) / 2 - cx, (b.y1 + b.y2) / 2 - cy) > near:
                    continue
                # Crossing, not the same stroke twice: the slopes differ in sign.
                if (a.x2 - a.x1) * (a.y2 - a.y1) * (b.x2 - b.x1) * (b.y2 - b.y1) >= 0:
                    continue
                pa, qa, pb, qb = (a.x1, a.y1), (a.x2, a.y2), (b.x1, b.y1), (b.x2, b.y2)
                caps = (joined(pa, pb) and joined(qa, qb)) or (joined(pa, qb) and joined(qa, pb))
                key = (round(cx), round(cy))
                if not caps or key in seen:
                    continue
                if any(inside(cx, cy, v.box) for v in found):
                    continue
                seen.add(key)
                x0, x1 = min(a.box[0], b.box[0]), max(a.box[2], b.box[2])
                y0, y1 = min(a.box[1], b.box[1]), max(a.box[3], b.box[3])
                # The pipe runs along the valve; its actuator may sit on either side.
                horizontal = abs(a.x2 - a.x1) >= abs(a.y2 - a.y1)
                reach = 2.4 * max(x1 - x0, y1 - y0) / 2
                region = (
                    (x0, cy - reach, x1, cy + reach)
                    if horizontal
                    else (cx - reach, y0, cx + reach, y1)
                )
                out.append(
                    Item(
                        id=f"valve@{cx:.0f},{cy:.0f}",
                        family="instrument",
                        cls="valve",
                        box=(x0, y0, x1, y1),
                        why="valve symbol (two crossed strokes)",
                        region=("box", *region),
                    )
                )
    return out


def _arrows(page: Page, skip: set[int]) -> tuple[list[Arrow], set[int]]:
    out, used = [], set()
    for k, s in enumerate(page.shapes):
        if k in skip or not s.filled or len(s.points) != 3 or s.size > 25:
            continue
        tip = _tip(s)
        others = [p for p in s.points if p != tip]
        bx = sum(p[0] for p in others) / len(others)
        by = sum(p[1] for p in others) / len(others)
        out.append(Arrow(tip, (tip[0] - bx, tip[1] - by), s.box))
        used.add(k)
    return out, used


def _chevrons(page: Page) -> list[Arrow]:
    """Open arrowheads: two short strokes meeting where a longer line ends."""

    short = [x for x in page.segs if 2 < x.length < 14 and not x.dashed]
    by_end: dict[tuple[int, int], list[tuple[Seg, tuple[float, float]]]] = defaultdict(list)
    for x in short:
        for here, there in (((x.x1, x.y1), (x.x2, x.y2)), ((x.x2, x.y2), (x.x1, x.y1))):
            by_end[(round(here[0]), round(here[1]))].append((x, there))
    out = []
    for (px, py), pair in by_end.items():
        if len(pair) == 3:
            # A CAD export may add a short piece of the line itself at the tip: it runs
            # between the two wings.
            pair = next(
                (
                    [w for w in pair if w is not shaft]
                    for shaft in pair
                    if _between(shaft, [w for w in pair if w is not shaft], (px, py))
                ),
                pair,
            )
        if len(pair) != 2:
            continue
        (a, ea), (b, eb) = pair
        mx, my = (ea[0] + eb[0]) / 2, (ea[1] + eb[1]) / 2
        spread = math.hypot(ea[0] - eb[0], ea[1] - eb[1])
        depth = math.hypot(px - mx, py - my)
        if not (0.4 * depth < spread < 3 * depth):
            continue
        if not any(x.length >= 14 and (_point_on(x, px, py, TOL)) for x in page.segs):
            continue
        out.append(
            Arrow(
                (px, py),
                (px - mx, py - my),
                (
                    min(ea[0], eb[0], px),
                    min(ea[1], eb[1], py),
                    max(ea[0], eb[0], px),
                    max(ea[1], eb[1], py),
                ),
            )
        )
    return out


def _between(shaft, wings, tip) -> bool:
    """Whether a stroke from the tip runs along the middle of two others from it."""

    def unit(end):
        x, y = end[0] - tip[0], end[1] - tip[1]
        n = math.hypot(x, y) or 1.0
        return x / n, y / n

    (ax, ay), (bx, by), (sx, sy) = unit(wings[0][1]), unit(wings[1][1]), unit(shaft[1])
    mx, my = ax + bx, ay + by
    n = math.hypot(mx, my)
    return n > 1e-6 and abs(sx * my / n - sy * mx / n) < 0.1 and sx * mx + sy * my > 0


def _tip(s: Shape) -> tuple[float, float]:
    """An arrowhead's point: the vertex facing its shortest side."""
    pts = s.points

    def facing(i):
        a, b = pts[(i + 1) % 3], pts[(i + 2) % 3]
        return math.hypot(a[0] - b[0], a[1] - b[1])

    return pts[min(range(3), key=facing)]


def _connectors(page: Page, used: set[int], skip: set[int], items: list[Item]) -> list[Item]:
    out = []
    for k, s in enumerate(page.shapes):
        if k in skip or s.filled:
            continue
        x0, y0, x1, y1 = s.box
        if x1 - x0 > 160 or y1 - y0 > 60 or x1 - x0 < 30:
            continue
        inner = [j for j, t in enumerate(page.texts) if j not in used and inside(t.cx, t.cy, s.box)]
        if not inner:
            continue
        words = [
            page.texts[j].text
            for j in sorted(inner, key=lambda j: (page.texts[j].cy, page.texts[j].cx))
        ]
        sheet = next((w for w in words if isa.SHEET.match(w.upper())), "")
        ref = next((t for t in (isa.parse(w) for w in words) if t), None)
        if not sheet and ref is None and len(" ".join(words)) > 40:
            continue
        used.update(inner)
        label = " ".join(words)
        if sheet:
            item = Item(
                id=f"to:{sheet}:{ref.tag if ref else ''}",
                family="connector",
                cls="sheet",
                box=s.box,
                label=label,
                ref_sheet=sheet,
                ref_tag=ref.tag if ref else "",
                why="off-page connector naming another sheet",
                region=("box", *s.box),
            )
        else:
            item = Item(
                id=f"end:{label}@{x0:.0f},{y0:.0f}",
                family="terminal",
                cls="destination",
                box=s.box,
                label=label,
                why="line end naming where it goes",
                region=("box", *s.box),
            )
        items.append(item)
        out.append(item)
    return out


def _loose_connectors(page: Page, used: set[int], items: list[Item]) -> None:
    """A sheet number with a tag just under it, outside any outline (a scan): a reference to
    that tag on the other sheet, not the tag's own place."""

    for k, t in enumerate(page.texts):
        if k in used or not isa.SHEET.match(t.text.upper()):
            continue
        for j, u in enumerate(page.texts):
            if j in used or j == k:
                continue
            if 0 < u.cy - t.cy < 4 * t.height and abs(u.cx - t.cx) < (t.box[2] - t.box[0]):
                ref = isa.parse(u.text)
                if ref:
                    box = (min(t.box[0], u.box[0]), t.box[1], max(t.box[2], u.box[2]), u.box[3])
                    items.append(
                        Item(
                            id=f"to:{t.text.upper()}:{ref.tag}",
                            family="connector",
                            cls="sheet",
                            box=box,
                            label=f"{t.text} {u.text}",
                            ref_sheet=t.text.upper(),
                            ref_tag=ref.tag,
                            confidence="medium",
                            why="sheet number with a tag under it",
                            region=("box", *grow(box, 6)),
                        )
                    )
                    used.update({k, j})
                    break


def _words(page: Page, used: set[int]) -> list[tuple[Text, isa.Tag]]:
    """Tags among the free words, also when written as two words (``FIC 1003``)."""

    free = [(k, t) for k, t in enumerate(page.texts) if k not in used]
    out = []
    taken: set[int] = set()
    for k, t in free:
        tag = isa.parse(t.text)
        if tag:
            out.append((t, tag))
            taken.add(k)
    by_line = sorted((t.cy, t.box[0], k, t) for k, t in free if k not in taken)
    for (cy, x0, k, t), (cy2, x2, k2, t2) in zip(by_line, by_line[1:], strict=False):
        if abs(cy - cy2) < 0.4 * t.height and 0 <= t2.box[0] - t.box[2] < 1.2 * t.height:
            if isa.LETTERS.match(t.text) and isa.NUMBER.match(t2.text):
                tag = isa.parse(f"{t.text}-{t2.text}")
                if tag:
                    box = (t.box[0], min(t.box[1], t2.box[1]), t2.box[2], max(t.box[3], t2.box[3]))
                    out.append((Text(f"{t.text} {t2.text}", box), tag))
    # Turned labels along a vertical line read bottom to top: the letters below the number.
    numbers = [
        (k, t)
        for k, t in free
        if k not in taken and t.height > 1.5 * t.width and isa.NUMBER.match(t.text)
    ]
    for k, t in free:
        if k in taken or not isa.LETTERS.match(t.text):
            continue
        for _, t2 in numbers:
            gap = t.box[1] - t2.box[3]
            if abs(t.cx - t2.cx) < 0.5 * t2.width and -0.5 < gap < 1.2 * t2.width:
                tag = isa.parse(f"{t.text}-{t2.text}")
                if tag:
                    box = (min(t.box[0], t2.box[0]), t2.box[1], max(t.box[2], t2.box[2]), t.box[3])
                    out.append((Text(f"{t.text} {t2.text}", box), tag))
                break
    return out


def _label_valves(valves: list[Item], words, bubbles, items: list[Item]) -> None:
    labels = [(t, tag) for t, tag in words if tag.family == "instrument" and tag.cls == "valve"]
    pairs = sorted(
        (
            (box_distance(v.box, t.box), vi, li)
            for vi, v in enumerate(valves)
            for li, (t, _) in enumerate(labels)
        ),
        key=lambda p: p[0],
    )
    done_v, done_l = set(), set()
    for dist, vi, li in pairs:
        if vi in done_v or li in done_l or dist > 30:
            continue
        v = valves[vi]
        tag = labels[li][1]
        v.id = v.tag = tag.tag
        v.label = labels[li][0].text
        v.why = "valve symbol with its tag beside it"
        done_v.add(vi)
        done_l.add(li)
    for vi, v in enumerate(valves):
        if vi not in done_v:
            v.confidence = "low"
            v.why = "valve symbol without a tag near it"
        items.append(v)
    # A valve tag with no symbol near it is still an instrument of the plant.
    for li, (t, tag) in enumerate(labels):
        if li not in done_l and not any(i.tag == tag.tag for i in items):
            items.append(
                Item(
                    id=tag.tag,
                    family="instrument",
                    cls="valve",
                    box=t.box,
                    tag=tag.tag,
                    label=t.text,
                    confidence="medium",
                    why="valve tag with no valve symbol near it",
                    region=("box", *t.box),
                )
            )
    # Other instrument tags written outside a bubble.
    for t, tag in words:
        if (
            tag.family == "instrument"
            and tag.cls != "valve"
            and not any(i.tag == tag.tag for i in items)
        ):
            items.append(
                Item(
                    id=tag.tag,
                    family="instrument",
                    cls=tag.cls,
                    box=t.box,
                    tag=tag.tag,
                    label=t.text,
                    confidence="medium",
                    why="instrument tag written outside a bubble",
                    region=("box", *t.box),
                )
            )
    del bubbles


def _equipment(page: Page, words, skip: set[int], connectors, bubbles, items) -> None:
    heights = sorted(t.height for t in page.texts) or [8.0]
    text_h = heights[len(heights) // 2]
    taken_regions = [i.box for i in items]
    bodies: list[tuple[Box, Any]] = []
    for k, s in enumerate(page.shapes):
        if k in skip or s.filled or s.size < 30:
            continue
        if any(
            box_distance(s.box, c.box) == 0 and _area(s.box) <= _area(c.box) * 1.01
            for c in connectors
        ):
            continue
        if _area(s.box) > 0.25 * page.width * page.height:
            continue  # the sheet's frame or title block
        if s.box[2] - s.box[0] > 0.2 * page.width and s.box[3] - s.box[1] < 0.2 * page.height:
            continue  # a title block strip
        bodies.append((s.box, ("box", *s.box)))
    for c in page.circles:
        if c.filled or any(
            abs(c.cx - b.region[1]) < 0.5 and abs(c.cy - b.region[2]) < 0.5
            for b in bubbles
            if b.region[0] == "circle"
        ):
            continue
        if c.r < min(12.0, 2 * text_h):
            continue  # a dot or a small mark, not a pump or a vessel (a drawing to scale)
        bodies.append((c.box, ("circle", c.cx, c.cy, c.r)))
    groups = _group(bodies)
    tags = [
        (t, tag)
        for t, tag in words
        if tag.family == "equipment" and not any(inside(t.cx, t.cy, r) for r in taken_regions)
    ]
    # A tag written more than once (on the drawing and again in a data table under it): the
    # drawing's label is the largest one.
    largest: dict[str, float] = {}
    for t, tag in tags:
        largest[tag.tag] = max(largest.get(tag.tag, 0.0), min(t.height, t.width))
    tags = [(t, tag) for t, tag in tags if min(t.height, t.width) >= 0.9 * largest[tag.tag]]
    pairs = sorted(
        (
            (box_distance(g[0], t.box), gi, ti)
            for gi, g in enumerate(groups)
            for ti, (t, _) in enumerate(tags)
        ),
        key=lambda p: p[0],
    )
    done_g, done_t = set(), set()
    for dist, gi, ti in pairs:
        if gi in done_g or ti in done_t or dist > 90:
            continue
        box, region = groups[gi]
        t, tag = tags[ti]
        if any(i.tag == tag.tag for i in items):
            done_t.add(ti)
            continue
        items.append(
            Item(
                id=tag.tag,
                family="equipment",
                cls=tag.cls,
                box=box,
                tag=tag.tag,
                label=t.text,
                confidence="high" if dist < 40 else "medium",
                why=f"equipment tag {dist:.0f} pt from its symbol",
                region=region,
            )
        )
        done_g.add(gi)
        done_t.add(ti)
    # A tag with no closed symbol near it: an outline drawn as separate strokes (a tank's two
    # walls and two heads) around it, or beside it.
    left = [(ti, t, tag) for ti, (t, tag) in enumerate(tags) if ti not in done_t]
    found = {ti: _enclosure(page, t, text_h) for ti, t, _ in left}
    for ti, t, tag in sorted(left, key=lambda x: found[x[0]] is None):
        box = found[ti]
        if box is None or any(i.tag == tag.tag for i in items):
            continue
        items.append(
            Item(
                id=tag.tag,
                family="equipment",
                cls=tag.cls,
                box=box,
                tag=tag.tag,
                label=t.text,
                confidence="medium",
                why="equipment tag with an outline drawn around or beside it",
                region=("box", *box),
            )
        )
        done_t.add(ti)
    for ti, (t, tag) in enumerate(tags):
        if ti not in done_t and not any(i.tag == tag.tag for i in items):
            items.append(
                Item(
                    id=tag.tag,
                    family="equipment",
                    cls=tag.cls,
                    box=t.box,
                    tag=tag.tag,
                    label=t.text,
                    confidence="low",
                    why="equipment tag with no symbol near it",
                    region=("box", *t.box),
                )
            )


def _group(bodies):
    """Outlines that touch are one symbol (a tank and its roof)."""
    parent = list(range(len(bodies)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(bodies)):
        for j in range(i + 1, len(bodies)):
            if box_distance(bodies[i][0], bodies[j][0]) <= 1.0:
                parent[find(i)] = find(j)
    merged: dict[int, list] = defaultdict(list)
    for i, b in enumerate(bodies):
        merged[find(i)].append(b)
    out = []
    for members in merged.values():
        if len(members) == 1:
            out.append(members[0])
            continue
        x0 = min(m[0][0] for m in members)
        y0 = min(m[0][1] for m in members)
        x1 = max(m[0][2] for m in members)
        y1 = max(m[0][3] for m in members)
        out.append(((x0, y0, x1, y1), ("box", x0, y0, x1, y1)))
    return out


def _sheet_info(page: Page, result: Result) -> None:
    for t in page.texts:
        word = t.text.upper()
        if isa.SHEET.match(word) and not result.sheet:
            # The biggest sheet number on the page is the drawing's own.
            own = max(
                (x for x in page.texts if isa.SHEET.match(x.text.upper())), key=lambda x: x.height
            )
            result.sheet = own.text.upper()
    for t in page.texts:
        m = re.fullmatch(r"U-?(\d{2,5})", t.text.upper())
        if m and not result.unit:
            result.unit = f"U-{m.group(1)}"
    line = " ".join(t.text for t in sorted(page.texts, key=lambda t: (round(t.cy), t.cx)))
    m = re.search(r"\bUNIT:?\s+(U)-?(\d{2,5})\b", line.upper())
    if m:
        result.unit = f"U-{m.group(2)}"
    for t in page.texts:
        upper = t.text.upper()
        if "DIAGRAM" not in upper:
            continue
        rest = upper.split("DIAGRAM", 1)[1].lstrip(":").strip()
        if not rest:
            same = sorted(
                (
                    u
                    for u in page.texts
                    if u is not t and abs(u.cy - t.cy) < 0.5 * t.height and u.box[0] >= t.box[2] - 1
                ),
                key=lambda u: u.box[0],
            )
            rest = " ".join(u.text.upper() for u in same).lstrip(":").strip()
        rest = re.split(r"\s+(?:DWG|UNIT|REV|SHEET|P&?ID|PFD)\b", rest)[0].strip(" :-")
        if rest and re.fullmatch(r"[A-Z][A-Z0-9 /&-]{1,60}", rest):
            result.title = rest.title()
            break


def _area(b: Box) -> float:
    return max(b[2] - b[0], 0) * max(b[3] - b[1], 0)


# ---------------------------------------------------------------- 3-4: nets


@dataclass
class Net:
    dashed: bool
    segs: list[Seg]
    touches: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    ends: list[tuple[float, float]] = field(default_factory=list)


def _hits(page: Page, x: float, y: float, dx: int, dy: int, reach: float) -> list:
    """The strokes a ray from (x, y) along an axis crosses, nearest first, with how far."""

    out = []
    for s in page.segs:
        if dx:
            lo, hi = sorted((s.y1, s.y2))
            if not lo <= y <= hi or hi - lo < 1e-6:
                continue
            at = s.x1 + (s.x2 - s.x1) * (y - s.y1) / (s.y2 - s.y1)
            d = (at - x) * dx
        else:
            lo, hi = sorted((s.x1, s.x2))
            if not lo <= x <= hi or hi - lo < 1e-6:
                continue
            at = s.y1 + (s.y2 - s.y1) * (x - s.x1) / (s.x2 - s.x1)
            d = (at - y) * dy
        if 0 < d <= reach:
            out.append((d, s))
    out.sort(key=lambda h: h[0])
    return out


def _enclosure(page: Page, t: Text, text_h: float) -> Box | None:
    """The outline around a tag, or around a point just beside it: rays left, right, up and
    down all meet a stroke, and the box they make is a symbol's size (not a table cell, not the
    sheet)."""

    reach = 0.2 * max(page.width, page.height)
    probes = [(0.0, 0.0)] + [
        (fx * k * text_h, fy * k * text_h)
        for k in (3, 5, 7)
        for fx, fy in ((0, -1), (0, 1), (1, 0), (-1, 0))
    ]
    sides = ((-1, 0), (1, 0), (0, -1), (0, 1))
    for ox, oy in probes:
        x, y = t.cx + ox, t.cy + oy
        hits = [_hits(page, x, y, dx, dy, reach) for dx, dy in sides]
        if any(not h for h in hits):
            continue
        box = (x - hits[0][0][0], y - hits[2][0][0], x + hits[1][0][0], y + hits[3][0][0])
        # The walls are the symbol's own strokes: grow the box to where they end (a rectangle
        # crossed inside by an X), then judge its size.
        for _, s in (hits[0][0], hits[1][0], hits[2][0], hits[3][0]):
            box = (
                min(box[0], s.box[0]),
                min(box[1], s.box[1]),
                max(box[2], s.box[2]),
                max(box[3], s.box[3]),
            )
        w, h = box[2] - box[0], box[3] - box[1]
        if w < 2.5 * text_h or h < 2.5 * text_h or w > 0.3 * page.width or h > 0.4 * page.height:
            continue
        # A symbol holds its own tag and little else; a gap between pipes holds other labels.
        own = grow(t.box, 1.0)
        if sum(inside(o.cx, o.cy, box) and not inside(o.cx, o.cy, own) for o in page.texts) > 2:
            continue
        if box_distance(box, t.box) > 6 * text_h:
            continue
        return box
    return None


def _nets(page: Page, items: list[Item]) -> list[Net]:
    strokes = [
        s for s in page.segs if s.length > 0.5 and not any(i.holds(s) for i in items if i.region)
    ]
    n = len(strokes)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        parent[find(i)] = find(j)

    # Ends that meet, and ends that land on another stroke (a T), within the same kind.
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    cell = 40.0
    for k, s in enumerate(strokes):
        x0, y0, x1, y1 = grow(s.box, TOL)
        for gx in range(int(x0 // cell), int(x1 // cell) + 1):
            for gy in range(int(y0 // cell), int(y1 // cell) + 1):
                grid[(gx, gy)].append(k)
    for k, s in enumerate(strokes):
        for x, y in ((s.x1, s.y1), (s.x2, s.y2)):
            for j in grid.get((int(x // cell), int(y // cell)), []):
                if j == k or strokes[j].dashed != s.dashed:
                    continue
                if _point_on(strokes[j], x, y, TOL):
                    union(k, j)
    groups: dict[int, list[int]] = defaultdict(list)
    for k in range(n):
        groups[find(k)].append(k)
    nets = []
    for members in groups.values():
        segs = [strokes[k] for k in members]
        net = Net(dashed=segs[0].dashed, segs=segs)
        # Every stroke end counts: a line may end on a symbol where an arrowhead or a nozzle
        # stub is joined to it.
        ends = [p for seg in segs for p in ((seg.x1, seg.y1), (seg.x2, seg.y2))]
        net.ends = _free_ends(segs)
        for item in items:
            hits = [p for p in ends if item.touches(*p)]
            if not hits and item.region[0] == "circle":
                hits = []
            if hits:
                net.touches[item.id] = hits
        if net.touches:
            nets.append(net)
    return nets


def _free_ends(segs: list[Seg]) -> list[tuple[float, float]]:
    """Every stroke end not joined to another stroke of the net (where it meets a symbol)."""
    ends = []
    for k, s in enumerate(segs):
        for x, y in ((s.x1, s.y1), (s.x2, s.y2)):
            if not any(j != k and _point_on(o, x, y, TOL) for j, o in enumerate(segs)):
                ends.append((x, y))
    return ends


def _point_on(s: Seg, x: float, y: float, tol: float) -> bool:
    dx, dy = s.x2 - s.x1, s.y2 - s.y1
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return math.hypot(x - s.x1, y - s.y1) <= tol
    t = max(0.0, min(1.0, ((x - s.x1) * dx + (y - s.y1) * dy) / length2))
    px, py = s.x1 + t * dx, s.y1 + t * dy
    return math.hypot(x - px, y - py) <= tol


# ---------------------------------------------------------------- 5-6: flow and relations


def _split_at(net: Net, arrow: Arrow, flow: list[Item]) -> tuple[set[str], set[str]]:
    """The members behind an arrow on a line and the members ahead of it, cutting the line
    where the arrow sits. Both empty when the arrow is not on this line."""

    tx, ty = arrow.tip
    cut = next((s for s in net.segs if _point_on(s, tx, ty, TOL)), None)
    if cut is None:
        return set(), set()
    dx, dy = arrow.direction
    rest = [s for s in net.segs if s is not cut]
    parent = list(range(len(rest)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(rest):
        for j in range(i + 1, len(rest)):
            b = rest[j]
            if any(_point_on(b, x, y, TOL) for x, y in ((a.x1, a.y1), (a.x2, a.y2))) or any(
                _point_on(a, x, y, TOL) for x, y in ((b.x1, b.y1), (b.x2, b.y2))
            ):
                parent[find(i)] = find(j)

    def side(x: float, y: float) -> int:
        return 1 if (x - tx) * dx + (y - ty) * dy > 0 else -1

    # Each piece of the line joins the cut stroke on one side of the arrow.
    sides: dict[int, set[int]] = defaultdict(set)
    for i, s in enumerate(rest):
        for x, y in ((s.x1, s.y1), (s.x2, s.y2)):
            if _point_on(cut, x, y, TOL):
                sides[find(i)].add(side(x, y))
        for x, y in ((cut.x1, cut.y1), (cut.x2, cut.y2)):
            if _point_on(s, x, y, TOL):
                sides[find(i)].add(side(x, y))
    behind: set[str] = set()
    ahead: set[str] = set()
    for m in flow:
        for x, y in net.touches[m.id]:
            if _point_on(cut, x, y, TOL):
                (ahead if side(x, y) > 0 else behind).add(m.id)
                continue
            for i, s in enumerate(rest):
                if (x, y) in ((s.x1, s.y1), (s.x2, s.y2)):
                    for v in sides.get(find(i), ()):
                        (ahead if v > 0 else behind).add(m.id)
    both = ahead & behind
    return behind - both, ahead - both


def _relations(items: list[Item], nets: list[Net], arrows: list[Arrow], result: Result) -> None:
    by_id = {i.id: i for i in items}
    process = {"equipment", "connector", "terminal"}

    def is_process(i: Item) -> bool:
        return i.family in process or i.cls == "valve"

    edges: list[tuple[str, str, str]] = []  # (from, to, confidence)
    taps: list[tuple[str, Net]] = []
    rels: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add(frm, kind, to, confidence, why):
        key = (frm, kind, to)
        if frm == to or key in rels:
            return
        rels[key] = {"from": frm, "type": kind, "to": to, "confidence": confidence, "why": why}

    unsure: list[tuple[Net, list[Item]]] = []
    for net in nets:
        members = [by_id[k] for k in net.touches]
        if net.dashed:
            controllers = [m for m in members if m.cls == "controller"]
            sensors = [
                m
                for m in members
                if m.family == "instrument" and m.cls not in {"controller", "valve"}
            ]
            valves = [m for m in members if m.cls == "valve"]
            for c in controllers:
                for v in valves:
                    conf = "high" if len(controllers) == 1 else "medium"
                    add(
                        c.id, "controls", v.id, conf, "signal line from the controller to the valve"
                    )
                for s in sensors:
                    conf = "high" if len(controllers) == 1 else "medium"
                    add(s.id, "signal", c.id, conf, "signal line from the transmitter")
            continue
        flow = [m for m in members if is_process(m)]
        for m in members:
            if m.family == "instrument" and m.cls != "valve":
                taps.append((m.id, net))
        if len(flow) < 2:
            continue
        downstream = set()
        for arrow in arrows:
            for m in flow:
                if m.touches(*arrow.tip, TOL + 1) and any(
                    math.hypot(p[0] - arrow.tip[0], p[1] - arrow.tip[1]) < 14
                    for p in net.touches[m.id]
                ):
                    downstream.add(m.id)
        if downstream and len(downstream) < len(flow):
            for a in flow:
                for b in flow:
                    if a.id not in downstream and b.id in downstream:
                        edges.append((a.id, b.id, "high"))
            continue
        # Arrows drawn along the line, away from any symbol: what lies ahead of them is
        # downstream.
        pairs: set[tuple[str, str]] = set()
        for arrow in arrows:
            behind, ahead = _split_at(net, arrow, flow)
            pairs |= {(a, b) for a in behind for b in ahead}
        pairs = {(a, b) for a, b in pairs if (b, a) not in pairs}
        if pairs:
            edges += [(a, b, "high") for a, b in sorted(pairs)]
        else:
            unsure.append((net, flow))

    # A line with no arrow that runs through a valve flows the way the valve's other line does.
    for _ in range(3):
        left = []
        for net, flow in unsure:
            ids = {m.id for m in flow}
            sure_out = {a for a, _, c in edges if c == "high" and a in ids}
            sure_in = {b for _, b, c in edges if c == "high" and b in ids}
            valves = [m for m in flow if m.cls == "valve"]
            into = [v for v in valves if v.id in sure_out and v.id not in sure_in]
            out_of = [v for v in valves if v.id in sure_in and v.id not in sure_out]
            if len(flow) == 2 and (into or out_of):
                v = (into or out_of)[0]
                other = next(m for m in flow if m.id != v.id)
                edges.append((other.id, v.id, "high") if into else (v.id, other.id, "high"))
            else:
                left.append((net, flow))
        unsure = left
    for net, flow in unsure:
        # No arrow: the drawing's convention, left to right, then top to bottom.
        def where(m, net=net):
            p = net.touches[m.id][0]
            return (p[0], p[1])

        ordered = sorted(flow, key=where)
        for a, b in zip(ordered, ordered[1:], strict=False):
            edges.append((a.id, b.id, "low"))

    succ: dict[str, list[tuple[str, str]]] = defaultdict(list)
    pred: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for a, b, conf in edges:
        succ[a].append((b, conf))
        pred[b].append((a, conf))

    def node_name(i: Item) -> str | None:
        if i.family == "equipment":
            return i.id
        if i.family == "connector" and i.ref_tag:
            return i.ref_tag
        return None

    def downstream_ends(start: str, seen=None):
        """Equipment reached from ``start`` through valves only."""
        seen = seen or set()
        out = []
        for b, conf in succ.get(start, []):
            if b in seen:
                continue
            seen.add(b)
            item = by_id[b]
            if item.cls == "valve":
                out += [(n, min_conf(conf, c)) for n, c in downstream_ends(b, seen)]
            elif node_name(item):
                out.append((node_name(item), conf))
        return out

    def upstream_end(start: str, seen=None):
        seen = seen or set()
        for a, conf in pred.get(start, []):
            if a in seen:
                continue
            seen.add(a)
            item = by_id[a]
            if node_name(item):
                return node_name(item), conf
            if item.cls == "valve":
                found = upstream_end(a, seen)
                if found:
                    return found[0], min_conf(conf, found[1])
        return None

    for item in items:
        name = node_name(item)
        if not name:
            continue
        for target, conf in downstream_ends(item.id):
            add(
                name,
                "feeds",
                target,
                conf,
                "process line"
                + (" (direction from its arrow)" if conf == "high" else " (direction assumed)"),
            )
    for item in items:
        if item.cls == "valve":
            up = upstream_end(item.id)
            if up:
                add(item.id, "on", up[0], up[1], "the line the valve sits on leaves it")
    for inst, net in taps:
        members = [by_id[k] for k in net.touches]
        equipment = [m for m in members if m.family == "equipment"]
        if len(equipment) == 1:
            add(inst, "measures", equipment[0].id, "high", "tapped on the equipment")
            continue
        flow = [m for m in members if is_process(m)]
        # On a line: the equipment it leaves, through any valve upstream.
        sources = [
            m
            for m in flow
            if not any(
                b == m.id
                for _, b, _ in [(a, b, c) for a, b, c in edges if a in {f.id for f in flow}]
            )
        ]
        for m in sources or flow[:1]:
            name = node_name(m)
            if name:
                add(inst, "measures", name, "medium", "on the line leaving the equipment")
                break
            if m.cls == "valve":
                up = upstream_end(m.id)
                if up:
                    add(inst, "measures", up[0], "medium", "on the line leaving the equipment")
                    break
    result.relations = list(rels.values())
    _name_untagged_valves(items, result)


def _name_untagged_valves(items: list[Item], result: Result) -> None:
    """A valve drawn without its tag takes its controller's: FIC-1003 moves FV-1003 (ISA-5.1
    gives the loop's instruments one number)."""

    taken = {i.id for i in items}
    renames = {}
    for rel in result.relations:
        if rel["type"] != "controls" or not rel["to"].startswith("valve@"):
            continue
        tag = isa.parse(rel["from"], in_bubble=True)
        if tag is None:
            continue
        name = f"{tag.letters[0]}V-{tag.number}"
        if name in taken or rel["to"] in renames:
            continue
        renames[rel["to"]] = name
        taken.add(name)
    for item in items:
        if item.id in renames:
            item.id = item.tag = renames[item.id]
            item.confidence = "medium"
            item.why = "valve with no tag beside it, named after the controller that moves it"
    for rel in result.relations:
        rel["from"] = renames.get(rel["from"], rel["from"])
        rel["to"] = renames.get(rel["to"], rel["to"])


def min_conf(a: str, b: str) -> str:
    order = {"low": 0, "medium": 1, "high": 2}
    return a if order[a] <= order[b] else b
