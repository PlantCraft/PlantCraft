"""A model drawn as a block diagram: read from its Modelica text and written back to it.

A diagram model is a class whose elements are blocks of the libraries (one declaration each,
its parameters as modifiers, its place as a ``Placement``) wired by ``connect()`` from an
output to an input. The editor's diagram (``@plantcraft/ui`` ``Diagram``) is read from that
text, and a changed diagram is written back as the few edits that turn one into the other, so
whatever else the text holds (comments, annotations, equations written by hand) is kept.

Coordinates: the editor places a node's top-left corner in pixels (y down); Modelica places a
component's extent in its own units (y up). A node at (x, y) is a component centered at
(x / SCALE, -y / SCALE), 20 units wide.

The simulation settings live in the class's annotation, as the Modelica specification and
OpenModelica read them::

    annotation(experiment(StartTime=0, StopTime=3600, Interval=1, Tolerance=1e-06),
      __OpenModelica_simulationFlags(s="dassl"));
"""

from __future__ import annotations

import math
import re
from typing import Any

from modelcraft.modelica import edit
from modelcraft.modelica.declarations import (
    ClassElements,
    class_elements,
    literal,
    modelica_value,
    split_arguments,
)
from modelcraft.modelica.edit import EditError
from modelcraft.modelica.source import find, tokens

SCALE = 3.0
VERSION = 2  # the suite's diagram format (@plantcraft/ui DIAGRAM_VERSION)
HALF = 10.0
VARIABLE_STEP = ("dassl", "ida", "cvode")
FIXED_STEP = ("euler", "heun", "rungekutta", "trapezoid", "impeuler")
SOLVERS = VARIABLE_STEP + FIXED_STEP
DEFAULT_SETTINGS = {
    "start": 0.0,
    "stop": 10.0,
    "interval": 0.01,
    "tolerance": 1e-6,
    "solver": "dassl",
}
MAX_INTERVALS = 200_000


# Simulation settings -----------------------------------------------------------------------


def _annotation_entries(annotation: str) -> dict[str, str]:
    """``experiment(...)``, ``Diagram(...)``... of a class annotation, by name, as written."""

    found: dict[str, str] = {}
    for part in split_arguments(annotation or ""):
        match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)", part)
        if match:
            found[match.group(1)] = part.strip()
    return found


def _arguments(entry: str) -> dict[str, str]:
    inner = entry[entry.find("(") + 1 : entry.rfind(")")] if "(" in entry else ""
    found = {}
    for part in split_arguments(inner):
        key, sep, value = part.partition("=")
        if sep:
            found[key.strip()] = value.strip()
    return found


def settings(found: ClassElements) -> dict[str, Any]:
    """The class's simulation settings, with the defaults for what it does not say."""

    entries = _annotation_entries(found.annotation)
    values = dict(DEFAULT_SETTINGS)
    experiment = _arguments(entries.get("experiment", ""))
    for key, name in (
        ("start", "StartTime"),
        ("stop", "StopTime"),
        ("interval", "Interval"),
        ("tolerance", "Tolerance"),
    ):
        ok, value = literal(experiment.get(name))
        if ok and isinstance(value, (int, float)) and not isinstance(value, bool):
            values[key] = float(value)
    flags = _arguments(entries.get("__OpenModelica_simulationFlags", ""))
    solver = flags.get("s", "").strip('"')
    if solver in SOLVERS:
        values["solver"] = solver
    return values


def check_settings(values: dict[str, Any]) -> dict[str, Any]:
    """The settings, checked: an ``EditError`` says what a person must change."""

    try:
        start, stop = float(values["start"]), float(values["stop"])
        interval, tolerance = float(values["interval"]), float(values["tolerance"])
    except (KeyError, TypeError, ValueError) as exc:
        raise EditError("Start, stop, step and tolerance are numbers.") from exc
    if not all(math.isfinite(v) for v in (start, stop, interval, tolerance)):
        raise EditError("Start, stop, step and tolerance are finite numbers.")
    if stop <= start:
        raise EditError("The stop time must come after the start time.")
    if interval <= 0:
        raise EditError("The step must be greater than zero.")
    if (stop - start) / interval > MAX_INTERVALS:
        raise EditError(f"Up to {MAX_INTERVALS:,} steps: make the step larger or the time shorter.")
    if not 1e-14 <= tolerance <= 0.1:
        raise EditError("The tolerance is between 1e-14 and 0.1.")
    solver = values.get("solver", "dassl")
    if solver not in SOLVERS:
        raise EditError(f"The solver is one of {', '.join(SOLVERS)}.")
    return {
        "start": start,
        "stop": stop,
        "interval": interval,
        "tolerance": tolerance,
        "solver": solver,
    }


def run_options(values: dict[str, Any]) -> dict[str, Any]:
    """The settings as the runner's options (start, stop, intervals, tolerance, method)."""

    checked = check_settings(values)
    return {
        "start": checked["start"],
        "stop": checked["stop"],
        "intervals": max(1, round((checked["stop"] - checked["start"]) / checked["interval"])),
        "tolerance": checked["tolerance"],
        "method": checked["solver"],
    }


def _class_annotation_span(text: str, cls_name: str) -> tuple[int, int] | None:
    """Offsets of the inside of the class's own ``annotation( ... )`` (None without one)."""

    cls = find(text, cls_name)
    if cls is None:
        raise EditError(f"Class {cls_name} is not in this file.")
    items = tokens(text)
    for statement in edit._statements(items, edit._own(items, cls)):
        if items[statement[0]].text == "annotation":
            open_index = statement[0] + 1
            close = edit._matching(items, open_index)
            return items[open_index].end, items[close].start
    return None


def set_settings(text: str, cls_name: str, values: dict[str, Any]) -> str:
    """Write the settings into the class annotation (its other entries are kept)."""

    checked = check_settings(values)
    experiment = "experiment(StartTime=%s, StopTime=%s, Interval=%s, Tolerance=%s)" % (
        modelica_value(checked["start"]),
        modelica_value(checked["stop"]),
        modelica_value(checked["interval"]),
        modelica_value(checked["tolerance"]),
    )
    flags = f'__OpenModelica_simulationFlags(s="{checked["solver"]}")'
    span = _class_annotation_span(text, cls_name)
    if span is None:
        cls = find(text, cls_name)
        items = tokens(text)
        end = items[cls.body_end].start
        line_start = text.rfind("\n", 0, end) + 1
        indent = text[line_start:end] if not text[line_start:end].strip() else ""
        addition = f"{indent}  annotation({experiment},\n{indent}    {flags});\n"
        if text[line_start:end].strip():
            return text[:end] + "\n" + addition + indent + text[end:]
        return text[:line_start] + addition + text[line_start:]
    start, end = span
    entries = split_arguments(text[start:end])
    kept = [
        entry
        for entry in entries
        if not re.match(r"^\s*(experiment|__OpenModelica_simulationFlags)\b", entry)
    ]
    body = ", ".join([*kept, experiment, flags])
    return text[:start] + body + text[end:]


# Reading the diagram -----------------------------------------------------------------------


def _center(annotation: str) -> tuple[float, float] | None:
    match = re.search(r"Placement\s*\(\s*transformation\s*\(([^;]*)", annotation or "")
    if not match:
        return None
    inner = match.group(1)
    extent = re.search(
        r"extent\s*=\s*\{\s*\{\s*([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)\s*\}\s*,"
        r"\s*\{\s*([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)\s*\}\s*\}",
        inner,
    )
    if not extent:
        return None
    x1, y1, x2, y2 = (float(v) for v in extent.groups())
    origin = re.search(r"origin\s*=\s*\{\s*([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)\s*\}", inner)
    ox, oy = (float(v) for v in origin.groups()) if origin else (0.0, 0.0)
    return ox + (x1 + x2) / 2, oy + (y1 + y2) / 2


def _position(center: tuple[float, float] | None, index: int) -> tuple[float, float]:
    if center is None:  # placed in a row, the way a person can then arrange them
        return 60.0 + 260.0 * (index % 5), 60.0 + 180.0 * (index // 5)
    return round(center[0] * SCALE, 1) + 0.0, round(-center[1] * SCALE, 1) + 0.0


def _ports(spec: dict[str, Any], kind: str) -> set[str]:
    return {port["port"] for port in spec.get(kind, [])}


def read(text: str, cls_name: str, catalog: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """``{"diagram", "settings", "problems", "editable"}`` of a class.

    A class the diagram can hold whole is ``editable``; any other (equations written by
    hand, components that are not blocks of the catalog, connections it cannot place) is
    shown as far as it can be, with its problems, and edited in the code.
    """

    found = class_elements(text, cls_name)
    if found is None:
        raise EditError(f"Class {cls_name} is not in this file.")
    problems: list[str] = []
    nodes: list[dict[str, Any]] = []
    specs: dict[str, dict[str, Any]] = {}
    for declaration in found.declarations:
        spec = catalog.get(declaration.type)
        if spec is None or declaration.prefixes or declaration.dims:
            problems.append(
                f"{declaration.name} ({declaration.type}) is not a block of the libraries."
            )
            continue
        specs[declaration.name] = spec
        known = {item["name"] for item in spec.get("parameters", [])}
        parameters: dict[str, Any] = {}
        for key, value in declaration.modifiers.items():
            if key not in known:
                problems.append(f"{declaration.name}.{key} is not a parameter of {spec['name']}.")
                continue
            ok, parsed = literal(value)
            parameters[key] = parsed if ok else value
        x, y = _position(_center(declaration.annotation), len(nodes))
        nodes.append(
            {
                "id": declaration.name,
                "block": declaration.type,
                "parameters": parameters,
                "label": declaration.comment,
                "x": x,
                "y": y,
            }
        )
    edges: list[dict[str, Any]] = []
    for left, right in found.connections:
        edge = _edge(left, right, specs)
        if edge is None:
            problems.append(f"connect({left}, {right}) does not join an output to an input.")
            continue
        edges.append(edge)
    if found.equations:
        problems.append("The class has equations of its own: edit it in the code.")
    if found.extends:
        problems.append("The class extends another class: edit it in the code.")
    if found.unread:
        problems.append("The class has declarations the diagram cannot read: edit it in the code.")
    return {
        "diagram": {"version": VERSION, "nodes": nodes, "edges": edges},
        "settings": settings(found),
        "problems": problems,
        "editable": not problems,
    }


def _edge(left: str, right: str, specs: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    def split(ref: str) -> tuple[str, str] | None:
        parts = ref.split(".")
        return (parts[0], parts[1]) if len(parts) == 2 and "[" not in ref else None

    a, b = split(left), split(right)
    if a is None or b is None or a[0] not in specs or b[0] not in specs:
        return None
    for source, target in ((a, b), (b, a)):
        if source[1] in _ports(specs[source[0]], "outputs") and target[1] in _ports(
            specs[target[0]], "inputs"
        ):
            return {
                "source": source[0],
                "source_port": source[1],
                "target": target[0],
                "target_port": target[1],
            }
    return None


# Writing the diagram -----------------------------------------------------------------------

NAME = re.compile(r"^[a-z][A-Za-z0-9_]{0,59}$")
KEYWORDS = {
    "algorithm", "and", "annotation", "block", "break", "class", "connect", "connector",
    "constant", "constrainedby", "der", "discrete", "each", "else", "elseif", "elsewhen",
    "encapsulated", "end", "enumeration", "equation", "expandable", "extends", "external",
    "false", "final", "flow", "for", "function", "if", "import", "impure", "in", "initial",
    "inner", "input", "loop", "model", "not", "operator", "or", "outer", "output", "package",
    "parameter", "partial", "protected", "public", "pure", "record", "redeclare",
    "replaceable", "return", "stream", "then", "true", "type", "when", "while", "within",
    "time", "delay", "sin", "cos", "exp", "log", "abs", "max", "min", "sum", "sign", "sqrt",
}  # fmt: skip


def _extent(node: dict[str, Any]) -> tuple[tuple[float, float], tuple[float, float]]:
    cx, cy = float(node["x"]) / SCALE, -float(node["y"]) / SCALE
    return ((round(cx - HALF, 1), round(cy - HALF, 1)), (round(cx + HALF, 1), round(cy + HALF, 1)))


def _value(spec: dict[str, Any], name: str, value: Any) -> str | None:
    """The modifier to write for a parameter (None: leave the block's default)."""

    parameter = next((p for p in spec.get("parameters", []) if p["name"] == name), None)
    if parameter is None:
        raise EditError(f"{name} is not a parameter of {spec['name']}.")
    if value is None or value == "" or value == parameter.get("default"):
        return None
    try:
        return modelica_value(value)
    except ValueError as exc:
        raise EditError(f"{spec['name']}: {name} is not a value Models can write.") from exc


def _set_comment(text: str, cls_name: str, name: str, comment: str) -> str:
    """Set (or remove) the component's description string."""

    comment = " ".join((comment or "").split())[:200].replace("\\", "").replace('"', "'")
    items, statement, _ = edit._declaration(text, cls_name, name)
    strings = [i for i in statement if items[i].kind == "string"]
    annotation = next((i for i in statement if items[i].text == "annotation"), None)
    depth = 0
    own = []
    for i in statement:  # strings at the top level only (not inside modifiers)
        if items[i].text in ("(", "{", "["):
            depth += 1
        elif items[i].text in (")", "}", "]"):
            depth -= 1
        elif depth == 0 and i in strings and (annotation is None or i < annotation):
            own.append(i)
    if own:
        start, end = items[own[0]].start, items[own[-1]].end
        if not comment:
            while start > 0 and text[start - 1] == " ":
                start -= 1
            return text[:start] + text[end:]
        return text[:start] + f'"{comment}"' + text[end:]
    if not comment:
        return text
    at = items[annotation].start if annotation is not None else items[statement[-1]].start
    before = text[:at].rstrip(" ")
    after = text[at:]
    return f'{before} "{comment}"' + (" " if annotation is not None else "") + after


def _points(source: dict[str, Any], target: dict[str, Any]) -> list[list[float]]:
    (_, _), (sx2, sy2) = _extent(source)
    (tx1, ty1), (_, _) = _extent(target)
    return [[sx2, round(sy2 - HALF, 1)], [tx1, round(ty1 + HALF, 1)]]


def check_diagram(diagram: dict[str, Any], catalog: dict[str, dict[str, Any]]) -> None:
    """A diagram the text can hold: known blocks, names Modelica accepts, wires from an output
    to an input, at most one wire into each input."""

    nodes = diagram.get("nodes") or []
    if len(nodes) > 500:
        raise EditError("Up to 500 blocks in a model.")
    ids: dict[str, dict[str, Any]] = {}
    for node in nodes:
        name = node.get("id", "")
        if not NAME.match(name or "") or name in KEYWORDS:
            raise EditError(
                f"{name!r} cannot name a block: use letters, digits and _, starting with a "
                "lower-case letter (and not a Modelica word)."
            )
        if name in ids:
            raise EditError(f"Two blocks are named {name}.")
        if node.get("block") not in catalog:
            raise EditError(f"{node.get('block')} is not a block of the libraries.")
        for key in ("x", "y"):
            value = node.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or abs(value) > 1e5:
                raise EditError("A block's place is two numbers.")
        ids[name] = node
    fed: set[tuple[str, str]] = set()
    for wire in diagram.get("edges") or []:
        source, target = ids.get(wire.get("source")), ids.get(wire.get("target"))
        if source is None or target is None:
            raise EditError("A wire joins two blocks of the model.")
        if wire.get("source_port") not in _ports(catalog[source["block"]], "outputs"):
            raise EditError(f"{wire.get('source')} has no output {wire.get('source_port')}.")
        if wire.get("target_port") not in _ports(catalog[target["block"]], "inputs"):
            raise EditError(f"{wire.get('target')} has no input {wire.get('target_port')}.")
        key = (wire["target"], wire["target_port"])
        if key in fed:
            raise EditError(f"{wire['target']}.{wire['target_port']} has two wires: keep one.")
        fed.add(key)


def write(
    text: str,
    cls_name: str,
    diagram: dict[str, Any],
    catalog: dict[str, dict[str, Any]],
) -> str:
    """The text with the class changed to hold ``diagram`` (only what changed is rewritten)."""

    check_diagram(diagram, catalog)
    current = read(text, cls_name, catalog)
    if not current["editable"]:
        raise EditError(
            "This model has text the diagram cannot hold: edit it in the code. "
            + " ".join(current["problems"][:3])
        )
    old_nodes = {node["id"]: node for node in current["diagram"]["nodes"]}
    new_nodes = {node["id"]: node for node in diagram.get("nodes") or []}

    def key(wire: dict[str, Any]) -> tuple[str, str, str, str]:
        return (wire["source"], wire["source_port"], wire["target"], wire["target_port"])

    old_edges = {key(w) for w in current["diagram"]["edges"]}
    new_edges = {key(w) for w in diagram.get("edges") or []}
    for edge in sorted(old_edges - new_edges):
        if edge[0] in new_nodes and edge[2] in new_nodes:
            text = edit.delete_connection(
                text, cls_name, f"{edge[0]}.{edge[1]}", f"{edge[2]}.{edge[3]}"
            )
    for name in sorted(set(old_nodes) - set(new_nodes)):
        text = edit.delete_component(text, cls_name, name)
    for name, node in new_nodes.items():
        spec = catalog[node["block"]]
        old = old_nodes.get(name)
        if old is not None and old["block"] != node["block"]:
            text = edit.delete_component(text, cls_name, name)
            old = None
            old_edges = {e for e in old_edges if name not in (e[0], e[2])}
        if old is None:
            text = edit.add_component(text, cls_name, node["block"], name, _extent(node))
            before: dict[str, Any] = {}
        else:
            before = old["parameters"]
            if (round(old["x"]), round(old["y"])) != (round(node["x"]), round(node["y"])):
                text = edit.move(text, cls_name, name, _extent(node))
        after = node.get("parameters") or {}
        changes: dict[str, str | None] = {}
        for parameter in sorted(set(before) | set(after)):
            value = _value(spec, parameter, after.get(parameter)) if parameter in after else None
            previous = before.get(parameter)
            was = None if previous is None else modelica_value(previous)
            if value != was:
                changes[parameter] = value
        if changes:
            text = edit.set_modifiers(text, cls_name, name, changes)
        label = " ".join((node.get("label") or "").split())
        if label != (old or {}).get("label", ""):
            text = _set_comment(text, cls_name, name, label)
    for edge in sorted(new_edges - old_edges):
        source, target = new_nodes[edge[0]], new_nodes[edge[2]]
        text = edit.connect(
            text,
            cls_name,
            f"{edge[0]}.{edge[1]}",
            f"{edge[2]}.{edge[3]}",
            _points(source, target),
        )
    return text


def new_model(name: str, description: str, *, within: str = "") -> str:
    """The text of an empty diagram model with the default settings."""

    head = f"within {within};\n" if within else ""
    description = " ".join(description.split()).replace("\\", "").replace('"', "'")
    comment = f' "{description}"' if description else ""
    text = f"{head}model {name}{comment}\nequation\nend {name};\n"
    return set_settings(text, f"{within}.{name}" if within else name, DEFAULT_SETTINGS)
