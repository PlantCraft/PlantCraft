"""An empirical model of normal operation by principal components (PCA), for a unit with no
physical model (M4).

Calibration standardises each signal on a period of normal operation and keeps the principal
components that explain ``variance`` of it. A sample is then judged two ways:

- ``T²`` (Hotelling) inside the model: ``T² = Σ_a t_a² / λ_a`` over the kept components. Beyond
  its limit the plant moves along its normal directions, but farther than normal operation.
- ``SPE`` (Q, squared prediction error) off the model: ``SPE = ‖z - t Pᵀ‖²``. Beyond its limit
  the signals no longer move together the way they did, which is usually how a fault shows.

Limits: ``χ²(confidence, k)`` for T² (the large-sample limit; calibrations have thousands of
samples) and Box's ``g χ²(confidence, h)`` for SPE, with ``g = θ₂/θ₁`` and ``h = θ₁²/θ₂`` from the
eigenvalues left out. The contribution of each signal is its share of the SPE (``e_i²``) or of
the T² (``z_i Σ_a t_a p_ia / λ_a``, positive parts) over the samples beyond a limit.

Public methods only: Jackson (1991), MacGregor and Kourti (1995), Box (1954), Qin (2003),
Westerhuis et al. (2000). Pure numpy.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from linkcraft.i18n import t
from linkcraft.models.stats import chi2_quantile

MIN_SAMPLES_PER_SIGNAL = 5
MIN_SAMPLES = 50
# A signal whose standard deviation in the calibration is below this (relative to its mean
# level) is constant there: it cannot be standardised and is left out, with a warning.
MIN_RELATIVE_STD = 1e-9


@dataclass
class PcaModel:
    signals: list[str]
    mean: list[float]
    std: list[float]
    loadings: list[list[float]]  # signals x components
    eigenvalues: list[float]  # of the kept components
    residual_eigenvalues: list[float]  # of the components left out
    samples: int
    explained: float
    warnings: list[str] = field(default_factory=list)

    @property
    def components(self) -> int:
        return len(self.eigenvalues)

    def limits(self, confidence: float) -> tuple[float, float]:
        """The T² and SPE limits at ``confidence``."""

        t2 = chi2_quantile(confidence, max(1, self.components))
        rest = np.asarray(self.residual_eigenvalues, dtype=float)
        theta1, theta2 = float(rest.sum()), float((rest**2).sum())
        if theta1 <= 0 or theta2 <= 0:
            return t2, 1e-9
        g, h = theta2 / theta1, max(1.0, theta1**2 / theta2)
        return t2, g * chi2_quantile(confidence, max(1, round(h)))

    def as_dict(self) -> dict:
        return {
            "kind": "pca",
            "signals": self.signals,
            "mean": self.mean,
            "std": self.std,
            "loadings": self.loadings,
            "eigenvalues": self.eigenvalues,
            "residual_eigenvalues": self.residual_eigenvalues,
            "samples": self.samples,
            "explained": self.explained,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PcaModel:
        found = cls(
            signals=[str(x) for x in data["signals"]],
            mean=[float(x) for x in data["mean"]],
            std=[float(x) for x in data["std"]],
            loadings=[[float(x) for x in row] for row in data["loadings"]],
            eigenvalues=[float(x) for x in data["eigenvalues"]],
            residual_eigenvalues=[float(x) for x in data.get("residual_eigenvalues") or []],
            samples=int(data.get("samples") or 0),
            explained=float(data.get("explained") or 0.0),
            warnings=[str(x) for x in data.get("warnings") or []],
        )
        size = len(found.signals)
        if not size or len(found.mean) != size or len(found.std) != size:
            raise ValueError("one mean and one deviation per signal")
        if len(found.loadings) != size or any(
            len(row) != found.components for row in found.loadings
        ):
            raise ValueError("one loading per signal and component")
        if not found.components or any(value <= 0 for value in found.eigenvalues):
            raise ValueError("at least one component with a positive variance")
        return found


def fit_pca(
    rows: np.ndarray, signals: list[str], *, variance: float = 0.9, max_components: int = 0
) -> PcaModel:
    """The PCA model of ``rows`` (samples x signals), from the rows where every signal has a
    value; constant signals are left out with a warning. ``ValueError`` when too few rows."""

    rows = np.asarray(rows, dtype=float)
    rows = rows[np.all(np.isfinite(rows), axis=1)]
    needed = max(MIN_SAMPLES, MIN_SAMPLES_PER_SIGNAL * len(signals))
    if len(rows) < needed:
        raise ValueError(
            t("{found} complete samples, {needed} needed", found=len(rows), needed=needed)
        )
    mean = rows.mean(axis=0)
    std = rows.std(axis=0, ddof=1)
    level = np.maximum(np.abs(mean), 1.0)
    keep = std > MIN_RELATIVE_STD * level
    warnings = [
        f"{name} is constant in the period and is left out."
        for name, kept in zip(signals, keep, strict=True)
        if not kept
    ]
    if keep.sum() < 2:
        raise ValueError(t("fewer than two signals vary in the period"))
    names = [name for name, kept in zip(signals, keep, strict=True) if kept]
    mean, std = mean[keep], std[keep]
    z = (rows[:, keep] - mean) / std
    covariance = (z.T @ z) / (len(z) - 1)
    values, vectors = np.linalg.eigh(covariance)
    order = np.argsort(values)[::-1]
    values, vectors = np.clip(values[order], 0.0, None), vectors[:, order]
    share = np.cumsum(values) / values.sum()
    k = int(np.searchsorted(share, min(max(variance, 0.01), 0.999)) + 1)
    if max_components:
        k = min(k, max_components)
    k = max(1, min(k, len(names) - 1))
    return PcaModel(
        signals=names,
        mean=mean.tolist(),
        std=std.tolist(),
        loadings=vectors[:, :k].tolist(),
        eigenvalues=values[:k].tolist(),
        residual_eigenvalues=values[k:].tolist(),
        samples=len(rows),
        explained=float(share[k - 1]),
        warnings=warnings,
    )


@dataclass
class PcaJudgement:
    t2: np.ndarray
    spe: np.ndarray
    t2_limit: float
    spe_limit: float
    exceed_share: float
    contributions: dict[str, float]
    spe_share: float  # of the samples beyond a limit, those beyond the SPE limit


def judge_pca(rows: np.ndarray, model: PcaModel, *, confidence: float = 0.99) -> PcaJudgement:
    """T² and SPE of every row (samples x ``model.signals``), the share beyond either limit and
    each signal's share of the excess (percent). Rows with a missing value are NaN."""

    rows = np.asarray(rows, dtype=float)
    z = (rows - np.asarray(model.mean)) / np.asarray(model.std)
    p = np.asarray(model.loadings)
    lam = np.asarray(model.eigenvalues)
    scores = z @ p
    t2 = np.sum(scores**2 / lam, axis=1)
    residual = z - scores @ p.T
    spe = np.sum(residual**2, axis=1)
    t2_limit, spe_limit = model.limits(confidence)
    valid = np.all(np.isfinite(z), axis=1)
    t2[~valid] = np.nan
    spe[~valid] = np.nan
    over_t2 = valid & (t2 > t2_limit)
    over_spe = valid & (spe > spe_limit)
    over = over_t2 | over_spe
    judged = int(valid.sum())
    exceed = float(over.sum()) / judged if judged else 0.0
    weights = np.zeros(len(model.signals))
    if over_spe.any():
        weights += np.sum(residual[over_spe] ** 2, axis=0) / spe_limit
    if over_t2.any():
        t2_parts = z[over_t2] * ((scores[over_t2] / lam) @ p.T)
        weights += np.sum(np.clip(t2_parts, 0.0, None), axis=0) / t2_limit
    total = float(weights.sum())
    contributions = {
        name: round(100.0 * float(value) / total, 1) if total > 0 else 0.0
        for name, value in zip(model.signals, weights, strict=True)
    }
    return PcaJudgement(
        t2=t2,
        spe=spe,
        t2_limit=t2_limit,
        spe_limit=spe_limit,
        exceed_share=exceed,
        contributions=contributions,
        spe_share=float(over_spe.sum()) / float(over.sum()) if over.any() else 0.0,
    )
