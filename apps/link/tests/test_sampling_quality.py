"""Sampling quality judges the recorded samples, not the analysis grid (gap G31).

The method's own assumption is that "timestamps reflect acquisition time"; the regular frame the
methods see is the analysis grid (``LINKCRAFT_RESAMPLE_SECONDS``), so its timestamps only ever say
what the grid step is. The recorded samples travel with the dataset (``LoopDataset.raw``).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from linkcraft.config import AnalysisConfig, LoopConfig, LoopSignals
from linkcraft.loops.analysis import analyze_loop
from tests.conftest import make_runtime
from tests.plant import HOURS, make_fake


def _raw(seconds: float, hours: float = 6.0, *, gap: tuple[int, int] | None = None) -> pd.DataFrame:
    index = pd.date_range("2026-10-01", periods=int(hours * 3600 / seconds), freq=f"{seconds}s")
    rng = np.random.default_rng(3)
    pv = 50 + rng.normal(0, 0.1, len(index))
    frame = pd.DataFrame(
        {"L.PV": pv, "L.SP": 50.0, "L.OP": 40 + rng.normal(0, 0.2, len(index))}, index=index
    )
    if gap:
        frame = frame.drop(frame.index[gap[0] : gap[1]])
    return frame


LOOP = LoopConfig(loop_id="L", name="L", signals=LoopSignals(pv="L.PV", sp="L.SP", op="L.OP"))


def _sampling(raw: pd.DataFrame, grid: int = 60, **parameters) -> dict:
    payload = analyze_loop(
        AnalysisConfig(resample_seconds=grid),
        LOOP,
        raw,
        method_ids=["sampling_quality"],
        parameter_overrides={"sampling_quality": parameters} if parameters else None,
    )
    return next(item for item in payload["results"] if item["method_id"] == "sampling_quality")


def test_recorded_10_s_data_on_a_60_s_grid_is_well_sampled():
    result = _sampling(_raw(10))
    assert result["metrics"]["median_sample_seconds"] == 10.0  # was 60: the grid step
    assert result["metrics"]["timestamp_source"] == "recorded"
    assert result["score"] == 0.0 and result["metrics"]["performance_component"] == 100.0


def test_coarse_recorded_data_is_still_penalised_whatever_the_grid():
    result = _sampling(_raw(120), grid=10)
    assert result["metrics"]["median_sample_seconds"] == 120.0  # was 10 on a 10 s grid
    assert result["score"] == 100.0  # (120 / 30 - 1) * 60, capped


def test_a_hole_in_the_recording_counts_as_a_gap():
    # 20 minutes without samples: the grid interpolates over it, the recording does not.
    result = _sampling(_raw(10, gap=(1000, 1120)))
    assert result["metrics"]["gap_count"] == 1
    assert result["metrics"]["largest_gap_seconds"] == 1210.0


def test_a_frame_without_raw_samples_says_it_read_the_frame():
    from plantcraft_sdk.methods import LoopDataset

    from linkcraft.methods.cpm import sampling_quality

    stamps = pd.date_range("2026-10-01", periods=30, freq="30s")
    dataset = LoopDataset(loop_id="L", data=pd.DataFrame({"timestamp": stamps, "pv": 1.0}))
    result = sampling_quality.run(
        sampling_quality.SamplingQualityInput(dataset=dataset),
        sampling_quality.SamplingQualityParameters(),
    )
    assert result.metrics["timestamp_source"] == "frame"
    assert result.metrics["median_sample_seconds"] == 30.0


def test_a_healthy_loop_on_the_default_grid_is_not_capped_by_sampling(tmp_path):
    """The default 60 s grid used to cost every loop 60 points here (health at most 40)."""

    runtime = make_runtime(
        tmp_path,
        make_fake(),
        analysis=AnalysisConfig(window_minutes=HOURS * 60, resample_seconds=60),
    )
    try:
        runtime.run_round()
        payload = runtime.monitor.loop_payload("fic-101")
        results = {item["method_id"]: item for item in payload["results"]}
        assert results["sampling_quality"]["metrics"]["median_sample_seconds"] == 10.0
        components = {
            item["method_id"]: item["value"] for item in payload["summary"]["functional_components"]
        }
        assert components["sampling_quality"] == 100.0
    finally:
        runtime.shutdown()
