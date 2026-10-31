"""The asset model shared by PlantCraft and the fake: types, attributes, roles, relations.

An **asset type** has a name, a parent type (single inheritance), attributes
(master data), signal roles (slots for measured signals) and the types that may
sit inside it. A child type gets its parent's attributes and roles and adds its
own; ``resolve_types`` turns the stored definitions into what
``GET /api/v1/asset-types`` answers, with everything inherited filled in.

``STARTER_TYPES`` are the types a new installation starts with. Their ids are
the asset kinds the platform always had (``site``, ``unit``, ``area``,
``equipment``, ``loop``) plus a few common ones; the admin may edit any of
them and add others. Apps match on ``type_path``: an app that works on control
loops takes every asset whose ``type_path`` contains ``loop``.

A **result asset** (type ``result``) is what an app records about another asset: Link gives each
asset of a schedule one, ``FIC-1003 · Daily review``, holding the points that schedule writes.
Only the app makes them, through ``PUT /api/v1/assets/results``; ``parse_result_assets`` holds the
rules PlantCraft and the fake share. The plant tree hides them unless asked.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterable
from typing import Any

DATA_TYPES = ("text", "number", "choice", "date", "asset")
# Relation id -> (label, label read from the other end).
RELATION_TYPES: dict[str, tuple[str, str]] = {
    "controls": ("Controls", "Controlled by"),
    "measures": ("Measures", "Measured by"),
    "feeds": ("Feeds", "Fed by"),
    "downstream_of": ("Downstream of", "Upstream of"),
}
# The kinds the platform code relies on (the root, the tree levels, loops).
CORE_TYPES = ("site", "unit", "area", "equipment", "loop")
LOOP_TYPE = "loop"
# A third-party multivariable controller (APC/MPC) and the variables it moves and holds: apps
# read them, never write (Analytics' APC health and constraint costs, View's MV/CV widget).
APC_TYPE = "apc"
APC_VARIABLE_TYPE = "apc_variable"
APC_MV_TYPE = "apc_mv"
APC_CV_TYPE = "apc_cv"
# What an app records about an asset (a schedule's outputs); only apps make them.
RESULT_TYPE = "result"
RESULT_STATES = ["active", "ended"]
CRITICALITY = ["low", "medium", "high"]


def attribute(
    key: str,
    name: str,
    data_type: str = "text",
    *,
    unit: str = "",
    required: bool = False,
    default: Any = None,
    options: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "data_type": data_type,
        "unit": unit,
        "required": required,
        "default": default,
        "options": list(options or []),
    }


def role(key: str, name: str, *, unit: str = "", required: bool = False) -> dict[str, Any]:
    return {"key": key, "name": name, "unit": unit, "required": required}


def _type(
    type_id: str,
    name: str,
    *,
    description: str = "",
    icon: str = "",
    parent: str | None = None,
    attributes: list[dict[str, Any]] | None = None,
    roles: list[dict[str, Any]] | None = None,
    children: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": type_id,
        "name": name,
        "description": description,
        "icon": icon,
        "parent": parent,
        "attributes": attributes or [],
        "roles": roles or [],
        "children": children or [],
    }


STARTER_TYPES: list[dict[str, Any]] = [
    _type(
        "site",
        "Plant",
        description="The installation: the root of the asset tree.",
        icon="building",
        attributes=[attribute("location", "Location"), attribute("operator", "Operator")],
        children=["unit"],
    ),
    _type(
        "unit",
        "Unit",
        description="A process unit.",
        icon="factory",
        attributes=[
            attribute("unit_code", "Unit code"),
            attribute("capacity", "Capacity", "number", unit="m³/d"),
        ],
        children=["area", "equipment", APC_TYPE],
    ),
    _type(
        "area",
        "Area",
        description="An area of a unit.",
        icon="map-pin",
        attributes=[attribute("owner", "Owner")],
        children=["equipment", "loop", APC_TYPE],
    ),
    _type(
        "equipment",
        "Equipment",
        description="A piece of process equipment.",
        icon="box",
        attributes=[
            attribute("manufacturer", "Manufacturer"),
            attribute("model", "Model"),
            attribute("serial_number", "Serial number"),
            attribute("criticality", "Criticality", "choice", options=CRITICALITY),
            attribute(
                "isa95_level",
                "ISA-95 level",
                "choice",
                options=["Site", "Area", "Work center", "Work unit", "Equipment module"],
            ),
            attribute("iso14224_class", "ISO 14224 class"),
        ],
        children=["equipment", "instrument", "loop"],
    ),
    _type(
        "pump",
        "Pump",
        description="A pump.",
        icon="pump",
        parent="equipment",
        attributes=[
            attribute("pump_type", "Pump type", "choice", options=["centrifugal", "reciprocating"]),
            attribute("rated_flow", "Rated flow", "number", unit="m³/h"),
            attribute("power", "Power", "number", unit="kW"),
        ],
        roles=[
            role("flow", "Flow"),
            role("suction_pressure", "Suction pressure"),
            role("discharge_pressure", "Discharge pressure"),
            role("current", "Current", unit="A"),
            role("status", "Status"),
        ],
        children=["instrument"],
    ),
    _type(
        "valve",
        "Valve",
        description="A valve.",
        icon="valve",
        parent="equipment",
        attributes=[
            attribute("diameter", "Diameter", "number", unit="in"),
            attribute("pressure_class", "Pressure class"),
        ],
        roles=[role("position", "Position", unit="%")],
    ),
    _type(
        "control_valve",
        "Control valve",
        description="A valve moved by a controller.",
        icon="valve",
        parent="valve",
        attributes=[
            attribute(
                "characteristic",
                "Characteristic",
                "choice",
                options=["linear", "equal percentage", "quick opening"],
            ),
            attribute(
                "actuator", "Actuator", "choice", options=["pneumatic", "electric", "hydraulic"]
            ),
            attribute("cv", "Cv", "number"),
        ],
        roles=[role("command", "Command", unit="%")],
    ),
    _type(
        "instrument",
        "Instrument",
        description="A transmitter or analyser.",
        icon="thermometer",
        attributes=[
            attribute(
                "measured_variable",
                "Measured variable",
                "choice",
                options=["flow", "level", "pressure", "temperature", "composition", "other"],
            ),
            attribute("range_min", "Range min", "number"),
            attribute("range_max", "Range max", "number"),
            attribute("range_unit", "Unit"),
        ],
        roles=[role("measurement", "Measurement")],
    ),
    # Static and rotating equipment, as ISO 14224 names its classes (0.10.1).
    _type(
        "vessel",
        "Vessel",
        description="A drum, separator or reactor vessel.",
        icon="cylinder",
        parent="equipment",
        attributes=[
            attribute("volume", "Volume", "number", unit="m³"),
            attribute("design_pressure", "Design pressure", "number", unit="bar g"),
            attribute("design_temperature", "Design temperature", "number", unit="°C"),
        ],
        roles=[
            role("level", "Level", unit="%"),
            role("pressure", "Pressure"),
            role("temperature", "Temperature"),
        ],
        children=["instrument", "valve"],
    ),
    _type(
        "column",
        "Column",
        description="A distillation, absorption or stripping column.",
        icon="column",
        parent="equipment",
        attributes=[
            attribute("trays", "Trays or stages", "number"),
            attribute("diameter", "Diameter", "number", unit="m"),
            attribute("height", "Height", "number", unit="m"),
        ],
        roles=[
            role("top_pressure", "Top pressure"),
            role("top_temperature", "Top temperature"),
            role("bottom_temperature", "Bottom temperature"),
            role("differential_pressure", "Differential pressure"),
        ],
        children=["instrument", "valve", "vessel", "pump"],
    ),
    _type(
        "heat_exchanger",
        "Heat exchanger",
        description="A shell-and-tube, plate or air-cooled exchanger.",
        icon="exchanger",
        parent="equipment",
        attributes=[
            attribute(
                "exchanger_type",
                "Exchanger type",
                "choice",
                options=["shell and tube", "plate", "air cooled", "double pipe"],
            ),
            attribute("duty", "Duty", "number", unit="MW"),
            attribute("area", "Exchange area", "number", unit="m²"),
        ],
        roles=[
            role("inlet_temperature", "Inlet temperature"),
            role("outlet_temperature", "Outlet temperature"),
        ],
        children=["instrument", "valve"],
    ),
    _type(
        "furnace",
        "Furnace",
        description="A fired heater.",
        icon="flame",
        parent="equipment",
        attributes=[
            attribute("duty", "Duty", "number", unit="MW"),
            attribute("burners", "Burners", "number"),
            attribute("fuel", "Fuel", "choice", options=["fuel gas", "fuel oil", "dual"]),
        ],
        roles=[
            role("outlet_temperature", "Outlet temperature"),
            role("fuel_flow", "Fuel flow"),
            role("excess_oxygen", "Excess oxygen", unit="%"),
        ],
        children=["instrument", "valve"],
    ),
    _type(
        "compressor",
        "Compressor",
        description="A centrifugal or reciprocating compressor.",
        icon="compressor",
        parent="equipment",
        attributes=[
            attribute(
                "compressor_type",
                "Compressor type",
                "choice",
                options=["centrifugal", "reciprocating", "screw"],
            ),
            attribute("power", "Power", "number", unit="kW"),
        ],
        roles=[
            role("suction_pressure", "Suction pressure"),
            role("discharge_pressure", "Discharge pressure"),
            role("speed", "Speed", unit="rpm"),
            role("vibration", "Vibration", unit="mm/s"),
        ],
        children=["instrument", "valve"],
    ),
    _type(
        "tank",
        "Tank",
        description="An atmospheric storage tank.",
        icon="tank",
        parent="equipment",
        attributes=[
            attribute("capacity", "Capacity", "number", unit="m³"),
            attribute("product", "Product"),
        ],
        roles=[role("level", "Level", unit="%"), role("temperature", "Temperature")],
        children=["instrument", "valve", "pump"],
    ),
    _type(
        "loop",
        "Control loop",
        description="A control loop: its controller and the signals it moves and reads.",
        icon="gauge",
        attributes=[
            attribute(
                "loop_type",
                "Loop type",
                "choice",
                options=["flow", "level", "pressure", "temperature", "composition"],
            ),
            attribute("criticality", "Criticality", "choice", options=CRITICALITY),
            attribute("action", "Action", "choice", options=["direct", "reverse"]),
            attribute("controller", "Controller", "choice", options=["DCS", "SLC"]),
        ],
        roles=[
            role("pv", "PV", required=True),
            role("sp", "SP"),
            role("op", "OP", unit="%", required=True),
            role("mode", "Mode"),
            role("secondary", "Secondary"),
        ],
    ),
    _type(
        APC_TYPE,
        "Multivariable controller",
        description=(
            "An advanced (multivariable, model predictive) controller from any vendor: whether it"
            " is on, and the variables it moves and holds. Read only."
        ),
        icon="cpu",
        attributes=[
            attribute("vendor", "Vendor"),
            attribute("cost_unit", "Cost unit", default="$/h"),
        ],
        roles=[role("on", "On (1 = on and in control)", required=True), role("mode", "Mode")],
        children=[APC_MV_TYPE, APC_CV_TYPE],
    ),
    _type(
        APC_VARIABLE_TYPE,
        "Controller variable",
        description="A variable of a multivariable controller: its value, limits and target.",
        icon="sliders-horizontal",
        attributes=[
            attribute("limit_band", "At-limit band", "number"),
        ],
        roles=[
            role("value", "Value", required=True),
            role("lo", "Low limit"),
            role("hi", "High limit"),
            role("target", "Steady-state target"),
            role("status", "In service (1 = yes)"),
            role("shadow_price", "Constraint cost (per unit of the limit)"),
        ],
    ),
    _type(
        APC_MV_TYPE,
        "Manipulated variable",
        description="What the controller moves: usually a loop's setpoint.",
        icon="sliders-horizontal",
        parent=APC_VARIABLE_TYPE,
    ),
    _type(
        APC_CV_TYPE,
        "Controlled variable",
        description="What the controller holds at a target or inside its limits.",
        icon="target",
        parent=APC_VARIABLE_TYPE,
    ),
    _type(
        RESULT_TYPE,
        "Result",
        description=(
            "What an app records about an asset, such as the outputs one Link schedule writes."
            " The app makes and ends these; the plant tree hides them unless asked."
        ),
        icon="chart",
        attributes=[
            attribute("app", "App"),
            attribute("made_by", "Made by"),
            attribute("state", "State", "choice", default="active", options=RESULT_STATES),
        ],
    ),
]


def starter_types() -> list[dict[str, Any]]:
    """A fresh copy of the starter definitions (parents before children)."""

    return copy.deepcopy(STARTER_TYPES)


# Resolution ------------------------------------------------------------------


def _by_id(definitions: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in definitions}


def type_path(definitions: dict[str, dict[str, Any]], type_id: str) -> list[str]:
    """Root type first, ``type_id`` last; a broken or circular chain stops where it breaks."""

    chain: list[str] = []
    current: str | None = type_id
    while current is not None and current not in chain:
        chain.append(current)
        item = definitions.get(current)
        current = item.get("parent") if item else None
    return list(reversed(chain))


def subtypes(definitions: dict[str, dict[str, Any]], type_id: str) -> set[str]:
    """The type and every type that inherits from it."""

    return {item for item in definitions if type_id in type_path(definitions, item)} | {type_id}


def resolve_type(definitions: dict[str, dict[str, Any]], type_id: str) -> dict[str, Any]:
    """One type as ``GET /api/v1/asset-types`` lists it, inherited attributes and roles first."""

    item = definitions[type_id]
    path = type_path(definitions, type_id)
    attributes: list[dict[str, Any]] = []
    roles: list[dict[str, Any]] = []
    for ancestor in path:
        own = definitions.get(ancestor) or {}
        for entry in own.get("attributes") or []:
            if all(entry["key"] != other["key"] for other in attributes):
                attributes.append({**entry, "options": list(entry.get("options") or [])})
        for entry in own.get("roles") or []:
            if all(entry["key"] != other["key"] for other in roles):
                roles.append(dict(entry))
    children: list[str] = []
    for child in item.get("children") or []:
        if child not in definitions:
            continue
        for found in [child, *sorted(subtypes(definitions, child) - {child})]:
            if found not in children:
                children.append(found)
    return {
        "id": type_id,
        "name": item.get("name") or type_id,
        "description": item.get("description") or "",
        "icon": item.get("icon") or "",
        "parent": item.get("parent"),
        "path": path,
        "attributes": [
            {
                "key": entry["key"],
                "name": entry.get("name") or entry["key"],
                "data_type": entry.get("data_type") or "text",
                "unit": entry.get("unit") or "",
                "required": bool(entry.get("required")),
                "default": entry.get("default"),
                "options": list(entry.get("options") or []),
            }
            for entry in attributes
        ],
        "roles": [
            {
                "key": entry["key"],
                "name": entry.get("name") or entry["key"],
                "unit": entry.get("unit") or "",
                "required": bool(entry.get("required")),
            }
            for entry in roles
        ],
        "children": children,
    }


def resolve_types(definitions: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every type, in the order given, with inheritance resolved."""

    by_id = _by_id(definitions)
    return [resolve_type(by_id, type_id) for type_id in by_id]


def effective_attributes(resolved: dict[str, Any] | None, stored: dict[str, Any]) -> dict[str, Any]:
    """The values an asset of a type shows: the stored one, else the attribute's default."""

    values: dict[str, Any] = {}
    for entry in (resolved or {}).get("attributes") or []:
        value = stored.get(entry["key"], entry.get("default"))
        if value is not None:
            values[entry["key"]] = value
    return values


# Result assets (``PUT /api/v1/assets/results``) ----------------------------------

# Result assets per request, and their points.
MAX_RESULT_ASSETS = 2000
MAX_RESULT_POINTS = 200
_RESULT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,199}$")
_ROLE = re.compile(r"^[a-z][a-z0-9_]{0,59}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _plain(value: Any, field: str, limit: int, *, required: bool = False) -> str:
    text = "" if value is None else value
    if not isinstance(text, str):
        raise ValueError(f"{field} is text")
    text = text.strip()
    if required and not text:
        raise ValueError(f"{field} is required")
    if len(text) > limit or _CONTROL.search(text):
        raise ValueError(f"{field}: {limit} characters at most, no control characters")
    return text


def result_asset_prefix(app: str) -> str:
    """The ids of an app's result assets start with ``<app id>.``."""

    return f"{app}."


def _result_item(app: str, item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("each result asset is an object")
    asset_id = _plain(item.get("id"), "id", 200, required=True)
    if not _RESULT_ID.match(asset_id) or not asset_id.startswith(result_asset_prefix(app)):
        raise ValueError(
            f"id is {result_asset_prefix(app)}<name>: letters, digits, '.', '_' and '-'"
        )
    parent = _plain(item.get("parent_id"), "parent_id", 200, required=True)
    points = item.get("points") or []
    if not isinstance(points, list) or len(points) > MAX_RESULT_POINTS:
        raise ValueError(f"points is a list of {MAX_RESULT_POINTS} at most")
    found_points = []
    for point in points:
        if not isinstance(point, dict):
            raise ValueError("each point is an object")
        role_key = _plain(point.get("role"), "points.role", 60, required=True)
        if not _ROLE.match(role_key):
            raise ValueError("points.role: lower case, digits and _ (health)")
        signal = _plain(point.get("signal"), "points.signal", 340, required=True)
        source, sep, tag = signal.partition(":")
        if not sep or not tag or source != f"app-{app}":
            raise ValueError(f"points.signal is app-{app}:<name>, one of the app's own series")
        found_points.append(
            {
                "role": role_key,
                "signal": signal,
                "name": _plain(point.get("name"), "points.name", 200),
                "unit": _plain(point.get("unit"), "points.unit", 40),
            }
        )
    return {
        "id": asset_id,
        "parent_id": parent,
        "name": _plain(item.get("name"), "name", 200, required=True),
        "description": _plain(item.get("description"), "description", 500),
        "made_by": _plain(item.get("made_by"), "made_by", 200),
        "points": found_points,
    }


def parse_result_assets(app: str, body: Any) -> list[dict[str, Any]]:
    """The checked items of ``PUT /api/v1/assets/results``; ``ValueError`` names the first fault.

    The body is ``{"assets": [...]}``, the app's whole set: each item has ``id``
    (``<app id>.<name>``), ``parent_id`` (the asset it is about), ``name``, optional
    ``description``, ``made_by`` (what made it, such as ``schedule:daily-review``) and
    ``points`` (``{"role", "signal": "app-<app id>:<name>", "name", "unit"}``).
    """

    items = body.get("assets") if isinstance(body, dict) else None
    if not isinstance(items, list) or len(items) > MAX_RESULT_ASSETS:
        raise ValueError(
            f'Send {{"assets": [...]}} with {MAX_RESULT_ASSETS} result assets at most.'
        )
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        try:
            checked = _result_item(app, item)
        except ValueError as exc:
            raise ValueError(f"[{index}] {exc}") from None
        if checked["id"] in seen:
            raise ValueError(f"[{index}] id {checked['id']} is listed twice")
        seen.add(checked["id"])
        found.append(checked)
    return found


__all__ = [
    "APC_CV_TYPE",
    "APC_MV_TYPE",
    "APC_TYPE",
    "APC_VARIABLE_TYPE",
    "CORE_TYPES",
    "DATA_TYPES",
    "LOOP_TYPE",
    "MAX_RESULT_ASSETS",
    "RELATION_TYPES",
    "RESULT_STATES",
    "RESULT_TYPE",
    "STARTER_TYPES",
    "attribute",
    "effective_attributes",
    "parse_result_assets",
    "resolve_type",
    "resolve_types",
    "result_asset_prefix",
    "role",
    "starter_types",
    "subtypes",
    "type_path",
]
