#!/usr/bin/env python3
"""Write ``src/pidcraft/plantmap/sample/riverbend.json``: what each P&ID sheet of the demo plant shows.

Read from the demo's plant map (``deploy/demo/plantcraft-50-loops-map.json`` at the
repository's root): one sheet per area (the sheet numbers of the demo's P&ID index,
DOC-PID-001), its equipment in the map's order joined by the main process line, the feeds that
cross sheets as off-page connectors, and each loop with its transmitter, controller and valve.
Run it again when the demo map changes: ``python tools/riverbend_spec.py``.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
MAP = HERE.parents[1] / "deploy" / "demo" / "plantcraft-50-loops-map.json"
OUT = HERE / "src" / "pidcraft" / "plantmap" / "sample" / "riverbend.json"
VESSELS = {"vessel", "column", "tank", "reactor", "furnace", "heat_exchanger", "compressor"}
EQUIPMENT_KINDS = VESSELS | {"pump"}


def main() -> None:
    plant = json.loads(MAP.read_text(encoding="utf-8"))
    assets = {a["asset_id"]: a for a in plant["assets"]}
    controls = {r["from_id"]: r["to_id"] for r in plant["relations"] if r["type"] == "controls"}
    feeds = [(r["from_id"], r["to_id"]) for r in plant["relations"] if r["type"] == "feeds"]
    units = [a for a in plant["assets"] if a["kind"] == "unit"]
    area_of = {}
    sheets = []
    for unit in units:
        areas = [
            a
            for a in plant["assets"]
            if a["kind"] == "area" and a.get("parent_id") == unit["asset_id"]
        ]
        for n, area in enumerate(areas, start=1):
            equipment = [
                a
                for a in plant["assets"]
                if a.get("parent_id") == area["asset_id"] and a["kind"] in EQUIPMENT_KINDS
            ]
            for item in equipment:
                area_of[item["asset_id"]] = len(sheets)
            sheets.append(
                {
                    "sheet": f"PID-{unit['asset_id']}-{n:02d}",
                    "title": area["name"],
                    "unit": unit["asset_id"],
                    "unit_name": unit["name"],
                    "area": area["asset_id"],
                    "equipment": [
                        {"tag": e["asset_id"], "kind": e["kind"], "name": e["name"]}
                        for e in equipment
                    ],
                    "incoming": [],
                    "outgoing": [],
                    "loops": [],
                }
            )
    for src, dst in feeds:
        a, b = area_of[src], area_of[dst]
        if a != b:
            sheets[a]["outgoing"].append({"from": src, "to": dst, "sheet": sheets[b]["sheet"]})
            sheets[b]["incoming"].append({"from": src, "to": dst, "sheet": sheets[a]["sheet"]})
    by_area = {s["area"]: s for s in sheets}
    for loop in plant["loops"]:
        letters, number = loop["loop_id"].split("-")
        transmitter = f"{letters[0]}T-{number}"
        valve = controls[loop["loop_id"]]
        parent = assets[transmitter].get("parent_id")
        equipment = (
            parent if parent in assets and assets[parent]["kind"] in EQUIPMENT_KINDS else None
        )
        sheet = by_area[assets[equipment]["parent_id"]] if equipment else by_area[parent]
        kind = assets[equipment]["kind"] if equipment else ""
        mount = "header"
        if equipment:
            mount = "vessel" if kind in VESSELS and letters[0] in "LPTA" else "line"
        sheet["loops"].append(
            {
                "controller": loop["loop_id"],
                "transmitter": transmitter,
                "valve": valve,
                "equipment": equipment,
                "mount": mount,
                "name": loop["name"],
            }
        )
    check = defaultdict(int)
    for s in sheets:
        check[len(s["loops"])] += 1
    OUT.write_text(
        json.dumps(
            {"plant": "Riverbend demo refinery", "sheets": sheets}, indent=1, ensure_ascii=False
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"{OUT.relative_to(HERE)}: {len(sheets)} sheets, loops per sheet {dict(check)}")


if __name__ == "__main__":
    main()
