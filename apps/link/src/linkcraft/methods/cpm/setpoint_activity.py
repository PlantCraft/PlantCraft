"""Setpoint movement monitoring."""

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
from plantcraft_sdk.methods.findings import counted as _counted
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


class SetpointActivityInput(BaseModel):
    dataset: LoopDataset


class SetpointActivityParameters(BaseModel):
    change_threshold: float = Field(default=0.1, ge=0.0)
    max_changes_per_hour: float = Field(default=6.0, gt=0.0)


METHOD_METADATA = MethodMetadata(
    method_id="setpoint_activity",
    name="Setpoint activity",
    description="How often and how far the setpoint moves; context for the other methods, not a fault.",
    maturity=MethodMaturity.ENGINEERING_HEURISTIC,
    references=[BAUER_2016_CPM_SURVEY],
    required_signals=["sp"],
    implemented_formula="count abs(diff(sp)) above threshold; score=changes_per_hour/max_changes_per_hour.",
    assumptions=[
        "The SP is numeric and changes above the threshold represent significant "
        "moves by the operator or a supervisory layer."
    ],
    limitations=[
        "Frequent setpoint movement may be normal in recipes, transitions or APC-driven operation."
    ],
)

METHOD_SPEC = MethodBlockSpec(
    method_id=METHOD_METADATA.method_id,
    version=METHOD_METADATA.version,
    input_ports=[
        InputPort(port_id="sp", semantic_type="setpoint", dtype="timeseries_float", required=True)
    ],
    input_schema=SetpointActivityInput,
    parameter_schema=SetpointActivityParameters,
    output_ports=[
        OutputPort(port_id="changes_per_hour", semantic_type="rate", dtype="float", unit="1/hour"),
        OutputPort(port_id="total_abs_change", semantic_type="metric", dtype="float"),
    ],
    output_schema=MethodResult,
    metadata=METHOD_METADATA,
)
from linkcraft.i18n import t


def run(input_data: SetpointActivityInput, parameters: SetpointActivityParameters) -> MethodResult:
    dataset = input_data.dataset
    missing = missing_columns(dataset, ["sp"])
    if missing:
        return insufficient_data(
            METHOD_METADATA, dataset.loop_id, t("SP is required for setpoint activity."), missing
        )

    sp = numeric_series(dataset, "sp")
    if len(sp) < 2:
        return insufficient_data(
            METHOD_METADATA, dataset.loop_id, t("SP needs at least two valid samples.")
        )

    diffs = np.diff(sp.to_numpy(dtype=float))
    meaningful = np.abs(diffs) > parameters.change_threshold
    change_count = int(np.sum(meaningful))
    hours = duration_hours(dataset, sp.index)
    changes_per_hour = float(change_count / hours) if hours > 0 else 0.0
    total_abs_change = float(np.sum(np.abs(diffs[meaningful]))) if change_count else 0.0
    score = normalized_score(changes_per_hour, parameters.max_changes_per_hour)

    return result(
        metadata=METHOD_METADATA,
        loop_id=dataset.loop_id,
        status=status_from_score(score),
        score=score,
        message=t("Setpoint activity calculated."),
        metrics={
            "change_count": change_count,
            "changes_per_hour": changes_per_hour,
            "total_abs_change": total_abs_change,
            "change_threshold": parameters.change_threshold,
            "valid_samples": int(len(sp)),
        },
    )


def describe(metrics: dict) -> str:
    return t(
        "{changes} ({rate} per hour).",
        changes=_counted(
            metrics.get("change_count"), "{count} setpoint change", "{count} setpoint changes"
        ),
        rate=_n(metrics.get("changes_per_hour")),
    )
