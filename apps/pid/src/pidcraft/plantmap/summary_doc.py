"""The plant map written out as a document of the library, so search and the assistant find it
and cite it like any other: what each unit holds, its equipment in flow order with what each
piece feeds and is fed by, its control loops, and the sheets each item is drawn on.

It is made from the map alone, with no language model, every time an editor asks (a new
revision of the same document). Each item gets its own heading, so a passage answers "what
feeds T-4750?" with its sheet. What the reader was unsure of is said, item by item.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

NUMBER = "PLANT-MAP-SUMMARY"


def _flow_order(tags: list[str], feeds: list[tuple[str, str]]) -> list[str]:
    """Upstream first (a topological order that tolerates recycles), then by tag."""

    succ: dict[str, list[str]] = defaultdict(list)
    indeg = {t: 0 for t in tags}
    for a, b in feeds:
        if a in indeg and b in indeg and a != b:
            succ[a].append(b)
            indeg[b] += 1
    order: list[str] = []
    left = set(tags)
    while left:
        ready = sorted(t for t in left if indeg[t] == 0) or [min(left, key=lambda t: (indeg[t], t))]
        t = ready[0]
        order.append(t)
        left.discard(t)
        for b in succ[t]:
            if b in left:
                indeg[b] -= 1
    return order


def _join(values: list[str]) -> str:
    return ", ".join(values) if values else "none found"


def summary_markdown(plant: dict[str, Any], scope: str, now: datetime | None = None) -> str:
    """``plant`` from :func:`pidcraft.plantmap.build.build_map`; ``scope`` says which drawings
    it comes from (a folder's name)."""

    now = now or datetime.now(UTC)
    items = {i["tag"]: i for i in plant["items"]}
    rel = plant["relations"]
    by: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for r in rel:
        a, kind, b = r["from"], r["type"], r["to"]
        note = "" if r["confidence"] != "low" else " (unsure)"
        by[a][kind].append(b + note)
        by[b]["by " + kind].append(a + note)
    sheets = {s["sheet"]: s for s in plant["sheets"]}

    def drawn_on(item: dict[str, Any]) -> str:
        seen = []
        for p in item["places"]:
            name = f"{p['sheet']} ({p['doc_title'] or 'untitled'}, page {p['page']})"
            if name not in seen:
                seen.append(name)
        return _join(seen)

    s = plant["summary"]
    out = [
        f"# Plant summary from the P&IDs ({scope})",
        "",
        f"Made by PlantCraft PID on {now.strftime('%Y-%m-%d %H:%M')} UTC from the plant map: "
        f"{s['sheets']} sheets, {s['equipment']} pieces of equipment, {s['instruments']} "
        f"instruments, {s['loops']} control loops ({s['loops_complete']} complete) and "
        f"{s['feeds']} process lines between equipment. The drawings were read by the drawing "
        "reader with no language model; what people marked Wrong on the map is left out, and "
        "what the reader was unsure of is marked (unsure). Check a line on its sheet before "
        "acting on it.",
        "",
    ]
    units: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in plant["items"]:
        units[item["unit"] or "No unit"].append(item)
    loops_by_unit: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for loop in plant["loops"]:
        loops_by_unit[loop["unit"] or "No unit"].append(loop)
    feeds = [(r["from"], r["to"]) for r in rel if r["type"] == "feeds"]
    for unit in sorted(units):
        members = units[unit]
        areas = sorted({i["area"] for i in members if i["area"]})
        equipment = [i["tag"] for i in members if i["family"] == "equipment"]
        order = _flow_order(equipment, feeds)
        out += [f"## Unit {unit}", ""]
        if areas:
            out += [f"Areas: {', '.join(areas)}.", ""]
        out += [f"Equipment in flow order: {_join(order)}.", ""]
        for tag in order:
            item = items[tag]
            links = by[tag]
            out += [
                f"### {tag} ({item['cls'].replace('_', ' ')}, unit {unit})",
                "",
                f"- Feeds: {_join(links['feeds'])}.",
                f"- Fed by: {_join(links['by feeds'])}.",
                f"- Measured by: {_join(links['by measures'])}.",
                f"- Valves on its lines: {_join(links['by on'])}.",
                f"- Drawn on: {drawn_on(item)}.",
            ]
            if item["confidence"] == "low":
                out.append(f"- Unsure: {item['why']}.")
            out.append("")
        loops = loops_by_unit.get(unit, [])
        if loops:
            out += [f"### Control loops of unit {unit}", ""]
            for loop in loops:
                out.append(
                    f"- {loop['loop']}: measures with {_join(loop['transmitters'])}, moves "
                    f"{_join(loop['valves'])}, on {_join(loop['equipment'])}"
                    + ("." if loop["complete"] else " (incomplete on the drawings).")
                )
            out.append("")
        instruments = [i for i in members if i["family"] == "instrument"]
        if instruments:
            out += [f"### Instruments of unit {unit}", ""]
            for i in sorted(instruments, key=lambda i: i["tag"]):
                parts = [
                    f"{k} {_join(v)}" for k, v in by[i["tag"]].items() if not k.startswith("by ")
                ]
                out.append(
                    f"- {i['tag']} ({i['cls'].replace('_', ' ')}): "
                    + ("; ".join(parts) if parts else "no line found")
                    + f". Drawn on {drawn_on(i)}."
                )
            out.append("")
    if sheets:
        out += ["## Sheets read", ""]
        for name, sheet in sheets.items():
            out.append(
                f"- {name}: {sheet['title'] or 'untitled'}, unit {sheet['unit'] or 'none'}, "
                f"{len(sheet['items'])} tags."
            )
        out.append("")
    if s["doubt_count"]:
        out += [
            "## To check",
            "",
            f"{s['doubt_count']} findings are unsure; the plant map lists them under To check.",
            "",
        ]
    return "\n".join(out)
