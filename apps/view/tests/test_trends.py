"""Trends: signals over a relative or fixed period, overlaid or in subplots, saved to reopen."""

from __future__ import annotations

from fastapi.testclient import TestClient

from dashcraft.api.app import create_app
from tests.conftest import client_for

VIEW = {
    "plots": [
        {
            "title": "Flow",
            "lines": [{"signal_id": "fake:FIC-101.PV"}, {"signal_id": "fake:FIC-101.SP"}],
        },
        {"lines": [{"signal_id": "fake:FIC-101.OP", "label": "Valve"}]},
    ],
    "period": {"mode": "relative", "window": "2h"},
}


def test_a_trend_reads_every_plot_with_the_step_asked(client):
    data = client.post("/dash/api/trends/data", json=VIEW).json()
    assert [len(plot["lines"]) for plot in data["plots"]] == [2, 1]
    assert data["plots"][0]["title"] == "Flow" and data["plots"][1]["lines"][0]["label"] == "Valve"
    line = data["plots"][0]["lines"][0]
    assert line["unit"] and len(line["v"]) == 480 and data["range"]["step"] == 15
    hourly = client.post("/dash/api/trends/data", json={**VIEW, "step_seconds": 600}).json()
    assert hourly["range"]["step"] == 600 and len(hourly["plots"][0]["lines"][0]["v"]) == 12


def test_a_fixed_period_is_checked(client):
    fixed = {"mode": "fixed", "start": "2026-10-01T10:00:00Z", "end": "2026-10-01T11:00:00Z"}
    data = client.post("/dash/api/trends/data", json={**VIEW, "period": fixed}).json()
    assert data["range"]["start"].startswith("2026-10-01T10:00")
    backwards = {**fixed, "start": fixed["end"], "end": fixed["start"]}
    assert (
        client.post("/dash/api/trends/data", json={**VIEW, "period": backwards}).status_code == 422
    )
    assert client.post("/dash/api/trends/data", json={"plots": []}).status_code == 422


def test_an_unknown_signal_is_named_not_fatal_and_a_text_one_reads_its_states(client):
    view = {"plots": [{"lines": [{"signal_id": "fake:NOPE"}, {"signal_id": "fake:P-201.STATE"}]}]}
    unknown, state = client.post("/dash/api/trends/data", json=view).json()["plots"][0]["lines"]
    assert unknown["error"]
    assert state["error"] is None and state["kind"] == "text" and state["agg"] == "last"
    assert state["v"] and all(isinstance(value, str) for value in state["v"] if value is not None)


def test_anyone_saves_a_trend_and_only_its_author_or_an_editor_changes_it(runtime, fake):
    with client_for(runtime, fake, "operator") as operator:
        created = operator.post("/dash/api/trends", json={"name": "Morning check", **VIEW})
        assert created.status_code == 201, created.text
        trend_id = created.json()["trend_id"]
        assert created.json()["plots"][0]["title"] == "Flow"
        renamed = operator.put(f"/dash/api/trends/{trend_id}", json={"name": "Shift", **VIEW})
        assert renamed.status_code == 200 and renamed.json()["name"] == "Shift"
    with client_for(runtime, fake, "wallboard") as other:
        assert [item["trend_id"] for item in other.get("/dash/api/trends").json()] == [trend_id]
        assert other.delete(f"/dash/api/trends/{trend_id}").status_code == 403
    with client_for(runtime, fake, "engineer") as editor:
        assert editor.delete(f"/dash/api/trends/{trend_id}").status_code == 204
        assert editor.get(f"/dash/api/trends/{trend_id}").status_code == 404
    assert "dashcraft.trend.create" in [entry["action"] for entry in fake.audit_log]


def test_a_public_demo_visit_searches_and_draws_but_saves_no_trend(runtime, fake):
    # Every visitor is the one demo account: a saved trend would be every visitor's to change.
    with client_for(runtime, fake, "operator") as operator:
        trend_id = operator.post("/dash/api/trends", json={"name": "Kept", **VIEW}).json()[
            "trend_id"
        ]
    visit = {"visit": "v1", "ends": 4102444800, "queries": 4, "queries_total": 8}
    with TestClient(create_app(runtime), raise_server_exceptions=False) as visitor:
        visitor.headers["Authorization"] = f"Bearer {fake.token('operator', demo=visit)}"
        assert visitor.get("/dash/api/signals", params={"q": "FIC-101"}).json()
        assert visitor.post("/dash/api/trends/data", json=VIEW).status_code == 200
        refused = visitor.post("/dash/api/trends", json={"name": "Mine", **VIEW})
        assert refused.status_code == 403 and "nothing is saved" in refused.json()["detail"]
        assert (
            visitor.put(f"/dash/api/trends/{trend_id}", json={"name": "X", **VIEW}).status_code
            == 403
        )
        assert visitor.delete(f"/dash/api/trends/{trend_id}").status_code == 403


def test_each_line_chooses_how_its_interval_is_summarised_and_drawn(client):
    style = {"mode": "markers", "shape": "hv", "color": "#AA3300", "axis": "right"}
    view = {
        "plots": [
            {
                "lines": [
                    {"signal_id": "fake:FIC-101.PV"},
                    {"signal_id": "fake:FIC-101.PV", "label": "Max", "agg": "max"},
                    {"signal_id": "fake:FIC-101.PV", "label": "Min", "agg": "min"},
                    {
                        "signal_id": "fake:FIC-101.PV",
                        "label": "Last",
                        "agg": "last",
                        "style": style,
                    },
                ]
            }
        ],
        "period": {"mode": "relative", "window": "2h"},
        "step_seconds": 600,
    }
    mean, high, low, last = client.post("/dash/api/trends/data", json=view).json()["plots"][0][
        "lines"
    ]
    assert [line["agg"] for line in (mean, high, low, last)] == ["mean", "max", "min", "last"]
    assert len(high["v"]) == len(low["v"]) == 12
    assert all(lo <= m <= hi for lo, m, hi in zip(low["v"], mean["v"], high["v"], strict=True))
    assert any(hi > lo for lo, hi in zip(low["v"], high["v"], strict=True))
    assert last["style"]["mode"] == "markers" and last["style"]["axis"] == "right"
    assert mean["style"] == {
        "mode": "lines", "shape": "linear", "color": "", "width": 2.0, "dash": "solid",
        "marker_size": 6, "axis": "left",
    }  # fmt: skip
    recorded = client.post("/dash/api/trends/data", json={**view, "step_seconds": 0}).json()
    assert {line["agg"] for line in recorded["plots"][0]["lines"]} == {"recorded"}


def test_line_options_are_checked_and_saved(client):
    bad = {"plots": [{"lines": [{"signal_id": "fake:FIC-101.PV", "agg": "median"}]}]}
    assert client.post("/dash/api/trends/data", json=bad).status_code == 422
    colour = {"plots": [{"lines": [{"signal_id": "fake:FIC-101.PV", "style": {"color": "red"}}]}]}
    assert client.post("/dash/api/trends/data", json=colour).status_code == 422
    line = {"signal_id": "fake:FIC-101.PV", "agg": "last", "style": {"mode": "lines+markers"}}
    saved = client.post("/dash/api/trends", json={"name": "Points", "plots": [{"lines": [line]}]})
    stored = saved.json()["plots"][0]["lines"][0]
    assert stored["agg"] == "last" and stored["style"]["mode"] == "lines+markers"


def test_summarise_keeps_one_value_per_interval():
    from datetime import datetime, timezone

    from dashcraft.query.trends import summarise

    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    times = ["2026-10-01T00:00:00Z", "2026-10-01T00:00:30Z", "2026-10-01T00:01:10+00:00"]
    assert summarise(times, [1.0, 3.0, 2.0], start, 60, "max") == (
        ["2026-10-01T00:00:00+00:00", "2026-10-01T00:01:00+00:00"],
        [3.0, 2.0],
    )
    assert summarise(times, [1.0, None, 2.0], start, 60, "last")[1] == [1.0, 2.0]


def test_each_line_reads_at_its_own_interval(client):
    """The owner's example: PV blue and solid every minute, SP light blue and dashed hourly."""

    view = {
        "plots": [
            {
                "lines": [
                    {
                        "signal_id": "fake:FIC-101.PV",
                        "step_seconds": 60,
                        "style": {"color": "#1F5FD6", "dash": "solid"},
                    },
                    {
                        "signal_id": "fake:FIC-101.SP",
                        "step_seconds": 3600,
                        "style": {"color": "#8DB4F2", "dash": "dash"},
                    },
                    {"signal_id": "fake:FIC-101.OP", "agg": "max", "step_seconds": 600},
                    {"signal_id": "fake:FIC-101.PV", "label": "Trend's"},
                ]
            }
        ],
        "period": {"mode": "relative", "window": "2h"},
        "step_seconds": 0,
    }
    data = client.post("/dash/api/trends/data", json=view).json()
    pv, sp, op, default = data["plots"][0]["lines"]
    assert (pv["step"], len(pv["v"])) == (60, 120)
    assert (sp["step"], len(sp["v"])) == (3600, 2)
    assert (op["step"], op["agg"], len(op["v"])) == (600, "max", 12)
    assert default["step"] == 0 and default["agg"] == "recorded"
    assert pv["style"]["color"] == "#1F5FD6" and sp["style"]["dash"] == "dash"
    bad = {**view, "plots": [{"lines": [{"signal_id": "fake:FIC-101.PV", "step_seconds": -1}]}]}
    assert client.post("/dash/api/trends/data", json=bad).status_code == 422


def test_min_and_max_lines_come_from_the_historians_extremes_not_raw_samples(client, monkeypatch):
    from plantcraft_sdk.client import PlantCraftClient

    asked: list[tuple[float | None, bool]] = []
    original = PlantCraftClient.series_many

    def counted(self, signal_ids, start=None, end=None, step=None, **options):
        asked.append((step, bool(options.get("extremes"))))
        return original(self, signal_ids, start, end, step, **options)

    monkeypatch.setattr(PlantCraftClient, "series_many", counted)
    lines = [
        {"signal_id": "fake:FIC-101.PV"},
        {"signal_id": "fake:FIC-101.PV", "agg": "max"},
        {"signal_id": "fake:FIC-101.PV", "agg": "min"},
    ]
    view = {"plots": [{"lines": lines}], "period": {"mode": "relative", "window": "2h"}}
    mean, high, low = client.post(
        "/dash/api/trends/data", json={**view, "step_seconds": 600}
    ).json()["plots"][0]["lines"]
    assert asked == [(600, True)]  # one grid read, no raw samples
    assert all(lo <= m <= hi for lo, m, hi in zip(low["v"], mean["v"], high["v"], strict=True))
    assert any(hi > lo for lo, hi in zip(low["v"], high["v"], strict=True))
    # A first or last line still summarises the raw samples here.
    asked.clear()
    last = {**view, "plots": [{"lines": [{"signal_id": "fake:FIC-101.PV", "agg": "last"}]}]}
    client.post("/dash/api/trends/data", json={**last, "step_seconds": 600})
    assert asked == [(600, False), (None, False)]
