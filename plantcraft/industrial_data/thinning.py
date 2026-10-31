"""Fewer points for a chart without losing what matters on it: a spike, a trip, a step.

Taking every n-th point (the old way) misses any event shorter than the gap between kept points:
a day at 1 s thinned to 1,500 points keeps one value in 58, so a 5 s spike is gone. Here the
series is cut into buckets and each bucket keeps its lowest and its highest value, in time
order, so every excursion is still drawn at its full height with the same number of points.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypeVar

import numpy as np

T = TypeVar("T")


def _numbers(values: list[Any]) -> np.ndarray | None:
    """The values as floats, or None when one is not a number (a state, a text, a flag, a gap)."""

    if any(type(item) is bool or isinstance(item, str) for item in values):
        return None
    try:
        array = np.asarray(values, dtype=float)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(array).any() else array


def thin_extremes(points: Sequence[T], max_points: int, value: Any = None) -> list[T]:
    """At most ``max_points`` of ``points`` (plus the first and the last), in time order.

    ``value(point)`` gives a point's number; left out, the point is ``(time, value)``. Each
    bucket keeps its minimum and maximum; a series with values that are not numbers (states,
    texts) keeps every n-th point instead, as there is no "highest" to keep.
    """

    count = len(points)
    if max_points < 2 or count <= max_points:
        return list(points)
    read = value or (lambda point: point[1])
    values = [read(point) for point in points]
    array = _numbers(values)
    if array is None:
        kept = list(points[:: count // max_points + 1])
        if kept[-1] is not points[-1]:
            kept.append(points[-1])
        return kept
    buckets = max_points // 2
    size = -(-count // buckets)
    # Vectorised: pad the series to whole buckets (with the bucket's own edge values, which never
    # win a min or max they would not win anyway), then one argmin and one argmax per bucket.
    padded = np.pad(array, (0, buckets * size - count), mode="edge").reshape(buckets, size)
    base = np.arange(buckets) * size
    low = np.minimum(base + padded.argmin(axis=1), count - 1)
    high = np.minimum(base + padded.argmax(axis=1), count - 1)
    keep = np.unique(np.concatenate(([0, count - 1], low, high)))
    return [points[int(index)] for index in keep]
