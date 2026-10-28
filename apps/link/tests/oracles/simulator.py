"""Closed-loop dynamics of the Simulator OPC UA simulator, copied for the simulator oracle.

Source: the Simulator (Apache-2.0, PlantCraft authors), ``src/simcraft/loops/dynamics.py`` at
commit ``3e0a912`` (the same models as PlantCraft's ``processcraft/simulator/dynamics.py``).
The Simulator is not a dependency of LinkCraft (apps never import each other), so the few functions
that generate one loop's samples are copied here unchanged; only the 50-loop portfolio, the OPC UA
tag naming and the state (de)serialisation are left out. Keep this file in step with the source
when its dynamics change, and say so in the commit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Behavior = Literal[
    "healthy",
    "oscillation",
    "stiction",
    "saturation",
    "manual",
    "noise",
    "setpoint_activity",
    "sensor_drift",
    "disturbance",
    "interaction",
]


@dataclass(frozen=True)
class LoopDefinition:
    loop_id: str
    name: str
    area: str
    service: str
    pv_unit: str
    behavior: Behavior
    seed: int
    base_sp: float
    base_pv: float
    process_gain: float = 0.55
    time_constant_seconds: float = 150.0
    dead_time_seconds: float = 15.0
    controller_gain: float = 1.25
    integral_gain: float = 0.16
    process_noise: float = 0.03
    measurement_noise: float = 0.08
    stiction_band: float = 0.0
    has_secondary: bool = False


@dataclass
class LoopState:
    true_pv: float
    measured_pv: float
    integral: float = 0.0
    op: float = 50.0
    valve_position: float = 50.0
    mode: str = "AUTO"
    sensor_bias: float = 0.0
    delay_buffer: list[tuple[float, float]] = field(default_factory=list)


def initial_state(definition: LoopDefinition) -> LoopState:
    return LoopState(
        true_pv=definition.base_pv,
        measured_pv=definition.base_pv,
    )


def _fractional_noise(seed: int, timestamp: float, channel: int = 0) -> float:
    """Return deterministic, approximately Gaussian zero-mean noise."""

    x = timestamp * (0.017 + channel * 0.0031) + seed * 17.173
    u1 = abs(math.sin(x * 12.9898) * 43758.5453) % 1.0
    u2 = abs(math.sin((x + 19.19) * 78.233) * 12345.6789) % 1.0
    u1 = max(u1, 1e-9)
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


def _setpoint(definition: LoopDefinition, timestamp: float) -> float:
    if definition.behavior == "setpoint_activity":
        values = (46.0, 57.0, 64.0, 51.0, 59.0, 49.0)
        return values[int(timestamp // 1800) % len(values)]
    if definition.behavior == "healthy":
        return definition.base_sp + (2.5 if int(timestamp // 21600) % 2 else 0.0)
    return definition.base_sp


def _secondary_signal(definition: LoopDefinition, timestamp: float) -> float:
    base = 50.0 + 8.5 * math.sin(2.0 * math.pi * timestamp / 1200.0)
    return base + 0.25 * _fractional_noise(definition.seed, timestamp, 4)


def _disturbance(
    definition: LoopDefinition,
    timestamp: float,
    secondary: float | None,
) -> float:
    if definition.behavior == "oscillation":
        return 4.8 * math.sin(2.0 * math.pi * timestamp / 720.0)
    if definition.behavior == "disturbance":
        phase = timestamp % 14400.0
        if 3600.0 <= phase < 6600.0:
            return -8.0
        if 9000.0 <= phase < 10800.0:
            return 5.5
    if definition.behavior == "interaction" and secondary is not None:
        return 0.58 * (secondary - 50.0)
    return 0.0


def _delayed_output(
    state: LoopState,
    timestamp: float,
    value: float,
    delay_seconds: float,
) -> float:
    state.delay_buffer.append((timestamp, value))
    target = timestamp - delay_seconds
    delayed = state.delay_buffer[0][1]
    for point_time, point_value in state.delay_buffer:
        if point_time > target:
            break
        delayed = point_value
    retention = max(delay_seconds * 2.0, 600.0)
    state.delay_buffer = [item for item in state.delay_buffer if item[0] >= timestamp - retention]
    return delayed


def simulate_step(
    definition: LoopDefinition,
    state: LoopState,
    timestamp: datetime,
    step_seconds: float,
) -> dict[str, float | str]:
    """Advance one loop and return the published signal values."""

    epoch = timestamp.timestamp()
    dt = max(float(step_seconds), 0.05)
    sp = _setpoint(definition, epoch)
    secondary = _secondary_signal(definition, epoch) if definition.has_secondary else None

    manual_phase = int(epoch // 3600) % 24
    mode = "MAN" if definition.behavior == "manual" and 4 <= manual_phase < 10 else "AUTO"
    state.mode = mode

    if mode == "AUTO":
        error = sp - state.measured_pv
        state.integral = max(
            -180.0,
            min(180.0, state.integral + error * dt / 60.0),
        )
        requested_op = (
            50.0 + definition.controller_gain * error + definition.integral_gain * state.integral
        )
    else:
        requested_op = 43.0 + 2.2 * math.sin(2.0 * math.pi * epoch / 2700.0)
        state.integral *= math.exp(-dt / 900.0)

    state.op = max(0.0, min(100.0, requested_op))
    if definition.behavior == "stiction":
        delta = state.op - state.valve_position
        if abs(delta) >= definition.stiction_band:
            state.valve_position = state.op - math.copysign(
                definition.stiction_band * 0.35,
                delta,
            )
    else:
        state.valve_position = state.op

    delayed_op = _delayed_output(
        state,
        epoch,
        state.valve_position,
        definition.dead_time_seconds,
    )
    disturbance = _disturbance(definition, epoch, secondary)
    process_target = (
        definition.base_pv + definition.process_gain * (delayed_op - 50.0) + disturbance
    )
    alpha = 1.0 - math.exp(-dt / definition.time_constant_seconds)
    process_noise = (
        definition.process_noise
        * math.sqrt(max(dt, 1.0))
        * _fractional_noise(definition.seed, epoch, 1)
    )
    state.true_pv += alpha * (process_target - state.true_pv) + process_noise

    if definition.behavior == "sensor_drift":
        state.sensor_bias = min(9.0, state.sensor_bias + dt * 7.0 / 86400.0)
    measurement_noise = definition.measurement_noise * _fractional_noise(definition.seed, epoch, 2)
    state.measured_pv = state.true_pv + state.sensor_bias + measurement_noise

    published_op = state.valve_position if definition.behavior == "stiction" else state.op
    values: dict[str, float | str] = {
        "PV": round(state.measured_pv, 6),
        "SP": round(sp, 6),
        "OP": round(published_op, 6),
        "MODE": mode,
    }
    if secondary is not None:
        values["SECONDARY"] = round(secondary, 6)
    return values
