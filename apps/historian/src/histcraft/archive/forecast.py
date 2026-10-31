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


# Rollup levels (H9): rows a point keeps per day, and bytes per row on disk with its index
# (measured on PostgreSQL 16, ``ci/bench/storage/rollups.md``).
LEVEL_ROWS_PER_DAY = {"hour": 24.0, "day": 1.0, "month": 12.0 / 365.0}
ROW_BYTES = {"hour": 125, "day": 150, "month": 150}
LEVEL_SETTINGS = {
    "hour": "hourly_retention_days",
    "day": "daily_retention_days",
    "month": "monthly_retention_days",
}


def level_days(raw_days: int, settings: dict[str, Any]) -> dict[str, int]:
    """The days each rollup level keeps for a point whose raw values are kept ``raw_days`` (0:
    forever): its setting, but never less than the finer levels and the raw values (a level
    shorter than those would be summed again from them)."""

    out: dict[str, int] = {}
    floor = int(raw_days)
    for level, key in LEVEL_SETTINGS.items():
        days = int(settings.get(key) or 0)
        floor = 0 if floor == 0 or days == 0 else max(days, floor)
        out[level] = floor
    return out


def retention_disk(
    points: list[dict[str, Any]],
    stats: dict[int, dict[str, Any]],
    rows: dict[str, int],
    settings: dict[str, Any],
    raw_days: dict[int, int],
) -> list[dict[str, Any]]:
    """The disk each retention takes (the Settings page, H9): per level (``raw``, ``hour``,
    ``day``, ``month``) what it holds now and what it holds once every point keeps its full
    retention at the values archived in the last 24 h; ``per_year`` when some point keeps it
    forever (then the yearly growth of those points is counted for one year)."""

    stored = sum(int(item["bytes"]) for item in stats.values())
    values = sum(int(item["values"]) for item in stats.values())
    average = stored / values if values else DEFAULT_BYTES_PER_VALUE
    levels = {
        "raw": {"level": "raw", "days": int(settings.get("retention_days") or 0), "now": stored},
    }
    for level, key in LEVEL_SETTINGS.items():
        levels[level] = {
            "level": level,
            "days": int(settings.get(key) or 0),
            "now": int(rows.get(level, 0)) * ROW_BYTES[level],
        }
    full = {name: 0.0 for name in levels}
    forever = {name: False for name in levels}
    for point in points:
        item = stats.get(int(point["id"]))
        if not item or not item.get("day"):
            continue
        days = int(raw_days.get(int(point["id"]), 0))
        per_value = item["bytes"] / item["values"] if item["values"] else average
        kept = {"raw": days, **level_days(days, settings)}
        rates = {"raw": float(item["day"]) * per_value}
        if point.get("kind", "number") == "number":
            rates.update(
                {level: LEVEL_ROWS_PER_DAY[level] * ROW_BYTES[level] for level in LEVEL_SETTINGS}
            )
        for name, rate in rates.items():
            if kept[name] <= 0:
                forever[name] = True
                full[name] += rate * 365.0
            else:
                full[name] += rate * kept[name]
    return [
        {**levels[name], "full": round(full[name]), "per_year": forever[name]}
        for name in ("raw", "hour", "day", "month")
    ]


def raw_days(points: list[dict[str, Any]]) -> dict[int, int]:
    """Each point's raw retention in effect, in days (0: forever): its own, else its source's,
    else the general one; an import keeps its values until it is deleted, unless it was given a
    retention of its own."""

    return {
        int(point["id"]): int(point["retention_days"] or 0)
        if point.get("source_kind") != "import"
        or (point.get("origins") or {}).get("retention_days") != "general"
        else 0
        for point in points
    }


def cutoffs(
    points: list[dict[str, Any]], settings: dict[str, Any], now: int
) -> tuple[dict[int, int], dict[str, dict[int, int]]]:
    """The raw cutoff of each point kept for a time (ms), and each rollup level's (H9)."""

    raw: dict[int, int] = {}
    levels: dict[str, dict[int, int]] = {level: {} for level in LEVEL_SETTINGS}
    for point, days in raw_days(points).items():
        if days > 0:
            raw[point] = now - days * DAY_MS
        for level, kept in level_days(days, settings).items():
            if kept > 0:
                levels[level][point] = now - kept * DAY_MS
    return raw, levels
