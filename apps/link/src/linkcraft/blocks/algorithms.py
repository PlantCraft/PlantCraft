"""The algorithms PlantCraft Analytics ships (read-only; people save copies and change those).

Six examples, each clear about what it is for and tagged (owner, Link round 6): Signal quality
("data quality", on every signal); Flow loop, Level loop, Surge level and Temperature or pressure
loop ("control loop", each the start of the loops of its type, ``catalog.loop_types``); Unit twin
("digital twin", a process model beside the plant, on assets). The demo plant adds its own
calibrated twins (``models.examples``). Loop health, Control valve and Oscillation and noise of
0.3 live on inside Flow loop; a loop that named one runs Flow loop. What depends on the kind of
loop (a flow is faster than a temperature) stays in the loop types' parameters, under each
algorithm's own.
"""

from __future__ import annotations

from typing import Any

from plantcraft_sdk.blocks import VERSION, AlgorithmDocs

from linkcraft.catalog.loop_types import (
    ALGORITHM_OF_PROTOCOL,
    DEFAULT_ALGORITHM,
    FLOW_LOOP,
    LEVEL_LOOP,
    SLOW_LOOP,
)
from linkcraft.catalog.signal_checks import CHECKS

DEFAULT = DEFAULT_ALGORITHM
SIGNAL_QUALITY = "signal_quality"
# The protocols of 0.2 and the algorithms of 0.3 -> the algorithm that replaces each.
LEGACY: dict[str, str] = ALGORITHM_OF_PROTOCOL
# The tags of the shipped algorithms (translated where they are shown).
CONTROL_LOOP, DATA_QUALITY, DIGITAL_TWIN = "control loop", "data quality", "digital twin"

COLUMNS = {"input": 40, "gate": 330, "method": 640, "logic": 960, "output": 1260}
ROW = 130


class _Diagram:
    """A small builder so each algorithm below reads as its blocks and wires."""

    def __init__(self) -> None:
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self.rows: dict[str, int] = {}

    def node(
        self,
        node_id: str,
        block: str,
        column: str,
        *,
        parameters: dict[str, Any] | None = None,
        record: list[str] | None = None,
        label: str = "",
    ) -> str:
        row = self.rows.get(column, 0)
        self.rows[column] = row + 1
        node: dict[str, Any] = {
            "id": node_id,
            "block": block,
            "parameters": dict(parameters or {}),
            "x": COLUMNS[column],
            "y": 40 + ROW * row,
        }
        if record:
            node["record"] = list(record)
        if label:
            node["label"] = label
        self.nodes.append(node)
        return node_id

    def wire(self, source: str, source_port: str, target: str, target_port: str) -> None:
        self.edges.append(
            {
                "source": source,
                "source_port": source_port,
                "target": target,
                "target_port": target_port,
            }
        )

    def done(self) -> dict[str, Any]:
        return {"version": VERSION, "nodes": self.nodes, "edges": self.edges}


def _loop_inputs(diagram: _Diagram, roles: tuple[str, ...] = ("pv", "sp", "op", "mode")) -> str:
    """The loop's signals into the loop data check; returns the check's node id."""

    for role in roles:
        block = "input.state" if role == "mode" else "input.signal"
        diagram.node(role, block, "input", parameters={"role": role})
    gate = diagram.node("data", "dq.loop_data", "gate")
    for role in roles:
        diagram.wire(role, "value", gate, role)
    return gate


def _method(
    diagram: _Diagram,
    method_id: str,
    ports: tuple[str, ...],
    *,
    gate: str = "data",
    parameters: dict[str, Any] | None = None,
    record: list[str] | None = None,
) -> str:
    node_id = diagram.node(
        method_id, f"cpm.{method_id}", "method", parameters=parameters, record=record
    )
    for port in ports:
        if port == "x":  # sampling quality reads the PV's sample times as recorded
            diagram.wire("pv", "recorded", node_id, "x")
        else:
            diagram.wire(gate, port, node_id, port)
    return node_id


def _health(
    diagram: _Diagram,
    scored: list[str],
    context: list[str] = (),  # type: ignore[assignment]
    diagnostics: list[str] = (),  # type: ignore[assignment]
) -> None:
    health = diagram.node("health", "output.loop_health", "output")
    for node_id in scored:
        diagram.wire(node_id, "result", health, "methods")
    for node_id in context:
        diagram.wire(node_id, "result", health, "context")
    for node_id in diagnostics:
        diagram.wire(node_id, "result", health, "diagnostics")
    diagram.wire("data", "verdict", health, "data")


def _flow_loop() -> dict[str, Any]:
    """Tracking, output, valve and sampling scored; stiction, oscillation and noise flagged (a
    copy adds a Valve result or records the measures it wants trended)."""

    d = _Diagram()
    _loop_inputs(d)
    error = _method(d, "error_metrics_basic", ("pv", "sp"))
    saturation = _method(d, "op_saturation_fraction", ("op",))
    travel = _method(d, "op_travel_reversal", ("op",))
    sampling = _method(d, "sampling_quality", ("x",))
    context = [
        _method(d, "setpoint_activity", ("sp",)),
        _method(d, "manual_mode_fraction", ("mode",)),
        _method(d, "operational_interventions", ("sp", "mode")),
    ]
    stiction = _method(d, "stiction_screening", ("pv", "op"))
    oscillation = _method(d, "oscillation_autocorrelation", ("pv", "sp"))
    noise = _method(d, "sensor_noise_ratio", ("pv",))
    _health(d, [error, saturation, travel, sampling], context, [stiction, oscillation, noise])
    return d.done()


def _level_loop() -> dict[str, Any]:
    """A level held tight at its setpoint: the error, the output and the valve scored."""

    d = _Diagram()
    _loop_inputs(d)
    scored = [
        _method(d, "error_metrics_basic", ("pv", "sp")),
        _method(d, "op_saturation_fraction", ("op",)),
        _method(d, "op_travel_reversal", ("op",)),
        _method(d, "sampling_quality", ("x",)),
    ]
    context = [
        _method(d, "setpoint_activity", ("sp",)),
        _method(d, "manual_mode_fraction", ("mode",)),
    ]
    diagnostics = [
        _method(d, "oscillation_autocorrelation", ("pv", "sp")),
        _method(d, "stiction_screening", ("pv", "op")),
    ]
    _health(d, scored, context, diagnostics)
    return d.done()


def _slow_loop() -> dict[str, Any]:
    """A slow loop with dead time: the variance against minimum-variance control (Harris) with
    the error and the output; oscillation and stiction flagged."""

    d = _Diagram()
    _loop_inputs(d)
    scored = [
        _method(d, "harris_index", ("pv", "sp", "op")),
        _method(d, "error_metrics_basic", ("pv", "sp")),
        _method(d, "op_saturation_fraction", ("op",)),
        _method(d, "sampling_quality", ("x",)),
    ]
    context = [
        _method(d, "setpoint_activity", ("sp",)),
        _method(d, "manual_mode_fraction", ("mode",)),
        _method(d, "operational_interventions", ("sp", "mode")),
    ]
    diagnostics = [
        _method(d, "oscillation_autocorrelation", ("pv", "sp")),
        _method(d, "stiction_screening", ("pv", "op")),
    ]
    _health(d, scored, context, diagnostics)
    return d.done()


def _surge_level() -> dict[str, Any]:
    d = _Diagram()
    _loop_inputs(d)
    scored = [
        _method(
            d,
            "disturbance_attenuation",
            ("pv", "op"),
            parameters={
                "full_performance_factor": 0.5,
                "zero_performance_factor": 1.5,
                "assume_surge_level": True,
            },
        ),
        _method(
            d,
            "operating_band_fraction",
            ("pv",),
            parameters={"lower_limit": 20, "upper_limit": 80, "assume_surge_level": True},
        ),
        _method(d, "op_saturation_fraction", ("op",)),
        _method(d, "op_travel_reversal", ("op",), parameters={"reversal_epsilon": 0.1}),
        _method(d, "sampling_quality", ("x",), parameters={"recommended_sample_seconds": 20}),
    ]
    context = [
        _method(
            d,
            "operational_interventions",
            ("sp", "mode"),
            parameters={
                "reference_hours": 12,
                "full_performance_max": 2,
                "zero_performance_min": 12,
            },
        ),
        _method(d, "manual_mode_fraction", ("mode",)),
    ]
    _health(d, scored, context)
    return d.done()


UNIT_TWIN = "unit_twin"
# The process model every Link ships (``models.builtin``): first order plus dead time.
LOOP_MODEL_BLOCK = "model.fmu_plantcrafttwin_loopprocess"


def _unit_twin() -> dict[str, Any]:
    d = _Diagram()
    d.node("op", "input.signal", "input", parameters={"role": "op"}, label="Valve (OP)")
    d.node("pv", "input.signal", "input", parameters={"role": "pv"}, label="Measured (PV)")
    d.node(
        "model",
        LOOP_MODEL_BLOCK,
        "gate",
        record=["y", "y_residual"],
    )
    d.node("deviation", "model.deviation", "method", record=["t2"])
    d.node("result", "output.result", "output", parameters={"name": "Model deviation"})
    d.node("message", "output.message", "output")
    d.wire("op", "value", "model", "u")
    d.wire("pv", "value", "model", "y_measured")
    d.wire("model", "y_residual", "deviation", "residuals")
    d.wire("deviation", "result", "result", "in")
    d.wire("deviation", "result", "message", "in")
    return d.done()


def _signal_quality() -> dict[str, Any]:
    d = _Diagram()
    d.node("signal", "input.signal", "input", parameters={"role": "signal"})
    d.node("reference", "input.signal", "input", parameters={"role": "reference"})
    verdict = d.node("verdict", "output.signal_quality", "output")
    for check_id in CHECKS:
        node_id = check_id.removeprefix("sq_")
        d.node(node_id, f"dq.{node_id}", "method")
        d.wire("signal", "recorded", node_id, "x")
        if check_id == "sq_drift":
            d.wire("reference", "recorded", node_id, "reference")
        d.wire(node_id, "result", verdict, "checks")
    return d.done()


SYSTEM: tuple[dict[str, Any], ...] = (
    {
        "algorithm_id": FLOW_LOOP,
        "name": "Flow loop",
        "tags": [CONTROL_LOOP],
        "description": "Tracking, output, valve travel and sampling make the health; stiction, "
        "oscillation and noise are flagged beside it; operator behaviour shown as context.",
        "subject_kind": "loop",
        "diagram": _flow_loop(),
        "docs": AlgorithmDocs(
            purpose="How well does a fast loop hold its setpoint, and is the valve, an "
            "oscillation or noise what limits it?",
            assets="Flow loops, and any loop whose type the record does not give (asset type "
            "loop) with at least a PV; it reads the PV, SP, OP and mode roles and uses those "
            "the loop has.",
            when="The start of every flow loop and of loops of unknown type. A level held "
            "tight uses Level loop, a level that absorbs upsets Surge level, a slow loop with "
            "dead time (temperature, pressure, composition) Temperature or pressure loop.",
            reading="The health (0 to 100) is the product of the PV-SP error, output "
            "saturation, valve travel and sampling components; the limiting method explains a "
            "low score. Stiction, oscillation and noise are flagged as diagnostics without "
            "changing the score; a copy can record the stiction index, the travel per hour or "
            "the oscillation period in the historian, so wear and cycling show over weeks "
            "(each a series per loop). Manual mode, setpoint moves and interventions are "
            "context. No health in manual, with the output parked or with unusable data.",
            assistant="Start from the limiting method's finding and the diagnostics. Treat "
            "stiction as a screening to confirm with a valve test; report an oscillation's "
            "period and compare it with other loops of the area before naming a cause. Say "
            "what to check in the plant (valve, transmitter, tuning, operation). Never suggest "
            "new controller settings yourself, and do not call a loop bad when it has no "
            "health: say why it has none.",
        ),
    },
    {
        "algorithm_id": LEVEL_LOOP,
        "name": "Level loop",
        "tags": [CONTROL_LOOP],
        "description": "A level held tight at its setpoint: error, output and valve travel "
        "make the health; oscillation and stiction flagged beside it.",
        "subject_kind": "loop",
        "diagram": _level_loop(),
        "docs": AlgorithmDocs(
            purpose="Does a level held at its setpoint stay there without wearing the valve?",
            assets="Level loops (asset type loop, loop type level) with a PV and an OP; SP and "
            "mode are used when the loop has them.",
            when="The start of every level loop: a reactor, a column bottom, a level whose "
            "setpoint matters. A buffer level meant to wander inside a band uses Surge level "
            "instead: there a moving level is the job.",
            reading="The health is the product of the PV-SP error, output saturation, valve "
            "travel and sampling. The level loop type allows the valve less travel than a "
            "flow. Oscillation and stiction are flagged without changing the score.",
            assistant="A level that cycles slowly with a sticky valve is common: say so when "
            "both are flagged. Do not recommend tightening a level that is meant to average "
            "its inflow; ask whether it is a surge level first.",
        ),
    },
    {
        "algorithm_id": "surge_level",
        "name": "Surge level",
        "tags": [CONTROL_LOOP],
        "description": "Attenuation and time in band for levels that must absorb upsets "
        "inside their band, with the output and sampling.",
        "subject_kind": "loop",
        "diagram": _surge_level(),
        "docs": AlgorithmDocs(
            purpose="Does a surge level absorb upsets inside its band, as it should?",
            assets="Level loops of buffer vessels (drums, tanks) with a PV and an OP; the "
            "band limits are parameters of the time-in-band block.",
            when="On levels meant to wander inside a band so the outflow stays smooth. A "
            "level held tight at its setpoint uses Level loop instead: there a moving level "
            "is a fault, here it is the job.",
            reading="The health is the product of disturbance attenuation, time in band, "
            "output saturation and valve travel and sampling. An amplification factor above "
            "1 means the level passes the upsets on downstream.",
            assistant="Judge the level by how smooth it keeps the outflow, not by how close "
            "it stays to its setpoint. Mention the band limits used when the level leaves "
            "it.",
        ),
    },
    {
        "algorithm_id": SLOW_LOOP,
        "name": "Temperature or pressure loop",
        "tags": [CONTROL_LOOP],
        "description": "A slow loop with dead time: its variance against minimum-variance "
        "control (Harris index), the error and the output; oscillation and stiction flagged.",
        "subject_kind": "loop",
        "diagram": _slow_loop(),
        "docs": AlgorithmDocs(
            purpose="Does a slow loop with dead time reject disturbances as well as its dead "
            "time allows?",
            assets="Temperature, pressure and composition loops (loop types temperature, "
            "pressure, composition) with a PV, an SP and an OP; the dead time is a parameter "
            "of the minimum-variance block, estimated from the OP-PV lag when left at 0.",
            when="The start of temperature, pressure and composition loops: furnaces, "
            "exchangers, column pressures, analysers. A fast loop uses Flow loop.",
            reading="The Harris index compares the error's variance with what minimum-variance "
            "control would leave given the dead time: 1 is the bound, 0.3 to 0.6 is usual for "
            "a well-tuned industrial loop (a copy can record its score in the historian). Error, "
            "saturation and sampling score with it; oscillation and stiction are diagnostics.",
            assistant="Say the dead time used and whether it was estimated: a wrong dead time "
            "moves the index. A low index with an oscillation points at tuning or the valve; "
            "a low index alone, at disturbances the loop cannot reject. Do not judge it in a "
            "window full of setpoint changes.",
        ),
    },
    {
        "algorithm_id": UNIT_TWIN,
        "name": "Unit twin",
        "tags": [DIGITAL_TWIN],
        "description": "A process model runs beside the plant on its own signals; the "
        "residuals are judged with T² against a calibration of normal operation.",
        "subject_kind": "asset",
        "diagram": _unit_twin(),
        "docs": AlgorithmDocs(
            purpose="Does the unit still behave as its process model says?",
            assets="Units, equipment or loops (any asset) whose signals feed the model: here "
            "the valve (OP role) and the measured value (PV role) of the asset itself; a "
            "signal block can also read a role of another asset or a signal by its id.",
            when="When a model of the unit exists (a published FMU, or the built-in first "
            "order plus dead time). Duplicate it, swap the model block for the unit's own, "
            "wire every input and measured output, name the assets and press Calibrate on "
            "the Deviation block over a period of normal operation.",
            reading="Every cycle the model is run over the window, each output starting where "
            "the plant measured it, and the residuals (measured minus predicted) of the "
            "judged part are compared with the calibration. Normal: the plant follows the "
            "model. Attention: it deviates for fewer runs than the persistence; problem: a "
            "lasting deviation, with the output that explains most of it and whether the "
            "plant is above or below the model. Unknown says why it could not judge.",
            assistant="Name the output that explains the deviation and its direction. A "
            "deviation on one output points at its sensor or at that part of the process; "
            "on all outputs, at the operation or the model. Never call a model wrong or a "
            "sensor failed from this alone: say what to check.",
        ),
    },
    {
        "algorithm_id": SIGNAL_QUALITY,
        "name": "Signal quality",
        "tags": [DATA_QUALITY],
        "description": "Every signal's recorded data checked for gaps, staleness, freezes, "
        "spikes, range, noise, resolution and drift.",
        "subject_kind": "signal",
        "diagram": _signal_quality(),
        "docs": AlgorithmDocs(
            purpose="Can each signal's recorded data be trusted?",
            assets="Every signal PlantCraft lists, number or text (text signals get only "
            "the availability and freshness checks), read as recorded.",
            when="Always, on a schedule: loops are judged only on signals it found usable, "
            "and its verdicts are published on each signal and asset for every app.",
            reading="Bad when any check is bad, suspect when any warns, good when all that "
            "could judge passed; the quality is 100 minus the worst check's score and the "
            "sentence is that check's. A signal's own settings can switch a check off.",
            assistant="Name the worst check and what to look at (source, transmitter, "
            "historian compression). A frozen or stale signal often looks normal on a trend: "
            "say so. Do not judge the process from a signal marked bad.",
        ),
    },
)

BY_ID = {item["algorithm_id"]: item for item in SYSTEM}


def system_algorithm(algorithm_id: str) -> dict[str, Any] | None:
    return BY_ID.get(LEGACY.get(algorithm_id, algorithm_id))
