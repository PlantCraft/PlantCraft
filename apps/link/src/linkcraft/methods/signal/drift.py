"""Drift: a slow, steady change of the signal against a reference (or on its own)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from plantcraft_sdk.methods import Finding, NotEnoughData, ScientificReference, method, param

from linkcraft.i18n import t
from linkcraft.methods.signal._common import (
    event,
    is_text,
    limits,
    num,
    numbers,
    robust_span,
    window,
)

MAD_TO_SIGMA = 1.4826


def bucket_medians(
    values: pd.Series, start: pd.Timestamp, end: pd.Timestamp, count: int
) -> pd.Series:
    """The median of each of ``count`` equal time slices of ``[start, end]``, indexed by slice."""

    if values.empty:
        return pd.Series(dtype=float)
    seconds = (values.index - start).total_seconds().to_numpy()
    width = (end - start).total_seconds() / count
    slot = np.clip((seconds // width).astype(int), 0, count - 1)
    return values.groupby(slot).median()


def mann_kendall(values: np.ndarray) -> tuple[float, float]:
    """Kendall's tau of the values against time and its two-sided p-value (no ties correction)."""

    n = values.size
    signs = np.sign(values[None, :] - values[:, None])
    s = float(np.triu(signs, 1).sum())
    variance = n * (n - 1) * (2 * n + 5) / 18.0
    if variance <= 0:
        return 0.0, 1.0
    z = (s - math.copysign(1.0, s)) / math.sqrt(variance) if s else 0.0
    return s / (n * (n - 1) / 2.0), math.erfc(abs(z) / math.sqrt(2.0))


def theil_sen(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Median of the pairwise slopes, and the intercept through the medians."""

    i, j = np.triu_indices(x.size, 1)
    dx = x[j] - x[i]
    keep = dx != 0
    if not keep.any():
        return 0.0, float(np.median(y))
    slope = float(np.median((y[j] - y[i])[keep] / dx[keep]))
    return slope, float(np.median(y - slope * x))


def _describe(metrics: dict) -> str:
    against = t("against its reference") if metrics.get("with_reference") else t("on its own")
    return t(
        "Change of {change} over the window {against} ({share} of the range, Kendall tau {tau}).",
        change=num(metrics.get("change")),
        against=against,
        share=f"{100 * float(metrics.get('change_fraction') or 0):.1f}%",
        tau=num(metrics.get("tau")),
    )


@method(
    "sq_drift",
    name="Drift",
    application="linkcraft",
    version="1.0.0",
    maturity="literature_based",
    min_samples=0,
    references=[
        ScientificReference(
            title="Nonparametric tests against trend",
            authors=["Mann, H. B."],
            year=1945,
            venue="Econometrica 13(3), 245-259",
            doi="10.2307/1907187",
        ),
        ScientificReference(
            title="Estimates of the regression coefficient based on Kendall's tau",
            authors=["Sen, P. K."],
            year=1968,
            venue="Journal of the American Statistical Association 63(324), 1379-1389",
            doi="10.1080/01621459.1968.10480934",
        ),
    ],
    formula=(
        "d = slice medians of (signal - reference), or of the signal without a reference; "
        "Mann-Kendall test on d, change = Theil-Sen slope x window, compared with the range "
        "(engineering limits, else the 1-99 percentile range) and with d's scatter."
    ),
    assumptions=[
        "With a reference (a redundant or model-predicted measurement of the same quantity) "
        "the difference should stay level; a steady change in it is sensor drift."
    ],
    limitations=[
        "Without a reference a steady trend can be the process itself, so the check reports "
        "the trend but does not judge it.",
    ],
    describe=_describe,
)
def drift(
    dataset,
    *,
    slices: int = param(24, ge=8, le=200, help="Time slices the window is split into."),
    warn_change: float = param(
        0.02, gt=0, le=1, help="Change over the window, as a share of the range, that is a warning."
    ),
    bad_change: float = param(
        0.05, gt=0, le=1, help="Change over the window, as a share of the range, that is drift."
    ),
    max_p_value: float = param(
        0.001, gt=0, le=0.5, help="Largest p-value of the trend test that counts as a trend."
    ),
):
    """A steady trend that a stable process should not have: the sensor slowly walks away."""

    if is_text(dataset):
        return Finding(score=0, status="not_applicable", message=t("Text signals do not drift."))
    span = window(dataset)
    values = numbers(dataset)
    if span is None or len(values) < slices:
        raise NotEnoughData(t("Too few numeric samples to look for a trend."))
    start, end = span
    reference = numbers(dataset, "reference")
    with_reference = len(reference) >= slices
    medians = bucket_medians(values, start, end, slices)
    if with_reference:
        medians = (medians - bucket_medians(reference, start, end, slices)).dropna()
    if len(medians) < 8:
        raise NotEnoughData(t("Too few time slices with data to look for a trend."))
    x = medians.index.to_numpy(dtype=float)
    y = medians.to_numpy(dtype=float)
    tau, p_value = mann_kendall(y)
    slope, intercept = theil_sen(x, y)
    change = slope * slices
    residual = y - (slope * x + intercept)
    scatter = MAD_TO_SIGMA * float(np.median(np.abs(residual - np.median(residual))))
    low, high = limits(dataset)
    width = (
        (high - low)
        if low is not None and high is not None
        else robust_span(reference if with_reference else values)
    )
    share = abs(change) / width if width > 0 else 0.0
    trend = p_value <= max_p_value and abs(change) > 3.0 * scatter
    score = 0.0
    if trend:
        score = (
            25.0 * share / warn_change
            if share < warn_change
            else 25.0
            + 50.0 * min(1.0, (share - warn_change) / max(1e-9, bad_change - warn_change))
            + (min(25.0, 25.0 * (share - bad_change) / bad_change) if share >= bad_change else 0.0)
        )
    if not with_reference:
        # A steady trend alone may be the process: report it, do not judge it.
        return Finding(
            score=0,
            status="not_applicable",
            metrics={
                "change": round(change, 6),
                "change_fraction": round(share, 4),
                "tau": round(tau, 3),
                "p_value": float(f"{p_value:.3g}"),
                "with_reference": False,
                "trend": trend,
            },
            message=t(
                "No reference signal, so drift cannot be told from a process change (change of "
                "{change} over the window). Give the signal a reference to check it.",
                change=num(change),
            ),
        )
    events = (
        [
            event(
                start,
                end,
                t("Drift") if with_reference else t("Steady trend"),
                change=round(change, 6),
            )
        ]
        if score >= 25
        else []
    )
    return Finding(
        score=score,
        metrics={
            "change": round(change, 6),
            "change_fraction": round(share, 4),
            "tau": round(tau, 3),
            "p_value": float(f"{p_value:.3g}"),
            "with_reference": with_reference,
            "apt": score < 75,
        },
        events=events,
    )
