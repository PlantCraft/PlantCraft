"""Rounds ask only for what is new (``data.cache``): the same samples as a whole read."""

from __future__ import annotations

import numpy as np
import pandas as pd

from linkcraft.data.cache import RawCache, read_incremental

START = pd.Timestamp("2026-10-30 00:00")
STAMPS = pd.date_range(START, periods=3 * 1440, freq="1min", tz="UTC")
ALL = {
    name: pd.Series(np.random.default_rng(n).normal(size=len(STAMPS)), index=STAMPS)
    for n, name in enumerate("abc")
}


class Source:
    def __init__(self):
        self.asked: list[tuple[list[str], pd.Timestamp, pd.Timestamp]] = []

    def __call__(self, names, begin, end):
        self.asked.append((list(names), begin, end))
        lo, hi = begin.tz_localize("UTC"), end.tz_localize("UTC")
        return {n: ALL[n][(ALL[n].index >= lo) & (ALL[n].index <= hi)] for n in names}, []


def window(end):
    return end - pd.Timedelta(hours=24), end


def test_the_next_rounds_read_only_the_new_part_and_see_the_same_samples():
    cache, source = RawCache(overlap_seconds=900), Source()
    end = START + pd.Timedelta(hours=30)
    for step in range(5):
        start, finish = window(end + pd.Timedelta(minutes=10 * step))
        columns, _ = read_incremental(cache, list("abc"), start, finish, source)
        whole, _ = Source()(list("abc"), start, finish)
        for name in "abc":
            # the Historian never sends a freq; joined samples carry none
            pd.testing.assert_series_equal(columns[name], whole[name], check_freq=False)
    first, later = source.asked[0], source.asked[1:]
    assert first[1] == window(end)[0]
    # each later round from the last end minus the overlap: 25 minutes, not 24 hours
    assert all(finish - begin == pd.Timedelta(minutes=25) for _, begin, finish in later)


def test_a_late_value_inside_the_overlap_is_seen_and_older_changes_wait_for_the_refresh():
    clock = [0.0]
    cache, source = (
        RawCache(overlap_seconds=900, refresh_seconds=3600, clock=lambda: clock[0]),
        Source(),
    )
    end = START + pd.Timedelta(hours=30)
    read_incremental(cache, ["a"], *window(end), source)
    late = end.tz_localize("UTC") - pd.Timedelta(minutes=5)
    old = end.tz_localize("UTC") - pd.Timedelta(hours=2)
    saved = ALL["a"].copy()
    try:
        ALL["a"][late] = 99.0
        ALL["a"][old] = -99.0
        columns, _ = read_incremental(cache, ["a"], *window(end + pd.Timedelta(minutes=10)), source)
        assert columns["a"][late] == 99.0 and columns["a"][old] != -99.0
        clock[0] = 3600.0
        columns, _ = read_incremental(cache, ["a"], *window(end + pd.Timedelta(minutes=20)), source)
        assert columns["a"][old] == -99.0
    finally:
        ALL["a"] = saved


def test_means_and_failures_are_never_kept():
    cache = RawCache()
    end = START + pd.Timedelta(hours=30)

    def read(names, begin, finish):
        means = pd.Series([1.0], index=[begin.tz_localize("UTC")])
        means.attrs["means"] = True
        return {"a": means}, [{"signal": "b", "status": 502, "detail": "down"}]

    read_incremental(cache, ["a", "b"], *window(end), read)
    assert cache.values() == 0


def test_quality_changes_are_joined_across_incremental_reads():
    marks = {
        "a": [
            (STAMPS[0], "uncertain"),
            (STAMPS[27 * 60], "good"),
            (STAMPS[30 * 60 + 5], "bad"),
        ]
    }

    def source(names, begin, end):
        lo, hi = begin.tz_localize("UTC"), end.tz_localize("UTC")
        columns = {}
        for name in names:
            column = ALL[name][(ALL[name].index >= lo) & (ALL[name].index <= hi)].copy()
            changes = [(at, code) for at, code in marks.get(name, []) if at <= hi]
            before = [item for item in changes if item[0] <= lo]
            inside = [item for item in changes if item[0] > lo]
            state = before[-1:] if before and before[-1][1] != "good" else []
            column.attrs["quality"] = [
                {"t": at.isoformat(), "quality": code} for at, code in state + inside
            ]
            columns[name] = column
        return columns, []

    cache = RawCache(overlap_seconds=900)
    end = START + pd.Timedelta(hours=30)
    for step in range(3):
        start, finish = window(end + pd.Timedelta(minutes=10 * step))
        columns, _ = read_incremental(cache, ["a"], start, finish, source)
        whole, _ = source(["a"], start, finish)
        assert columns["a"].attrs["quality"] == whole["a"].attrs["quality"], step
    assert [item["quality"] for item in columns["a"].attrs["quality"]] == [
        "uncertain",
        "good",
        "bad",
    ]


def test_samples_are_kept_compact_when_exact_and_come_back_identical():
    stamps = pd.date_range(START, periods=2000, freq="1500ms", tz="UTC")
    real = pd.Series(
        np.random.default_rng(5).normal(50, 5, len(stamps)).astype(np.float32).astype(float),
        index=stamps,
        name="a",
    )
    exact = pd.Series(np.random.default_rng(6).normal(size=len(stamps)), index=stamps)
    cache = RawCache(max_bytes=10**9)
    end = stamps[-1]
    cache.merge("real", real, START.tz_localize("UTC"), end, None)
    cache.merge("exact", exact, START.tz_localize("UTC"), end, None)
    pd.testing.assert_series_equal(cache._kept["real"].values, real)
    pd.testing.assert_series_equal(cache._kept["exact"].values, exact)
    # float32 numbers and int32 milliseconds: 8 bytes a sample; float64 ones: 12
    assert cache.nbytes() == len(stamps) * 8 + len(stamps) * 12


def test_the_least_recently_used_signals_are_dropped_past_the_memory_limit():
    cache, source = RawCache(overlap_seconds=900, max_bytes=2 * 1440 * 12 + 1000), Source()
    start, finish = window(START + pd.Timedelta(hours=30))
    read_incremental(cache, ["a", "b"], start, finish, source)
    assert set(cache._kept) == {"a", "b"}
    read_incremental(cache, ["c"], start, finish, source)  # "a" was used least recently
    assert set(cache._kept) == {"b", "c"} and cache.evicted == 1
    assert cache.nbytes() <= cache.max_bytes
    columns, _ = read_incremental(cache, ["a"], start, finish, source)
    pd.testing.assert_series_equal(columns["a"], Source()(["a"], start, finish)[0]["a"])


def test_scheduled_means_read_only_the_new_steps_and_match_a_whole_read():
    from linkcraft.data.cache import read_means_incremental

    asked = []

    def means(names, begin, end, step):
        asked.append((begin, end))
        out = {}
        for name in names:
            raw = ALL[name][(ALL[name].index >= begin) & (ALL[name].index < end)]
            out[name] = (
                raw.resample(f"{step:g}s", origin=begin, closed="left", label="left")
                .mean()
                .dropna()
            )
        return out, []

    cache = RawCache(overlap_seconds=900)
    end = (START + pd.Timedelta(hours=30)).tz_localize("UTC")
    for k in range(4):
        finish = end + pd.Timedelta(minutes=10 * k)
        begin = finish - pd.Timedelta(hours=24)
        columns, _ = read_means_incremental(cache, ["a", "b"], begin, finish, 300.0, means)
        whole, _ = means(["a", "b"], begin, finish, 300.0)
        for name in "ab":
            pd.testing.assert_series_equal(columns[name], whole[name], check_freq=False)
    # after the first run: from the last whole step before the end minus 15 min, not 24 h
    assert all(f - b <= pd.Timedelta(minutes=30) for b, f in asked[2::2])
    assert len(asked) == 8
    # a window off the grid of the kept means is read whole
    asked.clear()
    read_means_incremental(cache, ["a"], begin + pd.Timedelta(seconds=7), finish, 300.0, means)
    assert asked[0][0] == begin + pd.Timedelta(seconds=7)
    # kept apart from the raw samples of the same signal
    assert "a@300s" in cache._kept and "a" not in cache._kept
