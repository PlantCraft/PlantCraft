"""Slow drift of the controller output while the loop holds its setpoint.

A transmitter that drifts makes the controller hold the wrong reading: the PV stays at the
setpoint while the process moves away from it, and the only trace in the loop's own data is the
output walking steadily in one direction to keep the drifting reading in place. A fouling
exchanger, a wearing valve or a feed that changes slowly leave the same trace, so the finding
names all of them and asks for a check against another measurement.

The window is cut in blocks (an hour by default) and the output's median taken in each, so noise
and fast cycles cancel. The drift is the median change from one block to the next (a single step,
a calibration or a setpoint move, does not move a median), counted only between blocks where the
setpoint held; it is scored when most of those changes go the same way.
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
    MethodStatus,
    OutputPort,
)
from plantcraft_sdk.methods.findings import fmt_number as _n
from plantcraft_sdk.methods.findings import fmt_percent as _pct
from plantcraft_sdk.methods.utils import (
    estimate_sample_seconds,
    insufficient_data,
    missing_columns,
    normalized_score,
    numeric_frame,
    result,
    status_from_score,
)
from pydantic import BaseModel, Field

from linkcraft.methods.references import BAUER_2016_CPM_SURVEY


class OutputDriftInput(BaseModel):
    dataset: LoopDataset


class OutputDriftParameters(BaseModel):
    block_minutes: float = Field(
        default=60.0, gt=0.0, description="Length of the blocks whose median output is compared."
    )
    drift_per_day: float = Field(
        default=6.0,
        gt=0.0,
        description="Output drift (% of OP per day) that scores 100.",
    )
    min_consistency: float = Field(
        default=0.6,
        ge=0.5,
        le=1.0,
        description="Share of block-to-block changes in the drift's direction from which it counts.",
    )
    full_consistency: float = Field(
        default=0.8,
        gt=0.5,
        le=1.0,
        description="Share of changes in the drift's direction at which it counts fully.",
    )
    min_blocks: int = Field(
        default=8, ge=3, description="Fewest comparable blocks (setpoint held) to judge a drift."
    )


METHOD_METADATA = MethodMetadata(
    method_id="output_drift",
    name="Output drift",
    description="The output walking steadily one way while the PV holds its setpoint: a drifting "
    "transmitter, fouling or a slow load change.",
    maturity=MethodMaturity.ENGINEERING_HEURISTIC,
    references=[BAUER_2016_CPM_SURVEY],
    required_signals=["op"],
    implemented_formula=(
        "m_k = median OP in block k (block_minutes); d_k = m_k - m_(k-1) for blocks whose median "
        "SP equals the one before; drift = median(d) * blocks per day; consistency = share of d "
        "with the sign of the drift; score = 100*min(1, |drift|/drift_per_day)"
        "*clip((consistency-min_consistency)/(full_consistency-min_consistency), 0, 1)."
    ),
    assumptions=[
        "The OP is in percent and the loop is in automatic for most of the window.",
        "A steady walk of the output over hours is not the controller's normal work.",
    ],
    limitations=[
        "It cannot tell a drifting transmitter from fouling or a slow load change: confirm "
        "against a redundant measurement, a lab result or a balance.",
        "A drift slower than the window's length, or one calibrated back inside it, reads weaker.",
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
        ),
        InputPort(port_id="sp", semantic_type="setpoint", dtype="timeseries_float", required=False),
    ],
    input_schema=OutputDriftInput,
    parameter_schema=OutputDriftParameters,
    output_ports=[
        OutputPort(
            port_id="drift_per_day", semantic_type="rate", dtype="float", unit="percent/day"
        ),
        OutputPort(port_id="consistency", semantic_type="fraction", dtype="float"),
    ],
    output_schema=MethodResult,
    metadata=METHOD_METADATA,
)
from linkcraft.i18n import t


def run(input_data: OutputDriftInput, parameters: OutputDriftParameters) -> MethodResult:
    dataset = input_data.dataset
    missing = missing_columns(dataset, ["op"])
    if missing:
        return insufficient_data(
            METHOD_METADATA, dataset.loop_id, t("OP is required for output drift."), missing
        )
    with_sp = not missing_columns(dataset, ["sp"])
    frame = numeric_frame(dataset, ["op", "sp"] if with_sp else ["op"])
    dt = estimate_sample_seconds(dataset, frame.index)
    per_block = max(1, int(round(parameters.block_minutes * 60.0 / max(dt, 1e-9))))
    blocks = np.arange(len(frame)) // per_block
    medians = frame.groupby(blocks).median()
    counts = frame.groupby(blocks).size()
    # Only whole blocks: a short last block's median is a different average.
    medians = medians[counts.to_numpy() >= 0.5 * per_block]
    op = medians["op"].to_numpy(dtype=float)
    changes = np.diff(op)
    if with_sp:
        sp = medians["sp"].to_numpy(dtype=float)
        scale = max(float(np.nanmedian(np.abs(sp))) if sp.size else 0.0, 1e-9)
        held = np.abs(np.diff(sp)) <= 1e-3 * scale
        changes = changes[held]
    if changes.size < parameters.min_blocks - 1:
        return insufficient_data(
            METHOD_METADATA,
            dataset.loop_id,
            t(
                "Too few hours with a steady setpoint to judge a drift ({count}).",
                count=int(changes.size),
            ),
        )
    blocks_per_day = 24.0 * 60.0 / parameters.block_minutes
    step = float(np.median(changes))
    drift = step * blocks_per_day
    consistency = float(np.mean(np.sign(changes) == np.sign(step))) if step else 0.0
    span = parameters.full_consistency - parameters.min_consistency
    weight = float(np.clip((consistency - parameters.min_consistency) / max(span, 1e-9), 0.0, 1.0))
    score = normalized_score(abs(drift), parameters.drift_per_day) * weight
    status: MethodStatus = status_from_score(score)
    return result(
        metadata=METHOD_METADATA,
        loop_id=dataset.loop_id,
        status=status,
        score=score,
        message=t("Output drift calculated."),
        metrics={
            "drift_per_day": drift,
            "consistency": consistency,
            "blocks_compared": int(changes.size),
            "block_minutes": parameters.block_minutes,
            "window_change": float(op[-1] - op[0]) if op.size else 0.0,
            "valid_samples": int(len(frame)),
        },
    )


def describe(metrics: dict) -> str:
    drift = float(metrics.get("drift_per_day") or 0.0)
    consistency = metrics.get("consistency")
    if abs(drift) < 1e-9:
        return t("The output holds steady: no drift.")
    return t(
        "The output drifts {direction} by about {drift} % per day ({consistency} of the block-to-block "
        "changes the same way) while the setpoint holds: a drifting transmitter, fouling or a "
        "slow load change.",
        direction=t("up") if drift > 0 else t("down"),
        drift=_n(abs(drift)),
        consistency=_pct(consistency),
    )
