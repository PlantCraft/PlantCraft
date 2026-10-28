"""Freshness: whether the signal is still updating at the end of the window."""

from __future__ import annotations

from plantcraft_sdk.methods import Finding, NotEnoughData, method, param

from linkcraft.i18n import t
from linkcraft.methods.signal._common import event, samples, score_band, window


@method(
    "sq_freshness",
    name="Freshness",
    application="linkcraft",
    version="1.0.0",
    maturity="engineering_heuristic",
    min_samples=0,
    formula="age = window end - time of the last sample.",
    limitations=[
        "A signal recorded only on change can be steady and old at once; raise the limits "
        "for such signals."
    ],
    describe="Last sample {age_minutes:.1} min before the end of the window.",
)
def freshness(
    dataset,
    *,
    warn_age_minutes: float = param(30.0, gt=0, help="Age of the last sample that is a warning."),
    bad_age_minutes: float = param(
        120.0, gt=0, help="Age of the last sample that marks the signal as stale."
    ),
):
    """Time since the last sample: a stale signal stopped updating."""

    span = window(dataset)
    if span is None:
        raise NotEnoughData(t("The window is empty."))
    start, end = span
    values = samples(dataset)
    values = values[(values.index >= start) & (values.index <= end)]
    last = values.index.max() if len(values) else start
    age = max(0.0, (end - last).total_seconds() / 60.0)
    stale = age >= bad_age_minutes
    events = (
        [event(last, end, t("No new samples"), minutes=round(age, 1))]
        if age >= warn_age_minutes
        else []
    )
    return Finding(
        score=score_band(age, warn_age_minutes, max(bad_age_minutes, warn_age_minutes * 1.001)),
        metrics={
            "age_minutes": round(age, 1),
            "last_sample": last.isoformat() if len(values) else None,
            "apt": not stale,
        },
        events=events,
    )
