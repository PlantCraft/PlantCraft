"""Deterministic scenario validation and compact research-study manifests."""

from __future__ import annotations

import math
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from statistics import fmean, stdev

from .catalog import SignalDefinition, load_catalog
from .contracts import (
    BENCHMARK_VERSION,
    build_benchmark_manifest,
    canonical_json_bytes,
    document_digest,
)
from .engine import Observation, PlantSimulator

SCENARIO_VALIDATION_SCHEMA = "process-plant-opcua/scenario-validation/v1"
SCENARIO_ISOLATION_MATRIX_SCHEMA = "process-plant-opcua/scenario-isolation-matrix/v1"
SEED_PARTITIONS = {
    "development": tuple(range(1, 16)),
    "validation": tuple(range(16, 21)),
    "held_out_test": tuple(range(21, 31)),
}
INITIAL_RESPONSE_WINDOW_SECONDS = 1_800.0
METRICS = (
    "observed_fraction",
    "bad_fraction",
    "uncertain_fraction",
    "jitter_fraction",
    "sensor_error",
    "control_error",
    "initial_response_control_error",
    "actuator_gap",
    "stuck_fraction",
    "manual_fraction",
    "capacity_fraction",
    "pv_variation",
    "true_pv_variation",
    "setpoint_variation",
    "output_variation",
    "bias_abs",
)
PREREGISTERED_RULES: dict[str, tuple[dict[str, object], ...]] = {
    "normal.steady": ({"metric": "active.observed_fraction", "operator": ">=", "threshold": 0.99},),
    "normal.load_change": (
        {"metric": "active.setpoint_range", "operator": ">=", "threshold": 0.07},
    ),
    "control.aggressive_tuning": (
        {"metric": "active.actuator_gap", "operator": ">=", "threshold": 0.002},
    ),
    "control.sluggish_tuning": (
        {
            "metric": "active.initial_response_control_error",
            "operator": ">=",
            "threshold": 0.003,
        },
    ),
    "control.oscillation": ({"metric": "active.pv_range", "operator": ">=", "threshold": 0.05},),
    "control.propagated_oscillation": (
        {"metric": "active.pv_range", "operator": ">=", "threshold": 0.008},
    ),
    "valve.stiction": ({"metric": "active.stuck_fraction", "operator": ">=", "threshold": 0.80},),
    "valve.backlash": ({"metric": "active.actuator_gap", "operator": ">=", "threshold": 0.0005},),
    "actuator.saturation": (
        {"metric": "active.capacity_fraction", "operator": ">=", "threshold": 0.50},
    ),
    "operations.manual": (
        {"metric": "active.manual_fraction", "operator": ">=", "threshold": 0.90},
    ),
    "operations.setpoint_activity": (
        {"metric": "active.setpoint_range", "operator": ">=", "threshold": 0.15},
    ),
    "sensor.noise": ({"metric": "active.sensor_error", "operator": ">=", "threshold": 0.015},),
    "sensor.drift": ({"metric": "active.bias_abs", "operator": ">=", "threshold": 0.005},),
    "sensor.frozen": ({"metric": "active.pv_range", "operator": "<=", "threshold": 0.001},),
    "data.gap": ({"metric": "active.observed_fraction", "operator": "<=", "threshold": 0.05},),
    "data.bad_quality": ({"metric": "active.bad_fraction", "operator": ">=", "threshold": 0.95},),
    "data.communication_loss": (
        {"metric": "active.observed_fraction", "operator": "<=", "threshold": 0.05},
    ),
    "data.irregular_cadence": (
        {"metric": "active.uncertain_fraction", "operator": ">=", "threshold": 0.70},
        {"metric": "active.jitter_fraction", "operator": ">=", "threshold": 0.70},
        {"metric": "active.observed_fraction", "operator": "<=", "threshold": 0.90},
    ),
    "process.disturbance": ({"metric": "active.pv_range", "operator": ">=", "threshold": 0.03},),
    "process.interaction": (
        {"metric": "active.control_error", "operator": ">=", "threshold": 0.0015},
    ),
}

SUMMARY_METRICS = METRICS + ("pv_range", "setpoint_range")
OBSERVATION_METRICS = (
    "observed_fraction",
    "bad_fraction",
    "uncertain_fraction",
    "jitter_fraction",
    "pv_available",
    "sp_available",
    "op_available",
    "mvfb_available",
    "mode_available",
    "pv_sp_error",
    "op_mvfb_gap",
    "pv_variation",
    "sp_variation",
    "op_variation",
    "manual_fraction",
    "upstream_available_fraction",
    "downstream_available_fraction",
    "upstream_pv_variation",
    "downstream_pv_variation",
)
REGULARIZED_FRAME_METRICS = (
    "regularized_pv_available",
    "regularized_sp_available",
    "regularized_op_available",
    "regularized_mvfb_available",
    "regularized_mode_available",
    "regularized_pv_sp_error",
    "regularized_op_mvfb_gap",
    "regularized_pv_variation",
    "regularized_sp_variation",
    "regularized_op_variation",
    "regularized_manual_fraction",
    "imputed_fraction",
)
FRAME_FEATURE_METRICS = OBSERVATION_METRICS + REGULARIZED_FRAME_METRICS
OBSERVATION_ABLATION_FEATURES = {
    "pv_sp": (
        "observed_fraction",
        "pv_available",
        "sp_available",
        "pv_sp_error",
        "pv_variation",
        "sp_variation",
        "pv_range",
        "sp_range",
    ),
    "pv_sp_op_mvfb_mode": (
        "observed_fraction",
        "pv_available",
        "sp_available",
        "pv_sp_error",
        "pv_variation",
        "sp_variation",
        "pv_range",
        "sp_range",
        "op_available",
        "mvfb_available",
        "mode_available",
        "op_mvfb_gap",
        "op_variation",
        "manual_fraction",
    ),
    "pv_sp_op_mvfb_mode_quality_timestamps": (
        "observed_fraction",
        "pv_available",
        "sp_available",
        "pv_sp_error",
        "pv_variation",
        "sp_variation",
        "pv_range",
        "sp_range",
        "op_available",
        "mvfb_available",
        "mode_available",
        "op_mvfb_gap",
        "op_variation",
        "manual_fraction",
        "bad_fraction",
        "uncertain_fraction",
        "jitter_fraction",
    ),
}
FRAME_ABLATION_FEATURES = {
    view: tuple(feature for feature in features if feature not in {"pv_range", "sp_range"})
    for view, features in OBSERVATION_ABLATION_FEATURES.items()
}
FRAME_ABLATION_FEATURES["plant_graph"] = FRAME_ABLATION_FEATURES[
    "pv_sp_op_mvfb_mode_quality_timestamps"
] + (
    "upstream_available_fraction",
    "downstream_available_fraction",
    "upstream_pv_variation",
    "downstream_pv_variation",
)
FRAME_ABLATION_FEATURES["regularized_grid"] = (
    "observed_fraction",
    "bad_fraction",
    "uncertain_fraction",
    "jitter_fraction",
    *REGULARIZED_FRAME_METRICS,
)
DETECTION_PERSISTENCE_FRAMES = 3
LOCALIZATION_K = 5
REGULARIZATION_MAX_AGE_SECONDS = 60.0
_T_95_BY_SAMPLE_COUNT = {
    2: 12.706205,
    3: 4.302653,
    4: 3.182446,
    5: 2.776445,
    10: 2.262157,
    15: 2.144787,
    30: 2.04523,
}


@dataclass
class _Phase:
    samples: int = 0
    sums: dict[str, float] = field(default_factory=lambda: {metric: 0.0 for metric in METRICS})
    metric_counts: dict[str, int] = field(default_factory=lambda: {metric: 0 for metric in METRICS})
    pv_min: float = math.inf
    pv_max: float = -math.inf
    sp_min: float = math.inf
    sp_max: float = -math.inf

    def add(self, values: dict[str, float | None], pv: float, sp: float) -> None:
        self.samples += 1
        for metric in METRICS:
            value = values[metric]
            if value is not None:
                self.sums[metric] += value
                self.metric_counts[metric] += 1
        self.pv_min = min(self.pv_min, pv)
        self.pv_max = max(self.pv_max, pv)
        self.sp_min = min(self.sp_min, sp)
        self.sp_max = max(self.sp_max, sp)

    def summary(self) -> dict[str, float | int]:
        if not self.samples:
            return {
                "samples": 0,
                **{metric: 0.0 for metric in METRICS},
                "pv_range": 0.0,
                "setpoint_range": 0.0,
            }
        return {
            "samples": self.samples,
            **{
                metric: (
                    self.sums[metric] / self.metric_counts[metric]
                    if self.metric_counts[metric]
                    else 0.0
                )
                for metric in METRICS
            },
            "pv_range": self.pv_max - self.pv_min,
            "setpoint_range": self.sp_max - self.sp_min,
        }


@dataclass
class _ObservationPhase:
    samples: int = 0
    sums: dict[str, float] = field(
        default_factory=lambda: {metric: 0.0 for metric in OBSERVATION_METRICS}
    )
    pv_min: float = math.inf
    pv_max: float = -math.inf
    sp_min: float = math.inf
    sp_max: float = -math.inf

    def add(
        self,
        values: dict[str, float],
        pv: float | None,
        sp: float | None,
    ) -> None:
        self.samples += 1
        for metric in OBSERVATION_METRICS:
            self.sums[metric] += values[metric]
        if pv is not None:
            self.pv_min = min(self.pv_min, pv)
            self.pv_max = max(self.pv_max, pv)
        if sp is not None:
            self.sp_min = min(self.sp_min, sp)
            self.sp_max = max(self.sp_max, sp)

    def summary(self) -> dict[str, float | int]:
        if not self.samples:
            return {
                "samples": 0,
                **{metric: 0.0 for metric in OBSERVATION_METRICS},
                "pv_range": 0.0,
                "sp_range": 0.0,
            }
        return {
            "samples": self.samples,
            **{metric: self.sums[metric] / self.samples for metric in OBSERVATION_METRICS},
            "pv_range": 0.0 if self.pv_min == math.inf else self.pv_max - self.pv_min,
            "sp_range": 0.0 if self.sp_min == math.inf else self.sp_max - self.sp_min,
        }


def _normalized_observation(
    signal: SignalDefinition,
    observation: Observation | None,
) -> float | None:
    if (
        observation is None
        or isinstance(observation.value, bool)
        or not isinstance(observation.value, (int, float))
    ):
        return None
    try:
        low_text, high_text = signal.normal_range.split("..", 1)
        low = float(low_text)
        high = float(high_text)
    except (TypeError, ValueError):
        return None
    if high <= low:
        return None
    return (float(observation.value) - low) / (high - low)


def _observed_variation(current: float | None, previous: float | None) -> float:
    if current is None or previous is None:
        return 0.0
    return abs(current - previous)


def _neighbor_pv_values(
    loop_ids: tuple[str, ...],
    signal_by_loop_suffix: dict[str, dict[str, SignalDefinition]],
    observed_by_loop: dict[str, dict[str, Observation]],
) -> list[float]:
    values = []
    for loop_id in loop_ids:
        signal = signal_by_loop_suffix[loop_id]["PV"]
        observation = observed_by_loop.get(loop_id, {}).get(signal.signal_id)
        value = _normalized_observation(signal, observation)
        if value is not None:
            values.append(value)
    return values


def _is_active(scenario_id: str, truth: dict[str, object]) -> bool:
    if scenario_id == "normal.steady":
        return not bool(truth["load_change_active"])
    if scenario_id == "normal.load_change":
        return bool(truth["load_change_active"])
    return bool(truth["scenario_active"])


def evaluate_seed(
    seed: int,
    *,
    scenario_cycle_seconds: float = 3_600.0,
    frame_seconds: float = 30.0,
    integration_step_seconds: float = 1.0,
    scenario_ids: tuple[str, ...] | None = None,
    collect_frame_samples: bool = False,
) -> dict[str, object]:
    """Evaluate all declared scenarios over one complete deterministic cycle."""

    if not math.isclose(
        scenario_cycle_seconds / frame_seconds,
        round(scenario_cycle_seconds / frame_seconds),
        abs_tol=1e-9,
    ):
        raise ValueError("scenario cycle must be divisible by frame_seconds")
    catalog = load_catalog()
    declared_scenarios = {scenario.scenario_id for scenario in catalog.scenarios}
    selected_scenarios = declared_scenarios if scenario_ids is None else set(scenario_ids)
    unknown_scenarios = selected_scenarios - declared_scenarios
    if unknown_scenarios:
        raise ValueError(f"unknown scenarios: {sorted(unknown_scenarios)}")
    if not selected_scenarios:
        raise ValueError("at least one scenario must be selected")
    simulator = PlantSimulator(
        seed=seed,
        scenario_cycle_seconds=scenario_cycle_seconds,
        integration_step_seconds=integration_step_seconds,
        enabled_scenarios=selected_scenarios,
    )
    signal_by_id = {signal.signal_id: signal for signal in catalog.signals}
    signals_by_loop = {
        loop.loop_id: tuple(signal for signal in catalog.signals if signal.loop_id == loop.loop_id)
        for loop in catalog.loops
    }
    signal_by_loop_suffix = {
        loop_id: {signal.node_identifier.rsplit(".", 1)[-1]: signal for signal in signals}
        for loop_id, signals in signals_by_loop.items()
    }
    upstream = {loop.loop_id: [] for loop in catalog.loops}
    downstream = {loop.loop_id: [] for loop in catalog.loops}
    for edge in simulator.coupling_edges:
        upstream[edge.target_loop_id].append(edge.source_loop_id)
        downstream[edge.source_loop_id].append(edge.target_loop_id)
    phases = {
        scenario.scenario_id: {"active": _Phase(), "inactive": _Phase()}
        for scenario in catalog.scenarios
        if scenario.scenario_id in selected_scenarios
    }
    observation_phases = {
        scenario.scenario_id: {
            "active": _ObservationPhase(),
            "inactive": _ObservationPhase(),
        }
        for scenario in catalog.scenarios
        if scenario.scenario_id in selected_scenarios
    }
    previous: dict[tuple[str, str], tuple[float, float, float, float]] = {}
    previous_observed: dict[tuple[str, str], dict[str, float]] = {}
    previous_observed_at: dict[tuple[str, str], dict[str, int]] = {}
    previous_regularized: dict[tuple[str, str], dict[str, float]] = {}
    previous_mode: dict[tuple[str, str], tuple[str, int]] = {}
    previous_neighbors: dict[tuple[str, str], dict[str, float]] = {}
    active_started_at: dict[tuple[str, str], int] = {}
    frame_samples: list[dict[str, object]] = []
    transitions = {scenario_id: 0 for scenario_id in selected_scenarios}
    frames = round(scenario_cycle_seconds / frame_seconds)
    for _ in range(frames):
        frame = simulator.advance(frame_seconds)
        truth = simulator.truth_state()
        observed_by_loop: dict[str, dict[str, Observation]] = {}
        for observation in frame.observations:
            signal = signal_by_id[observation.signal_id]
            if signal.loop_id:
                observed_by_loop.setdefault(signal.loop_id, {})[signal.signal_id] = observation
        for event in frame.truth_events:
            if event.scenario_id in transitions:
                transitions[event.scenario_id] += 1
        elapsed = round(simulator.elapsed_seconds)
        for scenario in catalog.scenarios:
            if scenario.scenario_id not in selected_scenarios:
                continue
            for loop_id in scenario.primary_loop_ids:
                state = truth[loop_id]
                phase_name = "active" if _is_active(scenario.scenario_id, state) else "inactive"
                scenario_loop = (scenario.scenario_id, loop_id)
                if phase_name == "active":
                    active_start = active_started_at.setdefault(scenario_loop, elapsed)
                else:
                    active_started_at.pop(scenario_loop, None)
                    active_start = None
                expected = tuple(
                    signal
                    for signal in signals_by_loop[loop_id]
                    if elapsed % signal.nominal_cadence_seconds == 0
                )
                observed = observed_by_loop.get(loop_id, {})
                due_pairs = [
                    (item, observed[item.signal_id])
                    for item in expected
                    if item.signal_id in observed
                ]
                due = [observation for _, observation in due_pairs]
                denominator = len(expected) or 1
                observed_denominator = len(due) or 1
                measured = float(state["measured_pv_normalized"])
                true_pv = float(state["true_pv_normalized"])
                setpoint = float(state["setpoint_normalized"])
                output = float(state["controller_output_normalized"])
                actuator = float(state["actuator_position_normalized"])
                prior = previous.get((scenario.scenario_id, loop_id))
                measured_variation = 0.0 if prior is None else abs(measured - prior[0])
                true_variation = 0.0 if prior is None else abs(true_pv - prior[1])
                setpoint_variation = 0.0 if prior is None else abs(setpoint - prior[2])
                output_variation = 0.0 if prior is None else abs(output - prior[3])
                previous[(scenario.scenario_id, loop_id)] = (
                    measured,
                    true_pv,
                    setpoint,
                    output,
                )
                transport_due = bool(expected)
                values = {
                    "observed_fraction": (len(due) / denominator if transport_due else None),
                    "bad_fraction": (
                        sum(item.quality == "BAD" for item in due) / observed_denominator
                        if transport_due
                        else None
                    ),
                    "uncertain_fraction": (
                        sum(item.quality == "UNCERTAIN" for item in due) / observed_denominator
                        if transport_due
                        else None
                    ),
                    "jitter_fraction": (
                        sum(item.timestamp != frame.timestamp for item in due)
                        / observed_denominator
                        if transport_due
                        else None
                    ),
                    "sensor_error": abs(measured - true_pv),
                    "control_error": abs(setpoint - measured),
                    "initial_response_control_error": (
                        abs(setpoint - measured)
                        if active_start is not None
                        and elapsed - active_start < INITIAL_RESPONSE_WINDOW_SECONDS
                        else None
                    ),
                    "actuator_gap": abs(output - actuator),
                    "stuck_fraction": float(bool(state["actuator_stuck"])),
                    "manual_fraction": float(state["mode"] == "MAN"),
                    "capacity_fraction": float(actuator >= 0.665),
                    "pv_variation": measured_variation,
                    "true_pv_variation": true_variation,
                    "setpoint_variation": setpoint_variation,
                    "output_variation": output_variation,
                    "bias_abs": abs(float(state["sensor_bias_normalized"])),
                }
                phases[scenario.scenario_id][phase_name].add(values, measured, setpoint)
                by_suffix = {
                    signal.node_identifier.rsplit(".", 1)[-1]: (signal, observation)
                    for signal, observation in due_pairs
                }
                observed_values = {
                    suffix: _normalized_observation(*by_suffix[suffix])
                    if suffix in by_suffix
                    else None
                    for suffix in ("PV", "SP", "OP", "MVFB")
                }
                mode_observation = by_suffix.get("MODE", (None, None))[1]
                prior_observed = previous_observed.setdefault((scenario.scenario_id, loop_id), {})
                prior_observed_at = previous_observed_at.setdefault(
                    (scenario.scenario_id, loop_id), {}
                )
                regularized_values = {
                    suffix: (
                        value
                        if value is not None
                        else prior_observed.get(suffix)
                        if elapsed - prior_observed_at.get(suffix, -math.inf)
                        <= REGULARIZATION_MAX_AGE_SECONDS
                        else None
                    )
                    for suffix, value in observed_values.items()
                }
                prior_regularized = previous_regularized.setdefault(
                    (scenario.scenario_id, loop_id), {}
                )
                current_mode = str(mode_observation.value) if mode_observation is not None else None
                prior_mode = previous_mode.get((scenario.scenario_id, loop_id))
                regularized_mode = current_mode
                if (
                    regularized_mode is None
                    and prior_mode is not None
                    and elapsed - prior_mode[1] <= REGULARIZATION_MAX_AGE_SECONDS
                ):
                    regularized_mode = prior_mode[0]
                upstream_values = _neighbor_pv_values(
                    tuple(upstream[loop_id]),
                    signal_by_loop_suffix,
                    observed_by_loop,
                )
                downstream_values = _neighbor_pv_values(
                    tuple(downstream[loop_id]),
                    signal_by_loop_suffix,
                    observed_by_loop,
                )
                upstream_mean = fmean(upstream_values) if upstream_values else None
                downstream_mean = fmean(downstream_values) if downstream_values else None
                prior_neighbors = previous_neighbors.setdefault((scenario.scenario_id, loop_id), {})
                observation_values = {
                    "observed_fraction": len(due) / denominator,
                    "bad_fraction": sum(item.quality == "BAD" for item in due)
                    / observed_denominator,
                    "uncertain_fraction": sum(item.quality == "UNCERTAIN" for item in due)
                    / observed_denominator,
                    "jitter_fraction": sum(item.timestamp != frame.timestamp for item in due)
                    / observed_denominator,
                    "pv_available": float(observed_values["PV"] is not None),
                    "sp_available": float(observed_values["SP"] is not None),
                    "op_available": float(observed_values["OP"] is not None),
                    "mvfb_available": float(observed_values["MVFB"] is not None),
                    "mode_available": float(mode_observation is not None),
                    "pv_sp_error": 0.0
                    if observed_values["PV"] is None or observed_values["SP"] is None
                    else abs(observed_values["PV"] - observed_values["SP"]),
                    "op_mvfb_gap": 0.0
                    if observed_values["OP"] is None or observed_values["MVFB"] is None
                    else abs(observed_values["OP"] - observed_values["MVFB"]),
                    "pv_variation": _observed_variation(
                        observed_values["PV"], prior_observed.get("PV")
                    ),
                    "sp_variation": _observed_variation(
                        observed_values["SP"], prior_observed.get("SP")
                    ),
                    "op_variation": _observed_variation(
                        observed_values["OP"], prior_observed.get("OP")
                    ),
                    "manual_fraction": float(
                        mode_observation is not None and mode_observation.value == "MAN"
                    ),
                    "upstream_available_fraction": len(upstream_values)
                    / (len(upstream[loop_id]) or 1),
                    "downstream_available_fraction": len(downstream_values)
                    / (len(downstream[loop_id]) or 1),
                    "upstream_pv_variation": _observed_variation(
                        upstream_mean, prior_neighbors.get("upstream")
                    ),
                    "downstream_pv_variation": _observed_variation(
                        downstream_mean, prior_neighbors.get("downstream")
                    ),
                    "regularized_pv_available": float(regularized_values["PV"] is not None),
                    "regularized_sp_available": float(regularized_values["SP"] is not None),
                    "regularized_op_available": float(regularized_values["OP"] is not None),
                    "regularized_mvfb_available": float(regularized_values["MVFB"] is not None),
                    "regularized_mode_available": float(regularized_mode is not None),
                    "regularized_pv_sp_error": (
                        0.0
                        if regularized_values["PV"] is None or regularized_values["SP"] is None
                        else abs(regularized_values["PV"] - regularized_values["SP"])
                    ),
                    "regularized_op_mvfb_gap": (
                        0.0
                        if regularized_values["OP"] is None or regularized_values["MVFB"] is None
                        else abs(regularized_values["OP"] - regularized_values["MVFB"])
                    ),
                    "regularized_pv_variation": _observed_variation(
                        regularized_values["PV"], prior_regularized.get("PV")
                    ),
                    "regularized_sp_variation": _observed_variation(
                        regularized_values["SP"], prior_regularized.get("SP")
                    ),
                    "regularized_op_variation": _observed_variation(
                        regularized_values["OP"], prior_regularized.get("OP")
                    ),
                    "regularized_manual_fraction": float(regularized_mode == "MAN"),
                    "imputed_fraction": sum(
                        original is None and regularized_values[suffix] is not None
                        for suffix, original in observed_values.items()
                    )
                    / 5.0
                    + float(mode_observation is None and regularized_mode is not None) / 5.0,
                }
                for suffix, value in observed_values.items():
                    if value is not None:
                        prior_observed[suffix] = value
                        prior_observed_at[suffix] = elapsed
                for suffix, value in regularized_values.items():
                    if value is not None:
                        prior_regularized[suffix] = value
                if current_mode is not None:
                    previous_mode[(scenario.scenario_id, loop_id)] = (
                        current_mode,
                        elapsed,
                    )
                if upstream_mean is not None:
                    prior_neighbors["upstream"] = upstream_mean
                if downstream_mean is not None:
                    prior_neighbors["downstream"] = downstream_mean
                observation_phases[scenario.scenario_id][phase_name].add(
                    observation_values,
                    observed_values["PV"],
                    observed_values["SP"],
                )
                if collect_frame_samples:
                    frame_samples.append(
                        {
                            "scenario_id": scenario.scenario_id,
                            "loop_id": loop_id,
                            "frame": len(frame_samples),
                            "elapsed_seconds": elapsed,
                            "active": phase_name == "active",
                            "features": observation_values,
                        }
                    )
    scenarios = {}
    for scenario in catalog.scenarios:
        if scenario.scenario_id not in selected_scenarios:
            continue
        active = phases[scenario.scenario_id]["active"].summary()
        inactive = phases[scenario.scenario_id]["inactive"].summary()
        scenarios[scenario.scenario_id] = {
            "active": active,
            "inactive": inactive,
            "observations": {
                "active": observation_phases[scenario.scenario_id]["active"].summary(),
                "inactive": observation_phases[scenario.scenario_id]["inactive"].summary(),
            },
            "transitions": transitions[scenario.scenario_id],
        }
    failures = validate_scenario_results(scenarios)
    result = {
        "seed": seed,
        "frames": frames,
        "enabled_scenarios": sorted(selected_scenarios),
        "scenarios": scenarios,
        "passed": not failures,
        "failures": failures,
    }
    if collect_frame_samples:
        result["frame_samples"] = frame_samples
    return result


def validate_scenario_results(scenarios: dict[str, object]) -> list[dict[str, object]]:
    """Apply the frozen scenario-specific minimum signatures."""

    failures = []
    for scenario_id, rules in PREREGISTERED_RULES.items():
        if scenario_id not in scenarios:
            continue
        scenario = scenarios[scenario_id]
        for rule in rules:
            phase, metric = str(rule["metric"]).split(".", 1)
            actual = float(scenario[phase][metric])
            threshold = float(rule["threshold"])
            operator = rule["operator"]
            passed = actual >= threshold if operator == ">=" else actual <= threshold
            if not passed:
                failures.append(
                    {
                        "scenario_id": scenario_id,
                        "metric": rule["metric"],
                        "operator": operator,
                        "threshold": threshold,
                        "actual": actual,
                    }
                )
    return failures


def _confidence_interval(values: list[float]) -> dict[str, float | int]:
    count = len(values)
    mean = fmean(values)
    if count < 2:
        return {
            "count": count,
            "mean": mean,
            "sample_sd": 0.0,
            "lower": mean,
            "upper": mean,
        }
    sample_sd = stdev(values)
    critical = _T_95_BY_SAMPLE_COUNT.get(count, 1.959964)
    margin = critical * sample_sd / math.sqrt(count)
    return {
        "count": count,
        "mean": mean,
        "sample_sd": sample_sd,
        "lower": mean - margin,
        "upper": mean + margin,
    }


def summarize_scenario_statistics(
    results: list[dict[str, object]],
) -> dict[str, object]:
    """Calculate two-sided 95% t intervals across independent seed summaries."""

    if not results or not results[0]["scenarios"]:
        return {}
    scenario_ids = sorted(results[0]["scenarios"])
    return {
        "method": "two-sided Student t interval across independent seeds",
        "confidence_level": 0.95,
        "scenarios": {
            scenario_id: {
                metric: _confidence_interval(
                    [
                        float(result["scenarios"][scenario_id]["active"][metric])
                        for result in results
                    ]
                )
                for metric in SUMMARY_METRICS
            }
            for scenario_id in scenario_ids
        },
    }


def _macro_f1(
    labels: tuple[str, ...],
    truth: list[str],
    predictions: list[str],
) -> float:
    scores = []
    for label in labels:
        true_positive = sum(t == label and p == label for t, p in zip(truth, predictions))
        false_positive = sum(t != label and p == label for t, p in zip(truth, predictions))
        false_negative = sum(t == label and p != label for t, p in zip(truth, predictions))
        denominator = 2 * true_positive + false_positive + false_negative
        scores.append(0.0 if denominator == 0 else 2 * true_positive / denominator)
    return fmean(scores)


def _baseline_samples(
    results: list[dict[str, object]],
    selected_seeds: set[int],
    features: tuple[str, ...],
) -> list[tuple[str, tuple[float, ...]]]:
    samples = []
    for result in results:
        if int(result["seed"]) not in selected_seeds:
            continue
        for scenario_id, scenario in sorted(result["scenarios"].items()):
            active = scenario["observations"]["active"]
            samples.append(
                (
                    scenario_id,
                    tuple(float(active[feature]) for feature in features),
                )
            )
    return samples


def evaluate_observation_baselines(
    results: list[dict[str, object]],
) -> dict[str, object]:
    """Evaluate observation-only nearest-centroid baselines on seed partitions."""

    if not results or len(results[0]["scenarios"]) < 2:
        return {}
    labels = tuple(sorted(results[0]["scenarios"]))
    reports: dict[str, object] = {}
    for view, features in OBSERVATION_ABLATION_FEATURES.items():
        training = _baseline_samples(results, set(SEED_PARTITIONS["development"]), features)
        if not training:
            continue
        normalize, centroids = _fit_centroids(training, len(features), labels)
        split_reports = {}
        for split in ("validation", "held_out_test"):
            samples = _baseline_samples(results, set(SEED_PARTITIONS[split]), features)
            truth = [label for label, _ in samples]
            predictions = []
            for _, row in samples:
                normalized = normalize(row)
                predictions.append(
                    min(
                        labels,
                        key=lambda label: sum(
                            (value - centroids[label][index]) ** 2
                            for index, value in enumerate(normalized)
                        ),
                    )
                )
            correct = sum(actual == predicted for actual, predicted in zip(truth, predictions))
            confusion = {
                actual: {
                    predicted: sum(
                        left == actual and right == predicted
                        for left, right in zip(truth, predictions)
                    )
                    for predicted in labels
                    if any(
                        left == actual and right == predicted
                        for left, right in zip(truth, predictions)
                    )
                }
                for actual in labels
            }
            split_reports[split] = {
                "samples": len(samples),
                "accuracy": 0.0 if not samples else correct / len(samples),
                "macro_f1": 0.0 if not samples else _macro_f1(labels, truth, predictions),
                "confusion": confusion,
            }
        reports[view] = {"features": list(features), "splits": split_reports}
    return {
        "method": "development-fit standardized nearest centroid",
        "input": "OPC UA observation-window summaries",
        "missing_data_policy": (
            "availability is explicit and unavailable numeric features contribute zero"
        ),
        "limitation": (
            "This is a reproducible observation-window baseline, not a deployable "
            "online detector; temporal and causal-localization baselines remain required."
        ),
        "views": reports,
    }


def _frame_baseline_samples(
    results: list[dict[str, object]],
    selected_seeds: set[int],
    features: tuple[str, ...],
) -> list[tuple[str, tuple[float, ...]]]:
    samples = []
    for result in results:
        if int(result["seed"]) not in selected_seeds:
            continue
        for sample in result.get("frame_samples", []):
            values = sample["features"]
            samples.append(
                (
                    "active" if sample["active"] else "inactive",
                    tuple(float(values[feature]) for feature in features),
                )
            )
    return samples


def _frame_records(
    results: list[dict[str, object]],
    selected_seeds: set[int],
    features: tuple[str, ...],
) -> list[dict[str, object]]:
    records = []
    for result in results:
        seed = int(result["seed"])
        if seed not in selected_seeds:
            continue
        for sample in result.get("frame_samples", []):
            if not all(field in sample for field in ("scenario_id", "loop_id", "elapsed_seconds")):
                continue
            values = sample["features"]
            records.append(
                {
                    "seed": seed,
                    "scenario_id": str(sample["scenario_id"]),
                    "loop_id": str(sample["loop_id"]),
                    "elapsed_seconds": float(sample["elapsed_seconds"]),
                    "active": bool(sample["active"]),
                    "row": tuple(float(values[feature]) for feature in features),
                }
            )
    return records


def _temporal_detection_metrics(
    records: list[dict[str, object]],
    predictions: list[str],
    *,
    persistence_frames: int,
) -> dict[str, object]:
    grouped: dict[tuple[int, str, str], list[tuple[dict[str, object], str]]] = {}
    for record, prediction in zip(records, predictions):
        key = (
            int(record["seed"]),
            str(record["scenario_id"]),
            str(record["loop_id"]),
        )
        grouped.setdefault(key, []).append((record, prediction))
    delays = []
    onsets = 0
    for sequence in grouped.values():
        sequence.sort(key=lambda item: float(item[0]["elapsed_seconds"]))
        for onset_index in range(1, len(sequence)):
            if not sequence[onset_index][0]["active"]:
                continue
            if sequence[onset_index - 1][0]["active"]:
                continue
            onsets += 1
            end_index = onset_index
            while end_index < len(sequence) and sequence[end_index][0]["active"]:
                end_index += 1
            for confirmation_index in range(
                onset_index + persistence_frames - 1,
                end_index,
            ):
                start_index = confirmation_index - persistence_frames + 1
                if all(
                    sequence[index][1] == "active"
                    for index in range(start_index, confirmation_index + 1)
                ):
                    delays.append(
                        float(sequence[confirmation_index][0]["elapsed_seconds"])
                        - float(sequence[onset_index][0]["elapsed_seconds"])
                    )
                    break
    ordered_delays = sorted(delays)
    p95_index = max(math.ceil(0.95 * len(ordered_delays)) - 1, 0)
    return {
        "persistence_frames": persistence_frames,
        "onsets": onsets,
        "detected_onsets": len(delays),
        "detection_rate": 0.0 if not onsets else len(delays) / onsets,
        "mean_detection_delay_seconds": None if not delays else fmean(delays),
        "p95_detection_delay_seconds": (None if not delays else ordered_delays[p95_index]),
    }


def _localization_metrics(
    records: list[dict[str, object]],
    active_scores: list[float],
    *,
    top_k: int,
) -> dict[str, object]:
    grouped: dict[tuple[int, float], list[tuple[dict[str, object], float]]] = {}
    for record, score in zip(records, active_scores):
        key = (int(record["seed"]), float(record["elapsed_seconds"]))
        grouped.setdefault(key, []).append((record, score))
    average_precisions = []
    precisions = []
    recalls = []
    for candidates in grouped.values():
        relevant = sum(bool(record["active"]) for record, _ in candidates)
        if not relevant:
            continue
        ranked = sorted(
            candidates,
            key=lambda item: (
                -item[1],
                str(item[0]["scenario_id"]),
                str(item[0]["loop_id"]),
            ),
        )
        found = 0
        precision_sum = 0.0
        for rank, (record, _) in enumerate(ranked, start=1):
            if record["active"]:
                found += 1
                precision_sum += found / rank
        average_precisions.append(precision_sum / relevant)
        selected = ranked[:top_k]
        selected_relevant = sum(bool(record["active"]) for record, _ in selected)
        precisions.append(selected_relevant / len(selected))
        recalls.append(selected_relevant / relevant)
    return {
        "ranking": "distance-to-inactive minus distance-to-active centroid",
        "uses_loop_or_scenario_identity_as_feature": False,
        "active_frames": len(average_precisions),
        "mean_average_precision": (0.0 if not average_precisions else fmean(average_precisions)),
        f"precision_at_{top_k}": 0.0 if not precisions else fmean(precisions),
        f"recall_at_{top_k}": 0.0 if not recalls else fmean(recalls),
    }


def evaluate_frame_baselines(
    results: list[dict[str, object]],
    *,
    frame_seconds: float,
) -> dict[str, object]:
    """Fit binary per-frame observation baselines on development seeds."""

    if not results or not results[0].get("frame_samples"):
        return {}
    labels = ("active", "inactive")
    reports: dict[str, object] = {}
    for view, features in FRAME_ABLATION_FEATURES.items():
        training = _frame_baseline_samples(results, set(SEED_PARTITIONS["development"]), features)
        normalize, centroids = _fit_centroids(training, len(features), labels)
        split_reports = {}
        for split in ("validation", "held_out_test"):
            records = _frame_records(results, set(SEED_PARTITIONS[split]), features)
            samples = [
                (
                    "active" if record["active"] else "inactive",
                    record["row"],
                )
                for record in records
            ]
            truth = [label for label, _ in samples]
            predictions = []
            active_scores = []
            for _, row in samples:
                normalized = normalize(row)
                distances = {
                    label: sum(
                        (value - centroids[label][index]) ** 2
                        for index, value in enumerate(normalized)
                    )
                    for label in labels
                }
                predictions.append(min(labels, key=distances.__getitem__))
                active_scores.append(distances["inactive"] - distances["active"])
            confusion = {
                actual: {
                    predicted: sum(
                        left == actual and right == predicted
                        for left, right in zip(truth, predictions)
                    )
                    for predicted in labels
                }
                for actual in labels
            }
            correct = sum(actual == predicted for actual, predicted in zip(truth, predictions))
            false_positives = confusion["inactive"]["active"]
            inactive_frames = sum(label == "inactive" for label in truth)
            inactive_loop_days = inactive_frames * frame_seconds / 86_400.0
            split_reports[split] = {
                "samples": len(samples),
                "accuracy": correct / len(samples),
                "macro_f1": _macro_f1(labels, truth, predictions),
                "false_alarms_per_loop_day": false_positives / inactive_loop_days,
                "confusion": confusion,
                "temporal_detection": _temporal_detection_metrics(
                    records,
                    predictions,
                    persistence_frames=DETECTION_PERSISTENCE_FRAMES,
                ),
                "loop_localization": _localization_metrics(
                    records,
                    active_scores,
                    top_k=LOCALIZATION_K,
                ),
            }
        reports[view] = {"features": list(features), "splits": split_reports}
    return {
        "method": "development-fit standardized binary nearest centroid",
        "input": "individual OPC UA publication frames",
        "target": "scenario active versus inactive",
        "unit": "primary-loop frame",
        "temporal_policy": ("an onset is detected after three consecutive active predictions"),
        "localization_policy": (
            "rank candidate loops with the shared binary score; loop and scenario "
            "identity are deterministic tie-breakers only"
        ),
        "regularization_policy": (
            "causal last observation carried forward for at most 60 seconds; "
            "quality, timestamp, and imputation fraction remain explicit"
        ),
        "views": reports,
    }


def run_scenario_study(
    output: str | Path,
    *,
    jobs: int = 1,
    scenario_cycle_seconds: float = 3_600.0,
    frame_seconds: float = 30.0,
    integration_step_seconds: float = 1.0,
    scenario_ids: tuple[str, ...] | None = None,
    include_frame_baselines: bool = True,
) -> dict[str, object]:
    """Run the preregistered 15/5/10 seed partitions and write one compact manifest."""

    if isinstance(jobs, bool) or not isinstance(jobs, int) or jobs < 1:
        raise ValueError("jobs must be a positive integer")
    if scenario_ids is not None:
        if not scenario_ids:
            raise ValueError("at least one scenario must be selected")
        if len(set(scenario_ids)) != len(scenario_ids):
            raise ValueError("selected scenarios must be unique")
        unknown_scenarios = set(scenario_ids) - set(PREREGISTERED_RULES)
        if unknown_scenarios:
            raise ValueError(f"unknown scenarios: {sorted(unknown_scenarios)}")
    seeds = tuple(seed for partition in SEED_PARTITIONS.values() for seed in partition)
    arguments = [
        (
            seed,
            scenario_cycle_seconds,
            frame_seconds,
            integration_step_seconds,
            scenario_ids,
            include_frame_baselines,
        )
        for seed in seeds
    ]
    if jobs > 1:
        with ProcessPoolExecutor(max_workers=jobs) as executor:
            results = list(executor.map(_evaluate_seed_arguments, arguments))
    else:
        results = [_evaluate_seed_arguments(item) for item in arguments]
    frame_baselines = (
        evaluate_frame_baselines(results, frame_seconds=frame_seconds)
        if include_frame_baselines
        else {}
    )
    for result in results:
        result.pop("frame_samples", None)
    benchmark = build_benchmark_manifest()
    selected_scenarios = sorted(PREREGISTERED_RULES if scenario_ids is None else set(scenario_ids))
    scenario_mode = (
        "integrated"
        if len(selected_scenarios) == len(PREREGISTERED_RULES)
        else "isolated"
        if len(selected_scenarios) == 1
        else "selected_overlap"
    )
    manifest: dict[str, object] = {
        "schema": SCENARIO_VALIDATION_SCHEMA,
        "benchmark_version": BENCHMARK_VERSION,
        "benchmark_manifest_digest": document_digest(benchmark),
        "partitions": {key: list(value) for key, value in SEED_PARTITIONS.items()},
        "scenario_cycle_seconds": scenario_cycle_seconds,
        "frame_seconds": frame_seconds,
        "integration_step_seconds": integration_step_seconds,
        "scenario_mode": scenario_mode,
        "selected_scenarios": selected_scenarios,
        "preregistered_rules": PREREGISTERED_RULES,
        "results": results,
        "statistics": summarize_scenario_statistics(results),
        "observation_window_baselines": evaluate_observation_baselines(results),
        "frame_baselines": frame_baselines,
        "passed": all(bool(result["passed"]) for result in results),
        "failed_runs": [
            {"seed": result["seed"], "failures": result["failures"]}
            for result in results
            if not result["passed"]
        ],
    }
    manifest["study_digest"] = document_digest(manifest)
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(canonical_json_bytes(manifest) + b"\n")
    return manifest


def _evaluate_seed_arguments(
    arguments: tuple[int, float, float, float, tuple[str, ...] | None, bool],
) -> dict[str, object]:
    seed, cycle, frame, integration, scenario_ids, collect_frame_samples = arguments
    return evaluate_seed(
        seed,
        scenario_cycle_seconds=cycle,
        frame_seconds=frame,
        integration_step_seconds=integration,
        scenario_ids=scenario_ids,
        collect_frame_samples=collect_frame_samples,
    )


def run_isolation_matrix(
    output: str | Path,
    *,
    jobs: int = 1,
    scenario_cycle_seconds: float = 3_600.0,
    frame_seconds: float = 30.0,
    integration_step_seconds: float = 1.0,
) -> dict[str, object]:
    """Qualify every scenario independently across all fixed seed partitions."""

    if isinstance(jobs, bool) or not isinstance(jobs, int) or jobs < 1:
        raise ValueError("jobs must be a positive integer")
    scenario_ids = tuple(sorted(PREREGISTERED_RULES))
    seeds = tuple(seed for partition in SEED_PARTITIONS.values() for seed in partition)
    arguments = [
        (
            seed,
            scenario_id,
            scenario_cycle_seconds,
            frame_seconds,
            integration_step_seconds,
        )
        for scenario_id in scenario_ids
        for seed in seeds
    ]
    if jobs > 1:
        with ProcessPoolExecutor(max_workers=jobs) as executor:
            runs = list(executor.map(_evaluate_isolated_arguments, arguments))
    else:
        runs = [_evaluate_isolated_arguments(item) for item in arguments]
    statistics = {}
    for scenario_id in scenario_ids:
        scenario_results = [
            {
                "seed": run["seed"],
                "scenarios": {scenario_id: run["scenario"]},
            }
            for run in runs
            if run["scenario_id"] == scenario_id
        ]
        statistics[scenario_id] = summarize_scenario_statistics(scenario_results)["scenarios"][
            scenario_id
        ]
    benchmark = build_benchmark_manifest()
    manifest: dict[str, object] = {
        "schema": SCENARIO_ISOLATION_MATRIX_SCHEMA,
        "benchmark_version": BENCHMARK_VERSION,
        "benchmark_manifest_digest": document_digest(benchmark),
        "partitions": {key: list(value) for key, value in SEED_PARTITIONS.items()},
        "scenario_cycle_seconds": scenario_cycle_seconds,
        "frame_seconds": frame_seconds,
        "integration_step_seconds": integration_step_seconds,
        "scenario_ids": list(scenario_ids),
        "run_count": len(runs),
        "runs": runs,
        "statistics": statistics,
        "passed": all(bool(run["passed"]) for run in runs),
        "failed_runs": [
            {
                "seed": run["seed"],
                "scenario_id": run["scenario_id"],
                "failures": run["failures"],
            }
            for run in runs
            if not run["passed"]
        ],
    }
    manifest["matrix_digest"] = document_digest(manifest)
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(canonical_json_bytes(manifest) + b"\n")
    return manifest


def _evaluate_isolated_arguments(
    arguments: tuple[int, str, float, float, float],
) -> dict[str, object]:
    seed, scenario_id, cycle, frame, integration = arguments
    result = evaluate_seed(
        seed,
        scenario_cycle_seconds=cycle,
        frame_seconds=frame,
        integration_step_seconds=integration,
        scenario_ids=(scenario_id,),
    )
    return {
        "seed": seed,
        "scenario_id": scenario_id,
        "frames": result["frames"],
        "scenario": result["scenarios"][scenario_id],
        "passed": result["passed"],
        "failures": result["failures"],
        "evaluation_digest": document_digest(result),
    }


def _fit_centroids(
    training: list[tuple[str, tuple[float, ...]]], width: int, labels: tuple[str, ...]
) -> tuple[Callable[[tuple[float, ...]], tuple[float, ...]], dict[str, tuple[float, ...]]]:
    """A nearest-centroid baseline: the z-score of each feature over ``training`` (a feature
    that never moves keeps a scale of 1) and each label's mean normalized row."""

    means = tuple(fmean(row[index] for _, row in training) for index in range(width))
    scales = []
    for index in range(width):
        values = [row[index] for _, row in training]
        scale = stdev(values) if len(values) > 1 else 0.0
        scales.append(scale or 1.0)

    def normalize(row: tuple[float, ...]) -> tuple[float, ...]:
        return tuple((value - means[index]) / scales[index] for index, value in enumerate(row))

    centroids = {
        label: tuple(
            fmean(normalize(row)[index] for truth, row in training if truth == label)
            for index in range(width)
        )
        for label in labels
    }
    return normalize, centroids
