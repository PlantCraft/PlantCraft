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
            pd.testing.assert_series_equal(columns[name], whole[name])
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
