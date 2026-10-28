"""Range: values outside the signal's engineering limits."""

from __future__ import annotations

import numpy as np
from plantcraft_sdk.methods import Finding, NotEnoughData, method, param

from linkcraft.i18n import t
from linkcraft.methods.signal._common import (
    event,
    is_text,
    limits,
    num,
    numbers,
    runs,
    worst_events,
)


def _describe(metrics: dict) -> str:
    if metrics.get("low") is None and metrics.get("high") is None:
        return t("No engineering limits are set for this signal.")
    if not metrics.get("outside_count"):
        return t(
            "All values inside {low} to {high} (min {minimum}, max {maximum}).",
            low=num(metrics.get("low")),
            high=num(metrics.get("high")),
            minimum=num(metrics.get("minimum")),
            maximum=num(metrics.get("maximum")),
        )
    return t(
        "{share} of the values outside {low} to {high} (min {minimum}, max {maximum}).",
        share=f"{100 * float(metrics.get('outside_fraction') or 0):.1f}%",
        low=num(metrics.get("low")),
        high=num(metrics.get("high")),
        minimum=num(metrics.get("minimum")),
        maximum=num(metrics.get("maximum")),
    )


@method(
    "sq_range",
    name="Out of range",
    application="linkcraft",
    version="1.0.0",
    maturity="engineering_heuristic",
    min_samples=0,
    formula=(
        "outside = samples below low - margin * (high - low) or above high + margin * "
        "(high - low); the limits come from PlantCraft or the signal's settings here."
    ),
    limitations=[
        "Needs engineering limits: without them the check does not judge the signal.",
        "A sensor stuck exactly at a limit is inside the range; the frozen value check finds it.",
    ],
    describe=_describe,
)
def out_of_range(
    dataset,
    *,
    margin: float = param(
        0.02, ge=0, le=1, help="Tolerance beyond each limit, as a share of the range."
    ),
    bad_fraction: float = param(
        0.05, gt=0, le=1, help="Share of values outside the range that makes the data unusable."
    ),
):
    """Values a healthy instrument cannot give: below its low or above its high limit."""

    if is_text(dataset):
        return Finding(score=0, status="not_applicable", message=t("Text signals have no range."))
    low, high = limits(dataset)
    if low is None and high is None:
        return Finding(
            score=0,
            status="not_applicable",
            metrics={"low": None, "high": None},
            message=t("No engineering limits are set for this signal."),
        )
    values = numbers(dataset)
    if values.empty:
        raise NotEnoughData(t("No numeric samples in the window."))
    data = values.to_numpy()
    width = (high - low) if low is not None and high is not None else max(1.0, float(np.ptp(data)))
    below = data < (low - margin * width) if low is not None else np.zeros(data.size, bool)
    above = data > (high + margin * width) if high is not None else np.zeros(data.size, bool)
    outside = below | above
    fraction = float(outside.sum()) / data.size
    found = []
    for first, last in runs(outside):
        stretch = data[first : last + 1]
        extreme = float(stretch.min() if below[first] else stretch.max())
        found.append(
            (
                float(last - first + 1),
                event(values.index[first], values.index[last], t("Out of range"), value=extreme),
            )
        )
    if not found:
        score = 0.0
    elif fraction >= bad_fraction:
        score = min(100.0, 75.0 + 25.0 * (fraction - bad_fraction) / max(1e-9, 1 - bad_fraction))
    else:
        score = 25.0 + 50.0 * fraction / bad_fraction
    return Finding(
        score=score,
        metrics={
            "low": low,
            "high": high,
            "minimum": round(float(data.min()), 6),
            "maximum": round(float(data.max()), 6),
            "outside_count": int(outside.sum()),
            "outside_fraction": round(fraction, 5),
            "apt": fraction < bad_fraction,
        },
        events=worst_events(found),
    )
