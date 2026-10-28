"""Spikes: isolated samples far from their neighbours (Hampel filter)."""

from __future__ import annotations

import numpy as np
from plantcraft_sdk.methods import Finding, NotEnoughData, ScientificReference, method, param

from linkcraft.i18n import t
from linkcraft.methods.signal._common import (
    event,
    is_text,
    num,
    numbers,
    robust_span,
    runs,
    worst_events,
)

MAD_TO_SIGMA = 1.4826


def noise_sigma(values: np.ndarray) -> float:
    """Sample-to-sample noise from the first differences that move (robust: median absolute
    deviation)."""

    if values.size < 3:
        return 0.0
    diffs = np.diff(values)
    # Repeated samples (a frozen stretch, a value recorded twice) say nothing about the noise.
    diffs = diffs[np.abs(diffs) > 1e-12 * max(1.0, float(np.max(np.abs(values))))]
    if diffs.size < 3:
        return 0.0
    return float(MAD_TO_SIGMA * np.median(np.abs(diffs - np.median(diffs))) / np.sqrt(2.0))


def _describe(metrics: dict) -> str:
    if not metrics.get("spike_count"):
        return t("No spikes found.")
    return t(
        "{count} spikes ({share} of the samples), the largest {size} away from its neighbours.",
        count=metrics.get("spike_count"),
        share=f"{100 * float(metrics.get('spike_fraction') or 0):.2f}%",
        size=num(metrics.get("largest_spike")),
    )


@method(
    "sq_spikes",
    name="Spikes",
    application="linkcraft",
    version="1.0.0",
    maturity="literature_based",
    min_samples=0,
    references=[
        ScientificReference(
            title="The influence curve and its role in robust estimation",
            authors=["Hampel, F. R."],
            year=1974,
            venue="Journal of the American Statistical Association 69(346), 383-393",
            doi="10.1080/01621459.1974.10482962",
        ),
        ScientificReference(
            title="Outliers in process modeling and identification",
            authors=["Pearson, R. K."],
            year=2002,
            venue="IEEE Transactions on Control Systems Technology 10(1), 55-63",
            doi="10.1109/87.974338",
        ),
    ],
    formula=(
        "Hampel filter: a sample is a spike when |x - median| > n_sigma * max(1.4826 MAD, "
        "noise) over a centred window of 2 half_window + 1 samples, and the jump exceeds "
        "min_jump of the signal's 1-99 percentile range."
    ),
    limitations=[
        "A disturbance shorter than half the window looks like a spike.",
        "Spikes longer than half the window are taken for a level change.",
    ],
    describe=_describe,
)
def spikes(
    dataset,
    *,
    half_window: int = param(
        5, ge=2, le=50, help="Neighbours on each side a sample is compared with."
    ),
    n_sigma: float = param(6.0, gt=0, help="How many standard deviations away a spike is."),
    min_jump: float = param(
        0.02, ge=0, le=1, help="Smallest spike as a share of the signal's normal range."
    ),
    bad_fraction: float = param(
        0.01, gt=0, le=1, help="Share of spiky samples that makes the data unusable."
    ),
):
    """Samples that jump away from their neighbours and come straight back."""

    if is_text(dataset):
        return Finding(
            score=0, status="not_applicable", message=t("Text signals are not checked for spikes.")
        )
    values = numbers(dataset)
    if len(values) < 2 * half_window + 1:
        raise NotEnoughData(t("Too few numeric samples to compare each one with its neighbours."))
    width = 2 * half_window + 1
    median = values.rolling(width, center=True, min_periods=half_window + 1).median()
    deviation = (values - median).abs()
    mad = deviation.rolling(width, center=True, min_periods=half_window + 1).median()
    data = values.to_numpy()
    steps = np.abs(np.diff(data))
    moving = steps[steps > 1e-12 * max(1.0, float(np.nanmax(np.abs(data))))]
    # Never smaller than the noise, nor than the signal's own step (quantised data moves in steps).
    quantum = float(np.percentile(moving, 5)) if moving.size else 0.0
    floor = max(noise_sigma(data), quantum, 1e-9 * max(1.0, float(np.nanmax(np.abs(data)))))
    scale = np.maximum(MAD_TO_SIGMA * mad.to_numpy(), floor)
    jump = deviation.to_numpy()
    spiky = (jump > n_sigma * scale) & (jump > min_jump * robust_span(values))
    spiky &= np.isfinite(jump)
    found: list[tuple[float, dict]] = []
    times = values.index
    kept = np.zeros(spiky.size, dtype=bool)
    for first, last in runs(spiky):
        # A spike leaves and comes back: its peak stands out from the samples on both sides,
        # in the same direction. A step into a frozen stretch or a level change does not.
        if first == 0 or last == data.size - 1:
            continue
        stretch = data[first : last + 1]
        peak = stretch[np.argmax(np.abs(stretch - (data[first - 1] + data[last + 1]) / 2))]
        before, after = peak - data[first - 1], peak - data[last + 1]
        needed = 0.5 * n_sigma * float(np.min(scale[first : last + 1]))
        if np.sign(before) != np.sign(after) or min(abs(before), abs(after)) <= needed:
            continue
        kept[first : last + 1] = True
        size = float(np.max(jump[first : last + 1]))
        found.append(
            (
                size,
                event(
                    times[first],
                    times[last],
                    t("Spike"),
                    size=round(size, 6),
                    samples=last - first + 1,
                ),
            )
        )
    fraction = float(kept.sum()) / len(values)
    if not found:
        score = 0.0
    elif fraction >= bad_fraction:
        score = min(100.0, 75.0 + 25.0 * (fraction - bad_fraction) / bad_fraction)
    else:
        score = 25.0 + 50.0 * fraction / bad_fraction
    return Finding(
        score=score,
        metrics={
            "spike_count": len(found),
            "spike_fraction": round(fraction, 5),
            "largest_spike": round(max((size for size, _ in found), default=0.0), 6),
            "apt": fraction < bad_fraction,
        },
        events=worst_events(found),
    )
