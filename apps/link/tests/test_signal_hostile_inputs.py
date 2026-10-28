"""Bad data never crashes: every signal data quality check, fed with junk.

A check facing NaN, gaps, constant or empty signals, infinities, shuffled or
duplicated timestamps, text where numbers belong or numbers where text
belongs returns a verdict (insufficient data, not applicable or a finding),
never raises. (The API routes, these included, are in ``test_hostile_inputs.py``.)
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from linkcraft.catalog.signal_checks import CHECKS, default_parameters
from linkcraft.signals.assess import _check_result, dataset_for

N = 400
START = pd.Timestamp("2026-01-01")
END = START + pd.Timedelta(seconds=10 * (N - 1))


def _series(values, index=None) -> pd.Series:
    return pd.Series(
        values,
        index=index if index is not None else pd.date_range(START, periods=len(values), freq="10s"),
    )


def _hostile() -> dict[str, pd.Series]:
    ramp = np.linspace(40, 60, N)
    infinite = ramp.copy()
    infinite[5:15] = np.inf
    infinite[20:25] = -np.inf
    gappy = ramp.copy()
    gappy[10:390] = np.nan
    shuffled = _series(ramp).sample(frac=1.0, random_state=1)
    same_time = _series(ramp, pd.DatetimeIndex([START] * N))
    return {
        "empty": pd.Series(dtype=float),
        "one_sample": _series([50.0]),
        "two_samples": _series([50.0, 51.0]),
        "all_nan": _series(np.full(N, np.nan)),
        "constant": _series(np.full(N, 50.0)),
        "huge_spikes": _series(np.where(np.arange(N) % 7 == 0, 1e12, ramp)),
        "infinities": _series(infinite),
        "mostly_gaps": _series(gappy),
        "negative_huge": _series(-1e15 * np.ones(N)),
        "text_in_numbers": _series(np.array(["?", None, 3, "MAN"] * (N // 4), dtype=object)),
        "shuffled_time": shuffled,
        "same_timestamp": same_time,
        "outside_window": _series(ramp, pd.date_range("2020-01-01", periods=N, freq="10s")),
        "tiny_values": _series(1e-300 * np.arange(N)),
        "alternating": _series(np.where(np.arange(N) % 2 == 0, 0.0, 100.0)),
    }


SERIES = _hostile()
SIGNALS = {
    "number": {"id": "H", "kind": "number", "low": 0.0, "high": 100.0},
    "no_limits": {"id": "H", "kind": "number", "low": None, "high": None},
    "text": {"id": "H", "kind": "text", "low": "junk", "high": float("nan")},
}


@pytest.mark.parametrize("signal_kind", sorted(SIGNALS))
@pytest.mark.parametrize("series_name", sorted(SERIES))
@pytest.mark.parametrize("check_id", sorted(CHECKS))
def test_checks_survive_hostile_data(check_id, series_name, signal_kind):
    signal = SIGNALS[signal_kind]
    dataset = dataset_for(signal, SERIES[series_name], START, END, SERIES["shuffled_time"])
    result = _check_result(check_id, default_parameters(check_id), dataset, False)
    assert result["status"] in ("ok", "warning", "bad", "not_applicable", "insufficient_data")
    assert not result["message"].startswith("The check failed"), result["message"]
    assert math.isfinite(result["score"]) and 0 <= result["score"] <= 100
    assert isinstance(result["message"], str)
