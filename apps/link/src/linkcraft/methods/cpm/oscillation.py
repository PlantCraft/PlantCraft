"""Oscillation screening: autocorrelation peak plus the regularity of the period.

A loop oscillates when its signal (the control error when the setpoint is known) repeats
itself: the autocorrelation function (ACF) has a clear peak after lag zero (Thornhill and
Hagglund 1997) *and* the ACF crosses zero at regular intervals. The regularity test is the one
of Thornhill, Huang and Zhang (2003): the periods between alternate zero crossings of the ACF
(up to ten of them) give a mean period Tp and a standard deviation; the oscillation is regular
when ``r = Tp / (3 * std(Tp)) > 1``.

The regularity criterion is what keeps a single setpoint step from reading as an oscillation:
the decaying error after a step lifts the ACF for a long lag range and leaves small wiggles that
count as a peak, but its zero crossings come at irregular intervals (r well below 1), while a
sustained oscillation crosses zero every half period (r far above 1).
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
from plantcraft_sdk.methods.utils import (
    autocorrelation_peak,
    estimate_sample_seconds,
    insufficient_data,
    missing_columns,
    numeric_frame,
    numeric_series,
    result,
    status_from_score,
)
from pydantic import BaseModel, Field

from linkcraft.methods.references import (
    THORNHILL_HAGGLUND_1997_OSCILLATION,
    THORNHILL_HUANG_ZHANG_2003_REGULARITY,
)

# Thornhill, Huang and Zhang (2003) use up to ten periods of the ACF; with fewer than three the
# spread of the periods says nothing about regularity.
MAX_PERIODS = 10
MIN_PERIODS = 3
# Upper bound reported for r (a perfect sinusoid has zero spread and an infinite r).
MAX_REGULARITY = 100.0


class OscillationInput(BaseModel):
    dataset: LoopDataset
    signal: str = "pv"


class OscillationParameters(BaseModel):
    min_lag_samples: int = Field(default=3, ge=1)
    max_lag_samples: int | None = Field(default=None, ge=2)
    min_cycles: float = Field(default=3.0, gt=0.0)
    min_autocorrelation: float = Field(default=0.30, ge=0.0, le=1.0)
    min_regularity: float = Field(default=1.0, gt=0.0)


METHOD_METADATA = MethodMetadata(
    method_id="oscillation_autocorrelation",
    name="Oscillation screening by autocorrelation",
    description="Regular cycles in the control error, found by autocorrelation, with their period.",
    maturity=MethodMaturity.LITERATURE_BASED,
    references=[THORNHILL_HAGGLUND_1997_OSCILLATION, THORNHILL_HUANG_ZHANG_2003_REGULARITY],
    required_signals=["pv"],
    implemented_formula=(
        "peak = largest local maximum of the normalized autocorrelation after min_lag; "
        "r = mean(Tp)/(3*std(Tp)) over the periods Tp between alternate zero crossings of the "
        "autocorrelation (Thornhill, Huang and Zhang 2003); flagged when peak >= "
        "min_autocorrelation and r >= min_regularity; "
        "score = 100*(peak/min_autocorrelation)*min(1, cycles/min_cycles)"
        "*min(1, r/min_regularity), capped at 100."
    ),
    assumptions=[
        "The oscillation persists through the analysed window.",
        "The selected signal has a roughly regular sampling interval.",
    ],
    limitations=[
        "This is a screening implementation, not a full reproduction of "
        "every signature in the reference paper.",
        "External oscillating disturbances can produce a similar signature.",
        "An oscillation whose period drifts strongly in the window is not regular and is not "
        "flagged.",
    ],
)

METHOD_SPEC = MethodBlockSpec(
    method_id=METHOD_METADATA.method_id,
    version=METHOD_METADATA.version,
    input_ports=[
        InputPort(
            port_id="pv", semantic_type="process_variable", dtype="timeseries_float", required=True
        ),
        InputPort(port_id="sp", semantic_type="setpoint", dtype="timeseries_float", required=False),
    ],
    input_schema=OscillationInput,
    parameter_schema=OscillationParameters,
    output_ports=[
        OutputPort(port_id="autocorrelation_peak", semantic_type="metric", dtype="float"),
        OutputPort(
            port_id="dominant_period_seconds",
            semantic_type="time_period",
            dtype="float",
            unit="seconds",
        ),
    ],
    output_schema=MethodResult,
    metadata=METHOD_METADATA,
)
from linkcraft.i18n import t


def _selected_series(dataset: LoopDataset, signal: str) -> np.ndarray | None:
    if signal == "error":
        if missing_columns(dataset, ["pv", "sp"]):
            return None
        frame = numeric_frame(dataset, ["pv", "sp"])
        if frame.empty:
            return None
        return frame["pv"].to_numpy(dtype=float) - frame["sp"].to_numpy(dtype=float)
    if missing_columns(dataset, [signal]):
        return None
    series = numeric_series(dataset, signal)
    if series.empty:
        return None
    return series.to_numpy(dtype=float)


def acf_regularity(
    values: np.ndarray, max_lag: int | None = None
) -> tuple[float, float | None, int]:
    """Regularity r, mean period (samples) and periods used, from the ACF zero crossings.

    Thornhill, Huang and Zhang (2003): the ACF of an oscillating signal crosses zero every half
    period; the periods are the distances between alternate crossings. Returns ``(0.0, None, n)``
    when fewer than ``MIN_PERIODS`` periods are seen.
    """

    clean = np.asarray(values, dtype=float)
    clean = clean[np.isfinite(clean)]
    clean = clean - (np.mean(clean) if clean.size else 0.0)
    size = clean.size
    if size < 8 or float(np.std(clean)) <= 0:
        return 0.0, None, 0
    spectrum = np.fft.rfft(clean, 2 * size)
    acf = np.fft.irfft(spectrum * np.conj(spectrum), 2 * size)[:size]
    if not np.isfinite(acf[0]) or acf[0] <= 0:
        return 0.0, None, 0
    acf = acf / acf[0]
    upper = min(size, max_lag) if max_lag is not None else size
    signs = np.sign(acf[:upper])
    crossings = np.flatnonzero(signs[:-1] * signs[1:] < 0)[: MAX_PERIODS + 2]
    periods = (crossings[2:] - crossings[:-2]).astype(float)
    if periods.size < MIN_PERIODS:
        return 0.0, None, int(periods.size)
    mean_period = float(np.mean(periods))
    spread = float(np.std(periods))
    regularity = MAX_REGULARITY if spread <= 0 else min(MAX_REGULARITY, mean_period / (3 * spread))
    return regularity, mean_period, int(periods.size)


def run(input_data: OscillationInput, parameters: OscillationParameters) -> MethodResult:
    dataset = input_data.dataset
    values = _selected_series(dataset, input_data.signal)
    if values is None or len(values) < parameters.min_lag_samples + 3:
        return insufficient_data(
            METHOD_METADATA,
            dataset.loop_id,
            t(
                "Signal {signal} is not available for oscillation screening.",
                signal=input_data.signal,
            ),
        )

    peak, lag = autocorrelation_peak(
        values, min_lag=parameters.min_lag_samples, max_lag=parameters.max_lag_samples
    )
    if lag is None:
        return insufficient_data(
            METHOD_METADATA, dataset.loop_id, t("Not enough variation to evaluate oscillation.")
        )

    cycles = float(len(values) / lag) if lag > 0 else 0.0
    dt = estimate_sample_seconds(dataset)
    period_seconds = float(lag * dt)
    cycle_factor = min(1.0, cycles / parameters.min_cycles)
    peak_factor = (
        max(0.0, peak) / parameters.min_autocorrelation
        if parameters.min_autocorrelation > 0
        else 0.0
    )
    regularity, mean_period, periods = acf_regularity(values, parameters.max_lag_samples)
    regularity_factor = min(1.0, regularity / parameters.min_regularity)
    score = min(100.0, 100.0 * peak_factor * cycle_factor * regularity_factor)
    # A peak below the autocorrelation threshold, or zero crossings at irregular intervals (a
    # decaying transient, drift), is not a clear oscillation to flag.
    regular = regularity >= parameters.min_regularity
    flagged = peak >= parameters.min_autocorrelation and regular
    status = status_from_score(score) if flagged else MethodStatus.OK

    return result(
        metadata=METHOD_METADATA,
        loop_id=dataset.loop_id,
        status=status,
        score=score,
        message=t("Oscillation screening completed."),
        metrics={
            "signal": input_data.signal,
            "autocorrelation_peak": peak,
            "lag_samples": lag,
            "dominant_period_seconds": period_seconds,
            "estimated_cycles": cycles,
            "regularity": float(regularity),
            "zero_crossing_period_seconds": float(mean_period * dt) if mean_period else None,
            "acf_periods": periods,
            "min_regularity": parameters.min_regularity,
            "oscillating": bool(flagged),
            "valid_samples": int(len(values)),
        },
    )


def describe(metrics: dict) -> str:
    period = metrics.get("dominant_period_seconds")
    peak = float(metrics.get("autocorrelation_peak") or 0)
    oscillating = metrics.get("oscillating")
    if oscillating is None:  # results stored before the regularity test
        oscillating = peak >= 0.3
    if not period or not oscillating:
        regularity = metrics.get("regularity")
        if period and peak >= 0.3 and regularity is not None:
            return t(
                "No sustained oscillation: the signal repeats (autocorrelation {peak}) but its "
                "period is irregular (regularity {regularity}, below {limit}), as after a "
                "setpoint step or a one-off upset.",
                peak=_n(peak, 2),
                regularity=_n(regularity, 2),
                limit=_n(metrics.get("min_regularity") or 1.0, 2),
            )
        return t("No clear periodic oscillation.")
    return t(
        "Oscillation with a period of about {period} min, {cycles} cycles in the window "
        "(autocorrelation {peak}, regularity {regularity}).",
        period=_n(float(period) / 60),
        cycles=_n(metrics.get("estimated_cycles")),
        peak=_n(peak, 2),
        regularity=_n(metrics.get("regularity"), 2),
    )
