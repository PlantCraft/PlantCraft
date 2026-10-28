"""HTTP routes: View's dashboards and reports as objects (``[[contributes.objects]]``).

What the assistant and notebooks read with ``list_app_objects`` / ``pc.app("view")`` (format
``plantcraft-objects/1``, ``plantcraft_sdk.server.objects``), so a question asked away from
the Dashboards page ("which dashboard shows the feed?") reads the list too. A closed folder hides
its dashboards and reports here as it does on the pages; both are read only.
"""

from __future__ import annotations

from typing import Any

from plantcraft_sdk.server.objects import AppObjects, object_item

from dashcraft.api.deps import permissions
from dashcraft.diagrams.model import bindings

objects = AppObjects()


def _signals(cards: list[dict[str, Any]]) -> list[str]:
    """The signals the cards show, once each, in their order."""

    found: dict[str, None] = {}
    for card in cards:
        for item in card.get("items") or []:
            if item.get("signal_id"):
                found[str(item["signal_id"])] = None
    return list(found)


def _section_cards(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [section["card"] for section in report.get("sections") or [] if section.get("card")]


@objects.lister("dashboard")
def dashboards(user: Any, rt: Any) -> list[dict[str, Any]]:
    perms = permissions(rt, user)
    return [
        object_item(
            item["dashboard_id"],
            item.get("name") or item["dashboard_id"],
            description=item.get("description") or "",
            tags=item.get("tags") or [],
            panels=[
                card.get("title") or card.get("kind") or "" for card in item.get("cards") or []
            ],
            signals=_signals(item.get("cards") or []),
            url=f"/dash/dashboards/{item['dashboard_id']}",
            updated_at=item.get("updated_at"),
        )
        for item in rt.dashboards.list()
        if perms.sees(item)
    ]


@objects.getter("dashboard")
def dashboard(user: Any, rt: Any, dashboard_id: str) -> dict[str, Any] | None:
    found = rt.dashboards.get(dashboard_id) if len(dashboard_id) <= 40 else None
    if found is None or not permissions(rt, user).sees(found):
        return None
    return {"id": dashboard_id, **found, "signals": _signals(found.get("cards") or [])}


@objects.lister("report")
def reports(user: Any, rt: Any) -> list[dict[str, Any]]:
    perms = permissions(rt, user)
    rows = []
    for item in rt.reports.list():
        if not perms.sees(item):
            continue
        described = rt.report_service.describe(item)
        rows.append(
            object_item(
                item["report_id"],
                item.get("name") or item["report_id"],
                description=item.get("description") or "",
                period=item.get("period") or "",
                cadence=described.get("cadence") or "",
                next_run=item.get("next_run_at"),
                sections=[
                    section.get("title") or section.get("kind") or ""
                    for section in item.get("sections") or []
                ],
                signals=_signals(_section_cards(item)),
                url=f"/dash/reports/{item['report_id']}",
            )
        )
    return rows


@objects.getter("report")
def report(user: Any, rt: Any, report_id: str) -> dict[str, Any] | None:
    found = rt.reports.get(report_id) if len(report_id) <= 40 else None
    if found is None or not permissions(rt, user).sees(found):
        return None
    return {
        "id": report_id,
        **rt.report_service.describe(found),
        "signals": _signals(_section_cards(found)),
    }


def _bound(diagram: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """A diagram's bindings (element, slot, item), and the signals and assets they read."""

    rows, signals, assets = [], {}, {}
    for element, slot, binding in bindings(diagram):
        item = binding.get("item") if isinstance(binding, dict) else None
        if not isinstance(item, dict):
            continue
        rows.append({"element": element, "slot": slot, "item": item})
        if item.get("signal_id"):
            signals[str(item["signal_id"])] = None
        if item.get("asset_id"):
            assets[str(item["asset_id"])] = None
    return rows, list(signals), list(assets)


def _elements(diagram: dict[str, Any]) -> list[dict[str, Any]]:
    """Each element in a line: what it is and what it names (no geometry)."""

    keep = ("id", "type", "symbol", "label", "asset_id", "text", "kind", "medium")
    return [
        {key: element[key] for key in keep if element.get(key) not in (None, "")}
        for element in diagram.get("elements") or []
        if isinstance(element, dict)
    ]


@objects.lister("diagram")
def diagrams(user: Any, rt: Any) -> list[dict[str, Any]]:
    perms = permissions(rt, user)
    rows = []
    for item in rt.diagrams.list():
        if not perms.sees(item):
            continue
        _, signals, assets = _bound(item)
        rows.append(
            object_item(
                item["diagram_id"],
                item.get("name") or item["diagram_id"],
                description=item.get("description") or "",
                tags=item.get("tags") or [],
                elements=len(item.get("elements") or []),
                symbols=[
                    element.get("label") or element.get("symbol") or ""
                    for element in item.get("elements") or []
                    if element.get("type") == "symbol"
                ][:60],
                signals=signals,
                assets=assets,
                url=f"/dash/diagrams/{item['diagram_id']}",
                updated_at=item.get("updated_at"),
            )
        )
    return rows


@objects.getter("diagram")
def diagram(user: Any, rt: Any, diagram_id: str) -> dict[str, Any] | None:
    found = rt.diagrams.get(diagram_id) if len(diagram_id) <= 40 else None
    if found is None or not permissions(rt, user).sees(found):
        return None
    rows, signals, assets = _bound(found)
    return {
        "id": diagram_id,
        **found,
        "elements": _elements(found),
        "bindings": rows,
        "signals": signals,
        "assets": assets,
    }


router = objects.router()
