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

from doccraft.i18n import t

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
    return ", ".join(values) if values else t("none found")


def summary_markdown(plant: dict[str, Any], scope: str, now: datetime | None = None) -> str:
    """``plant`` from :func:`doccraft.plantmap.build.build_map`; ``scope`` says which drawings
    it comes from (a folder's name)."""

    now = now or datetime.now(UTC)
    items = {i["tag"]: i for i in plant["items"]}
    rel = plant["relations"]
    by: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for r in rel:
        a, kind, b = r["from"], r["type"], r["to"]
        note = "" if r["confidence"] != "low" else t(" (unsure)")
        by[a][kind].append(b + note)
        by[b]["by " + kind].append(a + note)
    sheets = {s["sheet"]: s for s in plant["sheets"]}

    def drawn_on(item: dict[str, Any]) -> str:
        seen = []
        for p in item["places"]:
            name = t(
                "{sheet} ({title}, page {page})",
                sheet=p["sheet"],
                title=p["doc_title"] or t("untitled"),
                page=p["page"],
            )
            if name not in seen:
                seen.append(name)
        return _join(seen)

    s = plant["summary"]
    out = [
        t("# Plant summary from the P&IDs ({scope})", scope=scope),
        "",
        t(
            "Made by PlantCraft Documents on {when} UTC from the plant map: {sheets} sheets, "
            "{equipment} pieces of equipment, {instruments} instruments, {loops} control loops "
            "({complete} complete) and {feeds} process lines between equipment. The drawings "
            "were read by the drawing reader with no language model; what people marked Wrong on "
            "the map is left out, and what the reader was unsure of is marked (unsure). Check a "
            "line on its sheet before acting on it.",
            when=now.strftime("%Y-%m-%d %H:%M"),
            sheets=s["sheets"],
            equipment=s["equipment"],
            instruments=s["instruments"],
            loops=s["loops"],
            complete=s["loops_complete"],
            feeds=s["feeds"],
        ),
        "",
    ]
    no_unit = t("No unit")
    units: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in plant["items"]:
        units[item["unit"] or no_unit].append(item)
    loops_by_unit: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for loop in plant["loops"]:
        loops_by_unit[loop["unit"] or no_unit].append(loop)
    feeds = [(r["from"], r["to"]) for r in rel if r["type"] == "feeds"]
    for unit in sorted(units):
        members = units[unit]
        areas = sorted({i["area"] for i in members if i["area"]})
        equipment = [i["tag"] for i in members if i["family"] == "equipment"]
        order = _flow_order(equipment, feeds)
        out += [t("## Unit {unit}", unit=unit), ""]
        if areas:
            out += [t("Areas: {areas}.", areas=", ".join(areas)), ""]
        out += [t("Equipment in flow order: {order}.", order=_join(order)), ""]
        for tag in order:
            item = items[tag]
            links = by[tag]
            out += [
                t(
                    "### {tag} ({cls}, unit {unit})",
                    tag=tag,
                    cls=item["cls"].replace("_", " "),
                    unit=unit,
                ),
                "",
                t("- Feeds: {tags}.", tags=_join(links["feeds"])),
                t("- Fed by: {tags}.", tags=_join(links["by feeds"])),
                t("- Measured by: {tags}.", tags=_join(links["by measures"])),
                t("- Valves on its lines: {tags}.", tags=_join(links["by on"])),
                t("- Drawn on: {sheets}.", sheets=drawn_on(item)),
            ]
            if item["confidence"] == "low":
                out.append(t("- Unsure: {why}.", why=item["why"]))
            out.append("")
        loops = loops_by_unit.get(unit, [])
        if loops:
            out += [t("### Control loops of unit {unit}", unit=unit), ""]
            for loop in loops:
                text = (
                    "- {loop}: measures with {transmitters}, moves {valves}, on {equipment}."
                    if loop["complete"]
                    else "- {loop}: measures with {transmitters}, moves {valves}, on {equipment} "
                    "(incomplete on the drawings)."
                )
                out.append(
                    t(
                        text,
                        loop=loop["loop"],
                        transmitters=_join(loop["transmitters"]),
                        valves=_join(loop["valves"]),
                        equipment=_join(loop["equipment"]),
                    )
                )
            out.append("")
        instruments = [i for i in members if i["family"] == "instrument"]
        if instruments:
            out += [t("### Instruments of unit {unit}", unit=unit), ""]
            for i in sorted(instruments, key=lambda i: i["tag"]):
                parts = [
                    f"{k} {_join(v)}" for k, v in by[i["tag"]].items() if not k.startswith("by ")
                ]
                out.append(
                    t(
                        "- {tag} ({cls}): {lines}. Drawn on {sheets}.",
                        tag=i["tag"],
                        cls=i["cls"].replace("_", " "),
                        lines="; ".join(parts) if parts else t("no line found"),
                        sheets=drawn_on(i),
                    )
                )
            out.append("")
    if sheets:
        out += [t("## Sheets read"), ""]
        for name, sheet in sheets.items():
            out.append(
                t(
                    "- {name}: {title}, unit {unit}, {n} tags.",
                    name=name,
                    title=sheet["title"] or t("untitled"),
                    unit=sheet["unit"] or t("none"),
                    n=len(sheet["items"]),
                )
            )
        out.append("")
    if s["doubt_count"]:
        out += [
            t("## To check"),
            "",
            t(
                "{n} findings are unsure; the plant map lists them under To check.",
                n=s["doubt_count"],
            ),
            "",
        ]
    return "\n".join(out)
