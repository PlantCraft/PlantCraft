"""Each signal data quality check on a clean signal and on the fault it looks for."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from linkcraft.catalog.signal_checks import CHECKS, parameters_for
from linkcraft.signals.assess import assess, plan
from linkcraft.signals.models import SignalQualitySettings
from tests.signal_plant import base, times

SIGNAL = {"id": "X", "kind": "number", "low": 0.0, "high": 100.0, "roles": [], "settings": {}}


def verdict(values, signal=None, reference=None, settings=None):
    signal = {**SIGNAL, **(signal or {})}
    index = times()
    return assess(
        {
            "signal": signal,
            "values": values,
            "reference": reference,
            "start": index[0],
            "end": index[-1],
            "checks": plan(signal, settings or SignalQualitySettings()),
        }
    )


def result(found, check_id):
    return next(item for item in found["checks"] if item["check"] == check_id)


def test_a_clean_signal_passes_every_check():
    found = verdict(base(1))
    assert found["status"] == "good", found["message"]
    assert found["apt"] is True
    assert found["quality"] >= 90
    assert {item["status"] for item in found["checks"]} <= {"ok", "not_applicable"}


def test_frozen_stretch_is_found_with_its_time():
    values = base(2)
    values.iloc[3000:5000] = values.iloc[3000]
    found = result(verdict(values), "sq_frozen")
    assert found["status"] == "warning"
    assert found["events"][0]["start_time"].startswith(str(values.index[3000].date()))
    assert found["metrics"]["longest_minutes"] == pytest.approx(333.3, abs=1)


def test_a_signal_frozen_most_of_the_window_is_bad():
    values = base(2)
    values.iloc[1000:] = 42.0
    found = verdict(values)
    assert found["status"] == "bad"
    assert found["limiting"] == "sq_frozen"
    assert found["apt"] is False


def test_spikes_are_counted_and_located():
    values = base(3)
    values.iloc[[500, 4400]] += 30.0
    found = result(verdict(values), "sq_spikes")
    assert found["metrics"]["spike_count"] == 2
    assert len(found["events"]) == 2
    assert found["status"] == "warning"


def test_a_step_change_is_not_a_spike():
    values = base(3)
    values.iloc[4000:] += 20.0
    assert result(verdict(values), "sq_spikes")["metrics"]["spike_count"] == 0


def test_a_gap_lowers_coverage():
    values = base(4)
    values = values.drop(values.index[2000:2600])
    found = result(verdict(values), "sq_availability")
    assert found["metrics"]["gap_count"] == 1
    assert 0.9 < found["metrics"]["coverage"] < 0.95
    assert found["status"] == "warning"


def test_no_samples_at_all_is_bad_not_a_crash():
    found = verdict(pd.Series(dtype=float))
    assert found["status"] == "bad"
    assert found["limiting"] in ("sq_availability", "sq_freshness")
    assert found["apt"] is False


def test_a_stale_signal_is_bad():
    values = base(5).iloc[:-1200]
    found = verdict(values)
    assert result(found, "sq_freshness")["status"] == "bad"
    assert found["status"] == "bad"


def test_out_of_range_uses_the_limits_and_the_signal_override():
    values = base(6, level=101.0)
    assert result(verdict(values), "sq_range")["status"] == "bad"
    widened = verdict(values, {"settings": {"high": 120.0}})
    assert result(widened, "sq_range")["status"] == "ok"


def test_without_limits_range_and_noise_do_not_judge():
    found = verdict(base(1), {"low": None, "high": None})
    assert result(found, "sq_range")["status"] == "not_applicable"
    assert result(found, "sq_noise")["status"] == "not_applicable"
    assert found["status"] == "good"


def test_noise_against_the_range():
    values = base(7) + np.random.default_rng(1).normal(0, 4.0, len(times()))
    assert result(verdict(values), "sq_noise")["status"] == "bad"


def test_coarse_steps_are_a_resolution_problem_not_a_frozen_sensor():
    values = (base(8) / 5.0).round(0) * 5.0
    found = verdict(values)
    assert result(found, "sq_frozen")["status"] == "not_applicable"
    assert result(found, "sq_resolution")["status"] in ("warning", "bad")


def test_interpolated_compressed_data_is_found():
    values = base(8)
    kept = values.iloc[::60]
    rebuilt = kept.reindex(values.index).interpolate()
    assert result(verdict(rebuilt), "sq_resolution")["status"] == "bad"


def test_drift_against_a_reference_is_bad_and_without_one_not_judged():
    reference = base(9)
    drifting = reference + np.linspace(0.0, 9.0, len(reference))
    assert result(verdict(drifting, reference=reference), "sq_drift")["status"] == "bad"
    steady_ramp = pd.Series(np.linspace(20, 80, len(reference)), index=reference.index)
    alone = result(
        verdict(steady_ramp + np.random.default_rng(3).normal(0, 0.2, len(reference))), "sq_drift"
    )
    assert alone["status"] == "not_applicable"
    assert alone["metrics"]["trend"] is True


def test_text_signals_get_only_availability_and_freshness():
    labels = pd.Series(["AUTO"] * len(times()), index=times())
    found = verdict(labels, {"kind": "text", "low": None, "high": None})
    assert [item["check"] for item in found["checks"]] == ["sq_availability", "sq_freshness"]
    assert found["status"] == "good"


def test_setpoints_skip_the_frozen_check_unless_switched_on():
    constant = pd.Series(50.0, index=times())
    assert verdict(constant, {"roles": ["sp"]})["status"] == "good"
    forced = verdict(constant, {"roles": ["sp"], "settings": {"checks_on": ["sq_frozen"]}})
    assert forced["limiting"] == "sq_frozen"


def test_a_signal_can_switch_a_check_off_and_change_its_parameters():
    values = base(2)
    values.iloc[3000:5000] = values.iloc[3000]
    off = verdict(values, {"settings": {"checks_off": ["sq_frozen"]}})
    assert "sq_frozen" not in [item["check"] for item in off["checks"]]
    longer = verdict(values, {"settings": {"parameters": {"sq_frozen": {"min_minutes": 600}}}})
    assert result(longer, "sq_frozen")["status"] == "ok"


def test_bad_parameters_fall_back_to_the_defaults():
    merged = parameters_for("sq_frozen", {"min_minutes": -5, "unknown": 1}, {"tolerance": "x"})
    assert merged == parameters_for("sq_frozen")


def test_admin_can_switch_checks_off_for_every_signal():
    found = verdict(base(1), settings=SignalQualitySettings(enabled_checks=["sq_availability"]))
    assert [item["check"] for item in found["checks"]] == ["sq_availability"]


@pytest.mark.parametrize("check_id", list(CHECKS))
def test_every_check_explains_itself(check_id):
    block = CHECKS[check_id]
    assert block.metadata.description
    assert block.metadata.implemented_formula
    assert callable(getattr(block, "describe", None))


def test_a_step_into_a_frozen_stretch_is_not_a_spike():
    values = base(2)
    values.iloc[3000:5000] = values.iloc[3000]
    assert result(verdict(values), "sq_spikes")["metrics"]["spike_count"] == 0


# Laboratory analyses: a sample every 4 h, the last one an hour before the window ends.
def lab_samples(values=None):
    index = times()
    stamps = pd.date_range(end=index[-1] - pd.Timedelta(hours=1), start=index[0], freq="4h")
    found = values if values is not None else [50.0 + (i % 3) * 0.5 for i in range(len(stamps))]
    return pd.Series(found[: len(stamps)], index=stamps[: len(found)])


def lab_verdict(values, signal=None, settings=None):
    signal = {**SIGNAL, **(signal or {})}
    index = times()
    return assess(
        {
            "signal": signal,
            "values": values,
            "reference": None,
            "start": index[0],
            "end": index[-1],
            "checks": plan(signal, settings or SignalQualitySettings(), values),
        }
    )


def test_lab_analyses_are_not_judged_as_a_process_signal():
    samples = lab_samples()
    as_process = lab_verdict(samples, {"settings": {"sampling": "continuous"}})
    assert result(as_process, "sq_availability")["status"] == "bad"
    found = lab_verdict(samples, {"source_kind": "csv"})
    checks = [item["check"] for item in found["checks"]]
    assert not {"sq_frozen", "sq_noise", "sq_resolution"} & set(checks)
    assert {"sq_range", "sq_spikes", "sq_freshness", "sq_availability"} <= set(checks)
    assert found["status"] == "good", found["message"]


def test_a_signal_marked_lab_by_hand_is_sampled_whatever_its_source():
    found = lab_verdict(lab_samples(), {"source_kind": "opcua", "settings": {"sampling": "lab"}})
    assert found["status"] == "good", found["message"]


def test_a_lab_signal_late_against_its_interval_is_stale():
    samples = lab_samples().iloc[:-2]  # two analyses missed: the last is 9 h old
    found = lab_verdict(samples, {"source_kind": "csv"})
    assert result(found, "sq_freshness")["status"] in ("warning", "bad")
    hourly = lab_verdict(
        samples, {"source_kind": "csv", "settings": {"sample_interval_minutes": 60}}
    )
    assert result(hourly, "sq_freshness")["status"] == "bad"


def test_a_lab_signal_still_gets_range_and_jumps():
    values = [50.0] * 6
    values[3] = 250.0
    found = lab_verdict(lab_samples(values), {"source_kind": "csv"})
    assert result(found, "sq_range")["status"] in ("warning", "bad")
    assert found["status"] != "good"


def test_a_lab_signal_can_switch_the_frozen_check_back_on():
    signal = {"source_kind": "csv", "settings": {"checks_on": ["sq_frozen"]}}
    checks = [check_id for check_id, _ in plan({**SIGNAL, **signal}, SignalQualitySettings())]
    assert "sq_frozen" in checks
    assert "sq_noise" not in checks


def test_a_csv_source_signal_is_sampled_once_synced(tmp_path):
    from linkcraft.db import Database
    from linkcraft.signals.assess import is_sampled
    from linkcraft.signals.store import SignalStore

    store = SignalStore(Database(tmp_path / "link.db"))
    store.sync(
        [
            {"id": "lab:VISC", "name": "Viscosity", "source": "lab", "source_kind": "csv"},
            {"id": "plant:FI-1", "name": "Flow", "source": "plant", "source_kind": "opcua"},
        ],
        {},
    )
    assert is_sampled(store.get("lab:VISC")) is True
    assert is_sampled(store.get("plant:FI-1")) is False
    # An older database gains the column in place.
    assert SignalStore(Database(tmp_path / "link.db")).get("lab:VISC")["source_kind"] == "csv"
