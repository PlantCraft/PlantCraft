"""A signal against the laboratory (A5): the health, the bias, results counted from approval."""

from __future__ import annotations

import numpy as np
import pandas as pd

from linkcraft.signals.lab import against_lab


def _analyzer(hours: int = 48):
    index = pd.date_range("2026-10-29", periods=hours * 60, freq="1min")
    rng = np.random.default_rng(5)
    true = 10 + np.sin(np.arange(len(index)) / 200.0)
    drift = np.linspace(0, 1.5, len(index))
    online = pd.Series(true + drift + 0.02 * rng.standard_normal(len(index)), index)
    rows = []
    for k in range(0, len(index), 120):  # a sample every 2 h, approved 1 h later
        rows.append(
            {
                "sampled_at": index[k].tz_localize("UTC").isoformat(),
                "value": float(true[k]),
                "status": "approved",
                "approved_at": (index[k] + pd.Timedelta(hours=1)).tz_localize("UTC").isoformat(),
            }
        )
    return online, rows, true


def test_the_corrected_value_is_healthier_than_the_drifting_one():
    online, rows, _true = _analyzer()
    out = against_lab(online, rows)
    assert out["used"] == len(rows)
    assert out["health_corrected"] > out["health"]
    assert 1.0 < out["bias"] < 2.0
    late = out["samples"][len(rows) // 2 :]
    assert np.mean([abs(item["corrected"] - item["lab"]) for item in late]) < 0.2
    assert np.mean([abs(item["online"] - item["lab"]) for item in late]) > 1.0
    assert len(out["corrected"]["t"]) <= 2100
    # Nothing is corrected before the first approval, an hour after the first sample.
    assert out["samples"][0]["corrected"] == out["samples"][0]["online"]


def test_rejected_and_pending_results_do_not_correct():
    online, rows, _true = _analyzer()
    rows[3]["status"] = "rejected"
    rows[4]["status"] = "entered"
    rows[4]["approved_at"] = None
    out = against_lab(online, rows)
    assert out["used"] == len(rows) - 2
    statuses = [item["status"] for item in out["samples"]]
    assert statuses.count("rejected") == 1 and statuses.count("entered") == 1


def test_too_little_data_is_empty():
    out = against_lab(pd.Series(dtype=float), [])
    assert out["samples"] == [] and out["health"] is None


def test_the_api_reads_the_reference_as_the_lab(checked, sq_client):
    signal = "historian:TI-108A.PV"
    path = f"/link/api/signals/{signal}"
    assert sq_client.get(f"{path}/lab").status_code == 404  # no reference yet
    assert sq_client.patch(path, json={"reference": "historian:TI-108B.PV"}).status_code == 200
    window = sq_client.get(f"{path}/data").json()
    out = sq_client.get(f"{path}/lab", params={"end": window["end"], "days": 1}).json()
    assert out["reference"] == "historian:TI-108B.PV" and out["timed"] is False
    assert out["samples"] and out["used"] > 0
    assert out["health"] is not None
    assert sq_client.get(f"{path}/lab", params={"end": "no"}).status_code == 422


def test_a_continuous_reference_is_read_one_value_in_n():
    from linkcraft.signals.lab import MAX_RESULTS, results_from_series

    index = pd.date_range("2026-10-29", periods=5000, freq="1s")
    assert len(results_from_series(pd.Series(np.arange(5000.0), index))) <= MAX_RESULTS
