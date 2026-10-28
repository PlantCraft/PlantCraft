"""Algorithms as diagrams: check one against a catalog of blocks, then run it.

A diagram is plain JSON, as the editor saves it::

    {"version": 2,
     "nodes": [{"id": "pv", "block": "input.signal", "parameters": {"role": "pv"}},
               {"id": "f1", "block": "transform.first_order_filter",
                "parameters": {"time_constant_seconds": 30}},
               {"id": "st", "block": "cpm.stiction", "record": ["index"]}],
     "edges": [{"source": "pv", "source_port": "value", "target": "f1", "target_port": "x"},
               {"source": "f1", "source_port": "value", "target": "st", "target_port": "pv"}]}

``compile_diagram`` checks it (known blocks, valid parameters, wires between ports of matching
types, required inputs wired, no loops) and returns a ``Plan``: the order to run the blocks in,
with every problem said in words and tied to its block so the editor can mark it.
``execute`` runs a plan on one window: each block receives what its inputs are wired to; a
block that fails, or whose required input carries ``NoData``, passes ``NoData`` on with the
reason, so only the blocks after it go without a value. An optional input whose wire carries
``NoData`` counts as not wired (a loop without a setpoint), unless nothing wired to the block
has a value. The order comes from the standard library's
``graphlib``.

Positions (``x``, ``y``) and a node's ``label`` are kept for the editor and ignored here.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from graphlib import CycleError, TopologicalSorter
from typing import Any

from pydantic import BaseModel, ValidationError

from plantcraft_sdk.blocks.contract import (
    COERCIONS,
    Block,
    Context,
    NoData,
    Result,
    accepts,
)
from plantcraft_sdk.i18n import t

LOGGER = logging.getLogger(__name__)
VERSION = 2
MAX_NODES = 200
MAX_EDGES = 600


@dataclass(frozen=True)
class Wire:
    source: str
    source_port: str
    target: str
    target_port: str


@dataclass
class Plan:
    """A checked diagram: what ``execute`` runs, and what is wrong with it."""

    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    # node id -> its validated parameters.
    parameters: dict[str, BaseModel] = field(default_factory=dict)
    # node id -> {input port: [wires into it]}.
    inputs: dict[str, dict[str, list[Wire]]] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    # node id -> output ports written to the historian.
    recorded: dict[str, list[str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    node_errors: dict[str, list[str]] = field(default_factory=dict)
    node_warnings: dict[str, list[str]] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return not self.errors

    def blocks_of(self, block_id: str) -> list[str]:
        """Node ids of one block, in run order."""

        return [node_id for node_id in self.order if self.nodes[node_id]["block"] == block_id]

    def report(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "node_errors": self.node_errors,
            "node_warnings": self.node_warnings,
            "order": self.order,
        }


def label_of(node: Mapping[str, Any], catalog: Mapping[str, Block]) -> str:
    """The name people read for a node: its own label, else its block's name."""

    own = str(node.get("label") or "").strip()
    if own:
        return own
    block = catalog.get(str(node.get("block")))
    return t(block.spec.name) if block else str(node.get("block") or node.get("id"))


def compile_diagram(
    diagram: Mapping[str, Any],
    catalog: Mapping[str, Block],
    *,
    sinks: Callable[[Block], bool] | None = None,
) -> Plan:
    """Check ``diagram`` against ``catalog`` and plan its run.

    ``sinks`` tells which blocks are outputs (by default: blocks without outputs). A diagram
    needs at least one; a block from which no output can be reached gets a warning.
    """

    plan = Plan()

    def fail(message: str, node_id: str | None = None) -> None:
        plan.errors.append(message)
        if node_id:
            plan.node_errors.setdefault(node_id, []).append(message)

    def warn(message: str, node_id: str | None = None) -> None:
        plan.warnings.append(message)
        if node_id:
            plan.node_warnings.setdefault(node_id, []).append(message)

    raw_nodes = diagram.get("nodes") if isinstance(diagram, Mapping) else None
    raw_edges = diagram.get("edges") if isinstance(diagram, Mapping) else None
    if not isinstance(raw_nodes, list) or not raw_nodes:
        fail(t("The diagram has no blocks."))
        return plan
    if len(raw_nodes) > MAX_NODES:
        fail(t("A diagram has at most {count} blocks.", count=MAX_NODES))
        return plan
    raw_edges = raw_edges if isinstance(raw_edges, list) else []
    if len(raw_edges) > MAX_EDGES:
        fail(t("A diagram has at most {count} wires.", count=MAX_EDGES))
        return plan

    broken: set[str] = set()
    for node in raw_nodes:
        node_id = str(node.get("id") or "") if isinstance(node, Mapping) else ""
        if not node_id or len(node_id) > 80 or node_id in plan.nodes:
            fail(t("Block without a unique id: {id}.", id=node_id or t("(empty)")))
            continue
        node = dict(node)
        plan.nodes[node_id] = node
        block = catalog.get(str(node.get("block")))
        if block is None:
            fail(t("Unknown block: {block}.", block=node.get("block")), node_id)
            broken.add(node_id)
            continue
        try:
            plan.parameters[node_id] = block.spec.parameters.model_validate(
                node.get("parameters") or {}
            )
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(part) for part in first.get("loc", ()))
            fail(
                t(
                    "{block}: parameter {name} is not valid ({error}).",
                    block=label_of(node, catalog),
                    name=where or "?",
                    error=first["msg"],
                ),
                node_id,
            )
        recorded = node.get("record") or []
        known = {port.port_id for port in block.spec.outputs}
        wanted = [str(item) for item in recorded if isinstance(item, str)]
        for port_id in wanted:
            if port_id not in known:
                fail(
                    t(
                        "{block} has no output {port} to record.",
                        block=label_of(node, catalog),
                        port=port_id,
                    ),
                    node_id,
                )
        recordable = {
            port.port_id
            for port in block.spec.outputs
            if port.type in ("number", "result", "series")
        }
        plan.recorded[node_id] = [port_id for port_id in wanted if port_id in recordable]

    plan.inputs = {node_id: {} for node_id in plan.nodes}
    graph: dict[str, set[str]] = {node_id: set() for node_id in plan.nodes}
    for edge in raw_edges:
        if not isinstance(edge, Mapping):
            fail(t("A wire is not valid."))
            continue
        wire = Wire(
            str(edge.get("source") or ""),
            str(edge.get("source_port") or ""),
            str(edge.get("target") or ""),
            str(edge.get("target_port") or ""),
        )
        if wire.source not in plan.nodes or wire.target not in plan.nodes:
            fail(t("A wire connects to a block that does not exist."))
            continue
        if wire.source in broken or wire.target in broken:
            continue
        source = catalog[plan.nodes[wire.source]["block"]].spec
        target = catalog[plan.nodes[wire.target]["block"]].spec
        source_label = label_of(plan.nodes[wire.source], catalog)
        target_label = label_of(plan.nodes[wire.target], catalog)
        out = source.output(wire.source_port) or (
            source.outputs[0] if not wire.source_port and len(source.outputs) == 1 else None
        )
        into = target.input(wire.target_port) or (
            target.inputs[0] if not wire.target_port and len(target.inputs) == 1 else None
        )
        if out is None:
            fail(
                t("{block} has no output {port}.", block=source_label, port=wire.source_port),
                wire.target,
            )
            continue
        if into is None:
            fail(
                t("{block} has no input {port}.", block=target_label, port=wire.target_port),
                wire.target,
            )
            continue
        wire = replace(wire, source_port=out.port_id, target_port=into.port_id)
        if not accepts(into.types, out.type):
            fail(
                t(
                    "{source} gives {given}; input {port} of {target} takes {taken}.",
                    source=f"{source_label} › {t(out.label)}",
                    given=t(out.type),
                    port=t(into.label),
                    target=target_label,
                    taken=" / ".join(t(item) for item in into.types),
                ),
                wire.target,
            )
            continue
        wired = plan.inputs[wire.target].setdefault(into.port_id, [])
        if wired and not into.multiple:
            fail(
                t(
                    "Input {port} of {block} receives two wires.",
                    port=t(into.label),
                    block=target_label,
                ),
                wire.target,
            )
            continue
        if out.unit and into.unit and out.unit != into.unit and into.unit != "*":
            warn(
                t(
                    "{source} is in {unit}; {target} expects {expected}.",
                    source=f"{source_label} › {t(out.label)}",
                    unit=out.unit,
                    target=target_label,
                    expected=into.unit,
                ),
                wire.target,
            )
        wired.append(wire)
        graph[wire.target].add(wire.source)

    for node_id, node in plan.nodes.items():
        if node_id in broken:
            continue
        spec = catalog[node["block"]].spec
        for port in spec.inputs:
            if port.required and not plan.inputs[node_id].get(port.port_id):
                fail(
                    t(
                        "Input {port} of {block} is not wired.",
                        port=t(port.label),
                        block=label_of(node, catalog),
                    ),
                    node_id,
                )

    try:
        order = list(TopologicalSorter(graph).static_order())
    except CycleError as cycle:
        loop = [str(item) for item in cycle.args[1]]
        names = " → ".join(label_of(plan.nodes[item], catalog) for item in loop)
        for node_id in set(loop):
            plan.node_errors.setdefault(node_id, []).append(
                t("There is a wiring loop: {path}.", path=names)
            )
        plan.errors.append(t("There is a wiring loop: {path}.", path=names))
        order = []
    plan.order = [node_id for node_id in order if node_id not in broken]

    is_sink = sinks or (lambda block: not block.spec.outputs)
    outputs = [
        node_id
        for node_id, node in plan.nodes.items()
        if node_id not in broken and is_sink(catalog[node["block"]])
    ]
    if not outputs and not broken:
        fail(t("The diagram has no output: add one so its result goes somewhere."))
    # Blocks that feed no output and record nothing do work nobody sees.
    reaches: set[str] = set(outputs)
    pending = list(outputs)
    while pending:
        current = pending.pop()
        for source in graph.get(current, ()):
            if source not in reaches:
                reaches.add(source)
                pending.append(source)
    recorded = {node_id for node_id, ports in plan.recorded.items() if ports}
    pending = list(recorded - reaches)
    seen = set(pending)
    while pending:
        current = pending.pop()
        for source in graph.get(current, ()):
            if source not in seen:
                seen.add(source)
                pending.append(source)
    useful = reaches | seen
    for node_id, node in plan.nodes.items():
        if node_id not in broken and node_id not in useful and outputs:
            warn(
                t(
                    "{block} leads to no output and records nothing.",
                    block=label_of(node, catalog),
                ),
                node_id,
            )
    return plan


@dataclass
class Values:
    """What one run gave: every output port's value, and why blocks gave none."""

    values: dict[tuple[str, str], Any] = field(default_factory=dict)
    missing: dict[str, NoData] = field(default_factory=dict)

    def get(self, node_id: str, port_id: str, default: Any = None) -> Any:
        return self.values.get((node_id, port_id), default)

    def outputs(self, node_id: str) -> dict[str, Any]:
        return {port: value for (node, port), value in self.values.items() if node == node_id}


def _coerce(value: Any, source_type: str, target_types: tuple[str, ...]) -> Any:
    if isinstance(value, NoData) or source_type in target_types:
        return value
    if (source_type, "number") in COERCIONS and "number" in target_types:
        if isinstance(value, Result):
            if value.value is None:
                return NoData(value.message or t("No score."), value.label)
            return float(value.value)
    return value


def execute(
    plan: Plan,
    catalog: Mapping[str, Block],
    context: Context | None = None,
    *,
    preset: Mapping[tuple[str, str], Any] | None = None,
) -> Values:
    """Run every block of ``plan`` in order on one window.

    ``preset`` gives values for some output ports in advance (an app that computed them once
    for many diagrams); a node whose every output is preset is not run.
    """

    if not plan.valid:
        raise ValueError(t("The diagram is not valid: {errors}", errors=" ".join(plan.errors)))
    context = context or Context()
    run = Values()
    for (node_id, port_id), value in (preset or {}).items():
        run.values[(node_id, port_id)] = value
    for node_id in plan.order:
        node = plan.nodes[node_id]
        block = catalog[node["block"]]
        spec = block.spec
        if spec.outputs and all((node_id, port.port_id) in run.values for port in spec.outputs):
            continue
        label = label_of(node, catalog)
        inputs: dict[str, Any] = {}
        missing: NoData | None = None
        # An optional input whose wire carries no value counts as not wired, unless nothing
        # wired to the block has a value (then the block has nothing to work on).
        first_missing: NoData | None = None
        any_value = False
        for port in spec.inputs:
            wires = plan.inputs.get(node_id, {}).get(port.port_id, [])
            found = []
            for wire in wires:
                source = catalog[plan.nodes[wire.source]["block"]].spec.output(wire.source_port)
                value = run.values.get(
                    (wire.source, wire.source_port),
                    run.missing.get(wire.source) or NoData(t("No value."), wire.source),
                )
                found.append(_coerce(value, source.type if source else "", port.types))
            gaps = [item for item in found if isinstance(item, NoData)]
            first_missing = first_missing or (gaps[0] if gaps else None)
            any_value = any_value or len(gaps) < len(found)
            if spec.runs_on_missing:
                inputs[port.port_id] = found if port.multiple else (found[0] if found else None)
            elif port.multiple:
                inputs[port.port_id] = found
                if gaps:
                    missing = missing or gaps[0]
            elif found and not gaps:
                inputs[port.port_id] = found[0]
            elif found:
                inputs[port.port_id] = None
                if port.required:
                    missing = missing or gaps[0]
            else:
                inputs[port.port_id] = None
        if missing is None and first_missing is not None and not any_value:
            if not spec.runs_on_missing:
                missing = first_missing
        if missing is not None:
            run.missing[node_id] = missing
            for port in spec.outputs:
                run.values[(node_id, port.port_id)] = missing
            continue
        try:
            given = block.run(
                inputs,
                plan.parameters.get(node_id) or spec.parameters(),
                replace(context, node_id=node_id),
            )
        except Exception as exc:  # One block failing never stops the others.
            LOGGER.warning("Block %s (%s) failed: %s", node_id, spec.block_id, exc)
            reason = NoData(
                t("{block} failed: {error}", block=label, error=f"{type(exc).__name__}: {exc}"),
                node_id,
            )
            run.missing[node_id] = reason
            for port in spec.outputs:
                run.values[(node_id, port.port_id)] = reason
            continue
        given = given or {}
        for port in spec.outputs:
            if port.port_id in given:
                value = given[port.port_id]
            else:
                value = NoData(
                    t("{block} gave no {port}.", block=label, port=port.port_id), node_id
                )
            run.values[(node_id, port.port_id)] = value
    return run


__all__ = [
    "MAX_EDGES",
    "MAX_NODES",
    "VERSION",
    "Plan",
    "Values",
    "Wire",
    "compile_diagram",
    "execute",
    "label_of",
]
