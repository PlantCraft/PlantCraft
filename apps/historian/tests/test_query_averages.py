"""The one-pass time-weighted averages give exactly what the integrals they replace gave."""

from __future__ import annotations

import numpy as np

from histcraft.archive import query


def _by_integrals(times, values, step, edges):
    times_f = times.astype(float)
    cover_knots = query._cumulative(times, values, step, 0)
    area_knots = query._cumulative(times, values, step, 1)
    cover = query._integral_at(times_f, values, step, 0, cover_knots, edges)
    area = query._integral_at(times_f, values, step, 1, area_knots, edges)
    covered = np.diff(cover)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(covered > 0, np.diff(area) / np.where(covered > 0, covered, 1.0), np.nan)


def test_averages_match_the_integrals_bit_for_bit():
    rng = np.random.default_rng(7)
    for _ in range(200):
        count = int(rng.integers(2, 2000))
        times = np.sort(rng.choice(10**7, count, replace=False)).astype(np.int64)
        values = rng.normal(size=count)
        values[rng.random(count) < 0.05] = np.nan  # bad samples leave holes
        edges = np.sort(rng.uniform(-(10**6), 1.1 * 10**7, int(rng.integers(2, 200))))
        for step in (True, False):
            assert np.array_equal(
                query._averages(times, values, step, edges),
                _by_integrals(times, values, step, edges),
                equal_nan=True,
            )
