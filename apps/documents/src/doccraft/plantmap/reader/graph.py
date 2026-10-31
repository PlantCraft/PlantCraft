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
    arrows += _chevrons(page)
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
    # The actuator's dome and any small outline on the stem belong to the valve.
    for k, s in enumerate(page.shapes):
        if k in used or s.size > 20:
            continue
        for v in out:
            if inside((s.box[0] + s.box[2]) / 2, (s.box[1] + s.box[3]) / 2, v.region[1:]):
                used.add(k)
                break
    return out, used


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
        if c.r < 12:
            continue
        bodies.append((c.box, ("circle", c.cx, c.cy, c.r)))
    groups = _group(bodies)
    tags = [
        (t, tag)
        for t, tag in words
        if tag.family == "equipment" and not any(inside(t.cx, t.cy, r) for r in taken_regions)
    ]
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
