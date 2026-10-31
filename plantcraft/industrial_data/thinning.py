"""Fewer points for a chart without losing what matters on it: a spike, a trip, a step.

Taking every n-th point (the old way) misses any event shorter than the gap between kept points:
a day at 1 s thinned to 1,500 points keeps one value in 58, so a 5 s spike is gone. Here the
series is cut into buckets and each bucket keeps its lowest and its highest value, in time
order, so every excursion is still drawn at its full height with the same number of points.
"""

from __future__ import annotations

from collections.abc import Sequence
from numbers import Real
from typing import Any, TypeVar

T = TypeVar("T")


def _number(value: Any) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool) and value == value


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
    if not all(_number(item) for item in values):
        kept = list(points[:: count // max_points + 1])
        if kept[-1] is not points[-1]:
            kept.append(points[-1])
        return kept
    buckets = max_points // 2
    size = -(-count // buckets)
    keep: list[int] = []
    for begin in range(0, count, size):
        end = min(begin + size, count)
        low = min(range(begin, end), key=values.__getitem__)
        high = max(range(begin, end), key=values.__getitem__)
        keep.extend(sorted({low, high}))
    if keep[0] != 0:
        keep.insert(0, 0)
    if keep[-1] != count - 1:
        keep.append(count - 1)
    return [points[index] for index in keep]
