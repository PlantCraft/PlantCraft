"""Lab fusion: an online value drifting away from the truth, corrected by laboratory results at
their sampling times, each known only once approved."""

from __future__ import annotations

import numpy as np
import pytest

from plantcraft_sdk.estimators import fuse_lab, sensor_health


def drifting(steps: int = 3000, seed: int = 3):
    rng = np.random.default_rng(seed)
    true = 50 + 2 * np.sin(np.arange(steps) / 150.0)
    bias = np.cumsum(0.02 * rng.standard_normal(steps)) + np.linspace(0, 3, steps)
    online = true + bias + 0.1 * rng.standard_normal(steps)
    lab = np.full(steps, np.nan)
    lab[::60] = true[::60] + 0.05 * rng.standard_normal(len(lab[::60]))
    return true, online, lab


def rmse(a, b):
    return float(np.sqrt(np.mean((a - b) ** 2)))


def test_the_fused_value_follows_the_truth_where_the_online_value_drifts():
    true, online, lab = drifting()
    out = fuse_lab(online, lab, delay_steps=20, lab_noise=0.05**2)
    late = slice(300, None)
    assert out.used == len(np.flatnonzero(np.isfinite(lab[: len(lab) - 20])))
    assert rmse(out.estimate[late], true[late]) < rmse(online[late], true[late]) / 4
    assert np.all(np.isfinite(out.uncertainty[20:])) and out.q > 0


def test_a_result_corrects_only_from_its_arrival():
    true, online, lab = drifting()
    fixed = {"delay_steps": 30, "q": 1e-3, "online_noise": 0.01}
    out = fuse_lab(online, lab, **fixed)
    # The first result is sampled at 0 and arrives at 30: nothing moves before it.
    assert np.all(out.bias[:30] == 0) and np.all(np.isinf(out.uncertainty[:30]))
    assert out.bias[30] != 0 and np.isfinite(out.uncertainty[30])
    # The past does not change when a later result arrives (no look into the future).
    cut = 1200
    short = fuse_lab(online[:cut], lab[:cut], **fixed)
    assert np.allclose(short.bias, out.bias[:cut])


def test_a_result_never_approved_never_corrects():
    _true, online, lab = drifting()
    arrival = np.full(len(lab), -1)
    taken = np.flatnonzero(np.isfinite(lab))
    arrival[taken[::2]] = taken[::2] + 10
    out = fuse_lab(online, lab, arrival=arrival, q=1e-3)
    assert out.used == len(taken[::2])
    none = fuse_lab(online, lab, arrival=np.full(len(lab), -1), q=1e-3)
    assert none.used == 0 and np.all(none.bias == 0)


def test_the_grids_must_match():
    with pytest.raises(ValueError):
        fuse_lab(np.ones(5), np.ones(4))
    with pytest.raises(ValueError):
        fuse_lab(np.ones(5), np.ones(5), arrival=np.ones(3))


def test_health_from_the_error_against_the_lab():
    actual = np.linspace(0, 10, 50)
    assert sensor_health(actual, actual) == 100.0
    assert sensor_health(actual, actual + 100) == 0.0
    middle = sensor_health(actual, actual + 0.5 * np.std(actual))
    assert 0 < middle < 100
    assert np.isnan(sensor_health([1.0, 2.0], [1.0, 2.0]))


def test_deadband_and_step_limit_hold_the_bias():
    _true, online, lab = drifting()
    free = fuse_lab(online, lab, q=1e-3, online_noise=0.01)
    held = fuse_lab(online, lab, q=1e-3, online_noise=0.01, deadband=1e6)
    # The first result sets the bias; with a huge dead zone no later one moves it.
    first = held.bias[np.flatnonzero(np.isfinite(held.uncertainty))[0]]
    assert np.all(held.bias[np.isfinite(held.uncertainty)] == first)
    capped = fuse_lab(online, lab, q=1e-3, online_noise=0.01, max_step=0.01)
    assert np.max(np.abs(np.diff(capped.bias[60:]))) <= 0.01 + 1e-12
    assert np.max(np.abs(np.diff(free.bias[60:]))) > 0.01
