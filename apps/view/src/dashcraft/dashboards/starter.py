"""Dashboard templates built from the plant's assets: a new dashboard can start from one.

Pure functions over the API v1 asset list: no reads here. Two templates:

- **Loop detail**: a template on the dashboard's asset (``context_kind`` = the kind
  of the first asset with a PV); PV and SP with their last hours, OP on a gauge, trends of PV
  with SP and OP, PV against OP and a note on how to read it.
- **Unit overview**: for the unit with the most such assets, a table of their PVs
  and a trend of the first few. ``unit_overviews`` draws one for each unit a new plant's
  import names (``[[contributes.start]]``).
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from dashcraft.dashboards.model import CONTEXT
from dashcraft.i18n import t

MAX_TABLE_ROWS = 12
MAX_TREND_LINES = 4
# A unit's overview lists this many tables of PVs at most (48 loops).
MAX_UNIT_TABLES = 4


def _context_item(role: str, label: str) -> dict[str, Any]:
    return {"asset_id": CONTEXT, "role": role, "label": label}


def _with_pv(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [asset for asset in assets if (asset.get("signals") or {}).get("pv")]


def loop_detail(assets: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = _with_pv(assets)
    if not candidates:
        return None
    kind = Counter(asset.get("kind") or "" for asset in candidates).most_common(1)[0][0]
    roles: set[str] = set()
    for asset in candidates:
        if asset.get("kind") == kind:
            roles.update((asset.get("signals") or {}).keys())
    cards: list[dict[str, Any]] = []
    # The value now with its last 8 hours (round 4: a number alone says little).
    for role, label in (("pv", "PV"), ("sp", "SP")):
        if role in roles:
            cards.append(
                {
                    "card_id": f"kpi-{role}",
                    "title": t("{role} now", role=label),
                    "kind": "spark",
                    "items": [_context_item(role, label)],
                    "agg": "last",
                    "window": "8h",
                    "width": 3,
                }
            )
    if "op" in roles:
        cards.append(
            {
                "card_id": "kpi-op",
                "title": t("Controller output"),
                "kind": "gauge",
                "items": [_context_item("op", "OP")],
                "agg": "last",
                "window": "1h",
                "gauge_min": 0,
                "gauge_max": 100,
                "thresholds": {"low_warn": 5, "high_warn": 95},
                "width": 3,
            }
        )
    cards.append(
        {
            "card_id": "kpi-pv-mean",
            "title": t("PV mean, last 24 h"),
            "kind": "kpi",
            "items": [_context_item("pv", "PV")],
            "agg": "mean",
            "window": "24h",
            "width": 3,
        }
    )
    trend = [_context_item("pv", "PV")]
    if "sp" in roles:
        trend.append(_context_item("sp", "SP"))
    cards.append(
        {
            "card_id": "trend-pv",
            "title": t("PV and SP"),
            "kind": "trend",
            "items": trend,
            "window": "8h",
            "width": 8,
            "height": 4,
        }
    )
    if "op" in roles:
        cards.append(
            {
                "card_id": "trend-op",
                "title": t("Controller output"),
                "kind": "trend",
                "items": [_context_item("op", "OP")],
                "window": "8h",
                "width": 4,
                "height": 4,
            }
        )
        # OP against PV: a valve that sticks draws a parallelogram, a healthy loop a cloud.
        cards.append(
            {
                "card_id": "scatter-op-pv",
                "title": t("PV against OP"),
                "kind": "scatter",
                "items": [_context_item("op", "OP"), _context_item("pv", "PV")],
                "window": "8h",
                "width": 6,
                "height": 4,
            }
        )
        cards.append(
            {
                "card_id": "note",
                "title": t("How to read it"),
                "kind": "text",
                "items": [],
                "text": t(
                    "PV against OP: a loop that follows its setpoint draws a cloud along a "
                    "line; a sticky valve draws flat steps (OP moves, PV does not); a "
                    "saturated valve piles up at 0 or 100 %.\n\nThe gauge turns amber when "
                    "the output is below 5 % or above 95 %."
                ),
                "width": 6,
                "height": 4,
            }
        )
    return {
        "name": t("Loop detail"),
        "description": t("Pick an asset at the top: every panel follows it."),
        "context_kind": kind,
        "refresh_seconds": 30,
        "cards": cards,
    }


def unit_overview(assets: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The overview of the unit with the most assets with a PV, under it directly."""

    by_parent: dict[str, list[dict[str, Any]]] = {}
    for asset in _with_pv(assets):
        if asset.get("parent_id"):
            by_parent.setdefault(asset["parent_id"], []).append(asset)
    if not by_parent:
        return None
    parent_id, children = max(by_parent.items(), key=lambda pair: len(pair[1]))
    if len(children) < 2:
        return None
    names = {asset.get("id"): asset.get("name") or asset.get("id") for asset in assets}
    return overview(str(names.get(parent_id, parent_id)), children, names)


def unit_overviews(assets: list[dict[str, Any]], units: list[str]) -> list[dict[str, Any]]:
    """One overview for each of ``units`` (asset ids) with an asset with a PV anywhere under it,
    in the order given: a new plant's first dashboards (``[[contributes.start]]``)."""

    wanted = set(units)
    parents = {asset.get("id"): asset.get("parent_id") for asset in assets}
    names = {asset.get("id"): asset.get("name") or asset.get("id") for asset in assets}
    members: dict[str, list[dict[str, Any]]] = {}
    for asset in _with_pv(assets):
        seen, current = set(), asset.get("parent_id")
        while current and current not in wanted and current not in seen:
            seen.add(current)
            current = parents.get(current)
        if current in wanted:
            members.setdefault(current, []).append(asset)
    return [
        overview(str(names.get(unit, unit)), members[unit], names)
        for unit in units
        if unit in members
    ]


def overview(unit: str, members: list[dict[str, Any]], names: dict[Any, Any]) -> dict[str, Any]:
    """A unit's overview: its PVs in tables of ``MAX_TABLE_ROWS`` (``MAX_UNIT_TABLES`` at most)
    and a trend of the first few."""

    members = sorted(members, key=lambda asset: str(asset.get("name") or asset.get("id")))
    rows = [
        {"asset_id": asset["id"], "role": "pv", "label": str(names.get(asset["id"], asset["id"]))}
        for asset in members[: MAX_TABLE_ROWS * MAX_UNIT_TABLES]
    ]
    tables = [rows[index : index + MAX_TABLE_ROWS] for index in range(0, len(rows), MAX_TABLE_ROWS)]
    cards: list[dict[str, Any]] = [
        {
            "card_id": "table-pv" if number == 0 else f"table-pv-{number + 1}",
            "title": t("Process values, last 24 h"),
            "kind": "table",
            "items": items,
            "window": "24h",
            "width": 6,
            "height": 4,
        }
        for number, items in enumerate(tables)
    ]
    cards.insert(
        1,
        {
            "card_id": "trend-pv",
            "title": t("Process values, last 24 h"),
            "kind": "trend",
            "items": rows[:MAX_TREND_LINES],
            "window": "24h",
            "width": 6,
            "height": 4,
        },
    )
    return {
        "name": t("{unit} overview", unit=unit),
        "description": t("Process values of the loops in {unit}.", unit=unit),
        "context_kind": None,
        "refresh_seconds": 60,
        "cards": cards,
    }


def starter_dashboards(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in (loop_detail(assets), unit_overview(assets)) if item]


# The New dashboard dialog offers these as "start from"; nothing is saved until the editor saves.
TEMPLATES = (("loop-detail", loop_detail), ("unit-overview", unit_overview))


def templates(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The templates the plant's assets allow, each with the dashboard it starts."""

    out = []
    for template_id, build in TEMPLATES:
        draft = build(assets)
        if draft:
            out.append(
                {
                    "template_id": template_id,
                    "name": draft["name"],
                    "description": draft["description"],
                    "cards": len(draft["cards"]),
                    "draft": draft,
                }
            )
    return out
