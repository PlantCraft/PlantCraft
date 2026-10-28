"""A report started from a dashboard: its pair as a document.

Each page of the dashboard becomes a ``#`` heading, each card a card cell in the order the grid
reads (top to bottom, left to right), a text card a text cell, and a card narrower than half the
grid a half cell (two side by side, as in the PDF). A report names fixed signals: every variable
takes one value (its default, else its first) and the cards say it in their titles; a card's
own window gives way to the report's period, and a repeated card is drawn once.
"""

from __future__ import annotations

from typing import Any

from dashcraft.dashboards.model import Card
from dashcraft.dashboards.variables import interpolate, whole
from dashcraft.reports.model import MAX_SECTIONS, MAX_TEXT


def _order(card: dict[str, Any], index: int) -> tuple[int, int, int]:
    return (
        card.get("y") if card.get("y") is not None else 10_000 + index,
        card.get("x") or 0,
        index,
    )


def _fixed(card: dict[str, Any], values: dict[str, list[str]], names: dict[str, list[str]]) -> dict:
    """The card with each variable set to its one value."""

    items = []
    for item in card.get("items") or []:
        item = dict(item)
        asset = whole(item.get("asset_id"))
        if asset is not None:
            item["asset_id"] = (values.get(asset) or [""])[0] or None
        if item.get("signal_id"):
            item["signal_id"] = interpolate(
                item["signal_id"], {k: v[:1] for k, v in values.items()}
            )
        if item.get("label"):
            item["label"] = interpolate(item["label"], names)
        items.append(item)
    fixed = {
        **card,
        "items": [item for item in items if item.get("asset_id") or item.get("signal_id")],
        "title": interpolate(card.get("title") or "", names),
        "description": interpolate(card.get("description") or "", names),
        "repeat": None,
        "page_id": None,
        "x": None,
        "y": None,
    }
    if str(fixed.get("window") or "").startswith("$"):
        fixed["window"] = "1h"
    return fixed


def sections_from(
    dashboard: dict[str, Any], values: dict[str, list[str]], names: dict[str, list[str]]
) -> list[dict[str, Any]]:
    """The sections of a report that reads what ``dashboard`` shows, ``values`` being the one
    value each variable takes (asset ids) and ``names`` how they read (asset names)."""

    sections: list[dict[str, Any]] = []
    if dashboard.get("description"):
        text = interpolate(dashboard["description"], names)
        sections.append({"section_id": "s1", "kind": "text", "text": text[:MAX_TEXT]})
    pages = dashboard.get("pages") or []
    first = pages[0]["page_id"] if pages else None
    groups = [(page.get("name") or "", page["page_id"]) for page in pages] or [("", None)]
    cards = list(dashboard.get("cards") or [])
    for name, page_id in groups:
        on_page = [
            (index, card)
            for index, card in enumerate(cards)
            if len(groups) == 1 or (card.get("page_id") or first) == page_id
        ]
        if len(groups) > 1 and on_page:
            sections.append({"kind": "text", "text": f"# {interpolate(name, names)}"})
        for _index, card in sorted(on_page, key=lambda pair: _order(pair[1], pair[0])):
            if card.get("kind") == "text":
                title = interpolate(card.get("title") or "", names)
                body = interpolate(card.get("text") or "", names)
                text = (f"## {title}\n\n{body}" if title else body).strip()
                if text:
                    sections.append({"kind": "text", "text": text[:MAX_TEXT]})
                continue
            fixed = _fixed(card, values, names)
            if not fixed["items"]:
                continue
            try:
                Card.model_validate(fixed)
            except ValueError:
                continue
            half = int(card.get("width") or 12) <= 6 and card.get("kind") != "table"
            sections.append({"kind": "card", "card": fixed, "width": "half" if half else "full"})
    sections = sections[:MAX_SECTIONS]
    for number, section in enumerate(sections, start=1):
        section["section_id"] = f"s{number}"
    return sections


__all__ = ["sections_from"]
