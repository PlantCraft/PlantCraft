"""Example model algorithms of the Simulator demo plant, on Link's built-in models.

The Simulator (the suite's simulated plant) publishes the equations of its loops; the built-in
``PlantCraftTwin`` models describe them, so these algorithms follow the plant until a fault the
simulator injects on purpose: TIC-1104 has load disturbances, TIC-1209 a drifting sensor,
LIC-1010 a level driven by a measured flow. They came from PlantCraft Twin's example twins
(the same twins, written as ``assets.twins`` diagrams); a person creates them with one button
when the plant's loops are in PlantCraft, each calibrated on the last hours.
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from typing import Any

import pandas as pd

from linkcraft.assets.calibrate import calibrate_on_asset
from linkcraft.assets.run import AssetTiming
from linkcraft.assets.twins import twin_diagram, twin_subject, twin_timing
from linkcraft.blocks.stored import method_config
from linkcraft.i18n import t

LOOP_MODEL = "plantcrafttwin-loopprocess"
FURNACES_MODEL = "plantcrafttwin-furnaces"
# The Simulator's published loop definitions (simcraft.loops.dynamics.LOOP_DEFINITIONS).
FURNACE_LOOPS = ("TIC-1104", "TIC-1209", "FIC-1210")
SINGLE_LOOPS = {
    "FIC-1001": {"K": 0.55, "tau": 110.0, "theta": 8.0, "y0": 55.0},
    "LIC-1010": {"K": 0.55, "tau": 190.0, "theta": 20.0, "y0": 51.0, "Kd": 0.58, "d0": 50.0},
}
NEEDED = {
    **{loop: ("op", "pv") for loop in FURNACE_LOOPS},
    "FIC-1001": ("op", "pv"),
    "LIC-1010": ("op", "pv", "secondary"),
}
# The period each example is calibrated on when it is created (the plant ran normally).
CALIBRATION = pd.Timedelta(hours=6)
# The examples a demo plant gets by itself (the loop process twins stay in the library: a twin per
# loop is too many for a first look), and how often each runs: the model beside
# the plant every hour.
DEMO_EXAMPLES = ("Furnaces",)
EXAMPLE_MINUTES = 60.0

# lookup(loop id, role) -> where that signal is ({"asset_id", "role"} or {"signal_id"}), or None.
Lookup = Callable[[str, str], dict[str, str] | None]


def _variable(loop: str) -> str:
    return loop.replace("-", "")


def algorithm_id(name: str) -> str:
    """``FIC-1001 process`` -> ``example_fic_1001_process``."""

    return "example_" + "".join(ch if ch.isalnum() else "_" for ch in name.lower()).strip("_")


def twins(
    lookup: Lookup, *, area: str | None, loop_asset: Callable[[str], str | None]
) -> list[dict[str, Any]]:
    """The example twins whose signals are all found (``assets.twins`` fields)."""

    found: list[dict[str, Any]] = []
    sources = {loop: {role: lookup(loop, role) for role in roles} for loop, roles in NEEDED.items()}
    if area and all(all(sources[loop].values()) for loop in FURNACE_LOOPS):
        found.append(
            {
                "name": "Furnaces",
                "description": (
                    "The furnace area of the Simulator: two outlet temperatures and the fuel gas "
                    "flow, each predicted from its valve. TIC-1104 sees load disturbances and "
                    "TIC-1209's sensor drifts; the deviation says which one."
                ),
                "asset_id": area,
                "model_id": FURNACES_MODEL,
                "inputs": [
                    {"variable": f"{_variable(loop)}_OP", "source": sources[loop]["op"]}
                    for loop in FURNACE_LOOPS
                ],
                "outputs": [
                    {
                        "variable": f"{_variable(loop)}_PV",
                        "label": loop,
                        "source": sources[loop]["pv"],
                        "start_parameter": f"{_variable(loop)}.y_start",
                    }
                    for loop in FURNACE_LOOPS
                ],
            }
        )
    for loop, parameters in SINGLE_LOOPS.items():
        if not all(sources[loop].values()) or not loop_asset(loop):
            continue
        inputs = [{"variable": "u", "source": sources[loop]["op"]}]
        if "secondary" in sources[loop]:
            inputs.append({"variable": "d", "source": sources[loop]["secondary"]})
        found.append(
            {
                "name": f"{loop} process",
                "description": (
                    f"The process of loop {loop} in the Simulator, first order plus dead time"
                    + (
                        ", with the measured flow that drives it"
                        if "secondary" in sources[loop]
                        else ""
                    )
                    + "."
                ),
                "asset_id": loop_asset(loop),
                "model_id": LOOP_MODEL,
                "parameters": parameters,
                "inputs": inputs,
                "outputs": [
                    {
                        "variable": "y",
                        "label": loop,
                        "source": sources[loop]["pv"],
                        "start_parameter": "y_start",
                    }
                ],
            }
        )
    return found


def plant_lookups(client: Any) -> tuple[Lookup, Callable[[str], str | None], str | None]:
    """How the Simulator loops are found: loop assets by id or name, else signals by tag; and
    the area the furnace loops share (the Furnaces example runs there)."""

    assets = list(client.assets())
    by_name: dict[str, dict[str, Any]] = {}
    for item in assets:
        if item.get("kind") != "loop":
            continue
        for key in (item.get("id"), item.get("name")):
            if key:
                by_name[str(key).upper()] = item
    signals = {}
    for item in client.signals("CPM.Loops."):
        tag = str(item.get("id") or "").partition(":")[2] or str(item.get("id"))
        signals[tag] = item["id"]

    def loop_asset(loop: str) -> str | None:
        found = by_name.get(loop.upper())
        return found.get("id") if found else None

    def lookup(loop: str, role: str) -> dict[str, str] | None:
        found = by_name.get(loop.upper())
        if found and (found.get("signals") or {}).get(role):
            return {"asset_id": found["id"], "role": role}
        signal = signals.get(f"CPM.Loops.{loop}.{role.upper()}")
        return {"signal_id": signal} if signal else None

    furnaces = [by_name.get(loop) for loop in FURNACE_LOOPS]
    parents = {item.get("parent_id") for item in furnaces if item and item.get("parent_id")}
    area = next(iter(parents)) if len(parents) == 1 else None
    return lookup, loop_asset, area


def measured_signals(twin: dict[str, Any], assets: list[dict[str, Any]]) -> list[str]:
    """The signal ids behind a twin's measured outputs (where its newest data is read)."""

    roles = {str(item.get("id")): item.get("signals") or {} for item in assets}
    found = []
    for item in twin.get("outputs") or []:
        source = item.get("source") or {}
        signal = source.get("signal_id") or roles.get(str(source.get("asset_id")), {}).get(
            source.get("role")
        )
        if signal:
            found.append(str(signal))
    return found


def example_algorithm(
    twin: dict[str, Any], model: dict[str, Any], *, client: Any, models: Any, end: pd.Timestamp
) -> tuple[dict[str, Any], str]:
    """An example's stored configuration, calibrated on the hours before ``end`` when the plant
    allows; (config, why it is not calibrated or "")."""

    info = model.get("info") or {}
    subject = twin_subject(twin)
    timing = twin_timing(twin)
    diagram = twin_diagram(twin, info)
    problem = ""
    try:
        found = calibrate_on_asset(
            diagram,
            "deviation",
            str(subject),
            client=client,
            start=end - CALIBRATION,
            end=end,
            timing=AssetTiming.model_validate(timing),
            models=models,
        )
        diagram = twin_diagram(twin, info, found["calibration"])
    except (LookupError, ValueError) as exc:
        problem = str(exc)
    config = method_config(
        diagram, {}, "asset", timing=timing, assets=[str(subject)] if subject else []
    )
    return config, problem


__all__ = ["algorithm_id", "example_algorithm", "measured_signals", "plant_lookups", "twins"]


def example_schedule(rt: Any, profile_id: str, name: str, assets: list[str], owner: str) -> str:
    """The schedule an example runs on, every ``EXAMPLE_MINUTES`` on its assets ("" when one of
    those assets already runs it: an asset runs an algorithm in one schedule only)."""

    if not assets or rt.schedule_overlap(profile_id, assets) is not None:
        return ""
    return str(
        rt.jobs.create_schedule(
            name=t("{name}: model beside the plant", name=name),
            loop_id="*",
            cadence="interval",
            interval_minutes=EXAMPLE_MINUTES,
            timezone=rt.settings.timezone,
            lookback_minutes=0,
            profile_id=profile_id,
            method_config={"profile_id": profile_id},
            subject_kind="asset",
            selector={"mode": "list", "ids": assets},
            created_by=owner or "System",
            owner=owner or None,
        )
    )


def create_examples(
    rt: Any,
    client: Any,
    plant: Any,
    *,
    owner: str,
    owner_name: str,
    names: Collection[str] | None = None,
) -> list[dict[str, Any]]:
    """Create the example model algorithms this plant can have that do not exist yet (only
    ``names`` when given), each calibrated on the hours up to the newest data (one the plant
    cannot calibrate yet is created without, and says why), and a schedule for each on the
    assets it was made for."""

    from linkcraft.blocks.algorithms import DIGITAL_TWIN
    from linkcraft.catalog.presets import SHIPPED_AUTHOR

    lookup, loop_asset, area = plant_lookups(client)
    found = twins(lookup, area=area, loop_asset=loop_asset)
    assets = list(client.assets()) if found else []
    created = []
    for twin in found:
        if names is not None and twin["name"] not in names:
            continue
        profile_id = algorithm_id(twin["name"])
        model = rt.models.get(twin["model_id"])
        if model is None or rt.presets.get_profile(profile_id) is not None:
            continue
        end = pd.Timestamp(plant.data_end(measured_signals(twin, assets), 360), tz="UTC").floor(
            "min"
        )
        config, problem = example_algorithm(
            twin, model, client=client, models=rt.model_runtime(), end=end
        )
        rt.presets.save_profile(
            profile_id=profile_id,
            name=twin["name"],
            description=twin["description"],
            method_config=config,
            author=SHIPPED_AUTHOR,
            owner=owner,
            owner_name=owner_name,
            tags=[t(DIGITAL_TWIN)],
        )
        rt.publish_algorithms([rt.presets.get_profile(profile_id)])
        schedule_id = example_schedule(
            rt, profile_id, twin["name"], list(config.get("assets") or []), owner
        )
        created.append(
            {
                "algorithm_id": profile_id,
                "name": twin["name"],
                "schedule_id": schedule_id,
                "assets": config.get("assets") or [],
                "calibrated": not problem,
                "problem": problem,
            }
        )
    return created
