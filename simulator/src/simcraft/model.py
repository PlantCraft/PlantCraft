"""Numerical parameterization for the grey-box plant model.

All dynamic states are normalized before conversion to engineering units.  This
keeps the benchmark readable while the catalog retains physical names, units,
and normal ranges.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from itertools import pairwise

from .catalog import Catalog, LoopDefinition


@dataclass(frozen=True)
class LoopParameters:
    process_gain: float
    time_constant_seconds: float
    dead_time_seconds: float
    controller_gain: float
    integral_time_seconds: float
    actuator_time_seconds: float
    noise_standard_deviation: float
    actuator_rate_limit_per_second: float = 0.025
    integral_lower_limit: float = -0.50
    integral_upper_limit: float = 0.50
    stiction_band: float = 0.055
    backlash_band: float = 0.035
    lower_limit: float = 0.0
    upper_limit: float = 1.0


@dataclass(frozen=True)
class CouplingEdge:
    source_loop_id: str
    target_loop_id: str
    gain: float
    delay_seconds: float
    mechanism: str


@dataclass(frozen=True)
class LoopModelDefinition:
    loop_id: str
    control_structure: str
    controller_action: str
    default_mode: str
    setpoint_policy: str
    final_element_policy: str
    parameters: LoopParameters


CONTROL_STRUCTURE_POLICIES: dict[str, tuple[str, str, str, float]] = {
    "feedback_pid": ("AUTO", "local", "single", 0.0),
    "inventory_control": ("AUTO", "inventory", "single", 0.0),
    "cascade_primary": ("CAS", "cascade", "single", 0.35),
    "cascade_secondary": ("CAS", "cascade", "single", 0.35),
    "supervisory_bias": ("REMOTE", "supervisory_bias", "single", 1.0),
    "split_range": ("AUTO", "local", "split_range", 0.0),
    "ratio_control": ("CAS", "ratio", "single", 0.5),
    "override_selector": ("AUTO", "protective_selector", "single", 0.0),
    "plant_master": ("REMOTE", "plant_master", "single", 1.0),
    "three_element": ("CAS", "three_element", "single", 0.35),
}

SCENARIO_PARAMETERS: dict[str, dict[str, float | str]] = {
    "normal.steady": {"activation": "disabled"},
    "normal.load_change": {"onset_phase": 0.45, "end_phase": 0.68, "setpoint_step": 0.08},
    "control.aggressive_tuning": {"controller_gain_scale": 2.1, "integral_time_scale": 0.55},
    "control.sluggish_tuning": {
        "controller_gain_scale": 0.38,
        "integral_time_scale": 2.4,
        "setpoint_step": 0.06,
    },
    "control.oscillation": {"disturbance_amplitude": 0.075, "period_seconds": 540.0},
    "control.propagated_oscillation": {"source_amplitude": 0.10, "period_seconds": 540.0},
    "valve.stiction": {"stick_band": 0.055},
    "valve.backlash": {"reversal_band": 0.035},
    "actuator.saturation": {"upper_capacity": 0.67, "active_setpoint_step": 0.25},
    "operations.manual": {"output_amplitude": 0.06, "cycles_per_window": 3.0},
    "operations.setpoint_activity": {"ramp_span": 0.20},
    "sensor.noise": {"standard_deviation_scale": 14.0},
    "sensor.drift": {"bias_rate_per_second": 0.000012, "recovery_time_seconds": 1800.0},
    "sensor.frozen": {"hold": "last_measurement"},
    "data.gap": {"publication": "omit"},
    "data.bad_quality": {"status": "Bad"},
    "data.communication_loss": {"publication": "omit"},
    "data.irregular_cadence": {"maximum_jitter_seconds": 7.0, "skip_fraction": 0.20},
    "process.disturbance": {"step_amplitude": 0.085},
    "process.interaction": {
        "coupling_gain_scale": 2.0,
        "source_driver_amplitude": 0.12,
        "source_driver_period_seconds": 720.0,
    },
}


_KIND_PARAMETERS: dict[str, LoopParameters] = {
    "flow": LoopParameters(0.82, 65.0, 6.0, 1.15, 55.0, 5.0, 0.0025),
    "pressure": LoopParameters(0.70, 105.0, 12.0, 1.25, 80.0, 7.0, 0.0020),
    "temperature": LoopParameters(0.58, 310.0, 35.0, 1.05, 220.0, 12.0, 0.0015),
    "level": LoopParameters(0.42, 420.0, 8.0, 0.70, 360.0, 8.0, 0.0012),
    "analyzer": LoopParameters(0.45, 480.0, 75.0, 0.85, 420.0, 15.0, 0.0030),
    "ratio": LoopParameters(0.76, 95.0, 10.0, 1.00, 80.0, 6.0, 0.0020),
    "speed": LoopParameters(0.88, 45.0, 4.0, 1.10, 35.0, 3.0, 0.0015),
}


def parameters_for(loop: LoopDefinition) -> LoopParameters:
    """Return transparent, deterministic parameters for a loop class."""

    base = _KIND_PARAMETERS[loop.loop_kind]
    digest = hashlib.sha256(loop.loop_id.encode()).digest()
    spread = (digest[0] / 255.0) - 0.5
    time_scale = 1.0 + 0.24 * spread
    gain_scale = 1.0 + 0.16 * ((digest[1] / 255.0) - 0.5)
    return LoopParameters(
        process_gain=base.process_gain * gain_scale,
        time_constant_seconds=base.time_constant_seconds * time_scale,
        dead_time_seconds=base.dead_time_seconds,
        controller_gain=base.controller_gain,
        integral_time_seconds=base.integral_time_seconds,
        actuator_time_seconds=base.actuator_time_seconds,
        noise_standard_deviation=base.noise_standard_deviation,
    )


def model_definition_for(loop: LoopDefinition) -> LoopModelDefinition:
    """Return the complete inspectable dynamic definition for one loop."""

    try:
        default_mode, setpoint_policy, final_element_policy, _ = CONTROL_STRUCTURE_POLICIES[
            loop.control_structure
        ]
    except KeyError as error:
        raise ValueError(f"unsupported control structure: {loop.control_structure}") from error
    return LoopModelDefinition(
        loop_id=loop.loop_id,
        control_structure=loop.control_structure,
        controller_action="reverse",
        default_mode=default_mode,
        setpoint_policy=setpoint_policy,
        final_element_policy=final_element_policy,
        parameters=parameters_for(loop),
    )


def validate_model(catalog: Catalog) -> tuple[str, ...]:
    """Validate numerical and structural invariants before runtime starts."""

    errors: list[str] = []
    for loop in catalog.loops:
        if loop.control_structure not in CONTROL_STRUCTURE_POLICIES:
            errors.append(f"{loop.loop_id} has an unsupported control structure")
            continue
        try:
            parameters = parameters_for(loop)
        except KeyError:
            errors.append(f"{loop.loop_id} has an unsupported loop kind")
            continue
        positive = (
            parameters.process_gain,
            parameters.time_constant_seconds,
            parameters.controller_gain,
            parameters.integral_time_seconds,
            parameters.actuator_time_seconds,
            parameters.actuator_rate_limit_per_second,
        )
        if any(not math.isfinite(value) or value <= 0 for value in positive):
            errors.append(f"{loop.loop_id} has invalid positive model parameters")
        if not 0 <= parameters.dead_time_seconds < parameters.time_constant_seconds:
            errors.append(f"{loop.loop_id} has invalid dead time")
        if not (
            parameters.lower_limit < parameters.upper_limit
            and parameters.integral_lower_limit < parameters.integral_upper_limit
        ):
            errors.append(f"{loop.loop_id} has invalid state limits")
    edges = build_coupling_graph(catalog)
    identities = {(edge.source_loop_id, edge.target_loop_id, edge.mechanism) for edge in edges}
    if len(identities) != len(edges):
        errors.append("coupling graph contains duplicate identities")
    if any(
        not math.isfinite(edge.gain)
        or not math.isfinite(edge.delay_seconds)
        or edge.delay_seconds <= 0
        for edge in edges
    ):
        errors.append("coupling graph contains invalid gain or delay")
    return tuple(errors)


def build_coupling_graph(catalog: Catalog) -> tuple[CouplingEdge, ...]:
    """Build a sparse declared plant-wide graph from process order and utilities."""

    by_area: dict[str, list[str]] = {}
    for loop in catalog.loops:
        by_area.setdefault(loop.area_code, []).append(loop.loop_id)
    edges: list[CouplingEdge] = []
    for area, loop_ids in by_area.items():
        for source, target in pairwise(loop_ids):
            edges.append(CouplingEdge(source, target, 0.035, 45.0, f"within_{area.lower()}"))
    cross_area = (
        ("FIC-101", "FIC-201", 0.085, 90.0, "feed_to_distillation"),
        ("FIC-201", "FIC-301", 0.060, 180.0, "distillation_to_hydrotreating"),
        ("FIC-301", "FIC-403", 0.055, 120.0, "hydrogen_demand"),
        ("AIC-405", "AIC-307", 0.045, 240.0, "hydrogen_purity_to_product_quality"),
        ("PIC-502", "TIC-104", 0.050, 75.0, "fuel_header_to_furnace"),
        ("PIC-601", "TIC-204", 0.050, 100.0, "steam_header_to_reboiler"),
        ("FIC-701", "PIC-202", -0.055, 80.0, "cooling_water_to_column_pressure"),
        ("PIC-703", "LIC-103", 0.050, 40.0, "instrument_air_to_valve_response"),
        ("FIC-901", "AIC-904", 0.045, 300.0, "wastewater_load_to_quality"),
        ("PIC-1001", "LIC-1002", 0.055, 30.0, "flare_load_to_knockout_drum"),
    )
    edges.extend(CouplingEdge(*edge) for edge in cross_area)
    return tuple(edges)
