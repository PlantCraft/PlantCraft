"""Recent reads of remote historians kept in memory (gap G20): a dashboard refresh asks the
source only for the newest minutes, and what it answers is what a whole read would answer."""

from __future__ import annotations

import numpy as np

from histcraft.sources.cache import LATE_MS, RecentReads

MIN = 60_000


class Historian:
    """A source with one sample a minute per address; text for addresses starting with T."""

    def __init__(self):
        self.calls: list[tuple[list[str], int, int]] = []
        self.broken: set[str] = set()

    def recorded(self, addresses, start_ms, end_ms):
        self.calls.append((list(addresses), start_ms, end_ms))
        out = {}
        for address in addresses:
            if address in self.broken:
                out[address] = "PI Point not found"
                continue
            # Values in [start, end] and the last one before start.
            first = (start_ms // MIN) * MIN
            if first == start_ms:
                first -= MIN
            times = np.arange(max(first, 0), end_ms + 1, MIN, dtype=np.int64)
            if address.startswith("T"):
                out[address] = (times, [f"s{int(t // MIN)}" for t in times])
            else:
                out[address] = (times, times.astype(np.float64) / MIN)
        return out


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _same(a, b):
    assert np.array_equal(a[0], b[0])
    if isinstance(a[1], list):
        assert a[1] == b[1]
    else:
        assert np.array_equal(a[1], b[1])


def test_a_refresh_asks_only_for_the_tail_and_answers_like_a_whole_read():
    source, clock = Historian(), Clock()
    recent = RecentReads(300, clock=clock)
    key = ("pi", "2026-10-21T00:00:00")
    first = recent.recorded(key, ["FI-1", "TAG"], 0, 480 * MIN, source.recorded)
    assert len(source.calls) == 1
    clock.now += 60
    later = recent.recorded(key, ["FI-1", "TAG"], 60 * MIN, 481 * MIN, source.recorded)
    assert source.calls[-1] == (["FI-1", "TAG"], 480 * MIN - LATE_MS, 481 * MIN)
    whole = Historian().recorded(["FI-1", "TAG"], 60 * MIN, 481 * MIN)
    for address in ("FI-1", "TAG"):
        _same(later[address], whole[address])
    _same(first["FI-1"], Historian().recorded(["FI-1"], 0, 480 * MIN)["FI-1"])


def test_a_read_inside_what_is_known_does_not_reach_the_source():
    source, clock = Historian(), Clock()
    recent = RecentReads(300, clock=clock)
    recent.recorded(("pi", 1), ["FI-1"], 0, 480 * MIN, source.recorded)
    # Asked again a second later up to "now" (a second later too): memory.
    clock.now += 1
    recent.recorded(("pi", 1), ["FI-1"], 0, 480 * MIN + 1000, source.recorded)
    assert len(source.calls) == 1
    clock.now += 30
    inside = recent.recorded(("pi", 1), ["FI-1"], 100 * MIN, 200 * MIN, source.recorded)
    assert len(source.calls) == 1 and recent.hits == 2
    _same(inside["FI-1"], Historian().recorded(["FI-1"], 100 * MIN, 200 * MIN)["FI-1"])


def test_old_spans_errors_earlier_starts_and_changed_sources_read_the_source_again():
    source, clock = Historian(), Clock()
    recent = RecentReads(300, clock=clock)
    source.broken.add("BAD")
    answer = recent.recorded(("pi", 1), ["FI-1", "BAD"], 0, 60 * MIN, source.recorded)
    assert answer["BAD"] == "PI Point not found"
    recent.recorded(("pi", 1), ["BAD"], 0, 60 * MIN, source.recorded)
    assert len(source.calls) == 2  # an error is never kept
    recent.recorded(("pi", 1), ["FI-1"], -30 * MIN, 60 * MIN, source.recorded)
    assert source.calls[-1][1] == -30 * MIN  # before the known span: a whole read
    recent.recorded(("pi", 2), ["FI-1"], 0, 60 * MIN, source.recorded)
    assert source.calls[-1][0] == ["FI-1"] and len(source.calls) == 4  # the source changed
    clock.now += 301
    recent.recorded(("pi", 2), ["FI-1"], 10 * MIN, 61 * MIN, source.recorded)
    assert source.calls[-1][1] == 10 * MIN  # too old: read whole again


def test_zero_seconds_turns_it_off():
    source = Historian()
    recent = RecentReads(0)
    for _ in range(2):
        recent.recorded(("pi", 1), ["FI-1"], 0, 60 * MIN, source.recorded)
    assert len(source.calls) == 2
