"""A signal against the laboratory (A5, 2026-10-31): how well an analyzer or a soft sensor
agrees with the lab results of the same quantity (the signal's reference), and its value
corrected by them.

Each result counts at its sampling time and only from its approval (the Historian keeps both,
``PlantCraftClient.lab_samples``): ``plantcraft_sdk.estimators.fuse_lab``. A rejected result
is left out, one not approved yet is shown but corrects nothing. The health is
``sensor_health`` of the signal at the sampling times against the results, 0 to 100.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from plantcraft_sdk.estimators import fuse_lab, sensor_health

from linkcraft.data.samples import naive_utc, thin

PLOT_POINTS = 2000


def _stamp(value: Any) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    try:
        return naive_utc(value)
    except (TypeError, ValueError):
        return None


def _points(values: pd.Series) -> dict[str, list[Any]]:
    values = thin(values[np.isfinite(values.to_numpy(dtype=float))], PLOT_POINTS)
    return {
        "t": [stamp.tz_localize("UTC").isoformat() for stamp in values.index],
        "v": [round(float(item), 6) for item in values],
    }


MAX_RESULTS = 500


def results_from_series(values: pd.Series) -> list[dict[str, Any]]:
    """A reference read as a plain series (no laboratory times): each value known when taken,
    at most ``MAX_RESULTS`` of them, evenly spread (a continuous reference is not a lab)."""

    found = pd.to_numeric(values, errors="coerce").dropna()
    if len(found) > MAX_RESULTS:
        found = found.iloc[:: -(-len(found) // MAX_RESULTS)]
    return [
        {"sampled_at": stamp, "value": float(value), "status": "approved", "approved_at": stamp}
        for stamp, value in found.items()
    ]


def against_lab(online: pd.Series, results: list[dict[str, Any]]) -> dict[str, Any]:
    """``online`` (naive UTC index) against ``results`` (``lab_samples`` rows)."""

    online = pd.to_numeric(online, errors="coerce").sort_index()
    online = online[~online.index.duplicated(keep="last")]
    index = pd.DatetimeIndex(online.index)
    values = online.to_numpy(dtype=float)
    empty = {"samples": [], "used": 0, "health": None, "health_corrected": None, "bias": None}
    if len(index) < 2:
        return {**empty, "bias_series": {"t": [], "v": []}, "corrected": {"t": [], "v": []}}
    lab = np.full(len(index), np.nan)
    arrival = np.full(len(index), -1)
    rows = []
    for item in results:
        sampled = _stamp(item.get("sampled_at"))
        value = item.get("value")
        if sampled is None or not isinstance(value, int | float) or not np.isfinite(value):
            continue
        if sampled < index[0] or sampled > index[-1]:
            continue
        status = str(item.get("status") or "approved")
        step = int(index.searchsorted(sampled))
        approved = _stamp(item.get("approved_at"))
        rows.append((sampled, float(value), status, approved, step))
        if status == "rejected":
            continue
        lab[step] = float(value)
        if status == "approved":
            known = approved if approved is not None else sampled
            arrival[step] = max(step, int(index.searchsorted(known)))
    fused = fuse_lab(values, lab, arrival=arrival)
    samples = []
    for sampled, value, status, approved, step in rows:
        samples.append(
            {
                "t": sampled.tz_localize("UTC").isoformat(),
                "lab": value,
                "online": float(values[step]) if np.isfinite(values[step]) else None,
                "corrected": float(fused.estimate[step])
                if np.isfinite(fused.estimate[step])
                else None,
                "status": status,
                "approved_at": approved.tz_localize("UTC").isoformat() if approved else None,
            }
        )
    counted = [item for item in samples if item["status"] != "rejected"]
    actual = np.array([item["lab"] for item in counted], dtype=float)

    def health(key: str) -> float | None:
        found = np.array([np.nan if item[key] is None else item[key] for item in counted])
        score = sensor_health(actual, found) if len(counted) else float("nan")
        return None if not np.isfinite(score) else score

    last_bias = fused.bias[-1] if fused.used else None
    return {
        "samples": samples,
        "used": fused.used,
        "health": health("online"),
        "health_corrected": health("corrected"),
        "bias": None if last_bias is None else round(float(last_bias), 6),
        "bias_series": _points(
            pd.Series(np.where(np.isinf(fused.uncertainty), np.nan, fused.bias), index)
        ),
        "corrected": _points(pd.Series(fused.estimate, index)),
    }
