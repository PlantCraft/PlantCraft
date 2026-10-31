"""Availability: how much of the window the signal's samples actually cover."""

from __future__ import annotations

import numpy as np
import pandas as pd
from plantcraft_sdk.methods import Finding, NotEnoughData, method, param

from linkcraft.i18n import t
from linkcraft.methods.signal._common import (
    event,
    quality_spans,
    samples,
    score_band,
    window,
    worst_events,
)


@method(
    "sq_availability",
    name="Availability and gaps",
    application="linkcraft",
    version="1.1.0",
    maturity="engineering_heuristic",
    min_samples=0,
    formula=(
        "coverage = 1 - sum(max(0, interval - max_gap)) / window, over the recorded samples "
        "(the window's start and end count as edges); a gap is an interval above max_gap. "
        "When the source keeps quality, time it marked substituted counts as missing too, and "
        "time marked uncertain above 1 - warn_coverage is a warning."
    ),
    assumptions=[
        "Historians that record on change keep long intervals on a steady signal; intervals "
        "up to the maximum gap count as valid data."
    ],
    limitations=[
        "Checks that values exist, not that they are right.",
        "Does not tell a communication failure from stopped equipment.",
        "A bad sample is no value, so bad time shows as a gap only when it is longer than "
        "the maximum gap; its share is reported apart.",
    ],
    describe="Samples cover {coverage:%} of the window; {gap_count} gaps, the longest "
    "{largest_gap_minutes:.1} min.",
)
def availability(
    dataset,
    *,
    max_gap_seconds: float = param(
        600.0, gt=0, help="Longest interval between samples that still counts as data."
    ),
    warn_coverage: float = param(0.95, gt=0, le=1, help="Coverage below this is a warning."),
    min_coverage: float = param(
        0.8, gt=0, le=1, help="Coverage below this makes the data unusable."
    ),
):
    """Share of the window covered by samples, and the gaps between them."""

    span = window(dataset)
    if span is None:
        raise NotEnoughData(t("The window is empty."))
    start, end = span
    values = samples(dataset)
    inside = values.index[(values.index >= start) & (values.index <= end)]
    edges = (
        pd.DatetimeIndex([start]).append(pd.DatetimeIndex(inside)).append(pd.DatetimeIndex([end]))
    )
    intervals = (edges[1:] - edges[:-1]).total_seconds().to_numpy()
    duration = (end - start).total_seconds()
    missing = float(np.clip(intervals - max_gap_seconds, 0.0, None).sum())
    gaps = [
        (float(intervals[i]), event(edges[i], edges[i + 1], t("Gap"), seconds=float(intervals[i])))
        for i in np.flatnonzero(intervals > max_gap_seconds)
    ]
    gap_count = len(gaps)
    # The source's own word on its samples (OPC UA / PI quality), when the Historian keeps it.
    spans = quality_spans(dataset, start, end)
    shares: dict[str, float] = {}
    if spans is not None:
        seconds = {
            code: sum((b - a).total_seconds() for a, b in found) for code, found in spans.items()
        }
        shares = {code: value / duration for code, value in seconds.items()}
        # Substituted values are samples the source made up: not data, though present.
        missing += seconds["substituted"]
        labels = {
            "bad": t("Bad quality"),
            "substituted": t("Substituted"),
            "uncertain": t("Uncertain"),
        }
        gaps += [
            (
                (b - a).total_seconds(),
                event(a, b, labels[code], seconds=(b - a).total_seconds(), quality=code),
            )
            for code, found in spans.items()
            for a, b in found
        ]
    coverage = max(0.0, 1.0 - missing / duration)
    sample_intervals = np.diff(inside.asi8) / 1e9 if len(inside) > 1 else np.array([])
    warn = 1.0 - warn_coverage
    bad = max(1.0 - min_coverage, warn * 1.001)
    score = score_band(1.0 - coverage, warn, bad, 1.0)
    if shares:
        # Uncertain values are data, but doubtful: a warning at most, never unusable.
        score = max(score, min(score_band(shares["uncertain"], warn, bad, 1.0), 74.0))
    quality_metrics = {f"quality_{code}": round(share, 4) for code, share in shares.items()}
    return Finding(
        score=score,
        metrics={
            "coverage": round(coverage, 4),
            "samples": int(len(inside)),
            "gap_count": gap_count,
            "largest_gap_minutes": round(float(intervals.max()) / 60.0, 1),
            "median_interval_seconds": (
                round(float(np.median(sample_intervals)), 2) if sample_intervals.size else None
            ),
            "apt": coverage >= min_coverage,
            **quality_metrics,
        },
        events=worst_events(gaps),
    )
