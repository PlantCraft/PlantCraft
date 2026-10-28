"""Small, deterministic closed-loop models of the 50-loop portfolio (PlantCraft demo)."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

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

    @property
    def signal_names(self) -> tuple[str, ...]:
        base = ("PV", "SP", "OP", "MODE")
        return (*base, "SECONDARY") if self.has_secondary else base

    def tag(self, signal: str) -> str:
        return f"CPM.Loops.{self.loop_id}.{signal}"


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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> LoopState:
        values = dict(payload)
        values["delay_buffer"] = [
            (float(item[0]), float(item[1])) for item in values.get("delay_buffer", [])
        ]
        return cls(**values)


LOOP_DEFINITIONS: tuple[LoopDefinition, ...] = (
    LoopDefinition(
        loop_id="FIC-1001",
        name="Feed flow",
        area="Feed",
        service="Healthy, well-tuned loop",
        pv_unit="m³/h",
        behavior="healthy",
        seed=101,
        base_sp=55.0,
        base_pv=55.0,
        time_constant_seconds=110.0,
        dead_time_seconds=8.0,
        controller_gain=1.10,
        integral_gain=0.12,
        process_noise=0.025,
        measurement_noise=0.05,
    ),
    LoopDefinition(
        loop_id="PIC-1002",
        name="Vessel pressure",
        area="Separation",
        service="Persistent oscillation from aggressive tuning",
        pv_unit="bar",
        behavior="oscillation",
        seed=102,
        base_sp=52.0,
        base_pv=52.0,
        time_constant_seconds=95.0,
        dead_time_seconds=28.0,
        controller_gain=2.40,
        integral_gain=0.42,
        process_noise=0.035,
        measurement_noise=0.08,
    ),
    LoopDefinition(
        loop_id="FIC-1003",
        name="Recycle flow",
        area="Recycle",
        service="Valve with static friction and jumpy movement",
        pv_unit="m³/h",
        behavior="stiction",
        seed=103,
        base_sp=58.0,
        base_pv=58.0,
        time_constant_seconds=130.0,
        dead_time_seconds=12.0,
        controller_gain=1.55,
        integral_gain=0.24,
        process_noise=0.02,
        measurement_noise=0.05,
        stiction_band=3.2,
    ),
    LoopDefinition(
        loop_id="LIC-1004",
        name="Separator level",
        area="Separation",
        service="Undersized actuator with output at the upper limit",
        pv_unit="%",
        behavior="saturation",
        seed=104,
        base_sp=85.0,
        base_pv=49.0,
        process_gain=0.42,
        time_constant_seconds=260.0,
        dead_time_seconds=25.0,
        controller_gain=2.10,
        integral_gain=0.38,
        process_noise=0.025,
        measurement_noise=0.07,
    ),
    LoopDefinition(
        loop_id="TIC-1005",
        name="Reactor temperature",
        area="Reaction",
        service="Long periods in manual mode",
        pv_unit="°C",
        behavior="manual",
        seed=105,
        base_sp=62.0,
        base_pv=62.0,
        time_constant_seconds=310.0,
        dead_time_seconds=35.0,
        controller_gain=1.40,
        integral_gain=0.15,
        process_noise=0.02,
        measurement_noise=0.05,
    ),
    LoopDefinition(
        loop_id="AIC-1006",
        name="Product composition",
        area="Quality",
        service="Measurement with high-frequency noise",
        pv_unit="mol%",
        behavior="noise",
        seed=106,
        base_sp=50.0,
        base_pv=50.0,
        time_constant_seconds=180.0,
        dead_time_seconds=18.0,
        controller_gain=1.05,
        integral_gain=0.11,
        process_noise=0.015,
        measurement_noise=1.45,
    ),
    LoopDefinition(
        loop_id="FIC-1007",
        name="Charge flow",
        area="Feed",
        service="Frequent setpoint changes per campaign",
        pv_unit="m³/h",
        behavior="setpoint_activity",
        seed=107,
        base_sp=54.0,
        base_pv=54.0,
        time_constant_seconds=125.0,
        dead_time_seconds=10.0,
        controller_gain=1.25,
        integral_gain=0.18,
        process_noise=0.025,
        measurement_noise=0.06,
    ),
    LoopDefinition(
        loop_id="PIC-1008",
        name="Header pressure",
        area="Utilities",
        service="Slow pressure sensor drift",
        pv_unit="bar",
        behavior="sensor_drift",
        seed=108,
        base_sp=57.0,
        base_pv=57.0,
        time_constant_seconds=165.0,
        dead_time_seconds=14.0,
        controller_gain=1.10,
        integral_gain=0.12,
        process_noise=0.02,
        measurement_noise=0.05,
    ),
    LoopDefinition(
        loop_id="TIC-1009",
        name="Outlet temperature",
        area="Heat exchange",
        service="Recurring load disturbances",
        pv_unit="°C",
        behavior="disturbance",
        seed=109,
        base_sp=60.0,
        base_pv=60.0,
        time_constant_seconds=230.0,
        dead_time_seconds=22.0,
        controller_gain=1.30,
        integral_gain=0.16,
        process_noise=0.025,
        measurement_noise=0.06,
    ),
    LoopDefinition(
        loop_id="LIC-1010",
        name="Interface level",
        area="Separation",
        service="Interaction with the light phase flow",
        pv_unit="%",
        behavior="interaction",
        seed=110,
        base_sp=51.0,
        base_pv=51.0,
        time_constant_seconds=190.0,
        dead_time_seconds=20.0,
        controller_gain=1.15,
        integral_gain=0.13,
        process_noise=0.02,
        measurement_noise=0.05,
        has_secondary=True,
    ),
)

LOOP_DEFINITIONS = (
    *LOOP_DEFINITIONS,
    LoopDefinition(
        loop_id="FIC-1101",
        name="Column charge flow",
        area="Distillation",
        service="Stable charge tracking",
        pv_unit="m³/h",
        behavior="healthy",
        seed=111,
        base_sp=63.0,
        base_pv=63.0,
        time_constant_seconds=105.0,
    ),
    LoopDefinition(
        loop_id="FIC-1102",
        name="Reflux flow",
        area="Distillation",
        service="Stepwise valve movement",
        pv_unit="m³/h",
        behavior="stiction",
        seed=112,
        base_sp=48.0,
        base_pv=48.0,
        stiction_band=2.8,
    ),
    LoopDefinition(
        loop_id="PIC-1103",
        name="Suction pressure",
        area="Compression",
        service="Persistent pressure oscillation",
        pv_unit="bar",
        behavior="oscillation",
        seed=113,
        base_sp=46.0,
        base_pv=46.0,
        controller_gain=2.2,
        integral_gain=0.38,
        dead_time_seconds=26.0,
    ),
    LoopDefinition(
        loop_id="TIC-1104",
        name="Furnace temperature",
        area="Furnaces",
        service="Recovery after load disturbances",
        pv_unit="°C",
        behavior="disturbance",
        seed=114,
        base_sp=68.0,
        base_pv=68.0,
        time_constant_seconds=320.0,
    ),
    LoopDefinition(
        loop_id="LIC-1105",
        name="Surge drum level",
        area="Separation",
        service="Attenuation of feed variations",
        pv_unit="%",
        behavior="disturbance",
        seed=115,
        base_sp=50.0,
        base_pv=50.0,
        time_constant_seconds=280.0,
        controller_gain=0.72,
        integral_gain=0.06,
    ),
    LoopDefinition(
        loop_id="LIC-1106",
        name="Accumulator level",
        area="Distillation",
        service="Inventory within the operating range",
        pv_unit="%",
        behavior="healthy",
        seed=116,
        base_sp=52.0,
        base_pv=52.0,
        time_constant_seconds=300.0,
        controller_gain=0.68,
        integral_gain=0.05,
    ),
    LoopDefinition(
        loop_id="LIC-1107",
        name="Interface level (treating)",
        area="Treating",
        service="Attenuation with a correlated disturbance",
        pv_unit="%",
        behavior="interaction",
        seed=117,
        base_sp=49.0,
        base_pv=49.0,
        time_constant_seconds=260.0,
        controller_gain=0.75,
        integral_gain=0.06,
        has_secondary=True,
    ),
    LoopDefinition(
        loop_id="AIC-1108",
        name="Stream composition",
        area="Quality",
        service="Analyzer with high noise",
        pv_unit="mol%",
        behavior="noise",
        seed=118,
        base_sp=55.0,
        base_pv=55.0,
        measurement_noise=1.2,
    ),
    LoopDefinition(
        loop_id="FIC-1109",
        name="Steam flow",
        area="Utilities",
        service="Actuator restriction and saturation",
        pv_unit="t/h",
        behavior="saturation",
        seed=119,
        base_sp=82.0,
        base_pv=48.0,
        process_gain=0.42,
        controller_gain=2.0,
        integral_gain=0.34,
    ),
    LoopDefinition(
        loop_id="PIC-1110",
        name="Network pressure",
        area="Utilities",
        service="Recurring manual operation",
        pv_unit="bar",
        behavior="manual",
        seed=120,
        base_sp=58.0,
        base_pv=58.0,
    ),
    LoopDefinition(
        loop_id="TIC-1111",
        name="Product temperature",
        area="Heat exchange",
        service="Slow measurement drift",
        pv_unit="°C",
        behavior="sensor_drift",
        seed=121,
        base_sp=61.0,
        base_pv=61.0,
        time_constant_seconds=240.0,
    ),
    LoopDefinition(
        loop_id="FIC-1112",
        name="Production flow",
        area="Feed",
        service="Frequent setpoint interventions",
        pv_unit="m³/h",
        behavior="setpoint_activity",
        seed=122,
        base_sp=56.0,
        base_pv=56.0,
    ),
    LoopDefinition(
        loop_id="LIC-1113",
        name="Reflux drum level",
        area="Distillation",
        service="Operating range compromised by saturation",
        pv_unit="%",
        behavior="saturation",
        seed=123,
        base_sp=84.0,
        base_pv=48.0,
        process_gain=0.4,
        time_constant_seconds=300.0,
        controller_gain=1.8,
        integral_gain=0.3,
    ),
    LoopDefinition(
        loop_id="TIC-1114",
        name="Stabilizer temperature",
        area="Treating",
        service="Stable tracking reference",
        pv_unit="°C",
        behavior="healthy",
        seed=124,
        base_sp=59.0,
        base_pv=59.0,
        time_constant_seconds=210.0,
    ),
    LoopDefinition(
        loop_id="FIC-1201",
        name="Hydrotreater charge flow",
        area="Hydrotreating",
        service="Stable tracking of the unit's charge",
        pv_unit="m³/h",
        behavior="healthy",
        seed=125,
        base_sp=64.0,
        base_pv=64.0,
        time_constant_seconds=115.0,
    ),
    LoopDefinition(
        loop_id="PIC-1202",
        name="Reactor inlet pressure",
        area="Hydrotreating",
        service="Oscillation tied to aggressive tuning",
        pv_unit="bar",
        behavior="oscillation",
        seed=126,
        base_sp=56.0,
        base_pv=56.0,
        controller_gain=2.25,
        integral_gain=0.39,
        dead_time_seconds=27.0,
    ),
    LoopDefinition(
        loop_id="TIC-1203",
        name="Catalyst bed temperature",
        area="Hydrotreating",
        service="Response to thermal load variations",
        pv_unit="°C",
        behavior="disturbance",
        seed=127,
        base_sp=66.0,
        base_pv=66.0,
        time_constant_seconds=330.0,
    ),
    LoopDefinition(
        loop_id="LIC-1204",
        name="High-pressure separator level",
        area="Hydrotreating",
        service="Stable inventory in the operating range",
        pv_unit="%",
        behavior="healthy",
        seed=128,
        base_sp=51.0,
        base_pv=51.0,
        time_constant_seconds=290.0,
        controller_gain=0.7,
        integral_gain=0.05,
    ),
    LoopDefinition(
        loop_id="AIC-1205",
        name="Hydrogen purity",
        area="Hydrotreating",
        service="Analyzer with measurement noise",
        pv_unit="mol%",
        behavior="noise",
        seed=129,
        base_sp=58.0,
        base_pv=58.0,
        measurement_noise=1.15,
    ),
    LoopDefinition(
        loop_id="FIC-1206",
        name="Quench flow",
        area="Hydrotreating",
        service="Valve with friction and stepwise movement",
        pv_unit="m³/h",
        behavior="stiction",
        seed=130,
        base_sp=47.0,
        base_pv=47.0,
        stiction_band=2.6,
    ),
    LoopDefinition(
        loop_id="PIC-1207",
        name="Compressor discharge pressure",
        area="Compression",
        service="Output limited during high demand",
        pv_unit="bar",
        behavior="saturation",
        seed=131,
        base_sp=83.0,
        base_pv=49.0,
        process_gain=0.43,
        controller_gain=2.05,
        integral_gain=0.35,
    ),
    LoopDefinition(
        loop_id="LIC-1208",
        name="Suction drum level",
        area="Compression",
        service="Level influenced by the compressor load",
        pv_unit="%",
        behavior="interaction",
        seed=132,
        base_sp=50.0,
        base_pv=50.0,
        time_constant_seconds=275.0,
        controller_gain=0.72,
        integral_gain=0.06,
        has_secondary=True,
    ),
    LoopDefinition(
        loop_id="TIC-1209",
        name="Furnace outlet temperature",
        area="Furnaces",
        service="Slow drift of the temperature element",
        pv_unit="°C",
        behavior="sensor_drift",
        seed=133,
        base_sp=69.0,
        base_pv=69.0,
        time_constant_seconds=340.0,
    ),
    LoopDefinition(
        loop_id="FIC-1210",
        name="Fuel gas flow",
        area="Furnaces",
        service="Setpoint changes per operating campaign",
        pv_unit="Nm³/h",
        behavior="setpoint_activity",
        seed=134,
        base_sp=57.0,
        base_pv=57.0,
    ),
    LoopDefinition(
        loop_id="LIC-1211",
        name="Flash drum level",
        area="Distillation",
        service="Attenuation of feed disturbances",
        pv_unit="%",
        behavior="disturbance",
        seed=135,
        base_sp=48.0,
        base_pv=48.0,
        time_constant_seconds=310.0,
        controller_gain=0.66,
        integral_gain=0.05,
    ),
    LoopDefinition(
        loop_id="PIC-1212",
        name="Flare header pressure",
        area="Utilities",
        service="Recurring manual operation during transients",
        pv_unit="bar",
        behavior="manual",
        seed=136,
        base_sp=53.0,
        base_pv=53.0,
    ),
    LoopDefinition(
        loop_id="TIC-1213",
        name="Column top temperature",
        area="Distillation",
        service="Stable tracking of the specification",
        pv_unit="°C",
        behavior="healthy",
        seed=137,
        base_sp=60.0,
        base_pv=60.0,
        time_constant_seconds=235.0,
    ),
    LoopDefinition(
        loop_id="FIC-1214",
        name="Side draw flow",
        area="Distillation",
        service="Static friction in the product valve",
        pv_unit="m³/h",
        behavior="stiction",
        seed=138,
        base_sp=52.0,
        base_pv=52.0,
        stiction_band=3.0,
    ),
    LoopDefinition(
        loop_id="AIC-1215",
        name="Sulfur content in product",
        area="Quality",
        service="Analyzer subject to high-frequency noise",
        pv_unit="ppm",
        behavior="noise",
        seed=139,
        base_sp=45.0,
        base_pv=45.0,
        measurement_noise=1.3,
    ),
    LoopDefinition(
        loop_id="LIC-1216",
        name="Amine absorber level",
        area="Treating",
        service="Stable inventory with good attenuation",
        pv_unit="%",
        behavior="healthy",
        seed=140,
        base_sp=54.0,
        base_pv=54.0,
        time_constant_seconds=305.0,
        controller_gain=0.68,
        integral_gain=0.05,
    ),
    LoopDefinition(
        loop_id="PIC-1217",
        name="Medium-pressure steam pressure",
        area="Utilities",
        service="Disturbances from varying consumers",
        pv_unit="bar",
        behavior="disturbance",
        seed=141,
        base_sp=62.0,
        base_pv=62.0,
        time_constant_seconds=175.0,
    ),
    LoopDefinition(
        loop_id="LIC-1218",
        name="Condensate drum level",
        area="Utilities",
        service="Interaction with the steam network demand",
        pv_unit="%",
        behavior="interaction",
        seed=142,
        base_sp=50.0,
        base_pv=50.0,
        time_constant_seconds=285.0,
        controller_gain=0.7,
        integral_gain=0.05,
        has_secondary=True,
    ),
    LoopDefinition(
        loop_id="FIC-1219",
        name="Cooling water flow",
        area="Utilities",
        service="Capacity restriction in the actuator",
        pv_unit="m³/h",
        behavior="saturation",
        seed=143,
        base_sp=81.0,
        base_pv=47.0,
        process_gain=0.44,
        controller_gain=1.95,
        integral_gain=0.33,
    ),
    LoopDefinition(
        loop_id="TIC-1220",
        name="Water return temperature",
        area="Utilities",
        service="Oscillation caused by interaction with consumers",
        pv_unit="°C",
        behavior="oscillation",
        seed=144,
        base_sp=55.0,
        base_pv=55.0,
        controller_gain=2.15,
        integral_gain=0.36,
        dead_time_seconds=25.0,
    ),
    LoopDefinition(
        loop_id="PIC-1221",
        name="Nitrogen network pressure",
        area="Utilities",
        service="Stable pressure reference",
        pv_unit="bar",
        behavior="healthy",
        seed=145,
        base_sp=57.0,
        base_pv=57.0,
        time_constant_seconds=155.0,
    ),
    LoopDefinition(
        loop_id="FIC-1222",
        name="Effluent flow to treatment",
        area="Water treatment",
        service="Frequent setpoint interventions",
        pv_unit="m³/h",
        behavior="setpoint_activity",
        seed=146,
        base_sp=49.0,
        base_pv=49.0,
    ),
    LoopDefinition(
        loop_id="LIC-1223",
        name="Equalization tank level",
        area="Water treatment",
        service="Long periods in manual mode",
        pv_unit="%",
        behavior="manual",
        seed=147,
        base_sp=52.0,
        base_pv=52.0,
        time_constant_seconds=325.0,
        controller_gain=0.65,
        integral_gain=0.05,
    ),
    LoopDefinition(
        loop_id="AIC-1224",
        name="Treated effluent pH",
        area="Water treatment",
        service="Gradual drift of the analytical sensor",
        pv_unit="pH",
        behavior="sensor_drift",
        seed=148,
        base_sp=50.0,
        base_pv=50.0,
        time_constant_seconds=195.0,
    ),
    LoopDefinition(
        loop_id="LIC-1225",
        name="Slop tank level",
        area="Water treatment",
        service="Inventory influenced by the unit's load",
        pv_unit="%",
        behavior="interaction",
        seed=149,
        base_sp=47.0,
        base_pv=47.0,
        time_constant_seconds=320.0,
        controller_gain=0.64,
        integral_gain=0.05,
        has_secondary=True,
    ),
    LoopDefinition(
        loop_id="TIC-1226",
        name="Sulfur reactor temperature",
        area="Sulfur recovery",
        service="Thermal disturbances during load changes",
        pv_unit="°C",
        behavior="disturbance",
        seed=150,
        base_sp=67.0,
        base_pv=67.0,
        time_constant_seconds=315.0,
    ),
)


def loop_catalog() -> list[dict[str, Any]]:
    """Every loop as plain data: id, texts, behaviour and the OPC UA tag of each signal."""

    return [
        {
            "loop_id": item.loop_id,
            "name": item.name,
            "area": item.area,
            "service": item.service,
            "pv_unit": item.pv_unit,
            "behavior": item.behavior,
            "signals": {name.lower(): item.tag(name) for name in item.signal_names},
        }
        for item in LOOP_DEFINITIONS
    ]


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
    if definition.behavior == "stiction":
        # A slow load change, as every real line has: it is what makes a sticky valve show. The
        # integral winds up while the valve holds, the valve jumps past, and the loop cycles
        # (stick-slip, several jumps an hour) instead of resting at its setpoint.
        return 2.0 * math.sin(2.0 * math.pi * timestamp / 2400.0)
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
