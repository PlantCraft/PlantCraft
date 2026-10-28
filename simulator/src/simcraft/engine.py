"""Deterministic plant-wide simulation and observation pipeline."""

from __future__ import annotations

import hashlib
import math
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from .catalog import Catalog, LoopDefinition, SignalDefinition, load_catalog
from .model import (
    CONTROL_STRUCTURE_POLICIES,
    SCENARIO_PARAMETERS,
    CouplingEdge,
    LoopModelDefinition,
    build_coupling_graph,
    model_definition_for,
    parameters_for,
    validate_model,
)

Quality = Literal["GOOD", "UNCERTAIN", "BAD", "BAD_NO_COMMUNICATION"]

SUPPORTED_SCENARIOS = frozenset(
    {
        "normal.steady",
        "normal.load_change",
        "control.aggressive_tuning",
        "control.sluggish_tuning",
        "control.oscillation",
        "control.propagated_oscillation",
        "valve.stiction",
        "valve.backlash",
        "actuator.saturation",
        "operations.manual",
        "operations.setpoint_activity",
        "sensor.noise",
        "sensor.drift",
        "sensor.frozen",
        "data.gap",
        "data.bad_quality",
        "data.communication_loss",
        "data.irregular_cadence",
        "process.disturbance",
        "process.interaction",
    }
)


@dataclass(frozen=True)
class Observation:
    signal_id: str
    node_id: str
    timestamp: datetime
    value: float | str | bool
    quality: Quality
    engineering_unit: str


@dataclass(frozen=True)
class TruthEvent:
    scenario_id: str
    loop_id: str
    cycle: int
    active: bool
    elapsed_seconds: float
    parameters: tuple[tuple[str, float | str], ...] = ()


@dataclass(frozen=True)
class SimulationFrame:
    timestamp: datetime
    observations: tuple[Observation, ...]
    truth_events: tuple[TruthEvent, ...]
    state_digest: str


@dataclass
class _LoopState:
    true_pv: float = 0.55
    measured_pv: float = 0.55
    setpoint: float = 0.55
    integral: float = 0.0
    output: float = 0.50
    actuator: float = 0.50
    mode: str = "AUTO"
    previous_mode: str = "AUTO"
    sensor_bias: float = 0.0
    frozen_measurement: float | None = None
    actuator_stuck: bool = False
    backlash_direction: int = 0
    backlash_remaining: float = 0.0
    balance_residual: float = 0.0
    delay: deque[tuple[float, float]] = field(default_factory=lambda: deque(((0.0, 0.50),)))
    process_history: deque[tuple[float, float]] = field(
        default_factory=lambda: deque(((0.0, 0.55),))
    )


def _stable_fraction(*parts: object) -> float:
    encoded = "|".join(str(part) for part in parts).encode()
    raw = int.from_bytes(hashlib.sha256(encoded).digest()[:8], "big")
    return raw / float(2**64 - 1)


def _gaussian(seed: int, step: int, channel: str) -> float:
    u1 = max(_stable_fraction(seed, step, channel, 1), 1e-12)
    u2 = _stable_fraction(seed, step, channel, 2)
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


def _bounded(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(max(value, low), high)


def _numeric_range(signal: SignalDefinition) -> tuple[float, float]:
    try:
        left, right = signal.normal_range.split("..", 1)
        return float(left), float(right)
    except (TypeError, ValueError):
        return 0.0, 100.0


class PlantSimulator:
    """A reproducible, sparse-coupled, nonlinear grey-box benchmark.

    The process model uses normalized first-order-plus-dead-time states, PI
    controllers with conditional-integration anti-windup, first-order
    actuators, and a sparse directed coupling graph. Measurement and transport
    faults are applied after physical-state integration so hidden truth remains
    distinct from observable data.
    """

    def __init__(
        self,
        *,
        catalog: Catalog | None = None,
        seed: int = 20260903,
        start_at: datetime | None = None,
        integration_step_seconds: float = 1.0,
        scenario_cycle_seconds: float = 21_600.0,
        enabled_scenarios: frozenset[str] | set[str] | tuple[str, ...] | None = None,
    ) -> None:
        self.catalog = catalog or load_catalog()
        errors = self.catalog.validate()
        if errors:
            raise ValueError("invalid catalog: " + "; ".join(errors))
        model_errors = validate_model(self.catalog)
        if model_errors:
            raise ValueError("invalid model: " + "; ".join(model_errors))
        scenario_ids = {item.scenario_id for item in self.catalog.scenarios}
        if scenario_ids != SUPPORTED_SCENARIOS:
            raise ValueError(
                "scenario implementation mismatch: "
                f"missing={sorted(scenario_ids - SUPPORTED_SCENARIOS)}, "
                f"undeclared={sorted(SUPPORTED_SCENARIOS - scenario_ids)}"
            )
        selected_scenarios = (
            SUPPORTED_SCENARIOS if enabled_scenarios is None else frozenset(enabled_scenarios)
        )
        unknown_scenarios = selected_scenarios - SUPPORTED_SCENARIOS
        if unknown_scenarios:
            raise ValueError(f"unknown enabled scenarios: {sorted(unknown_scenarios)}")
        selected_start = start_at or datetime(2026, 1, 1, tzinfo=UTC)
        if selected_start.tzinfo is None or selected_start.utcoffset() is None:
            raise ValueError("start_at must include a UTC offset")
        integration_step = float(integration_step_seconds)
        scenario_cycle = float(scenario_cycle_seconds)
        if not math.isfinite(integration_step) or integration_step <= 0:
            raise ValueError("integration_step_seconds must be finite and positive")
        if not math.isfinite(scenario_cycle) or scenario_cycle < 600:
            raise ValueError("scenario_cycle_seconds must be finite and at least 600")
        self.seed = int(seed)
        self.start_at = selected_start.astimezone(UTC)
        self.integration_step_seconds = integration_step
        self.scenario_cycle_seconds = scenario_cycle
        self.enabled_scenarios = selected_scenarios
        self.elapsed_seconds = 0.0
        self._step_index = 0
        self._loops = {loop.loop_id: loop for loop in self.catalog.loops}
        self._scenario_onset_offsets = {
            loop.loop_id: 0.08 * (_stable_fraction(loop.loop_id, "onset") - 0.5)
            for loop in self.catalog.loops
        }
        self._parameters = {loop.loop_id: parameters_for(loop) for loop in self.catalog.loops}
        self._state = {loop.loop_id: _LoopState() for loop in self.catalog.loops}
        self._edges = build_coupling_graph(self.catalog)
        self._incoming: dict[str, list[CouplingEdge]] = {
            loop.loop_id: [] for loop in self.catalog.loops
        }
        self._interaction_source_targets: dict[str, list[str]] = {}
        self._process_history_retention = {
            loop.loop_id: self.integration_step_seconds for loop in self.catalog.loops
        }
        for edge in self._edges:
            self._incoming[edge.target_loop_id].append(edge)
            self._process_history_retention[edge.source_loop_id] = max(
                self._process_history_retention[edge.source_loop_id],
                edge.delay_seconds,
            )
            if self._loops[edge.target_loop_id].primary_scenario == "process.interaction":
                self._interaction_source_targets.setdefault(edge.source_loop_id, []).append(
                    edge.target_loop_id
                )
        self._signal_by_loop: dict[str, list[SignalDefinition]] = {}
        self._context_signals: list[SignalDefinition] = []
        for signal in self.catalog.signals:
            if signal.scope == "control_loop" and signal.loop_id:
                self._signal_by_loop.setdefault(signal.loop_id, []).append(signal)
            else:
                self._context_signals.append(signal)
        self._last_active: dict[str, bool] = {loop.loop_id: False for loop in self.catalog.loops}
        self._last_load_change = False

    @property
    def coupling_edges(self) -> tuple[CouplingEdge, ...]:
        return self._edges

    @property
    def model_definitions(self) -> tuple[LoopModelDefinition, ...]:
        return tuple(model_definition_for(loop) for loop in self.catalog.loops)

    def _scenario_active(self, loop: LoopDefinition) -> tuple[bool, int, float]:
        cycle = int(self.elapsed_seconds // self.scenario_cycle_seconds)
        phase = (self.elapsed_seconds % self.scenario_cycle_seconds) / self.scenario_cycle_seconds
        offset = self._scenario_onset_offsets[loop.loop_id]
        active = (0.24 + offset) <= phase < (0.72 + offset)
        if (
            loop.primary_scenario == "normal.steady"
            or loop.primary_scenario not in self.enabled_scenarios
        ):
            active = False
        return active, cycle, phase

    def _setpoint(self, loop: LoopDefinition, active: bool, phase: float) -> float:
        value = 0.55
        if loop.loop_id in {
            "FIC-101",
            "FIC-201",
            "FIC-301",
        } and self._load_change_active(phase):
            value += 0.08
        if loop.primary_scenario == "operations.setpoint_activity" and active:
            local = (phase - 0.24) / 0.48
            value += 0.10 * (2.0 * local - 1.0)
        if loop.primary_scenario == "control.sluggish_tuning" and active:
            value += float(SCENARIO_PARAMETERS["control.sluggish_tuning"]["setpoint_step"])
        if loop.primary_scenario == "actuator.saturation" and active:
            value += float(SCENARIO_PARAMETERS["actuator.saturation"]["active_setpoint_step"])
        if self._interaction_source_active(loop.loop_id):
            interaction = SCENARIO_PARAMETERS["process.interaction"]
            value += float(interaction["source_driver_amplitude"]) * math.sin(
                2.0
                * math.pi
                * self.elapsed_seconds
                / float(interaction["source_driver_period_seconds"])
            )
        structure_bias = 0.025 * math.sin(
            2.0 * math.pi * self.elapsed_seconds / self.scenario_cycle_seconds
        )
        _, _, _, bias_scale = CONTROL_STRUCTURE_POLICIES[loop.control_structure]
        value += bias_scale * structure_bias
        return _bounded(value, 0.15, 0.90)

    def _interaction_source_active(self, loop_id: str) -> bool:
        if "process.interaction" not in self.enabled_scenarios:
            return False
        return any(
            self._scenario_active(self._loops[target_loop_id])[0]
            for target_loop_id in self._interaction_source_targets.get(loop_id, ())
        )

    def _load_change_active(self, phase: float) -> bool:
        return "normal.load_change" in self.enabled_scenarios and 0.45 <= phase < 0.68

    def _delayed_actuator(self, state: _LoopState, delay_seconds: float) -> float:
        target_time = self.elapsed_seconds - delay_seconds
        value = state.delay[0][1] if state.delay else state.actuator
        for stamp, candidate in state.delay:
            if stamp > target_time:
                break
            value = candidate
        while len(state.delay) > 2 and state.delay[1][0] < target_time - delay_seconds:
            state.delay.popleft()
        return value

    def _delayed_process(self, loop_id: str, delay_seconds: float) -> float:
        history = self._state[loop_id].process_history
        target_time = self.elapsed_seconds - delay_seconds
        value = history[0][1]
        for stamp, candidate in history:
            if stamp > target_time:
                break
            value = candidate
        return value

    def _coupling(
        self,
        loop_id: str,
        active: bool,
    ) -> float:
        total = 0.0
        for edge in self._incoming[loop_id]:
            gain = edge.gain * (
                2.0
                if active and self._loops[loop_id].primary_scenario == "process.interaction"
                else 1.0
            )
            delayed_source = self._delayed_process(edge.source_loop_id, edge.delay_seconds)
            deviation = delayed_source - 0.55
            if (
                active
                and self._loops[loop_id].primary_scenario == "control.propagated_oscillation"
                and edge.source_loop_id == "FIC-701"
            ):
                parameters = SCENARIO_PARAMETERS["control.propagated_oscillation"]
                source_time = self.elapsed_seconds - edge.delay_seconds
                deviation += float(parameters["source_amplitude"]) * math.sin(
                    2.0 * math.pi * source_time / float(parameters["period_seconds"])
                )
            total += gain * deviation
        return total

    def _advance_loop(
        self,
        loop: LoopDefinition,
        dt: float,
    ) -> None:
        state = self._state[loop.loop_id]
        params = self._parameters[loop.loop_id]
        active, _, phase = self._scenario_active(loop)
        state.setpoint = self._setpoint(loop, active, phase)
        state.previous_mode = state.mode
        default_mode = CONTROL_STRUCTURE_POLICIES[loop.control_structure][0]
        state.mode = (
            "MAN" if loop.primary_scenario == "operations.manual" and active else default_mode
        )

        measurement = state.true_pv
        noise_scale = params.noise_standard_deviation
        if loop.primary_scenario == "sensor.noise" and active:
            noise_scale *= 14.0
        if loop.primary_scenario == "sensor.drift" and active:
            state.sensor_bias += 0.000012 * dt
        else:
            state.sensor_bias *= math.exp(-dt / 1_800.0)
        measurement += state.sensor_bias + noise_scale * _gaussian(
            self.seed, self._step_index, loop.loop_id
        )
        if loop.primary_scenario == "sensor.frozen" and active:
            if state.frozen_measurement is None:
                state.frozen_measurement = state.measured_pv
            measurement = state.frozen_measurement
        else:
            state.frozen_measurement = None
        state.measured_pv = _bounded(measurement, -0.05, 1.05)

        error = state.setpoint - state.measured_pv
        controller_gain = params.controller_gain
        integral_time = params.integral_time_seconds
        if active and loop.primary_scenario in {
            "control.aggressive_tuning",
            "control.sluggish_tuning",
        }:
            tuning = SCENARIO_PARAMETERS[loop.primary_scenario]
            controller_gain *= float(tuning["controller_gain_scale"])
            integral_time *= float(tuning["integral_time_scale"])
        if state.mode == "MAN":
            requested = 0.50 + 0.06 * math.sin(2.0 * math.pi * phase * 3.0)
            state.integral = _bounded(
                requested - 0.50 - controller_gain * error,
                params.integral_lower_limit,
                params.integral_upper_limit,
            )
        else:
            proposed_integral = state.integral + (controller_gain / integral_time) * error * dt
            requested = 0.50 + controller_gain * error + proposed_integral
            if params.lower_limit < requested < params.upper_limit:
                state.integral = _bounded(
                    proposed_integral,
                    params.integral_lower_limit,
                    params.integral_upper_limit,
                )
            if loop.control_structure == "override_selector":
                protective_limit = 0.74 if state.measured_pv > 0.82 else 1.0
                requested = min(requested, protective_limit)
        state.output = _bounded(requested, params.lower_limit, params.upper_limit)

        actuator_target = state.output
        if loop.control_structure == "split_range":
            if actuator_target < 0.48:
                actuator_target = 0.5 * actuator_target / 0.48
            elif actuator_target > 0.52:
                actuator_target = 0.5 + 0.5 * (actuator_target - 0.52) / 0.48
            else:
                actuator_target = 0.50
        if loop.primary_scenario == "actuator.saturation" and active:
            actuator_target = min(actuator_target, 0.67)
        delta = actuator_target - state.actuator
        state.actuator_stuck = False
        if (
            loop.primary_scenario == "valve.stiction"
            and active
            and abs(delta) < params.stiction_band
        ):
            delta = 0.0
            state.actuator_stuck = True
        elif loop.primary_scenario == "valve.backlash" and active:
            direction = 1 if delta > 0 else -1 if delta < 0 else 0
            if direction and direction != state.backlash_direction:
                state.backlash_direction = direction
                state.backlash_remaining = params.backlash_band
            consumed = min(abs(delta), state.backlash_remaining)
            state.backlash_remaining -= consumed
            delta = math.copysign(max(abs(delta) - consumed, 0.0), delta)
        desired_move = dt * delta / params.actuator_time_seconds
        rate_move = params.actuator_rate_limit_per_second * dt
        state.actuator = _bounded(
            state.actuator + _bounded(desired_move, -rate_move, rate_move),
            params.lower_limit,
            params.upper_limit,
        )
        state.delay.append((self.elapsed_seconds + dt, state.actuator))

        delayed = self._delayed_actuator(state, params.dead_time_seconds)
        disturbance = 0.0
        if active and loop.primary_scenario == "control.oscillation":
            disturbance += 0.075 * math.sin(2.0 * math.pi * self.elapsed_seconds / 540.0)
        if active and loop.primary_scenario == "process.disturbance":
            disturbance += 0.085
        coupling = self._coupling(loop.loop_id, active)
        equilibrium = 0.55 + params.process_gain * (delayed - 0.50) + disturbance + coupling
        derivative = (equilibrium - state.true_pv) / params.time_constant_seconds
        previous_pv = state.true_pv
        state.true_pv = _bounded(
            state.true_pv + dt * derivative,
            -0.05,
            1.05,
        )
        actual_derivative = (state.true_pv - previous_pv) / dt
        state.balance_residual = actual_derivative - derivative

    def advance(self, seconds: float) -> SimulationFrame:
        """Advance physical time and return observations due at the final time."""

        remaining = float(seconds)
        if not math.isfinite(remaining) or remaining < 0:
            raise ValueError("seconds must be finite and non-negative")
        transitions: list[TruthEvent] = []
        while remaining > 1e-12:
            dt = min(remaining, self.integration_step_seconds)
            active_before = self._last_active.copy()
            for loop in self.catalog.loops:
                self._advance_loop(loop, dt)
            self.elapsed_seconds += dt
            for loop_id, state in self._state.items():
                state.process_history.append((self.elapsed_seconds, state.true_pv))
                oldest_required = self.elapsed_seconds - self._process_history_retention[loop_id]
                while (
                    len(state.process_history) > 2
                    and state.process_history[1][0] <= oldest_required
                ):
                    state.process_history.popleft()
            self._step_index += 1
            remaining -= dt
            cycle = int(self.elapsed_seconds // self.scenario_cycle_seconds)
            phase = (
                self.elapsed_seconds % self.scenario_cycle_seconds
            ) / self.scenario_cycle_seconds
            load_change = self._load_change_active(phase)
            if load_change != self._last_load_change:
                transitions.extend(
                    TruthEvent(
                        scenario_id="normal.load_change",
                        loop_id=loop_id,
                        cycle=cycle,
                        active=load_change,
                        elapsed_seconds=self.elapsed_seconds,
                    )
                    for loop_id in ("FIC-101", "FIC-201", "FIC-301")
                )
            self._last_load_change = load_change
            for loop in self.catalog.loops:
                active, cycle, _ = self._scenario_active(loop)
                before = active_before[loop.loop_id]
                if active != before:
                    transitions.append(
                        TruthEvent(
                            scenario_id=loop.primary_scenario,
                            loop_id=loop.loop_id,
                            cycle=cycle,
                            active=active,
                            elapsed_seconds=self.elapsed_seconds,
                        )
                    )
                self._last_active[loop.loop_id] = active
        timestamp = self.start_at + timedelta(seconds=self.elapsed_seconds)
        observations = self._observations(timestamp)
        digest_input = "|".join(
            f"{key}:{state.true_pv:.12f}:{state.output:.12f}:{state.actuator:.12f}"
            for key, state in sorted(self._state.items())
        )
        digest = hashlib.sha256(digest_input.encode()).hexdigest()
        return SimulationFrame(timestamp, observations, tuple(transitions), digest)

    def snapshot(self) -> SimulationFrame:
        return self.advance(0.0)

    def _loop_value(self, signal: SignalDefinition) -> float | str:
        assert signal.loop_id is not None
        state = self._state[signal.loop_id]
        suffix = signal.node_identifier.rsplit(".", 1)[-1]
        if suffix == "PV":
            normalized: float | str = state.measured_pv
        elif suffix == "SP":
            normalized = state.setpoint
        elif suffix == "OP":
            normalized = state.output
        elif suffix == "MVFB":
            normalized = state.actuator
        else:
            return state.mode
        low, high = _numeric_range(signal)
        return low + float(normalized) * (high - low)

    def _context_value(self, signal: SignalDefinition) -> float | str | bool:
        related = [self._state[item] for item in signal.context_for_loop_ids if item in self._state]
        normalized = sum(item.true_pv for item in related) / len(related) if related else 0.55
        channel = _stable_fraction(signal.signal_id, self._step_index)
        if signal.data_type == "boolean":
            return normalized > 0.12
        if signal.data_type == "string":
            options = signal.normal_range.split("|")
            return options[0] if options else "NORMAL"
        low, high = _numeric_range(signal)
        shaped = _bounded(normalized + 0.008 * (channel - 0.5))
        return low + shaped * (high - low)

    def _observations(self, timestamp: datetime) -> tuple[Observation, ...]:
        observations: list[Observation] = []
        elapsed = round(self.elapsed_seconds)
        for signal in self.catalog.signals:
            if elapsed and elapsed % signal.nominal_cadence_seconds != 0:
                continue
            loop = self._loops.get(signal.loop_id or "")
            active = self._scenario_active(loop)[0] if loop else False
            scenario = loop.primary_scenario if loop else ""
            if active and scenario in {"data.gap", "data.communication_loss"}:
                continue
            quality: Quality = "GOOD"
            if active and scenario == "data.bad_quality":
                quality = "BAD"
            observed_at = timestamp
            if active and scenario == "data.irregular_cadence":
                skip = _stable_fraction(signal.signal_id, elapsed, "skip") < float(
                    SCENARIO_PARAMETERS[scenario]["skip_fraction"]
                )
                if skip:
                    continue
                jitter = int(1 + 7 * _stable_fraction(signal.signal_id, elapsed))
                observed_at += timedelta(seconds=jitter)
                quality = "UNCERTAIN"
            value = (
                self._loop_value(signal)
                if signal.scope == "control_loop"
                else self._context_value(signal)
            )
            observations.append(
                Observation(
                    signal_id=signal.signal_id,
                    node_id=signal.opcua_node_id,
                    timestamp=observed_at,
                    value=value,
                    quality=quality,
                    engineering_unit=signal.engineering_unit,
                )
            )
        return tuple(observations)

    def truth_state(self) -> dict[str, dict[str, float | str | bool]]:
        """Return hidden state for benchmark scoring, never for OPC UA publication."""

        result: dict[str, dict[str, float | str | bool]] = {}
        for loop in self.catalog.loops:
            active, cycle, phase = self._scenario_active(loop)
            state = self._state[loop.loop_id]
            result[loop.loop_id] = {
                "scenario_id": loop.primary_scenario,
                "scenario_active": active,
                "load_change_active": (
                    loop.loop_id in {"FIC-101", "FIC-201", "FIC-301"}
                    and self._load_change_active(phase)
                ),
                "cycle": cycle,
                "cycle_phase": phase,
                "true_pv_normalized": state.true_pv,
                "measured_pv_normalized": state.measured_pv,
                "setpoint_normalized": state.setpoint,
                "controller_output_normalized": state.output,
                "actuator_position_normalized": state.actuator,
                "actuator_stuck": state.actuator_stuck,
                "balance_residual": state.balance_residual,
                "integral_state": state.integral,
                "sensor_bias_normalized": state.sensor_bias,
                "mode": state.mode,
            }
        return result
