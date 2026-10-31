"""A4: a regression (OLS, ridge, PLS) trained once by Calibrate, with its validity range."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from linkcraft.assets.calibrate import calibrate_on_asset
from linkcraft.assets.run import AssetTiming, run_on_asset
from linkcraft.models.regression import Regression, fit_regression
from tests.plant import NOW, sid
from tests.test_asset_algorithms import STEP, TIMING, UNIT, unit_fake, unit_runtime


def data(rng, n=400, collinear=False):
    a = rng.normal(10, 2, n)
    b = a + rng.normal(0, 0.01, n) if collinear else rng.normal(5, 1, n)
    y = 3.0 + 2.0 * a - 1.5 * b + rng.normal(0, 0.05, n)
    return np.column_stack([a, b]), y


@pytest.mark.parametrize("method", ["ols", "ridge", "pls"])
def test_each_method_recovers_the_relation(method):
    rows, y = data(np.random.default_rng(1))
    model = fit_regression(rows, y, ["a", "b"], method=method, alpha=0.01, components=2)
    assert model.r2 > 0.99 and model.rmse < 0.2
    assert np.allclose(model.coefficients, [2.0, -1.5], atol=0.05)
    again = Regression.from_dict(model.as_dict())
    assert np.allclose(again.predict(rows), model.predict(rows))


def test_pls_stays_steady_where_inputs_move_together():
    rows, y = data(np.random.default_rng(2), collinear=True)
    model = fit_regression(rows, y, ["a", "b"], method="pls", components=1)
    # One direction carries both inputs: the prediction is right, the coefficients sensible.
    assert model.r2 > 0.95 and max(abs(c) for c in model.coefficients) < 5


def test_the_range_marks_where_the_estimate_extrapolates():
    rows, y = data(np.random.default_rng(3))
    model = fit_regression(rows, y, ["a", "b"], method="ols")
    inside = np.array([[model.low[0] + 0.1, model.high[1] - 0.1]])
    above = np.array([[model.high[0] + 1.0, 5.0]])
    assert model.outside(inside).tolist() == [[0, 0]]
    assert model.outside(above).tolist() == [[1, 0]]
    # A margin of the span on each side still counts as inside.
    span = model.high[0] - model.low[0]
    near = np.array([[model.high[0] + 0.05 * span, 5.0]])
    assert model.outside(near, margin=0.1).tolist() == [[0, 0]]


def test_too_few_target_samples_is_said_in_words():
    with pytest.raises(ValueError, match="samples of the target"):
        fit_regression(np.ones((5, 2)), np.ones(5), ["a", "b"])


def regression_diagram(calibration=None, share=0.1):
    return {
        "nodes": [
            {"id": "op", "block": "input.signal", "parameters": {"role": "op", "asset": "tic-1"}},
            {"id": "pv", "block": "input.signal", "parameters": {"signal": sid("TIC-1.PV")}},
            {
                "id": "reg",
                "block": "model.regression",
                "parameters": {"calibration": calibration, "method": "ridge", "share": share},
            },
            {"id": "out", "block": "output.result", "parameters": {"name": "Regression"}},
        ],
        "edges": [
            {"source": "op", "source_port": "value", "target": "reg", "target_port": "inputs"},
            {"source": "pv", "source_port": "value", "target": "reg", "target_port": "target"},
            {"source": "reg", "source_port": "result", "target": "out", "target_port": "in"},
        ],
    }


def test_calibrate_trains_it_and_a_run_warns_outside_the_training_range(tmp_path):
    runtime = unit_runtime(tmp_path, unit_fake())
    try:
        start = pd.Timestamp(NOW) - pd.Timedelta(minutes=90)
        found = calibrate_on_asset(
            regression_diagram(),
            "reg",
            UNIT,
            client=runtime.service_client,
            start=start,
            end=start + pd.Timedelta(hours=1),
            timing=AssetTiming.model_validate(TIMING),
        )
        calibration = found["calibration"]
        assert calibration["kind"] == "regression" and calibration["inputs"] == [sid("TIC-1.OP")]
        assert found["samples"] >= 300 and calibration["r2"] > 0.3

        def verdict(changed):
            end = pd.Timestamp(NOW)
            return run_on_asset(
                regression_diagram(changed),
                UNIT,
                client=runtime.service_client,
                start=end - pd.Timedelta(minutes=30),
                end=end,
                step=STEP,
            )["summary"]["verdict"]

        assert verdict(calibration)["status"] == "ok"
        # Trained on a narrower range: the valve now goes above it and the estimate extrapolates.
        narrow = {**calibration, "high": [calibration["low"][0] + 1.0]}
        found = verdict(narrow)
        assert found["status"] == "warning" and "went above" in found["message"]
    finally:
        runtime.shutdown()
