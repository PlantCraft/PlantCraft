"""Earlier periods drawn over a trend's own (V11): yesterday over today, a week over this week."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from dashcraft.dashboards.trends import TrendView
from dashcraft.query.cards import Reader
from dashcraft.query.trends import compare_offset, read_view

NOW = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)


class Plant:
    """Each signal holds one value per hour equal to the day of the month (31 today, 30 yesterday)."""

    def __init__(self):
        self.asked = []

    def signal(self, signal_id):
        kind = "text" if signal_id.endswith(".MODE") else "number"
        return {"id": signal_id, "name": signal_id, "unit": "m3/h", "kind": kind}

    def series_many(self, signals, start, end, step, **_):
        self.asked.append((start, end))
        if any(s.endswith(".MISSING") for s in signals):
            return {"series": [], "errors": [{"signal": s, "status": 404} for s in signals]}
        return {
            "series": [
                {
                    "signal": s,
                    "t": [start.isoformat()],
                    "v": ["AUTO" if s.endswith(".MODE") else float(start.day)],
                }
                for s in signals
            ]
        }


def _view(compare, *signals, window="24h"):
    lines = [{"signal_id": signal} for signal in signals or ("plant:FIC-101.PV",)]
    return TrendView.model_validate(
        {"plots": [{"lines": lines}], "period": {"window": window}, "compare": compare}
    )


def test_each_earlier_period_is_moved_onto_the_trends_time_axis():
    plant = Plant()
    data = read_view(Reader(client=plant, clock=lambda: NOW), _view(["1d", "7d"]))
    own, day, week = data["plots"][0]["lines"]
    assert own["v"] == [30.0] and "compare" not in own
    assert day["compare"] == "1d" and day["source"] == 0 and day["v"] == [29.0]
    assert week["compare"] == "7d" and week["v"] == [23.0]
    # Read 1 day and 7 days back, drawn where today's period is.
    assert plant.asked[1] == (NOW - timedelta(days=2), NOW - timedelta(days=1))
    assert day["t"] == own["t"] == week["t"]
    assert day["label"].endswith("1 day earlier") and week["label"].endswith("1 week earlier")


def test_the_previous_period_is_the_trends_own_length_back():
    plant = Plant()
    read_view(Reader(client=plant, clock=lambda: NOW), _view(["previous"], window="8h"))
    assert plant.asked[1] == (NOW - timedelta(hours=16), NOW - timedelta(hours=8))
    assert compare_offset("previous", timedelta(hours=8)) == timedelta(hours=8)
    assert compare_offset("28d", timedelta(hours=8)) == timedelta(days=28)


def test_states_and_failed_lines_are_not_compared():
    plant = Plant()
    data = read_view(
        Reader(client=plant, clock=lambda: NOW),
        _view(["1d"], "plant:FIC-101.PV", "plant:FIC-101.MODE"),
    )
    lines = data["plots"][0]["lines"]
    assert [line.get("compare") for line in lines] == [None, None, "1d"]
    assert lines[2]["source"] == 0


def test_the_choice_is_ordered_unique_and_at_most_three():
    assert _view(["7d", "1d", "7d"]).compare == ["1d", "7d"]
    with pytest.raises(ValidationError):
        _view(["previous", "1d", "7d", "28d"])
    with pytest.raises(ValidationError):
        _view(["2d"])
    assert _view([]).compare == []
