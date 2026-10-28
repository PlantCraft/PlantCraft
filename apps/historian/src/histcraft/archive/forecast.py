"""How fast the archive grows and when the disk fills (round 8 D4).

Each point grows by the values it archived in the last 24 h times its bytes per value, until
its retention starts deleting as much as it writes: a point kept 400 days that already holds 100
grows 300 days more, one kept forever never stops. The forecast adds those up for the next year
(``bytes_per_year``) and finds the day the free disk is used up (``days_to_full``; None when the
growth stops before). The collector's housekeeping stores it hourly (archive state
``forecast``) for the ``archive.disk_low`` condition, raised below ``ALERT_DAYS``.
"""

from __future__ import annotations

import math
import shutil
from pathlib import Path
from typing import Any

DAY_MS = 86_400_000
ALERT_DAYS = 90
# A point that archived nothing yet is costed at this many bytes per value.
DEFAULT_BYTES_PER_VALUE = 2.0


def free_bytes(path: Path) -> int | None:
    """Free bytes on the disk that holds ``path`` (None when it cannot be told)."""

    try:
        return int(shutil.disk_usage(path).free)
    except OSError:
        return None


def forecast(
    points: list[dict[str, Any]],
    stats: dict[int, dict[str, Any]],
    free: int | None,
    now: int,
) -> dict[str, Any]:
    """The growth of the archive and the days until ``free`` bytes are used.

    ``points``: catalog points (``id``, ``retention_days`` in effect, 0 forever); ``stats``:
    ``ArchiveStore.point_stats``."""

    stored = sum(int(item["bytes"]) for item in stats.values())
    values = sum(int(item["values"]) for item in stats.values())
    average = stored / values if values else DEFAULT_BYTES_PER_VALUE
    growth: list[tuple[float, float]] = []  # (bytes a day, days it keeps growing)
    for point in points:
        item = stats.get(int(point["id"]))
        if not item or not item.get("day"):
            continue
        per_value = item["bytes"] / item["values"] if item["values"] else average
        rate = float(item["day"]) * per_value
        retention = int(point.get("retention_days") or 0)
        if retention <= 0:
            left = math.inf
        else:
            held = (now - int(item["first"])) / DAY_MS if item.get("first") is not None else 0.0
            left = max(0.0, retention - held)
        if left > 0:
            growth.append((rate, left))
    per_day = sum(rate for rate, _ in growth)
    per_year = sum(rate * min(365.0, left) for rate, left in growth)
    return {
        "bytes_per_day": round(per_day),
        "bytes_per_year": round(per_year),
        "free_bytes": free,
        "days_to_full": None if free is None else _days_to_full(growth, float(free)),
        "alert_days": ALERT_DAYS,
        "at": now,
    }


def _days_to_full(growth: list[tuple[float, float]], free: float) -> float | None:
    """The first day the growth uses ``free`` bytes; None when it stops before."""

    used, day = 0.0, 0.0
    # The rate drops each time a point reaches its retention: walk those days in order.
    ends = sorted({left for _, left in growth})
    for end in ends:
        rate = sum(r for r, left in growth if left > day)
        if rate <= 0:
            return None
        if used + rate * (end - day) >= free:
            return round(day + (free - used) / rate, 1)
        used += rate * (end - day)
        day = end
    return None
