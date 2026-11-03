"""A regression trained once on a period (A4): ordinary least squares, ridge or partial least
squares (PLS), with the range it is valid in.

Calibrate fits it on the samples of the target (a lab analysis, an analyzer) and the inputs
at those times. The model keeps, besides its coefficients, each input's range in the training
(``low``, ``high``) and its fit (R², RMSE). At each run the block predicts at every step and
says where the inputs left that range: a regression extrapolates there, and its value is not
to be trusted.

- OLS: ``min ‖y - Xb‖²``, by least squares on the inputs as they are.
- Ridge: ``min ‖y - Xb‖² + α‖b‖²`` on standardised inputs (each input weighs the same).
- PLS (PLS1, NIPALS): the ``components`` directions of the standardised inputs that explain
  most of the target, for inputs that move together (collinear), where OLS is unstable.

Public methods only: Hoerl and Kennard (1970), Wold, Sjöström and Eriksson (2001), Kadlec,
Gabrys and Strandt (2009). Pure numpy.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from linkcraft.i18n import t

METHODS = ("ols", "ridge", "pls")
MIN_SAMPLES = 8


@dataclass
class Regression:
    method: str
    inputs: list[str]
    target: str
    intercept: float
    coefficients: list[float]  # one per input, in the inputs' own units
    low: list[float]
    high: list[float]
    samples: int
    r2: float
    rmse: float
    alpha: float = 0.0
    components: int = 0
    warnings: list[str] = field(default_factory=list)

    def predict(self, rows: np.ndarray) -> np.ndarray:
        return self.intercept + np.asarray(rows, dtype=float) @ np.asarray(self.coefficients)

    def outside(self, rows: np.ndarray, margin: float = 0.0) -> np.ndarray:
        """Per row and input: -1 below the training range (widened by ``margin`` of its span
        on each side), +1 above, 0 inside; NaN inputs count as inside."""

        rows = np.asarray(rows, dtype=float)
        low, high = np.asarray(self.low), np.asarray(self.high)
        spread = (high - low) * margin
        found = np.zeros(rows.shape, dtype=int)
        found[rows < low - spread] = -1
        found[rows > high + spread] = 1
        return found

    def as_dict(self) -> dict:
        return {
            "kind": "regression",
            "method": self.method,
            "inputs": self.inputs,
            "target": self.target,
            "intercept": self.intercept,
            "coefficients": self.coefficients,
            "low": self.low,
            "high": self.high,
            "samples": self.samples,
            "r2": self.r2,
            "rmse": self.rmse,
            "alpha": self.alpha,
            "components": self.components,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Regression:
        found = cls(
            method=str(data["method"]),
            inputs=[str(x) for x in data["inputs"]],
            target=str(data.get("target") or ""),
            intercept=float(data["intercept"]),
            coefficients=[float(x) for x in data["coefficients"]],
            low=[float(x) for x in data["low"]],
            high=[float(x) for x in data["high"]],
            samples=int(data.get("samples") or 0),
            r2=float(data.get("r2") or 0.0),
            rmse=float(data.get("rmse") or 0.0),
            alpha=float(data.get("alpha") or 0.0),
            components=int(data.get("components") or 0),
            warnings=[str(x) for x in data.get("warnings") or []],
        )
        size = len(found.inputs)
        if found.method not in METHODS:
            raise ValueError(f"method is one of {', '.join(METHODS)}")
        if not size or any(len(v) != size for v in (found.coefficients, found.low, found.high)):
            raise ValueError("one coefficient and one range per input")
        return found


def _pls1(z: np.ndarray, y: np.ndarray, components: int) -> np.ndarray:
    """PLS1 regression coefficients of centred ``y`` on standardised ``z`` (NIPALS)."""

    x, r = z.copy(), y.copy()
    weights, loadings, inner = [], [], []
    for _ in range(components):
        w = x.T @ r
        norm = float(np.linalg.norm(w))
        if norm < 1e-12:
            break
        w /= norm
        t = x @ w
        tt = float(t @ t)
        if tt < 1e-12:
            break
        p = x.T @ t / tt
        q = float(r @ t / tt)
        x = x - np.outer(t, p)
        r = r - q * t
        weights.append(w)
        loadings.append(p)
        inner.append(q)
    if not weights:
        return np.zeros(z.shape[1])
    w_mat, p_mat = np.column_stack(weights), np.column_stack(loadings)
    return w_mat @ np.linalg.solve(p_mat.T @ w_mat, np.asarray(inner))


def fit_regression(
    rows: np.ndarray,
    target: np.ndarray,
    inputs: list[str],
    *,
    target_name: str = "",
    method: str = "ridge",
    alpha: float = 1.0,
    components: int = 2,
) -> Regression:
    """The regression of ``target`` on ``rows`` (samples x inputs), from the samples where the
    target and every input have a value. ``ValueError`` in words when it cannot be fitted."""

    if method not in METHODS:
        raise ValueError(f"method is one of {', '.join(METHODS)}")
    rows = np.asarray(rows, dtype=float)
    target = np.asarray(target, dtype=float)
    keep = np.isfinite(target) & np.all(np.isfinite(rows), axis=1)
    rows, target = rows[keep], target[keep]
    needed = max(MIN_SAMPLES, 2 * len(inputs) + 2)
    if len(target) < needed:
        raise ValueError(
            t(
                "{found} samples of the target with every input, {needed} needed",
                found=len(target),
                needed=needed,
            )
        )
    mean, std = rows.mean(axis=0), rows.std(axis=0, ddof=1)
    warnings = [
        f"{name} did not move in the period: it cannot explain the target."
        for name, spread, level in zip(inputs, std, mean, strict=True)
        if spread <= 1e-12 * max(1.0, abs(float(level)))
    ]
    std = np.where(std > 0, std, 1.0)
    y_mean = float(target.mean())
    centred = target - y_mean
    if method == "ols":
        design = np.column_stack([np.ones(len(rows)), rows])
        solution, *_ = np.linalg.lstsq(design, target, rcond=None)
        intercept, coefficients = float(solution[0]), solution[1:]
    else:
        z = (rows - mean) / std
        if method == "ridge":
            gram = z.T @ z + alpha * np.eye(z.shape[1])
            scaled = np.linalg.solve(gram, z.T @ centred)
        else:
            components = max(1, min(components, len(inputs)))
            scaled = _pls1(z, centred, components)
        coefficients = scaled / std
        intercept = y_mean - float(mean @ coefficients)
    predicted = intercept + rows @ coefficients
    residual = target - predicted
    total = float(np.sum(centred**2))
    r2 = 1.0 - float(np.sum(residual**2)) / total if total > 0 else 0.0
    return Regression(
        method=method,
        inputs=list(inputs),
        target=target_name,
        intercept=intercept,
        coefficients=[float(x) for x in coefficients],
        low=[float(x) for x in rows.min(axis=0)],
        high=[float(x) for x in rows.max(axis=0)],
        samples=int(len(target)),
        r2=round(r2, 4),
        rmse=float(np.sqrt(np.mean(residual**2))),
        alpha=float(alpha) if method == "ridge" else 0.0,
        components=components if method == "pls" else 0,
        warnings=warnings,
    )
