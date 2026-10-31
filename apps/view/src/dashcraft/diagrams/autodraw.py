"""A unit's first diagram, drawn from its assets in PlantCraft: no model, no guessing.

``draw_unit(assets, unit_id)`` takes the asset list API v1 answers (``reader.assets(None)``:
``id``, ``name``, ``kind``, ``type_path``, ``parent_id``, ``signals`` by role, ``attributes``
and the ``relations`` to other assets) and lays out every asset under the unit:

- each piece of equipment is one symbol, picked from its kind (a library symbol that lists
  the kind in ``asset_types`` first, else a common one, else a generic box), with the level of
  a tank or a vessel and the running state of a pump bound when a role says so;
- each control loop is an instrument bubble coloured by Analytics' loop health
  (``linkcraft.loop_health``), with its PV and SP as values, drawn above the equipment it
  controls or measures, joined to it by a signal line;
- process lines follow the ``feeds`` and ``downstream_of`` relations.

The layout runs left to right: each piece of equipment goes one column after everything that
feeds it (the longest path), back edges (a recycle) do not push columns and are drawn under the
graph; equipment without process lines and loops of no equipment are placed in rows below.
Everything snaps to the grid and the canvas grows to hold it (up to the largest canvas, then the
whole drawing shrinks to fit). The same assets always draw the same diagram.
"""

from __future__ import annotations

import heapq
import math
import re
from collections.abc import Iterable
from typing import Any

from dashcraft.diagrams.model import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    MAX_SIZE,
    MIN_SIZE,
    PAGE_ELEMENTS,
    DiagramPayload,
)
from dashcraft.i18n import t

GRID = 10
MARGIN = 40
TITLE_HEIGHT = 50
# One cell per piece of equipment: its loops on top, the symbol, its label and values below.
CELL_W, CELL_H = 240, 360
BUBBLE_BAND = 110
EQUIPMENT_BAND = 160
BUBBLE = 40
BUBBLE_PITCH = 72
MAX_BUBBLES = 3
# A loop of no equipment: a bubble and its values in a small cell.
LOOP_W, LOOP_H = 120, 130
MAX_SYMBOL_W, MAX_SYMBOL_H = 120, 140
WRAP_COLUMNS = 6
MAX_VALUES = 2
LOOP_HEALTH = "linkcraft.loop_health"
STRUCTURE = frozenset({"site", "unit", "area"})
LOOP_KINDS = frozenset({"loop"})
INSTRUMENT_WORDS = ("instrument", "transmitter", "sensor", "analyzer", "analyser", "indicator")
PROCESS_RELATIONS = ("feeds", "downstream_of")
ATTACH_RELATIONS = ("controls", "measures")
LEVEL_ROLE = re.compile(r"(^|[_\-. ])(level|lvl)($|[_\-. ])|^level|level$|^l$", re.I)
RUN_ROLES = ("running", "run", "run_status", "run_state", "on", "motor_running")
VALUE_ROLES = ("pv", "flow", "pressure", "temperature", "speed", "current", "power", "out")
FALLBACK_SYMBOL = ("shape.panel", 80, 60)

# Common kinds and the symbol each draws as (first match on the words of the kind wins).
KIND_SYMBOLS: tuple[tuple[tuple[str, ...], str, int, int], ...] = (
    (("control_valve", "controlvalve"), "valve.control", 40, 40),
    (("valve",), "valve.gate", 40, 40),
    (("pump",), "pump.centrifugal", 60, 60),
    (("compressor",), "compressor.centrifugal", 80, 60),
    (("blower", "fan"), "fan.blower", 60, 60),
    (("tank", "silo"), "vessel.tank", 80, 120),
    (("column", "tower"), "column.distillation", 60, 140),
    (("reactor",), "reactor.stirred", 80, 120),
    (("drum", "vessel", "separator", "accumulator", "receiver"), "vessel.vertical", 60, 120),
    (
        ("exchanger", "cooler", "condenser", "reboiler", "chiller", "heat_exchanger"),
        "exchanger.shell_tube",
        100,
        60,
    ),
    (("furnace", "heater", "boiler", "kiln"), "heater.furnace", 100, 120),
    (("turbine",), "turbine.steam", 80, 60),
    (("filter", "strainer"), "filter.basket", 40, 60),
    (("mixer", "agitator"), "machine.agitator", 60, 80),
    (("conveyor",), "conveyor.belt", 120, 40),
    (("motor",), "motor.electric", 60, 40),
)
LEVEL_KINDS = frozenset(
    {"vessel.tank", "vessel.vertical", "column.distillation", "reactor.stirred"}
)


def _snap(value: float) -> int:
    return int(round(value / GRID) * GRID)


def _snap_up(value: float) -> int:
    return int(math.ceil(value / GRID) * GRID)


def _text(value: Any, limit: int = 80) -> str:
    return str(value if value is not None else "").strip()[:limit]


def _parent(asset: dict[str, Any]) -> str | None:
    parent = asset.get("parent_id")
    return parent if isinstance(parent, str) and parent else None


def _attribute(asset: dict[str, Any], key: str) -> Any:
    attributes = asset.get("attributes")
    return attributes.get(key, "") if isinstance(attributes, dict) else ""


def _words(asset: dict[str, Any]) -> list[str]:
    """The asset's kind and its type path, most specific first, lower case."""

    path = asset.get("type_path")
    words = [str(asset.get("kind") or "")]
    if isinstance(path, list):
        words += [str(item) for item in reversed(path)]
    return [word.strip().lower() for word in words if word and word.strip()]


def _signals(asset: dict[str, Any]) -> dict[str, str]:
    found = asset.get("signals")
    if not isinstance(found, dict):
        return {}
    return {
        str(role): str(signal)
        for role, signal in found.items()
        if isinstance(role, str) and role.strip() and len(role) <= 60 and signal
    }


def _relations(asset: dict[str, Any]) -> list[tuple[str, str]]:
    found = asset.get("relations")
    out: list[tuple[str, str]] = []
    if not isinstance(found, list):
        return out
    for item in found:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or item.get("relation") or "")
        target = item.get("to") or item.get("to_id")
        if kind and isinstance(target, str) and target:
            out.append((kind, target))
    return out


def _is_loop(words: list[str]) -> bool:
    return any(word in LOOP_KINDS for word in words)


def _is_instrument(words: list[str]) -> bool:
    return any(any(part in word for part in INSTRUMENT_WORDS) for word in words[:1])


def _library_index(library: Iterable[dict[str, Any]]) -> tuple[dict[str, dict], dict[str, dict]]:
    """Symbols by id, and by the asset type each one says it draws (first one wins)."""

    by_id: dict[str, dict[str, Any]] = {}
    by_type: dict[str, dict[str, Any]] = {}
    for symbol in library:
        if not isinstance(symbol, dict) or not symbol.get("id"):
            continue
        by_id.setdefault(str(symbol["id"]), symbol)
        for kind in symbol.get("asset_types") or []:
            by_type.setdefault(str(kind).lower(), symbol)
    return by_id, by_type


def _fit_size(w: float, h: float) -> tuple[int, int]:
    """The library drawing's size, shrunk to fit a cell at the drawing's own ratio, on the grid
    (the page never squashes a drawing: what the grid adds is room round it, see ``_fitted``)."""

    w, h = max(float(w), 1.0), max(float(h), 1.0)
    scale = min(1.0, MAX_SYMBOL_W / w, MAX_SYMBOL_H / h)
    return max(20, _snap(w * scale / 2) * 2), max(20, _snap(h * scale / 2) * 2)


def _fitted(box: dict[str, Any], symbol: dict[str, Any]) -> tuple[float, float, float, float]:
    """Where the drawing sits in its box (left, top, x scale, y scale): one scale both ways and
    centred, as the page draws it (``fitted`` in the frontend's diagrams/model.ts)."""

    sw, sh = float(symbol["w"]), float(symbol["h"])
    if symbol.get("stretch"):
        return box["x"], box["y"], box["w"] / sw, box["h"] / sh
    scale = min(box["w"] / sw, box["h"] / sh)
    return (
        box["x"] + (box["w"] - sw * scale) / 2,
        box["y"] + (box["h"] - sh * scale) / 2,
        scale,
        scale,
    )


def pick_symbol(
    words: list[str], by_id: dict[str, dict], by_type: dict[str, dict]
) -> tuple[str, int, int]:
    """The symbol for an asset of these kinds: the library's own pick, a common one, a box."""

    for word in words:
        if word in by_type:
            symbol = by_type[word]
            return (str(symbol["id"]), *_fit_size(symbol.get("w", 60), symbol.get("h", 60)))
    for word in words:
        for keys, symbol_id, w, h in KIND_SYMBOLS:
            if any(key in word for key in keys):
                known = by_id.get(symbol_id)
                if known:
                    return (symbol_id, *_fit_size(known.get("w", w), known.get("h", h)))
                return symbol_id, w, h
    return FALLBACK_SYMBOL


def _port(symbol: dict[str, Any] | None, side: str) -> dict[str, Any] | None:
    """A process port on the ``side`` of a library symbol (``e`` out, ``w`` in), if any."""

    if not symbol:
        return None
    ports = [port for port in symbol.get("ports") or [] if port.get("kind", "process") == "process"]
    wanted = "out" if side == "e" else "in"
    for test in (
        lambda port: port.get("dir") == side and wanted in str(port.get("id", "")).lower(),
        lambda port: port.get("dir") == side,
        lambda port: wanted in str(port.get("id", "")).lower(),
    ):
        found = next((port for port in ports if test(port)), None)
        if found:
            return found
    return None


def _anchor(
    box: dict[str, Any], symbol: dict[str, Any] | None, side: str
) -> tuple[dict[str, Any] | None, tuple[float, float]]:
    """Where a process line joins a drawn symbol: its library port on ``side``, else the middle
    of that side (the line then ends on the symbol's centre, port "")."""

    port = _port(symbol, side)
    if port is not None and symbol and symbol.get("w") and symbol.get("h"):
        left, top, sx, sy = _fitted(box, symbol)
        return port, (left + float(port["x"]) * sx, top + float(port["y"]) * sy)
    return None, (box["x"] + (box["w"] if side == "e" else 0), box["y"] + box["h"] / 2)


class _Ids:
    """Element ids from asset ids: readable, within the contract's pattern, never twice."""

    def __init__(self) -> None:
        self.taken: set[str] = set()

    def __call__(self, prefix: str, name: str) -> str:
        base = re.sub(r"[^A-Za-z0-9_-]+", "-", f"{prefix}-{name}").strip("-")[:34] or prefix
        candidate, number = base, 2
        while candidate in self.taken:
            candidate = f"{base}-{number}"
            number += 1
        self.taken.add(candidate)
        return candidate


def _descendants(
    assets: list[dict[str, Any]], unit_id: str, stop: frozenset[str] = frozenset()
) -> list[dict[str, Any]]:
    """Every asset under ``unit_id``, except those under one of ``stop`` (another unit drawn on
    its own diagram), by name."""

    by_id = {str(asset.get("id")): asset for asset in assets if asset.get("id")}
    out = []
    for asset_id, asset in by_id.items():
        if asset_id == unit_id or asset_id in stop:
            continue
        seen: set[str] = set()
        current = _parent(asset)
        while current and current != unit_id and current not in seen and current not in stop:
            seen.add(current)
            current = _parent(by_id.get(current) or {})
        if current == unit_id:
            out.append(asset)
    return sorted(
        out, key=lambda asset: (_text(asset.get("name") or asset["id"]).lower(), asset["id"])
    )


def _layers(nodes: list[str], edges: list[tuple[str, str]]) -> tuple[dict[str, int], set]:
    """Longest-path layers of the nodes joined by ``edges`` (back edges found by a depth-first
    walk in the nodes' order are left out), and those back edges."""

    order = {node: index for index, node in enumerate(nodes)}
    out: dict[str, list[str]] = {node: [] for node in nodes}
    for source, target in edges:
        out[source].append(target)
    for node in out:
        out[node] = sorted(set(out[node]), key=order.__getitem__)
    back: set[tuple[str, str]] = set()
    state: dict[str, int] = {}
    for root in nodes:
        if root in state:
            continue
        stack = [(root, iter(out[root]))]
        state[root] = 1
        while stack:
            node, children = stack[-1]
            child = next(children, None)
            if child is None:
                state[node] = 2
                stack.pop()
            elif state.get(child) == 1:
                back.add((node, child))
            elif child not in state:
                state[child] = 1
                stack.append((child, iter(out[child])))
    forward = [(s, d) for s, d in edges if (s, d) not in back and s != d]
    incoming = {node: 0 for node in nodes}
    successors: dict[str, set[str]] = {node: set() for node in nodes}
    for source, target in set(forward):
        successors[source].add(target)
        incoming[target] += 1
    layer = {node: 0 for node in nodes}
    ready = [(order[node], node) for node in nodes if incoming[node] == 0]
    heapq.heapify(ready)
    while ready:
        _, node = heapq.heappop(ready)
        for child in sorted(successors[node], key=order.__getitem__):
            layer[child] = max(layer[child], layer[node] + 1)
            incoming[child] -= 1
            if incoming[child] == 0:
                heapq.heappush(ready, (order[child], child))
    return layer, back


def _scale(elements: list[dict[str, Any]], factor: float) -> None:
    """Shrink a drawing too big for the largest canvas (positions and sizes)."""

    for element in elements:
        for key in ("x", "y"):
            if key in element:
                element[key] = _snap(element[key] * factor)
        for key in ("w", "h"):
            if key in element:
                element[key] = max(10, _snap(element[key] * factor))
        if "size" in element:
            element["size"] = max(8, int(element["size"] * factor))
        if element.get("points"):
            element["points"] = [
                [round(x * factor, 1), round(y * factor, 1)] for x, y in element["points"]
            ]


def draw_unit(
    assets: list[dict[str, Any]],
    unit_id: str,
    *,
    library: Iterable[dict[str, Any]] = (),
    name: str | None = None,
    stop: Iterable[str] = (),
) -> tuple[dict[str, Any], list[str]] | None:
    """The diagram of ``unit_id`` (a stored ``DiagramPayload``) and notes on what was left out;
    None when the unit is not among ``assets``. Assets under one of ``stop`` are left out."""

    assets = [
        asset
        for asset in assets or []
        if isinstance(asset, dict) and isinstance(asset.get("id"), str) and asset["id"]
    ]
    unit = next((asset for asset in assets if asset.get("id") == unit_id), None)
    if unit is None:
        return None
    by_id, by_type = _library_index(library)
    notes: list[str] = []
    unit_name = _text(unit.get("name") or unit_id, 60)
    members = [
        asset
        for asset in _descendants(assets, unit_id, frozenset(stop) - {unit_id})
        if len(asset["id"]) <= 300
    ]
    equipment: list[dict[str, Any]] = []
    loops: list[dict[str, Any]] = []
    for asset in members:
        words = _words(asset)
        if any(word in STRUCTURE for word in words[:1]) or "result" in words[:1]:
            continue
        if _is_loop(words) or _is_instrument(words):
            loops.append(asset)
        else:
            equipment.append(asset)
    drawn = {asset["id"] for asset in equipment}
    ids = _Ids()
    element_of = {asset["id"]: ids("e", asset["id"]) for asset in equipment}

    # Process lines and the layers they make.
    edges: list[tuple[str, str]] = []
    for asset in equipment:
        for kind, target in _relations(asset):
            if target not in drawn or target == asset["id"]:
                continue
            if kind == "feeds":
                edges.append((asset["id"], target))
            elif kind == "downstream_of":
                edges.append((target, asset["id"]))
    edges = list(dict.fromkeys(edges))
    connected = [asset["id"] for asset in equipment if any(asset["id"] in edge for edge in edges)]
    isolated = [asset["id"] for asset in equipment if asset["id"] not in set(connected)]
    layer, back = _layers(connected, edges)

    # Loops onto the equipment they control or measure (or sit under).
    attached: dict[str, list[dict[str, Any]]] = {}
    free: list[dict[str, Any]] = []
    for loop in loops:
        related = _relations(loop)
        targets = [
            target for wanted in ATTACH_RELATIONS for kind, target in related if kind == wanted
        ]
        host = next((target for target in targets if target in drawn), None)
        if host is None and _parent(loop) in drawn:
            host = _parent(loop)
        if host is not None and len(attached.get(host, [])) < MAX_BUBBLES:
            attached.setdefault(host, []).append(loop)
        else:
            free.append(loop)

    # Cells: layers left to right, each ordered by where what feeds it sits.
    position: dict[str, tuple[int, int]] = {}
    columns: dict[int, list[str]] = {}
    for node in connected:
        columns.setdefault(layer[node], []).append(node)
    rank: dict[str, int] = {}
    name_order = {node: index for index, node in enumerate(connected)}
    for column in sorted(columns):
        nodes = columns[column]

        def centre(node: str) -> tuple[float, int]:
            preds = [rank[s] for s, d in edges if d == node and s in rank and (s, d) not in back]
            return (sum(preds) / len(preds) if preds else math.inf, name_order[node])

        nodes.sort(key=centre)
        for row, node in enumerate(nodes):
            rank[node] = row
            position[node] = (column, row)
    graph_rows = max((len(nodes) for nodes in columns.values()), default=0)
    graph_columns = len(columns)
    wrap = max(WRAP_COLUMNS, graph_columns)
    for index, node in enumerate(isolated):
        position[node] = (index % wrap, graph_rows + index // wrap)
    rows_used = graph_rows + math.ceil(len(isolated) / wrap)
    top = MARGIN + TITLE_HEIGHT
    lane = top + graph_rows * CELL_H - 15

    elements: list[dict[str, Any]] = [
        {
            "id": ids("title", "unit"),
            "type": "text",
            "x": MARGIN,
            "y": MARGIN,
            "text": t("{unit}, drawn from PlantCraft's assets", unit=unit_name),
            "size": 18,
            "bold": True,
        }
    ]
    lines: list[dict[str, Any]] = []
    boxes: dict[str, dict[str, Any]] = {}
    left_out = 0

    def room(count: int) -> bool:
        return len(elements) + len(lines) + count <= PAGE_ELEMENTS

    def loop_elements(loop: dict[str, Any], x: int, y: int) -> list[dict[str, Any]]:
        roles = _signals(loop)
        bubble_id = ids("l", loop["id"])
        bubble: dict[str, Any] = {
            "id": bubble_id,
            "type": "symbol",
            "symbol": "instrument.bubble",
            "x": x,
            "y": y,
            "w": BUBBLE,
            "h": BUBBLE,
            "label": _text(loop.get("name") or loop["id"]),
            "label_position": "above",
            "asset_id": loop["id"],
        }
        if _is_loop(_words(loop)):
            bubble["state"] = {"item": {"asset_id": loop["id"], "result": LOOP_HEALTH}}
        out = [bubble]
        for offset, role in enumerate(role for role in ("pv", "sp") if role in roles):
            out.append(
                {
                    "id": ids("v", f"{loop['id']}-{role}"),
                    "type": "value",
                    "x": x - 10,
                    "y": y + BUBBLE + 10 + offset * 20,
                    "item": {"asset_id": loop["id"], "role": role},
                    "label": role.upper(),
                    "size": 12,
                }
            )
        return out

    for asset in equipment:
        column, row = position[asset["id"]]
        cell_x, cell_y = MARGIN + column * CELL_W, top + row * CELL_H
        hosted = attached.get(asset["id"], [])
        roles = _signals(asset)
        words = _words(asset)
        symbol_id, w, h = pick_symbol(words, by_id, by_type)
        level_role = next((role for role in sorted(roles) if LEVEL_ROLE.search(role)), None)
        run_role = next((role for role in RUN_ROLES if role in roles), None)
        values = [
            role for role in VALUE_ROLES if role in roles and role not in (level_role, run_role)
        ][:MAX_VALUES]
        wanted = 1 + len(values) + sum(1 + 2 + 1 for _ in hosted)
        if not room(wanted):
            left_out += 1
            continue
        x = _snap(cell_x + (CELL_W - w) / 2)
        y = _snap(cell_y + BUBBLE_BAND + (EQUIPMENT_BAND - h) / 2)
        symbol: dict[str, Any] = {
            "id": element_of[asset["id"]],
            "type": "symbol",
            "symbol": symbol_id,
            "x": x,
            "y": y,
            "w": w,
            "h": h,
            "label": _text(asset.get("name") or asset["id"]),
            "asset_id": asset["id"],
        }
        if level_role is None and symbol_id in LEVEL_KINDS:
            # A level loop on the vessel stands in for a level role of its own.
            level_loop = next(
                (
                    loop
                    for loop in hosted
                    if "pv" in _signals(loop)
                    and str(_attribute(loop, "loop_type")).lower() == "level"
                ),
                None,
            )
            if level_loop is not None:
                symbol["level"] = {"item": {"asset_id": level_loop["id"], "role": "pv"}}
        elif level_role is not None:
            symbol["level"] = {"item": {"asset_id": asset["id"], "role": level_role}}
        if run_role is not None:
            symbol["running"] = {"item": {"asset_id": asset["id"], "role": run_role}}
        elements.append(symbol)
        boxes[asset["id"]] = symbol
        label_bottom = y + h + 30
        for offset, role in enumerate(values):
            elements.append(
                {
                    "id": ids("v", f"{asset['id']}-{role}"),
                    "type": "value",
                    "x": _snap(x + w / 2 - 40),
                    "y": label_bottom + offset * 20,
                    "item": {"asset_id": asset["id"], "role": role},
                    "label": role.upper() if len(role) <= 4 else role.replace("_", " "),
                    "size": 12,
                }
            )
        span = len(hosted) * BUBBLE_PITCH - (BUBBLE_PITCH - BUBBLE)
        start_x = _snap(cell_x + (CELL_W - span) / 2)
        for index, loop in enumerate(hosted):
            bx, by = start_x + index * BUBBLE_PITCH, cell_y + 30
            parts = loop_elements(loop, bx, by)
            elements.extend(parts)
            # The signal line from the bubble down to the equipment.
            cx, top_y = bx + BUBBLE / 2, y - 10
            ex = x + w / 2
            lines.append(
                {
                    "id": ids("s", f"{loop['id']}-{asset['id']}"),
                    "type": "line",
                    "kind": "signal",
                    "start": {"element": parts[0]["id"], "port": ""},
                    "end": {"element": symbol["id"], "port": ""},
                    "points": [] if cx == ex else [[cx, top_y], [ex, top_y]],
                    "arrow": "end",
                }
            )

    # Loops of no equipment, in rows under everything else.
    loop_top = top + rows_used * CELL_H
    per_row = max(1, (max(wrap * CELL_W, DEFAULT_WIDTH - 2 * MARGIN)) // LOOP_W)
    placed_free = 0
    for loop in free:
        if not room(3):
            left_out += 1
            continue
        column, row = placed_free % per_row, placed_free // per_row
        x = MARGIN + column * LOOP_W + (LOOP_W - BUBBLE) // 2
        y = loop_top + row * LOOP_H + 30
        elements.extend(loop_elements(loop, _snap(x), _snap(y)))
        placed_free += 1
    free_rows = math.ceil(placed_free / per_row) if placed_free else 0

    # Process lines between the equipment drawn.
    for source, target in edges:
        if source not in boxes or target not in boxes or not room(1):
            continue
        a, b = boxes[source], boxes[target]
        out_port, (sx, sy) = _anchor(a, by_id.get(a["symbol"]), "e")
        in_port, (tx, ty) = _anchor(b, by_id.get(b["symbol"]), "w")
        if (source, target) in back or tx <= sx:
            # A recycle: out to the right, along the lane under the graph, back in from the left.
            right, left = _snap(sx + 20), _snap(tx - 20)
            points = [[right, sy], [right, lane], [left, lane], [left, ty]]
        else:
            # Forward: no corners of its own, the page routes it from port to port (out of each
            # along its way, round the two symbols, on the grid).
            points = []
        lines.append(
            {
                "id": ids("p", f"{source}-{target}"),
                "type": "line",
                "kind": "process",
                "medium": "process",
                "start": {"element": a["id"], "port": out_port["id"] if out_port else ""},
                "end": {"element": b["id"], "port": in_port["id"] if in_port else ""},
                "points": [[round(px, 1), round(py, 1)] for px, py in points],
                "arrow": "end",
            }
        )

    if not equipment and not loops:
        elements.append(
            {
                "id": ids("note", "empty"),
                "type": "text",
                "x": MARGIN,
                "y": top,
                "text": t("No equipment or loop under {unit} in PlantCraft yet.", unit=unit_name),
                "size": 14,
            }
        )
        notes.append(t("{unit} has no equipment or loop under it.", unit=unit_name))
    if left_out:
        notes.append(
            t(
                "{count} assets were left out: a process display holds at most {limit} elements.",
                count=left_out,
                limit=PAGE_ELEMENTS,
            )
        )
    if not edges and len(equipment) > 1:
        notes.append(
            t(
                "No feeds or downstream-of relation joins the equipment of {unit}: the lines "
                "are left for you to draw.",
                unit=unit_name,
            )
        )

    used_columns = max(wrap if isolated else graph_columns, 1)
    width = MARGIN * 2 + max(used_columns * CELL_W, per_row * LOOP_W if placed_free else 0)
    height = loop_top + free_rows * LOOP_H + MARGIN
    every = elements + lines
    biggest = max(width, height)
    if width > MAX_SIZE or height > MAX_SIZE:
        factor = MAX_SIZE / biggest
        _scale(every, factor)
        width, height = int(width * factor), int(height * factor)
    payload = {
        "name": _text(name or t("{unit} process display", unit=unit_name)),
        "description": _text(
            t("Drawn from the assets of {unit} in PlantCraft.", unit=unit_name), 400
        ),
        "width": min(MAX_SIZE, max(MIN_SIZE, DEFAULT_WIDTH, _snap_up(width))),
        "height": min(MAX_SIZE, max(MIN_SIZE, DEFAULT_HEIGHT, _snap_up(height))),
        "grid": GRID,
        "elements": every,
    }
    return DiagramPayload.model_validate(payload).stored(), notes


def unit_diagrams(
    assets: list[dict[str, Any]], units: list[str], *, library: Iterable[dict[str, Any]] = ()
) -> list[dict[str, Any]]:
    """One diagram for each of ``units`` that has equipment or loops under it, in that order:
    a new plant's first diagrams (``[[contributes.start]]``). An asset is drawn on the diagram
    of the nearest unit above it only."""

    symbols = list(library)
    wanted = list(dict.fromkeys(unit for unit in units if isinstance(unit, str)))
    out = []
    for unit_id in wanted:
        drawn = draw_unit(assets, unit_id, library=symbols, stop=wanted)
        if drawn is None:
            continue
        diagram, _notes = drawn
        if any(element["type"] == "symbol" for element in diagram["elements"]):
            out.append(diagram)
    return out


# The kinds a plant's display gives a page each (the frontend's StartDialog offers the same).
UNIT_KINDS = frozenset({"area", "unit", "section", "system", "train"})


def plant_units(assets: list[dict[str, Any]]) -> list[str]:
    """The units of the plant, by name: the assets of a unit kind, else those that hold others."""

    named = sorted(
        (asset for asset in assets if isinstance(asset, dict) and asset.get("id")),
        key=lambda asset: (_text(asset.get("name") or asset["id"]).lower(), asset["id"]),
    )
    units = [asset["id"] for asset in named if str(asset.get("kind") or "").lower() in UNIT_KINDS]
    if units:
        return units
    parents = {_parent(asset) for asset in named}
    return [asset["id"] for asset in named if asset["id"] in parents]


# The plant's overview page (Level 1 of ISA-101's display hierarchy): a block per unit.
OVERVIEW_PAGE = "overview"
TILE_W, TILE_H = 320, 220
TILE_COLUMNS = 4
TILE_BUBBLES = 8
TILE_BUBBLE = 36


def _overview(
    assets: list[dict[str, Any]], units: list[tuple[str, str, str]], stop: list[str]
) -> tuple[list[dict[str, Any]], int, int]:
    """The overview page's elements, width and height: for each ``(unit_id, name, page)`` a
    block that opens the unit's page, its name, how much is under it, and its first control
    loops as bubbles coloured by Analytics' loop health (each opens its loop)."""

    ids = _Ids()
    elements: list[dict[str, Any]] = [
        {
            "id": ids("title", "overview"),
            "type": "text",
            "x": MARGIN,
            "y": MARGIN,
            "text": t("Plant overview: open a unit for its process display"),
            "size": 18,
            "bold": True,
            "page": OVERVIEW_PAGE,
        }
    ]
    top = MARGIN + TITLE_HEIGHT
    for index, (unit_id, name, page) in enumerate(units):
        x = MARGIN + (index % TILE_COLUMNS) * TILE_W
        y = top + (index // TILE_COLUMNS) * TILE_H
        opens = {"kind": "page", "target": page}
        under = _descendants(assets, unit_id, frozenset(stop) - {unit_id})
        loops = [asset for asset in under if _is_loop(_words(asset))]
        equipment = [
            asset
            for asset in under
            if not any(word in STRUCTURE for word in _words(asset)[:1])
            and "result" not in _words(asset)[:1]
            and not _is_loop(_words(asset))
            and not _is_instrument(_words(asset))
        ]
        elements += [
            {
                "id": ids("unit", unit_id),
                "type": "symbol",
                "symbol": "shape.panel",
                "x": x,
                "y": y,
                "w": TILE_W - 20,
                "h": TILE_H - 20,
                "label": "",
                "label_position": "none",
                "link": opens,
                "page": OVERVIEW_PAGE,
            },
            {
                "id": ids("name", unit_id),
                "type": "text",
                "x": x + 14,
                "y": y + 30,
                "text": _text(name, 30),
                "size": 16,
                "bold": True,
                "link": opens,
                "page": OVERVIEW_PAGE,
            },
            {
                "id": ids("count", unit_id),
                "type": "text",
                "x": x + 14,
                "y": y + 50,
                "text": t(
                    "{equipment} equipment · {loops} control loops",
                    equipment=len(equipment),
                    loops=len(loops),
                ),
                "size": 12,
                "link": opens,
                "page": OVERVIEW_PAGE,
            },
        ]
        per_row = TILE_BUBBLES // 2
        for at, loop in enumerate(loops[:TILE_BUBBLES]):
            elements.append(
                {
                    "id": ids("loop", loop["id"]),
                    "type": "symbol",
                    "symbol": "instrument.bubble",
                    "x": x + 24 + (at % per_row) * 70,
                    "y": y + 68 + (at // per_row) * 62,
                    "w": TILE_BUBBLE,
                    "h": TILE_BUBBLE,
                    "label": _text(loop.get("name") or loop["id"], 10),
                    "label_position": "below",
                    "asset_id": loop["id"],
                    "state": {"item": {"asset_id": loop["id"], "result": LOOP_HEALTH}},
                    "page": OVERVIEW_PAGE,
                }
            )
        if len(loops) > TILE_BUBBLES:
            elements.append(
                {
                    "id": ids("more", unit_id),
                    "type": "text",
                    "x": x + TILE_W - 34,
                    "y": y + 50,
                    "text": t("+{count} more", count=len(loops) - TILE_BUBBLES),
                    "size": 11,
                    "align": "end",
                    "link": opens,
                    "page": OVERVIEW_PAGE,
                }
            )
    columns = min(len(units), TILE_COLUMNS)
    rows = math.ceil(len(units) / TILE_COLUMNS)
    return elements, MARGIN * 2 + columns * TILE_W, top + rows * TILE_H + MARGIN


def plant_display(
    assets: list[dict[str, Any]],
    units: list[str],
    *,
    name: str,
    library: Iterable[dict[str, Any]] = (),
) -> dict[str, Any] | None:
    """One process display for the whole plant: a page for each of ``units`` drawn from its
    assets (``unit_diagrams``), on one canvas as large as the largest page; None when no unit
    has equipment. Each page's elements carry its id first, so ids never clash."""

    symbols = list(library)
    names = {item.get("id"): item.get("name") or item.get("id") for item in assets}
    wanted = list(dict.fromkeys(unit for unit in units if isinstance(unit, str)))
    drawn: list[tuple[str, str, dict[str, Any]]] = []
    for unit_id in wanted:
        found = draw_unit(assets, unit_id, library=symbols, stop=wanted)
        if found is not None and any(item["type"] == "symbol" for item in found[0]["elements"]):
            drawn.append((unit_id, str(names.get(unit_id) or unit_id), found[0]))
    if not drawn:
        return None
    # Two units or more: an overview page first (Level 1), each unit's page a way back to it.
    overview = len(drawn) > 1
    pages: list[dict[str, Any]] = []
    elements: list[dict[str, Any]] = []
    sizes = [(diagram["width"], diagram["height"]) for _, _, diagram in drawn]
    if overview:
        tiles = [(unit_id, unit, f"p{n}") for n, (unit_id, unit, _) in enumerate(drawn, start=1)]
        found, width, height = _overview(assets, tiles, wanted)
        pages.append({"id": OVERVIEW_PAGE, "name": t("Overview")})
        elements += found
        sizes.append((width, height))
    for number, (_unit_id, unit, diagram) in enumerate(drawn, start=1):
        page = f"p{number}"
        pages.append({"id": page, "name": _text(unit, 60)})
        for element in diagram["elements"]:
            moved = {**element, "id": f"{page}-{element['id']}"[:40], "page": page}
            for end in ("start", "end"):
                if moved.get(end):
                    moved[end] = {**moved[end], "element": f"{page}-{moved[end]['element']}"[:40]}
            elements.append(moved)
        if overview:
            elements.append(
                {
                    "id": f"{page}-back"[:40],
                    "type": "text",
                    "x": MARGIN,
                    "y": 20,
                    "text": t("‹ Plant overview"),
                    "size": 12,
                    "link": {"kind": "page", "target": OVERVIEW_PAGE},
                    "page": page,
                }
            )
    payload = {
        "name": _text(name),
        "description": _text(
            t("Drawn from the plant's assets in PlantCraft: an overview and a page per unit.")
            if overview
            else t("Drawn from the plant's assets in PlantCraft, a page per unit."),
            400,
        ),
        "width": min(MAX_SIZE, max(width for width, _ in sizes)),
        "height": min(MAX_SIZE, max(height for _, height in sizes)),
        "grid": GRID,
        "pages": pages,
        "elements": elements,
    }
    return DiagramPayload.model_validate(payload).stored()
