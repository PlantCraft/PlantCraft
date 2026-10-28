"""The card and dashboard contract refuses what it cannot draw, with words a person can act on."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dashcraft.dashboards.fields import (
    FieldConfig,
    Override,
    Thresholds,
    effective,
    legacy_thresholds,
    state_of,
)
from dashcraft.dashboards.model import (
    CONTEXT,
    Card,
    DashboardPayload,
    window_seconds,
)
from tests.conftest import dashboard, kpi


@pytest.mark.parametrize(
    ("window", "seconds"), [("90s", 90), ("15m", 900), ("8h", 28800), ("7d", 604800)]
)
def test_windows(window, seconds):
    assert window_seconds(window) == seconds


@pytest.mark.parametrize("window", ["", "0h", "1w", "h", "1.5h", "-1h", "367d", "1h ", "99999d"])
def test_bad_windows(window):
    with pytest.raises(ValueError):
        window_seconds(window)


def _state(thresholds, value, **row):
    return state_of(FieldConfig(thresholds=thresholds), value, row)


def test_the_old_four_limits_become_steps_with_the_same_states():
    limits = legacy_thresholds({"low_alarm": 10, "low_warn": 20, "high_warn": 80, "high_alarm": 90})
    assert [(step.value, step.level) for step in limits.steps] == [
        (None, "alarm"),
        (10, "warning"),
        (20, "ok"),
        (80, "warning"),
        (90, "alarm"),
    ]
    assert [_state(limits, v) for v in (5, 15, 50, 85, 95, None)] == [
        "alarm",
        "warning",
        "ok",
        "warning",
        "alarm",
        "none",
    ]
    assert legacy_thresholds({}) is None
    assert _state(Thresholds(), 50) == "none"
    with pytest.raises(ValidationError):
        Thresholds.model_validate({"steps": [{}, {"value": float("inf"), "level": "alarm"}]})


def test_threshold_steps_are_sorted_and_have_one_base():
    steps = Thresholds.model_validate(
        {"steps": [{"value": 90, "level": "alarm"}, {"value": 70, "level": "warning"}]}
    )
    # Without a base, values below every step are ok.
    assert [step.value for step in steps.steps] == [None, 70, 90]
    assert [_state(steps, v) for v in (10, 70, 89.9, 90)] == ["ok", "warning", "warning", "alarm"]
    with pytest.raises(ValidationError, match="same value"):
        Thresholds.model_validate({"steps": [{"value": 1}, {"value": 1}]})
    with pytest.raises(ValidationError, match="one base"):
        Thresholds.model_validate({"steps": [{}, {}]})
    # A step can be only a colour.
    colour = Thresholds.model_validate({"steps": [{"level": "none", "color": "#123456"}]})
    assert _state(colour, 5) == "none"


def test_percentage_thresholds_use_the_range():
    steps = Thresholds.model_validate(
        {"mode": "percentage", "steps": [{}, {"value": 80, "level": "alarm"}]}
    )
    # The field's min and max, else the signal's range; without either, no state.
    assert state_of(FieldConfig(thresholds=steps, min=0, max=200), 170, {}) == "alarm"
    assert state_of(FieldConfig(thresholds=steps, min=0, max=200), 150, {}) == "ok"
    assert _state(steps, 9, low=0, high=10) == "alarm"
    assert _state(steps, 9) == "none"


def test_mappings_show_words_and_can_be_a_state():
    config = FieldConfig.model_validate(
        {
            "mappings": [
                {"type": "value", "value": "0", "text": "Off"},
                {"type": "range", "low": 2, "high": 3, "text": "Fault", "level": "alarm"},
                {"type": "text", "value": "TRIP", "level": "alarm"},
            ]
        }
    )
    assert state_of(config, 2.5, {}) == "alarm"
    assert state_of(config, "trip", {}) == "alarm"
    assert state_of(config, 0, {}) == "none"


def test_overrides_change_some_signals():
    defaults = FieldConfig(unit="m3/h", decimals=1)
    overrides = [
        Override.model_validate(
            {"match": {"by": "role", "value": "PV"}, "field": {"color": "red"}}
        ),
        Override.model_validate(
            {"match": {"by": "name", "value": "fic-1*"}, "field": {"decimals": 3}}
        ),
        Override.model_validate(
            {"match": {"by": "signal", "value": "x:y"}, "field": {"unit": "%"}}
        ),
    ]
    pv = effective(defaults, overrides, {"role": "pv", "label": "FIC-101 PV", "signal": "a"})
    assert (pv.color, pv.decimals, pv.unit) == ("red", 3, "m3/h")
    sp = effective(defaults, overrides, {"role": "sp", "label": "LIC-1 SP", "signal": "x:y"})
    assert (sp.color, sp.decimals, sp.unit) == (None, 1, "%")


def test_an_item_names_a_signal_or_an_asset_role():
    Card.model_validate(kpi(asset_id="fic-101", role="pv"))
    with pytest.raises(ValidationError, match="Pick a signal"):
        Card.model_validate(kpi(asset_id="fic-101"))
    with pytest.raises(ValidationError, match="Pick a signal"):
        Card.model_validate({**kpi(), "items": [{"label": "only a label"}]})


def test_old_cards_are_read_in_the_round_7_shape():
    old = {
        **kpi(asset_id=CONTEXT, role="pv"),
        "thresholds": {"high_alarm": 90},
        "decimals": 2,
    }
    card = Card.model_validate(old)
    assert card.kind == "stat" and card.options.graph == "none"
    assert card.items[0].asset_id == "$asset"
    assert card.field.decimals == 2 and card.field.thresholds.steps[-1].value == 90
    spark = Card.model_validate({**kpi(), "kind": "spark"})
    assert (spark.kind, spark.options.graph) == ("stat", "area")
    gauge = Card.model_validate({**kpi(), "kind": "gauge", "gauge_min": 0, "gauge_max": 50})
    assert (gauge.field.min, gauge.field.max) == (0, 50)


def test_a_stat_shows_several_signals():
    card = {**kpi(), "items": [{"signal_id": "A"}, {"signal_id": "B"}]}
    assert len(Card.model_validate(card).items) == 2
    every = Card.model_validate({**kpi(), "items": [{"asset_id": "fic-101", "role": "*"}]})
    assert every.items[0].every_role


def test_dashboards_check_their_cards():
    with pytest.raises(ValidationError, match="same id"):
        DashboardPayload.model_validate(dashboard(cards=[kpi("a"), kpi("a")]))
    with pytest.raises(ValidationError, match="not an asset variable"):
        DashboardPayload.model_validate(dashboard(cards=[kpi(asset_id=CONTEXT, role="pv")]))
    old = DashboardPayload.model_validate(
        dashboard(context_kind="loop", cards=[kpi(asset_id=CONTEXT, role="pv")])
    )
    # The old dashboard's asset is the asset variable "asset".
    assert [(v.name, v.type, v.asset_kind) for v in old.variables] == [("asset", "asset", "loop")]
    assert old.context_kind == "loop"
    with pytest.raises(ValidationError, match="Refresh"):
        DashboardPayload.model_validate(dashboard(refresh_seconds=7))
    with pytest.raises(ValidationError):
        DashboardPayload.model_validate(dashboard(name="   "))
    with pytest.raises(ValidationError):
        DashboardPayload.model_validate(dashboard(cards=[kpi(str(i)) for i in range(31)]))


def test_the_new_card_kinds_check_their_signals():
    """Round 4: gauge, value and line, scatter (x then y) and text cards."""

    one = [{"signal_id": "A"}]
    two = [{"signal_id": "A"}, {"signal_id": "B"}]
    for kind in ("gauge", "spark"):
        Card.model_validate({**kpi(), "kind": kind, "items": one})
    Card.model_validate({**kpi(), "kind": "scatter", "items": two})
    with pytest.raises(ValidationError, match="x, then y"):
        Card.model_validate({**kpi(), "kind": "scatter", "items": one})
    Card.model_validate({**kpi(), "kind": "text", "items": [], "text": "Who to call"})
    with pytest.raises(ValidationError, match="no signal"):
        Card.model_validate({**kpi(), "kind": "text", "items": one, "text": "x"})
    with pytest.raises(ValidationError, match="Write the text"):
        Card.model_validate({**kpi(), "kind": "text", "items": [], "text": " "})
    with pytest.raises(ValidationError, match="at least one signal"):
        Card.model_validate({**kpi(), "kind": "trend", "items": []})
    with pytest.raises(ValidationError, match="minimum must be below"):
        Card.model_validate({**kpi(), "kind": "gauge", "gauge_min": 10, "gauge_max": 5})


def test_cards_span_columns_and_rows_of_the_grid():
    card = Card.model_validate(kpi())
    assert (card.width, card.height) == (4, 2)
    assert Card.model_validate({**kpi(), "width": 5, "height": 1}).height == 1
    trend = {**kpi(), "kind": "trend"}
    assert Card.model_validate({**trend, "height": 7}).height == 7
    assert Card.model_validate({**trend, "height": 12}).height == 12
    for bad in ({"width": 1}, {"width": 13}, {"height": 0}, {"height": 13}):
        with pytest.raises(ValidationError):
            Card.model_validate({**kpi(), **bad})
    # A chart one row high is unreadable.
    with pytest.raises(ValidationError, match="2 rows"):
        Card.model_validate({**trend, "height": 1})


def test_pages_hold_the_cards_of_a_dashboard():
    pages = [{"page_id": "p1", "name": " Overview "}, {"page_id": "p2", "name": "Pumps"}]
    cards = [kpi("a"), {**kpi("b"), "page_id": "p2"}]
    payload = DashboardPayload.model_validate(
        {"name": "D", "pages": pages, "page_seconds": 60, "cards": cards}
    )
    assert payload.pages[0].name == "Overview" and payload.cards[1].page_id == "p2"
    # A dashboard without pages is one page: the old format still validates.
    assert DashboardPayload.model_validate({"name": "D", "cards": cards[:1]}).pages == []
    with pytest.raises(ValidationError, match="does not have"):
        DashboardPayload.model_validate({"name": "D", "cards": [{**kpi(), "page_id": "p9"}]})
    with pytest.raises(ValidationError, match="same id"):
        DashboardPayload.model_validate({"name": "D", "pages": pages + pages[:1]})
    with pytest.raises(ValidationError, match="0, 30, 60 or 300"):
        DashboardPayload.model_validate({"name": "D", "page_seconds": 45})
    # 30 cards per page, but more than 30 in the dashboard.
    many = [{**kpi(f"c{i}"), "page_id": "p1" if i < 30 else "p2"} for i in range(40)]
    assert (
        len(DashboardPayload.model_validate({"name": "D", "pages": pages, "cards": many}).cards)
        == 40
    )
    with pytest.raises(ValidationError, match="at most 30"):
        DashboardPayload.model_validate(
            {"name": "D", "pages": pages, "cards": [{**c, "page_id": "p1"} for c in many]}
        )


def test_cards_without_a_place_flow_into_the_grid():
    cards = [
        {**kpi("a"), "width": 8, "height": 2},
        {**kpi("b"), "width": 6, "height": 2},
        {**kpi("c"), "width": 4, "height": 2},
    ]
    payload = DashboardPayload.model_validate({"name": "D", "cards": cards})
    # As the grid before round 7 flowed them: the narrow card fills the hole beside the first.
    assert [(c.x, c.y) for c in payload.cards] == [(0, 0), (0, 2), (8, 0)]
    placed = DashboardPayload.model_validate(
        {"name": "D", "cards": [{**kpi("a"), "x": 6, "y": 3, "width": 6}]}
    )
    assert (placed.cards[0].x, placed.cards[0].y) == (6, 3)


def test_variables_are_checked_where_cards_name_them():
    loop = {"name": "loop", "type": "asset", "asset_kind": "loop"}
    period = {"name": "period", "type": "interval", "options": ["1h", "8h"]}
    tags = {"name": "tag", "type": "custom", "options": ["FIC-101", "LIC-102"], "multi": True}
    cards = [
        kpi("a", asset_id="$loop", role="pv"),
        {**kpi("b", signal_id="fake:${tag}.PV"), "window": "$period"},
        {**kpi("c", asset_id="$loop", role="*"), "repeat": {"variable": "loop"}},
    ]
    payload = DashboardPayload.model_validate(
        {"name": "D", "variables": [loop, period, tags], "cards": cards}
    )
    assert payload.context_kind == "loop" and payload.cards[1].window == "$period"
    with pytest.raises(ValidationError, match="not an asset variable"):
        DashboardPayload.model_validate({"name": "D", "variables": [period], "cards": cards[:1]})
    with pytest.raises(ValidationError, match="not an interval"):
        DashboardPayload.model_validate({"name": "D", "variables": [loop], "cards": cards[1:2]})
    with pytest.raises(ValidationError, match="same name"):
        DashboardPayload.model_validate({"name": "D", "variables": [loop, loop]})
    with pytest.raises(ValidationError, match="kind of asset"):
        DashboardPayload.model_validate({"name": "D", "variables": [{"name": "x"}]})
    with pytest.raises(ValidationError, match="at least one value"):
        DashboardPayload.model_validate(
            {"name": "D", "variables": [{"name": "x", "type": "custom"}]}
        )
    with pytest.raises(ValidationError, match="parent"):
        DashboardPayload.model_validate(
            {"name": "D", "variables": [{**loop, "parent": "unit"}, {**loop, "name": "unit"}]}
        )
