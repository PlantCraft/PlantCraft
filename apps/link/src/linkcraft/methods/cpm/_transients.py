"""The PV's travel to a new setpoint, which methods that judge regulation leave out.

When the setpoint steps, the PV needs some time to get there: that error is the loop answering
the operator, not a failure to hold the setpoint. A loop whose setpoint moves every half hour
would otherwise read as a bad loop on the PV-SP error, and the steps themselves would read as an
oscillation. So each setpoint change opens a transient that lasts until the PV first reaches the
new setpoint (it crosses it or comes within the band), at most ``max_seconds``. A loop too slow to
get there in that time is judged from then on: a sluggish answer still counts, only the
travel itself is left out.
"""

from __future__ import annotations

import numpy as np

# A setpoint move smaller than this share of the loop's scale is a ramp or a rounding, not a step.
MIN_STEP_FRACTION = 0.002


def setpoint_transients(
    pv: np.ndarray,
    sp: np.ndarray,
    *,
    band: float,
    max_samples: int,
    scale: float | None = None,
) -> np.ndarray:
    """A mask of the samples where the PV is still travelling to a setpoint that just changed."""

    n = min(pv.size, sp.size)
    mask = np.zeros(n, dtype=bool)
    if n < 2 or max_samples <= 0:
        return mask
    reference = scale if scale and np.isfinite(scale) and scale > 0 else None
    if reference is None:
        finite = np.abs(sp[np.isfinite(sp)])
        reference = float(np.median(finite)) if finite.size else 0.0
    threshold = max(MIN_STEP_FRACTION * reference, 1e-9)
    steps = np.flatnonzero(np.abs(np.diff(sp[:n])) > threshold) + 1
    error = pv[:n] - sp[:n]
    for start in steps:
        stop = min(n, start + max_samples)
        first = error[start]
        if not np.isfinite(first) or abs(first) <= band:
            continue
        window = error[start:stop]
        arrived = np.flatnonzero((np.abs(window) <= band) | (np.sign(window) != np.sign(first)))
        end = start + int(arrived[0]) if arrived.size else stop
        mask[start:end] = True
    return mask
