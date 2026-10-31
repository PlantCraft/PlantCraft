"""Reconciliation (M5) and redundant pair drift (A23): balances with a planted gross error."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from plantcraft_sdk.blocks import NoData

from linkcraft.blocks.catalog import CATALOG
from linkcraft.methods.reconciliation import BalanceError, chi2_quantile, parse_balances, reconcile

NAMES = ["s1", "s2", "s3", "s4", "s5"]
BALANCES = "s1 + s2 = s3; s3 = s4 + s5"
TRUE = np.array([60.0, 40.0, 100.0, 70.0, 30.0])


def _run(block_id: str, inputs: dict, **parameters) -> dict:
    block = CATALOG[block_id]
    return block.run(inputs, block.spec.parameters(**parameters), None)


def _flows(bias: dict[int, float] | None = None, n: int = 720, noise: float = 0.01, seed: int = 3):
    rng = np.random.default_rng(seed)
    index = pd.date_range("2026-10-31", periods=n, freq="10s", tz="UTC")
    swing = 1.0 + 0.05 * np.sin(np.arange(n) / 90.0)
    out = {}
    for k, name in enumerate(NAMES):
        value = TRUE[k] * swing * (1.0 + rng.normal(0, noise, n))
        value *= 1.0 + (bias or {}).get(k, 0.0)
        out[name] = pd.Series(value, index)
    return out


def test_balances_parse_with_factors_and_reject_bad_text():
    a = parse_balances("s1 + 0.5*s2 = s3; s3 - s4 = s5", ["s1", "s2", "s3", "s4", "s5"])
    assert a.tolist() == [[1, 0.5, -1, 0, 0], [0, 0, 1, -1, -1]]
    for text in ("s1 + s2", "s1 = s9", "= s1", "s1 = s1", "s1 = 2 s2"):
        with pytest.raises(BalanceError):
            parse_balances(text, ["s1", "s2"])


def test_chi2_quantiles_match_the_tables():
    assert chi2_quantile(0.95, 1) == pytest.approx(3.841, abs=1e-3)
    assert chi2_quantile(0.95, 2) == pytest.approx(5.991, abs=1e-3)
    assert chi2_quantile(0.95, 5) == pytest.approx(11.070, rel=0.01)
    assert chi2_quantile(0.95, 20) == pytest.approx(31.410, rel=0.01)


def test_serial_elimination_names_the_biased_meter_and_its_bias():
    a = parse_balances(BALANCES, NAMES)
    y = TRUE.copy()
    y[0] *= 1.15
    found = reconcile(a, y, (0.02 * TRUE) ** 2)
    assert found.suspects == [0]
    assert found.adjustments[0] == pytest.approx(0.15 * TRUE[0], rel=1e-6)
    assert np.allclose(a @ found.values, 0, atol=1e-9)
    clean = reconcile(a, TRUE, (0.02 * TRUE) ** 2)
    assert not clean.gross_error and clean.gamma == pytest.approx(0.0, abs=1e-12)


def test_block_closes_the_balances_and_passes_a_healthy_window():
    out = _run("estimator.reconcile", _flows(), balances=BALANCES)
    assert out["result"].status == "ok"
    rec = np.column_stack([out[f"r{k}"].to_numpy() for k in range(1, 6)])
    assert np.allclose(rec[:, 0] + rec[:, 1] - rec[:, 2], 0, atol=1e-6)
    assert np.allclose(rec[:, 2] - rec[:, 3] - rec[:, 4], 0, atol=1e-6)
    assert isinstance(out["r6"], NoData)
    assert abs(out["imbalance"].mean()) < 1.0


def test_block_names_a_ten_percent_bias_on_a_two_percent_meter():
    # s3 is in both balances: the only meter that explains both missing.
    out = _run("estimator.reconcile", _flows({2: 0.10}), balances=BALANCES)
    result = out["result"]
    assert result.status == "bad"
    suspect = result.detail["suspects"][0]
    assert suspect["stream"] == "s3" and not suspect["alike"]
    assert suspect["percent"] == pytest.approx(10.0, abs=1.5)
    assert "s3" in result.message
    # s4 and s5 are only in the second balance: either could carry it, and both are named.
    other = _run("estimator.reconcile", _flows({3: 0.10}), balances=BALANCES)["result"]
    named = other.detail["suspects"][0]
    assert other.status == "bad" and {named["stream"], *named["alike"]} == {"s4", "s5"}


def test_meters_in_the_same_balances_are_named_together():
    flows = {"s1": _flows()["s3"], "s2": _flows()["s4"] * 1.1, "s3": _flows()["s5"]}
    out = _run("estimator.reconcile", flows, balances="s1 = s2 + s3")
    assert out["result"].status == "bad"
    # One balance and three meters: any of them could carry the error; all show the same z.
    assert out["result"].detail["suspects"][0]["alike"]


def test_no_redundancy_and_bad_text_are_unknown():
    flows = _flows()
    out = _run(
        "estimator.reconcile",
        {"s1": flows["s1"], "s2": flows["s2"]},
        balances="s1 = s2",
        uncertainties="s2 = 1",
    )
    assert out["result"].status in ("ok", "bad")
    broken = _run("estimator.reconcile", {"s1": flows["s1"], "s2": flows["s2"]}, balances="s1 = s7")
    assert broken["result"].status == "unknown" and isinstance(broken["r1"], NoData)
    with pytest.raises(ValueError):
        CATALOG["estimator.reconcile"].spec.parameters(uncertainties="s1 = lots")


def test_pair_drift_finds_a_meter_drifting_away_and_passes_twins():
    index = pd.date_range("2026-10-31", periods=2000, freq="5s", tz="UTC")
    rng = np.random.default_rng(5)
    flow = 50.0 + 2.0 * np.sin(np.arange(2000) / 200.0)
    a = flow + rng.normal(0, 0.3, 2000)
    b = flow + rng.normal(0, 0.3, 2000)
    twins = _run("estimator.pair_drift", {"a": pd.Series(a, index), "b": pd.Series(b, index)})
    assert twins["result"].status == "ok"
    drift = np.clip(np.arange(2000) - 800, 0, None) * 0.0025  # 3 (6%) by the end
    out = _run("estimator.pair_drift", {"a": pd.Series(a + drift, index), "b": pd.Series(b, index)})
    assert out["result"].status == "bad"
    assert out["drift"].iloc[-1] == pytest.approx(drift[-1], abs=0.5)
    assert (out["uncertainty"] > 0).all()
    short = _run(
        "estimator.pair_drift",
        {"a": pd.Series(a[:10], index[:10]), "b": pd.Series(b[:10], index[:10])},
    )
    assert isinstance(short["drift"], NoData) and short["result"].status == "unknown"
