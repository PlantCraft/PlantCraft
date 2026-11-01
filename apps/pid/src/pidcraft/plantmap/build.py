"""The plant map: every diagram page read, joined into one plant.

The same tag on two sheets is one item (its sheets listed); an off-page connector naming
``E-1009`` on sheet 01 and the ``E-1009`` drawn on sheet 02 are the same equipment, so a line
that leaves one sheet arrives on the next. Units come from the sheets' title blocks, areas from
the sheets' titles. Nothing here writes to PlantCraft: the map is offered as an asset file
(``processcraft-assets``) that a person reviews and applies on PlantCraft's Assets › Import.

Also here: the plant summary (units, areas, equipment by kind, loops complete or not, what the
reader was unsure of), and which tags PlantCraft already has as assets.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

ASSET_TYPES = {
    "pump": "pump",
    "vessel": "vessel",
    "reactor": "vessel",
    "separator": "vessel",
    "column": "column",
    "heat_exchanger": "heat_exchanger",
    "air_cooler": "heat_exchanger",
    "furnace": "furnace",
    "compressor": "compressor",
    "blower": "compressor",
    "tank": "tank",
}
RELATION_TYPES = {"feeds": "feeds", "measures": "measures", "controls": "controls"}
CONFIDENCE = {"low": 0, "medium": 1, "high": 2}


def build_map(
    diagrams: list[dict[str, Any]],
    known: set[str] | None = None,
    reviews: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """``diagrams``: rows of ``DocumentStore.diagrams(full=True)``; ``known``: PlantCraft's
    asset ids (None when it could not be read); ``reviews``: ``DocumentStore.map_reviews()``,
    what people approved (kept, made sure) or rejected (left out of the map)."""

    items: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}
    sheets = []
    for row in diagrams:
        result = row["result"]
        sheet_id = row.get("sheet") or f"{row.get('doc_number') or row['doc_id']} p.{row['page']}"
        unit = row.get("unit") or ""
        where = {
            "doc_id": row["doc_id"],
            "rev_id": row["rev_id"],
            "page": row["page"],
            "sheet": sheet_id,
            "doc_title": row.get("doc_title") or "",
        }
        sheet = {
            **where,
            "title": row.get("title") or "",
            "unit": unit,
            "source": row.get("source") or "",
            "width": result.get("width"),
            "height": result.get("height"),
            "items": [],
        }
        sheets.append(sheet)
        for item in result["items"]:
            tag = item.get("tag")
            if not tag:
                continue
            place = {**where, "box": item["box"]}
            entry = items.get(tag)
            if entry is None:
                entry = items[tag] = {
                    "tag": tag,
                    "family": item["family"],
                    "cls": item["cls"],
                    "unit": unit,
                    "area": row.get("title") or "",
                    "sheet": sheet_id,
                    "confidence": item["confidence"],
                    "why": item["why"],
                    "places": [],
                }
            elif CONFIDENCE[item["confidence"]] > CONFIDENCE[entry["confidence"]]:
                entry.update(confidence=item["confidence"], why=item["why"])
            entry["places"].append(place)
            sheet["items"].append(
                {"tag": tag, "family": item["family"], "cls": item["cls"], "box": item["box"]}
            )
        for rel in result["relations"]:
            if rel["from"].startswith("valve@") or rel["to"].startswith("valve@"):
                continue
            key = (rel["from"], rel["type"], rel["to"])
            entry = edges.get(key)
            if entry is None:
                entry = edges[key] = {
                    "from": rel["from"],
                    "type": rel["type"],
                    "to": rel["to"],
                    "confidence": rel["confidence"],
                    "why": rel["why"],
                    "sheets": [],
                }
            elif CONFIDENCE[rel["confidence"]] > CONFIDENCE[entry["confidence"]]:
                entry.update(confidence=rel["confidence"], why=rel["why"])
            if sheet_id not in entry["sheets"]:
                entry["sheets"].append(sheet_id)
    # An item named only by an off-page connector is drawn on another sheet not read yet.
    for edge in edges.values():
        for end in (edge["from"], edge["to"]):
            if end not in items:
                items[end] = {
                    "tag": end,
                    "family": "equipment",
                    "cls": "equipment",
                    "unit": "",
                    "area": "",
                    "sheet": "",
                    "confidence": "low",
                    "why": "named by an off-page connector; its sheet is not here",
                    "places": [],
                }
    rejected = _apply_reviews(items, edges, reviews or {})
    for tag, entry in items.items():
        entry["in_plantcraft"] = None if known is None else tag in known
    loops = _loops(items, edges)
    return {
        "items": sorted(items.values(), key=lambda i: (i["unit"], i["sheet"], i["tag"])),
        "relations": sorted(edges.values(), key=lambda e: (e["type"], e["from"], e["to"])),
        "loops": loops,
        "sheets": sheets,
        "rejected": rejected,
        "summary": summary(items, edges, loops, sheets, known),
    }


def relation_key(rel: dict[str, Any]) -> str:
    return f"{rel['from']}|{rel['type']}|{rel['to']}"


def _apply_reviews(items, edges, reviews) -> list[dict[str, str]]:
    """A rejected item or relation leaves the map (with the relations of a rejected item); an
    approved one becomes sure, saying who checked it."""

    rejected = {key for key, r in reviews.items() if r["verdict"] == "rejected"}
    for tag in [t for t in items if t in rejected]:
        del items[tag]
    for key in list(edges):
        edge = edges[key]
        if relation_key(edge) in rejected or edge["from"] in rejected or edge["to"] in rejected:
            del edges[key]
    for entry in list(items.values()) + list(edges.values()):
        key = entry["tag"] if "tag" in entry else relation_key(entry)
        review = reviews.get(key)
        entry["review"] = review["verdict"] if review else ""
        if review and review["verdict"] == "approved":
            entry["confidence"] = "high"
            entry["why"] = f"checked by {review['by']}"
    return [
        {"key": key, "kind": reviews[key]["kind"], "by": reviews[key]["by"]}
        for key in sorted(rejected)
    ]


LIST_COLUMNS = {
    "equipment": ("tag", "kind", "unit", "area", "sheet", "confidence", "checked", "in_plantcraft"),
    "instruments": (
        "tag",
        "kind",
        "unit",
        "area",
        "sheet",
        "confidence",
        "checked",
        "in_plantcraft",
    ),
    "lines": ("from", "relation", "to", "sheets", "confidence", "checked"),
    "loops": ("loop", "transmitters", "valves", "equipment", "unit", "area", "complete"),
}


def lists(plant: dict[str, Any], kind: str) -> list[list[str]]:
    """The map as a table (header first): equipment, instruments, process lines or loops."""

    rows: list[list[str]] = [list(LIST_COLUMNS[kind])]

    def flag(value):
        return "" if value is None else ("yes" if value else "no")

    if kind in {"equipment", "instruments"}:
        family = "equipment" if kind == "equipment" else "instrument"
        for i in plant["items"]:
            if i["family"] == family:
                rows.append(
                    [
                        i["tag"],
                        i["cls"].replace("_", " "),
                        i["unit"],
                        i["area"],
                        i["sheet"],
                        i["confidence"],
                        flag(i.get("review") == "approved"),
                        flag(i.get("in_plantcraft")),
                    ]
                )
    elif kind == "lines":
        for r in plant["relations"]:
            rows.append(
                [
                    r["from"],
                    r["type"],
                    r["to"],
                    " ".join(r["sheets"]),
                    r["confidence"],
                    flag(r.get("review") == "approved"),
                ]
            )
    else:
        for x in plant["loops"]:
            rows.append(
                [
                    x["loop"],
                    " ".join(x["transmitters"]),
                    " ".join(x["valves"]),
                    " ".join(x["equipment"]),
                    x["unit"],
                    x["area"],
                    flag(x["complete"]),
                ]
            )
    return rows


def _loops(items, edges) -> list[dict[str, Any]]:
    out = []
    controls = defaultdict(list)
    signals = defaultdict(list)
    measures = defaultdict(list)
    on = defaultdict(list)
    for a, kind, b in edges:
        {"controls": controls, "signal": signals, "measures": measures, "on": on}.get(
            kind, defaultdict(list)
        )[a if kind != "signal" else b].append(b if kind != "signal" else a)
    for tag, item in items.items():
        if item["cls"] != "controller":
            continue
        sensors = signals.get(tag, [])
        valves = controls.get(tag, [])
        equipment = sorted(
            {e for s in sensors for e in measures.get(s, [])}
            | {e for v in valves for e in on.get(v, [])}
        )
        out.append(
            {
                "loop": tag,
                "transmitters": sorted(sensors),
                "valves": sorted(valves),
                "equipment": equipment,
                "unit": item["unit"],
                "area": item["area"],
                "complete": bool(sensors and valves),
            }
        )
    return sorted(out, key=lambda x: x["loop"])


def summary(items, edges, loops, sheets, known) -> dict[str, Any]:
    units: dict[str, dict[str, Any]] = {}
    for sheet in sheets:
        unit = units.setdefault(
            sheet["unit"] or "",
            {
                "unit": sheet["unit"] or "",
                "areas": [],
                "equipment": Counter(),
                "loops": 0,
                "instruments": 0,
            },
        )
        if sheet["title"] and sheet["title"] not in unit["areas"]:
            unit["areas"].append(sheet["title"])
    for item in items.values():
        unit = units.get(item["unit"])
        if unit is None:
            continue
        if item["family"] == "equipment":
            unit["equipment"][item["cls"]] += 1
        elif item["family"] == "instrument":
            unit["instruments"] += 1
    for loop in loops:
        if loop["unit"] in units:
            units[loop["unit"]]["loops"] += 1
    doubts = [
        {"tag": i["tag"], "why": i["why"]} for i in items.values() if i["confidence"] == "low"
    ] + [
        {"tag": f"{e['from']} {e['type']} {e['to']}", "why": e["why"]}
        for e in edges.values()
        if e["confidence"] == "low"
    ]
    tags = [i for i in items.values() if i["family"] in {"equipment", "instrument"}]
    return {
        "sheets": len(sheets),
        "units": [{**u, "equipment": dict(u["equipment"])} for u in units.values()],
        "equipment": sum(1 for i in tags if i["family"] == "equipment"),
        "instruments": sum(1 for i in tags if i["family"] == "instrument"),
        "loops": len(loops),
        "loops_complete": sum(1 for x in loops if x["complete"]),
        "feeds": sum(1 for e in edges.values() if e["type"] == "feeds"),
        "relations": len(edges),
        "doubts": doubts[:100],
        "doubt_count": len(doubts),
        "in_plantcraft": None if known is None else sum(1 for i in tags if i["tag"] in known),
        "new": None if known is None else sum(1 for i in tags if i["tag"] not in known),
    }


def asset_file(plant: dict[str, Any]) -> dict[str, Any]:
    """The map as PlantCraft's asset file (``processcraft-assets``), for Assets › Import."""

    assets: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(asset_id, name, kind, parent, description=""):
        if asset_id in seen:
            return
        seen.add(asset_id)
        row = {"asset_id": asset_id, "name": name, "type": kind}
        if parent:
            row["parent_id"] = parent
        if description:
            row["description"] = description
        assets.append(row)

    area_of: dict[tuple[str, str], str] = {}
    for sheet in plant["sheets"]:
        unit = sheet["unit"]
        if unit:
            add(unit, unit, "unit", "")
        if sheet["title"]:
            area_id = _slug(f"{unit}-{sheet['title']}") if unit else _slug(sheet["title"])
            area_of[(unit, sheet["title"])] = area_id
            add(
                area_id,
                sheet["title"],
                "area",
                unit,
                f"Drawn on {sheet['sheet']} ({sheet['doc_title']}).",
            )
    items = {i["tag"]: i for i in plant["items"]}
    parent_of: dict[str, str] = {}
    for rel in plant["relations"]:
        if (
            rel["type"] in {"measures", "on"}
            and items.get(rel["to"], {}).get("family") == "equipment"
        ):
            parent_of.setdefault(rel["from"], rel["to"])
    loops = {x["loop"]: x for x in plant["loops"]}
    for kind_pass in ("equipment", "instrument"):
        for item in plant["items"]:
            if item["family"] != kind_pass or not item["places"]:
                continue
            tag = item["tag"]
            area = area_of.get((item["unit"], item["area"]), item["unit"])
            where = f"Drawn on {item['sheet']}."
            if kind_pass == "equipment":
                add(tag, tag, ASSET_TYPES.get(item["cls"], "equipment"), area, where)
            elif item["cls"] == "controller":
                add(tag, tag, "loop", area, where)
            elif item["cls"] == "valve":
                add(
                    tag,
                    tag,
                    "control_valve"
                    if tag in {v for x in loops.values() for v in x["valves"]}
                    else "valve",
                    parent_of.get(tag, area),
                    where,
                )
            else:
                add(tag, tag, "instrument", parent_of.get(tag, area), where)
    relations = [
        {"from": r["from"], "type": RELATION_TYPES[r["type"]], "to": r["to"]}
        for r in plant["relations"]
        if r["type"] in RELATION_TYPES and r["from"] in seen and r["to"] in seen
    ]
    return {"format": "processcraft-assets", "version": 1, "assets": assets, "relations": relations}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80]
