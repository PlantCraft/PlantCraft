"""The demo plant's P&ID sheets, drawn from ``riverbend.json``, with their answer key.

Each sheet is drawn once on a :class:`Canvas` and written as SVG (always) or as a vector PDF
(``reportlab``, a development dependency). The drawing follows ISA-5.1 and ISO 10628 habits
with our own simple symbols: instrument bubbles (letters over the number, a line between them
for a shared display), signal lines dashed, process lines solid with arrowheads, valves as a bow
tie with an actuator, off-page connectors naming the other sheet. Line numbers, notes and the
title block are drawn too, to test that the reader leaves them out.

The answer key (:func:`truth`) is what the sheet was drawn to show: the equipment, the
instruments, which line feeds which equipment, which transmitter measures which equipment,
which controller moves which valve, which transmitter feeds which controller, and the equipment
each valve's line leaves.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

W, H = 1684.0, 1190.0  # A2 landscape, points
Y_EQ = 420.0
BRANCH0 = 590.0
BRANCH_STEP = 70.0
HEADER0 = 900.0
DESTINATIONS = ["STORAGE", "FLARE", "SLOP", "DRAIN", "RETURN", "BLOWDOWN"]


def spec() -> dict[str, Any]:
    text = resources.files("pidcraft.plantmap.sample").joinpath("riverbend.json").read_text("utf-8")
    return json.loads(text)


# ---------------------------------------------------------------- canvas


@dataclass
class Canvas:
    width: float = W
    height: float = H
    ops: list[tuple] = field(default_factory=list)
    font: str = "Helvetica"
    # Untidy drawing, to test the reader: ends off by up to ``jitter`` pt, lines in pieces.
    jitter: float = 0.0
    split: bool = False
    valve_tags: bool = True
    rnd: random.Random = field(default_factory=lambda: random.Random(7))

    def line(self, pts, dashed=False, width=1.0):
        pts = [tuple(p) for p in pts]
        if self.jitter:
            j = self.jitter
            pts = [(x + self.rnd.uniform(-j, j), y + self.rnd.uniform(-j, j)) for x, y in pts]
        if self.split and len(pts) >= 2:
            for a, b in zip(pts, pts[1:]):
                n = self.rnd.randint(1, 3)
                cuts = [
                    (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)
                    for k in range(n + 1)
                ]
                for p, q in zip(cuts, cuts[1:]):
                    self.ops.append(("line", [p, q], dashed, width))
            return
        self.ops.append(("line", pts, dashed, width))

    def poly(self, pts, fill=False, width=1.0):
        self.ops.append(("poly", [tuple(p) for p in pts], fill, width))

    def circle(self, cx, cy, r, width=1.0):
        self.ops.append(("circle", cx, cy, r, width))

    def rrect(self, x, y, w, h, r, width=1.2):
        self.ops.append(("rrect", x, y, w, h, r, width))

    def arc(self, cx, cy, r, width=1.0):
        """The upper half of a circle (a valve's diaphragm actuator)."""
        self.ops.append(("arc", cx, cy, r, width))

    def text(self, x, y, s, size=8.0, anchor="middle", bold=False):
        self.ops.append(("text", x, y, s, size, anchor, bold))

    # -- writers

    def svg(self) -> str:
        out = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width:.0f}" '
            f'height="{self.height:.0f}" viewBox="0 0 {self.width:.0f} {self.height:.0f}">',
            f'<rect x="0" y="0" width="{self.width:.0f}" height="{self.height:.0f}" '
            'fill="white" stroke="none"/>',
            '<g stroke="black" fill="none" font-family="'
            + (
                "Courier New, monospace"
                if self.font == "Courier"
                else "Helvetica, Arial, sans-serif"
            )
            + '">',
        ]
        for op in self.ops:
            kind = op[0]
            if kind == "line":
                _, pts, dashed, width = op
                dash = ' stroke-dasharray="5 3"' if dashed else ""
                out.append(f'<polyline points="{_pts(pts)}" stroke-width="{width}"{dash}/>')
            elif kind == "poly":
                _, pts, fill, width = op
                f = "black" if fill else "none"
                out.append(f'<polygon points="{_pts(pts)}" fill="{f}" stroke-width="{width}"/>')
            elif kind == "circle":
                _, cx, cy, r, width = op
                out.append(
                    f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" stroke-width="{width}"/>'
                )
            elif kind == "rrect":
                _, x, y, w, h, r, width = op
                out.append(
                    f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
                    f'rx="{r:.1f}" stroke-width="{width}"/>'
                )
            elif kind == "arc":
                _, cx, cy, r, width = op
                out.append(
                    f'<path d="M {cx - r:.1f} {cy:.1f} A {r:.1f} {r:.1f} 0 0 1 '
                    f'{cx + r:.1f} {cy:.1f} Z" stroke-width="{width}"/>'
                )
            elif kind == "text":
                _, x, y, s, size, anchor, bold = op
                weight = ' font-weight="bold"' if bold else ""
                out.append(
                    f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" '
                    f'text-anchor="{anchor}" fill="black" stroke="none"{weight}>'
                    f"{_escape(s)}</text>"
                )
        out.append("</g></svg>")
        return "\n".join(out) + "\n"

    def pdf(self, path) -> None:
        from reportlab.pdfgen import canvas as rl

        c = rl.Canvas(str(path), pagesize=(self.width, self.height))
        h = self.height
        for op in self.ops:
            kind = op[0]
            if kind == "line":
                _, pts, dashed, width = op
                c.setLineWidth(width)
                c.setDash(5, 3) if dashed else c.setDash()
                p = c.beginPath()
                p.moveTo(pts[0][0], h - pts[0][1])
                for x, y in pts[1:]:
                    p.lineTo(x, h - y)
                c.drawPath(p, stroke=1, fill=0)
                c.setDash()
            elif kind == "poly":
                _, pts, fill, width = op
                c.setLineWidth(width)
                p = c.beginPath()
                p.moveTo(pts[0][0], h - pts[0][1])
                for x, y in pts[1:]:
                    p.lineTo(x, h - y)
                p.close()
                c.drawPath(p, stroke=1, fill=1 if fill else 0)
            elif kind == "circle":
                _, cx, cy, r, width = op
                c.setLineWidth(width)
                c.circle(cx, h - cy, r, stroke=1, fill=0)
            elif kind == "rrect":
                _, x, y, w, hh, r, width = op
                c.setLineWidth(width)
                c.roundRect(x, h - y - hh, w, hh, r, stroke=1, fill=0)
            elif kind == "arc":
                _, cx, cy, r, width = op
                c.setLineWidth(width)
                p = c.beginPath()
                p.moveTo(cx - r, h - cy)
                p.arcTo(cx - r, h - cy - r, cx + r, h - cy + r, startAng=180, extent=-180)
                p.close()
                c.drawPath(p, stroke=1, fill=0)
            elif kind == "text":
                _, x, y, s, size, anchor, bold = op
                font = self.font + ("-Bold" if bold else "")
                c.setFont(font, size)
                if anchor == "middle":
                    c.drawCentredString(x, h - y, s)
                elif anchor == "end":
                    c.drawRightString(x, h - y, s)
                else:
                    c.drawString(x, h - y, s)
        c.showPage()
        c.save()


def _pts(pts) -> str:
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ---------------------------------------------------------------- symbols


@dataclass
class Sym:
    cx: float
    cy: float
    x0: float
    y0: float
    x1: float
    y1: float
    round_r: float = 0.0  # circles: radius, so top/bottom follow the outline

    def top_at(self, x: float) -> float:
        if self.round_r:
            dx = min(abs(x - self.cx), self.round_r * 0.95)
            return self.cy - math.sqrt(self.round_r**2 - dx**2)
        return self.y0

    def bottom_at(self, x: float) -> float:
        if self.round_r:
            dx = min(abs(x - self.cx), self.round_r * 0.95)
            return self.cy + math.sqrt(self.round_r**2 - dx**2)
        return self.y1


def equipment_symbol(c: Canvas, kind: str, cx: float, cy: float) -> Sym:
    if kind == "pump":
        r = 22
        c.circle(cx, cy, r, 1.4)
        c.poly([(cx - 8, cy - 10), (cx - 8, cy + 10), (cx + 12, cy)])
        return Sym(cx, cy, cx - r, cy - r, cx + r, cy + r, r)
    if kind == "heat_exchanger":
        r = 28
        c.circle(cx, cy, r, 1.4)
        c.line(
            [
                (cx - 20, cy + 8),
                (cx - 10, cy - 10),
                (cx, cy + 10),
                (cx + 10, cy - 10),
                (cx + 20, cy + 8),
            ]
        )
        return Sym(cx, cy, cx - r, cy - r, cx + r, cy + r, r)
    if kind == "column":
        w, h = 56, 170
        c.rrect(cx - w / 2, cy - h / 2, w, h, 20)
        for k in range(1, 6):
            y = cy - h / 2 + k * h / 6
            c.line([(cx - w / 2 + 6, y), (cx + w / 2 - 6, y)], dashed=True, width=0.6)
        return Sym(cx, cy, cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    if kind == "reactor":
        w, h = 64, 130
        c.rrect(cx - w / 2, cy - h / 2, w, h, 24)
        c.line([(cx - w / 2 + 6, cy + 20), (cx + w / 2 - 6, cy - 20)], width=0.6)
        c.line([(cx - w / 2 + 6, cy - 20), (cx + w / 2 - 6, cy + 20)], width=0.6)
        return Sym(cx, cy, cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    if kind == "tank":
        w, h = 110, 80
        c.poly(
            [
                (cx - w / 2, cy - h / 2),
                (cx + w / 2, cy - h / 2),
                (cx + w / 2, cy + h / 2),
                (cx - w / 2, cy + h / 2),
            ],
            width=1.4,
        )
        c.poly([(cx - w / 2, cy - h / 2), (cx, cy - h / 2 - 16), (cx + w / 2, cy - h / 2)])
        return Sym(cx, cy, cx - w / 2, cy - h / 2 - 16, cx + w / 2, cy + h / 2)
    if kind == "furnace":
        w, h = 96, 110
        c.poly(
            [
                (cx - w / 2, cy - h / 2),
                (cx + w / 2, cy - h / 2),
                (cx + w / 2, cy + h / 2),
                (cx - w / 2, cy + h / 2),
            ],
            width=1.4,
        )
        c.poly(
            [
                (cx - w / 2, cy - h / 2),
                (cx - 14, cy - h / 2 - 30),
                (cx + 14, cy - h / 2 - 30),
                (cx + w / 2, cy - h / 2),
            ]
        )
        c.line(
            [
                (cx - 30, cy + 30),
                (cx - 30, cy - 30),
                (cx - 10, cy - 30),
                (cx - 10, cy + 30),
                (cx + 10, cy + 30),
                (cx + 10, cy - 30),
                (cx + 30, cy - 30),
                (cx + 30, cy + 30),
            ],
            width=0.7,
        )
        return Sym(cx, cy, cx - w / 2, cy - h / 2 - 30, cx + w / 2, cy + h / 2)
    if kind == "compressor":
        c.poly(
            [(cx - 34, cy - 32), (cx + 34, cy - 16), (cx + 34, cy + 16), (cx - 34, cy + 32)],
            width=1.4,
        )
        return Sym(cx, cy, cx - 34, cy - 32, cx + 34, cy + 32)
    # vessel or drum: horizontal, rounded ends
    w, h = 130, 54
    c.rrect(cx - w / 2, cy - h / 2, w, h, 26)
    return Sym(cx, cy, cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def valve(c: Canvas, x: float, y: float, tag: str = "") -> tuple[float, float]:
    """A control valve on a horizontal line, its tag below; returns its inlet and outlet x."""
    if tag and c.valve_tags:
        c.text(x, y + 19, tag, 6)
    c.poly([(x - 10, y - 7), (x - 10, y + 7), (x, y)])
    c.poly([(x + 10, y - 7), (x + 10, y + 7), (x, y)])
    c.line([(x, y), (x, y - 13)])
    c.arc(x, y - 13, 7)
    return x - 10, x + 10


@dataclass
class Style:
    bubble: str = "isa"  # "isa": letters over number with a line; "inline": FIC-1003
    font: str = "Helvetica"
    line_numbers: bool = True
    arrows: bool = True
    jitter: float = 0.0
    split: bool = False
    valve_tags: bool = True


def bubble(c: Canvas, st: Style, x: float, y: float, tag: str) -> float:
    letters, number = tag.split("-", 1)
    if st.bubble == "isa":
        r = 13
        c.circle(x, y, r)
        c.line([(x - r, y), (x + r, y)], width=0.8)
        c.text(x, y - 3, letters, 7)
        c.text(x, y + 9, number, 7)
    else:
        r = 18
        c.circle(x, y, r)
        c.text(x, y + 2.5, f"{letters}-{number}", 6)
    return r


def arrow(c: Canvas, st: Style, tip: tuple[float, float], direction: tuple[float, float]):
    if not st.arrows:
        return
    dx, dy = direction
    n = math.hypot(dx, dy) or 1
    ux, uy = dx / n, dy / n
    bx, by = tip[0] - 11 * ux, tip[1] - 11 * uy
    c.poly([tip, (bx - 4.5 * uy, by + 4.5 * ux), (bx + 4.5 * uy, by - 4.5 * ux)], fill=True)


def offpage(c: Canvas, x: float, y: float, top: str, bottom: str) -> tuple[float, float]:
    """An off-page connector pointing right at (x, y): returns its left and right x."""
    c.poly([(x, y - 15), (x + 82, y - 15), (x + 96, y), (x + 82, y + 15), (x, y + 15)])
    c.text(x + 42, y - 3, top, 6.5)
    c.text(x + 42, y + 9, bottom, 6.5)
    return x, x + 96


# ---------------------------------------------------------------- the sheet


def draw_sheet(sheet: dict[str, Any], style: Style | None = None, seed: int = 0):
    """Draw one sheet; returns the canvas and its answer key."""

    st = style or Style()
    rnd = random.Random(seed)
    c = Canvas(
        font=st.font,
        jitter=st.jitter,
        split=st.split,
        valve_tags=st.valve_tags,
        rnd=random.Random(seed + 101),
    )
    key = {
        "sheet": sheet["sheet"],
        "unit": sheet["unit"],
        "area": sheet["area"],
        "equipment": [{"tag": e["tag"], "kind": e["kind"]} for e in sheet["equipment"]],
        "instruments": [],
        "feeds": [],
        "measures": [],
        "controls": [],
        "signals": [],
        "valve_on": [],
        "line_numbers": [],
    }
    _frame(c, sheet)
    equipment = sheet["equipment"]
    n = len(equipment)
    syms: dict[str, Sym] = {}
    col_w = min(1560.0 / max(n, 1), 560.0)
    for i, e in enumerate(equipment):
        left = 60 + i * col_w
        cx = left + max(0.30 * col_w, 210 if i == 0 else 0)
        s = equipment_symbol(c, e["kind"], cx, Y_EQ)
        syms[e["tag"]] = s
        c.text(s.x0 - 8, s.y1 + 4, e["tag"], 9, "end", bold=True)
        c.text(s.x0 - 8, s.y1 + 14, e["name"].upper(), 6, "end")

    loops = sheet["loops"]
    by_eq: dict[str, list[dict]] = {}
    for loop in loops:
        by_eq.setdefault(loop["equipment"] or "", []).append(loop)
        key["instruments"] += [
            {"tag": loop["transmitter"], "cls": "transmitter"},
            {"tag": loop["controller"], "cls": "controller"},
            {"tag": loop["valve"], "cls": "valve"},
        ]
        key["controls"].append([loop["controller"], loop["valve"]])
        key["signals"].append([loop["transmitter"], loop["controller"]])
        if loop["equipment"]:
            key["measures"].append([loop["transmitter"], loop["equipment"]])
            key["valve_on"].append([loop["valve"], loop["equipment"]])

    outgoing = {o["from"]: o for o in sheet["outgoing"]}
    incoming = {o["to"]: o for o in sheet["incoming"]}

    # Incoming off-page connectors: into the left port of their equipment.
    for k, (tag, conn) in enumerate(incoming.items()):
        s = syms[tag]
        y = Y_EQ
        _, right = offpage(c, 40, y + 0 * k, conn["sheet"], conn["from"])
        c.line([(right, y), (s.x0, y)], width=1.4)
        arrow(c, st, (s.x0, y), (1, 0))
        key["feeds"].append([conn["from"], tag])

    for i, e in enumerate(equipment):
        tag = e["tag"]
        s = syms[tag]
        mine = by_eq.get(tag, [])
        nxt = equipment[i + 1]["tag"] if i + 1 < n else None
        out = outgoing.get(tag)
        main_loop = None
        if nxt or out:
            line_loops = [lp for lp in mine if lp["mount"] == "line"]
            main_loop = line_loops[0] if line_loops else None
            x_start = s.x1
            if out and not nxt:
                x_end, _ = (W - 40 - 96, None)
            else:
                x_end = syms[nxt].x0
            pieces_start = x_start
            if main_loop:
                xt = x_start + 70
                xc = xt + 46
                xv = xt + 95
                _instrument_pair(c, st, main_loop, xt, xc, xv, Y_EQ)
                vin, vout = valve(c, xv, Y_EQ, main_loop["valve"])
                c.line([(pieces_start, Y_EQ), (vin, Y_EQ)], width=1.4)
                pieces_start = vout
            c.line([(pieces_start, Y_EQ), (x_end, Y_EQ)], width=1.4)
            arrow(c, st, (x_end, Y_EQ), (1, 0))
            if st.line_numbers:
                size = rnd.choice(["4", "6", "8", "10", "12"])
                number = f'{size}"-P-{tag.split("-")[1]}{i}-A1A'
                mid = (pieces_start + x_end) / 2
                c.text(mid, Y_EQ - 6, number, 6)
                key["line_numbers"].append(number)
            if nxt:
                key["feeds"].append([tag, nxt])
            else:
                offpage(c, x_end, Y_EQ, out["sheet"], out["to"])
                key["feeds"].append([tag, out["to"]])

        vessel_loops = [lp for lp in mine if lp["mount"] == "vessel"]
        branches = [lp for lp in mine if lp is not main_loop]
        # Transmitters on the vessel: above it, a tap line down to its top.
        tx_pos = {}
        mv = len(vessel_loops)
        crowded = mv > 1 and (s.x1 - s.x0) / mv < 2 * 18 + 10
        for j, lp in enumerate(vessel_loops):
            x = s.x0 + (j + 0.5) * (s.x1 - s.x0) / mv
            top = s.top_at(x)
            y = min(top, s.y0) - 48 - (40 if crowded and j % 2 else 0)
            r = bubble(c, st, x, y, lp["transmitter"])
            c.line([(x, y + r), (x, top)])
            tx_pos[lp["controller"]] = (x, y, r, j)
        # Branches below the equipment, the deepest one leaving furthest left.
        m = len(branches)
        x_b = s.x1 + 34 + 7 * mv
        for k, lp in enumerate(branches):
            y_k = BRANCH0 + k * BRANCH_STEP
            dx = (m - 1 - k - (m - 1) / 2) * 9
            x_drop = s.cx + dx
            bottom = s.bottom_at(x_drop)
            xt, xc, xv = x_b + 40, x_b + 86, x_b + 135
            vin, vout = valve(c, xv, y_k, lp["valve"])
            c.line([(x_drop, bottom), (x_drop, y_k), (vin, y_k)], width=1.2)
            dest = rnd.choice(DESTINATIONS)
            left, _ = offpage(c, vout + 70, y_k, "TO", dest)
            c.line([(vout, y_k), (left, y_k)], width=1.2)
            arrow(c, st, (left, y_k), (1, 0))
            if lp["mount"] == "line":
                _instrument_pair(c, st, lp, xt, xc, xv, y_k)
            else:
                rc = bubble(c, st, xc, y_k - 30, lp["controller"])
                x, y, r, j = tx_pos[lp["controller"]]
                route = s.x1 + 14 + 7 * j
                high = min(p[1] - p[2] for p in tx_pos.values()) - 10 - 8 * (mv - 1 - j)
                c.line(
                    [(x, y - r), (x, high), (route, high), (route, y_k - 30), (xc - rc, y_k - 30)],
                    dashed=True,
                    width=0.8,
                )
                c.line(
                    [(xc + rc, y_k - 30), (xv, y_k - 30), (xv, y_k - 20)], dashed=True, width=0.8
                )

    # Header loops: on a line from the battery limit to the users, no equipment.
    for h, lp in enumerate(by_eq.get("", [])):
        y = HEADER0 + h * 66
        _, right = offpage(c, 60, y, "FROM", "BATTERY LIMIT")
        xt, xc, xv = right + 120, right + 166, right + 215
        _instrument_pair(c, st, lp, xt, xc, xv, y)
        vin, vout = valve(c, xv, y, lp["valve"])
        c.line([(right, y), (vin, y)], width=1.2)
        left, _ = offpage(c, vout + 260, y, "TO", "USERS")
        c.line([(vout, y), (left, y)], width=1.2)
        arrow(c, st, (left, y), (1, 0))
    return c, key


def _instrument_pair(c, st, lp, xt, xc, xv, y_line):
    """Transmitter tapped on the line, controller beside it, dashed signals to the valve."""
    yb = y_line - 30
    rt = bubble(c, st, xt, yb, lp["transmitter"])
    c.line([(xt, yb + rt), (xt, y_line)])
    rc = bubble(c, st, xc, yb, lp["controller"])
    c.line([(xt + rt, yb), (xc - rc, yb)], dashed=True, width=0.8)
    c.line([(xc + rc, yb), (xv, yb), (xv, y_line - 20)], dashed=True, width=0.8)


def _frame(c: Canvas, sheet: dict[str, Any]) -> None:
    c.poly([(20, 20), (W - 20, 20), (W - 20, H - 20), (20, H - 20)], width=2)
    x0, y0 = W - 420, H - 150
    c.poly([(x0, y0), (W - 20, y0), (W - 20, H - 20), (x0, H - 20)], width=1.2)
    c.line([(x0, y0 + 40), (W - 20, y0 + 40)])
    c.line([(x0, y0 + 80), (W - 20, y0 + 80)])
    c.text(x0 + 10, y0 + 26, "RIVERBEND DEMO REFINERY", 12, "start", bold=True)
    c.text(x0 + 10, y0 + 54, f"UNIT {sheet['unit']} {sheet['unit_name'].upper()}", 9, "start")
    c.text(
        x0 + 10,
        y0 + 70,
        f"PIPING AND INSTRUMENTATION DIAGRAM: {sheet['title'].upper()}",
        9,
        "start",
    )
    c.text(x0 + 10, y0 + 100, "DWG NO.", 7, "start")
    c.text(x0 + 60, y0 + 100, sheet["sheet"], 11, "start", bold=True)
    c.text(x0 + 240, y0 + 100, "REV B", 9, "start")
    c.text(x0 + 10, y0 + 118, "DATE 2025-11-20   SCALE NONE   DRAWN PLANTCRAFT", 7, "start")
    notes = [
        "NOTES:",
        "1. INSTRUMENT SYMBOLS AND IDENTIFICATION PER ISA-5.1.",
        "2. ALL CONTROL VALVES FAIL CLOSED UNLESS NOTED.",
        "3. SIMULATED PLANT FOR DEMONSTRATION ONLY.",
    ]
    for k, line in enumerate(notes):
        c.text(40, 50 + 12 * k, line, 7, "start")


def draw_all(styles: dict[str, Style] | None = None, **untidy):
    """Every sheet of the demo plant: [(sheet id, canvas, key)]. ``untidy``: Style fields
    applied to every sheet (``arrows=False``, ``jitter=1.5``, ``split=True``...)."""
    out = []
    for n, sheet in enumerate(spec()["sheets"]):
        st = (styles or {}).get(sheet["sheet"]) or Style(
            bubble="isa" if n % 2 == 0 else "inline",
            font="Helvetica" if n % 3 else "Courier",
            **untidy,
        )
        canvas, key = draw_sheet(sheet, st, seed=n)
        out.append((sheet["sheet"], canvas, key))
    return out
