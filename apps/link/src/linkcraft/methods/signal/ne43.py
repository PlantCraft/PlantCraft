"""NAMUR NE 43: values a 4-20 mA transmitter only gives when it saturates or signals a fault.

NE 43 (public recommendation) keeps 3.8 to 20.5 mA for measurement and 3.6 mA or less, 21 mA or
more, for a failure. On the signal's range (low = 4 mA, high = 20 mA) that is -1.25% to 103.125%
of the span for measurement, and -2.5% or less, 106.25% or more, for a failure: a value there is
the transmitter saying it is broken, not the process.
"""

from __future__ import annotations

from plantcraft_sdk.methods import Finding, NotEnoughData, method, param

from linkcraft.i18n import t
from linkcraft.methods.signal._common import (
    event,
    is_text,
    limits,
    numbers,
    runs,
    score_band,
    worst_events,
)

# Share of the span, from the 4-20 mA levels of NE 43 (16 mA span).
MEASURE_LOW, MEASURE_HIGH = -0.2 / 16, 0.5 / 16
FAILURE_LOW, FAILURE_HIGH = -0.4 / 16, 1.0 / 16


@method(
    "sq_ne43",
    name="Transmitter fault levels (NE 43)",
    application="linkcraft",
    version="1.0.0",
    maturity="engineering_heuristic",
    min_samples=0,
    formula=(
        "On span = high - low: failure = value <= low - 2.5% span or >= high + 6.25% span "
        "(3.6 and 21 mA); saturated = beyond low - 1.25% or high + 3.125% (3.8 and 20.5 mA) "
        "but not a failure. Bad when failure samples pass bad_fraction, warning on any "
        "failure or saturation."
    ),
    assumptions=[
        "The signal comes from a 4-20 mA transmitter whose range is the signal's low and high "
        "limits (NAMUR NE 43)."
    ],
    limitations=[
        "Needs the signal's engineering limits; without them the check does not apply.",
        "A digital (fieldbus) or calculated signal has no current levels; switch the check off "
        "for it.",
    ],
    describe="{failure_fraction:%} of the values at fault levels, {saturated_fraction:%} "
    "saturated beyond the measuring range.",
)
def ne43(
    dataset,
    *,
    bad_fraction: float = param(
        0.01, gt=0, le=1, help="Share of values at fault levels that makes the data unusable."
    ),
):
    """Values at the levels a 4-20 mA transmitter uses to say it failed (NAMUR NE 43)."""

    if is_text(dataset):
        return Finding(score=0, status="not_applicable", message=t("Text signals have no range."))
    low, high = limits(dataset)
    if low is None or high is None:
        return Finding(
            score=0,
            status="not_applicable",
            message=t("No engineering limits are set for this signal."),
        )
    values = numbers(dataset)
    if values.empty:
        raise NotEnoughData(t("No numeric samples in the window."))
    span = high - low
    array = values.to_numpy()
    failure = (array <= low + FAILURE_LOW * span) | (array >= high + FAILURE_HIGH * span)
    saturated = ~failure & (
        (array < low + MEASURE_LOW * span) | (array > high + MEASURE_HIGH * span)
    )
    failure_fraction = float(failure.mean())
    saturated_fraction = float(saturated.mean())
    score = score_band(failure_fraction, bad_fraction * 1e-3, bad_fraction, 1.0)
    if saturated_fraction > 0:
        score = max(score, 25.0)
    events = [
        (float(b - a + 1), event(values.index[a], values.index[b], label))
        for mask, label in ((failure, t("Fault level")), (saturated, t("Saturated")))
        for a, b in runs(mask)
    ]
    return Finding(
        score=score,
        metrics={
            "failure_fraction": round(failure_fraction, 4),
            "saturated_fraction": round(saturated_fraction, 4),
            "failure_count": int(failure.sum()),
            "saturated_count": int(saturated.sum()),
            "apt": failure_fraction < bad_fraction,
        },
        events=worst_events(events),
    )
