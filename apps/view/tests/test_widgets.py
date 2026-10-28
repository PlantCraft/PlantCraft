"""View's widgets (contract v1): offered on PlantCraft's Overview and drawn on View's own."""

from __future__ import annotations

from plantcraft_sdk import apptest

from tests.conftest import dashboard


def test_the_dashboards_widget_links_each_dashboard(client):
    listed = client.get("/dash/api/widgets").json()
    assert [item["id"] for item in listed["widgets"] if item["default"]] == ["dashboards"]
    assert apptest.widget_problems(client, "/dash") == []
    assert client.get("/dash/api/widgets/dashboards").json()["items"] == []
    made = client.post("/dash/api/dashboards", json=dashboard()).json()
    data = client.get("/dash/api/widgets/dashboards").json()
    assert data["kind"] == "list" and data["href"] == "/dash/dashboards"
    assert data["items"][0]["href"] == f"/dash/d/{made['dashboard_id']}"
    assert data["items"][0]["detail"] == "Updated just now" and data["items"][0]["value"] is None
    one = client.get("/dash/api/widgets/dashboard", params={"item": made["dashboard_id"]}).json()
    assert one["kind"] == "facts" and one["href"] == data["items"][0]["href"]
    assert client.get("/dash/api/widgets/nope").status_code == 404


def test_the_trends_and_public_links_widgets(client):
    assert client.get("/dash/api/widgets/trends").json()["items"] == []
    line = {"signal_id": "fake:FIC-101.PV"}
    saved = client.post("/dash/api/trends", json={"name": "Feed", "plots": [{"lines": [line]}]})
    data = client.get("/dash/api/widgets/trends").json()
    assert data["items"][0]["label"] == "Feed"
    assert data["items"][0]["href"] == f"/dash/trends/{saved.json()['trend_id']}"
    assert data["items"][0]["detail"] == "Updated just now" and data["items"][0]["value"] is None
    assert client.get("/dash/api/widgets/trend").status_code == 404
    assert apptest.widget_problems(client, "/dash") == []
    shared = client.get("/dash/api/widgets/public-links").json()
    assert shared["kind"] == "list" and shared["items"] == []
    made = client.post("/dash/api/dashboards", json=dashboard()).json()
    client.post(f"/dash/api/dashboards/{made['dashboard_id']}/shares", json={"label": "Wall"})
    rows = client.get("/dash/api/widgets/public-links").json()["items"]
    assert [row["label"] for row in rows] == [f"{made['name']} · Wall"]
    assert rows[0]["detail"] == "Dashboard · Never opened"
    assert rows[0]["href"] == f"/dash/d/{made['dashboard_id']}"
    assert apptest.widget_problems(client, "/dash") == []


def _report(name: str, schedule: dict) -> dict:
    return {"name": name, "period": "24h", "schedule": schedule, "sections": []}


def test_each_report_says_its_next_send_and_how_the_last_went(client, runtime, fake):
    # 12:00 UTC is 09:00 on a Thursday in São Paulo, the plant's clock.
    fake.time_zone = "America/Sao_Paulo"
    assert client.get("/dash/api/widgets/reports").json()["empty"] == "No report yet."
    schedules = {
        "A daily": {"every": "day", "at": "06:00"},
        "B weekly": {"every": "week", "weekday": "thu", "at": "10:00"},
        "C monthly": {"every": "month", "day": 1, "at": "06:00"},
        "D by hand": {"every": "off"},
    }
    made = {
        name: client.post("/dash/api/reports", json=_report(name, schedule)).json()
        for name, schedule in schedules.items()
    }
    for name, status in (("A daily", "done"), ("B weekly", "failed")):
        run = runtime.reports.start_run(
            made[name], trigger="schedule", by=None, period_start=fake.now, period_end=fake.now
        )
        runtime.reports.finish_run(run["run_id"], status=status)
    data = client.get("/dash/api/widgets/reports").json()
    assert data["kind"] == "list" and data["href"] == "/dash/reports"
    rows = {row["label"]: row for row in data["items"]}
    assert rows["A daily"]["detail"] == "Next: Fri 06:00" and rows["A daily"]["state"] == "ok"
    assert rows["B weekly"]["detail"] == "Next: today 10:00"
    assert rows["B weekly"]["state"] == "alarm"
    assert rows["C monthly"]["detail"] == "Next: 01 Nov 06:00"
    assert rows["C monthly"]["state"] is None
    assert rows["D by hand"]["detail"] == "Not scheduled"
    assert rows["A daily"]["href"] == f"/dash/reports/{made['A daily']['report_id']}"
    assert apptest.widget_problems(client, "/dash") == []


def test_the_diagrams_widget_lists_the_diagrams_a_person_sees(client, runtime, fake):
    from tests.conftest import client_for
    from tests.test_diagrams import unit

    empty = client.get("/dash/api/widgets/diagrams").json()
    assert empty["kind"] == "list" and empty["items"] == [] and empty["href"] == "/dash/diagrams"
    made = client.post("/dash/api/diagrams", json=unit()).json()
    folder = client.post(
        "/dash/api/folders", json={"name": "Closed", "viewers": ["user:engineer"]}
    ).json()
    client.post("/dash/api/diagrams", json=unit(name="Hidden", folder_id=folder["folder_id"]))
    assert apptest.widget_problems(client, "/dash") == []
    data = client.get("/dash/api/widgets/diagrams").json()
    assert [item["label"] for item in data["items"]] == ["Hidden", "Feed section"]
    with client_for(runtime, fake, "operator") as operator:
        seen = operator.get("/dash/api/widgets/diagrams").json()["items"]
    assert [item["href"] for item in seen] == [f"/dash/diagrams/{made['diagram_id']}"]
    assert seen[0]["detail"] == "Updated just now"


def test_a_diagram_reference_names_it_for_whoever_may_see_it(client, runtime, fake):
    from tests.conftest import client_for
    from tests.test_diagrams import unit

    made = client.post("/dash/api/diagrams", json=unit()).json()
    ref = client.get(f"/dash/api/refs/diagram/{made['diagram_id']}").json()
    assert ref == {
        "title": "Feed section",
        "status": "6 elements",
        "url": f"/dash/diagrams/{made['diagram_id']}",
    }
    assert client.get("/dash/api/refs/diagram/nowhere").status_code == 404
    folder = client.post(
        "/dash/api/folders", json={"name": "Closed", "viewers": ["user:engineer"]}
    ).json()
    hidden = client.post("/dash/api/diagrams", json=unit(folder_id=folder["folder_id"])).json()
    with client_for(runtime, fake, "operator") as operator:
        assert operator.get(f"/dash/api/refs/diagram/{hidden['diagram_id']}").status_code == 404
