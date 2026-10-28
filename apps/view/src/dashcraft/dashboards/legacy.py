"""Dashboards saved before round 7, read as round 7 writes them.

Old cards had four limits (``thresholds``), ``decimals`` and ``gauge_min``/``gauge_max`` on the
card, the kinds ``kpi`` and ``spark``, and no place on the grid (they flowed in order). Old
dashboards had ``context_kind`` and items ``$context``: the asset variable ``asset``. Every
saved dashboard, version, template, exported file and API call goes through these functions
(the models' ``before`` validators), so nothing is ever read twice in two shapes.
"""

from __future__ import annotations

from typing import Any

from dashcraft.dashboards.fields import legacy_thresholds

CONTEXT = "$context"
CONTEXT_VARIABLE = "asset"
# Old kind: (new kind, the stat's graph).
OLD_KINDS = {"kpi": ("stat", "none"), "spark": ("stat", "area")}


def upgrade_card(raw: Any) -> Any:
    if not isinstance(raw, dict):
        return raw
    card = dict(raw)
    options = dict(card.get("options") or {})
    if card.get("kind") in OLD_KINDS:
        kind, graph = OLD_KINDS[card["kind"]]
        card["kind"] = kind
        options.setdefault("graph", graph)
    field = dict(card.get("field") or {})
    if "thresholds" in card:
        old = card.pop("thresholds")
        if "thresholds" not in field:
            steps = legacy_thresholds(old)
            if steps is not None:
                field["thresholds"] = steps.model_dump()
    if "decimals" in card:
        decimals = card.pop("decimals")
        if decimals is not None:
            field.setdefault("decimals", decimals)
    for old, new in (("gauge_min", "min"), ("gauge_max", "max")):
        if old in card:
            value = card.pop(old)
            if value is not None:
                field.setdefault(new, value)
    card["field"] = field
    card["options"] = options
    items = card.get("items")
    if isinstance(items, list):
        card["items"] = [
            {**item, "asset_id": f"${CONTEXT_VARIABLE}"}
            if isinstance(item, dict) and item.get("asset_id") == CONTEXT
            else item
            for item in items
        ]
    return card


def upgrade_dashboard(raw: Any) -> Any:
    if not isinstance(raw, dict):
        return raw
    dashboard = dict(raw)
    variables = list(dashboard.get("variables") or [])
    kind = (
        (dashboard.get("context_kind") or "").strip()
        if isinstance(dashboard.get("context_kind"), str)
        else ""
    )
    if kind and not any(
        isinstance(item, dict) and item.get("type", "asset") == "asset" for item in variables
    ):
        names = {item.get("name") for item in variables if isinstance(item, dict)}
        if CONTEXT_VARIABLE not in names:
            variables.insert(
                0, {"name": CONTEXT_VARIABLE, "label": kind, "type": "asset", "asset_kind": kind}
            )
    dashboard["variables"] = variables
    if isinstance(dashboard.get("cards"), list):
        dashboard["cards"] = [upgrade_card(card) for card in dashboard["cards"]]
    return dashboard


GRID_COLUMNS = 12


def place_cards(cards: list[dict[str, Any]], first_page: str | None) -> list[dict[str, Any]]:
    """Every card at (x, y): cards without a place go, in order, to the first free place of
    their page, row by row, left to right (how the grid before round 7 flowed them, so an old
    dashboard keeps its look). Cards that have a place keep it."""

    taken: dict[str | None, list[tuple[int, int, int, int]]] = {}
    for card in cards:
        if isinstance(card.get("x"), int) and isinstance(card.get("y"), int):
            taken.setdefault(card.get("page_id") or first_page, []).append(_box(card))
    placed = []
    for card in cards:
        if isinstance(card.get("x"), int) and isinstance(card.get("y"), int):
            placed.append(card)
            continue
        page = card.get("page_id") or first_page
        boxes = taken.setdefault(page, [])
        width = min(GRID_COLUMNS, max(1, int(card.get("width") or 4)))
        height = max(1, int(card.get("height") or 2))
        x, y = _free(boxes, width, height)
        card = {**card, "x": x, "y": y}
        boxes.append((x, y, width, height))
        placed.append(card)
    return placed


def _box(card: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        int(card["x"]),
        int(card["y"]),
        int(card.get("width") or 4),
        int(card.get("height") or 2),
    )


def _free(boxes: list[tuple[int, int, int, int]], width: int, height: int) -> tuple[int, int]:
    def busy(x: int, y: int) -> bool:
        return any(
            x < bx + bw and x + width > bx and y < by + bh and y + height > by
            for bx, by, bw, bh in boxes
        )

    for y in range(10_000):
        for x in range(GRID_COLUMNS - width + 1):
            if not busy(x, y):
                return x, y
    return 0, max((by + bh for _, by, _, bh in boxes), default=0)
