"""How fast the archive grows and when the disk fills (round 8 D4)."""

from __future__ import annotations

from histcraft.archive.forecast import forecast

DAY = 86_400_000
NOW = 1000 * DAY


def _stats(first_days_ago: float, day_values: int, values: int = 1000, size: int = 2000):
    return {"chunks": 1, "values": values, "bytes": size, "first": NOW - first_days_ago * DAY,
            "last": NOW, "day": day_values}  # fmt: skip


def test_a_point_kept_forever_grows_until_the_disk_is_full():
    found = forecast([{"id": 1, "retention_days": 0}], {1: _stats(10, 500)}, 10_000, NOW)
    assert found["bytes_per_day"] == 1000  # 500 values a day at 2 bytes each
    assert found["bytes_per_year"] == 365_000
    assert found["days_to_full"] == 10.0


def test_a_retention_stops_the_growth():
    points = [{"id": 1, "retention_days": 30}, {"id": 2, "retention_days": 400}]
    stats = {1: _stats(30, 500), 2: _stats(100, 500)}
    found = forecast(points, stats, 10**9, NOW)
    # Point 1 already deletes as much as it writes; point 2 grows 300 days more.
    assert found["bytes_per_day"] == 1000
    assert found["bytes_per_year"] == 300_000  # it stops after 300 days
    assert found["days_to_full"] is None
    tight = forecast(points, stats, 100_000, NOW)
    assert tight["days_to_full"] == 100.0


def test_nothing_known_is_no_forecast():
    found = forecast([{"id": 1, "retention_days": 0}], {}, None, NOW)
    assert (found["bytes_per_day"], found["days_to_full"], found["free_bytes"]) == (0, None, None)
