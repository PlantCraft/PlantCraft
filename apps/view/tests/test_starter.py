"""A unit's overview from the asset list: each unit an import names gets one, with its loops at
any depth under it, in tables of twelve."""

from __future__ import annotations

from dashcraft.dashboards.model import DashboardPayload
from dashcraft.dashboards.starter import unit_overviews


def _tree() -> list[dict]:
    assets = [
        {"id": "U-100", "name": "Crude unit", "parent_id": None},
        {"id": "U-200", "name": "Hydrotreater", "parent_id": None},
        {"id": "A-1", "name": "Heater area", "parent_id": "U-100"},
    ]
    assets += [
        {"id": f"FIC-1{n:03d}", "parent_id": "A-1", "signals": {"pv": f"FIC-1{n:03d}.PV"}}
        for n in range(30)
    ]
    assets.append({"id": "P-1", "parent_id": "U-200"})  # no PV: nothing to draw
    return assets


def test_each_unit_gets_its_overview_with_every_loop_under_it():
    [crude] = unit_overviews(_tree(), ["U-100", "U-200", "U-999"])
    assert crude["name"] == "Crude unit overview"
    tables = [card for card in crude["cards"] if card["kind"] == "table"]
    assert [len(card["items"]) for card in tables] == [12, 12, 6]
    assert [card["card_id"] for card in crude["cards"]][:2] == ["table-pv", "trend-pv"]
    DashboardPayload.model_validate(crude)
