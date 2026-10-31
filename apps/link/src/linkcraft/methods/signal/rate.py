"""Rate of change: steps faster than the process (or the instrument) can move."""

from __future__ import annotations

import numpy as np
from plantcraft_sdk.methods import Finding, NotEnoughData, method, param

from linkcraft.i18n import t
from linkcraft.methods.signal._common import (
    event,
    is_text,
    limits,
    numbers,
    score_band,
    worst_events,
)


@method(
    "sq_rate",
    name="Rate of change",
    application="linkcraft",
    version="1.0.0",
    maturity="engineering_heuristic",
    min_samples=0,
    formula=(
        "rate = |v[i] - v[j]| / (t[i] - t[j]) in units per minute, j the last sample at least "
        "over_seconds before i; the limit is "
        "max_rate_per_minute, else max_span_per_minute x (high - low). Share = intervals "
        "above the limit / intervals: warning from warn_fraction, bad from bad_fraction."
    ),
    assumptions=[
        "A real process moves no faster than its limit; a faster step is the instrument, "
        "the wiring or the data, not the process."
    ],
    limitations=[
        "Needs a limit: max_rate_per_minute, or the signal's engineering limits to scale "
        "max_span_per_minute; without either the check does not apply.",
        "A sparse signal (recorded on change) shows a slow drift as one step; its rate is "
        "measured over the interval between samples.",
    ],
    describe="{fast_fraction:%} of the steps faster than {limit_per_minute:.4} per minute "
    "(fastest {max_rate_per_minute_seen:.4}).",
)
def rate(
    dataset,
    *,
    max_rate_per_minute: float = param(
        0.0,
        ge=0,
        help="Fastest change the process can make, in the signal's units per minute (0: use the span).",
    ),
    max_span_per_minute: float = param(
        0.5,
        gt=0,
        help="Without an absolute limit: fastest change as a share of the range per minute.",
    ),
    over_seconds: float = param(
        60.0, gt=0, help="Shortest time a change is measured over (noise is faster)."
    ),
    warn_fraction: float = param(0.001, ge=0, le=1, help="Share of fast steps that is a warning."),
    bad_fraction: float = param(
        0.01, gt=0, le=1, help="Share of fast steps that makes the data unusable."
    ),
):
    """Steps faster than the process can move: a jumping instrument or bad data."""

    if is_text(dataset):
        return Finding(score=0, status="not_applicable", message=t("Text signals have no rate."))
    low, high = limits(dataset)
    if max_rate_per_minute > 0:
        limit = max_rate_per_minute
    elif low is not None and high is not None:
        limit = max_span_per_minute * (high - low)
    else:
        return Finding(
            score=0,
            status="not_applicable",
            message=t("Set a maximum rate or the signal's engineering limits to check its rate."),
        )
    values = numbers(dataset)
    if len(values) < 3:
        raise NotEnoughData(t("Too few samples to measure a rate."))
    # The change over at least ``over_seconds`` (or to the previous sample when the samples are
    # further apart): fast transmitter noise over a few seconds is not the process moving.
    stamps = values.index.asi8
    array = values.to_numpy()
    before = np.searchsorted(stamps, stamps - int(over_seconds * 1e9), side="right") - 1
    valid = before >= 0
    ends = np.flatnonzero(valid)
    starts = before[valid]
    minutes = (stamps[ends] - stamps[starts]) / 60e9
    steps = np.abs(array[ends] - array[starts])
    rates = np.divide(steps, minutes, out=np.full_like(steps, np.inf), where=minutes > 0)
    if not rates.size:
        raise NotEnoughData(t("Too few samples to measure a rate."))
    fast = rates > limit
    fraction = float(fast.mean())
    warn = max(warn_fraction, 1e-12)
    score = score_band(fraction, warn, max(bad_fraction, warn * 1.001), 1.0) if fast.any() else 0.0
    events = [
        (
            float(rates[i]),
            event(
                values.index[i],
                values.index[i + 1],
                t("Fast step"),
                rate_per_minute=float(rates[i]),
            ),
        )
        for i in np.flatnonzero(fast)
    ]
    finite = rates[np.isfinite(rates)]
    return Finding(
        score=score,
        metrics={
            "fast_fraction": round(fraction, 5),
            "fast_count": int(fast.sum()),
            "limit_per_minute": float(limit),
            "max_rate_per_minute_seen": float(finite.max()) if finite.size else None,
            "apt": fraction < bad_fraction,
        },
        events=worst_events(events),
    )
