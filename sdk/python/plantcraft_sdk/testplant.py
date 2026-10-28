"""The Simulator's loop portfolio, recomputed for app tests: the same closed-loop equations as
The Simulator's ``simcraft.loops.dynamics.simulate_step`` (Apache-2.0, same authors), for a few
loops, so an app's tests read the demo plant without running the Simulator::

    from plantcraft_sdk.testplant import plant_fake
    fake = plant_fake("twincraft", "PlantCraft Twin", "/twin/")   # 12 h of 5 loops to NOW

Apps never import each other or the Simulator: this is one copy of the public equations, kept small
and shared by every app's ``tests/plant.py``. Each loop's
behaviour is the Simulator's ground truth: ``healthy`` and ``setpoint_activity`` follow the model,
``disturbance`` adds -8 then +5.5 to the process in fixed windows of every 4 hours,
``sensor_drift`` adds a bias growing 7 units a day (up to 9).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import cache
from typing import Any

import pandas as pd

from plantcraft_sdk.testing import FakePlantCraft


@dataclass(frozen=True)
class Loop:
    loop_id: str
    behavior: str
    base_pv: float
    tau: float
    theta: float
    seed: int
    gain: float = 0.55
    kc: float = 1.25
    ki: float = 0.16
    process_noise: float = 0.03
    measurement_noise: float = 0.08


# The Simulator's furnace area (LOOP_DEFINITIONS, area "Furnaces") and two more loops.
FURNACES = (
    Loop("TIC-1104", "disturbance", 68.0, 320.0, 15.0, 114),
    Loop("TIC-1209", "sensor_drift", 69.0, 340.0, 15.0, 133),
    Loop("FIC-1210", "setpoint_activity", 57.0, 150.0, 15.0, 134),
)
HEALTHY = Loop(
    "FIC-1001",
    "healthy",
    55.0,
    110.0,
    8.0,
    101,
    kc=1.10,
    ki=0.12,
    process_noise=0.025,
    measurement_noise=0.05,
)
INTERACTION = Loop(
    "LIC-1010",
    "interaction",
    51.0,
    190.0,
    20.0,
    110,
    kc=1.15,
    ki=0.13,
    process_noise=0.02,
    measurement_noise=0.05,
)
LOOPS = (*FURNACES, HEALTHY, INTERACTION)


def _noise(seed: int, timestamp: float, channel: int = 0) -> float:
    x = timestamp * (0.017 + channel * 0.0031) + seed * 17.173
    u1 = abs(math.sin(x * 12.9898) * 43758.5453) % 1.0
    u2 = abs(math.sin((x + 19.19) * 78.233) * 12345.6789) % 1.0
    u1 = max(u1, 1e-9)
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


def _setpoint(loop: Loop, epoch: float) -> float:
    if loop.behavior == "setpoint_activity":
        values = (46.0, 57.0, 64.0, 51.0, 59.0, 49.0)
        return values[int(epoch // 1800) % len(values)]
    if loop.behavior == "healthy":
        return loop.base_pv + (2.5 if int(epoch // 21600) % 2 else 0.0)
    return loop.base_pv


def secondary(loop: Loop, epoch: float) -> float:
    """The measured flow of an ``interaction`` loop (the Simulator's SECONDARY signal)."""

    base = 50.0 + 8.5 * math.sin(2.0 * math.pi * epoch / 1200.0)
    return base + 0.25 * _noise(loop.seed, epoch, 4)


def disturbance(loop: Loop, epoch: float) -> float:
    if loop.behavior == "interaction":
        return 0.58 * (secondary(loop, epoch) - 50.0)
    if loop.behavior == "disturbance":
        phase = epoch % 14400.0
        if 3600.0 <= phase < 6600.0:
            return -8.0
        if 9000.0 <= phase < 10800.0:
            return 5.5
    return 0.0


@dataclass
class _State:
    true_pv: float
    measured_pv: float
    integral: float = 0.0
    bias: float = 0.0
    buffer: list[tuple[float, float]] = field(default_factory=list)


def run(loop: Loop, start: datetime, hours: float, step: float = 1.0, every: float = 5.0):
    """``{role: series}`` of ``loop`` from ``start`` (PV, SP, OP and, for an ``interaction``
    loop, SECONDARY), one value every ``every`` seconds."""

    state = _State(loop.base_pv, loop.base_pv)
    stamps, pv, sp, op, second = [], [], [], [], []
    begin = start.timestamp()
    steps = int(hours * 3600 / step)
    for index in range(steps + 1):
        epoch = begin + index * step
        target_sp = _setpoint(loop, epoch)
        error = target_sp - state.measured_pv
        state.integral = max(-180.0, min(180.0, state.integral + error * step / 60.0))
        out = max(0.0, min(100.0, 50.0 + loop.kc * error + loop.ki * state.integral))
        # The Simulator's delay line: the output of ``theta`` seconds ago (the first one before).
        state.buffer.append((epoch, out))
        back = int(loop.theta / step)
        delayed = state.buffer[max(0, len(state.buffer) - 1 - back)][1]
        if len(state.buffer) > 2 * back + 10:
            del state.buffer[: len(state.buffer) - back - 5]
        target = loop.base_pv + loop.gain * (delayed - 50.0) + disturbance(loop, epoch)
        alpha = 1.0 - math.exp(-step / loop.tau)
        state.true_pv += alpha * (target - state.true_pv) + loop.process_noise * math.sqrt(
            max(step, 1.0)
        ) * _noise(loop.seed, epoch, 1)
        if loop.behavior == "sensor_drift":
            state.bias = min(9.0, state.bias + step * 7.0 / 86400.0)
        state.measured_pv = (
            state.true_pv + state.bias + loop.measurement_noise * _noise(loop.seed, epoch, 2)
        )
        if index % int(every / step) == 0:
            stamps.append(datetime.fromtimestamp(epoch, timezone.utc))
            pv.append(state.measured_pv)
            sp.append(target_sp)
            op.append(out)
            second.append(secondary(loop, epoch))
    index = pd.DatetimeIndex(stamps)
    found = {"PV": pd.Series(pv, index), "SP": pd.Series(sp, index), "OP": pd.Series(op, index)}
    if loop.behavior == "interaction":
        found["SECONDARY"] = pd.Series(second, index)
    return found


def series(loops, start: datetime, hours: float, source: str = "plantcraft") -> dict:
    """``{signal id: values}`` for the PV, SP and OP of every loop, as PlantCraft names them."""

    found = {}
    for loop in loops:
        for role, values in run(loop, start, hours).items():
            found[f"{source}:CPM.Loops.{loop.loop_id}.{role}"] = values
    return found


# The test plant every app's tests read: 12 hours of LOOPS ending at NOW, on source "plantcraft".
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
HOURS = 12
START = NOW - timedelta(hours=HOURS)
SOURCE = "plantcraft"
APP_KEY = "test-app-key"


@cache
def plant_series() -> dict[str, pd.Series]:
    return series(LOOPS, START, HOURS, source=SOURCE)


def plant_signals() -> list[dict[str, Any]]:
    return [
        {
            "id": signal_id,
            "name": signal_id.partition(":")[2],
            "source": SOURCE,
            "unit": "",
            "description": signal_id.partition(":")[2],
            "low": None,
            "high": None,
        }
        for signal_id in plant_series()
    ]


def plant_assets() -> list[dict[str, Any]]:
    """The site, unit ``U-SIM`` and one loop asset per loop with its signal roles."""

    found = [
        {"id": "plant", "name": "Plant", "kind": "site", "parent_id": None, "attributes": {}},
        {
            "id": "U-SIM",
            "name": "Simulated unit",
            "kind": "unit",
            "parent_id": "plant",
            "attributes": {},
        },
    ]
    for loop in LOOPS:
        roles = {
            role.lower(): signal_id
            for signal_id in plant_series()
            if signal_id.startswith(f"{SOURCE}:CPM.Loops.{loop.loop_id}.")
            for role in [signal_id.rsplit(".", 1)[-1]]
        }
        found.append(
            {
                "id": loop.loop_id,
                "name": loop.loop_id,
                "kind": "loop",
                "parent_id": "U-SIM",
                "attributes": {"description": loop.behavior},
                "signals": roles,
            }
        )
    return found


def plant_users(app_id: str) -> dict[str, dict[str, Any]]:
    """The four people every app's tests sign in as.

    | User | Level | The app |
    |---|---|---|
    | ``admin`` | admin | editor |
    | ``engineer`` | editor | editor |
    | ``operator`` | viewer | viewer |
    | ``outsider`` | viewer | none |
    """

    return {
        "admin": {"name": "Administrator", "level": "admin", "apps": {app_id: "editor"}},
        "engineer": {"name": "Process Engineer", "level": "editor", "apps": {app_id: "editor"}},
        "operator": {"name": "Operator", "level": "viewer", "apps": {app_id: "viewer"}},
        "outsider": {"name": "No Apps", "level": "viewer", "apps": {}},
    }


def plant_fake(app_id: str, name: str, url: str, **options: Any) -> FakePlantCraft:
    """A ``FakePlantCraft`` serving the test plant to one app (its users, app key ``APP_KEY``)."""

    return FakePlantCraft(
        users=plant_users(app_id),
        apps=[{"id": app_id, "name": name, "url": url, "version": "0.1.0"}],
        app_keys={app_id: APP_KEY},
        assets=plant_assets(),
        signals=plant_signals(),
        series={key: value.copy() for key, value in plant_series().items()},
        now=NOW,
        **options,
    )
