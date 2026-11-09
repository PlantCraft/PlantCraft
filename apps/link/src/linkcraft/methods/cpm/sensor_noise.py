"""Sensor noise screening: the measurement's sample-to-sample noise against the loop's scale.

Noise is judged in the loop's own terms. An absolute amount in the PV's unit says nothing (0.5 is
nothing for a flow of 500 and a lot for a pressure of 2), and a share of the PV's total variation
is high on every tight loop, whose PV is mostly noise because the controller holds it. So the
noise is a share of the loop's scale, as the PV-SP error is judged: the PV span when it is known,
else the size of the setpoint (or of the PV). The default 2 % scores 100.

The noise is estimated from second differences with the median absolute deviation, so setpoint
steps, load changes and slow cycles (whose second differences are small or rare) do not read as
noise. A large estimate on a PV that cycles slowly is a fast cycle more than noise; the share of
the PV's own variation the noise explains (``noise_ratio``) weighs the score, so only a PV whose
variation is mostly noise is flagged.
"""

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
from plantcraft_sdk.methods.findings import fmt_number as _n
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
    noise_ratio_threshold: float = Field(
        default=0.35,
        gt=0.0,
        description="Share of the PV's variation explained by noise from which it weighs fully.",
    )
    noise_abs_tolerance: float | None = Field(
        default=None,
        gt=0.0,
        description="Absolute noise (PV unit) that scores 100; empty: a share of the loop's scale.",
    )
    relative_noise_percent: float = Field(
        default=2.0, gt=0.0, description="Noise that scores 100, in percent of the loop's scale."
    )
    pv_span: float | None = Field(
        default=None, gt=0.0, description="PV span (engineering range); empty: median |SP| or |PV|."
    )


METHOD_METADATA = MethodMetadata(
    method_id="sensor_noise_ratio",
    name="Sensor noise ratio",
    description="High-frequency noise as a share of the measurement's total variation.",
    maturity=MethodMaturity.ENGINEERING_HEURISTIC,
    references=[BAUER_2016_CPM_SURVEY],
    required_signals=["pv"],
    implemented_formula=(
        "noise_std = 1.4826*median(|d2 - median(d2)|)/sqrt(6), d2 = second difference of the PV; "
        "noise_ratio = min(1, noise_std/std(PV)); "
        "score = 100*(noise_std/tolerance)*min(1, noise_ratio/noise_ratio_threshold), "
        "tolerance = noise_abs_tolerance or relative_noise_percent/100*scale, "
        "scale = pv_span or median(|SP|) or median(|PV|)."
    ),
    assumptions=[
        "Measurement noise is independent from one sample to the next; the process moves "
        "smoothly between samples.",
    ],
    limitations=[
        "A process faster than the sampling (a fast flow sampled once a minute) looks like noise.",
        "A PV near zero (a gauge pressure, a differential) makes the relative tolerance tight: "
        "give the loop its pv_span or an absolute noise_abs_tolerance.",
    ],
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
    second = np.diff(values, n=2)
    if second.size and signal_std > 1e-12:
        mad = float(np.median(np.abs(second - np.median(second))))
        high_frequency_std = 1.4826 * mad / math.sqrt(6.0)
        noise_ratio = float(min(1.0, high_frequency_std / signal_std))
    else:
        high_frequency_std = 0.0
        noise_ratio = 0.0
    tolerance, scale, basis = _tolerance(parameters, dataset, values)
    weight = min(1.0, noise_ratio / parameters.noise_ratio_threshold)
    score = normalized_score(high_frequency_std, tolerance) * weight

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
            "noise_tolerance": tolerance,
            "scale": scale,
            "tolerance_basis": basis,
            "noise_percent_of_scale": (100.0 * high_frequency_std / scale) if scale else None,
            "valid_samples": int(len(series)),
        },
    )


def _tolerance(
    parameters: SensorNoiseParameters, dataset: LoopDataset, values: np.ndarray
) -> tuple[float, float | None, str]:
    """(tolerance, scale, basis): absolute when given, else a share of the loop's scale."""

    if parameters.noise_abs_tolerance:
        return float(parameters.noise_abs_tolerance), None, "absolute"
    scale, basis = None, "absolute"
    if parameters.pv_span:
        scale, basis = float(parameters.pv_span), "pv_span"
    else:
        for column, name in (("sp", "setpoint"), ("pv", "pv")):
            if column in dataset.data.columns:
                found = numeric_series(dataset, column)
                size = float(np.median(np.abs(found))) if len(found) else 0.0
                if np.isfinite(size) and size > 1e-9:
                    scale, basis = size, name
                    break
    if scale is None:
        return ABSOLUTE_TOLERANCE, None, "absolute"
    return parameters.relative_noise_percent / 100.0 * scale, scale, basis


# Used only when the loop has no scale (no span given, SP and PV at zero).
ABSOLUTE_TOLERANCE = 0.5


def describe(metrics: dict) -> str:
    share = metrics.get("noise_percent_of_scale")
    if share is None:
        return t(
            "Sample-to-sample noise of {noise}, {ratio} of the measurement's variation.",
            noise=_n(metrics.get("high_frequency_std")),
            ratio=_pct(metrics.get("noise_ratio")),
        )
    return t(
        "Sample-to-sample noise of {noise} ({share} % of the loop's scale), {ratio} of the "
        "measurement's variation.",
        noise=_n(metrics.get("high_frequency_std")),
        share=_n(share, 2),
        ratio=_pct(metrics.get("noise_ratio")),
    )
