"""Disturbance-attenuation performance for surge-drum level loops."""

from __future__ import annotations

import numpy as np
from plantcraft_sdk.methods import (
    InputPort,
    LoopDataset,
    MethodBlockSpec,
    MethodMaturity,
    MethodMetadata,
    MethodResult,
    MethodStatus,
    OutputPort,
)
from plantcraft_sdk.methods.findings import counted as _counted
from plantcraft_sdk.methods.utils import (
    clamp_score,
    insufficient_data,
    missing_columns,
    numeric_frame,
    result,
    status_from_score,
)
from pydantic import BaseModel, Field

from linkcraft.methods.cpm._surge_level import not_a_surge_level
from linkcraft.methods.references import (
    BAUER_2016_CPM_SURVEY,
    SHINSKEY_1996_PROCESS_CONTROL_SYSTEMS,
)


class AttenuationInput(BaseModel):
    dataset: LoopDataset


class AttenuationParameters(BaseModel):
    pv_range: float = Field(default=100.0, gt=0.0)
    op_range: float = Field(default=100.0, gt=0.0)
    full_performance_factor: float = Field(default=0.5, ge=0.0)
    zero_performance_factor: float = Field(default=1.5, gt=0.0)
    movement_epsilon: float = Field(default=0.01, ge=0.0)
    assume_surge_level: bool = Field(
        default=False,
        description="Run on a loop whose asset record gives no loop type (Surge level algorithm).",
    )


METHOD_METADATA = MethodMetadata(
    method_id="disturbance_attenuation",
    name="Disturbance attenuation",
    description="How much of the incoming disturbance the loop removes from the PV.",
    maturity=MethodMaturity.ENGINEERING_HEURISTIC,
    references=[BAUER_2016_CPM_SURVEY, SHINSKEY_1996_PROCESS_CONTROL_SYSTEMS],
    required_signals=["pv", "op"],
    implemented_formula="amplification=(normalized OP travel)/(normalized PV travel); lower amplification means better attenuation.",
    assumptions=[
        "The loop is a surge level that uses its inventory to dampen disturbances: the loop "
        "type is level, or the algorithm says so (assume_surge_level)."
    ],
    limitations=[
        "Wrong PV or OP ranges make the movement ratio incomparable.",
        "Not applicable to loops that must hold their setpoint (flow, pressure, temperature, "
        "composition) or whose loop type is unknown.",
    ],
)

METHOD_SPEC = MethodBlockSpec(
    method_id=METHOD_METADATA.method_id,
    version="1.0.0",
    input_ports=[
        InputPort(port_id="pv", semantic_type="process_variable", dtype="timeseries_float"),
        InputPort(port_id="op", semantic_type="controller_output", dtype="timeseries_float"),
    ],
    input_schema=AttenuationInput,
    parameter_schema=AttenuationParameters,
    output_ports=[
        OutputPort(port_id="amplification_factor", semantic_type="ratio", dtype="float"),
        OutputPort(
            port_id="performance_component", semantic_type="score", dtype="float", unit="percent"
        ),
    ],
    output_schema=MethodResult,
    metadata=METHOD_METADATA,
)
from linkcraft.i18n import t


def run(input_data: AttenuationInput, parameters: AttenuationParameters) -> MethodResult:
    dataset = input_data.dataset
    reason = not_a_surge_level(dataset, parameters.assume_surge_level)
    if reason is not None:
        return result(
            metadata=METHOD_METADATA,
            loop_id=dataset.loop_id,
            status=MethodStatus.NOT_APPLICABLE,
            score=0.0,
            message=reason,
        )
    missing = missing_columns(dataset, ["pv", "op"])
    if missing:
        return insufficient_data(
            METHOD_METADATA,
            dataset.loop_id,
            t("PV and OP are required for attenuation performance."),
            missing,
        )
    frame = numeric_frame(dataset, ["pv", "op"])
    if len(frame) < 3:
        return insufficient_data(
            METHOD_METADATA,
            dataset.loop_id,
            t("At least three aligned PV and OP samples are required."),
        )
    pv_travel = (
        float(np.sum(np.abs(np.diff(frame["pv"].to_numpy(dtype=float))))) / parameters.pv_range
    )
    op_travel = (
        float(np.sum(np.abs(np.diff(frame["op"].to_numpy(dtype=float))))) / parameters.op_range
    )
    if pv_travel <= parameters.movement_epsilon:
        return insufficient_data(
            METHOD_METADATA,
            dataset.loop_id,
            t("PV movement is too small for a stable amplification factor."),
        )
    factor = op_travel / pv_travel
    span = max(parameters.zero_performance_factor - parameters.full_performance_factor, 1e-9)
    performance = clamp_score(100.0 * (parameters.zero_performance_factor - factor) / span)
    score = 100.0 - performance
    return result(
        metadata=METHOD_METADATA,
        loop_id=dataset.loop_id,
        status=status_from_score(score),
        score=score,
        message=t("Normalized OP/PV amplification calculated."),
        metrics={
            "pv_travel_normalized": pv_travel,
            "op_travel_normalized": op_travel,
            "amplification_factor": factor,
            "performance_component": performance,
            "valid_samples": len(frame),
        },
    )


def describe(metrics: dict) -> str:
    factor = metrics.get("amplification_factor")
    times = _counted(factor, "{count} time", "{count} times")
    if factor is not None and factor > 1:
        return t(
            "The output moves {times} the normalized PV movement: the control passes "
            "disturbances on instead of absorbing them in the level.",
            times=times,
        )
    return t(
        "The output moves {times} the normalized PV movement: the level absorbs the disturbances.",
        times=times,
    )
