"""A laboratory signal's results are drawn at their sampling times, with their other times."""

from __future__ import annotations

from datetime import datetime, timezone

from dashcraft.dashboards.trends import TrendView
from dashcraft.query.cards import Reader
from dashcraft.query.trends import read_view

NOW = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
SAMPLES = [
    {
        "sampled_at": "2026-10-31T06:00:00.000Z",
        "value": 412.0,
        "status": "approved",
        "received_at": "2026-10-31T08:00:00.000Z",
        "approved_at": "2026-10-31T09:30:00.000Z",
        "written_by": "lims",
    },
    {"sampled_at": "2026-10-31T10:00:00.000Z", "value": 415.0, "status": "entered"},
]


class Plant:
    def __init__(self, samples):
        self.samples = samples
        self.asked = []

    def signal(self, signal_id):
        return {"id": signal_id, "name": signal_id, "unit": "cP", "kind": "number"}

    def series_many(self, signals, start, end, step, **_):
        # The means of the interval: a lab line must not be drawn from them.
        return {"series": [{"signal": s, "t": [start.isoformat()], "v": [1.0]} for s in signals]}

    def lab_samples(self, signal_id, start, end):
        self.asked.append((signal_id, start, end))
        return self.samples


def _view(signal):
    return TrendView.model_validate(
        {"plots": [{"lines": [{"signal_id": signal}]}], "period": {"window": "24h"}}
    )


def test_results_sit_at_their_sampling_times_with_status_and_times():
    plant = Plant(SAMPLES)
    data = read_view(Reader(client=plant, clock=lambda: NOW), _view("laboratory:VISC-101"))
    line = data["plots"][0]["lines"][0]
    assert line["t"] == [item["sampled_at"] for item in SAMPLES] and line["v"] == [412.0, 415.0]
    assert line["agg"] == "recorded"
    assert line["samples"][0]["approved_at"] == "2026-10-31T09:30:00.000Z"
    assert line["samples"][1]["received_at"] is None and "written_by" not in line["samples"][0]
    assert plant.asked[0][0] == "laboratory:VISC-101"


def test_other_signals_ask_for_no_samples():
    plant = Plant(SAMPLES)
    data = read_view(Reader(client=plant, clock=lambda: NOW), _view("plant:FIC-101.PV"))
    line = data["plots"][0]["lines"][0]
    assert "samples" not in line and line["v"] == [1.0] and not plant.asked
