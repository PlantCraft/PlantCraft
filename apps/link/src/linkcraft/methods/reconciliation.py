"""Linear data reconciliation with gross error detection (mass balances), NumPy only.

Measurements ``y`` of flows that must satisfy linear balances ``A x = 0`` never do exactly: each
meter has its noise and, sometimes, a bias. Reconciliation finds the values closest to the
measurements, weighted by each meter's variance, that close every balance:

    x̂ = y − Σ Aᵀ (A Σ Aᵀ)⁻¹ A y

The global test says whether the balances are off by more than the meters' uncertainty
(γ = rᵀ V⁻¹ r, r = A y, V = A Σ Aᵀ, against χ² with one degree of freedom per balance). The
measurement test says which meter: z_i = |a_i| / √W_ii on the adjustments a = y − x̂, with
W = Σ Aᵀ V⁻¹ A Σ, against the normal quantile at the Šidák level for n tests. Serial
elimination drops the most suspect meter (it becomes unmeasured: a huge variance) and tests
again, until the global test passes or no redundancy is left.

References: Mah, R. S. H., Tamhane, A. C. (1982), Detection of gross errors in process data,
AIChE Journal 28(5); Crowe, C. M., Garcia Campos, Y. A., Hrymak, A. (1983), Reconciliation of
process flow rates by matrix projection, AIChE Journal 29(6); Narasimhan, S., Jordache, C.
(2000), Data Reconciliation and Gross Error Detection, Gulf Publishing.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from statistics import NormalDist

import numpy as np

UNMEASURED = 1e12  # the variance that makes a meter count as not measured
_TERM = re.compile(r"^\s*([+-]?)\s*(?:(\d+(?:\.\d*)?|\.\d+)\s*\*\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*$")


class BalanceError(ValueError):
    """The balances' text cannot be read."""


def parse_balances(text: str, names: list[str]) -> np.ndarray:
    """``"s1 + s2 = s3; s3 = s4 + 0.5*s5"`` as the matrix A (one row per balance, one column per
    name), each row ``Σ in − Σ out = 0``. Unknown names and empty sides are errors."""

    rows: list[np.ndarray] = []
    for number, balance in enumerate(part for part in re.split(r"[;\n]", text) if part.strip()):
        sides = balance.split("=")
        if len(sides) != 2 or not sides[0].strip() or not sides[1].strip():
            raise BalanceError(f"balance {number + 1} is not 'a + b = c': {balance.strip()[:60]}")
        row = np.zeros(len(names))
        for side, sign in ((sides[0], 1.0), (sides[1], -1.0)):
            for term in re.split(r"(?=[+-])", side.strip()):
                if not term.strip():
                    continue
                found = _TERM.match(term)
                if not found:
                    raise BalanceError(f"not a term: {term.strip()[:40]}")
                minus, factor, name = found.groups()
                if name not in names:
                    raise BalanceError(f"unknown stream: {name}")
                value = float(factor) if factor else 1.0
                row[names.index(name)] += sign * (-value if minus == "-" else value)
        if not row.any():
            raise BalanceError(f"balance {number + 1} cancels out")
        rows.append(row)
    if not rows:
        raise BalanceError("no balance")
    return np.vstack(rows)


def chi2_quantile(p: float, dof: int) -> float:
    """The χ² quantile: exact for 1 and 2 degrees of freedom, Wilson and Hilferty's
    approximation above (within 1% at the levels used here), no SciPy."""

    if dof <= 0:
        return math.inf
    if dof == 1:
        return NormalDist().inv_cdf((1.0 + p) / 2.0) ** 2
    if dof == 2:
        return -2.0 * math.log(1.0 - p)
    z = NormalDist().inv_cdf(p)
    k = 2.0 / (9.0 * dof)
    return dof * max(0.0, 1.0 - k + z * math.sqrt(k)) ** 3


@dataclass
class Reconciled:
    """The reconciled values, the tests and what serial elimination found, for one sample."""

    values: np.ndarray
    adjustments: np.ndarray
    gamma: float
    critical: float
    z: np.ndarray
    z_critical: float
    suspects: list[int] = field(default_factory=list)
    redundant: np.ndarray = field(default_factory=lambda: np.array([], dtype=bool))

    @property
    def gross_error(self) -> bool:
        return bool(self.suspects)


def _solve(a: np.ndarray, y: np.ndarray, variances: np.ndarray) -> tuple[np.ndarray, ...]:
    sigma = np.diag(variances)
    v = a @ sigma @ a.T
    v_inv = np.linalg.pinv(v)
    gain = sigma @ a.T @ v_inv
    x = y - gain @ (a @ y)
    w = gain @ a @ sigma
    return x, v_inv, w


def reconcile(
    a: np.ndarray, y: np.ndarray, variances: np.ndarray, alpha: float = 0.05
) -> Reconciled:
    """Reconcile one sample ``y`` (a meter not read is NaN: unmeasured) and find its gross
    errors by serial elimination."""

    y = np.asarray(y, dtype=float)
    variances = np.asarray(variances, dtype=float).copy()
    measured = np.isfinite(y)
    variances[~measured] = UNMEASURED
    y = np.where(measured, y, 0.0)
    rank = int(np.linalg.matrix_rank(a))
    level = 1.0 - (1.0 - alpha) ** (1.0 / max(1, int(measured.sum())))
    z_critical = NormalDist().inv_cdf(1.0 - level / 2.0)
    suspects: list[int] = []
    first: tuple[np.ndarray, np.ndarray, float, float] | None = None
    while True:
        x, v_inv, w = _solve(a, y, variances)
        r = a @ y
        # Unmeasured meters take up the balances they are in: fewer degrees of freedom.
        dof = _degrees(a, variances, rank)
        gamma = float(r @ v_inv @ r) if dof > 0 else 0.0
        critical = chi2_quantile(1.0 - alpha, dof)
        diag = np.clip(np.diag(w), 0.0, None)
        redundant = (diag > 1e-9 * np.maximum(variances, 1e-300)) & (variances < UNMEASURED)
        z = np.zeros(len(y))
        z[redundant] = np.abs(y - x)[redundant] / np.sqrt(diag[redundant])
        if first is None:
            first = (z.copy(), redundant.copy(), gamma, critical)
        if gamma <= critical or not redundant.any():
            break
        worst = int(np.argmax(np.where(redundant, z, -1.0)))
        if z[worst] <= z_critical:
            break
        suspects.append(worst)
        variances[worst] = UNMEASURED
    z0, redundant0, gamma0, critical0 = first
    return Reconciled(
        values=x,
        adjustments=np.where(measured, y - x, np.nan),
        gamma=gamma0,
        critical=critical0,
        z=z0,
        z_critical=z_critical,
        suspects=suspects,
        redundant=redundant0,
    )


def _degrees(a: np.ndarray, variances: np.ndarray, rank: int) -> int:
    """Degrees of freedom of the global test: the balances left once the unmeasured meters are
    solved for (rank of A minus the rank of A's unmeasured columns)."""

    unmeasured = variances >= UNMEASURED
    if not unmeasured.any():
        return rank
    return rank - int(np.linalg.matrix_rank(a[:, unmeasured]))


def reconcile_series(a: np.ndarray, y: np.ndarray, variances: np.ndarray) -> np.ndarray:
    """Reconcile every row of ``y`` (samples × meters) with the same variances, at once (no
    gross error search; a row with a missing meter keeps NaN)."""

    sigma = np.diag(variances)
    gain = sigma @ a.T @ np.linalg.pinv(a @ sigma @ a.T)
    out = y - (y @ a.T) @ gain.T
    out[~np.isfinite(y).all(axis=1)] = np.nan
    return out


__all__ = [
    "BalanceError",
    "Reconciled",
    "chi2_quantile",
    "parse_balances",
    "reconcile",
    "reconcile_series",
]
