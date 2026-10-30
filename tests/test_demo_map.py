"""The plant map shipped with the demo: the Simulator's 50 loops, as the offline install imports it.

``deploy/demo/plantcraft-50-loops-map.json`` is written from the demo scenario
(``scenarios/opcua_demo.json``): the Simulator source as the ``demo`` profile serves it, the
unit, every signal routed to that source, and every loop with its signals by role and its loop
type. After changing the scenario, write it again with ``python -m tests.test_demo_map``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from plantcraft.api.app import create_app
from plantcraft.assets import asset_id_for
from plantcraft.config import load_scenario

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "scenarios" / "opcua_demo.json"
MAP = ROOT / "deploy" / "demo" / "plantcraft-50-loops-map.json"
SOURCE_ID = "plantcraft"
# The endpoint inside the compose network (the `demo` profile's service name).
ENDPOINT = "opc.tcp://plantcraft:4840/plantcraft/"
ROLES = ("pv", "sp", "op", "mode", "secondary")
# Keys of a scenario loop's metadata that are attributes of the Control loop type.
RECORD_KEYS = ("loop_type", "criticality", "action", "controller")


# The demo is a refinery of four units (realistic names, equipment inside the
# areas, loop records filled). The plant itself is the installation's root: the seed names it.
UNITS = {
    "U-100": (
        "Crude distillation unit",
        12000,
        ["Feed", "Heat exchange", "Furnaces", "Distillation"],
    ),
    "U-200": (
        "Hydrotreating unit",
        4500,
        ["Reaction", "Recycle", "Separation", "Compression", "Hydrotreating", "Quality"],
    ),
    "U-300": ("Treating and sulfur recovery", 900, ["Treating", "Sulfur recovery"]),
    "U-900": ("Utilities and offsites", None, ["Utilities", "Water treatment"]),
}
AREA_OWNERS = {
    "U-100": "Ana Lima",
    "U-200": "Ana Lima",
    "U-300": "Carlos Menezes",
    "U-900": "Marina Costa",
}
# Equipment of each area: (id, type, name, attributes) and the loops whose instruments sit on it.
EQUIPMENT: dict[str, list[tuple[str, str, str, dict[str, Any], list[str]]]] = {
    "Feed": [
        ("TK-1001", "tank", "Crude charge tank", {"capacity": 20000, "product": "Crude oil"}, []),
        (
            "P-1001",
            "pump",
            "Charge pump",
            {"pump_type": "centrifugal", "rated_flow": 520, "power": 450},
            ["FIC-1001", "FIC-1007", "FIC-1112"],
        ),
    ],
    "Heat exchange": [
        (
            "E-1009",
            "heat_exchanger",
            "Feed/product exchanger",
            {"exchanger_type": "shell and tube", "duty": 18.5, "area": 640},
            ["TIC-1009", "TIC-1111"],
        ),
    ],
    "Furnaces": [
        (
            "F-1104",
            "furnace",
            "Atmospheric furnace",
            {"duty": 42, "burners": 12, "fuel": "fuel gas"},
            ["TIC-1104", "TIC-1209", "FIC-1210"],
        ),
    ],
    "Distillation": [
        (
            "C-1101",
            "column",
            "Atmospheric column",
            {"trays": 48, "diameter": 6.2, "height": 52},
            ["FIC-1101", "TIC-1213", "FIC-1214"],
        ),
        (
            "D-1106",
            "vessel",
            "Overhead accumulator",
            {"volume": 85, "design_pressure": 3.5, "design_temperature": 120},
            ["LIC-1106", "LIC-1113", "LIC-1211"],
        ),
        (
            "P-1102",
            "pump",
            "Reflux pump",
            {"pump_type": "centrifugal", "rated_flow": 310, "power": 160},
            ["FIC-1102"],
        ),
    ],
    "Reaction": [
        (
            "R-1005",
            "vessel",
            "Reactor",
            {"volume": 120, "design_pressure": 95, "design_temperature": 420},
            ["TIC-1005"],
        ),
    ],
    "Recycle": [
        (
            "P-1003",
            "pump",
            "Recycle pump",
            {"pump_type": "centrifugal", "rated_flow": 140, "power": 75},
            ["FIC-1003"],
        ),
    ],
    "Separation": [
        (
            "V-1004",
            "vessel",
            "Product separator",
            {"volume": 60, "design_pressure": 12, "design_temperature": 180},
            ["PIC-1002", "LIC-1004", "LIC-1010"],
        ),
        (
            "V-1105",
            "vessel",
            "Surge drum",
            {"volume": 45, "design_pressure": 8, "design_temperature": 150},
            ["LIC-1105"],
        ),
    ],
    "Compression": [
        (
            "K-1103",
            "compressor",
            "Recycle gas compressor",
            {"compressor_type": "centrifugal", "power": 2800},
            ["PIC-1103", "PIC-1207"],
        ),
        (
            "V-1208",
            "vessel",
            "Compressor suction drum",
            {"volume": 18, "design_pressure": 40, "design_temperature": 80},
            ["LIC-1208"],
        ),
    ],
    "Hydrotreating": [
        (
            "R-1203",
            "vessel",
            "Hydrotreating reactor",
            {"volume": 95, "design_pressure": 110, "design_temperature": 430},
            ["PIC-1202", "TIC-1203", "FIC-1206", "FIC-1201"],
        ),
        (
            "V-1204",
            "vessel",
            "High-pressure separator",
            {"volume": 70, "design_pressure": 105, "design_temperature": 90},
            ["LIC-1204", "AIC-1205"],
        ),
    ],
    "Treating": [
        (
            "C-1216",
            "column",
            "Amine absorber",
            {"trays": 20, "diameter": 1.8, "height": 24},
            ["LIC-1216", "TIC-1114", "LIC-1107"],
        ),
    ],
    "Sulfur recovery": [
        (
            "R-1226",
            "vessel",
            "Claus reactor",
            {"volume": 35, "design_pressure": 1.5, "design_temperature": 350},
            ["TIC-1226"],
        ),
    ],
    "Utilities": [
        (
            "P-1219",
            "pump",
            "Cooling water pump",
            {"pump_type": "centrifugal", "rated_flow": 1800, "power": 630},
            ["FIC-1219", "TIC-1220"],
        ),
        (
            "V-1218",
            "vessel",
            "Condensate drum",
            {"volume": 25, "design_pressure": 6, "design_temperature": 165},
            ["LIC-1218", "FIC-1109", "PIC-1217"],
        ),
    ],
    "Water treatment": [
        (
            "TK-1223",
            "tank",
            "Equalization tank",
            {"capacity": 3500, "product": "Process water"},
            ["LIC-1223", "FIC-1222", "AIC-1224"],
        ),
        ("TK-1225", "tank", "Slop tank", {"capacity": 1200, "product": "Slop oil"}, ["LIC-1225"]),
    ],
}
# Where the equipment of one area feeds the next (the "feeds" relations of the demo).
FEEDS = [
    ("TK-1001", "P-1001"),
    ("P-1001", "E-1009"),
    ("E-1009", "F-1104"),
    ("F-1104", "C-1101"),
    ("P-1003", "R-1005"),
    ("V-1204", "K-1103"),
]
HIGH = {
    "FIC-1001",
    "FIC-1003",
    "PIC-1002",
    "PIC-1202",
    "TIC-1104",
    "TIC-1209",
    "TIC-1005",
    "TIC-1203",
    "PIC-1103",
}
LOW_AREAS = {"Utilities", "Water treatment"}
# What each loop type measures: (measured variable, range, unit, valve characteristic).
LOOP_KINDS = {
    "flow": ("flow", (0, 200), "m³/h", "equal percentage"),
    "pressure": ("pressure", (0, 20), "bar g", "equal percentage"),
    "level": ("level", (0, 100), "%", "linear"),
    "temperature": ("temperature", (0, 450), "°C", "equal percentage"),
    "composition": ("composition", (0, 100), "%", "linear"),
}


def _unit_of(area: str) -> str:
    return next(unit for unit, (_name, _capacity, areas) in UNITS.items() if area in areas)


def _loop_record(loop: Any, area: str) -> dict[str, Any]:
    loop_type = (loop.metadata or {}).get("loop_type")
    if loop.loop_id in HIGH:
        criticality = "high"
    elif area in LOW_AREAS:
        criticality = "low"
    else:
        criticality = "medium"
    return {
        "criticality": criticality,
        "action": "direct" if loop_type == "level" else "reverse",
        "controller": "SLC" if area == "Water treatment" else "DCS",
    }


def demo_map(endpoint: str = ENDPOINT) -> dict[str, list[dict[str, Any]]]:
    """The plant map of the demo scenario's loops, read from the Simulator at ``endpoint``.

    Besides the loops: the four units and their areas, the main equipment of each area, and per
    loop its transmitter (the PV) and control valve (the OP), so one signal is referenced by the
    loop and by the instrument, and the relations between them.
    """

    scenario = load_scenario(str(SCENARIO))
    source = scenario.source
    assets: list[dict[str, Any]] = []
    for unit, (name, capacity, areas) in UNITS.items():
        record = {"unit_code": unit, **({"capacity": capacity} if capacity else {})}
        assets.append({"asset_id": unit, "name": name, "kind": "unit", "attributes": record})
        for area in areas:
            assets.append(
                {
                    "asset_id": asset_id_for(f"{unit} {area}"),
                    "name": area,
                    "kind": "area",
                    "parent_id": unit,
                    "attributes": {"owner": AREA_OWNERS[unit]},
                }
            )
    holder: dict[str, str] = {}
    for area, items in EQUIPMENT.items():
        parent = asset_id_for(f"{_unit_of(area)} {area}")
        for asset_id, kind, name, record, loops in items:
            assets.append(
                {
                    "asset_id": asset_id,
                    "name": name,
                    "kind": kind,
                    "parent_id": parent,
                    "attributes": record,
                }
            )
            holder.update({loop_id: asset_id for loop_id in loops})
    signals: list[dict[str, Any]] = []
    loops: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    for loop in scenario.loops:
        unit = _unit_of(loop.area)
        roles = {role: tag for role, tag in loop.signals.model_dump().items() if tag}
        metadata = loop.metadata or {}
        variable, (low, high), engineering, characteristic = LOOP_KINDS[metadata["loop_type"]]
        letter, number = loop.loop_id[0], loop.loop_id.split("-", 1)[1]
        transmitter, valve = f"{letter}T-{number}", f"{letter}V-{number}"
        where = holder.get(loop.loop_id) or asset_id_for(f"{unit} {loop.area}")
        assets.append(
            {
                "asset_id": transmitter,
                "name": f"{loop.name} transmitter",
                "kind": "instrument",
                "parent_id": where,
                "attributes": {
                    "measured_variable": variable,
                    "range_min": low,
                    "range_max": high,
                    "range_unit": engineering,
                },
            }
        )
        assets.append(
            {
                "asset_id": valve,
                "name": f"{loop.name} valve",
                "kind": "control_valve",
                "parent_id": where,
                "attributes": {"characteristic": characteristic, "actuator": "pneumatic"},
            }
        )
        relations.append({"from_id": loop.loop_id, "type": "controls", "to_id": valve})
        if loop.loop_id in holder:
            relations.append(
                {"from_id": transmitter, "type": "measures", "to_id": holder[loop.loop_id]}
            )
        # The same tag on the loop (its PV, OP) and on the instrument and valve that carry it.
        bound = {"pv": (transmitter, "measurement"), "op": (valve, "command")}
        for role in ROLES:
            if role in roles:
                suffix = roles[role].rsplit(".", 1)[-1]
                owner, owner_role = bound.get(role, ("", ""))
                signals.append(
                    {
                        "tag": roles[role],
                        "source_id": SOURCE_ID,
                        "name": f"{loop.loop_id} {suffix}",
                        **({"asset_id": owner, "role": owner_role} if owner else {}),
                    }
                )
        loops.append(
            {
                "loop_id": loop.loop_id,
                "name": loop.name,
                "area": loop.area,
                "unit": unit,
                "service": loop.service,
                **{role: roles[role] for role in ROLES if role in roles},
                **{key: metadata[key] for key in RECORD_KEYS if metadata.get(key) is not None},
                **_loop_record(loop, loop.area),
            }
        )
    relations.extend({"from_id": a, "type": "feeds", "to_id": b} for a, b in FEEDS)
    return {
        "sources": [
            {
                "source_id": SOURCE_ID,
                "name": "Simulator (OPC UA)",
                "type": "opcua",
                "endpoint_url": endpoint,
                "namespace_uri": source.namespace_uri,
                "auth_type": "anonymous",
                "timeout_seconds": source.timeout_seconds,
            }
        ],
        "assets": assets,
        "signals": signals,
        "loops": loops,
        "relations": relations,
    }


def _write() -> None:
    MAP.parent.mkdir(parents=True, exist_ok=True)
    MAP.write_text(json.dumps(demo_map(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_the_shipped_map_is_the_demo_scenario():
    assert json.loads(MAP.read_text(encoding="utf-8")) == demo_map(), (
        "deploy/demo/plantcraft-50-loops-map.json is out of date: python -m tests.test_demo_map"
    )
    shipped = json.loads(MAP.read_text(encoding="utf-8"))
    assert len(shipped["loops"]) == 50
    assert all(row["loop_type"] for row in shipped["loops"])


@pytest.mark.slow  # the whole shipped plant map, imported: over ten seconds on purpose
def test_the_shipped_map_imports_cleanly_against_the_demo_plant(tmp_path, monkeypatch):
    pytest.importorskip("asyncua")
    from tests.opcua_plant import FakePlantCraft

    site = json.loads((ROOT / "deploy" / "site" / "site.json").read_text())
    site["storage"]["sqlite_path"] = str(tmp_path / "workspace.sqlite3")
    site["source"]["path"] = str(ROOT / "deploy" / "site" / "no-data.csv")
    path = tmp_path / "site.json"
    path.write_text(json.dumps(site))
    monkeypatch.setenv("PLANTCRAFT_SCENARIO", str(path))
    monkeypatch.setenv("PLANTCRAFT_PREWARM_HISTORY", "false")
    monkeypatch.delenv("PLANTCRAFT_BASIC_AUTH_ENABLED", raising=False)
    scenario = load_scenario(str(SCENARIO))
    with FakePlantCraft(scenario.loops) as plant, TestClient(create_app()) as client:
        # The shipped file, with the endpoint where this test's server listens.
        shipped = json.loads(MAP.read_text(encoding="utf-8"))
        shipped["sources"][0]["endpoint_url"] = plant.endpoint
        content = json.dumps(shipped).encode()
        params = {"filename": MAP.name}
        applied = client.post("/api/map/apply", params=params, content=content).json()
        assert applied["applied"], applied["issues"]
        # A source new in the file is checked once it exists: on the next preview.
        assert [issue["level"] for issue in applied["issues"]] == ["warning"]
        again = client.post("/api/map/preview", params=params, content=content).json()
        # Every tag checked against the server: no warning, and nothing left to change.
        assert again["issues"] == [] and again["changes"] == []
        assets = client.app.state.runtime.platform.workspace.assets
        loops = [item for item in assets.list() if item["kind"] == "loop"]
        assert len(loops) == 50
        # The loops' units are the ones the assets sheet names, each holding its areas.
        units = [item for item in assets.list() if item["kind"] == "unit"]
        assert sorted(item["asset_id"] for item in units) == sorted(UNITS)
        areas = [item for item in assets.list() if item["kind"] == "area"]
        assert len(areas) == 14 and {item["parent_id"] for item in areas} == set(UNITS)
        assert {assets.get(item["parent_id"])["kind"] for item in loops} == {"area"}
        records = assets.stored_attributes([item["asset_id"] for item in loops])
        assert {loop_id: record.get("loop_type") for loop_id, record in records.items()} == {
            loop.loop_id: loop.metadata["loop_type"] for loop in scenario.loops
        }
        # Every loop record is filled, and each loop has a transmitter and a valve.
        assert all(
            record.get("criticality") and record.get("action") for record in records.values()
        )
        assert assets.counts()["instrument"] == 50 and assets.counts()["control_valve"] == 50
        # One signal, several assets: the PV is the loop's and its transmitter's.
        users = assets.signal_assets(["CPM.Loops.FIC-1003.PV"])["CPM.Loops.FIC-1003.PV"]
        assert {item["asset_id"] for item in users} == {"FIC-1003", "FT-1003"}
        related = {(item["relation"], item["to_id"]) for item in assets.relations("FIC-1003")}
        assert ("controls", "FV-1003") in related
        assert assets.get("FT-1003")["parent_id"] == "P-1003"
        token = client.post("/api/v1/auth/token").json()["token"]
        listed = client.get("/api/v1/signals", headers={"Authorization": f"Bearer {token}"}).json()
        kinds = {item["id"]: item["kind"] for item in listed}
        assert kinds[f"{SOURCE_ID}:CPM.Loops.FIC-1003.MODE"] == "text"
        assert kinds[f"{SOURCE_ID}:CPM.Loops.FIC-1003.PV"] == "number"


if __name__ == "__main__":
    _write()
