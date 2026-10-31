"""M4: an empirical model (PCA) of normal operation for a unit with no physical model:
calibrated on a period, it judges by T² and SPE and names the signal that explains most."""

from __future__ import annotations

import numpy as np
import pandas as pd

from linkcraft.assets.calibrate import calibrate_on_asset
from linkcraft.assets.run import AssetTiming, run_on_asset
from linkcraft.models.pca import PcaModel, fit_pca, judge_pca
from tests.plant import NOW, sid
from tests.test_asset_algorithms import STEP, TIMING, UNIT, unit_fake, unit_runtime

NAMES = ["feed", "flow", "temperature", "pressure"]


def plant(rng, n):
    """Four signals driven by two hidden causes, plus noise."""

    causes = rng.normal(size=(n, 2))
    mix = np.array([[1.0, 0.2], [0.9, 0.1], [0.1, 1.0], [0.2, 0.8]])
    return causes @ mix.T + rng.normal(0, 0.05, size=(n, 4)) + [50, 40, 300, 10]


def test_normal_operation_stays_inside_and_a_broken_relation_is_found():
    rng = np.random.default_rng(1)
    model = fit_pca(plant(rng, 5000), NAMES, variance=0.9)
    assert model.components == 2 and model.explained > 0.9
    normal = judge_pca(plant(rng, 5000), model, confidence=0.99)
    assert normal.exceed_share < 0.04
    # The flow transmitter drifts away from the feed it follows: off the model (SPE).
    broken = plant(rng, 500)
    broken[:, 1] += 0.6
    found = judge_pca(broken, model, confidence=0.99)
    assert found.exceed_share > 0.9 and found.spe_share > 0.9
    assert max(found.contributions, key=found.contributions.get) in {"flow", "feed"}
    assert found.contributions["flow"] > 40
    # The model travels as the block's parameter.
    again = PcaModel.from_dict(model.as_dict())
    assert again.signals == NAMES and again.components == 2


def test_a_constant_signal_is_left_out_with_a_warning():
    rng = np.random.default_rng(2)
    rows = np.column_stack([plant(rng, 500), np.full(500, 7.0)])
    model = fit_pca(rows, [*NAMES, "spare"])
    assert model.signals == NAMES and "spare is constant" in model.warnings[0]


def empirical_diagram(calibration=None):
    return {
        "nodes": [
            {"id": "op", "block": "input.signal", "parameters": {"role": "op", "asset": "tic-1"}},
            {"id": "pv", "block": "input.signal", "parameters": {"signal": sid("TIC-1.PV")}},
            {
                "id": "pca",
                "block": "model.empirical",
                "parameters": {"calibration": calibration, "persistence": 1, "share": 0.2},
            },
            {"id": "out", "block": "output.result", "parameters": {"name": "Empirical model"}},
        ],
        "edges": [
            {"source": "op", "source_port": "value", "target": "pca", "target_port": "signals"},
            {"source": "pv", "source_port": "value", "target": "pca", "target_port": "signals"},
            {"source": "pca", "source_port": "result", "target": "out", "target_port": "in"},
        ],
    }


def test_calibrate_learns_the_unit_and_the_block_judges_a_shifted_measurement(tmp_path):
    runtime = unit_runtime(tmp_path, unit_fake(bias=4.0, minutes=15))
    try:
        hour = pd.Timedelta(hours=1)
        start = pd.Timestamp(NOW) - 2 * hour + pd.Timedelta(minutes=30)
        found = calibrate_on_asset(
            empirical_diagram(),
            "pca",
            UNIT,
            client=runtime.service_client,
            start=start,
            end=start + hour,
            timing=AssetTiming.model_validate(TIMING),
        )
        calibration = found["calibration"]
        assert calibration["kind"] == "pca" and len(calibration["signals"]) == 2
        assert found["used"] >= 1 and found["samples"] >= 300

        def judged(minutes):
            end = pd.Timestamp(NOW) - pd.Timedelta(minutes=minutes)
            return run_on_asset(
                empirical_diagram(calibration),
                UNIT,
                client=runtime.service_client,
                start=end - pd.Timedelta(minutes=10),
                end=end,
                step=STEP,
            )["summary"]["verdict"]

        assert judged(20)["status"] == "ok"  # before the shift
        shifted = judged(0)  # the last quarter hour reads 4 above what the valve explains
        assert shifted["status"] in {"warning", "bad"}
        assert "no longer move together" in shifted["message"]
    finally:
        runtime.shutdown()
