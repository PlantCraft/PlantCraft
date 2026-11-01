"""The plant map as DEXPI (Proteus XML), the open exchange format for P&IDs (dexpi.org).

What the map knows goes in: each piece of equipment with its class and tag, each process line
between two pieces of equipment as a piping network with a nozzle at each end, and each
instrument loop as a process instrumentation function holding its valves (actuating
functions) and naming the equipment it measures. There are no graphics: a tool that imports
it (AVEVA, Hexagon Smart P&ID, Siemens COMOS, pyDEXPI) gets the plant's data, laid out by its
own drawing. Only what people did not mark Wrong is exported, as on the map.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from typing import Any

from pidcraft import __version__

# The map's classes to DEXPI equipment classes (DEXPI 1.3 class names).
EQUIPMENT_CLASSES = {
    "pump": "CentrifugalPump",
    "compressor": "CentrifugalCompressor",
    "vessel": "Vessel",
    "tank": "Tank",
    "column": "ProcessColumn",
    "heat_exchanger": "HeatExchanger",
    "furnace": "Furnace",
    "reactor": "Reactor",
    "filter": "Filter",
    "drum": "Vessel",
}
TAG = re.compile(r"^([A-Z]+)-?(.+)$")


def _attributes(parent: ET.Element, values: dict[str, str]) -> None:
    group = ET.SubElement(
        parent, "GenericAttributes", Number=str(len(values)), Set="DexpiAttributes"
    )
    for name, value in values.items():
        ET.SubElement(group, "GenericAttribute", Name=name, Value=value, Format="string")


def _split(tag: str) -> tuple[str, str]:
    m = TAG.match(tag)
    return (m.group(1), m.group(2)) if m else ("", tag)


def dexpi_xml(plant: dict[str, Any], now: datetime | None = None) -> bytes:
    """``plant`` from :func:`pidcraft.plantmap.build.build_map`."""

    now = now or datetime.now(UTC)
    root = ET.Element("PlantModel")
    ET.SubElement(
        root,
        "PlantInformation",
        SchemaVersion="4.1.1",
        OriginatingSystem="PlantCraft PID",
        OriginatingSystemVendor="PlantCraft",
        OriginatingSystemVersion=__version__,
        Date=now.strftime("%Y-%m-%d"),
        Time=now.strftime("%H:%M:%S") + "Z",
        Is3D="no",
        Units="Metre",
        Discipline="PID",
    )
    items = {i["tag"]: i for i in plant["items"]}
    ids: dict[str, str] = {}
    equipment: dict[str, ET.Element] = {}
    for n, item in enumerate(i for i in plant["items"] if i["family"] == "equipment"):
        ids[item["tag"]] = f"EQ{n + 1}"
        prefix, number = _split(item["tag"])
        element = ET.SubElement(
            root,
            "Equipment",
            ID=ids[item["tag"]],
            ComponentClass=EQUIPMENT_CLASSES.get(item["cls"], "Equipment"),
            TagName=item["tag"],
        )
        _attributes(
            element,
            {
                "TagNameAssignmentClass": item["tag"],
                "TagNamePrefixAssignmentClass": prefix,
                "TagNameSequenceNumberAssignmentClass": number,
            },
        )
        equipment[item["tag"]] = element
    nozzles: dict[str, int] = {}

    def nozzle(tag: str) -> str:
        nozzles[tag] = nozzles.get(tag, 0) + 1
        nozzle_id = f"{ids[tag]}-N{nozzles[tag]}"
        element = ET.SubElement(
            equipment[tag],
            "Nozzle",
            ID=nozzle_id,
            ComponentClass="Nozzle",
            TagName=f"N{nozzles[tag]}",
        )
        _attributes(element, {"SubTagNameAssignmentClass": f"N{nozzles[tag]}"})
        return nozzle_id

    feeds = [
        r
        for r in plant["relations"]
        if r["type"] == "feeds" and r["from"] in equipment and r["to"] in equipment
    ]
    for n, rel in enumerate(feeds):
        system = ET.SubElement(
            root, "PipingNetworkSystem", ID=f"PNS{n + 1}", ComponentClass="PipingNetworkSystem"
        )
        _attributes(system, {"LineNumberAssignmentClass": f"{rel['from']} to {rel['to']}"})
        segment = ET.SubElement(
            system,
            "PipingNetworkSegment",
            ID=f"PNS{n + 1}-S1",
            ComponentClass="PipingNetworkSegment",
        )
        ET.SubElement(segment, "Connection", FromID=nozzle(rel["from"]), ToID=nozzle(rel["to"]))
    # Instrument loops: a controller (or any instrument) with the valves it moves and what it
    # measures; a valve no controller moves is a loop of its own.
    moves: dict[str, list[str]] = {}
    moved: set[str] = set()
    for rel in plant["relations"]:
        if rel["type"] == "controls" and rel["from"] in items and rel["to"] in items:
            moves.setdefault(rel["from"], []).append(rel["to"])
            moved.add(rel["to"])
    measured = {
        r["from"]: r["to"]
        for r in plant["relations"]
        if r["type"] in {"measures", "on"} and r["to"] in equipment
    }
    n = 0
    for item in plant["items"]:
        tag = item["tag"]
        if item["family"] != "instrument" or tag in moved:
            continue
        n += 1
        letters, number = _split(tag)
        element = ET.SubElement(
            root,
            "ProcessInstrumentationFunction",
            ID=f"PIF{n}",
            ComponentClass="ProcessInstrumentationFunction",
        )
        _attributes(
            element,
            {
                "ProcessInstrumentationFunctionCategoryAssignmentClass": letters[:1],
                "ProcessInstrumentationFunctionModifierAssignmentClass": letters[1:],
                "ProcessInstrumentationFunctionNumberAssignmentClass": f"{letters[:1]}-{number}",
            },
        )
        if tag in measured:
            ET.SubElement(element, "Association", Type="is located in", ItemID=ids[measured[tag]])
        for k, valve in enumerate(moves.get(tag, []) + ([tag] if item["cls"] == "valve" else [])):
            actuating = ET.SubElement(
                element,
                "ActuatingFunction",
                ID=f"PIF{n}-A{k + 1}",
                ComponentClass="ActuatingFunction",
            )
            _attributes(actuating, {"ActuatingFunctionNumberAssignmentClass": valve})
    ET.indent(root)
    return b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="utf-8")
