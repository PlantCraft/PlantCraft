"""A soft sensor: a value estimated from other signals, by ridge regression on their recent past.

The typical case is a quality a lab or an analyzer gives rarely or late (sulfur in product, a
melt index) estimated every minute from the flows, temperatures and pressures that drive it.
Each input enters with ``lags`` past samples (its dynamics), the inputs are scaled, and a ridge
penalty keeps a few correlated inputs from fighting. Fitted on the samples where the target
exists, it can be checked on held-out ones before anyone trusts it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class SoftSensor:
    lags: list[int]
    mean: np.ndarray
    scale: np.ndarray
    coef: np.ndarray
    intercept: float
    names: list[str]

    def features(self, X: np.ndarray) -> np.ndarray:
        return _lagged(np.asarray(X, dtype=float), self.lags)

    def predict(self, X: np.ndarray) -> np.ndarray:
        F = self.features(X)
        return ((F - self.mean) / self.scale) @ self.coef + self.intercept


def _lagged(X: np.ndarray, lags: list[int]) -> np.ndarray:
    if X.ndim == 1:
        X = X[:, None]
    columns = []
    for j in range(X.shape[1]):
        for lag in lags:
            col = np.full(X.shape[0], np.nan)
            col[lag:] = X[: X.shape[0] - lag, j] if lag else X[:, j]
            columns.append(col)
    return np.column_stack(columns)


def fit_soft_sensor(
    X: np.ndarray,
    y: np.ndarray,
    lags: list[int],
    alpha: float = 1.0,
    names: list[str] | None = None,
) -> SoftSensor:
    """Fit on the samples where ``y`` and every lagged input exist."""

    F = _lagged(np.asarray(X, dtype=float), lags)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(F).all(axis=1) & np.isfinite(y)
    if ok.sum() < F.shape[1] + 5:
        raise ValueError("Too few samples with the target to fit a soft sensor.")
    mean = F[ok].mean(axis=0)
    scale = F[ok].std(axis=0)
    scale[scale == 0] = 1.0
    Z = (F[ok] - mean) / scale
    target = y[ok]
    intercept = float(target.mean())
    coef = np.linalg.solve(Z.T @ Z + alpha * np.eye(Z.shape[1]), Z.T @ (target - intercept))
    return SoftSensor(lags, mean, scale, coef, intercept, names or [])
