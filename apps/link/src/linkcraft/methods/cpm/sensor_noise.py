"""Sensor noise screening using high-frequency variation."""

from __future__ import annotations

import math

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
from plantcraft_sdk.methods.findings import fmt_percent as _pct
from plantcraft_sdk.methods.utils import (
    insufficient_data,
    missing_columns,
    normalized_score,
    numeric_series,
    result,
    status_from_score,
)
from pydantic import BaseModel, Field

from linkcraft.methods.references import BAUER_2016_CPM_SURVEY


class SensorNoiseInput(BaseModel):
    dataset: LoopDataset
    signal: str = "pv"


class SensorNoiseParameters(BaseModel):
    noise_ratio_threshold: float = Field(default=0.35, gt=0.0)
    noise_abs_tolerance: float = Field(default=0.50, gt=0.0)


METHOD_METADATA = MethodMetadata(
    method_id="sensor_noise_ratio",
    name="Sensor noise ratio",
    description="High-frequency noise as a share of the measurement's total variation.",
    maturity=MethodMaturity.ENGINEERING_HEURISTIC,
    references=[BAUER_2016_CPM_SURVEY],
    required_signals=["pv"],
    implemented_formula="high_frequency_std=std(diff(signal))/sqrt(2); noise_ratio=high_frequency_std/std(signal); score=high_frequency_std/noise_abs_tolerance.",
    assumptions=["High-frequency moves between samples approximate the measurement noise."],
    limitations=["Real fast dynamics may be classified as noise without the process context."],
)

METHOD_SPEC = MethodBlockSpec(
    method_id=METHOD_METADATA.method_id,
    version=METHOD_METADATA.version,
    input_ports=[
        InputPort(
            port_id="pv", semantic_type="process_variable", dtype="timeseries_float", required=True
        )
    ],
    input_schema=SensorNoiseInput,
    parameter_schema=SensorNoiseParameters,
    output_ports=[OutputPort(port_id="noise_ratio", semantic_type="metric", dtype="float")],
    output_schema=MethodResult,
    metadata=METHOD_METADATA,
)
from linkcraft.i18n import t


def run(input_data: SensorNoiseInput, parameters: SensorNoiseParameters) -> MethodResult:
    dataset = input_data.dataset
    missing = missing_columns(dataset, [input_data.signal])
    if missing:
        return insufficient_data(
            METHOD_METADATA,
            dataset.loop_id,
            t("Signal {signal} is required for noise screening.", signal=input_data.signal),
            missing,
        )

    series = numeric_series(dataset, input_data.signal)
    if len(series) < 3:
        return insufficient_data(
            METHOD_METADATA,
            dataset.loop_id,
            t("At least three valid samples are required for noise screening."),
        )

    values = series.to_numpy(dtype=float)
    signal_std = float(np.std(values))
    if signal_std <= 1e-12:
        high_frequency_std = 0.0
        noise_ratio = 0.0
    else:
        high_frequency_std = float(np.std(np.diff(values)) / math.sqrt(2.0))
        noise_ratio = float(high_frequency_std / signal_std)
    score = max(
        0.35 * normalized_score(noise_ratio, parameters.noise_ratio_threshold),
        normalized_score(high_frequency_std, parameters.noise_abs_tolerance),
    )

    return result(
        metadata=METHOD_METADATA,
        loop_id=dataset.loop_id,
        status=status_from_score(score),
        score=score,
        message=t("Sensor-noise ratio calculated."),
        metrics={
            "signal": input_data.signal,
            "high_frequency_std": high_frequency_std,
            "noise_ratio": noise_ratio,
            "signal_std": signal_std,
            "valid_samples": int(len(series)),
        },
    )


def describe(metrics: dict) -> str:
    return t(
        "High-frequency noise is {ratio} of the measurement's total variation.",
        ratio=_pct(metrics.get("noise_ratio")),
    )
