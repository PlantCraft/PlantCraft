from datetime import UTC, datetime
from math import isfinite

import pytest

from simcraft import PlantSimulator, load_catalog
from simcraft.engine import SUPPORTED_SCENARIOS


def test_simulation_is_bitwise_reproducible_for_same_inputs() -> None:
    first = PlantSimulator(seed=17)
    second = PlantSimulator(seed=17)

    for step in (1, 9, 30, 120, 600):
        left = first.advance(step)
        right = second.advance(step)
        assert left == right
        assert left.state_digest == right.state_digest


def test_different_seeds_change_measurements_not_catalog() -> None:
    first = PlantSimulator(seed=17)
    second = PlantSimulator(seed=18)

    left = first.advance(30)
    right = second.advance(30)
    assert left.state_digest != right.state_digest
    assert first.catalog.digest == second.catalog.digest


def test_explicit_scenario_selection_is_deterministic_and_isolated() -> None:
    default = PlantSimulator(seed=17, scenario_cycle_seconds=600)
    explicit = PlantSimulator(
        seed=17,
        scenario_cycle_seconds=600,
        enabled_scenarios=set(SUPPORTED_SCENARIOS),
    )
    assert default.advance(180) == explicit.advance(180)

    isolated = PlantSimulator(
        seed=17,
        scenario_cycle_seconds=600,
        enabled_scenarios={"sensor.noise"},
    )
    frame = isolated.advance(180)
    truth = isolated.truth_state()
    assert any(
        state["scenario_id"] == "sensor.noise" and state["scenario_active"]
        for state in truth.values()
    )
    assert all(
        not state["scenario_active"]
        for state in truth.values()
        if state["scenario_id"] != "sensor.noise"
    )
    assert all(not state["load_change_active"] for state in truth.values())
    assert {event.scenario_id for event in frame.truth_events} <= {"sensor.noise"}


def test_unknown_scenario_selection_fails_before_simulation() -> None:
    with pytest.raises(ValueError, match="unknown enabled scenarios"):
        PlantSimulator(enabled_scenarios={"unknown.scenario"})


def test_isolated_process_interaction_excites_declared_source_loops_only() -> None:
    simulator = PlantSimulator(
        seed=17,
        scenario_cycle_seconds=600,
        enabled_scenarios={"process.interaction"},
    )
    simulator.advance(180)
    truth = simulator.truth_state()
    source_ids = set(simulator._interaction_source_targets)

    assert source_ids == {"FIC-207", "PIC-402", "FIC-301", "FIC-901"}
    assert all(float(truth[loop_id]["setpoint_normalized"]) != 0.55 for loop_id in source_ids)
    assert all(not state["load_change_active"] for state in truth.values())


def test_values_are_typed_finite_and_bounded_by_extended_model_domain() -> None:
    simulator = PlantSimulator(seed=7)
    frame = simulator.advance(1_000)

    assert frame.observations
    for observation in frame.observations:
        if isinstance(observation.value, float):
            assert isfinite(observation.value)
    for state in simulator.truth_state().values():
        assert -0.05 <= float(state["true_pv_normalized"]) <= 1.05
        assert -0.05 <= float(state["measured_pv_normalized"]) <= 1.05
        assert 0.0 <= float(state["controller_output_normalized"]) <= 1.0
        assert 0.0 <= float(state["actuator_position_normalized"]) <= 1.0
    assert all(
        len(simulator._state[loop_id].process_history)
        <= int(retention / simulator.integration_step_seconds) + 2
        for loop_id, retention in simulator._process_history_retention.items()
    )


def test_fault_truth_is_separate_from_observations() -> None:
    simulator = PlantSimulator(
        seed=5,
        start_at=datetime(2026, 1, 1, tzinfo=UTC),
        scenario_cycle_seconds=3_600,
    )
    frame = simulator.advance(1_100)
    truth = simulator.truth_state()

    assert truth["LIC-103"]["scenario_active"] is True
    assert truth["LIC-205"]["mode"] == "MAN"
    assert not any(
        "scenario" in observation.signal_id.lower() for observation in frame.observations
    )
    assert not any("truth" in observation.node_id.lower() for observation in frame.observations)


def test_sluggish_tuning_has_a_repeatable_setpoint_excitation() -> None:
    simulator = PlantSimulator(
        seed=5,
        scenario_cycle_seconds=3_600,
        enabled_scenarios=("control.sluggish_tuning",),
    )
    loop = next(item for item in simulator.catalog.loops if item.loop_id == "TIC-204")

    inactive = simulator._setpoint(loop, False, 0.30)
    active = simulator._setpoint(loop, True, 0.30)

    assert active - inactive == pytest.approx(0.06)


def test_data_failure_scenarios_affect_transport_semantics() -> None:
    simulator = PlantSimulator(seed=5, scenario_cycle_seconds=3_600)
    frame = simulator.advance(1_110)
    by_loop = {
        loop.loop_id: {
            signal.signal_id
            for signal in simulator.catalog.signals
            if signal.loop_id == loop.loop_id
        }
        for loop in simulator.catalog.loops
    }
    observed = {item.signal_id for item in frame.observations}

    assert not (by_loop["AIC-105"] & observed)
    bad_ids = by_loop["PIC-605"] & observed
    assert bad_ids
    assert all(item.quality == "BAD" for item in frame.observations if item.signal_id in bad_ids)


def test_coupling_graph_is_sparse_directed_and_crosses_plant_areas() -> None:
    simulator = PlantSimulator()
    catalog = load_catalog()
    areas = {loop.loop_id: loop.area_code for loop in catalog.loops}

    assert 40 <= len(simulator.coupling_edges) < 100
    assert any(
        areas[edge.source_loop_id] != areas[edge.target_loop_id]
        for edge in simulator.coupling_edges
    )
    assert all(abs(edge.gain) <= 0.1 for edge in simulator.coupling_edges)
    assert all(edge.delay_seconds > 0 for edge in simulator.coupling_edges)


def test_every_declared_scenario_has_an_implementation_path() -> None:
    catalog = load_catalog()
    assert {item.scenario_id for item in catalog.scenarios} == SUPPORTED_SCENARIOS
