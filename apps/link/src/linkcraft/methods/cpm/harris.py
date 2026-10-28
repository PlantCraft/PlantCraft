"""Minimum-variance (Harris) performance index, written with the method decorator (gap G19).

The control error is fitted with an AR model; its first ``b`` impulse-response coefficients
(``b`` = the loop's dead time in samples) are the part of the variance no controller can remove,
so ``eta = sigma_mv^2 / sigma_e^2`` is 1 for a loop at minimum variance and near 0 for a loop
far from it (Harris 1989; Desborough and Harris 1992).
"""

from __future__ import annotations

import numpy as np
from plantcraft_sdk.methods import Finding, NotEnoughData, method, param

from linkcraft.i18n import t
from linkcraft.methods.references import (
    BAUER_2016_CPM_SURVEY,
    HARRIS_1989_PERFORMANCE,
    HORCH_ISAKSSON_1999_MODIFIED_INDEX,
)


def ar_fit(series: np.ndarray, order: int) -> tuple[np.ndarray, float]:
    """Least-squares AR coefficients ``phi`` (``e_t = sum phi_i e_t-i + a_t``) and the
    innovation variance."""

    rows = len(series) - order
    lagged = np.column_stack([series[order - i - 1 : order - i - 1 + rows] for i in range(order)])
    target = series[order:]
    phi, *_ = np.linalg.lstsq(lagged, target, rcond=None)
    residual = target - lagged @ phi
    return phi, float(np.mean(residual**2))


def impulse_response(phi: np.ndarray, count: int) -> np.ndarray:
    """The first ``count`` coefficients of ``1 / (1 - sum phi_i z^-i)``."""

    psi = np.zeros(count)
    psi[0] = 1.0
    for k in range(1, count):
        top = min(k, len(phi))
        psi[k] = float(np.dot(phi[:top], psi[k - 1 :: -1][:top]))
    return psi


def harris_eta(error: np.ndarray, delay: int, order: int) -> tuple[float, float, float]:
    """``(eta, sigma_mv^2, sigma_e^2)`` of a zero-mean control error."""

    phi, innovation = ar_fit(error, order)
    psi = impulse_response(phi, max(delay, 1))
    variance = float(np.mean(error**2))
    minimum = innovation * float(np.sum(psi**2))
    eta = min(1.0, minimum / variance) if variance > 0 else 1.0
    return eta, minimum, variance


def estimate_delay(pv: np.ndarray, op: np.ndarray, max_lag: int) -> int | None:
    """Samples from an OP move to the PV's answer: the lag of the largest cross-correlation of
    their differences, or None when they do not correlate."""

    dpv, dop = np.diff(pv), np.diff(op)
    dpv, dop = dpv - dpv.mean(), dop - dop.mean()
    scale = float(np.sqrt(np.sum(dpv**2) * np.sum(dop**2)))
    if scale <= 0:
        return None
    best, lag_at = 0.0, None
    for lag in range(1, min(max_lag, len(dpv) // 4) + 1):
        value = abs(float(np.dot(dop[:-lag], dpv[lag:]))) / scale
        if value > best:
            best, lag_at = value, lag
    return lag_at if best >= 0.1 else None


def _describe(metrics: dict) -> str:
    eta = metrics.get("harris_index")
    if eta is None:
        return t("The minimum-variance index could not be computed.")
    if eta >= metrics.get("good_index", 0.5):
        return t(
            "The variance is {ratio} times the minimum-variance benchmark: close to what any "
            "controller could do with a dead time of {delay} samples.",
            ratio=f"{1 / max(eta, 1e-9):.1f}",
            delay=metrics.get("delay_samples"),
        )
    return t(
        "The variance is {ratio} times the minimum-variance benchmark (dead time {delay} "
        "samples): retuning could remove up to {share} of it.",
        ratio=f"{1 / max(eta, 1e-9):.1f}",
        delay=metrics.get("delay_samples"),
        share=f"{(1 - eta) * 100:.0f}%",
    )


@method(
    "harris_index",
    name="Minimum-variance (Harris) index",
    version="1.0.0",
    maturity="engineering_heuristic",
    references=[HARRIS_1989_PERFORMANCE, HORCH_ISAKSSON_1999_MODIFIED_INDEX, BAUER_2016_CPM_SURVEY],
    formula=(
        "e=PV-SP (or PV minus its mean); AR(order) fit by least squares; psi=impulse response; "
        "eta=sigma_a^2*sum(psi_0..psi_(b-1))^2/var(e), b=dead time in samples; "
        "score=100*(good-eta)/(good-poor), clipped to 0-100."
    ),
    assumptions=[
        "The loop's dead time is known (dead_time_seconds) or shows as the lag from an OP move "
        "to the PV's answer.",
        "The window is a steady operation without setpoint changes: the index judges how "
        "disturbances are rejected.",
    ],
    limitations=[
        "Minimum variance is a theoretical bound that often needs aggressive control; an index "
        "of 0.3 to 0.6 is usual for a well-tuned industrial loop.",
        "A wrong dead time moves the index: a shorter one makes the loop look worse.",
        "Setpoint changes, saturation and manual mode in the window distort it.",
    ],
    min_samples=200,
    describe=_describe,
)
def harris_index(
    pv,
    sp=None,
    op=None,
    *,
    sample_seconds,
    dead_time_seconds: float = param(
        0.0,
        ge=0.0,
        help="Loop dead time; 0 estimates it from the lag between OP moves and the PV.",
    ),
    ar_order: int = param(20, ge=2, le=100, help="Order of the AR model of the error."),
    max_delay_samples: int = param(
        60, ge=1, le=600, help="Longest dead time looked for when it is estimated."
    ),
    good_index: float = param(
        0.5, gt=0, le=1, help="Index at or above which the loop scores healthy."
    ),
    poor_index: float = param(0.1, ge=0, lt=1, help="Index at or below which the score is 100."),
):
    """How far the loop's variance is above what minimum-variance control would leave."""

    values = np.asarray(pv, dtype=float)
    error = values - np.asarray(sp, dtype=float) if sp is not None else values.copy()
    keep = np.isfinite(error)
    if keep.sum() < max(200, 10 * ar_order):
        raise NotEnoughData(t("Too few samples for the minimum-variance index."))
    error = error[keep] - float(np.mean(error[keep]))
    step = float(sample_seconds or 0) or 1.0
    source = "parameter"
    if dead_time_seconds > 0:
        delay = max(1, int(round(dead_time_seconds / step)))
    else:
        found = None
        if op is not None:
            outputs = np.asarray(op, dtype=float)
            both = np.isfinite(values) & np.isfinite(outputs)
            if both.sum() > 50:
                found = estimate_delay(values[both], outputs[both], max_delay_samples)
        delay, source = (found, "estimated") if found else (1, "assumed")
    order = max(ar_order, delay + 1)
    eta, minimum, variance = harris_eta(error, delay, order)
    span = max(good_index - poor_index, 1e-9)
    score = float(np.clip(100.0 * (good_index - eta) / span, 0.0, 100.0))
    return Finding(
        score=score,
        message=t("Minimum-variance index calculated."),
        metrics={
            "harris_index": round(eta, 4),
            "variance_ratio": round(1 / max(eta, 1e-9), 2),
            "minimum_variance": minimum,
            "error_variance": variance,
            "delay_samples": delay,
            "delay_seconds": delay * step,
            "delay_source": source,
            "ar_order": order,
            "good_index": good_index,
            "valid_samples": int(keep.sum()),
        },
    )
