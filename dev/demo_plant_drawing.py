"""Draws the demo's process display, "Riverbend plant" (deploy/demo/diagrams/riverbend-plant.json).

One display, the whole plant on one page (a 1600 x 900 tile per part, LAYOUT below), drawn on
View's own symbols at their own proportions, with lines from port to port. Edit the parts below
and run, from the repository's root:

    python dev/demo_plant_drawing.py

tests/test_demo_diagrams.py checks the result against the plant map and the symbol library.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "deploy" / "demo" / "diagrams" / "riverbend-plant.json"
SYMBOLS = ROOT / "apps" / "view" / "src" / "dashcraft" / "diagrams" / "symbols"


def _library() -> dict:
    found = {}
    for path in SYMBOLS.rglob("*.json"):
        spec = json.loads(path.read_text(encoding="utf-8"))
        found[spec["id"]] = {
            "w": spec["w"],
            "h": spec["h"],
            "ports": {p["id"]: [p["x"], p["y"], p["dir"]] for p in spec["ports"]},
        }
    return found


def _units() -> dict[str, str]:
    """Engineering unit per loop, read from the Simulator's own definitions."""
    text = (ROOT / "simulator" / "src" / "simcraft" / "loops" / "dynamics.py").read_text(
        encoding="utf-8"
    )
    pairs = re.findall(r'loop_id="([A-Z]+-\d+)".*?pv_unit="([^"]*)"', text, flags=re.S)
    return dict(pairs)


LIB = _library()
UNITS = _units()
NAV = 1.5  # scale of the off-page buttons: every name fits at the same type size
STUB = 16  # how far a line leaves a port straight before it turns
DIRS = {"n": (0, -1), "s": (0, 1), "e": (1, 0), "w": (-1, 0)}


def _id(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in text)[:40]


class Page:
    def __init__(self, slug: str, title: str, subtitle: str):
        self.slug, self.title, self.subtitle = slug, title, subtitle
        self.els: list[dict] = []
        self.boxes: dict[str, tuple[str, float, float, float]] = {}  # id -> symbol, x, y, scale
        self.loops: list[str] = []
        self.text(800, 34, title, 24, "middle", True)
        self.text(800, 58, subtitle, 13, "middle")

    # -- symbols ---------------------------------------------------------------------------
    def sym(
        self,
        eid,
        symbol,
        cx,
        cy,
        scale,
        label="",
        asset=None,
        label_pos="below",
        level=None,
        running=None,
        link=None,
        flip=False,
    ):
        """A symbol at the library's own proportions, its box centred on (cx, cy)."""
        spec = LIB[symbol]
        return self._add(
            eid,
            symbol,
            cx - spec["w"] * scale / 2,
            cy - spec["h"] * scale / 2,
            scale,
            label,
            asset,
            label_pos,
            level,
            running,
            link,
            flip,
        )

    def at(
        self,
        eid,
        symbol,
        port,
        px,
        py,
        scale,
        label="",
        asset=None,
        label_pos="below",
        level=None,
        running=None,
        link=None,
        flip=False,
    ):
        """A symbol placed so that one of its ports falls on (px, py)."""
        spec = LIB[symbol]
        x, y, _ = spec["ports"][port]
        if flip:
            x = spec["w"] - x
        return self._add(
            eid,
            symbol,
            px - x * scale,
            py - y * scale,
            scale,
            label,
            asset,
            label_pos,
            level,
            running,
            link,
            flip,
        )

    def _add(self, eid, symbol, x, y, scale, label, asset, label_pos, level, running, link, flip):
        spec = LIB[symbol]
        x, y = round(x, 1), round(y, 1)
        el = {
            "type": "symbol",
            "id": _id(eid),
            "symbol": symbol,
            "x": x,
            "y": y,
            "w": round(spec["w"] * scale, 1),
            "h": round(spec["h"] * scale, 1),
            "rotate": 0,
            "flip": flip,
            "label": label,
            "label_position": label_pos if label else "none",
        }
        if asset:
            el["asset_id"] = asset
            el["link"] = {"kind": "asset", "target": asset}
        if link:
            el["link"] = link
        if level:
            el["level"] = {"item": {"asset_id": level, "role": "pv"}}
        if running:
            el["running"] = {"item": {"asset_id": running, "role": "pv"}, "above": 1}
        assert el["id"] not in self.boxes, el["id"]
        self.els.append(el)
        self.boxes[el["id"]] = (symbol, x, y, scale, flip)
        return el["id"]

    def port(self, eid: str, port: str) -> tuple[float, float, str]:
        symbol, x, y, scale, flip = self.boxes[_id(eid)]
        px, py, d = LIB[symbol]["ports"][port]
        if flip:
            px, d = LIB[symbol]["w"] - px, {"e": "w", "w": "e"}.get(d, d)
        return round(x + px * scale, 1), round(y + py * scale, 1), d

    def box(self, eid: str) -> tuple[float, float, float, float]:
        symbol, x, y, scale, _ = self.boxes[_id(eid)]
        return x, y, LIB[symbol]["w"] * scale, LIB[symbol]["h"] * scale

    def valve(self, eid, x, y, loop, flip=False):
        """A control valve on a horizontal pipe through (x, y); its opening is the loop's OP."""
        _, iy, _ = LIB["valve.control"]["ports"]["inlet"]
        vid = self._add(
            eid,
            "valve.control",
            x - 20,
            y - iy * 0.5,
            0.5,
            "",
            eid,
            "none",
            None,
            None,
            {"kind": "trend", "target": loop},
            flip,
        )
        self.els[-1]["level"] = {"item": {"asset_id": loop, "role": "op"}}
        return vid

    def tw(self, eid, x, y, flip=False):
        """A thermowell on a horizontal pipe through (x, y)."""
        return self.at(
            eid, "instrument.thermowell", "inlet", x - 20 if not flip else x + 20, y, 1, flip=flip
        )

    # -- lines -----------------------------------------------------------------------------
    def pipe(
        self, medium, start, end, via=None, arrow="end", label=None, label_at=None, kind="process"
    ):
        """A line between two ends: (element, port) or a free point [x, y]; corners from
        ``via`` or an orthogonal route from the ports' directions."""
        a = self._end(start)
        b = self._end(end)
        if via is None:
            corners = _route(a, b)
        else:
            corners = [list(p) for p in via]
        n = sum(1 for e in self.els if e["type"] == "line")
        el = {
            "type": "line",
            "id": f"line-{n + 1}",
            "kind": kind,
            "medium": "" if kind == "signal" else medium,
            "points": corners,
            "arrow": arrow,
        }
        pts = list(corners)
        if isinstance(start, tuple):
            el["start"] = {"element": _id(start[0]), "port": start[1]}
        else:
            pts.insert(0, list(start))
        if isinstance(end, tuple):
            el["end"] = {"element": _id(end[0]), "port": end[1]}
        else:
            pts.append(list(end))
        el["points"] = pts
        self.els.append(el)
        if label:
            x, y, anchor = label_at if label_at else _label_spot(a, b, corners)
            self.text(x, y, label, 12, anchor)
        return el["id"]

    def _end(self, end):
        if isinstance(end, tuple):
            return self.port(*end)
        return (end[0], end[1], "")

    # -- loops -----------------------------------------------------------------------------
    def ctl(
        self, loop, cx, cy, to=None, side="right", show=("pv", "sp", "op"), port=None, via=None
    ):
        """The loop's controller: an ISA bubble at (cx, cy) coloured by the loop's health, its
        values in a column beside it, the mode under it, a signal line to ``to``."""
        bid = self.sym(f"ctl-{loop}", "instrument.bubble", cx, cy, 1, asset=loop)
        self.els[-1]["state"] = {"item": {"asset_id": loop, "result": "linkcraft.loop_health"}}
        kind, number = loop.split("-", 1)
        self.text(cx, cy - 2, kind, 12, "middle", True)
        self.text(cx, cy + 12, number, 10, "middle")
        top = cy - 12 * len(show) - 2
        for row, role in enumerate(show):
            size = 13 if role == "pv" else 11
            unit = "%" if role == "op" else UNITS.get(loop, "")
            # View sizes a value box from its text: label, about five digits, the unit.
            width = max(40, (len(role) + 1 + 5 + 1 + len(unit)) * size * 0.6 + 12)
            vx = cx + 28 if side == "right" else round(cx - 28 - width, 1)
            self.els.append(
                {
                    "type": "value",
                    "id": _id(f"{loop}-{role}"),
                    "x": vx,
                    "y": top + row * 24 + (0 if role == "pv" else 1),
                    "item": {"asset_id": loop, "role": role},
                    "label": role.upper(),
                    "show_label": True,
                    "show_unit": True,
                    "decimals": 1,
                    "size": size,
                    "link": {"kind": "trend", "target": loop},
                }
            )
        mx = cx - 52 if side == "right" else cx + 16
        self.els.append(
            {
                "type": "value",
                "id": _id(f"{loop}-mode"),
                "x": mx,
                "y": cy + 22,
                "item": {"asset_id": loop, "role": "mode"},
                "label": "",
                "show_label": False,
                "show_unit": False,
                "decimals": 0,
                "size": 10,
            }
        )
        if to is not None:
            self.signal((bid, port or _facing(self._end(to), (cx, cy))), to, via=via)
        self.loops.append(loop)
        return bid

    def signal(self, start, end, via=None):
        return self.pipe("signal", start, end, via=via, arrow="none", kind="signal")

    # -- navigation and text ---------------------------------------------------------------
    def go(self, target, title, x, y, flip=False):
        """Off to another page: an off-page button whose inlet sits at (x, y), pointing right (or
        left, flipped), the page's name on it. Click opens the page."""
        return self._nav("connector.offpage", "inlet", target, title, x, y, flip)

    def come(self, target, title, x, y, flip=False):
        """In from another page: an off-page button whose outlet sits at (x, y)."""
        return self._nav("connector.offpage_in", "outlet", target, title, x, y, flip)

    def _nav(self, symbol, port, target, title, x, y, flip):
        n = sum(1 for e in self.els if e.get("symbol", "").startswith("connector.offpage"))
        gid = self.at(
            f"go-{n + 1}",
            symbol,
            port,
            x,
            y,
            NAV,
            flip=flip,
            link={"kind": "page", "target": target},
        )
        # View draws an off-page connector as a button with its label and a chevron.
        self.els[-1]["label"] = title
        self.els[-1]["label_position"] = "inside"
        return gid

    def source(self, eid, x, y, flip=False):
        """Where a stream enters from outside the plant drawn (outlet at (x, y))."""
        return self.at(eid, "connector.source", "outlet", x, y, 1, flip=flip)

    def sink(self, eid, x, y, flip=False):
        """Where a stream leaves for outside the plant drawn (inlet at (x, y))."""
        return self.at(eid, "connector.sink", "inlet", x, y, 1, flip=flip)

    def text(self, x, y, text, size=12, align="start", bold=False):
        n = sum(1 for e in self.els if e["type"] == "text")
        self.els.append(
            {
                "type": "text",
                "id": f"t-{n + 1}",
                "x": x,
                "y": y,
                "text": text,
                "size": size,
                "align": align,
                "bold": bold,
            }
        )


def _facing(target, center):
    """The bubble's port that faces a point."""
    dx, dy = target[0] - center[0], target[1] - center[1]
    if abs(dx) >= abs(dy):
        return "right" if dx > 0 else "left"
    return "bottom" if dy > 0 else "top"


def _route(a, b):
    """Orthogonal corners from end a to end b, leaving and entering along the ports' sides."""
    ax, ay, ad = a
    bx, by, bd = b
    if ad:
        ux, uy = DIRS[ad]
        ax, ay = ax + ux * STUB, ay + uy * STUB
    if bd:
        ux, uy = DIRS[bd]
        bx, by = bx + ux * STUB, by + uy * STUB
    pts = [[ax, ay]]
    horizontal_a = ad in ("e", "w") or not ad
    horizontal_b = bd in ("e", "w") or not bd
    if ax == bx or ay == by:
        pass
    elif horizontal_a and horizontal_b:
        mx = round((ax + bx) / 2, 1)
        pts += [[mx, ay], [mx, by]]
    elif horizontal_a and not horizontal_b:
        pts.append([bx, ay])
    elif not horizontal_a and horizontal_b:
        pts.append([ax, by])
    else:
        my = round((ay + by) / 2, 1)
        pts += [[ax, my], [bx, my]]
    pts.append([bx, by])
    out = []
    for p in pts:
        if not out or out[-1] != p:
            out.append(p)
    # Drop the stubs that are collinear with their neighbours (a straight run needs no corner).
    clean = []
    for i, p in enumerate(out):
        if 0 < i < len(out) - 1:
            q, r = out[i - 1], out[i + 1]
            if (q[0] == p[0] == r[0]) or (q[1] == p[1] == r[1]):
                continue
        clean.append(p)
    full = [[a[0], a[1]], *clean, [b[0], b[1]]]
    corners = []
    for i in range(1, len(full) - 1):
        q, p, r = full[i - 1], full[i], full[i + 1]
        if (q[0] == p[0] == r[0]) or (q[1] == p[1] == r[1]):
            continue
        corners.append(p)
    return corners


def _label_spot(a, b, corners):
    pts = [[a[0], a[1]], *corners, [b[0], b[1]]]
    best = max(zip(pts, pts[1:]), key=lambda s: abs(s[1][0] - s[0][0]) + abs(s[1][1] - s[0][1]))
    (x1, y1), (x2, y2) = best
    if abs(y2 - y1) < 1:
        return round((x1 + x2) / 2, 1), y1 - 7, "middle"
    return x1 + 8, round((y1 + y2) / 2, 1), "start"


# ------------------------------------------------------------------------------------------
# Pages
# ------------------------------------------------------------------------------------------

PAGES: list[Page] = []


def page(slug, title, subtitle):
    p = Page(slug, title, subtitle)
    PAGES.append(p)
    return p


def preheat():
    p = page(
        "preheat",
        "Crude feed, preheat and furnace",
        "U-100 Crude distillation unit: Feed, Heat exchange, Furnaces",
    )
    p.sym(
        "TK-1001",
        "vessel.tank_cone_roof",
        200,
        400,
        1.3,
        "TK-1001 Crude charge tank",
        asset="TK-1001",
        label_pos="above",
    )
    p.source("SRC-crude", 90, p.port("TK-1001", "inlet")[1])
    p.pipe("process", ("SRC-crude", "outlet"), ("TK-1001", "inlet"), label="Crude")
    p.sym("P-1001", "pump.centrifugal", 350, 500, 0.8, "P-1001 Charge pump", asset="P-1001")
    p.pipe("process", ("TK-1001", "outlet"), ("P-1001", "suction"))
    y = p.port("P-1001", "discharge")[1]
    p.valve("FV-1001", 460, y, "FIC-1001")
    p.pipe("process", ("P-1001", "discharge"), ("FV-1001", "inlet"), arrow="none")
    p.ctl("FIC-1001", 460, y - 90, ("FV-1001", "signal"))
    p.at("E-1009", "exchanger.generic", "tube_in", 560, y, 1.4, "", asset="E-1009")
    p.pipe("process", ("FV-1001", "outlet"), ("E-1009", "tube_in"))
    p.text(632, y + 44, "E-1009", 12, "start", True)
    p.text(632, y + 60, "Feed/product exchanger", 12, "start")
    p.tw("TT-1009", 760, y)
    p.pipe("process", ("E-1009", "tube_out"), ("TT-1009", "inlet"), arrow="none")
    p.ctl("TIC-1009", 760, y - 90, ("TT-1009", "tap"))
    p.valve("FV-1007", 960, y, "FIC-1007")
    p.pipe("process", ("TT-1009", "outlet"), ("FV-1007", "inlet"), arrow="none")
    p.ctl("FIC-1007", 960, y - 90, ("FV-1007", "signal"))
    p.at(
        "F-1104",
        "heater.furnace",
        "coil_in",
        1130,
        y,
        2.0,
        "F-1104 Atmospheric furnace",
        asset="F-1104",
        label_pos="above",
        running="FIC-1210",
    )
    p.pipe("process", ("FV-1007", "outlet"), ("F-1104", "coil_in"))
    fx, fy, fw, fh = p.box("F-1104")
    p.ctl("TIC-1104", 1430, fy + 100, [fx + 173, fy + 100])
    out_y = p.port("F-1104", "coil_out")[1]
    p.tw("TT-1209", 1400, out_y)
    p.pipe("process", ("F-1104", "coil_out"), ("TT-1209", "inlet"), arrow="none")
    p.ctl("TIC-1209", 1400, out_y - 80, ("TT-1209", "tap"))
    p.go("column", "Column", 1460, out_y)
    p.pipe("process", ("TT-1209", "outlet"), ("go-1", "inlet"))
    p.text(1520, out_y + 50, "To C-1101", 12, "middle")
    # Fuel gas from the utilities, under the furnace.
    p.come("utilities", "Utilities", 1460, 760, flip=True)
    p.valve("FV-1210", 1340, 760, "FIC-1210", flip=True)
    p.pipe(
        "fuel gas",
        ("go-2", "outlet"),
        ("FV-1210", "inlet"),
        arrow="none",
        label="Fuel gas",
        label_at=(1420, 752, "middle"),
    )
    p.pipe("fuel gas", ("FV-1210", "outlet"), ("F-1104", "fuel"))
    p.ctl("FIC-1210", 1340, 670, ("FV-1210", "signal"))
    # Hot product from the column's flash drum heats the crude, then runs down to storage.
    p.come("column", "Column", 1460, 200, flip=True)
    p.pipe(
        "product",
        ("go-3", "outlet"),
        ("E-1009", "shell_in"),
        label="Hot product from flash drum D-1211",
        label_at=(1060, 192, "middle"),
    )
    p.tw("TT-1111", 520, 740, flip=True)
    p.pipe("product", ("E-1009", "shell_out"), ("TT-1111", "inlet"), arrow="none")
    p.ctl("TIC-1111", 520, 650, ("TT-1111", "tap"))
    p.valve("FV-1112", 300, 740, "FIC-1112", flip=True)
    p.pipe("product", ("TT-1111", "outlet"), ("FV-1112", "inlet"), arrow="none")
    p.ctl("FIC-1112", 300, 650, ("FV-1112", "signal"))
    p.sink("SNK-rundown", 60, 740, flip=True)
    p.pipe(
        "product",
        ("FV-1112", "outlet"),
        ("SNK-rundown", "inlet"),
        label="Product to storage",
        label_at=(160, 732, "middle"),
    )
    return p


def column():
    p = page("column", "Atmospheric column", "U-100 Crude distillation unit: Distillation")
    p.sym("C-1101", "column.distillation", 640, 412, 2.4, "", asset="C-1101")
    p.text(708, 160, "C-1101", 12, "start", True)
    p.text(708, 176, "Atmospheric column", 12, "start")
    feed_y = p.port("C-1101", "feed")[1]
    p.come("preheat", "Furnace", 160, feed_y)
    p.text(100, feed_y + 46, "From F-1104", 12, "middle")
    p.valve("FV-1101", 360, feed_y, "FIC-1101")
    p.pipe("process", ("go-1", "outlet"), ("FV-1101", "inlet"), arrow="none")
    p.pipe("process", ("FV-1101", "outlet"), ("C-1101", "feed"))
    p.ctl("FIC-1101", 360, feed_y - 90, ("FV-1101", "signal"))
    p.ctl("TIC-1213", 470, 200, [592, 200], side="left")
    # Overhead: condenser, accumulator, reflux pump.
    p.at(
        "E-1101C",
        "exchanger.air_cooler",
        "inlet",
        820,
        120,
        1.2,
        "Overhead condenser",
        label_pos="below",
    )
    p.pipe(
        "gas",
        ("C-1101", "overhead"),
        ("E-1101C", "inlet"),
        label="Overhead vapour",
        label_at=(730, 112, "middle"),
    )
    p.sym("D-1106", "vessel.horizontal", 1184, 292, 1.8, "", asset="D-1106", level="LIC-1106")
    p.text(1170, 384, "D-1106", 12, "start", True)
    p.text(1170, 400, "Overhead accumulator", 12, "start")
    p.pipe("process", ("E-1101C", "outlet"), ("D-1106", "top_left"))
    p.ctl("LIC-1113", 1420, 270, [1300, 270])
    p.sym(
        "P-1102",
        "pump.centrifugal",
        960,
        450,
        0.8,
        "P-1102 Reflux pump",
        asset="P-1102",
        flip=True,
        label_pos="above",
    )
    p.pipe("process", ("D-1106", "bottom_left"), ("P-1102", "suction"))
    dy = p.port("P-1102", "discharge")[1]
    p.valve("FV-1102", 840, dy, "FIC-1102", flip=True)
    p.pipe("process", ("P-1102", "discharge"), ("FV-1102", "inlet"), arrow="none")
    p.pipe(
        "process",
        ("FV-1102", "outlet"),
        ("C-1101", "reflux"),
        label="Reflux",
        label_at=(724, 212, "middle"),
    )
    p.ctl("FIC-1102", 840, dy - 90, ("FV-1102", "signal"))
    p.valve("LV-1106", 1360, 520, "LIC-1106")
    p.pipe("process", [900, dy], ("LV-1106", "inlet"), via=[[900, 520]], arrow="none")
    p.ctl("LIC-1106", 1360, 430, ("LV-1106", "signal"))
    p.signal(("ctl-LIC-1106", "top"), [1310, 300], via=[[1360, 300]])
    p.go("reactor", "Reactor", 1460, 520)
    p.pipe(
        "process",
        ("LV-1106", "outlet"),
        ("go-2", "inlet"),
        label="Naphtha",
        label_at=(1420, 512, "middle"),
    )
    p.text(1520, 566, "To R-1203", 12, "middle")
    # Side draw.
    p.valve("FV-1214", 900, 700, "FIC-1214")
    p.pipe(
        "product",
        ("C-1101", "side_draw"),
        ("FV-1214", "inlet"),
        via=[[720, 412], [720, 700]],
        arrow="none",
    )
    p.ctl("FIC-1214", 900, 610, ("FV-1214", "signal"))
    p.sink("SNK-diesel", 1500, 700)
    p.pipe(
        "product",
        ("FV-1214", "outlet"),
        ("SNK-diesel", "inlet"),
        label="Side draw (diesel) to storage",
        label_at=(1200, 692, "middle"),
    )
    # Bottoms to the flash drum; its vapour back to the column, its liquid to E-1009.
    p.sym("D-1211", "vessel.vertical", 388, 696, 1.2, "", level="LIC-1211")
    p.text(404, 812, "D-1211 Flash drum", 12, "start", True)
    p.pipe(
        "process",
        ("C-1101", "bottoms"),
        ("D-1211", "right_lower"),
        label="Bottoms",
        label_at=(520, 724, "middle"),
    )
    p.pipe(
        "gas",
        ("D-1211", "top"),
        ("C-1101", "reboiler_return"),
        label="Flashed vapour",
        label_at=(490, 572, "middle"),
    )
    p.go("preheat", "Preheat", 160, 860, flip=True)
    p.valve("LV-1211", 270, 860, "LIC-1211", flip=True)
    p.pipe("product", ("D-1211", "bottom"), ("LV-1211", "inlet"), arrow="none")
    p.pipe("product", ("LV-1211", "outlet"), ("go-3", "inlet"))
    p.ctl("LIC-1211", 270, 760, ("LV-1211", "signal"), side="left")
    p.signal(("ctl-LIC-1211", "right"), [364, 760])
    return p


def reactor():
    p = page(
        "reactor",
        "Hydrotreater reactor loop",
        "U-200 Hydrotreating unit: Hydrotreating, Compression, Quality",
    )
    p.sym("R-1203", "reactor.fixed_bed", 624, 480, 2.6, "", asset="R-1203", flip=True)
    p.text(644, 690, "R-1203", 12, "start", True)
    p.text(644, 706, "Hydrotreating reactor", 12, "start")
    p.come("column", "Column", 160, 190)
    p.text(100, 236, "Naphtha from C-1101", 12, "middle")
    p.valve("FV-1201", 300, 190, "FIC-1201")
    p.pipe("process", ("go-1", "outlet"), ("FV-1201", "inlet"), arrow="none")
    p.pipe("process", ("FV-1201", "outlet"), ("R-1203", "inlet"))
    p.ctl("FIC-1201", 300, 100, ("FV-1201", "signal"))
    rx, ry, rw, rh = p.box("R-1203")
    p.ctl("PIC-1202", 420, ry + 120, [rx + 52, ry + 120], side="left")
    p.ctl("TIC-1203", 420, ry + 280, [rx + 52, ry + 280], side="left")
    # Recycle gas: separator -> suction drum -> compressor -> reactor (and quench).
    p.sym("V-1208", "vessel.vertical", 1148, 396, 1.2, "", asset="V-1208", level="LIC-1208")
    p.text(1148, 516, "V-1208 Suction drum", 12, "middle", True)
    p.sym(
        "K-1103",
        "compressor.centrifugal",
        1060,
        240,
        1.2,
        "K-1103 Recycle compressor",
        asset="K-1103",
        flip=True,
        label_pos="above",
    )
    p.pipe("gas", ("V-1208", "top"), ("K-1103", "suction"))
    p.pipe(
        "gas",
        ("K-1103", "discharge"),
        [624, 240],
        label="Recycle hydrogen",
        label_at=(760, 232, "middle"),
    )
    p.ctl("PIC-1207", 820, 150, [820, 240], port="bottom")
    p.ctl("PIC-1103", 1240, 300, [1148, 300])
    p.ctl("LIC-1208", 1240, 410, [1172, 410])
    p.come("utilities", "Utilities", 1460, 240, flip=True)
    p.pipe(
        "gas",
        ("go-2", "outlet"),
        [1148, 240],
        label="Make-up hydrogen",
        label_at=(1360, 232, "middle"),
    )
    p.valve("FV-1206", 780, ry + 300, "FIC-1206", flip=True)
    p.pipe("gas", [980, 240], ("FV-1206", "inlet"), via=[[980, ry + 300]], arrow="none")
    p.pipe(
        "gas",
        ("FV-1206", "outlet"),
        ("R-1203", "quench"),
        label="Quench",
        label_at=(720, ry + 292, "middle"),
    )
    p.ctl("FIC-1206", 780, ry + 210, ("FV-1206", "signal"))
    # Effluent: cooler -> high-pressure separator.
    p.at("E-1203C", "exchanger.air_cooler", "inlet", 780, 790, 1.2, "Effluent cooler")
    p.pipe(
        "process",
        ("R-1203", "outlet"),
        ("E-1203C", "inlet"),
        label="Reactor effluent",
        label_at=(700, 782, "middle"),
    )
    p.at(
        "V-1204",
        "vessel.horizontal",
        "left",
        1076,
        790,
        1.8,
        "V-1204 High-pressure separator",
        asset="V-1204",
        level="LIC-1204",
    )
    p.pipe("process", ("E-1203C", "outlet"), ("V-1204", "left"))
    p.pipe(
        "gas",
        ("V-1204", "top_left"),
        ("V-1208", "bottom"),
        label="Recycle gas",
        label_at=(1140, 680, "end"),
    )
    p.ctl("AIC-1205", 1240, 610, [1148, 610])
    p.valve("LV-1204", 1380, 790, "LIC-1204")
    p.pipe("process", ("V-1204", "right"), ("LV-1204", "inlet"), arrow="none")
    p.ctl("LIC-1204", 1380, 700, ("LV-1204", "signal"))
    p.go("separation", "Separation", 1460, 790)
    p.pipe("process", ("LV-1204", "outlet"), ("go-3", "inlet"))
    p.text(1520, 836, "To R-1005", 12, "middle")
    return p


def separation():
    p = page(
        "separation",
        "Reaction and separation",
        "U-200 Hydrotreating unit: Reaction, Recycle, Separation, Quality",
    )
    p.sym("R-1005", "reactor.fixed_bed", 488, 420, 2.2, "", asset="R-1005")
    p.text(506, 640, "R-1005 Reactor", 12, "start", True)
    p.come("reactor", "Reactor", 160, 150)
    p.text(100, 196, "From V-1204", 12, "middle")
    p.pipe(
        "process",
        ("go-1", "outlet"),
        ("R-1005", "inlet"),
        label="Treated liquid",
        label_at=(330, 142, "middle"),
    )
    p.ctl("AIC-1215", 300, 250, [300, 150], port="top")
    p.sym("P-1003", "pump.centrifugal", 180, 436, 0.8, "P-1003 Recycle pump", asset="P-1003")
    dy = p.port("P-1003", "discharge")[1]
    p.valve("FV-1003", 310, dy, "FIC-1003")
    p.pipe("process", ("P-1003", "discharge"), ("FV-1003", "inlet"), arrow="none")
    p.pipe("process", ("FV-1003", "outlet"), ("R-1005", "quench"))
    p.ctl("FIC-1003", 310, dy - 90, ("FV-1003", "signal"))
    rx, ry, rw, rh = p.box("R-1005")
    p.ctl("TIC-1005", 620, 400, [rx + 132, 400])
    p.sym("V-1004", "vessel.separator", 920, 520, 2.0, "", asset="V-1004", level="LIC-1004")
    p.text(975, 642, "V-1004 Product separator", 12, "start", True)
    p.pipe(
        "process",
        ("R-1005", "outlet"),
        ("V-1004", "inlet"),
        via=[[488, 680], [700, 680], [700, 500]],
        label="Reactor product",
        label_at=(600, 672, "middle"),
    )
    p.ctl("AIC-1108", 560, 760, [560, 680], port="top")
    # Off-gas to amine treating.
    p.valve("PV-1002", 1200, 300, "PIC-1002")
    p.pipe("gas", ("V-1004", "gas"), ("PV-1002", "inlet"), arrow="none")
    p.ctl("PIC-1002", 1200, 210, ("PV-1002", "signal"))
    p.go("amine", "Amine", 1460, 300)
    p.pipe(
        "gas",
        ("PV-1002", "outlet"),
        ("go-2", "inlet"),
        label="Off-gas",
        label_at=(1330, 292, "middle"),
    )
    p.text(1520, 346, "To C-1216", 12, "middle")
    # Light phase to the surge drum, then product to storage.
    p.valve("LV-1004", 1120, 500, "LIC-1004")
    p.pipe("process", ("V-1004", "oil"), ("LV-1004", "inlet"), arrow="none")
    p.ctl("LIC-1004", 1120, 410, ("LV-1004", "signal"))
    p.sym(
        "V-1105",
        "vessel.horizontal",
        1248,
        704,
        1.6,
        "V-1105 Surge drum",
        asset="V-1105",
        level="LIC-1105",
        label_pos="below",
    )
    p.pipe(
        "process",
        ("LV-1004", "outlet"),
        ("V-1105", "top_left"),
        label="Light phase",
        label_at=(1226, 560, "start"),
    )
    p.valve("LV-1105", 1420, 704, "LIC-1105")
    p.pipe("product", ("V-1105", "right"), ("LV-1105", "inlet"), arrow="none")
    p.ctl("LIC-1105", 1420, 614, ("LV-1105", "signal"))
    p.sink("SNK-product", 1520, 704)
    p.pipe("product", ("LV-1105", "outlet"), ("SNK-product", "inlet"))
    p.text(1530, 678, "Product to storage", 12, "middle")
    p.ctl("AIC-1006", 1480, 830, [1480, 704], port="top", side="left")
    # Heavy phase back to the recycle pump.
    p.valve("LV-1010", 800, 820, "LIC-1010", flip=True)
    p.pipe("water", ("V-1004", "water"), ("LV-1010", "inlet"), arrow="none")
    p.pipe(
        "water",
        ("LV-1010", "outlet"),
        ("P-1003", "suction"),
        via=[[60, 820], [60, 436]],
        label="Heavy phase recycle",
        label_at=(400, 812, "middle"),
    )
    p.ctl("LIC-1010", 800, 730, ("LV-1010", "signal"))
    return p


def amine():
    p = page("amine", "Amine treating and sulfur recovery", "U-300 Treating and sulfur recovery")
    p.sym(
        "C-1216",
        "column.packed",
        388,
        446,
        2.2,
        "C-1216 Amine absorber",
        asset="C-1216",
        level="LIC-1216",
        label_pos="none",
    )
    p.text(250, 160, "C-1216 Amine absorber", 12, "middle", True)
    p.come("separation", "Separation", 160, 600)
    p.text(100, 646, "Off-gas from V-1004", 12, "middle")
    p.pipe(
        "gas",
        ("go-1", "outlet"),
        ("C-1216", "reboiler_return"),
        label="Sour gas",
        label_at=(260, 592, "middle"),
    )
    p.ctl("LIC-1107", 240, 730, [344, 650], via=[[300, 730], [300, 650]], side="left", port="right")
    p.go("utilities", "Fuel gas", 1460, 90)
    p.pipe(
        "gas",
        ("C-1216", "overhead"),
        ("go-2", "inlet"),
        label="Sweet gas",
        label_at=(1000, 82, "middle"),
    )
    p.text(1520, 136, "Fuel gas header", 12, "middle")
    p.sym("C-1217", "column.distillation", 776, 477, 1.9, "", label_pos="none")
    p.text(828, 640, "Amine regenerator", 12, "start", True)
    p.valve("LV-1216", 520, 800, "LIC-1216")
    p.pipe("process", ("C-1216", "bottoms"), ("LV-1216", "inlet"), arrow="none")
    p.pipe(
        "process",
        ("LV-1216", "outlet"),
        ("C-1217", "reflux"),
        via=[[960, 800], [960, 325]],
        label="Rich amine",
        label_at=(740, 792, "middle"),
    )
    p.ctl("LIC-1216", 520, 710, ("LV-1216", "signal"))
    p.tw("TT-1114", 530, 270, flip=True)
    p.pipe(
        "process",
        ("C-1217", "bottoms"),
        ("TT-1114", "inlet"),
        via=[[776, 740], [680, 740], [680, 270]],
        arrow="none",
        label="Lean amine",
        label_at=(728, 732, "middle"),
    )
    p.pipe("process", ("TT-1114", "outlet"), ("C-1216", "reflux"))
    p.ctl("TIC-1114", 530, 180, ("TT-1114", "tap"))
    # Sulfur recovery: reaction furnace, Claus reactor, sulfur pit.
    p.at(
        "H-1226", "heater.furnace", "coil_in", 1040, 220, 1.3, "Reaction furnace", label_pos="below"
    )
    p.pipe(
        "gas",
        ("C-1217", "overhead"),
        ("H-1226", "coil_in"),
        label="Acid gas",
        label_at=(900, 212, "middle"),
    )
    oy = p.port("H-1226", "coil_out")[1]
    p.at(
        "R-1226",
        "vessel.horizontal",
        "left",
        1220,
        oy,
        1.6,
        "R-1226 Claus reactor",
        asset="R-1226",
        label_pos="none",
    )
    p.text(1300, oy - 70, "R-1226 Claus reactor", 12, "middle", True)
    p.pipe("gas", ("H-1226", "coil_out"), ("R-1226", "left"))
    rx, ry, rw, rh = p.box("R-1226")
    p.ctl("TIC-1226", 1372, oy + 130, [1372, oy + 32], port="top")
    p.go("utilities", "Flare", 1460, oy)
    p.pipe("gas", ("R-1226", "right"), ("go-3", "inlet"))
    p.text(1520, oy + 46, "Tail gas to the flare", 12, "middle")
    p.at(
        "SP-1226",
        "vessel.basin",
        "inlet_top",
        p.port("R-1226", "bottom_left")[0],
        640,
        1.6,
        "Sulfur pit",
    )
    p.pipe(
        "product",
        ("R-1226", "bottom_left"),
        ("SP-1226", "inlet_top"),
        label="Liquid sulfur",
        label_at=(1240, 560, "end"),
    )
    return p


def utilities():
    p = page(
        "utilities", "Steam, cooling water and gases", "U-900 Utilities and offsites: Utilities"
    )
    # Steam: boiler -> HP header -> letdown -> MP header -> condensate drum -> back to the boiler.
    p.sym("B-901", "heater.boiler", 150, 330, 1.2, "Boilers", label_pos="below")
    p.valve("FV-1109", 300, 170, "FIC-1109")
    p.pipe("steam", ("B-901", "steam"), ("FV-1109", "inlet"), arrow="none")
    p.ctl("FIC-1109", 300, 80, ("FV-1109", "signal"))
    p.pipe(
        "steam",
        ("FV-1109", "outlet"),
        [1000, 170],
        arrow="none",
        label="HP steam header",
        label_at=(800, 162, "middle"),
    )
    p.valve("PV-1217", 540, 380, "PIC-1217")
    p.pipe(
        "steam",
        [480, 170],
        ("PV-1217", "inlet"),
        via=[[480, 380]],
        arrow="none",
        label="Letdown",
        label_at=(470, 300, "end"),
    )
    p.ctl("PIC-1217", 540, 290, ("PV-1217", "signal"))
    p.at(
        "V-1218",
        "vessel.horizontal",
        "left",
        1112,
        380,
        1.6,
        "V-1218 Condensate drum",
        asset="V-1218",
        level="LIC-1218",
        label_pos="right",
    )
    p.pipe(
        "steam",
        ("PV-1217", "outlet"),
        ("V-1218", "left"),
        label="MP steam header",
        label_at=(950, 372, "middle"),
    )
    p.ctl("PIC-1110", 800, 290, [800, 380], port="bottom")
    p.valve("LV-1218", 700, 520, "LIC-1218", flip=True)
    p.pipe("water", ("V-1218", "bottom_left"), ("LV-1218", "inlet"), arrow="none")
    p.pipe(
        "water",
        ("LV-1218", "outlet"),
        ("B-901", "feedwater"),
        via=[[40, 520], [40, p.port("B-901", "feedwater")[1]]],
        label="Condensate return",
        label_at=(380, 512, "middle"),
    )
    p.ctl("LIC-1218", 700, 430, ("LV-1218", "signal"))
    # Cooling water: tower -> pump -> the units -> back to the tower.
    p.sym("CT-901", "utility.cooling_tower", 144, 698, 1.4, "Cooling tower", label_pos="above")
    p.sym(
        "P-1219",
        "pump.centrifugal",
        300,
        836,
        0.8,
        "P-1219 Cooling water pump",
        asset="P-1219",
        label_pos="below",
    )
    p.pipe("cooling water", ("CT-901", "water_out"), ("P-1219", "suction"))
    dy = p.port("P-1219", "discharge")[1]
    p.valve("FV-1219", 560, dy, "FIC-1219")
    p.pipe("cooling water", ("P-1219", "discharge"), ("FV-1219", "inlet"), arrow="none")
    p.ctl("FIC-1219", 560, dy - 90, ("FV-1219", "signal"))
    p.sink("SNK-cw", 760, dy)
    p.pipe("cooling water", ("FV-1219", "outlet"), ("SNK-cw", "inlet"))
    p.text(790, dy + 40, "Supply to the units", 12, "middle")
    p.source("SRC-cw", 760, 670, flip=True)
    p.text(790, 710, "Return from the units", 12, "middle")
    p.tw("TT-1220", 420, 670, flip=True)
    p.pipe("cooling water", ("SRC-cw", "outlet"), ("TT-1220", "inlet"), arrow="none")
    p.pipe("cooling water", ("TT-1220", "outlet"), ("CT-901", "water_in"))
    p.ctl("TIC-1220", 420, 580, ("TT-1220", "tap"))
    # Fuel gas header (sweet gas from the amine absorber) to the furnace.
    p.come("amine", "Amine", 980, 600)
    p.text(920, 646, "Sweet gas from C-1216", 12, "middle")
    p.valve("PV-1008", 1260, 600, "PIC-1008")
    p.pipe(
        "fuel gas",
        ("go-1", "outlet"),
        ("PV-1008", "inlet"),
        arrow="none",
        label="Fuel gas header",
        label_at=(1100, 592, "middle"),
    )
    p.ctl("PIC-1008", 1260, 510, ("PV-1008", "signal"))
    p.go("preheat", "Furnace", 1460, 600)
    p.pipe("fuel gas", ("PV-1008", "outlet"), ("go-2", "inlet"))
    p.text(1520, 646, "To F-1104", 12, "middle")
    # Nitrogen network and hydrogen make-up.
    p.source("SRC-h2", 980, 700)
    p.text(950, 740, "Hydrogen supply", 12, "middle")
    p.go("reactor", "Reactor", 1460, 700)
    p.pipe(
        "gas",
        ("SRC-h2", "outlet"),
        ("go-3", "inlet"),
        label="Make-up hydrogen",
        label_at=(1220, 692, "middle"),
    )
    p.text(1520, 746, "To V-1208", 12, "middle")
    p.source("SRC-n2", 980, 850)
    p.text(950, 890, "Nitrogen supply", 12, "middle")
    p.valve("PV-1221", 1260, 850, "PIC-1221")
    p.pipe(
        "nitrogen",
        ("SRC-n2", "outlet"),
        ("PV-1221", "inlet"),
        arrow="none",
        label="Nitrogen network",
        label_at=(1100, 842, "middle"),
    )
    p.ctl("PIC-1221", 1260, 760, ("PV-1221", "signal"))
    p.sink("SNK-n2", 1500, 850)
    p.pipe("nitrogen", ("PV-1221", "outlet"), ("SNK-n2", "inlet"))
    p.text(1530, 890, "To the units", 12, "middle")
    # Flare: relief and tail gas to the stack.
    p.come("amine", "Amine", 1100, 230)
    p.text(1040, 276, "Tail gas from R-1226", 12, "middle")
    p.valve("PV-1212", 1220, 230, "PIC-1212")
    p.pipe("gas", ("go-4", "outlet"), ("PV-1212", "inlet"), arrow="none")
    p.ctl("PIC-1212", 1220, 140, ("PV-1212", "signal"))
    p.at("FL-901", "utility.flare_stack", "inlet", 1440, 230, 1.6, "Flare", label_pos="below")
    p.pipe(
        "gas",
        ("PV-1212", "outlet"),
        ("FL-901", "inlet"),
        label="Flare header",
        label_at=(1340, 222, "middle"),
    )
    return p


def effluent():
    p = page(
        "effluent", "Effluent treatment and slop", "U-900 Utilities and offsites: Water treatment"
    )
    # Slop: drains and skimmed oil -> slop tank -> rerun.
    p.sym(
        "TK-1225",
        "vessel.tank_cone_roof",
        300,
        280,
        1.6,
        "TK-1225 Slop tank",
        asset="TK-1225",
        level="LIC-1225",
        label_pos="below",
    )
    iy = p.port("TK-1225", "inlet")[1]
    p.source("SRC-drains", 120, iy)
    p.text(90, iy + 40, "Drains and skimmed oil", 12, "middle")
    p.pipe("oil", ("SRC-drains", "outlet"), ("TK-1225", "inlet"))
    oy = p.port("TK-1225", "outlet")[1]
    p.valve("LV-1225", 620, oy, "LIC-1225")
    p.pipe("oil", ("TK-1225", "outlet"), ("LV-1225", "inlet"), arrow="none")
    p.ctl("LIC-1225", 620, oy - 90, ("LV-1225", "signal"))
    p.signal(("ctl-LIC-1225", "left"), [372, oy - 90])
    p.sink("SNK-slop", 1500, oy)
    p.pipe(
        "oil",
        ("LV-1225", "outlet"),
        ("SNK-slop", "inlet"),
        label="Slop oil to rerun",
        label_at=(1060, oy - 8, "middle"),
    )
    # Oily water: equalization tank -> transfer pump -> neutralization -> discharge.
    p.at(
        "TK-1223",
        "vessel.tank",
        "inlet",
        560,
        560,
        2.0,
        "TK-1223 Equalization tank",
        asset="TK-1223",
        level="LIC-1223",
        label_pos="below",
    )
    p.source("SRC-oily", 120, 560)
    p.text(90, 600, "Oily water from the units", 12, "middle")
    p.valve("FV-1222", 360, 560, "FIC-1222")
    p.pipe("water", ("SRC-oily", "outlet"), ("FV-1222", "inlet"), arrow="none")
    p.pipe("water", ("FV-1222", "outlet"), ("TK-1223", "inlet"))
    p.ctl("FIC-1222", 360, 470, ("FV-1222", "signal"))
    ty = p.port("TK-1223", "outlet")[1]
    p.sym("P-1223", "pump.centrifugal", 850, ty + 16, 0.8, "Transfer pump")
    p.pipe("water", ("TK-1223", "outlet"), ("P-1223", "suction"))
    dy = p.port("P-1223", "discharge")[1]
    p.valve("LV-1223", 980, dy, "LIC-1223")
    p.pipe("water", ("P-1223", "discharge"), ("LV-1223", "inlet"), arrow="none")
    p.ctl("LIC-1223", 980, dy - 90, ("LV-1223", "signal"))
    tx, _, tw, _ = p.box("TK-1223")
    p.signal(("ctl-LIC-1223", "left"), [tx + 0.9 * tw, dy - 90])
    p.at("NT-901", "vessel.basin", "inlet", 1100, dy, 2.0, "Neutralization", label_pos="below")
    p.pipe("water", ("LV-1223", "outlet"), ("NT-901", "inlet"))
    by = p.port("NT-901", "outlet")[1]
    p.sink("SNK-treated", 1500, by)
    p.pipe(
        "water",
        ("NT-901", "outlet"),
        ("SNK-treated", "inlet"),
        label="Treated water",
        label_at=(1440, by - 8, "middle"),
    )
    p.ctl("AIC-1224", 1380, by - 90, [1380, by], port="bottom")
    return p


TILE_W, TILE_H = 1600, 900
# Where each part of the plant sits on the one page (the whole process
# together, looked at closely with the viewer's zoom): the crude's way left to right, top to
# bottom, the utilities and effluent centred under it. Column, row of each 1600 x 900 tile.
LAYOUT = {
    "preheat": (0, 0),
    "column": (1, 0),
    "reactor": (2, 0),
    "separation": (0, 1),
    "amine": (1, 1),
    "effluent": (2, 1),
    "utilities": (1, 2),
}

# The tabs over the drawing ("Overview" and a way to each part), in LAYOUT's
# reading order.
PART_NAMES = {
    "preheat": "Preheat and furnace",
    "column": "Column",
    "reactor": "Reactor loop",
    "separation": "Separation",
    "amine": "Amine and sulfur",
    "effluent": "Effluent",
    "utilities": "Utilities",
}


def whole(pages) -> dict:
    """The whole plant as one process display on one page: each part drawn at its tile of
    LAYOUT, element ids kept unique by the part's name. An off-page button ("Column") zooms to
    the part it names."""
    elements = []
    for p in pages:
        col, row = LAYOUT[p.slug]
        dx, dy = col * TILE_W, row * TILE_H
        mine = {e["id"] for e in p.els}
        for e in p.els:
            e = json.loads(json.dumps(e))
            e["id"] = _id(f"{p.slug[:4]}-{e['id']}")
            if "x" in e:
                e["x"], e["y"] = e["x"] + dx, e["y"] + dy
            if "points" in e:
                e["points"] = [[x + dx, y + dy] for x, y in e["points"]]
            if (e.get("link") or {}).get("kind") == "page":
                # On one page an off-page button zooms to the part it names.
                tc, tr = LAYOUT[e["link"]["target"]]
                e["link"] = {
                    "kind": "area",
                    "target": f"{tc * TILE_W},{tr * TILE_H},{TILE_W},{TILE_H}",
                }
            for end in ("start", "end"):
                if end in e:
                    assert e[end]["element"] in mine
                    e[end]["element"] = _id(f"{p.slug[:4]}-{e[end]['element']}")
            elements.append(e)
    ids = [e["id"] for e in elements]
    assert len(ids) == len(set(ids)), "ids collide"
    return {
        "name": "Riverbend plant",
        "description": "Riverbend Refinery on one page, unit by unit: zoom in with the wheel "
        "or a double click, drag to move.",
        "folder_id": "",
        "tags": ["demo", "Riverbend Refinery"],
        "width": 3 * TILE_W,
        "height": 3 * TILE_H,
        "grid": 10,
        "refresh_seconds": 5,
        "default_window": "1h",
        "parts": [
            {
                "id": slug,
                "name": name,
                "area": f"{LAYOUT[slug][0] * TILE_W},{LAYOUT[slug][1] * TILE_H},{TILE_W},{TILE_H}",
            }
            for slug, name in PART_NAMES.items()
        ],
        "elements": elements,
    }


def main() -> None:
    for draw in (preheat, column, reactor, separation, amine, utilities, effluent):
        draw()
    plant = whole(PAGES)
    OUT.write_text(json.dumps(plant, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    loops = sum(len(p.loops) for p in PAGES)
    print(
        f"{OUT.relative_to(ROOT)}: {len(PAGES)} parts on one page, "
        f"{len(plant['elements'])} elements, {loops} loops"
    )


if __name__ == "__main__":
    main()
