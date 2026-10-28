"""The data quality gate decides whether CPM methods may run."""

from __future__ import annotations

import numpy as np
import pandas as pd
from plantcraft_sdk.methods import LoopDataset

from linkcraft.methods.quality import availability, value_integrity


def _dataset(raw: pd.DataFrame, start, end) -> LoopDataset:
    return LoopDataset(
        loop_id="L1",
        data=raw.reset_index(names="timestamp"),
        raw=raw,
        start_time=str(start),
        end_time=str(end),
    )


def test_availability_counts_long_gaps_only():
    index = pd.date_range("2026-01-01", periods=480, freq="30s")
    raw = pd.DataFrame({"pv": np.random.default_rng(1).normal(50, 1, len(index))}, index=index)
    raw = raw.drop(raw.index[100:340])  # a two-hour hole in a four-hour window
    result = availability.run(
        availability.AvailabilityInput(dataset=_dataset(raw, index[0], index[-1])),
        availability.AvailabilityParameters(max_gap_seconds=600, min_coverage=0.8),
    )
    assert result.metrics["apt"] is False
    assert 0.45 < result.metrics["coverage_pv"] < 0.55
    assert result.metrics["largest_gap_seconds_pv"] > 7000


def test_compressed_history_with_short_gaps_is_available():
    index = pd.date_range("2026-01-01", periods=60, freq="4min")
    raw = pd.DataFrame({"pv": np.linspace(10, 12, len(index))}, index=index)
    result = availability.run(
        availability.AvailabilityInput(dataset=_dataset(raw, index[0], index[-1])),
        availability.AvailabilityParameters(),
    )
    assert result.metrics["apt"] is True
    assert result.metrics["coverage_pv"] == 1.0


def test_frozen_pv_is_not_apt():
    index = pd.date_range("2026-01-01", periods=240, freq="30s")
    raw = pd.DataFrame({"pv": [42.0] * 240}, index=index)
    result = value_integrity.run(
        value_integrity.ValueIntegrityInput(dataset=_dataset(raw, index[0], index[-1])),
        value_integrity.ValueIntegrityParameters(),
    )
    assert result.metrics["apt"] is False
    assert result.metrics["frozen_fraction"] > 0.99


def test_cpm_methods_do_not_run_on_data_the_gate_rejects(analysed):
    # TIC-104's transmitter is frozen (tests/plant.py).
    payload = analysed.monitor.loop_payload("tic-104")
    assert payload["summary"]["data_quality"]["apt"] is False
    assert payload["summary"]["status"] == "no_data"
    # Sampling quality reads the samples as recorded, beside the gate: it judges the recording.
    cpm = [
        item
        for item in payload["results"]
        if not item["method_id"].startswith("dq_") and item["method_id"] != "sampling_quality"
    ]
    assert cpm and all(item["status"] == "insufficient_data" for item in cpm)
    assert all(item["message"].startswith("Not run: data not usable.") for item in cpm)
