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
    r2: float  # one-step-ahead fit

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
    return Fopdt(
        gain=b / (1 - a),
        tau=-dt / math.log(a),
        dead_steps=d,
        dt=dt,
        u0=u0,
        y0=y0,
        r2=1 - err / var if var > 0 else 0.0,
    )
