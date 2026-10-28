"""Minimum-variance (Harris) index (gap G19) against processes whose index is known."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from plantcraft_sdk.methods import LoopDataset, MethodStatus

from linkcraft.methods.cpm.harris import estimate_delay, harris_eta, harris_index, impulse_response


def _ar1(phi: float, n: int = 20_000, seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, 1, n)
    out = np.zeros(n)
    for i in range(1, n):
        out[i] = phi * out[i - 1] + noise[i]
    return out


def _run(pv, sp=None, op=None, **params):
    n = len(pv)
    frame = {"timestamp": pd.date_range("2026-10-21", periods=n, freq="1s"), "pv": pv}
    frame["sp"] = np.zeros(n) if sp is None else sp
    if op is not None:
        frame["op"] = op
    dataset = LoopDataset(loop_id="FIC-1", data=pd.DataFrame(frame), sample_time_seconds=1.0)
    block = harris_index
    return block.run(block.input_schema(dataset=dataset), block.parameter_schema(**params))


def test_impulse_response_of_an_ar1_is_its_powers():
    np.testing.assert_allclose(impulse_response(np.array([0.9]), 4), [1, 0.9, 0.81, 0.729])


@pytest.mark.parametrize(("phi", "delay"), [(0.9, 2), (0.9, 1), (0.7, 3), (0.0, 5)])
def test_eta_matches_the_closed_form_for_an_ar1_error(phi, delay):
    # e_t = phi e_t-1 + a_t: sigma_mv^2 = sum_(k<b) phi^(2k), sigma_e^2 = 1 / (1 - phi^2).
    expected = (1 - phi**2) * sum(phi ** (2 * k) for k in range(delay))
    eta, _, _ = harris_eta(_ar1(phi), delay, order=10)
    assert eta == pytest.approx(expected, abs=0.02)


def test_white_noise_is_at_minimum_variance_and_scores_healthy():
    finding = _run(_ar1(0.0, n=3000), dead_time_seconds=3)
    assert finding.status == MethodStatus.OK
    assert finding.metrics["harris_index"] > 0.9 and finding.score == 0
    assert finding.metrics["delay_samples"] == 3 and finding.metrics["delay_source"] == "parameter"


def test_a_sluggish_loop_scores_poorly_and_says_how_much_retuning_could_remove():
    finding = _run(_ar1(0.98, n=5000), dead_time_seconds=1)
    assert finding.metrics["harris_index"] < 0.1 and finding.score == 100
    assert "retuning could remove" in harris_index.describe(finding.metrics)


def test_the_dead_time_is_estimated_from_op_moves():
    rng = np.random.default_rng(11)
    op = np.cumsum(rng.normal(0, 1, 4000))
    pv = np.roll(op, 7) * 0.8 + rng.normal(0, 0.2, 4000)
    assert estimate_delay(pv, op, 60) == 7
    finding = _run(pv - pv.mean(), op=op)
    assert finding.metrics["delay_samples"] == 7 and finding.metrics["delay_source"] == "estimated"
    # Without an OP the shortest dead time is assumed (the strictest benchmark).
    assert _run(pv - pv.mean()).metrics["delay_source"] == "assumed"


def test_a_short_window_is_not_enough():
    finding = _run(_ar1(0.5, n=150))
    assert finding.status == MethodStatus.INSUFFICIENT_DATA
