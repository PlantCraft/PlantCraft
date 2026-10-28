"""Frozen value: the signal repeats the same value for longer than a process would."""

from __future__ import annotations

import numpy as np
from plantcraft_sdk.methods import Finding, NotEnoughData, method, param

from linkcraft.i18n import t
from linkcraft.methods.signal._common import (
    event,
    is_text,
    num,
    numbers,
    runs,
    window,
    worst_events,
)
from linkcraft.methods.signal._common import spread as robust_spread


def _describe(metrics: dict) -> str:
    if not metrics.get("frozen_count"):
        return t(
            "No frozen stretches (longest repeat {minutes} min).",
            minutes=num(metrics.get("longest_minutes")),
        )
    return t(
        "Frozen for {fraction} of the window in {count} stretches, the longest {minutes} min "
        "at {value}.",
        fraction=f"{100 * float(metrics.get('frozen_fraction') or 0):.0f}%",
        count=metrics.get("frozen_count"),
        minutes=num(metrics.get("longest_minutes")),
        value=num(metrics.get("frozen_value")),
    )


def coarse(values: np.ndarray, limit: float = 0.25) -> bool:
    """True when the recorded steps are large against the spread (quantised data)."""

    spread = robust_spread(values)
    steps = np.abs(np.diff(values))
    moving = steps[steps > 1e-12 * max(1.0, float(np.max(np.abs(values))))]
    if spread <= 0 or moving.size < 5:
        return False
    return float(np.percentile(moving, 5)) / spread >= limit


@method(
    "sq_frozen",
    name="Frozen value",
    application="linkcraft",
    version="1.0.0",
    maturity="engineering_heuristic",
    min_samples=0,
    formula=(
        "A stretch is frozen when consecutive samples differ by at most the tolerance for at "
        "least min_minutes; frozen fraction = frozen time / window."
    ),
    assumptions=[
        "The source keeps sending samples while the value does not change (a historian that "
        "records only changes shows a frozen sensor as a gap instead)."
    ],
    limitations=[
        "Setpoints, modes and other signals that are constant by design look frozen: the "
        "check is off for signals with the setpoint or mode role, and can be switched off per "
        "signal.",
        "On coarsely quantised data (steps of a quarter of the spread or more) it does not judge.",
    ],
    describe=_describe,
)
def frozen(
    dataset,
    *,
    min_minutes: float = param(
        60.0, gt=0, help="Shortest repeat of one value that counts as frozen."
    ),
    tolerance: float = param(
        0.0, ge=0, help="Largest change that still counts as the same value (signal units)."
    ),
    bad_fraction: float = param(
        0.5, gt=0, le=1, help="Frozen share of the window that makes the data unusable."
    ),
):
    """Stretches where the value stops changing (a stuck sensor or a frozen transmitter)."""

    if is_text(dataset):
        return Finding(
            score=0,
            status="not_applicable",
            message=t("Text signals are not checked for frozen values."),
        )
    span = window(dataset)
    values = numbers(dataset)
    if span is None or len(values) < 3:
        raise NotEnoughData(t("Fewer than 3 numeric samples in the window."))
    start, end = span
    if coarse(values.to_numpy()):
        return Finding(
            score=0,
            status="not_applicable",
            message=t(
                "The signal moves in steps too coarse to tell a frozen sensor from a steady "
                "process; see the resolution check."
            ),
        )
    duration = (end - start).total_seconds()
    numbers_ = values.to_numpy()
    scale = max(float(np.nanmax(np.abs(numbers_))), 1.0)
    same = np.abs(np.diff(numbers_)) <= max(tolerance, 1e-12 * scale)
    times = values.index
    found: list[tuple[float, dict]] = []
    frozen_seconds = 0.0
    longest = 0.0
    frozen_value = None
    longest_frozen = 0.0
    for first, last in runs(same):
        # Samples first..last+1 hold one value; it lasts until the next sample (or the end).
        begins = times[first]
        stops = times[last + 2] if last + 2 < len(times) else end
        seconds = (stops - begins).total_seconds()
        if seconds > longest:
            longest = seconds
        if seconds >= min_minutes * 60.0:
            frozen_seconds += seconds
            value = float(numbers_[first])
            if seconds > longest_frozen:
                longest_frozen, frozen_value = seconds, value
            found.append(
                (
                    seconds,
                    event(begins, stops, t("Frozen"), value=value, minutes=round(seconds / 60, 1)),
                )
            )
    fraction = min(1.0, frozen_seconds / duration) if duration > 0 else 0.0
    if not found:
        score = 0.0
    elif fraction >= bad_fraction:
        score = min(100.0, 75.0 + 25.0 * (fraction - bad_fraction) / max(1e-9, 1 - bad_fraction))
    else:
        score = 25.0 + 50.0 * fraction / bad_fraction
    return Finding(
        score=score,
        metrics={
            "frozen_fraction": round(fraction, 4),
            "frozen_count": len(found),
            "longest_minutes": round(longest / 60.0, 1),
            "frozen_value": frozen_value,
            "apt": fraction < bad_fraction,
        },
        events=worst_events(found),
    )
