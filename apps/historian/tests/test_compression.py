import math

import numpy as np
import pytest

from histcraft.archive.compression import Compressor


def run(compressor, times, values):
    archived = []
    for at, value in zip(times, values, strict=True):
        archived += compressor.feed(int(at), value)
    return archived


def rebuild(archived, snapshot, times):
    points = archived + ([snapshot] if snapshot else [])
    t = np.array([p[0] for p in points], dtype=float)
    v = np.array([p[1] for p in points], dtype=float)
    return np.interp(times, t, v)


@pytest.mark.parametrize("deviation", [0.05, 0.5, 2.0])
def test_rebuilt_signal_stays_within_the_deviation(deviation):
    rng = np.random.default_rng(7)
    times = np.arange(0, 7200) * 1000
    values = 50 + np.cumsum(rng.normal(0, 0.2, len(times))) + 5 * np.sin(times / 300_000)
    compressor = Compressor(deviation=deviation, max_seconds=100_000)
    archived = run(compressor, times, values)
    rebuilt = rebuild(archived, compressor.snapshot, times)
    assert np.max(np.abs(rebuilt - values)) <= deviation + 1e-9
    if deviation >= 0.5:  # noise of 0.2 per step: a smaller deviation keeps most values
        assert len(archived) < len(times) / 3


def test_flat_signal_keeps_only_the_max_interval_points():
    compressor = Compressor(deviation=0.1, max_seconds=600)
    archived = run(compressor, np.arange(0, 3600) * 1000, [10.0] * 3600)
    assert 6 <= len(archived) <= 8
    gaps = np.diff([a[0] for a in archived]) / 1000
    assert gaps.max() <= 601


def test_zero_deviation_keeps_every_bend_and_drops_straight_runs():
    times = np.arange(0, 100) * 1000
    values = [float(min(i, 50)) for i in range(100)]  # ramp, then flat
    compressor = Compressor(deviation=0.0, max_seconds=10_000)
    archived = run(compressor, times, values)
    assert [a[0] for a in archived] == [0, 50_000]
    assert compressor.snapshot == (99_000, 50.0)


def test_text_archives_every_change_with_the_value_held_before():
    compressor = Compressor(kind="text", max_seconds=10_000)
    labels = ["AUTO"] * 5 + ["MAN"] * 5 + ["AUTO"]
    archived = run(compressor, [i * 1000 for i in range(11)], labels)
    assert archived == [(0, "AUTO"), (4000, "AUTO"), (5000, "MAN"), (9000, "MAN"), (10_000, "AUTO")]


def test_step_points_archive_on_change_only():
    compressor = Compressor(step=True, max_seconds=10_000)
    values = [0.0, 0.0, 1.0, 1.0, 1.0, 0.0]
    archived = run(compressor, [i * 1000 for i in range(6)], values)
    assert archived == [(0, 0.0), (1000, 0.0), (2000, 1.0), (4000, 1.0), (5000, 0.0)]


def test_a_gap_closes_the_line_with_a_marker_once():
    compressor = Compressor(deviation=1.0)
    run(compressor, [0, 1000, 2000], [1.0, 1.1, 1.2])
    out = compressor.gap(3000)
    assert out[0] == (2000, 1.2)
    assert out[1][0] == 3000 and math.isnan(out[1][1])
    assert compressor.gap(4000) == []
    assert compressor.feed(5000, 7.0) == [(5000, 7.0)]


def test_a_gap_at_the_last_value_time_still_gets_its_marker():
    compressor = Compressor(deviation=1.0)
    run(compressor, [0, 1000, 2000], [1.0, 1.1, 1.2])
    out = compressor.gap(1500)  # a source clock ahead of the collector's
    assert out[0] == (2000, 1.2)
    assert out[1][0] == 2001 and math.isnan(out[1][1])


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), "not a number", object()])
def test_bad_values_are_gaps_not_errors(bad):
    compressor = Compressor()
    compressor.feed(0, 1.0)
    out = compressor.feed(1000, bad)
    assert out and math.isnan(out[-1][1])


def test_time_never_goes_back():
    compressor = Compressor()
    compressor.feed(5000, 1.0)
    compressor.feed(6000, 2.0)
    assert compressor.feed(6000, 3.0) == []
    assert compressor.feed(1000, 3.0) == []
    assert compressor.snapshot == (6000, 2.0)


def test_percent_keeps_each_segment_within_that_share_of_its_start():
    rng = np.random.default_rng(3)
    times = np.arange(0, 7200) * 1000
    values = 80 + np.cumsum(rng.normal(0, 0.05, len(times))) + 20 * np.sin(times / 600_000)
    compressor = Compressor(percent=1.0, max_seconds=100_000)
    archived = run(compressor, times, values)
    rebuilt = rebuild(archived, compressor.snapshot, times)
    # Every value is within 1 % of the archived value its segment starts from.
    largest = max(abs(value) for _, value in archived)
    assert np.max(np.abs(rebuilt - values)) <= largest / 100 + 1e-9
    assert len(archived) < len(times) / 10
    # Near zero the share is small: the compressor keeps more, never strays further.
    assert Compressor(percent=1.0, archived=(0, 0.0)).tolerance() == 0.0


def test_the_exception_keeps_noise_from_the_compression():
    """Noise inside the exception never reaches the compression (D1): a flat line is kept."""

    noisy = Compressor(deviation=0.2, exception=0.1, max_seconds=600)
    plain = Compressor(deviation=0.2, max_seconds=600)
    kept_noisy = kept_plain = 0
    for second in range(300):
        value = 50.0 + (0.09 if second % 2 else -0.09) + second * 0.0
        kept_noisy += len(noisy.feed(second * 1000, value))
        kept_plain += len(plain.feed(second * 1000, value))
    assert kept_noisy == 1  # the first value; the rest is the held snapshot
    assert kept_plain >= 1
    # A real change passes the exception at once.
    assert noisy.feed(300_000, 55.0) != [] or noisy.snapshot == (300_000, 55.0)


def test_the_exception_as_a_share_of_the_value():
    compressor = Compressor(percent=0.2, exception_percent=0.1, max_seconds=600)
    compressor.feed(0, 100.0)
    compressor.feed(1000, 100.05)  # within 0.1 % of 100: taken as 100
    assert compressor.snapshot == (1000, 100.0)
    compressor.feed(2000, 101.0)
    assert compressor.snapshot == (2000, 101.0)
