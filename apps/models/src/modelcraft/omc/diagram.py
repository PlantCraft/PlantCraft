"""A class's diagram and icon, reduced from omc's ``getModelInstance`` JSON for the browser.

``getModelInstance`` answers the whole instance tree (hundreds of kilobytes for a small model).
The browser needs much less: the class's own diagram graphics, each component with its
placement, its icon and its connectors, the connections with their lines, and each
component's parameters. Graphics follow the Modelica specification's annotations (section 18,
Graphical objects), positional as omc writes them; anything that is not a literal value (an
expression omc did not evaluate) falls back to the specification's default.
"""

from __future__ import annotations

from typing import Any

DEFAULT_EXTENT = [[-100.0, -100.0], [100.0, 100.0]]
CONNECTORS = {"connector", "expandable connector"}
MAX_COMPONENTS = 600
MAX_GRAPHICS = 400
MAX_PARAMETERS = 80
MAX_DEPTH = 12


def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _point(value: Any, default: list[float] | None = None) -> list[float]:
    if isinstance(value, list) and len(value) == 2:
        return [_num(value[0]), _num(value[1])]
    return list(default or [0.0, 0.0])


def _points(value: Any) -> list[list[float]]:
    if not isinstance(value, list):
        return []
    return [_point(item) for item in value[:2000] if isinstance(item, list)]


def _extent(value: Any, default: list[list[float]] | None = None) -> list[list[float]]:
    if isinstance(value, list) and len(value) == 2:
        return [_point(value[0]), _point(value[1])]
    return [list(p) for p in (default or DEFAULT_EXTENT)]


def _color(value: Any, default: list[int] | None = None) -> list[int] | None:
    if (
        isinstance(value, list)
        and len(value) == 3
        and all(isinstance(v, (int, float)) for v in value)
    ):
        return [max(0, min(255, int(v))) for v in value]
    return default


def _enum(value: Any, default: str) -> str:
    if isinstance(value, dict) and isinstance(value.get("name"), str):
        return value["name"].rpartition(".")[2]
    return default


def _arg(elements: list, index: int) -> Any:
    return elements[index] if index < len(elements) else None


def _graphic(item: Any) -> dict[str, Any] | None:
    """One graphical primitive (Line, Polygon, Rectangle, Ellipse, Text, Bitmap)."""

    if not isinstance(item, dict) or item.get("$kind") != "record":
        return None
    kind = item.get("name")
    e = item.get("elements")
    if not isinstance(e, list):
        return None
    if _arg(e, 0) is False:
        return None
    base = {
        "kind": kind,
        "origin": _point(_arg(e, 1)),
        "rotation": _num(_arg(e, 2)),
    }
    if kind == "Line":
        arrows = _arg(e, 7) if isinstance(_arg(e, 7), list) else []
        return {
            **base,
            "points": _points(_arg(e, 3)),
            "color": _color(_arg(e, 4), [0, 0, 0]),
            "pattern": _enum(_arg(e, 5), "Solid"),
            "thickness": _num(_arg(e, 6), 0.25),
            "arrow": [
                _enum(arrows[0], "None") if arrows else "None",
                _enum(arrows[1], "None") if len(arrows) > 1 else "None",
            ],
            "arrowSize": _num(_arg(e, 8), 3.0),
            "smooth": _enum(_arg(e, 9), "None"),
        }
    if kind not in ("Polygon", "Rectangle", "Ellipse", "Text", "Bitmap"):
        return None
    if kind == "Bitmap":
        return {**base, "extent": _extent(_arg(e, 3))}
    filled = {
        **base,
        "lineColor": _color(_arg(e, 3), [0, 0, 0]),
        "fillColor": _color(_arg(e, 4), [0, 0, 0]),
        "pattern": _enum(_arg(e, 5), "Solid"),
        "fillPattern": _enum(_arg(e, 6), "None"),
        "lineThickness": _num(_arg(e, 7), 0.25),
    }
    if kind == "Polygon":
        return {**filled, "points": _points(_arg(e, 8)), "smooth": _enum(_arg(e, 9), "None")}
    if kind == "Rectangle":
        return {**filled, "extent": _extent(_arg(e, 9)), "radius": _num(_arg(e, 10))}
    if kind == "Ellipse":
        return {
            **filled,
            "extent": _extent(_arg(e, 8)),
            "startAngle": _num(_arg(e, 9), 0.0),
            "endAngle": _num(_arg(e, 10), 360.0),
        }
    text = _arg(e, 9)
    return {
        **filled,
        "extent": _extent(_arg(e, 8)),
        "text": text if isinstance(text, str) else "",
        "fontSize": _num(_arg(e, 10), 0.0),
        "textColor": _color(_arg(e, 11), None),
        "horizontalAlignment": _enum(_arg(e, 14), "Center"),
    }


def _layer(cls: dict[str, Any], layer: str) -> dict[str, Any]:
    annotation = cls.get("annotation") if isinstance(cls.get("annotation"), dict) else {}
    found = annotation.get(layer) if isinstance(annotation.get(layer), dict) else {}
    system = (
        found.get("coordinateSystem") if isinstance(found.get("coordinateSystem"), dict) else {}
    )
    graphics = found.get("graphics") if isinstance(found.get("graphics"), list) else []
    return {
        "extent": _extent(system.get("extent")) if system.get("extent") is not None else None,
        "graphics": [g for g in (_graphic(item) for item in graphics[:MAX_GRAPHICS]) if g],
    }


def _bases(cls: dict[str, Any]) -> list[dict[str, Any]]:
    elements = cls.get("elements") if isinstance(cls.get("elements"), list) else []
    return [
        item["baseClass"]
        for item in elements
        if isinstance(item, dict)
        and item.get("$kind") == "extends"
        and isinstance(item.get("baseClass"), dict)
    ]


def layer(cls: dict[str, Any], name: str, depth: int = 0) -> dict[str, Any]:
    """A class's Icon or Diagram layer with what its base classes draw first."""

    own = _layer(cls, name)
    graphics: list[dict[str, Any]] = []
    extent = own["extent"]
    if depth < MAX_DEPTH:
        for base in _bases(cls):
            inherited = layer(base, name, depth + 1)
            graphics.extend(inherited["graphics"])
            extent = extent or inherited["extent"]
    graphics.extend(own["graphics"])
    return {
        "extent": extent or [list(p) for p in DEFAULT_EXTENT],
        "graphics": graphics[:MAX_GRAPHICS],
    }


def _components(
    cls: dict[str, Any], depth: int = 0, inherited: bool = False
) -> list[tuple[dict, bool]]:
    """The class's components, those of its base classes first (``inherited``)."""

    found: list[tuple[dict, bool]] = []
    if depth < MAX_DEPTH:
        for base in _bases(cls):
            found.extend(_components(base, depth + 1, True))
    elements = cls.get("elements") if isinstance(cls.get("elements"), list) else []
    for item in elements:
        if isinstance(item, dict) and item.get("$kind") == "component":
            found.append((item, inherited))
    return found


def _type_of(component: dict[str, Any]) -> dict[str, Any]:
    kind = component.get("type")
    return kind if isinstance(kind, dict) else {"name": kind if isinstance(kind, str) else ""}


def _placement(component: dict[str, Any], icon: bool = False) -> dict[str, Any] | None:
    annotation = (
        component.get("annotation") if isinstance(component.get("annotation"), dict) else {}
    )
    placement = (
        annotation.get("Placement") if isinstance(annotation.get("Placement"), dict) else None
    )
    if placement is None:
        return None
    if placement.get("visible") is False:
        return None
    chosen = None
    if icon and isinstance(placement.get("iconTransformation"), dict):
        chosen = placement["iconTransformation"]
    elif isinstance(placement.get("transformation"), dict):
        chosen = placement["transformation"]
    if chosen is None:
        return None
    return {
        "extent": _extent(chosen.get("extent"), [[-10, -10], [10, 10]]),
        "origin": _point(chosen.get("origin")),
        "rotation": _num(chosen.get("rotation")),
    }


def _value_text(value: Any) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    if isinstance(value, str):
        return value
    if (
        isinstance(value, dict)
        and value.get("$kind") == "enum"
        and isinstance(value.get("name"), str)
    ):
        return value["name"].rpartition(".")[2]
    return None


def _modifier_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and isinstance(value.get("$value"), str):
        return value["$value"]
    return None


def parameters(
    cls: dict[str, Any], modifiers: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """The class's parameters (public, base classes included) with what the component sets."""

    modifiers = modifiers if isinstance(modifiers, dict) else {}
    found = []
    for item, _inherited in _components(cls):
        prefixes = item.get("prefixes") if isinstance(item.get("prefixes"), dict) else {}
        if prefixes.get("variability") != "parameter" or prefixes.get("public") is False:
            continue
        own = item.get("modifiers")
        value = item.get("value") if isinstance(item.get("value"), dict) else {}
        annotation = item.get("annotation") if isinstance(item.get("annotation"), dict) else {}
        dialog = annotation.get("Dialog") if isinstance(annotation.get("Dialog"), dict) else {}
        unit = own.get("unit") if isinstance(own, dict) else None
        found.append(
            {
                "name": item.get("name", ""),
                "type": _type_of(item).get("name", ""),
                "comment": item.get("comment", "") if isinstance(item.get("comment"), str) else "",
                "default": _modifier_text(own) if own is not None else None,
                "value": _value_text(value.get("value", value.get("binding"))),
                "set": _modifier_text(modifiers.get(item.get("name"))),
                "unit": unit.strip('"') if isinstance(unit, str) else "",
                "group": dialog.get("group") if isinstance(dialog.get("group"), str) else "",
                "tab": dialog.get("tab") if isinstance(dialog.get("tab"), str) else "",
            }
        )
        if len(found) >= MAX_PARAMETERS:
            break
    return found


def _connectors(kind: dict[str, Any]) -> list[dict[str, Any]]:
    found = []
    for item, _inherited in _components(kind):
        if item.get("condition") is False:
            continue
        connector_type = _type_of(item)
        if connector_type.get("restriction") not in CONNECTORS:
            continue
        placement = _placement(item, icon=True)
        if placement is None:
            continue
        prefixes = item.get("prefixes") if isinstance(item.get("prefixes"), dict) else {}
        found.append(
            {
                "name": item.get("name", ""),
                "type": connector_type.get("name", ""),
                "placement": placement,
                "icon": layer(connector_type, "Icon"),
                "direction": prefixes.get("direction") or "",
            }
        )
    return found


def _cref(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    parts = value.get("parts") if isinstance(value.get("parts"), list) else []
    names = []
    for part in parts:
        if not isinstance(part, dict) or not isinstance(part.get("name"), str):
            return ""
        name = part["name"]
        subscripts = part.get("subscripts")
        if isinstance(subscripts, list) and subscripts:
            name += "[" + ",".join(str(_value_text(s) or "") for s in subscripts) + "]"
        names.append(name)
    return ".".join(names)


def connections(
    cls: dict[str, Any], depth: int = 0, inherited: bool = False
) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if depth < MAX_DEPTH:
        for base in _bases(cls):
            found.extend(connections(base, depth + 1, True))
    items = cls.get("connections") if isinstance(cls.get("connections"), list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        annotation = item.get("annotation") if isinstance(item.get("annotation"), dict) else {}
        line = annotation.get("Line") if isinstance(annotation.get("Line"), dict) else {}
        found.append(
            {
                "from": _cref(item.get("lhs")),
                "to": _cref(item.get("rhs")),
                "points": _points(line.get("points")),
                "color": _color(line.get("color"), [0, 0, 127]),
                "thickness": _num(line.get("thickness"), 0.25),
                "inherited": inherited,
            }
        )
    return found


def reduce(instance: dict[str, Any]) -> dict[str, Any]:
    """What the diagram view and the parameter panel draw for one class."""

    components = []
    for item, inherited in _components(instance):
        if item.get("condition") is False:
            continue
        kind = _type_of(item)
        placement = _placement(item)
        if placement is None:
            continue
        prefixes = item.get("prefixes") if isinstance(item.get("prefixes"), dict) else {}
        values = {}
        for parameter in parameters(kind, item.get("modifiers")):
            text = parameter["set"] or parameter["value"] or parameter["default"]
            if text is not None:
                values[parameter["name"]] = text
        components.append(
            {
                "name": item.get("name", ""),
                "type": kind.get("name", ""),
                "restriction": kind.get("restriction", ""),
                "comment": item.get("comment", "") if isinstance(item.get("comment"), str) else "",
                "inherited": inherited,
                "placement": placement,
                "icon": layer(kind, "Icon"),
                "connectors": _connectors(kind),
                "parameters": parameters(kind, item.get("modifiers")),
                "values": values,
                "connector": kind.get("restriction") in CONNECTORS,
                "direction": prefixes.get("direction") or "",
            }
        )
        if len(components) >= MAX_COMPONENTS:
            break
    variables = []
    for item, inherited in _components(instance):
        if item.get("condition") is False:
            continue
        kind = _type_of(item)
        prefixes = item.get("prefixes") if isinstance(item.get("prefixes"), dict) else {}
        type_name = str(kind.get("name", ""))
        direction = prefixes.get("direction") or (
            "input"
            if type_name.endswith(("RealInput", "BooleanInput", "IntegerInput"))
            else "output"
            if type_name.endswith(("RealOutput", "BooleanOutput", "IntegerOutput"))
            else ""
        )
        if direction or prefixes.get("variability") == "parameter":
            variables.append(
                {
                    "name": item.get("name", ""),
                    "type": type_name,
                    "direction": direction,
                    "parameter": prefixes.get("variability") == "parameter",
                    "public": prefixes.get("public") is not False,
                    "comment": item.get("comment", "")
                    if isinstance(item.get("comment"), str)
                    else "",
                    "inherited": inherited,
                }
            )
    annotation = instance.get("annotation") if isinstance(instance.get("annotation"), dict) else {}
    documentation = (
        annotation.get("Documentation") if isinstance(annotation.get("Documentation"), dict) else {}
    )
    return {
        "name": instance.get("name", ""),
        "restriction": instance.get("restriction", ""),
        "comment": instance.get("comment", "") if isinstance(instance.get("comment"), str) else "",
        "diagram": layer(instance, "Diagram"),
        "icon": layer(instance, "Icon"),
        "components": components,
        "connections": connections(instance),
        "parameters": parameters(instance),
        "inputs": [v["name"] for v in variables if v["direction"] == "input"],
        "outputs": [v["name"] for v in variables if v["direction"] == "output"],
        "documentation": {
            "info": documentation.get("info", "")
            if isinstance(documentation.get("info"), str)
            else "",
            "revisions": documentation.get("revisions", "")
            if isinstance(documentation.get("revisions"), str)
            else "",
        },
    }
