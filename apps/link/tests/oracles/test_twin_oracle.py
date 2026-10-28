"""Oracle: PlantCraft Twin's example twins, as algorithms on assets, against the faults the Simulator
injects, with the simulator's own fault schedule (``plantcraft_sdk.testplant``) as the ground
truth. The same judgement Twin passed, now made by Link's model and Deviation (T²) blocks.

Twelve hours of the plant, each twin calibrated with Calibrate on its first calm hour (00:15 to
01:00), every ten-minute run from 01:00 to 12:00 judged and scored:

- **twin_disturbance_found**: runs fully inside TIC-1104's load disturbance that deviate and
  name TIC-1104;
- **twin_drift_found**: calm runs after the TIC-1209 bias passes about 1 °C that deviate and
  name TIC-1209;
- **twin_healthy_quiet**: runs of the healthy FIC-1001 twin and of the LIC-1010 twin (driven by
  its measured flow) that stay normal.

Each score must stay at or above its floor in ``tests/floors.toml``.
"""

from __future__ import annotations

import tomllib
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest
from plantcraft_sdk.blocks import Result
from plantcraft_sdk.testplant import APP_KEY, FURNACES, HOURS, START, disturbance, plant_fake

from linkcraft.assets.calibrate import calibrate_on_asset
from linkcraft.assets.run import AssetTiming, runs_over, segment_ends
from linkcraft.assets.twins import twin_diagram, twin_subject, twin_timing
from linkcraft.blocks import register_models
from linkcraft.blocks.models import ModelRuntime
from linkcraft.db import Database
from linkcraft.models.builtin import register_builtins
from linkcraft.models.simulate import InlinePool
from linkcraft.models.store import ModelStore

pytestmark = pytest.mark.slow

FLOORS = tomllib.loads(
    (Path(__file__).resolve().parents[1] / "floors.toml").read_text(encoding="utf-8")
)["oracles"]
TIC_1104 = FURNACES[0]
LOOP_MODEL = "plantcrafttwin-loopprocess"
FURNACES_MODEL = "plantcrafttwin-furnaces"
FURNACE_LOOPS = ("TIC-1104", "TIC-1209", "FIC-1210")


def _role(loop: str, role: str) -> dict:
    return {"asset_id": loop, "role": role}


def _variable(loop: str) -> str:
    return loop.replace("-", "")


# The three twins PlantCraft Twin creates on the Simulator demo (twincraft.twins.starter).
TWINS = {
    "Furnaces": {
        "asset_id": "U-SIM",
        "model_id": FURNACES_MODEL,
        "inputs": [
            {"variable": f"{_variable(loop)}_OP", "source": _role(loop, "op")}
            for loop in FURNACE_LOOPS
        ],
        "outputs": [
            {
                "variable": f"{_variable(loop)}_PV",
                "label": loop,
                "source": _role(loop, "pv"),
                "start_parameter": f"{_variable(loop)}.y_start",
            }
            for loop in FURNACE_LOOPS
        ],
    },
    "FIC-1001 process": {
        "asset_id": "FIC-1001",
        "model_id": LOOP_MODEL,
        "parameters": {"K": 0.55, "tau": 110.0, "theta": 8.0, "y0": 55.0},
        "inputs": [{"variable": "u", "source": _role("FIC-1001", "op")}],
        "outputs": [
            {"variable": "y", "source": _role("FIC-1001", "pv"), "start_parameter": "y_start"}
        ],
    },
    "LIC-1010 process": {
        "asset_id": "LIC-1010",
        "model_id": LOOP_MODEL,
        "parameters": {"K": 0.55, "tau": 190.0, "theta": 20.0, "y0": 51.0, "Kd": 0.58, "d0": 50.0},
        "inputs": [
            {"variable": "u", "source": _role("LIC-1010", "op")},
            {"variable": "d", "source": _role("LIC-1010", "secondary")},
        ],
        "outputs": [
            {"variable": "y", "source": _role("LIC-1010", "pv"), "start_parameter": "y_start"}
        ],
    },
}


@pytest.fixture(scope="module")
def judged(tmp_path_factory):
    """Every twin, calibrated on 00:15 to 01:00 and judged from 01:00 to 12:00: the deviation
    block's verdict of each run, by the run's end."""

    folder = tmp_path_factory.mktemp("models")
    store = ModelStore(Database(folder / "link.db"), folder / "models")
    register_builtins(store)
    register_models(store.list())
    models = ModelRuntime(store, InlinePool())
    client = plant_fake("linkcraft", "PlantCraft Analytics", "/link/").client(
        None, app="linkcraft", key=APP_KEY
    )
    found = {}
    for name, twin in TWINS.items():
        info = store.get(twin["model_id"])["info"]
        subject = twin_subject(twin)
        timing = AssetTiming.model_validate(twin_timing(twin))
        diagram = twin_diagram(twin, info)
        calibrated = calibrate_on_asset(
            diagram,
            "deviation",
            subject,
            client=client,
            start=pd.Timestamp(START + timedelta(minutes=15)),
            end=pd.Timestamp(START + timedelta(hours=1)),
            timing=timing,
            models=models,
        )
        diagram = twin_diagram(twin, info, calibrated["calibration"])
        ends = segment_ends(
            pd.Timestamp(START + timedelta(hours=1)),
            pd.Timestamp(START + timedelta(hours=HOURS)),
            600,
        )
        runs = runs_over(
            diagram,
            subject,
            client=client,
            ends=ends,
            window=timing.window_seconds,
            step=timing.step_seconds,
            models=models,
            keep=[("deviation", "result")],
        )
        found[name] = [(end, run["kept"][("deviation", "result")]) for end, run in zip(ends, runs)]
    return found


def _deviating(result: Result) -> bool:
    return result.status in ("warning", "bad")


def _names(result: Result, variable: str) -> bool:
    if not _deviating(result):
        return False
    contributions = result.detail["contributions"]
    return max(contributions, key=contributions.get) == variable


def _disturbed(end, evaluate: int = 600) -> bool:
    """TIC-1104's disturbance acts on the whole judged part and the 10 minutes before it."""

    return all(
        disturbance(TIC_1104, (end - timedelta(seconds=seconds)).timestamp()) != 0
        for seconds in range(0, evaluate + 600, 30)
    )


def _calm(end) -> bool:
    return all(
        disturbance(TIC_1104, (end - timedelta(seconds=seconds)).timestamp()) == 0
        for seconds in range(0, 2400, 30)
    )


def test_every_run_was_judged(judged):
    for name, runs in judged.items():
        assert len(runs) == 66, name
        unknown = [result.message for _end, result in runs if result.status == "unknown"]
        assert not unknown, (name, unknown[:3])


def test_load_disturbance_found_and_named(judged):
    inside = [result for end, result in judged["Furnaces"] if _disturbed(end)]
    assert len(inside) >= 4
    score = sum(_names(result, "TIC1104_PV") for result in inside) / len(inside)
    print(f"twin_disturbance_found = {score:.3f} over {len(inside)} runs")
    assert score >= FLOORS["twin_disturbance_found"]


def test_drifting_sensor_found_and_named(judged):
    calm = [
        result
        for end, result in judged["Furnaces"]
        if end >= START + timedelta(hours=4) and _calm(end)
    ]
    assert len(calm) >= 15
    score = sum(_names(result, "TIC1209_PV") for result in calm) / len(calm)
    print(f"twin_drift_found = {score:.3f} over {len(calm)} runs")
    assert score >= FLOORS["twin_drift_found"]


def test_healthy_twins_stay_quiet(judged):
    runs = judged["FIC-1001 process"] + judged["LIC-1010 process"]
    score = sum(result.status == "ok" for _end, result in runs) / len(runs)
    print(f"twin_healthy_quiet = {score:.3f} over {len(runs)} runs")
    assert score >= FLOORS["twin_healthy_quiet"]
