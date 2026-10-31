"""Lab fusion: an online value corrected by the laboratory, at the time each sample was taken.

An analyzer or a soft sensor gives a value at every step, but it drifts away from the truth; the
laboratory is right but rare and late (a sample taken at 06:00 is approved at 09:30). The fusion
keeps the online value's speed and the laboratory's accuracy: the online value's bias is a state
that walks slowly, and each approved result measures it, at the sampling time, when it arrives.

The measurement is delayed: at arrival step ``a`` it says what the bias was at sampling step
``s``. For a random-walk bias the bias moved by ``(a - s)`` steps of noise since then, so the
result counts as a measurement of the bias now with its noise plus ``(a - s)·q`` (the delayed
measurement of Alexander, 1991, for a random walk). Before arrival nothing changes, so the
estimate at a step uses only what was known then: run on history it gives what an operator
would have seen.

``fuse_lab`` tunes the bias' walk ``q`` by maximum likelihood of the results' innovations when it
is not given, as ``kalman.tune`` does for the filters. NumPy only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from plantcraft_sdk.estimators.kalman import _golden, noise_variance


@dataclass
class LabFusion:
    estimate: np.ndarray  # the online value minus its estimated bias, at every step
    bias: np.ndarray  # the online value's bias as known at each step
    uncertainty: np.ndarray  # one standard deviation of the bias (so of the estimate)
    innovations: np.ndarray  # at each result's arrival step: lab minus the estimate then
    used: int  # the results that corrected the bias
    q: float  # the bias' walk variance a step
    loglik: float


def _arrivals(lab: np.ndarray, arrival: np.ndarray | None, delay_steps: int) -> dict[int, list]:
    """By arrival step, the sampling steps whose result arrives then."""

    out: dict[int, list[int]] = {}
    for s in np.flatnonzero(np.isfinite(lab)):
        a = int(arrival[s]) if arrival is not None else int(s) + max(0, int(delay_steps))
        if arrival is not None and a < 0:
            continue  # not approved (yet): it never corrects
        out.setdefault(max(a, int(s)), []).append(int(s))
    return out


def _run(
    online: np.ndarray, lab: np.ndarray, arrivals: dict[int, list[int]], q: float, r: float
) -> LabFusion:
    steps = len(online)
    # No bias is known before the first result: it sets the bias, the next ones correct it.
    b, p = 0.0, math.inf
    bias, variance = np.empty(steps), np.empty(steps)
    innovations = np.full(steps, np.nan)
    used, loglik = 0, 0.0
    for k in range(steps):
        p += q
        for s in arrivals.get(k, ()):
            if not math.isfinite(online[s]):
                continue
            z = float(online[s] - lab[s])  # the bias at the sampling step
            delayed = r + (k - s) * q
            if math.isinf(p):
                b, p = z, delayed
                used += 1
                continue
            e = z - b
            spread = p + delayed
            gain = p / spread
            b += gain * e
            p -= gain * p
            innovations[k] = -e
            loglik -= 0.5 * (math.log(2 * math.pi * spread) + e * e / spread)
            used += 1
        bias[k], variance[k] = b, p
    return LabFusion(online - bias, bias, np.sqrt(variance), innovations, used, q, loglik)


def fuse_lab(
    online: np.ndarray,
    lab: np.ndarray,
    *,
    arrival: np.ndarray | None = None,
    delay_steps: int = 0,
    q: float | None = None,
    lab_noise: float = 0.0,
    online_noise: float | None = None,
) -> LabFusion:
    """Correct ``online`` with the laboratory results in ``lab`` (the same grid, a value at each
    sample's sampling step, NaN elsewhere).

    ``arrival``: for each step that holds a result, the step it was approved (became known),
    or -1 for a result never approved (it never corrects); else every result arrives
    ``delay_steps`` after its sampling. ``lab_noise``: the laboratory's own variance (its
    repeatability), added to the online value's noise; ``online_noise``: that noise's variance,
    None estimates it from the whole series (like ``q``, a setting fitted once, so give it to
    replay history exactly as it ran). Before the first result the bias is unknown: the
    estimate is the online value and its uncertainty infinite. ``q``: the bias' walk a step; None tunes
    it by maximum likelihood.
    """

    online = np.asarray(online, dtype=float)
    lab = np.asarray(lab, dtype=float)
    if online.shape != lab.shape:
        raise ValueError("The online and laboratory series must be on the same grid.")
    if arrival is not None:
        arrival = np.asarray(arrival)
        if arrival.shape != lab.shape:
            raise ValueError("The arrival steps must be on the laboratory's grid.")
    arrivals = _arrivals(lab, arrival, delay_steps)
    noise = noise_variance(online) if online_noise is None else max(0.0, float(online_noise))
    r = noise + max(0.0, float(lab_noise))
    if q is not None:
        return _run(online, lab, arrivals, float(q), r)
    if sum(len(items) for items in arrivals.values()) < 3:
        return _run(online, lab, arrivals, 1e-8 * max(r, 1e-12), r)
    scale = max(r, 1e-12)

    def cost(log_q: float) -> float:
        return -_run(online, lab, arrivals, scale * 10.0**log_q, r).loglik

    return _run(online, lab, arrivals, scale * 10.0 ** _golden(cost, -8.0, 1.0, 0.05), r)


def sensor_health(actual: np.ndarray, predicted: np.ndarray, spread: float | None = None) -> float:
    """A virtual sensor's health from 0 to 100 over its laboratory samples, from the root mean
    square of its error (bias included) against ``spread``: 100 while it stays within a quarter
    of the spread, falling in a line to 0 when it reaches the whole spread (no better than the
    samples' own mean). ``spread`` defaults to the samples' standard deviation."""

    a = np.asarray(actual, dtype=float)
    f = np.asarray(predicted, dtype=float)
    ok = np.isfinite(a) & np.isfinite(f)
    if ok.sum() < 3:
        return float("nan")
    error = f[ok] - a[ok]
    scale = float(spread) if spread else float(np.std(a[ok]))
    if not scale or not math.isfinite(scale):
        return 100.0 if not np.any(error) else 0.0
    rmse = float(np.sqrt(np.mean(error**2))) / scale
    return round(max(0.0, min(100.0, 100.0 * (1.0 - (rmse - 0.25) / 0.75))), 1)
