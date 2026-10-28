"""Hourly rollups (gap G9): a trend on an hourly or daily grid read from rollups gives the
numbers the samples give, and every write drops the hours it changes."""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pytest

from histcraft.archive import rollup
from histcraft.archive.query import PointRef, Reader
from histcraft.archive.store import HOUR_MS, ArchiveStore
from tests.conftest import database
from tests.test_query import MS, T0

DAYS = 10
WAVE = PointRef(1, "TI-200.PV")
VALVE = PointRef(2, "XV-201.OPEN", step=True)


def _wave(days: int = DAYS, every_s: int = 60, gap_hours: tuple[int, int] = (50, 53)):
    rng = np.random.default_rng(7)
    times = MS + np.arange(0, days * 86_400_000, every_s * 1000, dtype=np.int64)
    values = 50 + 10 * np.sin(np.arange(len(times)) / 90) + rng.normal(0, 1, len(times))
    hours = (times - MS) / HOUR_MS
    values[(hours >= gap_hours[0]) & (hours < gap_hours[1])] = np.nan  # an outage
    return [(int(t), float(v)) for t, v in zip(times, values, strict=True)]


@pytest.fixture
def archive(tmp_path):
    store = ArchiveStore(database(tmp_path))
    wave = _wave()
    valve = [(at, float(int((at - MS) // (7 * HOUR_MS)) % 2)) for at, _ in wave[::30]]
    store.append({1: ("number", wave), 2: ("number", valve)})
    return store


def test_built_rollups_answer_like_the_samples(archive):
    reader = Reader(archive)
    expected = {
        (point.tag, step): reader.series(point, T0, T0 + timedelta(days=DAYS), step)
        for point in (WAVE, VALVE)
        for step in (3600, 86_400, 6 * 3600)
    }
    hours = rollup.build(archive, [(1, False), (2, True)], hours=10_000)
    assert hours == 2 * (DAYS * 24 - 2)  # all but the first and the unsealed last hour
    assert len(archive.rollups(1, False, MS, MS + DAYS * 86_400_000)) == DAYS * 24 - 2
    for point in (WAVE, VALVE):
        for step in (3600, 86_400, 6 * 3600):
            stamps, values = reader.series(point, T0, T0 + timedelta(days=DAYS), step)
            want_stamps, want = expected[(point.tag, step)]
            assert stamps == want_stamps
            assert [v is None for v in values] == [v is None for v in want], (point, step)
            got = np.array([np.nan if v is None else v for v in values])
            ref = np.array([np.nan if v is None else v for v in want])
            np.testing.assert_allclose(got, ref, rtol=1e-9, atol=1e-9, equal_nan=True)


def test_the_series_reads_rollups_and_only_the_newest_hours_from_chunks(archive, monkeypatch):
    rollup.build(archive, [(1, False)], hours=10_000)
    reads = []
    original = archive.read

    def counting(point, start_ms, end_ms):
        reads.append((start_ms, end_ms))
        return original(point, start_ms, end_ms)

    monkeypatch.setattr(archive, "read", counting)
    Reader(archive).series(WAVE, T0, T0 + timedelta(days=DAYS), 3600)
    # The first hour (left out) and the last one (still open) come from the samples.
    assert [(end - start) // HOUR_MS for start, end in reads] == [1, 1]


def test_a_partial_build_fills_a_bounded_number_of_hours_and_reads_stay_right(archive):
    reader = Reader(archive)
    want = reader.series(WAVE, T0, T0 + timedelta(days=DAYS), 3600)
    assert rollup.build(archive, [(1, False)], hours=30) == 30
    got = reader.series(WAVE, T0, T0 + timedelta(days=DAYS), 3600)
    assert got[0] == want[0]
    np.testing.assert_allclose(
        [np.nan if v is None else v for v in got[1]],
        [np.nan if v is None else v for v in want[1]],
        rtol=1e-9,
        equal_nan=True,
    )


def test_writes_drop_the_hours_they_change(archive):
    rollup.build(archive, [(1, False)], hours=10_000)
    span = (MS, MS + DAYS * 86_400_000)
    reader = Reader(archive)
    window = (T0 + timedelta(hours=96), T0 + timedelta(hours=104))
    old = reader.series(WAVE, *window, 3600)[1]
    sealed = set(range(MS + HOUR_MS, MS + (DAYS * 24 - 1) * HOUR_MS, HOUR_MS))
    assert set(archive.rollups(1, False, *span)) == sealed
    # A backfill inside hour 100 changes only the segments around it: that hour goes.
    archive.replace(1, "number", [(MS + 100 * HOUR_MS + 30_000, 999.0)])
    assert set(archive.rollups(1, False, *span)) == sealed - {MS + 100 * HOUR_MS}
    rollup.build(archive, [(1, False)], hours=10_000)
    rolled = reader.series(WAVE, *window, 3600)[1]
    halves = np.array(reader.series(WAVE, *window, 1800)[1], dtype=float)  # never rollups
    np.testing.assert_allclose(rolled, halves.reshape(-1, 2).mean(axis=1), rtol=1e-9)
    assert rolled[4] > old[4] + 5 and rolled[:4] == old[:4]  # the 999 shows in hour 100
    # A newer value after the last one changes no sealed hour.
    archive.append({1: ("number", [(MS + DAYS * 86_400_000 + 5 * HOUR_MS, 1.0)])})
    assert set(archive.rollups(1, False, *span)) == sealed
    # Retention drops the start: hours up to the first value left go too.
    archive.prune({1: MS + 48 * HOUR_MS})
    first = min(archive.rollups(1, False, *span))
    assert first > archive.span(1)[0]
    # A deleted point leaves no rollups.
    archive.delete_points([1])
    assert archive.rollups(1, False, *span) == {}


def test_rollups_kept_for_the_other_interpolation_are_not_used(archive):
    rollup.build(archive, [(1, True)], hours=10_000)  # as if the point were a step point
    assert Reader(archive).archive.rollups(1, False, MS, MS + DAYS * 86_400_000) == {}
    rollup.build(archive, [(1, False)], hours=10_000)
    assert archive.rollups(1, True, MS, MS + DAYS * 86_400_000) == {}


def test_a_flush_finds_its_hours_from_the_last_chunk_alone(tmp_path):
    """The hours a flush drops (one indexed row read) are the ones the full scan of the point's
    chunks finds, wherever the new values fall among many chunks still waiting for compaction."""

    store = ArchiveStore(database(tmp_path))
    rng = np.random.default_rng(3)
    for flush in range(200):  # one chunk per collector flush, 5 s apart
        at = MS + flush * 5_000
        store.append({1: ("number", [(at, 1.0), (at + 2_000, 2.0)])})
    full_scan = (
        "SELECT COALESCE((SELECT MIN(t0) FROM chunks WHERE point = 1 AND t0 < ? AND t1 >= ?),"
        " (SELECT MAX(t1) FROM chunks WHERE point = 1 AND t1 < ?), ?) AS at"
    )
    last_chunk = (
        "SELECT COALESCE((SELECT CASE WHEN t1 >= ? THEN t0 ELSE t1 END FROM chunks"
        " WHERE point = 1 AND t0 < ? ORDER BY t0 DESC LIMIT 1), ?) AS at"
    )
    firsts = [MS - 1, MS, MS + 1_000, MS + 3_000, MS + 999_000, MS + 2_000_000]
    firsts += [int(MS + value) for value in rng.integers(0, 1_100_000, 50)]
    with store._connect() as connection:
        for first in firsts:
            expected = connection.execute(full_scan, (first, first, first, first)).fetchone()
            found = connection.execute(last_chunk, (first, first, first)).fetchone()
            assert found["at"] == expected["at"], first


def test_rollups_keep_each_hours_extremes_and_count(archive):
    rollup.build(archive, [(1, False)], hours=10_000)
    times, values = archive.read(1, MS, MS + DAYS * 86_400_000)
    kept = archive.rollups(1, False, MS, MS + DAYS * 86_400_000)
    for hour in (MS + HOUR_MS, MS + 51 * HOUR_MS, MS + 100 * HOUR_MS):  # 51: in the outage
        inside = (times >= hour) & (times < hour + HOUR_MS) & np.isfinite(values)
        _, _, low, high, n = kept[hour]
        assert n == int(inside.sum())
        if n:
            assert (low, high) == (values[inside].min(), values[inside].max())
        else:
            assert low is None and high is None


def test_rollups_written_before_their_extremes_are_built_again(archive):
    rollup.build(archive, [(1, False)], hours=10_000)
    hours = sorted(archive.rollups(1, False, MS, MS + DAYS * 86_400_000))
    # As Historian 0.5 left them: cover and area only.
    archive.put_rollups(1, False, [(hour, 1.0, 1.0) for hour in hours])
    assert all(item[4] is None for item in archive.rollups(1, False, MS, MS + 10**12).values())
    assert rollup.build(archive, [(1, False)], hours=10_000) == len(hours)
    assert all(item[4] is not None for item in archive.rollups(1, False, MS, MS + 10**12).values())


def test_a_windows_mean_min_and_max_from_rollups_are_the_samples(archive, monkeypatch):
    reader = Reader(archive)
    now = T0 + timedelta(days=DAYS, minutes=-17)
    windows = ("1d", "3d", "7d", "6h")
    want = {
        (point.tag, agg, window): reader.value(point, agg, window, now=now)["value"]
        for point in (WAVE, VALVE)
        for agg in ("mean", "min", "max")
        for window in windows
    }
    rollup.build(archive, [(1, False), (2, True)], hours=10_000)
    reads = []
    original = archive.read

    def counting(point, start_ms, end_ms):
        reads.append(end_ms - start_ms)
        return original(point, start_ms, end_ms)

    monkeypatch.setattr(archive, "read", counting)
    for (tag, agg, window), expected in want.items():
        point = WAVE if tag == WAVE.tag else VALVE
        got = reader.value(point, agg, window, now=now)["value"]
        assert got == pytest.approx(expected, rel=1e-9, abs=1e-9), (tag, agg, window)
    # Only the two ends of each window were read from the samples, never days of them.
    assert max(reads) <= 2 * HOUR_MS


def test_the_min_max_band_of_a_long_trend_comes_from_rollups(archive, monkeypatch):
    reader = Reader(archive)
    start, end = T0 + timedelta(hours=1), T0 + timedelta(days=DAYS)
    near = reader.extremes(WAVE, start, start + timedelta(days=6), 3600)
    assert reader.extremes(WAVE, start, end, 3600) is None  # past 7 days: too many samples
    rollup.build(archive, [(1, False)], hours=10_000)
    low, high = reader.extremes(WAVE, start, end, 3600)
    assert len(low) == DAYS * 24 - 1
    assert low[: len(near[0])] == near[0] and high[: len(near[1])] == near[1]
    assert low[50] is None  # the outage


def test_a_window_from_the_first_value_uses_the_rollups_after_its_first_hour(archive, monkeypatch):
    reader = Reader(archive)
    now = T0 + timedelta(days=DAYS)
    want = reader.value(WAVE, "mean", f"{DAYS}d", now=now)["value"]
    rollup.build(archive, [(1, False)], hours=10_000)
    reads = []
    original = archive.read
    monkeypatch.setattr(archive, "read", lambda p, a, b: reads.append(b - a) or original(p, a, b))
    assert reader.value(WAVE, "mean", f"{DAYS}d", now=now)["value"] == pytest.approx(want)
    assert max(reads) <= HOUR_MS  # the first hour and the newest one, not ten days
