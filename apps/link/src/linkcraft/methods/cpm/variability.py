"""PV variability metrics, written with the method decorator."""

from __future__ import annotations

from plantcraft_sdk.methods import Finding, method, param

from linkcraft.i18n import t
from linkcraft.methods.references import BAUER_2016_CPM_SURVEY


@method(
    "pv_variability",
    name="Process variable variability",
    maturity="engineering_heuristic",
    references=[BAUER_2016_CPM_SURVEY],
    formula="std, range and coefficient of variation of the selected signal; score=std/variability_tolerance.",
    assumptions=["The selected window represents a comparable operating state."],
    limitations=[
        "Variability alone does not separate controller problems from process disturbances."
    ],
    min_samples=1,
    describe="Standard deviation of {std} around the mean {mean} (range {range}).",
)
def pv_variability(
    pv,
    *,
    variability_tolerance: float = param(
        1.0, gt=0.0, help="Reference standard deviation for 100 percent score."
    ),
):
    """Standard deviation, range and coefficient of variation of the PV."""

    std = float(pv.std(ddof=0))
    mean = float(pv.mean())
    cv_abs = std / abs(mean) if abs(mean) > 1e-12 else 0.0
    return Finding(
        score=100.0 * std / variability_tolerance,
        message=t("Variability calculated for pv."),
        metrics={
            "signal": "pv",
            "mean": mean,
            "std": std,
            "range": float(pv.max() - pv.min()),
            "cv_abs": cv_abs,
            "valid_samples": int(len(pv)),
        },
    )
