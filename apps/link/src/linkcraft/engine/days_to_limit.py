"""Days until a degrading indicator reaches its limit (A18), as APM tools show it.

A straight line fitted to the indicator's recent points (least squares, time in days). When the
line heads toward the limit and fits well enough, the days left are ``(limit - now) / slope``,
counted from the last point; otherwise there is no forecast ("—"): a flat or noisy trend says
nothing about when. The loops' health uses it with the limit 50, below which a loop is critical.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

MIN_POINTS = 7
MIN_R2 = 0.5
# A forecast further than this says "not soon"; it is not shown as a number.
MAX_DAYS = 365.0


def days_to_limit(
    points: list[tuple[datetime, float]], limit: float, *, falling: bool = True
) -> dict[str, Any] | None:
    """``{days, slope_per_day, r2, last}`` when the fitted line reaches ``limit`` (going down
    when ``falling``, up otherwise) within ``MAX_DAYS``; None otherwise."""

    found = [(moment, float(value)) for moment, value in points if value is not None]
    if len(found) < MIN_POINTS:
        return None
    origin = found[0][0]
    xs = [(moment - origin).total_seconds() / 86400 for moment, _ in found]
    ys = [value for _, value in found]
    n = len(xs)
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx <= 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / sxx
    syy = sum((y - mean_y) ** 2 for y in ys)
    r2 = 1.0 if syy == 0 else (slope * slope * sxx) / syy
    now = mean_y + slope * (xs[-1] - mean_x)
    heading = slope < 0 if falling else slope > 0
    if not heading or r2 < MIN_R2:
        return None
    beyond = now <= limit if falling else now >= limit
    days = 0.0 if beyond else (limit - now) / slope
    if days > MAX_DAYS:
        return None
    return {
        "days": round(days, 1),
        "slope_per_day": round(slope, 3),
        "r2": round(r2, 2),
        "now": round(now, 1),
        "last": found[-1][0].isoformat().replace("+00:00", "Z"),
    }
