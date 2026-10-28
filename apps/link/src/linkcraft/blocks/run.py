"""What a run of a diagram gives besides its outputs: each block's verdict, the recorded ports and
what every wire carried (for the editor's test), the same for loops, signals and assets."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd
from plantcraft_sdk.blocks import NoData, Plan, Result, Values, label_of

from linkcraft.blocks.catalog import CATALOG

# Points kept per series when a test run shows the values on the wires.
TRACE_POINTS = 240
# A kept run's series per wire: enough for the inspector's chart (280 px wide).
SAMPLE_POINTS = 120


def block_verdicts(plan: Plan, values: Values) -> dict[str, dict[str, Any]]:
    """Each block's verdict (its first verdict output), for the editor and the loop page."""

    found: dict[str, dict[str, Any]] = {}
    for node_id in plan.order:
        spec = CATALOG[plan.nodes[node_id]["block"]].spec
        port = next((item for item in spec.outputs if item.type == "result"), None)
        if port is None:
            continue
        value = values.get(node_id, port.port_id)
        label = label_of(plan.nodes[node_id], CATALOG)
        if isinstance(value, Result):
            found[node_id] = {**value.as_dict(), "label": value.label or label}
        elif isinstance(value, NoData):
            found[node_id] = Result.unknown(value.reason, label).as_dict()
    return found


def output_key(text: str) -> str:
    """An output's name as a series key: ``Valve health`` -> ``valve-health``."""

    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:60] or "output"


def recorded_keys(plan: Plan) -> dict[tuple[str, str], str]:
    """The key of each recorded port in its series id: the block's name, plus the port when the
    block records more than one. Renaming a block starts a new series; versions of the algorithm
    keep writing the same one. Two blocks of one name get their block id to tell them apart."""

    names = {
        node_id: output_key(label_of(plan.nodes[node_id], CATALOG)) for node_id in plan.recorded
    }
    taken = [names[node_id] for node_id in plan.recorded]
    keys: dict[tuple[str, str], str] = {}
    for node_id, ports in plan.recorded.items():
        name = names[node_id]
        if taken.count(name) > 1:
            name = f"{name}-{output_key(node_id)}"
        for port_id in ports:
            keys[(node_id, port_id)] = name if len(ports) == 1 else f"{name}.{output_key(port_id)}"
    return keys


def recorded_ports(plan: Plan, values: Values) -> list[dict[str, Any]]:
    """The ports the diagram records in the historian, with this run's value."""

    found = []
    keys = recorded_keys(plan)
    for node_id, ports in plan.recorded.items():
        node = plan.nodes[node_id]
        spec = CATALOG[node["block"]].spec
        for port_id in ports:
            port = spec.output(port_id)
            if port is None:
                continue
            value = values.get(node_id, port_id)
            entry: dict[str, Any] = {
                "node_id": node_id,
                "port": port_id,
                "key": keys[(node_id, port_id)],
                "block": node["block"],
                "label": label_of(node, CATALOG),
                "port_label": port.label,
                "description": port.description,
                "type": port.type,
                "unit": port.unit,
                "value": None,
                "status": None,
            }
            if isinstance(value, Result):
                entry.update(value=value.value, status=value.status, message=value.message)
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                entry["value"] = float(value)
            elif isinstance(value, pd.Series) and len(value.dropna()):
                entry["value"] = float(pd.to_numeric(value, errors="coerce").dropna().iloc[-1])
            found.append(entry)
    return found


def trace_value(value: Any, points: int = TRACE_POINTS) -> dict[str, Any]:
    if isinstance(value, NoData):
        return {"type": "missing", "reason": value.reason}
    if isinstance(value, Result):
        return {"type": "result", **value.as_dict()}
    if isinstance(value, pd.Series):
        numbers = pd.to_numeric(value, errors="coerce")
        text = numbers.isna().all() and value.notna().any()
        clean = value.dropna()
        step = max(1, len(clean) // points)
        sample = clean.iloc[::step]
        return {
            "type": "state" if text else "series",
            "count": int(len(clean)),
            "t": [str(stamp) for stamp in sample.index],
            "v": [str(item) if text else float(item) for item in sample.to_numpy()],
            "last": (str(clean.iloc[-1]) if text else float(clean.iloc[-1]))
            if len(clean)
            else None,
        }
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"type": "number", "value": float(value)}
    return {"type": "none"}


def trace(plan: Plan, values: Values) -> dict[str, dict[str, Any]]:
    """What each output port carried in a test run, small enough to draw on the wires."""

    found: dict[str, dict[str, Any]] = {}
    for (node_id, port_id), value in values.values.items():
        found.setdefault(node_id, {})[port_id] = trace_value(value)
    return found


def wires(plan: Plan, values: Values) -> dict[str, dict[str, Any]]:
    """What each output port carried in a scheduled run, without the samples: kept with the run
    so its page draws the diagram with the values on the wires (owner D23, 2026-10-26). A
    series keeps its count and last point; its samples come from running the window again."""

    found: dict[str, dict[str, Any]] = {}
    for (node_id, port_id), value in values.values.items():
        item = trace_value(value)
        if item["type"] in {"series", "state"}:
            item = {**item, "t": item["t"][-1:], "v": item["v"][-1:]}
        found.setdefault(node_id, {})[port_id] = item
    return found


def samples(plan: Plan, values: Values) -> dict[str, dict[str, Any]]:
    """What each output port carried, with a thinned series (``SAMPLE_POINTS``): kept for a
    subject's last runs only (``engine.samples``), so clicking a block on one draws its charts."""

    found: dict[str, dict[str, Any]] = {}
    for (node_id, port_id), value in values.values.items():
        found.setdefault(node_id, {})[port_id] = trace_value(value, SAMPLE_POINTS)
    return found


__all__ = [
    "SAMPLE_POINTS",
    "TRACE_POINTS",
    "block_verdicts",
    "output_key",
    "recorded_keys",
    "recorded_ports",
    "samples",
    "trace",
    "trace_value",
    "wires",
]
