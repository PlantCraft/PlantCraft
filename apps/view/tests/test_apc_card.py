"""The multivariable controller panel (V10): a third-party APC's MVs and CVs, read only."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from dashcraft.dashboards.model import Card
from dashcraft.query.apc import at_limit, read_apc
from dashcraft.query.cards import Reader, read_card

NOW = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)

ROLES = ("value", "lo", "hi", "target", "status", "shadow_price")


def _variable(asset_id, name, kind, parent="apc-1", band=None):
    attributes = {"unit": "t/h"}
    if band is not None:
        attributes["limit_band"] = band
    return {
        "id": asset_id,
        "name": name,
        "kind": kind,
        "parent_id": parent,
        "attributes": attributes,
        "signals": {role: f"plant:{name}.{role}" for role in ROLES},
    }


ASSETS = [
    {
        "id": "apc-1",
        "name": "C-100 APC",
        "kind": "apc",
        "attributes": {"vendor": "Any MPC", "cost_unit": "$/h"},
        "signals": {"on": "plant:APC.on", "mode": "plant:APC.mode"},
    },
    _variable("mv-1", "FIC-101.SP", "apc_mv"),
    _variable("mv-2", "TIC-102.SP", "apc_mv"),
    _variable("cv-1", "AI-103", "apc_cv", band=0.5),
    _variable("cv-9", "AI-999", "apc_cv", parent="apc-2"),
]
NOW_VALUES = {
    "plant:APC.on": 1,
    "plant:APC.mode": "CONTROL",
    "plant:FIC-101.SP.value": 50,
    "plant:FIC-101.SP.lo": 10,
    "plant:FIC-101.SP.hi": 100,
    "plant:FIC-101.SP.target": 99.5,
    "plant:FIC-101.SP.status": 1,
    "plant:FIC-101.SP.shadow_price": 3.2,
    "plant:TIC-102.SP.value": 60,
    "plant:TIC-102.SP.lo": 0,
    "plant:TIC-102.SP.hi": 100,
    "plant:TIC-102.SP.status": 0,
    "plant:AI-103.value": 2.2,
    "plant:AI-103.lo": 2.0,
    "plant:AI-103.hi": 5.0,
    "plant:AI-103.target": 2.4,
    "plant:AI-103.status": 1,
}


class Plant:
    def asset(self, asset_id):
        return next(a for a in ASSETS if a["id"] == asset_id)

    def assets(self, kind=None):
        return [a for a in ASSETS if kind is None or a["kind"] == kind]

    def series_many(self, signals, start, end, step, **_):
        series = []
        for signal in signals:
            if signal not in NOW_VALUES:
                continue
            value = NOW_VALUES[signal]
            series.append(
                {"signal": signal, "t": [start.isoformat(), end.isoformat()], "v": [value, value]}
            )
        return {"series": series}


def test_the_controller_and_its_variables_now_and_over_the_horizon():
    data = read_apc(Reader(client=Plant(), clock=lambda: NOW), "apc-1", "1h")
    assert data["error"] is None
    assert data["controller"] == {
        "id": "apc-1",
        "name": "C-100 APC",
        "on": True,
        "mode": "CONTROL",
        "vendor": "Any MPC",
        "cost_unit": "$/h",
    }
    names = [(v["type"], v["name"]) for v in data["variables"]]
    assert names == [("mv", "FIC-101.SP"), ("mv", "TIC-102.SP"), ("cv", "AI-103")]  # not AI-999
    fic, tic, ai = data["variables"]
    assert fic["at_limit"] == "hi" and fic["shadow_price"] == 3.2 and fic["in_service"] is True
    assert tic["in_service"] is False and tic["target"] is None and tic["at_limit"] is None
    assert ai["at_limit"] == "lo"  # target 2.4 within its band of 0.5 above lo 2.0
    assert fic["value_line"] == [50, 50] and fic["target_line"] == [99.5, 99.5]
    assert data["counts"] == {"mv": 2, "cv": 1, "in_service": 2, "at_limits": 2}


def test_at_limit_uses_the_target_else_the_value_and_one_percent_by_default():
    assert at_limit({"lo": 0, "hi": 100, "value": 99.5}) == "hi"
    assert at_limit({"lo": 0, "hi": 100, "value": 98}) is None
    assert at_limit({"lo": 0, "hi": 100, "value": 0.5, "target": 50}) is None
    assert at_limit({"lo": 0, "hi": 100, "value": 50, "target": 0.4}) == "lo"
    assert at_limit({"lo": 0, "hi": 100, "value": 97}, band=5) == "hi"
    assert at_limit({"lo": None, "hi": 100, "value": 100}) is None


def test_an_asset_that_is_not_a_controller_says_so():
    data = read_apc(Reader(client=Plant(), clock=lambda: NOW), "mv-1", "1h")
    assert "not a multivariable controller" in data["error"]


def test_a_controller_card_reads_its_controller_and_takes_no_signals():
    card = Card.model_validate(
        {"card_id": "c1", "kind": "apc", "apc_id": "apc-1", "window": "1h", "height": 4}
    )
    data = read_card(Reader(client=Plant(), clock=lambda: NOW), card)
    assert data["apc"]["counts"]["mv"] == 2
    with pytest.raises(ValidationError, match="Pick the multivariable controller"):
        Card.model_validate({"card_id": "c1", "kind": "apc", "height": 4})
    with pytest.raises(ValidationError, match="not signals"):
        Card.model_validate(
            {
                "card_id": "c1",
                "kind": "apc",
                "apc_id": "apc-1",
                "height": 4,
                "items": [{"signal_id": "plant:x"}],
            }
        )
