from collections import deque
from dataclasses import replace
from math import isfinite

import pytest

from simcraft import PlantSimulator, load_catalog
from simcraft.model import CONTROL_STRUCTURE_POLICIES


def test_every_loop_has_a_complete_inspectable_model_definition() -> None:
    simulator = PlantSimulator()
    definitions = simulator.model_definitions

    assert len(definitions) == 50
    assert {item.loop_id for item in definitions} == {loop.loop_id for loop in load_catalog().loops}
    assert {item.control_structure for item in definitions} == set(CONTROL_STRUCTURE_POLICIES)
    for definition in definitions:
        parameters = definition.parameters
        assert parameters.process_gain > 0
        assert parameters.time_constant_seconds > parameters.dead_time_seconds
        assert parameters.integral_lower_limit < 0 < parameters.integral_upper_limit
        assert parameters.actuator_rate_limit_per_second > 0


def test_every_loop_has_engineering_context_and_positive_step_response() -> None:
    simulator = PlantSimulator(seed=11)

    for loop in simulator.catalog.loops:
        assert loop.process_purpose
        assert loop.controlled_variable
        assert loop.manipulated_variable
        state = simulator._state[loop.loop_id]
        state.delay = deque(((0.0, 0.65),))
        before = state.true_pv
        simulator._advance_loop(loop, 1.0)
        assert state.true_pv > before


def test_unsupported_control_structure_fails_before_simulation() -> None:
    catalog = load_catalog()
    invalid = replace(
        catalog,
        loops=(replace(catalog.loops[0], control_structure="unknown"), *catalog.loops[1:]),
    )

    with pytest.raises(ValueError, match="unsupported control structure"):
        PlantSimulator(catalog=invalid)


def test_control_structures_select_declared_operating_modes() -> None:
    simulator = PlantSimulator(seed=4)
    simulator.advance(1)
    truth = simulator.truth_state()

    for loop in simulator.catalog.loops:
        expected_mode = CONTROL_STRUCTURE_POLICIES[loop.control_structure][0]
        assert truth[loop.loop_id]["mode"] == expected_mode


def test_actuator_rate_integral_and_conservation_invariants() -> None:
    simulator = PlantSimulator(seed=7)
    before = simulator.truth_state()
    simulator.advance(1)
    after = simulator.truth_state()
    definitions = {item.loop_id: item for item in simulator.model_definitions}

    for loop_id, state in after.items():
        parameters = definitions[loop_id].parameters
        actuator_move = abs(
            float(state["actuator_position_normalized"])
            - float(before[loop_id]["actuator_position_normalized"])
        )
        assert actuator_move <= parameters.actuator_rate_limit_per_second + 1e-12
        assert parameters.integral_lower_limit <= float(state["integral_state"])
        assert float(state["integral_state"]) <= parameters.integral_upper_limit
        assert isfinite(float(state["balance_residual"]))
        assert abs(float(state["balance_residual"])) < 1e-12


def test_coupling_uses_declared_transport_delay() -> None:
    simulator = PlantSimulator()
    edge = next(item for item in simulator.coupling_edges if item.delay_seconds == 90.0)
    source = simulator._state[edge.source_loop_id]
    source.process_history = deque(((0.0, 0.55), (10.0, 0.85)))

    simulator.elapsed_seconds = 80.0
    assert simulator._delayed_process(edge.source_loop_id, edge.delay_seconds) == 0.55
    simulator.elapsed_seconds = 100.0
    assert simulator._delayed_process(edge.source_loop_id, edge.delay_seconds) == 0.85


def test_coupling_response_respects_declared_gain_sign() -> None:
    simulator = PlantSimulator()
    positive = next(
        item for item in simulator.coupling_edges if item.mechanism == "feed_to_distillation"
    )
    negative = next(
        item
        for item in simulator.coupling_edges
        if item.mechanism == "cooling_water_to_column_pressure"
    )
    simulator.elapsed_seconds = 1_000
    for edge in (positive, negative):
        simulator._state[edge.source_loop_id].process_history = deque(((0.0, 0.85),))

    assert simulator._coupling(positive.target_loop_id, False) > 0
    assert simulator._coupling(negative.target_loop_id, False) < 0


def test_manual_mode_tracks_integral_for_bumpless_return() -> None:
    simulator = PlantSimulator(seed=9, scenario_cycle_seconds=600)
    loop_id = "LIC-205"
    was_active = False
    last_manual_output = 0.0

    for _ in range(600):
        simulator.advance(1)
        state = simulator.truth_state()[loop_id]
        active = bool(state["scenario_active"])
        if active:
            last_manual_output = float(state["controller_output_normalized"])
        if was_active and not active:
            first_auto_output = float(state["controller_output_normalized"])
            assert abs(first_auto_output - last_manual_output) < 0.03
            break
        was_active = active
    else:
        raise AssertionError("manual scenario did not complete within one cycle")


def test_stiction_and_saturation_are_explicit_hidden_states() -> None:
    simulator = PlantSimulator(seed=5, scenario_cycle_seconds=3_600)
    simulator.advance(1_100)
    truth = simulator.truth_state()

    assert truth["LIC-103"]["scenario_active"] is True
    assert truth["LIC-103"]["actuator_stuck"] is True
    assert float(truth["FIC-207"]["actuator_position_normalized"]) <= 0.67


def test_sensor_drift_recovers_after_scenario_window() -> None:
    simulator = PlantSimulator(seed=3, scenario_cycle_seconds=3_600)
    simulator.advance(2_400)
    active_bias = abs(float(simulator.truth_state()["TIC-203"]["sensor_bias_normalized"]))
    simulator.advance(900)
    recovered = simulator.truth_state()["TIC-203"]

    assert recovered["scenario_active"] is False
    assert abs(float(recovered["sensor_bias_normalized"])) < active_bias
