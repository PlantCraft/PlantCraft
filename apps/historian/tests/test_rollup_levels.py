"""Daily and monthly rollups (H9): summed from the hours, read for trends of whole days and long
windows, kept for their own retention after the raw values are gone, dropped by a write into
the past and summed again."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from histcraft.archive import forecast, rollup
from histcraft.archive.query import PointRef, Reader, to_ms
from histcraft.archive.store import HOUR_MS, ArchiveStore
from tests.conftest import database

T0 = datetime(2026, 8, 20, tzinfo=timezone.utc)
MS = to_ms(T0)
DAY = 86_400_000
DAYS = 75  # across the ends of August, September and October
WAVE = PointRef(1, "TI-300.PV")


def _values(days: int = DAYS, every_s: int = 300) -> list[tuple[int, float]]:
    rng = np.random.default_rng(11)
    times = MS + np.arange(0, days * DAY, every_s * 1000, dtype=np.int64)
    values = 50 + 10 * np.sin(np.arange(len(times)) / 300) + rng.normal(0, 1, len(times))
    return [(int(t), float(v)) for t, v in zip(times, values, strict=True)]


@pytest.fixture
def archive(tmp_path):
    store = ArchiveStore(database(tmp_path))
    values = _values()
    # A chunk a day, as compaction leaves a month: retention deletes whole chunks.
    for day in range(DAYS):
        part = [item for item in values if MS + day * DAY <= item[0] < MS + (day + 1) * DAY]
        store.append({1: ("number", part)})
    return store


def _series(reader: Reader, days: int = DAYS, step: int = 86_400):
    stamps, values = reader.series(WAVE, T0, T0 + timedelta(days=days), step)
    return stamps, np.array([np.nan if v is None else v for v in values])


def test_days_and_months_are_summed_from_whole_hours(archive):
    rollup.build(archive, [(1, False)], hours=100_000)
    days = archive.coarse(1, False, rollup.DAY, MS, MS + DAYS * DAY)
    # The first day lacks its first hour and the last one is not sealed: neither is summed.
    assert sorted(days) == [MS + k * DAY for k in range(1, DAYS - 1)]
    months = archive.coarse(1, False, rollup.MONTH, MS - 31 * DAY, MS + DAYS * DAY)
    september, october = rollup.next_month(MS), rollup.next_month(rollup.next_month(MS))
    assert sorted(months) == [september, october]  # August starts mid-month
    hours = archive.rollups(1, False, september, october)
    month = months[september]
    assert month[0] == october
    assert month[1] == pytest.approx(sum(row[0] for row in hours.values()))
    assert month[2] == pytest.approx(sum(row[1] for row in hours.values()))
    assert month[5] == sum(row[4] for row in hours.values())
    assert archive.rollup_rows() == {
        "hour": len(archive.rollups(1, False, 0, 2**62)),
        "day": DAYS - 2,
        "month": 2,
    }


def test_a_daily_trend_and_a_long_window_read_the_days_and_answer_like_the_samples(
    archive, monkeypatch
):
    reader = Reader(archive)
    want_stamps, want = _series(reader)
    window = reader.value(WAVE, "mean", f"{DAYS - 5}d", now=T0 + timedelta(days=DAYS - 1))
    rollup.build(archive, [(1, False)], hours=100_000)
    hourly_reads = []
    original = archive.rollups

    def counting(point, step, start, end):
        hourly_reads.append(end - start)
        return original(point, step, start, end)

    monkeypatch.setattr(archive, "rollups", counting)
    stamps, got = _series(reader)
    assert stamps == want_stamps
    np.testing.assert_allclose(got, want, rtol=1e-9, atol=1e-9, equal_nan=True)
    # Only the hours outside the days kept: the first and the last day.
    assert sum(hourly_reads) <= 2 * DAY
    hourly_reads.clear()
    again = reader.value(WAVE, "mean", f"{DAYS - 5}d", now=T0 + timedelta(days=DAYS - 1))
    assert again["value"] == pytest.approx(window["value"], rel=1e-9)
    assert sum(hourly_reads) <= 2 * DAY


def test_rollups_outlive_the_raw_values_for_their_own_retention(archive):
    reader = Reader(archive)
    _, want = _series(reader)
    rollup.build(archive, [(1, False)], hours=100_000)
    now = MS + DAYS * DAY
    raw = {1: now - 20 * DAY}  # 20 days of raw values
    levels = {"hour": {1: now - 40 * DAY}, "day": {}, "month": {}}
    archive.prune(raw, levels)
    assert archive.span(1)[0] >= now - 21 * DAY
    hours = archive.rollups(1, False, 0, 2**62)
    assert min(hours) >= now - 40 * DAY - HOUR_MS
    # The raw values of the first 55 days are gone: their days still read from the rollups.
    _, got = _series(reader)
    np.testing.assert_allclose(got[1:50], want[1:50], rtol=1e-9, atol=1e-9)
    # The daily rollups go at their own cutoff, never before.
    archive.prune(raw, {"hour": {}, "day": {1: MS + 10 * DAY}, "month": {}})
    days = archive.coarse(1, False, rollup.DAY, 0, 2**62)
    assert min(days) == MS + 10 * DAY


def test_a_write_into_the_past_drops_the_days_and_months_after_it_and_they_come_back(archive):
    rollup.build(archive, [(1, False)], hours=100_000)
    before = archive.coarse(1, False, rollup.DAY, 0, 2**62)
    at = MS + 40 * DAY + 3 * HOUR_MS + 1000
    archive.replace(1, "number", [(at, 99.0)])
    after = archive.coarse(1, False, rollup.DAY, 0, 2**62)
    assert max(t1 for t1, *_ in after.values()) <= MS + 40 * DAY
    assert max(after) < MS + 40 * DAY
    months = archive.coarse(1, False, rollup.MONTH, 0, 2**62)
    assert all(row[0] <= at for row in months.values())
    rollup.build(archive, [(1, False)], hours=100_000)
    rebuilt = archive.coarse(1, False, rollup.DAY, 0, 2**62)
    assert sorted(rebuilt) == sorted(before)
    assert rebuilt[MS + 40 * DAY][4] == 99.0  # the new value is that day's highest


def test_each_level_keeps_at_least_the_finer_ones():
    settings = {
        "hourly_retention_days": 100,
        "daily_retention_days": 3000,
        "monthly_retention_days": 1000,
    }
    assert forecast.level_days(400, settings) == {"hour": 400, "day": 3000, "month": 3000}
    assert forecast.level_days(0, settings) == {"hour": 0, "day": 0, "month": 0}
    assert forecast.level_days(30, {"hourly_retention_days": 0}) == {
        "hour": 0,
        "day": 0,
        "month": 0,
    }
    points = [
        {"id": 1, "retention_days": 30, "source_kind": "opcua", "origins": {}, "kind": "number"}
    ]
    raw, levels = forecast.cutoffs(points, settings, 1000 * DAY)
    assert raw == {1: 970 * DAY}
    assert levels == {"hour": {1: 900 * DAY}, "day": {1: -2000 * DAY}, "month": {1: -2000 * DAY}}


def test_disk_by_retention_counts_each_level():
    points = [
        {"id": 1, "retention_days": 10, "kind": "number"},
        {"id": 2, "retention_days": 0, "kind": "number"},
    ]
    stats = {
        1: {"bytes": 1000, "values": 500, "day": 100, "first": 0},
        2: {"bytes": 1000, "values": 500, "day": 100, "first": 0},
    }
    settings = {
        "retention_days": 400,
        "hourly_retention_days": 20,
        "daily_retention_days": 0,
        "monthly_retention_days": 0,
    }
    levels = {
        item["level"]: item
        for item in forecast.retention_disk(
            points, stats, {"hour": 10, "day": 2, "month": 0}, settings, {1: 10, 2: 0}
        )
    }
    assert levels["raw"]["now"] == 2000
    assert levels["raw"]["full"] == round(200 * 10 + 200 * 365) and levels["raw"]["per_year"]
    hour = forecast.ROW_BYTES["hour"]
    assert levels["hour"]["now"] == 10 * hour
    assert levels["hour"]["full"] == round(24 * hour * 20 + 24 * hour * 365)
    assert levels["day"]["per_year"] and levels["month"]["days"] == 0
