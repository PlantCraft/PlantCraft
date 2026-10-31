"""A first order plus dead time fitted to an input and a response, by least squares.

For each dead time up to ``max_dead`` steps, y[k+1] - y0 = a (y[k] - y0) + b (u[k-d] - u0) is
fitted; the dead time with the smallest error wins. Gain b / (1 - a), time constant
-dt / ln(a). Enough to give a Kalman filter or a soft sensor its model; a full system
identification (several inputs, higher orders) is a Models study, not this.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class Fopdt:
    gain: float
    tau: float  # seconds
    dead_steps: int
    dt: float  # seconds a step
    u0: float
    y0: float
    r2: float  # share of the variance the simulated response explains (one-step when refined fails)

    @property
    def dead_seconds(self) -> float:
        return self.dead_steps * self.dt


def fit_fopdt(u: np.ndarray, y: np.ndarray, dt: float, max_dead: int = 60) -> Fopdt:
    u = np.asarray(u, dtype=float)
    y = np.asarray(y, dtype=float)
    u0, y0 = float(np.nanmean(u)), float(np.nanmean(y))
    du, dy = u - u0, y - y0
    best: tuple[float, int, float, float] | None = None
    for d in range(0, max_dead + 1):
        rows = slice(d, len(y) - 1)
        X = np.column_stack([dy[rows], du[0 : len(y) - 1 - d]])
        target = dy[d + 1 :]
        ok = np.isfinite(X).all(axis=1) & np.isfinite(target)
        if ok.sum() < 10:
            continue
        coef, *_ = np.linalg.lstsq(X[ok], target[ok], rcond=None)
        err = float(np.mean((X[ok] @ coef - target[ok]) ** 2))
        if best is None or err < best[0]:
            best = (err, d, float(coef[0]), float(coef[1]))
    if best is None:
        raise ValueError("Too few samples to fit a model.")
    err, d, a, b = best
    a = min(max(a, 1e-6), 0.999999)
    var = float(np.nanvar(dy[1:]))
    one_step = Fopdt(
        gain=b / (1 - a),
        tau=-dt / math.log(a),
        dead_steps=d,
        dt=dt,
        u0=u0,
        y0=y0,
        r2=1 - err / var if var > 0 else 0.0,
    )
    return _output_error(one_step, du, dy, max_dead) or one_step


def _simulate(du: list[float], a: float, d: int) -> list[float]:
    """The unit-gain first order with dead time driven by ``du`` (from rest)."""

    x, out, first = 0.0, [0.0] * len(du), du[0]
    for k in range(1, len(du)):
        j = k - 1 - d
        drive = du[j] if j >= 0 else first
        x = a * x + (1 - a) * (drive if drive == drive else 0.0)
        out[k] = x
    return out


def _output_error(start: Fopdt, du: np.ndarray, dy: np.ndarray, max_dead: int) -> Fopdt | None:
    """The fit refined on the simulated response (output error), which a one-step-ahead fit
    misses on smooth or slowly sampled data: it then calls the process an integrator (a time
    constant of days, a huge gain). Searched over the time constant (from one step to half the
    window, log scale) and the dead time around the one-step fit's; the gain by least squares."""

    n = len(dy)
    if n < 20 or not np.isfinite(du).any():
        return None
    inputs = [float(v) for v in du]
    target = np.asarray(dy, dtype=float)
    seen = np.isfinite(target)
    var = float(np.var(target[seen])) if seen.any() else 0.0
    if var <= 0:
        return None

    def score(tau: float, d: int) -> tuple[float, float]:
        x = np.asarray(_simulate(inputs, math.exp(-start.dt / tau), d))
        xs, ys = x[seen], target[seen]
        power = float(xs @ xs)
        gain = float(xs @ ys) / power if power > 0 else 0.0
        return float(np.mean((ys - gain * xs) ** 2)), gain

    taus = [float(t) for t in np.geomspace(start.dt, max(start.dt * 2, n * start.dt / 2), 24)]
    if math.isfinite(start.tau) and start.dt <= start.tau <= taus[-1]:
        taus.append(start.tau)  # the one-step fit is right on clean data: keep it a candidate
    tau = min(taus, key=lambda t: score(t, start.dead_steps)[0])
    span = range(max(0, start.dead_steps - 6), min(max_dead, start.dead_steps + 6) + 1)
    d = min(span, key=lambda d: score(tau, d)[0])
    # Golden-section on log(tau) within a factor of two either side.
    ratio = (math.sqrt(5) - 1) / 2
    low, high = math.log(tau / 2), math.log(tau * 2)
    for _ in range(18):
        c, e = high - ratio * (high - low), low + ratio * (high - low)
        if score(math.exp(c), d)[0] < score(math.exp(e), d)[0]:
            high = e
        else:
            low = c
    middle = math.exp((low + high) / 2)
    if score(middle, d)[0] < score(tau, d)[0]:
        tau = middle
    err, gain = score(tau, d)
    return Fopdt(
        gain=gain,
        tau=tau,
        dead_steps=d,
        dt=start.dt,
        u0=start.u0,
        y0=start.y0,
        r2=1 - err / var,
    )
