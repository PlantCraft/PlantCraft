"""Older protocol formats as algorithm diagrams (version 2).

PlantCraft Analytics 0.2 saved a protocol as a list of methods, or as a version 1 diagram
(``{"kind": "signal" | "transform" | "method" | "check" | "verdict" | "combine" | "score" |
"result" | "series" | "message"}`` nodes, one output per block). Both become diagrams of today's
blocks, with the step that was implicit then drawn now: the loop data check before the methods.
A version 1 ``series`` output becomes a recorded port of the block it read.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from plantcraft_sdk.blocks import VERSION

from linkcraft.blocks.algorithms import COLUMNS, ROW
from linkcraft.blocks.catalog import CATALOG, GATE_ID, HEALTH_ID, method_of
from linkcraft.blocks.checks import block_id as check_block
from linkcraft.blocks.methods import block_id as method_block
from linkcraft.catalog.registry import METHOD_SPECS, gate_method_ids, method_group

GATED = ("pv", "sp", "op", "mode")
# Context and diagnostics of 0.2 (``AnalysisConfig``): outside the score, beside it.
CONTEXT = ("operational_interventions", "manual_mode_fraction")
DIAGNOSTICS = ("stiction_screening", "oscillation_autocorrelation", "sensor_noise_ratio")
EXCLUDED = ("stiction_screening",)


def _edge(source: str, source_port: str, target: str, target_port: str) -> dict[str, str]:
    return {
        "source": source,
        "source_port": source_port,
        "target": target,
        "target_port": target_port,
    }


def from_methods(
    method_ids: Iterable[str] | None,
    parameters: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    context: Iterable[str] = CONTEXT,
    diagnostics: Iterable[str] = DIAGNOSTICS,
    excluded: Iterable[str] = EXCLUDED,
) -> dict[str, Any]:
    """A list of methods as a diagram: signals, the loop data check, the methods, the health."""

    parameters = parameters or {}
    context, diagnostics, excluded = set(context), set(diagnostics), set(excluded)
    gates = set(gate_method_ids())
    chosen = [item for item in dict.fromkeys(method_ids or []) if item in METHOD_SPECS]
    cpm = [item for item in chosen if method_group(item) == "cpm"]
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for index, role in enumerate(GATED):
        nodes.append(
            {
                "id": role,
                "block": "input.state" if role == "mode" else "input.signal",
                "parameters": {"role": role},
                "x": COLUMNS["input"],
                "y": 40 + ROW * index,
            }
        )
        edges.append(_edge(role, "value", "data", role))
    gate_parameters: dict[str, Any] = {}
    for method_id in gates:
        gate_parameters.update(parameters.get(method_id) or {})
    nodes.append(
        {
            "id": "data",
            "block": GATE_ID,
            "parameters": gate_parameters,
            "x": COLUMNS["gate"],
            "y": 40,
        }
    )
    extra_inputs: set[str] = set()
    for index, method_id in enumerate(cpm):
        nodes.append(
            {
                "id": method_id,
                "block": method_block(method_id),
                "parameters": dict(parameters.get(method_id) or {}),
                "x": COLUMNS["method"] + 300 * (index // 6),
                "y": 40 + ROW * (index % 6),
            }
        )
        for port in CATALOG[method_block(method_id)].spec.inputs:
            if port.port_id in GATED:
                edges.append(_edge("data", port.port_id, method_id, port.port_id))
            elif port.port_id == "x":
                edges.append(_edge("pv", "recorded", method_id, "x"))
            elif port.required:
                extra_inputs.add(port.port_id)
                edges.append(_edge(port.port_id, "value", method_id, port.port_id))
    for index, role in enumerate(sorted(extra_inputs)):
        nodes.append(
            {
                "id": role,
                "block": "input.signal",
                "parameters": {"role": role},
                "x": COLUMNS["input"],
                "y": 40 + ROW * (len(GATED) + index),
            }
        )
    output_x = COLUMNS["method"] + 300 * (1 + (max(len(cpm), 1) - 1) // 6) + 40
    if cpm:
        nodes.append({"id": "health", "block": HEALTH_ID, "parameters": {}, "x": output_x, "y": 40})
        for method_id in cpm:
            if method_id in context:
                edges.append(_edge(method_id, "result", "health", "context"))
                continue
            if method_id not in excluded:
                edges.append(_edge(method_id, "result", "health", "methods"))
            if method_id in diagnostics or method_id in excluded:
                edges.append(_edge(method_id, "result", "health", "diagnostics"))
        edges.append(_edge("data", "verdict", "health", "data"))
    else:
        # Only the loop data check: its verdict is the result.
        nodes.append(
            {
                "id": "data_result",
                "block": "output.result",
                "parameters": {"name": "Loop data"},
                "x": output_x,
                "y": 40,
            }
        )
        edges.append(_edge("data", "verdict", "data_result", "in"))
    return {"version": VERSION, "nodes": nodes, "edges": edges}


# Version 1 diagrams -----------------------------------------------------------------

_COMBINE = {"worst": "logic.worst", "average": "logic.average", "rule": "logic.rule"}
_OUTPUT = {"result": "output.result", "message": "output.message", "score": HEALTH_ID}


def _v1_block(node: Mapping[str, Any]) -> tuple[str, dict[str, Any]] | None:
    kind = node.get("kind")
    parameters = dict(node.get("parameters") or {})
    if kind == "signal":
        role = str(node.get("signal") or "pv")
        return ("input.state" if role == "mode" else "input.signal"), {"role": role}
    if kind == "verdict":
        return "input.verdict", {"role": str(node.get("signal") or "pv")}
    if kind == "transform":
        return f"transform.{node.get('transform')}", parameters
    if kind == "method":
        method_id = str(node.get("method_id"))
        if method_id in gate_method_ids():
            return None
        return method_block(method_id), parameters
    if kind == "check":
        return check_block(str(node.get("check"))), parameters
    if kind == "combine":
        found = _COMBINE.get(str(node.get("combine")))
        return (found, parameters) if found else None
    if kind in _OUTPUT:
        return _OUTPUT[str(kind)], parameters if kind != "score" else {}
    return None


def from_flow(flow: Mapping[str, Any]) -> dict[str, Any]:
    """A version 1 diagram as a version 2 one."""

    old = {
        str(node.get("id")): node
        for node in flow.get("nodes") or []
        if isinstance(node, Mapping) and node.get("id")
    }
    nodes: dict[str, dict[str, Any]] = {}
    for node_id, node in old.items():
        if node.get("kind") == "series":
            continue
        found = _v1_block(node)
        if found is None:
            continue
        block, parameters = found
        x = float(node.get("x") or 0)
        nodes[node_id] = {
            "id": node_id,
            "block": block,
            "parameters": parameters,
            # Room for the loop data check next to the signals.
            "x": x if node.get("kind") in {"signal", "verdict"} else x + 260,
            "y": float(node.get("y") or 0),
        }
    roles = {
        str(node.get("signal")): node_id
        for node_id, node in old.items()
        if node.get("kind") == "signal"
    }
    edges: list[dict[str, Any]] = []
    gated = False
    for edge in flow.get("edges") or []:
        if not isinstance(edge, Mapping):
            continue
        source, target = str(edge.get("source")), str(edge.get("target"))
        if source not in nodes:
            continue
        source_kind = old[source].get("kind")
        target_node = old.get(target) or {}
        target_kind = target_node.get("kind")
        port = str(edge.get("target_port") or "")
        if target_kind == "series":
            nodes[source].setdefault("record", []).append("result")
            continue
        if target not in nodes:
            continue
        if source_kind == "signal":
            role = str(old[source].get("signal"))
            if target_kind == "check":
                edges.append(_edge(source, "recorded", target, "x"))
            elif role in GATED and target_kind in {"method", "transform"}:
                gated = True
                edges.append(_edge("data", role, target, port))
            else:
                edges.append(_edge(source, "value", target, port))
            continue
        source_port = "value" if source_kind == "transform" else "result"
        if target_kind == "combine" and str(target_node.get("combine")) in {"worst", "average"}:
            port = "in"
        elif target_kind == "score":
            port = "methods"
        elif target_kind in {"result", "message"}:
            port = "in"
        elif target_kind == "check":
            port = "x"
        edges.append(_edge(source, source_port, target, port))
    if gated:
        first = min((node["y"] for node in nodes.values()), default=40)
        nodes["data"] = {
            "id": "data",
            "block": GATE_ID,
            "parameters": {},
            "x": max(
                (node["x"] for node in nodes.values() if node["block"].startswith("input.")),
                default=40,
            )
            + 260,
            "y": first,
        }
        for role, node_id in roles.items():
            if role in GATED:
                edges.append(_edge(node_id, "value", "data", role))
        if "pv" not in roles:
            nodes["pv"] = {
                "id": "pv",
                "block": "input.signal",
                "parameters": {"role": "pv"},
                "x": 40,
                "y": first,
            }
            roles["pv"] = "pv"
            edges.append(_edge("pv", "value", "data", "pv"))
    # Sampling quality reads the PV's sample times: an input that was implicit before.
    for node_id, node in nodes.items():
        if node["block"] == method_block("sampling_quality"):
            if "pv" not in roles:
                nodes["pv"] = {
                    "id": "pv",
                    "block": "input.signal",
                    "parameters": {"role": "pv"},
                    "x": 40,
                    "y": 40,
                }
                roles["pv"] = "pv"
            edges.append(_edge(roles["pv"], "recorded", node_id, "x"))
    health = [node_id for node_id, node in nodes.items() if node["block"] == HEALTH_ID]
    if health:
        scored = {edge["source"] for edge in edges if edge["target"] == health[0]}
        for node_id, node in nodes.items():
            method_id = method_of(node["block"])
            if not method_id or node_id in scored:
                continue
            # Methods outside the score were shown beside it: context or diagnostics.
            port = "context" if method_id in CONTEXT else "diagnostics"
            edges.append(_edge(node_id, "result", health[0], port))
        if gated:
            edges.append(_edge("data", "verdict", health[0], "data"))
    return {"version": VERSION, "nodes": list(nodes.values()), "edges": edges}


def diagram_of(config: Mapping[str, Any] | None) -> dict[str, Any]:
    """The diagram an algorithm's (or an old protocol's) configuration describes."""

    config = config or {}
    diagram = config.get("diagram")
    if isinstance(diagram, Mapping) and diagram.get("nodes"):
        return dict(diagram)
    flow = config.get("flow")
    if isinstance(flow, Mapping) and flow.get("nodes"):
        return from_flow(flow)
    return from_methods(config.get("method_ids"), config.get("parameters"))


def with_node_parameters(
    config: Mapping[str, Any] | None, overrides: Mapping[str, Any] | None
) -> dict[str, Any]:
    """An algorithm's configuration with a monitor's own parameter values on top: the block's
    default, then the algorithm's value, then the monitor's. ``overrides``
    is ``{node id: {parameter: value}}``; a node the diagram does not have is left out."""

    config = dict(config or {})
    if not overrides:
        return config
    diagram = diagram_of(config)
    nodes = []
    for node in diagram.get("nodes") or []:
        own = overrides.get(str(node.get("id"))) if isinstance(node, Mapping) else None
        if isinstance(own, Mapping) and own:
            node = {**node, "parameters": {**(node.get("parameters") or {}), **own}}
        nodes.append(node)
    return {**config, "diagram": {**diagram, "nodes": nodes}}


def methods_in(diagram: Mapping[str, Any]) -> list[str]:
    """The method ids a diagram runs (CPM blocks, and the gate's methods when it has one)."""

    found: list[str] = []
    for node in diagram.get("nodes") or []:
        block = str((node or {}).get("block") or "")
        if block == GATE_ID:
            found.extend(gate_method_ids())
        elif method_of(block):
            found.append(str(method_of(block)))
    return list(dict.fromkeys(found))


def parameters_in(diagram: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Each method's parameters as the diagram sets them (keyed by method id)."""

    found: dict[str, dict[str, Any]] = {}
    for node in diagram.get("nodes") or []:
        block = str((node or {}).get("block") or "")
        values = dict((node or {}).get("parameters") or {})
        if block == GATE_ID:
            for method_id in gate_method_ids():
                fields = METHOD_SPECS[method_id].parameter_schema.model_fields
                own = {key: value for key, value in values.items() if key in fields}
                if own:
                    found.setdefault(method_id, {}).update(own)
        elif method_of(block) and values:
            found.setdefault(str(method_of(block)), {}).update(values)
    return found
