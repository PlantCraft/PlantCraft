"""The CPM methods: registry, contracts and known answers on synthetic data."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from plantcraft_sdk.methods import LoopDataset, MethodStatus
from plantcraft_sdk.methods.utils import autocorrelation_peak

from linkcraft.catalog.registry import METHOD_SPECS, group_catalog, list_method_specs
from linkcraft.methods.cpm import (
    attenuation,
    error_metrics,
    interaction_correlation,
    interventions,
    manual_mode,
    operating_band,
    oscillation,
    sampling_quality,
    saturation,
    sensor_noise,
    setpoint_activity,
    stiction,
    valve_travel,
    variability,
)


def make_dataset() -> LoopDataset:
    n = 240
    t = np.arange(n)
    timestamps = pd.date_range("2026-01-01", periods=n, freq="10s")
    pv = 50 + np.sin(2 * np.pi * t / 30) + 0.05 * np.sin(2 * np.pi * t / 3)
    sp = np.full(n, 50.0)
    sp[80:120] = 50.5
    op = 45 + 5 * np.sin(2 * np.pi * t / 30)
    op[30:35] = 100
    op[140:150] = 0
    mode = np.array(["auto"] * n, dtype=object)
    mode[40:60] = "manual"
    neighbor_pv = np.roll(pv, 4)
    data = pd.DataFrame(
        {
            "timestamp": timestamps,
            "pv": pv,
            "sp": sp,
            "op": op,
            "mode": mode,
            "neighbor_pv": neighbor_pv,
        }
    )
    return LoopDataset(loop_id="FIC-101", data=data, sample_time_seconds=10.0)


def assert_executable_result(result):
    assert result.loop_id == "FIC-101"
    assert result.method_id
    assert 0 <= result.score <= 100
    assert result.status in MethodStatus
    assert result.references


def test_registry_exposes_all_expected_methodology_blocks():
    specs = list_method_specs("cpm")
    expected = {
        "error_metrics_basic",
        "operational_interventions",
        "disturbance_attenuation",
        "operating_band_fraction",
        "sampling_quality",
        "pv_variability",
        "manual_mode_fraction",
        "op_saturation_fraction",
        "setpoint_activity",
        "oscillation_autocorrelation",
        "sensor_noise_ratio",
        "op_travel_reversal",
        "stiction_screening",
        "interaction_cross_correlation",
        "harris_index",
    }
    data_quality = {"dq_availability", "dq_value_integrity", "dq_statistics"}
    assert {spec.method_id for spec in specs} == expected
    assert {spec.method_id for spec in list_method_specs("data_quality")} == data_quality
    assert set(METHOD_SPECS) == expected | data_quality
    groups = {item["group_id"]: item for item in group_catalog()}
    assert groups["data_quality"]["role"] == "gate"
    assert groups["cpm"]["method_count"] == len(expected)
    for spec in specs:
        assert spec.input_ports
        assert spec.output_ports
        assert spec.metadata.references


def test_all_methodology_blocks_run_on_synthetic_dataset():
    dataset = make_dataset()
    calls = [
        (
            error_metrics.run,
            error_metrics.ErrorMetricsInput(dataset=dataset),
            error_metrics.ErrorMetricsParameters(),
        ),
        (
            interventions.run,
            interventions.InterventionInput(dataset=dataset),
            interventions.InterventionParameters(),
        ),
        (
            attenuation.run,
            attenuation.AttenuationInput(dataset=dataset),
            attenuation.AttenuationParameters(),
        ),
        (
            operating_band.run,
            operating_band.OperatingBandInput(dataset=dataset),
            operating_band.OperatingBandParameters(),
        ),
        (
            sampling_quality.run,
            sampling_quality.SamplingQualityInput(dataset=dataset),
            sampling_quality.SamplingQualityParameters(),
        ),
        (
            variability.pv_variability.run,
            variability.pv_variability.input_schema(dataset=dataset),
            variability.pv_variability.parameter_schema(),
        ),
        (
            manual_mode.run,
            manual_mode.ManualModeInput(dataset=dataset),
            manual_mode.ManualModeParameters(),
        ),
        (
            saturation.run,
            saturation.SaturationInput(dataset=dataset),
            saturation.SaturationParameters(),
        ),
        (
            setpoint_activity.run,
            setpoint_activity.SetpointActivityInput(dataset=dataset),
            setpoint_activity.SetpointActivityParameters(),
        ),
        (
            oscillation.run,
            oscillation.OscillationInput(dataset=dataset),
            oscillation.OscillationParameters(),
        ),
        (
            sensor_noise.run,
            sensor_noise.SensorNoiseInput(dataset=dataset),
            sensor_noise.SensorNoiseParameters(),
        ),
        (
            valve_travel.run,
            valve_travel.ValveTravelInput(dataset=dataset),
            valve_travel.ValveTravelParameters(),
        ),
        (stiction.run, stiction.StictionInput(dataset=dataset), stiction.StictionParameters()),
        (
            interaction_correlation.run,
            interaction_correlation.InteractionCorrelationInput(
                dataset=dataset, secondary_column="neighbor_pv"
            ),
            interaction_correlation.InteractionCorrelationParameters(),
        ),
    ]

    for run, input_data, parameters in calls:
        result = run(input_data, parameters)
        assert_executable_result(result)


def test_missing_required_signal_returns_insufficient_data():
    data = pd.DataFrame(
        {"timestamp": pd.date_range("2026-01-01", periods=3, freq="10s"), "pv": [1.0, 2.0, 3.0]}
    )
    dataset = LoopDataset(loop_id="FIC-101", data=data, sample_time_seconds=10.0)
    output = error_metrics.run(
        error_metrics.ErrorMetricsInput(dataset=dataset), error_metrics.ErrorMetricsParameters()
    )
    assert output.status == MethodStatus.INSUFFICIENT_DATA
    assert output.evidence


def test_interaction_without_secondary_signal_is_insufficient_not_an_error():
    dataset = LoopDataset(
        loop_id="FIC-101",
        data=pd.DataFrame(
            {
                "timestamp": pd.date_range(
                    "2026-01-01",
                    periods=3,
                    freq="10s",
                ),
                "pv": [1.0, 2.0, 3.0],
            }
        ),
        sample_time_seconds=10.0,
    )

    output = interaction_correlation.run(
        interaction_correlation.InteractionCorrelationInput(dataset=dataset),
        interaction_correlation.InteractionCorrelationParameters(),
    )

    assert output.status == MethodStatus.INSUFFICIENT_DATA
    assert output.evidence[0].value == "secondary"


def test_autocorrelation_requires_a_local_periodic_peak():
    periodic = np.sin(2 * np.pi * np.arange(600) / 30)
    smooth_trend = np.linspace(0.0, 1.0, 600)

    periodic_peak, periodic_lag = autocorrelation_peak(
        periodic,
        min_lag=3,
        max_lag=120,
    )
    trend_peak, trend_lag = autocorrelation_peak(
        smooth_trend,
        min_lag=3,
        max_lag=120,
    )

    assert periodic_peak > 0.8
    assert periodic_lag == 30
    assert trend_peak == 0.0
    assert trend_lag is None


def test_tracking_metrics_expose_functional_components():
    dataset = make_dataset()
    error = error_metrics.run(
        error_metrics.ErrorMetricsInput(dataset=dataset),
        error_metrics.ErrorMetricsParameters(acceptable_band=0.5),
    )
    intervention = interventions.run(
        interventions.InterventionInput(dataset=dataset),
        interventions.InterventionParameters(reference_hours=12.0),
    )

    assert error.metrics["itae"] > error.metrics["iae"]
    assert 0.0 <= error.metrics["within_band_fraction"] <= 1.0
    assert error.metrics["performance_component"] == 100.0 - error.score
    assert intervention.metrics["sp_changes"] == 2
    assert intervention.metrics["mode_switches"] == 2
    assert 0.0 <= intervention.metrics["performance_component"] <= 100.0


def test_surge_drum_methods_measure_attenuation_and_operating_band():
    timestamps = pd.date_range("2026-01-01", periods=5, freq="10s")
    dataset = LoopDataset(
        loop_id="LIC-5001",
        data=pd.DataFrame(
            {
                "timestamp": timestamps,
                "pv": [50.0, 55.0, 50.0, 45.0, 50.0],
                "op": [50.0, 51.0, 50.0, 49.0, 50.0],
            }
        ),
        sample_time_seconds=10.0,
        metadata={"loop_type": "level"},
    )
    attenuation_result = attenuation.run(
        attenuation.AttenuationInput(dataset=dataset),
        attenuation.AttenuationParameters(),
    )
    band_result = operating_band.run(
        operating_band.OperatingBandInput(dataset=dataset),
        operating_band.OperatingBandParameters(lower_limit=20.0, upper_limit=80.0),
    )
    sampling_result = sampling_quality.run(
        sampling_quality.SamplingQualityInput(dataset=dataset),
        sampling_quality.SamplingQualityParameters(recommended_sample_seconds=10.0),
    )

    assert attenuation_result.metrics["amplification_factor"] == pytest.approx(0.2)
    assert attenuation_result.metrics["performance_component"] == 100.0
    assert band_result.metrics["inside_fraction"] == 1.0
    assert band_result.metrics["performance_component"] == 100.0
    assert sampling_result.metrics["median_sample_seconds"] == 10.0
    assert sampling_result.metrics["performance_component"] == 100.0


def _surge_window(loop_type: str | None) -> LoopDataset:
    timestamps = pd.date_range("2026-01-01", periods=5, freq="10s")
    return LoopDataset(
        loop_id="X-1",
        data=pd.DataFrame(
            {
                "timestamp": timestamps,
                "pv": [50.0, 55.0, 50.0, 45.0, 50.0],
                "op": [50.0, 51.0, 50.0, 49.0, 50.0],
            }
        ),
        sample_time_seconds=10.0,
        metadata={"loop_type": loop_type} if loop_type is not None else {},
    )


@pytest.mark.parametrize(
    ("module", "run_input", "params"),
    [
        (attenuation, attenuation.AttenuationInput, attenuation.AttenuationParameters),
        (operating_band, operating_band.OperatingBandInput, operating_band.OperatingBandParameters),
    ],
)
def test_surge_level_methods_do_not_apply_to_other_loops(module, run_input, params):
    """G34: on a flow, pressure or temperature loop they are not applicable, never a zero."""

    for loop_type in ("flow", "pressure", "temperature", "composition", "Flow "):
        found = module.run(run_input(dataset=_surge_window(loop_type)), params())
        assert found.status.value == "not_applicable", loop_type
        assert "must hold its setpoint" in found.message
        assert "performance_component" not in found.metrics
    unknown = module.run(run_input(dataset=_surge_window(None)), params())
    assert unknown.status.value == "not_applicable" and "no loop type" in unknown.message
    # The surge-level protocol says the loop is one; the record still wins when it says otherwise.
    assumed = module.run(run_input(dataset=_surge_window(None)), params(assume_surge_level=True))
    assert assumed.status.value == "ok" and assumed.metrics["performance_component"] == 100.0
    record = module.run(run_input(dataset=_surge_window("flow")), params(assume_surge_level=True))
    assert record.status.value == "not_applicable"
    level = module.run(run_input(dataset=_surge_window("level")), params())
    assert level.status.value == "ok"


def test_operating_band_with_own_limits_applies_to_any_loop():
    """Limits set for the loop make the band a time-in-limits KPI for any loop type."""

    params = operating_band.OperatingBandParameters(lower_limit=48.0, upper_limit=52.0)
    for loop_type in ("flow", "temperature", None):
        found = operating_band.run(
            operating_band.OperatingBandInput(dataset=_surge_window(loop_type)), params
        )
        assert found.status.value != "not_applicable", loop_type
        assert found.metrics["inside_fraction"] == pytest.approx(0.6)
    # A surge-level algorithm keeps the record's say, even with limits.
    surge = operating_band.OperatingBandParameters(
        lower_limit=20.0, upper_limit=80.0, assume_surge_level=True
    )
    found = operating_band.run(
        operating_band.OperatingBandInput(dataset=_surge_window("flow")), surge
    )
    assert found.status.value == "not_applicable"


def _tracking(sp: float, error: float, n: int = 600) -> LoopDataset:
    rng = np.random.default_rng(5)
    noise = rng.normal(0.0, 1.0, n)
    pv = sp + error * noise / np.mean(np.abs(noise))
    return _window(n, pv=pv, sp=np.full(n, sp))


def test_the_error_tolerance_follows_the_loops_scale():
    """G34: the same relative error scores the same on a 500 t/h flow and a 2 bar pressure."""

    params = error_metrics.ErrorMetricsParameters()
    big = error_metrics.run(error_metrics.ErrorMetricsInput(dataset=_tracking(500.0, 5.0)), params)
    small = error_metrics.run(error_metrics.ErrorMetricsInput(dataset=_tracking(2.0, 0.02)), params)
    assert big.metrics["mae"] == pytest.approx(5.0) and small.metrics["mae"] == pytest.approx(0.02)
    assert big.score == pytest.approx(25.0) and small.score == pytest.approx(25.0)  # 1 % of 4 %
    assert big.metrics["tolerance_basis"] == "setpoint" and big.metrics["scale"] == 500.0
    assert big.metrics["error_tolerance"] == pytest.approx(20.0)
    assert big.metrics["acceptable_band"] == pytest.approx(5.0)


def test_an_absolute_tolerance_or_a_span_wins_over_the_setpoint():
    dataset = _tracking(50.0, 0.5)
    absolute = error_metrics.run(
        error_metrics.ErrorMetricsInput(dataset=dataset),
        error_metrics.ErrorMetricsParameters(error_tolerance=5.0, acceptable_band=1.0),
    )
    assert absolute.score == pytest.approx(10.0)
    assert absolute.metrics["tolerance_basis"] == "absolute"
    span = error_metrics.run(
        error_metrics.ErrorMetricsInput(dataset=dataset),
        error_metrics.ErrorMetricsParameters(pv_span=200.0),
    )
    assert span.metrics["tolerance_basis"] == "pv_span" and span.score == pytest.approx(6.25)


def test_a_setpoint_at_zero_falls_back_to_the_absolute_tolerance():
    found = error_metrics.run(
        error_metrics.ErrorMetricsInput(dataset=_tracking(0.0, 0.25)),
        error_metrics.ErrorMetricsParameters(),
    )
    assert found.metrics["tolerance_basis"] == "absolute" and found.metrics["scale"] is None
    assert found.score == pytest.approx(25.0)
    assert found.metrics["mae_percent_of_scale"] is None


def _window(n: int, **columns: np.ndarray) -> LoopDataset:
    timestamps = pd.date_range("2026-01-01", periods=n, freq="10s")
    data = pd.DataFrame({"timestamp": timestamps, **columns})
    return LoopDataset(loop_id="FIC-101", data=data, sample_time_seconds=10.0)


def test_one_setpoint_step_is_not_an_oscillation():
    # G27: the decaying error after one SP step lifts the autocorrelation (peak ~0.4) but its
    # zero crossings are irregular (Thornhill, Huang and Zhang 2003), so it is not flagged.
    n = 2160
    k = np.arange(n)
    rng = np.random.default_rng(3)
    sp = np.where(k < 1800, 55.0, 57.5)
    error = np.zeros(n)
    after = k[1800:] - 1800
    error[1800:] = -2.5 * np.exp(-after / 60) * np.cos(2 * np.pi * after / 70)
    pv = sp + error + 0.05 * rng.normal(size=n) + 0.3 * np.cumsum(rng.normal(size=n)) / np.sqrt(n)
    found = oscillation.run(
        oscillation.OscillationInput(dataset=_window(n, pv=pv, sp=sp), signal="error"),
        oscillation.OscillationParameters(),
    )
    assert found.metrics["autocorrelation_peak"] >= 0.3
    assert found.metrics["regularity"] < 1.0
    assert found.status == MethodStatus.OK
    assert "irregular" in oscillation.describe(found.metrics)


def test_sustained_oscillation_is_regular():
    n = 2160
    k = np.arange(n)
    pv = 50 + 2 * np.sin(2 * np.pi * k / 40) + np.random.default_rng(4).normal(0, 0.1, n)
    found = oscillation.run(
        oscillation.OscillationInput(dataset=_window(n, pv=pv)),
        oscillation.OscillationParameters(),
    )
    assert found.metrics["regularity"] > 1.0
    assert found.metrics["zero_crossing_period_seconds"] == pytest.approx(400, rel=0.05)
    assert found.status == MethodStatus.BAD


def test_continuous_op_swings_are_not_stick_slip():
    # G28: a loop cycling from tuning moves its OP by a large step at every sample; with no
    # stuck sample before the jumps it is not the stick-slip of a sticky valve.
    n = 2160
    k = np.arange(n)
    rng = np.random.default_rng(5)
    op = 50 + 25 * np.sin(2 * np.pi * k / 12) + 0.3 * rng.normal(size=n)
    pv = 52 - 3 * np.sin(2 * np.pi * k / 12) + 0.05 * rng.normal(size=n)
    found = stiction.run(
        stiction.StictionInput(dataset=_window(n, pv=pv, op=op)), stiction.StictionParameters()
    )
    assert found.metrics["op_jump_fraction"] > 0.9
    assert found.metrics["op_slip_fraction"] < 0.05
    assert found.status == MethodStatus.OK


def test_op_pinned_at_a_limit_is_not_screened_as_stiction():
    # G28: an OP held at 100 % is flat because the controller saturates, not because it sticks.
    n = 2160
    k = np.arange(n)
    rng = np.random.default_rng(6)
    pv = 49 + 0.3 * np.sin(2 * np.pi * k / 800) + 0.07 * rng.normal(size=n)
    found = stiction.run(
        stiction.StictionInput(dataset=_window(n, pv=pv, op=np.full(n, 100.0))),
        stiction.StictionParameters(),
    )
    assert found.metrics["op_saturated_fraction"] == 1.0
    assert found.metrics["screened_moves"] == 0
    assert found.status == MethodStatus.NOT_APPLICABLE
    assert "not screened" in stiction.describe(found.metrics)


def test_stick_slip_off_the_limits_is_still_flagged():
    n = 2160
    k = np.arange(n)
    levels = np.concatenate([np.arange(46, 54), np.arange(54, 46, -1)]).astype(float)
    op = levels[(k // 6) % len(levels)]
    pv = 50 + 3 * np.sin(2 * np.pi * k / (6 * len(levels)))
    found = stiction.run(
        stiction.StictionInput(dataset=_window(n, pv=pv, op=op)), stiction.StictionParameters()
    )
    assert found.metrics["op_slip_fraction"] == pytest.approx(1 / 6, abs=0.01)
    assert found.status == MethodStatus.BAD
