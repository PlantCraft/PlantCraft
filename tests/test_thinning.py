"""Thinning a series for a chart keeps its spikes (bench of 2026-10-31, plan item C1)."""

import random

from plantcraft.industrial_data.thinning import thin_extremes


def _day_with_spikes() -> tuple[list[list[float]], list[int]]:
    rng = random.Random(1)
    values = [50 + rng.gauss(0, 0.3) for _ in range(86_400)]
    spikes = sorted(rng.sample(range(86_390), 20))
    for start in spikes:
        for second in range(5):
            values[start + second] = 80.0
    return [[float(i), v] for i, v in enumerate(values)], spikes


def test_every_short_spike_survives_with_the_same_number_of_points():
    points, _ = _day_with_spikes()
    kept = thin_extremes(points, 1500)
    assert len(kept) <= 1502
    assert sum(1 for _, value in kept if value > 70) >= 20
    every_nth = points[:: len(points) // 1500 + 1]
    assert sum(1 for _, value in every_nth if value > 70) < 20  # what the old way showed


def test_order_ends_and_small_series():
    points, _ = _day_with_spikes()
    kept = thin_extremes(points, 1000)
    stamps = [stamp for stamp, _ in kept]
    assert stamps == sorted(stamps) and len(set(stamps)) == len(stamps)
    assert kept[0] is points[0] and kept[-1] is points[-1]
    assert thin_extremes(points[:10], 1500) == points[:10]


def test_states_and_texts_keep_every_nth_point():
    points = [[i, "Running" if i % 7 else "Stopped"] for i in range(10_000)]
    kept = thin_extremes(points, 100)
    assert len(kept) <= 101 and kept[-1] is points[-1]
