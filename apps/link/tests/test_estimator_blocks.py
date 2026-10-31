"""The Estimators library: Kalman filter, sensor drift and soft sensor blocks on a known process."""

from __future__ import annotations

import numpy as np
import pandas as pd
from plantcraft_sdk.blocks import NoData

from linkcraft.blocks.catalog import CATALOG

STEP = 5.0


def _process(n: int = 2000, seed: int = 7) -> tuple[pd.Index, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    index = pd.date_range("2026-10-31", periods=n, freq="5s", tz="UTC")
    u = np.repeat(rng.uniform(0.3, 0.7, n // 100 + 1), 100)[:n]
    a = np.exp(-STEP / 60.0)
    x = np.empty(n)
    x[0] = 0.5
    for k in range(1, n):
        drive = u[k - 1 - 4] if k > 4 else u[0]
        x[k] = a * x[k - 1] + (1 - a) * 0.8 * drive
    return index, u, x


def _run(block_id: str, inputs: dict, **parameters) -> dict:
    block = CATALOG[block_id]
    return block.run(inputs, block.spec.parameters(**parameters), None)


def test_kalman_cleans_a_noisy_signal_better_than_the_raw_one():
    index, u, true = _process()
    noisy = true + np.random.default_rng(1).normal(0, 0.03, len(true))
    out = _run("estimator.kalman", {"x": pd.Series(noisy, index), "u": pd.Series(u, index)})
    error = np.sqrt(np.mean((out["value"].to_numpy() - true)[200:] ** 2))
    assert error < 0.03 / 4
    assert (out["uncertainty"] > 0).all()
    alone = _run("estimator.kalman", {"x": pd.Series(noisy, index)})
    assert np.sqrt(np.mean((alone["value"].to_numpy() - true)[200:] ** 2)) < 0.03


def test_drift_finds_the_bias_a_sensor_picked_up():
    index, u, true = _process()
    drift = np.clip(np.arange(len(true)) - 1000, 0, None) * 0.0001  # 0.1 by the end
    measured = true + drift + np.random.default_rng(2).normal(0, 0.005, len(true))
    out = _run(
        "estimator.drift",
        {"x": pd.Series(measured, index), "u": pd.Series(u, index)},
        fit_minutes=60,
    )
    assert abs(out["bias"].iloc[-1] - drift[-1]) < 0.02
    assert np.sqrt(np.mean((out["corrected"].to_numpy() - true)[1200:] ** 2)) < 0.02


def test_soft_sensor_fills_the_gaps_between_lab_samples():
    index, u, true = _process()
    lab = pd.Series(np.nan, index)
    lab.iloc[::120] = true[::120]
    out = _run("estimator.soft_sensor", {"target": lab, "x1": pd.Series(u, index)}, lag_minutes=10)
    held = lab.ffill().to_numpy()
    assert np.nanmean(np.abs(out["value"].to_numpy() - true)) < np.nanmean(np.abs(held - true))


def test_too_few_samples_is_no_data():
    index = pd.date_range("2026-10-31", periods=10, freq="5s", tz="UTC")
    out = _run("estimator.kalman", {"x": pd.Series(np.ones(10), index)})
    assert isinstance(out["value"], NoData)


def _drifting_analyzer(n: int = 3000, seed: int = 3):
    rng = np.random.default_rng(seed)
    index = pd.date_range("2026-10-31", periods=n, freq="5s", tz="UTC")
    true = 50 + 2 * np.sin(np.arange(n) / 150.0)
    bias = np.cumsum(0.02 * rng.standard_normal(n)) + np.linspace(0, 3, n)
    online = true + bias + 0.1 * rng.standard_normal(n)
    sampled = index[::60]  # a result every 5 minutes, at its sampling time
    lab = pd.Series(true[::60] + 0.05 * rng.standard_normal(len(sampled)), sampled)
    return index, true, online, lab


def test_lab_fusion_corrects_a_drifting_analyzer_with_late_results():
    index, true, online, lab = _drifting_analyzer()
    out = _run(
        "estimator.lab_fusion",
        {"x": pd.Series(online, index), "lab": lab},
        approval_minutes=100 / 60,
        lab_repeatability=0.05,
    )
    late = slice(300, None)
    fused = out["value"].to_numpy()
    assert np.sqrt(np.mean((fused - true)[late] ** 2)) < (
        np.sqrt(np.mean((online - true)[late] ** 2)) / 4
    )
    # The first result (sampled at the start) is known only 100 s later: nothing moves before.
    assert (out["bias"].iloc[:20] == 0).all() and out["bias"].iloc[20] != 0
    assert (out["uncertainty"].iloc[20:] > 0).all()


def test_lab_fusion_without_results_in_the_window_is_no_data():
    index, _true, online, lab = _drifting_analyzer()
    later = lab.copy()
    later.index = later.index + pd.Timedelta(days=30)
    out = _run("estimator.lab_fusion", {"x": pd.Series(online, index), "lab": later})
    assert isinstance(out["value"], NoData)


def test_lab_fusion_limits_each_correction():
    index, _true, online, lab = _drifting_analyzer()
    out = _run("estimator.lab_fusion", {"x": pd.Series(online, index), "lab": lab}, max_step=0.05)
    assert out["bias"].diff().iloc[100:].abs().max() <= 0.05 + 1e-9
