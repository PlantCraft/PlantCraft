"""Estimators: virtual sensors on the algorithm's window (prototype, 2026-10-31, E3.2).

A Kalman filter gives a better value of a signal the plant measures badly: without the lag of a
moving average when the valve (or feed) that drives it is wired, and with the sensor's drift when
asked. A soft sensor estimates a value the plant only samples (a lab analysis) from signals it
measures all the time; the lab fusion corrects an online value (an analyzer, a soft sensor) with
the lab results, each at its sampling time and only from when it is approved. The math is the SDK's (``plantcraft_sdk.estimators``), the same Models fits
with, so a filter here and a fit there agree.

Each block fits what it needs on the window it reads (the model's gain, time constant and dead
time, the noise), so it needs no setup; the result is a new series on the same grid, like a
filter of "Transforms".
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from plantcraft_sdk.blocks import Block, BlockDocs, BlockSpec, NoData, inport, outport
from plantcraft_sdk.estimators import (
    fit_fopdt,
    fit_soft_sensor,
    fopdt_model,
    fuse_lab,
    kalman_filter,
    local_level,
    noise_variance,
    tune,
)
from pydantic import BaseModel, Field

from linkcraft.blocks.base import clean, numeric, seconds
from linkcraft.i18n import t

LIBRARY = "estimator"
MIN_SAMPLES = 60
KALMAN = (
    "Kalman, R. E. (1960). A new approach to linear filtering and prediction problems. "
    "Journal of Basic Engineering 82(1), 35-45."
)
HARVEY = (
    "Harvey, A. C. (1989). Forecasting, Structural Time Series Models and the Kalman Filter. "
    "Cambridge University Press: the local level model and tuning by maximum likelihood."
)
SEBORG = (
    "Seborg, D. E., Edgar, T. F., Mellichamp, D. A., Doyle, F. J. (2016). Process Dynamics and "
    "Control, 4th ed. Wiley: first order plus dead time models."
)
ALEXANDER = (
    "Alexander, H. L. (1991). State estimation for distributed systems with sensing delay. "
    "SPIE Data Structures and Target Classification 1470: the delayed measurement."
)
FORTUNA = (
    "Fortuna, L., Graziani, S., Rizzo, A., Xibilia, M. G. (2007). Soft Sensors for Monitoring "
    "and Control of Industrial Processes. Springer."
)
X = inport("x", "series", "Signal", "The measured signal to estimate better.")
U = inport(
    "u",
    "series",
    "Driver",
    "What moves the signal: the controller's valve position or output, or a feed. Not wired: "
    "the filter follows the signal alone (it lags a little more).",
    required=False,
)


def _arrays(inputs: dict[str, Any], *names: str) -> tuple[pd.Index, list[np.ndarray]] | NoData:
    x = numeric(inputs["x"])
    out = [x.to_numpy(dtype=float)]
    for name in names:
        series = inputs.get(name)
        if not isinstance(series, pd.Series):
            out.append(np.array([]))
            continue
        filled = numeric(series).reindex(x.index).ffill().bfill()
        out.append(filled.to_numpy(dtype=float))
    if int(np.isfinite(out[0]).sum()) < MIN_SAMPLES:
        return NoData(t("Fewer than {n} samples with a value.", n=MIN_SAMPLES))
    return x.index, out


def _step(index: pd.Index) -> float:
    found = np.diff(seconds(index))
    return float(np.median(found)) if len(found) else 1.0


def _smooth(y: np.ndarray) -> np.ndarray:
    """A light first-order filter, so the model is fitted on the process, not the noise."""

    out = np.copy(y)
    for k in range(1, len(out)):
        out[k] = out[k - 1] if not np.isfinite(out[k]) else 0.2 * out[k] + 0.8 * out[k - 1]
    return out


class KalmanParameters(BaseModel):
    max_dead_time_seconds: float = Field(
        default=300.0,
        ge=0,
        le=3600,
        title="Longest dead time",
        description="The longest delay searched between the driver and the signal.",
        json_schema_extra={"unit": "s"},
    )


class DriftParameters(KalmanParameters):
    fit_minutes: float = Field(
        default=60.0,
        gt=0,
        le=1440,
        title="Fit on the first",
        description="The model is fitted on this first part of the window, before the sensor "
        "drifted; the bias is what the sensor reads apart from it afterwards.",
        json_schema_extra={"unit": "min"},
    )


class SoftSensorParameters(BaseModel):
    lag_minutes: float = Field(
        default=5.0,
        ge=0,
        le=240,
        title="Look back",
        description="How far back the inputs explain the target (a sample taken now reflects "
        "the process a few minutes before).",
        json_schema_extra={"unit": "min"},
    )


class LabFusionParameters(BaseModel):
    approval_minutes: float = Field(
        default=0.0,
        ge=0,
        le=10080,
        title="Approval delay",
        description="How long after its sampling a lab result is known (approved). The "
        "correction starts then, so the history shows what an operator would have seen.",
        json_schema_extra={"unit": "min"},
    )
    lab_repeatability: float = Field(
        default=0.0,
        ge=0,
        title="Lab repeatability",
        description="One standard deviation of the lab method, in the signal's unit. 0: the "
        "lab is taken as exact next to the online value's noise.",
    )
    deadband: float = Field(
        default=0.0,
        ge=0,
        title="Dead zone",
        description="A result closer than this to the estimate leaves the bias as it is (the "
        "lab's own scatter), in the signal's unit. 0: every result corrects.",
    )
    max_step: float = Field(
        default=0.0,
        ge=0,
        title="Largest correction",
        description="The most one result moves the bias, in the signal's unit, so one bad "
        "sample cannot jump it. 0: no limit.",
    )


def _lab_fusion(
    inputs: dict[str, Any], parameters: LabFusionParameters, _ctx: Any
) -> dict[str, Any]:
    found = _arrays(inputs)
    if isinstance(found, NoData):
        return {"value": found, "bias": found, "uncertainty": found}
    index, (online,) = found
    results = numeric(inputs["lab"]).dropna()
    inside = (results.index >= index[0]) & (results.index <= index[-1])
    if not inside.any():
        missing = NoData(t("No laboratory result in the window."))
        return {"value": missing, "bias": missing, "uncertainty": missing}
    # Each result on the online grid, at the first step at or after its sampling.
    lab = np.full(len(online), np.nan)
    lab[index.searchsorted(results.index[inside])] = results.to_numpy(float)[inside]
    out = fuse_lab(
        online,
        lab,
        delay_steps=round(parameters.approval_minutes * 60 / _step(index)),
        lab_noise=parameters.lab_repeatability**2,
        deadband=parameters.deadband,
        max_step=parameters.max_step or None,
    )
    return {
        "value": clean(pd.Series(out.estimate, index=index)),
        "bias": clean(pd.Series(out.bias, index=index)),
        "uncertainty": clean(pd.Series(out.uncertainty, index=index)),
    }


def _kalman(inputs: dict[str, Any], parameters: KalmanParameters, _ctx: Any) -> dict[str, Any]:
    found = _arrays(inputs, "u")
    if isinstance(found, NoData):
        return {"value": found, "uncertainty": found}
    index, (y, u) = found
    r = noise_variance(y)
    if len(u):
        dt = _step(index)
        fit = fit_fopdt(u, _smooth(y), dt, max_dead=int(parameters.max_dead_time_seconds / dt))
        _, filtered = tune(lambda q: fopdt_model(fit, q, r), y, u)
    else:
        _, filtered = tune(lambda q: local_level(q, r), y)
    return {
        "value": clean(pd.Series(filtered.estimate, index=index)),
        "uncertainty": clean(pd.Series(np.sqrt(filtered.variances[0]), index=index)),
    }


def _drift(inputs: dict[str, Any], parameters: DriftParameters, _ctx: Any) -> dict[str, Any]:
    found = _arrays(inputs, "u")
    if isinstance(found, NoData):
        return {"corrected": found, "bias": found}
    index, (y, u) = found
    dt = _step(index)
    first = max(MIN_SAMPLES, int(parameters.fit_minutes * 60 / dt))
    fit = fit_fopdt(
        u[:first], _smooth(y)[:first], dt, max_dead=int(parameters.max_dead_time_seconds / dt)
    )
    filtered = kalman_filter(
        fopdt_model(fit, 1e-7, noise_variance(y), bias=True, q_bias=1e-7), y, u
    )
    return {
        "corrected": clean(pd.Series(filtered.states[0] + fit.y0, index=index)),
        "bias": clean(pd.Series(filtered.states[1], index=index)),
    }


def _soft(inputs: dict[str, Any], parameters: SoftSensorParameters, _ctx: Any) -> dict[str, Any]:
    target = numeric(inputs["target"])
    wired = [inputs[name] for name in ("x1", "x2", "x3") if isinstance(inputs.get(name), pd.Series)]
    columns = [numeric(s).reindex(target.index).ffill().bfill().to_numpy(float) for s in wired]
    samples = int(target.notna().sum())
    if samples < 8:
        missing = NoData(t("Fewer than {n} samples of the target.", n=8))
        return {"value": missing}
    dt = _step(target.index)
    reach = int(parameters.lag_minutes * 60 / dt)
    lags = sorted({0, *range(0, reach + 1, max(1, reach // 4 or 1))})
    model = fit_soft_sensor(np.column_stack(columns), target.to_numpy(float), lags=lags, alpha=10.0)
    return {"value": clean(pd.Series(model.predict(np.column_stack(columns)), index=target.index))}


BLOCKS = (
    Block(
        BlockSpec(
            "estimator.kalman",
            "1.0",
            LIBRARY,
            "Kalman filter",
            BlockDocs(
                summary="A cleaner value of a noisy signal, without the lag a moving average "
                "adds when the valve or feed that drives it is wired.",
                description=(
                    "Fits a first order plus dead time model from the driver to the signal on "
                    "the window, tunes how much the process moves by maximum likelihood, and "
                    "filters: each step it predicts with the model and corrects with the "
                    "measurement as much as their noises say. Without a driver it follows the "
                    "signal alone (a local level). Gaps are bridged by the prediction."
                ),
                reading="The estimate, in the signal's unit; the uncertainty is one standard "
                "deviation of it. On the PlantCraft Simulator it cut a noisy analyzer's error 11 "
                "to 18 times with no lag, where a 5 minute average lagged 2 to 4 minutes.",
                assumptions=(
                    "The driver moves the signal roughly as a first order with dead time.",
                    "The sensor noise is about constant over the window.",
                ),
                limitations=(
                    "A gain 30% wrong doubles the error (still far below the raw signal).",
                    "Needs at least 60 samples with a value.",
                ),
                formula="x(k+1) = a·x(k) + K·(1−a)·u(k−d); y(k) = x(k) + v(k)",
                references=(KALMAN, HARVEY, SEBORG),
            ),
            inputs=(X, U),
            outputs=(
                outport("value", "series", "Estimate", "The filtered signal, on the same grid."),
                outport("uncertainty", "series", "Uncertainty", "One standard deviation of it."),
            ),
            parameters=KalmanParameters,
            group="Kalman",
        ),
        _kalman,
    ),
    Block(
        BlockSpec(
            "estimator.drift",
            "1.0",
            LIBRARY,
            "Sensor drift (Kalman)",
            BlockDocs(
                summary="How far a sensor drifted, and its value without the drift.",
                description=(
                    "Fits the model from the driver on the first part of the window, when the "
                    "sensor still read right, then filters with a second state, the sensor's "
                    "bias, that walks slowly. What the sensor reads apart from what the model "
                    "and the driver explain goes to the bias."
                ),
                reading="Bias near 0: the sensor agrees with the process. A bias that grows "
                "steadily is a drift: alarm on it, or use the corrected value until the sensor "
                "is calibrated. On the Simulator it tracked a drift of up to 0.128 (of range) "
                "within 0.006.",
                assumptions=("The first part of the window is before the drift.",),
                limitations=(
                    "A change in the process the driver does not explain reads as drift.",
                ),
                formula="y(k) = x(k) + b(k) + v(k); b(k+1) = b(k) + w(k)",
                references=(KALMAN, HARVEY),
            ),
            inputs=(X, inport("u", "series", "Driver", "What moves the signal (a valve).")),
            outputs=(
                outport("corrected", "series", "Corrected", "The signal without the drift."),
                outport("bias", "series", "Bias", "The drift, in the signal's unit."),
            ),
            parameters=DriftParameters,
            group="Kalman",
        ),
        _drift,
    ),
    Block(
        BlockSpec(
            "estimator.soft_sensor",
            "1.0",
            LIBRARY,
            "Soft sensor",
            BlockDocs(
                summary="A value the plant only samples (a lab analysis) at every step, from "
                "signals it measures all the time.",
                description=(
                    "Fits a ridge regression of the target's samples on up to three inputs and "
                    "their recent past, then predicts at every step. The target is the lab or "
                    "analyzer series with gaps between samples."
                ),
                reading="The estimate, in the target's unit. On the Simulator, with a lab "
                "value every 30 minutes, it was 5 times closer to the truth than holding the "
                "last lab value.",
                assumptions=("The inputs explain the target the same way over the window.",),
                limitations=(
                    "Needs at least 8 samples of the target.",
                    "Outside the inputs' range in the window it extrapolates.",
                ),
                formula="ŷ(k) = b + Σᵢ Σₗ wᵢₗ·xᵢ(k−l), ridge regularised",
                references=(FORTUNA,),
            ),
            inputs=(
                inport("target", "series", "Target", "The sampled value (gaps between samples)."),
                inport("x1", "series", "Input 1", "A signal that explains the target."),
                inport(
                    "x2",
                    "series",
                    "Input 2",
                    "A second signal that explains the target.",
                    required=False,
                ),
                inport(
                    "x3",
                    "series",
                    "Input 3",
                    "A third signal that explains the target.",
                    required=False,
                ),
            ),
            outputs=(outport("value", "series", "Estimate", "The target at every step."),),
            parameters=SoftSensorParameters,
            group="Soft sensors",
        ),
        _soft,
    ),
    Block(
        BlockSpec(
            "estimator.lab_fusion",
            "1.0",
            LIBRARY,
            "Lab fusion",
            BlockDocs(
                summary="An online value (an analyzer, a soft sensor) corrected by the lab, "
                "each result at its sampling time.",
                description=(
                    "The online value's bias is a state that walks slowly. Each lab result "
                    "measures it at the time the sample was taken, and corrects it when it is "
                    "approved: a delayed measurement, with the walk since the sampling added to "
                    "its noise. The walk is tuned by maximum likelihood of the results."
                ),
                reading="The estimate keeps the online value's speed and the lab's accuracy. "
                "The bias is how far the online value reads from the lab now: one that grows "
                "is an analyzer to calibrate or a soft sensor to fit again. Before the first "
                "result the estimate is the online value. On a made drift of 3 units it cut "
                "the error more than 4 times with results every 5 minutes approved 100 s late.",
                assumptions=(
                    "The lab is right; the online value is off by a bias that changes slowly.",
                    "The approval delay is about the same for every result.",
                ),
                limitations=(
                    "Needs at least 60 online samples and one lab result in the window.",
                    "A result whose sample was spoiled moves the bias until the next ones "
                    "bring it back.",
                ),
                formula="b(k+1) = b(k) + w(k); lab(s) = y(s) − b(s); "
                "x̂(k) = y(k) − b̂(k | results approved by k)",
                references=(KALMAN, ALEXANDER, HARVEY),
            ),
            inputs=(
                inport("x", "series", "Online value", "The analyzer or soft sensor to correct."),
                inport(
                    "lab",
                    "series",
                    "Lab",
                    "The lab results at their sampling times (laboratory:<analysis>).",
                ),
            ),
            outputs=(
                outport("value", "series", "Estimate", "The online value without its bias."),
                outport("bias", "series", "Bias", "How far the online value reads from the lab."),
                outport("uncertainty", "series", "Uncertainty", "One standard deviation of it."),
            ),
            parameters=LabFusionParameters,
            group="Soft sensors",
        ),
        _lab_fusion,
    ),
)
