"""Noise: sample-to-sample scatter compared with the signal's engineering range."""

from __future__ import annotations

from plantcraft_sdk.methods import Finding, NotEnoughData, ScientificReference, method, param

from linkcraft.i18n import t
from linkcraft.methods.signal._common import is_text, limits, num, numbers, score_band
from linkcraft.methods.signal.spikes import noise_sigma


def _describe(metrics: dict) -> str:
    if metrics.get("noise_fraction") is None:
        return t(
            "Noise of {sigma} (no engineering limits to judge it against).",
            sigma=num(metrics.get("noise_sigma")),
        )
    return t(
        "Noise of {sigma}, {share} of the range.",
        sigma=num(metrics.get("noise_sigma")),
        share=f"{100 * float(metrics.get('noise_fraction') or 0):.2f}%",
    )


@method(
    "sq_noise",
    name="Noise",
    application="linkcraft",
    version="1.0.0",
    maturity="literature_based",
    min_samples=0,
    references=[
        ScientificReference(
            title="Distribution of the ratio of the mean square successive difference to the variance",
            authors=["von Neumann, J."],
            year=1941,
            venue="The Annals of Mathematical Statistics 12(4), 367-395",
            doi="10.1214/aoms/1177731677",
        )
    ],
    formula=(
        "noise = 1.4826 MAD(first differences) / sqrt(2) (white noise estimate that ignores slow "
        "process moves); judged as a share of high - low."
    ),
    limitations=[
        "Needs engineering limits to judge; without them it only reports the noise level.",
        "Fast real process moves (a flow under a fast controller) count as noise.",
    ],
    describe=_describe,
)
def noise(
    dataset,
    *,
    warn_fraction: float = param(
        0.01, gt=0, le=1, help="Noise, as a share of the range, that is a warning."
    ),
    bad_fraction: float = param(
        0.03, gt=0, le=1, help="Noise, as a share of the range, that hides the process."
    ),
):
    """High-frequency scatter that hides the process behind the instrument."""

    if is_text(dataset):
        return Finding(
            score=0, status="not_applicable", message=t("Text signals are not checked for noise.")
        )
    values = numbers(dataset)
    if len(values) < 10:
        raise NotEnoughData(t("Fewer than 10 numeric samples in the window."))
    sigma = noise_sigma(values.to_numpy())
    low, high = limits(dataset)
    if low is None or high is None:
        return Finding(
            score=0,
            status="not_applicable",
            metrics={"noise_sigma": round(sigma, 6), "noise_fraction": None},
        )
    share = sigma / (high - low)
    return Finding(
        score=score_band(share, warn_fraction, max(bad_fraction, warn_fraction * 1.001)),
        metrics={
            "noise_sigma": round(sigma, 6),
            "noise_fraction": round(share, 5),
            "apt": share < bad_fraction,
        },
    )
