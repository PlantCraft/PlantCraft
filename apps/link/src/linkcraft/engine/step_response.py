"""How the loop answered its own setpoint steps, found in the recorded window (A10 of the 0.6 list).

Every setpoint change in the window (a jump, or a short ramp of a few samples) that stands clear
of the PV's noise and is held long enough to watch is one step. For each, with the PV scaled so
the old setpoint is 0 and the new one is 1 (``y = (pv - sp_before) / (sp_after - sp_before)``):

- **overshoot**: how far the PV went past the new setpoint, ``max(0, max(y) - 1)``, in percent;
- **rise time**: from the PV first reaching 10 % of the step to 90 % of it;
- **settling time**: from the step until the PV stays inside the band around the new setpoint
  (5 % of the step, wider when the PV's noise is), measured only when it stays there to the end
  of the hold;
- **IAE**: the integral of ``|sp - pv|`` over the hold, in PV units times seconds, and divided by
  the step's size, in seconds, so steps of different sizes compare.

These are the classic step-response figures (Åström and Murray, *Feedback Systems*, 2008,
section 5.3; Seborg et al., *Process Dynamics and Control*, chapter 11). Steps taken while the
mode signal says manual are left out: the controller was not answering them. Read only: the
figures describe the loop's own history, no test is run on the plant.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

# A ramp of at most this many samples is one step.
RAMP_SAMPLES = 3
# The step must be this many times the PV's sample-to-sample noise.
MIN_STEP_NOISE = 5.0
# A step must be held this many samples to be watched.
MIN_HOLD = 10
# Settling band: this share of the step, or three noise widths when that is wider.
SETTLE_BAND = 0.05
# Samples before the step whose PV gives the starting value shown.
BEFORE = 10
# The figures of at most this many steps (the latest) are returned.
MAX_STEPS = 50
MANUAL_LABELS = frozenset({"manual", "man", "m"})


def _noise(pv: np.ndarray) -> float:
    """The PV's noise from its sample-to-sample changes (median absolute deviation)."""

    steps = np.diff(pv[np.isfinite(pv)])
    if steps.size < 2:
        return 0.0
    return float(1.4826 * np.median(np.abs(steps - np.median(steps))) / math.sqrt(2.0))


def _changes(sp: np.ndarray, tolerance: float) -> list[tuple[int, int]]:
    """``(first, last)`` sample indices of each setpoint change, a short ramp merged into one."""

    moved = np.flatnonzero(np.abs(np.diff(sp)) > tolerance) + 1
    found: list[tuple[int, int]] = []
    for index in moved.tolist():
        if found and index - found[-1][1] <= 1 and index - found[-1][0] < RAMP_SAMPLES:
            found[-1] = (found[-1][0], index)
        else:
            found.append((index, index))
    return found


def _first(mask: np.ndarray) -> int | None:
    hits = np.flatnonzero(mask)
    return int(hits[0]) if hits.size else None


def _one_step(
    pv: np.ndarray, sp: np.ndarray, start: int, ramp_end: int, end: int, dt: float, noise: float
) -> dict[str, Any] | None:
    before, after = float(sp[start - 1]), float(sp[ramp_end])
    size = after - before
    hold_pv = pv[start:end]
    if hold_pv.size < MIN_HOLD or np.isfinite(hold_pv).sum() < MIN_HOLD:
        return None
    y = (hold_pv - before) / size
    finite = np.isfinite(y)
    peak = float(np.nanmax(y))
    overshoot = max(0.0, peak - 1.0) * 100.0
    ten, ninety = _first(finite & (y >= 0.1)), _first(finite & (y >= 0.9))
    rise = (ninety - ten) * dt if ten is not None and ninety is not None else None
    band = max(SETTLE_BAND, 3.0 * noise / abs(size))
    outside = np.flatnonzero(finite & (np.abs(y - 1.0) > band))
    last_out = int(outside[-1]) if outside.size else -1
    # Settled only when the PV stays inside the band for the last samples of the hold.
    settled = last_out < y.size - max(3, MIN_HOLD // 2)
    settling = (last_out + 1) * dt if settled else None
    error = np.abs(sp[start:end] - hold_pv)
    iae = float(np.nansum(error) * dt)
    return {
        "index": start,
        "sp_before": before,
        "sp_after": after,
        "size": size,
        "pv_before": float(np.nanmean(pv[max(0, start - BEFORE) : start])),
        "hold_seconds": hold_pv.size * dt,
        "overshoot_pct": round(overshoot, 2),
        "rise_seconds": round(rise, 1) if rise is not None else None,
        "settling_seconds": round(settling, 1) if settling is not None else None,
        "reached": ninety is not None,
        "settled": settled,
        "iae": round(iae, 4),
        "iae_seconds": round(iae / abs(size), 1),
    }


def _median(values: list[float | None]) -> float | None:
    kept = [value for value in values if value is not None]
    return round(float(np.median(kept)), 2) if kept else None


def step_responses(frame: pd.DataFrame, sample_seconds: float) -> dict[str, Any]:
    """The setpoint steps found in ``frame`` (``sp`` and ``pv``, and ``mode`` when there is one,
    on a regular grid of ``sample_seconds``) with each one's figures and their medians; ``reason``
    instead when there is nothing to measure."""

    if frame is None or frame.empty or not {"sp", "pv"} <= set(frame.columns):
        return {"available": False, "reason": "The window has no SP and PV to find steps in."}
    sp = pd.to_numeric(frame["sp"], errors="coerce").ffill().to_numpy(dtype=float)
    pv = pd.to_numeric(frame["pv"], errors="coerce").to_numpy(dtype=float)
    dt = float(sample_seconds)
    if np.isfinite(sp).sum() < MIN_HOLD or np.isfinite(pv).sum() < MIN_HOLD or dt <= 0:
        return {"available": False, "reason": "Too few samples with both SP and PV."}
    manual = np.zeros(len(sp), dtype=bool)
    if "mode" in frame.columns:
        manual = frame["mode"].astype(str).str.strip().str.lower().isin(MANUAL_LABELS).to_numpy()
    noise = _noise(pv)
    scale = float(np.nanmax(np.abs(sp))) if np.isfinite(sp).any() else 1.0
    tolerance = max(1e-9 * max(scale, 1.0), 0.0)
    changes = [item for item in _changes(sp, tolerance) if item[0] > 0]
    steps: list[dict[str, Any]] = []
    skipped = {"small": 0, "short": 0, "manual": 0}
    for number, (start, ramp_end) in enumerate(changes):
        end = changes[number + 1][0] if number + 1 < len(changes) else len(sp)
        size = float(sp[ramp_end] - sp[start - 1])
        if not math.isfinite(size) or abs(size) < max(MIN_STEP_NOISE * noise, tolerance * 10):
            skipped["small"] += 1
            continue
        if manual[start:end].any():
            skipped["manual"] += 1
            continue
        found = _one_step(pv, sp, start, ramp_end, end, dt, noise)
        if found is None:
            skipped["short"] += 1
            continue
        steps.append(found)
    if not steps:
        return {
            "available": False,
            "reason": "No setpoint step in the window stands clear of the noise and is held "
            "long enough to measure.",
            "skipped": skipped,
        }
    steps = steps[-MAX_STEPS:]
    # When the step began: the frame's ``timestamp`` (naive UTC) when it has one, else its index.
    times = pd.to_datetime(
        frame["timestamp"] if "timestamp" in frame.columns else frame.index,
        utc=True,
        errors="coerce",
    )
    for step in steps:
        at = times[step.pop("index")]
        step["at"] = at.isoformat().replace("+00:00", "Z") if not pd.isna(at) else None
    return {
        "available": True,
        "steps": steps,
        "skipped": skipped,
        "summary": {
            "steps": len(steps),
            "overshoot_pct": _median([step["overshoot_pct"] for step in steps]),
            "rise_seconds": _median([step["rise_seconds"] for step in steps]),
            "settling_seconds": _median([step["settling_seconds"] for step in steps]),
            "iae_seconds": _median([step["iae_seconds"] for step in steps]),
            "settled_pct": round(100.0 * sum(step["settled"] for step in steps) / len(steps), 1),
        },
    }
