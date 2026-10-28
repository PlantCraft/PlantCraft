"""Availability: how much of the window each signal actually covers."""

from __future__ import annotations

import numpy as np
import pandas as pd
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
from plantcraft_sdk.methods.findings import fmt_percent as _pct
from plantcraft_sdk.methods.utils import insufficient_data, result
from pydantic import BaseModel, Field

from linkcraft.i18n import t
from linkcraft.methods.quality._common import (
    numeric,
    present_signals,
    raw_frame,
    window,
)


class AvailabilityInput(BaseModel):
    dataset: LoopDataset


class AvailabilityParameters(BaseModel):
    max_gap_seconds: float = Field(
        default=600.0,
        gt=0.0,
        description="Maximum interval between samples before it counts as missing data.",
    )
    min_coverage: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Minimum PV coverage for the data to be usable.",
    )


METHOD_METADATA = MethodMetadata(
    method_id="dq_availability",
    name="Signal availability",
    description="Whether the loop's signals have enough samples in the window, and how big the gaps are.",
    maturity=MethodMaturity.ENGINEERING_HEURISTIC,
    required_signals=["pv"],
    implemented_formula=(
        "coverage = 1 - sum(max(0, interval - max_interval)) / window duration, "
        "per signal, over the raw samples."
    ),
    assumptions=[
        "Historians with compression only record changes; intervals up to the "
        "configured maximum count as valid data."
    ],
    limitations=[
        "Does not check whether the value is correct, only whether it exists.",
        "Does not tell a communication failure from stopped equipment.",
    ],
)
METHOD_SPEC = MethodBlockSpec(
    method_id=METHOD_METADATA.method_id,
    version="1.0.0",
    input_ports=[InputPort(port_id="pv", semantic_type="process_value", dtype="timeseries_float")],
    input_schema=AvailabilityInput,
    parameter_schema=AvailabilityParameters,
    output_ports=[OutputPort(port_id="coverage_pv", semantic_type="ratio", dtype="float")],
    output_schema=MethodResult,
    metadata=METHOD_METADATA,
)


def coverage(
    times: pd.DatetimeIndex, start: pd.Timestamp, end: pd.Timestamp, max_gap: float
) -> tuple[float, float]:
    """Covered fraction of [start, end] and the largest gap in seconds."""

    duration = (end - start).total_seconds()
    inside = times[(times >= start) & (times <= end)].sort_values().unique()
    if not len(inside):
        return 0.0, duration
    edges = (
        pd.DatetimeIndex([start]).append(pd.DatetimeIndex(inside)).append(pd.DatetimeIndex([end]))
    )
    gaps = (edges[1:] - edges[:-1]).total_seconds().to_numpy()
    missing = float(np.clip(gaps - max_gap, 0.0, None).sum())
    return max(0.0, 1.0 - missing / duration), float(gaps.max())


def run(input_data: AvailabilityInput, parameters: AvailabilityParameters) -> MethodResult:
    dataset = input_data.dataset
    frame = raw_frame(dataset)
    span = window(dataset, frame)
    if "pv" not in frame.columns or span is None:
        return insufficient_data(
            METHOD_METADATA, dataset.loop_id, t("No PV in the analysed window."), ["pv"]
        )
    start, end = span
    metrics: dict[str, float | bool | None] = {}
    for name in present_signals(frame) or ["pv"]:
        values = numeric(frame[name]) if name != "mode" else frame[name].dropna()
        ratio, largest = coverage(
            pd.DatetimeIndex(values.index), start, end, parameters.max_gap_seconds
        )
        metrics[f"coverage_{name}"] = round(ratio, 4)
        metrics[f"largest_gap_seconds_{name}"] = round(largest, 1)
    pv_coverage = float(metrics.get("coverage_pv") or 0.0)
    apt = pv_coverage >= parameters.min_coverage
    metrics["apt"] = apt
    metrics["min_coverage"] = parameters.min_coverage
    score = round(100.0 * (1.0 - pv_coverage), 1)
    status = MethodStatus.OK if apt else MethodStatus.BAD
    message = (
        t("PV covers {coverage} of the window.", coverage=_pct(pv_coverage))
        if apt
        else t(
            "PV covers only {coverage} of the window (minimum {minimum}).",
            coverage=_pct(pv_coverage),
            minimum=_pct(parameters.min_coverage),
        )
    )
    return result(
        metadata=METHOD_METADATA,
        loop_id=dataset.loop_id,
        status=status,
        score=score,
        message=message,
        metrics=metrics,
    )
