"""Controller output travel and reversal monitoring.

A reversal counts when the output turns back by at least ``reversal_epsilon`` from its last
extreme (a hysteresis), as a valve's deadband sees it: sample-to-sample chatter smaller than that
(noise on a PV that a controller passes on) never moves the stem and is not a reversal, whatever
the sampling rate.
"""

from __future__ import annotations

import numpy as np
from plantcraft_sdk.methods import (
    InputPort,
    LoopDataset,
    MethodBlockSpec,
    MethodMaturity,
    MethodMetadata,
    MethodResult,
    OutputPort,
)
from plantcraft_sdk.methods.findings import fmt_number as _n
from plantcraft_sdk.methods.utils import (
    duration_hours,
    insufficient_data,
    missing_columns,
    normalized_score,
    numeric_series,
    result,
    status_from_score,
)
from pydantic import BaseModel, Field

from linkcraft.methods.references import BAUER_2016_CPM_SURVEY


class ValveTravelInput(BaseModel):
    dataset: LoopDataset


class ValveTravelParameters(BaseModel):
    max_travel_per_hour: float = Field(default=200.0, gt=0.0)
    max_reversals_per_hour: float = Field(default=60.0, gt=0.0)
    reversal_epsilon: float = Field(
        default=0.5,
        ge=0.0,
        description="Smallest turn back from the last extreme counted as a reversal, in % of OP.",
    )


METHOD_METADATA = MethodMetadata(
    method_id="op_travel_reversal",
    name="Controller output travel and reversals",
    description="How far the valve travels and how often it reverses: wear on the actuator.",
    maturity=MethodMaturity.ENGINEERING_HEURISTIC,
    references=[BAUER_2016_CPM_SURVEY],
    required_signals=["op"],
    implemented_formula=(
        "travel=sum(abs(diff(op))); reversals = turns of the OP back by at least "
        "reversal_epsilon from its last extreme (hysteresis); "
        "score=max(normalized travel rate, normalized reversal rate)."
    ),
    assumptions=["The OP is a reasonable approximation of the actuator movement."],
    limitations=[
        "OP movement does not always match stem movement when the actual "
        "valve position is not available."
    ],
)

METHOD_SPEC = MethodBlockSpec(
    method_id=METHOD_METADATA.method_id,
    version=METHOD_METADATA.version,
    input_ports=[
        InputPort(
            port_id="op",
            semantic_type="controller_output",
            dtype="timeseries_float",
            required=True,
            unit="percent",
        )
    ],
    input_schema=ValveTravelInput,
    parameter_schema=ValveTravelParameters,
    output_ports=[
        OutputPort(
            port_id="travel_per_hour", semantic_type="rate", dtype="float", unit="percent/hour"
        ),
        OutputPort(
            port_id="reversals_per_hour", semantic_type="rate", dtype="float", unit="1/hour"
        ),
    ],
    output_schema=MethodResult,
    metadata=METHOD_METADATA,
)
from linkcraft.i18n import t


def run(input_data: ValveTravelInput, parameters: ValveTravelParameters) -> MethodResult:
    dataset = input_data.dataset
    missing = missing_columns(dataset, ["op"])
    if missing:
        return insufficient_data(
            METHOD_METADATA,
            dataset.loop_id,
            t("OP is required for output travel monitoring."),
            missing,
        )

    op = numeric_series(dataset, "op")
    if len(op) < 2:
        return insufficient_data(
            METHOD_METADATA, dataset.loop_id, t("OP needs at least two valid samples.")
        )

    values = op.to_numpy(dtype=float)
    travel = float(np.sum(np.abs(np.diff(values))))
    reversals = hysteresis_reversals(values, parameters.reversal_epsilon)
    hours = duration_hours(dataset, op.index)
    travel_per_hour = float(travel / hours) if hours > 0 else 0.0
    reversals_per_hour = float(reversals / hours) if hours > 0 else 0.0
    score = max(
        normalized_score(travel_per_hour, parameters.max_travel_per_hour),
        normalized_score(reversals_per_hour, parameters.max_reversals_per_hour),
    )

    return result(
        metadata=METHOD_METADATA,
        loop_id=dataset.loop_id,
        status=status_from_score(score),
        score=score,
        message=t("Controller-output travel and reversals calculated."),
        metrics={
            "travel": travel,
            "travel_per_hour": travel_per_hour,
            "reversals": reversals,
            "reversals_per_hour": reversals_per_hour,
            "valid_samples": int(len(op)),
        },
    )


def hysteresis_reversals(values: np.ndarray, epsilon: float) -> int:
    """Turns of the signal back by more than ``epsilon`` from its last extreme."""

    clean = np.asarray(values, dtype=float)
    clean = clean[np.isfinite(clean)]
    if clean.size < 3:
        return 0
    if epsilon <= 0:
        moves = np.diff(clean)
        moves = moves[moves != 0]
        return int(np.sum(np.sign(moves[1:]) != np.sign(moves[:-1]))) if moves.size > 1 else 0
    reversals = 0
    direction = 0
    extreme = anchor = clean[0]
    for value in clean[1:]:
        if direction == 0:
            if abs(value - anchor) > epsilon:
                direction, extreme = (1 if value > anchor else -1), value
        elif direction * (value - extreme) > 0:
            extreme = value
        elif direction * (extreme - value) > epsilon:
            reversals += 1
            direction, extreme = -direction, value
    return reversals


def describe(metrics: dict) -> str:
    return t(
        "The output travelled {travel}% per hour, with {reversals} reversals per hour.",
        travel=_n(metrics.get("travel_per_hour")),
        reversals=_n(metrics.get("reversals_per_hour")),
    )
