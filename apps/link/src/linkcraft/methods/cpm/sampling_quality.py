"""Sampling interval and data-continuity assessment of the recorded samples.

The method judges how the source recorded the loop: the intervals between the PV's recorded
samples (``LoopDataset.raw``, as PlantCraft returned them without a ``step``), their median,
95th percentile and gaps. Its assumption is that the timestamps are acquisition times, so it
never reads the regular frame the other methods see: that frame is the analysis grid
(``LINKCRAFT_RESAMPLE_SECONDS``), whose interval is the grid step and whose interpolation hides
holes in the recording (gap G31, fixed 2026-10-19: on the default 60 s grid every loop scored 60
here and its health was capped at 40). Only a caller that hands no raw samples gets the frame's
timestamps, and the result says so (``timestamp_source``).
"""

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
    OutputPort,
)
from plantcraft_sdk.methods.findings import counted as _counted
from plantcraft_sdk.methods.findings import fmt_number as _n
from plantcraft_sdk.methods.utils import (
    clamp_score,
    insufficient_data,
    result,
    status_from_score,
)
from pydantic import BaseModel, Field

from linkcraft.i18n import t
from linkcraft.methods.references import (
    BAUER_2016_CPM_SURVEY,
    THORNHILL_CHOUDHURY_SHAH_2004_COMPRESSION,
)


class SamplingQualityInput(BaseModel):
    dataset: LoopDataset


class SamplingQualityParameters(BaseModel):
    recommended_sample_seconds: float = Field(default=30.0, gt=0.0)
    gap_multiplier: float = Field(default=2.5, gt=1.0)


METHOD_METADATA = MethodMetadata(
    method_id="sampling_quality",
    name="Sampling quality",
    description="Whether the PV is sampled often and regularly enough for the analysis.",
    maturity=MethodMaturity.ENGINEERING_HEURISTIC,
    references=[BAUER_2016_CPM_SURVEY, THORNHILL_CHOUDHURY_SHAH_2004_COMPRESSION],
    required_signals=["timestamp"],
    implemented_formula="evaluate median sampling interval, irregularity and gaps against a configured recommendation.",
    assumptions=[
        "Timestamps reflect acquisition time: the PV's recorded samples are judged, not the "
        "analysis grid."
    ],
    limitations=[
        "Historian compression (record on change) lengthens the intervals of a steady signal; "
        "such data really are coarser for CPM.",
        "When PlantCraft cannot return the recorded values of a crowded window (more than "
        "200,000 points) it returns one mean per grid step, and the method sees that step.",
    ],
)
METHOD_SPEC = MethodBlockSpec(
    method_id=METHOD_METADATA.method_id,
    version="1.0.0",
    input_ports=[
        InputPort(port_id="timestamp", semantic_type="timestamp", dtype="timeseries_datetime")
    ],
    input_schema=SamplingQualityInput,
    parameter_schema=SamplingQualityParameters,
    output_ports=[
        OutputPort(
            port_id="median_sample_seconds", semantic_type="duration", dtype="float", unit="seconds"
        ),
        OutputPort(port_id="gap_count", semantic_type="count", dtype="integer"),
    ],
    output_schema=MethodResult,
    metadata=METHOD_METADATA,
)


def _timestamps(dataset: LoopDataset) -> tuple[pd.DatetimeIndex | None, str]:
    """Acquisition times of the PV's recorded samples, else the frame's (and which it is)."""

    raw = dataset.raw
    if raw is not None and not raw.empty:
        if "pv" in raw.columns:
            recorded = pd.to_numeric(raw["pv"], errors="coerce").dropna().index
        else:
            recorded = raw.index[raw.notna().any(axis=1).to_numpy()]
        index = pd.DatetimeIndex(pd.to_datetime(recorded, errors="coerce")).dropna()
        return index.sort_values(), "recorded"
    if "timestamp" not in dataset.data:
        return None, "frame"
    stamps = pd.to_datetime(dataset.data["timestamp"], errors="coerce").dropna().sort_values()
    return pd.DatetimeIndex(stamps), "frame"


def run(input_data: SamplingQualityInput, parameters: SamplingQualityParameters) -> MethodResult:
    dataset = input_data.dataset
    stamps, source = _timestamps(dataset)
    if stamps is None:
        return insufficient_data(
            METHOD_METADATA,
            dataset.loop_id,
            t("Timestamps are required for sampling quality."),
            ["timestamp"],
        )
    if len(stamps) < 3:
        return insufficient_data(
            METHOD_METADATA, dataset.loop_id, t("At least three timestamps are required.")
        )
    diffs = pd.Series(stamps).diff().dropna().dt.total_seconds().to_numpy(dtype=float)
    diffs = diffs[diffs > 0]
    if not len(diffs):
        return insufficient_data(
            METHOD_METADATA, dataset.loop_id, t("No positive timestamp intervals were found.")
        )
    median = float(np.median(diffs))
    p95 = float(np.percentile(diffs, 95))
    gaps = int(np.sum(diffs > median * parameters.gap_multiplier))
    interval_penalty = max(0.0, median / parameters.recommended_sample_seconds - 1.0) * 60.0
    gap_penalty = min(40.0, 100.0 * gaps / len(diffs))
    score = clamp_score(interval_penalty + gap_penalty)
    return result(
        metadata=METHOD_METADATA,
        loop_id=dataset.loop_id,
        status=status_from_score(score),
        score=score,
        message=t("Sampling interval and continuity assessed."),
        metrics={
            "median_sample_seconds": median,
            "p95_sample_seconds": p95,
            "largest_gap_seconds": float(np.max(diffs)),
            "recommended_sample_seconds": parameters.recommended_sample_seconds,
            "gap_count": gaps,
            "interval_count": len(diffs),
            "timestamp_source": source,
            "performance_component": 100.0 - score,
        },
    )


def describe(metrics: dict) -> str:
    if metrics.get("timestamp_source") == "recorded":
        return t(
            "The PV was recorded every {median} s (median; recommended up to {recommended} s), "
            "with {gaps}.",
            median=_n(metrics.get("median_sample_seconds")),
            recommended=_n(metrics.get("recommended_sample_seconds")),
            gaps=_counted(metrics.get("gap_count"), "{count} gap", "{count} gaps"),
        )
    return t(
        "Median sampling of {median} s (recommended up to {recommended} s) and {gaps}.",
        median=_n(metrics.get("median_sample_seconds")),
        recommended=_n(metrics.get("recommended_sample_seconds")),
        gaps=_counted(metrics.get("gap_count"), "{count} gap", "{count} gaps"),
    )
