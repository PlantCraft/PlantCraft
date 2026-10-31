"""The linear Kalman filter and the models it runs most often in a plant.

``kalman_filter`` runs any linear state-space model over a measured series, with an input when
the model has one. A missing sample (NaN) is a prediction only, so a gap in the data, an
analyzer between samples or a bad-quality stretch is bridged by the model. Two ready models:

- ``local_level``: the value wanders slowly and the sensor adds noise (filtering a noisy
  transmitter or analyzer without knowing the process);
- ``fopdt_model``: the measured value follows what drives it (a valve, a feed) through a first
  order with dead time, optionally plus a slowly drifting sensor bias (the bias becomes a state
  the filter estimates: a drift seen against the process model).

``tune`` picks the process noise by maximum likelihood of the innovations, so a person gives the
model and the filter finds how much to trust it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from plantcraft_sdk.estimators.identify import Fopdt


@dataclass
class StateSpace:
    """x[k+1] = A x[k] + B u[k] + w,  y[k] = C x[k] + v,  w ~ N(0, Q), v ~ N(0, R)."""

    A: np.ndarray
    C: np.ndarray
    Q: np.ndarray
    R: float
    B: np.ndarray | None = None
    x0: np.ndarray | None = None
    P0: np.ndarray | None = None
    # Steps the input takes to reach the state (dead time): u[k - delay] drives x[k + 1].
    delay: int = 0
    # A constant added to the input (the operating point the model was fitted around).
    u_offset: float = 0.0
    # A constant added to C x to give the measurement (the operating point of the output).
    y_offset: float = 0.0
    names: list[str] = field(default_factory=list)


@dataclass
class Filtered:
    states: np.ndarray  # (states, steps): one row per state
    variances: np.ndarray  # (states, steps): the diagonal of P
    estimate: np.ndarray  # C x: the filtered measurement
    innovations: np.ndarray  # y - C x_prior (NaN where y was missing)
    loglik: float


def kalman_filter(model: StateSpace, y: np.ndarray, u: np.ndarray | None = None) -> Filtered:
    """The filtered states over ``y`` (and the input ``u`` when the model has ``B``)."""

    y = np.asarray(y, dtype=float) - model.y_offset
    n = model.A.shape[0]
    steps = len(y)
    first = next((float(v) for v in y if math.isfinite(v)), 0.0)
    x = (
        np.array(model.x0, dtype=float)
        if model.x0 is not None
        else np.linalg.lstsq(model.C.reshape(1, -1), [first], rcond=None)[0]
    )
    P = np.array(model.P0, dtype=float) if model.P0 is not None else np.eye(n)
    C = model.C.reshape(1, n)
    c = C.ravel()
    states = np.empty((n, steps))
    variances = np.empty((n, steps))
    innovations = np.full(steps, np.nan)
    loglik = 0.0
    if u is not None:
        u = np.asarray(u, dtype=float) - model.u_offset
    if n == 1:
        return _scalar(model, y, u, float(x[0]), float(P[0, 0]))
    for k in range(steps):
        if k:
            x = model.A @ x
            if model.B is not None and u is not None:
                j = k - 1 - model.delay
                drive = u[j] if j >= 0 else u[0]
                if math.isfinite(drive):
                    x = x + model.B * drive
            P = model.A @ P @ model.A.T + model.Q
        if math.isfinite(y[k]):
            e = y[k] - float(c @ x)
            S = float(c @ P @ c) + model.R
            K = P @ c / S
            x = x + K * e
            P = P - np.outer(K, c @ P)
            innovations[k] = e
            loglik -= 0.5 * (math.log(2 * math.pi * S) + e * e / S)
        states[:, k] = x
        variances[:, k] = np.diag(P)
    return Filtered(states, variances, (C @ states).ravel() + model.y_offset, innovations, loglik)


def _scalar(model: StateSpace, y: np.ndarray, u: np.ndarray | None, x: float, p: float) -> Filtered:
    """The one-state filter on plain floats: the same steps, about ten times faster than the
    matrix loop, which matters when ``tune`` runs it a few dozen times."""

    a, q, r, c = float(model.A[0, 0]), float(model.Q[0, 0]), float(model.R), float(model.C[0])
    b = float(model.B[0]) if model.B is not None and u is not None else 0.0
    ys = y.tolist()
    us = u.tolist() if u is not None else []
    states, variances, innovations = [0.0] * len(ys), [0.0] * len(ys), [math.nan] * len(ys)
    loglik = 0.0
    log2pi = math.log(2 * math.pi)
    for k, value in enumerate(ys):
        if k:
            x = a * x
            if b:
                j = k - 1 - model.delay
                drive = us[j] if j >= 0 else us[0]
                if drive == drive:  # not NaN
                    x += b * drive
            p = a * a * p + q
        if value == value and value not in (math.inf, -math.inf):
            e = value - c * x
            s = c * c * p + r
            gain = p * c / s
            x += gain * e
            p -= gain * c * p
            innovations[k] = e
            loglik -= 0.5 * (log2pi + math.log(s) + e * e / s)
        states[k] = x
        variances[k] = p
    row = np.array([states])
    return Filtered(
        row,
        np.array([variances]),
        c * row[0] + model.y_offset,
        np.array(innovations),
        loglik,
    )


def noise_variance(y: np.ndarray) -> float:
    """The sensor's white noise variance from the series alone: half the variance of the
    first differences (the slow process cancels, the noise doubles)."""

    d = np.diff(np.asarray(y, dtype=float))
    d = d[np.isfinite(d)]
    return float(np.var(d) / 2) if len(d) > 2 else 1e-6


def local_level(q: float, r: float) -> StateSpace:
    """A value that wanders (random walk, variance ``q`` a step) seen with noise ``r``."""

    return StateSpace(A=np.eye(1), C=np.ones(1), Q=np.array([[q]]), R=r, names=["level"])


def fopdt_model(
    fit: Fopdt, q: float, r: float, *, bias: bool = False, q_bias: float = 0.0
) -> StateSpace:
    """A first order with dead time driven by the input; with ``bias``, a second state, the
    sensor's bias, that drifts as a random walk of variance ``q_bias`` a step."""

    a = math.exp(-fit.dt / fit.tau) if fit.tau > 0 else 0.0
    b = fit.gain * (1 - a)
    if not bias:
        return StateSpace(
            A=np.array([[a]]),
            B=np.array([b]),
            C=np.ones(1),
            Q=np.array([[q]]),
            R=r,
            x0=None,
            delay=fit.dead_steps,
            u_offset=fit.u0,
            y_offset=fit.y0,
            names=["process"],
        )
    return StateSpace(
        A=np.array([[a, 0.0], [0.0, 1.0]]),
        B=np.array([b, 0.0]),
        C=np.array([1.0, 1.0]),
        Q=np.diag([q, q_bias]),
        R=r,
        x0=np.array([0.0, 0.0]),
        P0=np.diag([1e-2, 1e-2]),
        delay=fit.dead_steps,
        u_offset=fit.u0,
        y_offset=fit.y0,
        names=["process", "bias"],
    )


def _golden(cost, low: float, high: float, tolerance: float) -> float:
    """The minimum of a one-humped ``cost`` on ``[low, high]`` by golden-section search (numpy
    only, so the SDK needs no SciPy)."""

    ratio = (math.sqrt(5) - 1) / 2
    a, b = low, high
    c, d = b - ratio * (b - a), a + ratio * (b - a)
    fc, fd = cost(c), cost(d)
    while b - a > tolerance:
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - ratio * (b - a)
            fc = cost(c)
        else:
            a, c, fc = c, d, fd
            d = a + ratio * (b - a)
            fd = cost(d)
    return (a + b) / 2


def tune(
    build, y: np.ndarray, u: np.ndarray | None = None, low: float = 1e-10, high: float = 1e-1
) -> tuple[float, Filtered]:
    """The process noise ``q`` (searched on a log scale) that makes the innovations most likely
    for ``build(q)``; with its filtered result."""

    def cost(log_q: float) -> float:
        return -kalman_filter(build(10.0**log_q), y, u).loglik

    q = 10.0 ** _golden(cost, math.log10(low), math.log10(high), 0.05)
    return q, kalman_filter(build(q), y, u)
