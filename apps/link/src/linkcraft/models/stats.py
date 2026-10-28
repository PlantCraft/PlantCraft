"""Residual statistics of a twin: calibration, Hotelling's T², its limit and contributions.

A residual is what the plant measured minus what the model predicted, one column per output.
In normal operation residuals are small noise; their covariance ``S`` is calibrated on a period
the engineer marks as normal. For a residual vector ``r`` (centred on the calibrated mean only
when the twin asks for it):

- ``T² = rᵀ S⁻¹ r`` (Hotelling); beyond its limit the outputs together are farther from the
  model than normal operation explains. The limit is the chi-square quantile with one degree of
  freedom per output at the chosen confidence.
- the contribution of output ``i`` is ``r_i (S⁻¹ r)_i`` (they add up to T²); negative parts are
  set to zero and the rest normalised to percent: the share of the deviation each output
  explains, not a probability that it failed.

Public methods only (Hotelling 1931; MacGregor and Kourti 1995; Westerhuis et al. 2000). Pure
NumPy: no SciPy in the image.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import NormalDist

import numpy as np

# Smallest variance kept for an output (a perfectly quiet residual would divide by zero).
MIN_VARIANCE = 1e-12
# Fewer clean samples than this per output make a calibration unreliable.
MIN_CALIBRATION_SAMPLES = 30
# Calibration ignores rows farther than this many robust deviations from the median: a short
# upset inside the chosen period does not inflate what "normal" means.
TRIM_DEVIATIONS = 5.0
# MAD of a normal variable times this is its standard deviation.
MAD_TO_STD = 1.4826


def chi2_cdf(x: float, dof: int) -> float:
    """P(X <= x) for a chi-square variable: the regularised lower incomplete gamma function
    P(dof/2, x/2), by its power series (Abramowitz and Stegun 6.5.29)."""

    if x <= 0:
        return 0.0
    a, half = dof / 2.0, x / 2.0
    term = total = 1.0 / a
    n = 0
    while term > total * 1e-15 and n < 10_000:
        n += 1
        term *= half / (a + n)
        total += term
    return min(1.0, math.exp(-half + a * math.log(half) - math.lgamma(a)) * total)


def chi2_quantile(confidence: float, dof: int) -> float:
    """The chi-square quantile: the x with ``chi2_cdf(x, dof) == confidence`` (bisection)."""

    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence is between 0 and 1")
    if dof < 1:
        raise ValueError("at least one degree of freedom")
    low, high = 0.0, float(dof) + 10.0 * math.sqrt(2.0 * dof) + 50.0
    while chi2_cdf(high, dof) < confidence:
        high *= 2.0
    for _ in range(200):
        middle = (low + high) / 2.0
        if chi2_cdf(middle, dof) < confidence:
            low = middle
        else:
            high = middle
        if high - low < 1e-10 * high:
            break
    return (low + high) / 2.0


def normal_limit(confidence: float) -> float:
    """How many standard deviations a single residual may stray at ``confidence`` (two-sided)."""

    return NormalDist().inv_cdf(0.5 + confidence / 2.0)


def positive_definite(matrix: np.ndarray) -> np.ndarray:
    """The nearest symmetric matrix with eigenvalues at least ``MIN_VARIANCE`` relative to its
    largest one, so a calibration with collinear outputs still inverts."""

    symmetric = (matrix + matrix.T) / 2.0
    values, vectors = np.linalg.eigh(symmetric)
    floor = max(float(values.max(initial=0.0)), 1.0) * MIN_VARIANCE
    values = np.clip(values, floor, None)
    return (vectors * values) @ vectors.T


@dataclass
class Calibration:
    """Residual statistics of normal operation, one entry per output in ``outputs`` order."""

    outputs: list[str]
    mean: list[float]
    cov: list[list[float]]
    samples: int
    warnings: list[str] = field(default_factory=list)

    @property
    def std(self) -> list[float]:
        return [math.sqrt(max(self.cov[i][i], MIN_VARIANCE)) for i in range(len(self.outputs))]

    def as_dict(self) -> dict:
        return {
            "outputs": self.outputs,
            "mean": self.mean,
            "cov": self.cov,
            "std": self.std,
            "samples": self.samples,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Calibration:
        return cls(
            outputs=list(data["outputs"]),
            mean=[float(x) for x in data["mean"]],
            cov=[[float(x) for x in row] for row in data["cov"]],
            samples=int(data.get("samples") or 0),
            warnings=list(data.get("warnings") or []),
        )


def calibrate(residuals: np.ndarray, outputs: list[str]) -> Calibration:
    """Mean and covariance of residuals (rows: samples, columns: outputs), from the rows where
    every output has a value. Warns, in words, when the period does not look like normal
    operation (a residual that sits far from zero is a model or sensor offset, not noise)."""

    data = np.asarray(residuals, dtype=float)
    if data.ndim != 2 or data.shape[1] != len(outputs):
        raise ValueError("one column of residuals per output")
    clean = data[np.all(np.isfinite(data), axis=1)]
    clean, trimmed = _trim(clean)
    if len(clean) < MIN_CALIBRATION_SAMPLES:
        raise ValueError(
            f"only {len(clean)} samples with every output measured; "
            f"a calibration needs at least {MIN_CALIBRATION_SAMPLES}"
        )
    mean = clean.mean(axis=0)
    cov = positive_definite(np.atleast_2d(np.cov(clean, rowvar=False, ddof=1)))
    warnings = []
    if trimmed:
        share = trimmed / (trimmed + len(clean)) * 100
        warnings.append(
            f"{trimmed} samples ({share:.0f}%) were far from the rest and left out"
            " (an upset inside the period)"
        )
    for index, name in enumerate(outputs):
        spread = math.sqrt(cov[index, index])
        if abs(mean[index]) > 3.0 * spread:
            warnings.append(
                f"{name}: the residual averages {mean[index]:.3g}, {abs(mean[index]) / spread:.0f}"
                " times its spread; the model or the sensor is offset in this period"
            )
    return Calibration(
        outputs=list(outputs),
        mean=[float(x) for x in mean],
        cov=[[float(x) for x in row] for row in cov],
        samples=int(len(clean)),
        warnings=warnings,
    )


def _trim(rows: np.ndarray) -> tuple[np.ndarray, int]:
    """Rows within ``TRIM_DEVIATIONS`` robust deviations of the median on every output."""

    if len(rows) < MIN_CALIBRATION_SAMPLES:
        return rows, 0
    median = np.median(rows, axis=0)
    spread = np.median(np.abs(rows - median), axis=0) * MAD_TO_STD
    spread = np.where(spread > 0, spread, np.inf)
    keep = np.all(np.abs(rows - median) <= TRIM_DEVIATIONS * spread, axis=1)
    return rows[keep], int((~keep).sum())


@dataclass
class Judgement:
    """T² of every sample, its limit and how the outputs share the deviation."""

    t2: np.ndarray
    limit: float
    exceed_share: float
    contributions: dict[str, float]
    # Per output: mean residual, mean residual in standard deviations, share beyond its limit.
    outputs: dict[str, dict[str, float]]


def judge(
    residuals: np.ndarray,
    calibration: Calibration,
    *,
    confidence: float = 0.99,
    centre: bool = False,
) -> Judgement:
    """Judge residual rows (samples x outputs, NaN where not measured) against a calibration."""

    data = np.asarray(residuals, dtype=float)
    names = calibration.outputs
    if data.ndim != 2 or data.shape[1] != len(names):
        raise ValueError("one column of residuals per output")
    mean = np.asarray(calibration.mean) if centre else np.zeros(len(names))
    cov = np.asarray(calibration.cov, dtype=float)
    inverse = np.linalg.inv(cov)
    centred = data - mean
    rows = np.all(np.isfinite(centred), axis=1)
    t2 = np.full(len(data), np.nan)
    terms = np.zeros_like(centred)
    if rows.any():
        clean = centred[rows]
        weighted = clean @ inverse
        terms[rows] = clean * weighted
        t2[rows] = terms[rows].sum(axis=1)
    limit = chi2_quantile(confidence, len(names))
    valid = np.isfinite(t2)
    beyond = valid & (t2 > limit)
    exceed = float(beyond.sum() / valid.sum()) if valid.any() else 0.0
    focus = beyond if beyond.any() else valid
    shares = np.clip(terms[focus].sum(axis=0), 0.0, None) if focus.any() else np.zeros(len(names))
    total = float(shares.sum())
    contributions = {
        name: (float(shares[i]) / total * 100.0 if total > 0 else 0.0)
        for i, name in enumerate(names)
    }
    std = np.sqrt(np.clip(np.diag(cov), MIN_VARIANCE, None))
    single = normal_limit(confidence)
    outputs = {}
    for index, name in enumerate(names):
        column = centred[:, index]
        seen = np.isfinite(column)
        if not seen.any():
            outputs[name] = {"mean": math.nan, "z": math.nan, "exceed_share": math.nan}
            continue
        values = column[seen]
        outputs[name] = {
            "mean": float(data[seen, index].mean()),
            "z": float(values.mean() / std[index]),
            "exceed_share": float((np.abs(values) > single * std[index]).mean()),
        }
    return Judgement(
        t2=t2, limit=limit, exceed_share=exceed, contributions=contributions, outputs=outputs
    )
