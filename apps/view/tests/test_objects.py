"""View's dashboards and reports as objects (``[[contributes.objects]]``): what the assistant's
list_app_objects and notebooks read, with a closed folder hiding its own."""

from __future__ import annotations

from pathlib import Path

from plantcraft_sdk import apptest

from tests.conftest import client_for, dashboard
from tests.test_diagrams import unit
from tests.test_reports import report

ROOT = Path(__file__).resolve().parents[1]


def test_view_serves_its_dashboards_and_reports(client):
    client.post("/dash/api/dashboards", json=dashboard(description="The feed flow."))
    client.post("/dash/api/reports", json=report())
    assert apptest.objects_problems(client, "/dash", ROOT) == []
    listed = client.get("/dash/api/objects/dashboard").json()["items"]
    assert listed[0]["name"] == "Feed" and listed[0]["signals"] == ["fake:FIC-101.PV"]
    one = client.get(f"/dash/api/objects/dashboard/{listed[0]['id']}").json()
    assert one["cards"] and one["description"] == "The feed flow."
    reports = client.get("/dash/api/objects/report").json()["items"]
    assert reports[0]["cadence"] and reports[0]["signals"] == ["fake:FIC-101.PV", "fake:FIC-101.SP"]
    read = client.get(f"/dash/api/objects/report/{reports[0]['id']}").json()
    assert read["name"] == "Daily unit report" and len(read["sections"]) == 5


def test_a_closed_folder_hides_its_dashboards_and_reports(runtime, fake):
    with client_for(runtime, fake, "admin") as admin:
        folder = admin.post(
            "/dash/api/folders", json={"name": "Shift leads", "viewers": ["user:engineer"]}
        ).json()
        kept = admin.post("/dash/api/dashboards", json=dashboard(folder_id=folder["folder_id"]))
        admin.post("/dash/api/reports", json=report(folder_id=folder["folder_id"]))
    with client_for(runtime, fake, "operator") as operator:
        assert operator.get("/dash/api/objects/dashboard").json()["items"] == []
        assert operator.get("/dash/api/objects/report").json()["items"] == []
        hidden = kept.json()["dashboard_id"]
        assert operator.get(f"/dash/api/objects/dashboard/{hidden}").status_code == 404


def test_view_serves_its_diagrams_with_their_bindings(client, runtime, fake):
    made = client.post("/dash/api/diagrams", json=unit(description="The feed tank.")).json()
    assert apptest.objects_problems(client, "/dash", ROOT) == []
    [listed] = client.get("/dash/api/objects/diagram").json()["items"]
    assert listed["name"] == "Feed section" and listed["elements"] == 6
    assert listed["signals"] == ["fake:P-201.FLOW"]
    assert listed["assets"] == ["lic-102", "p-201", "fic-101"]
    assert listed["url"] == f"/dash/diagrams/{made['diagram_id']}"
    one = client.get(f"/dash/api/objects/diagram/{listed['id']}").json()
    assert one["description"] == "The feed tank."
    assert ("tk1", "level") in {(row["element"], row["slot"]) for row in one["bindings"]}
    assert "points" not in next(e for e in one["elements"] if e["id"] == "l1")
    with client_for(runtime, fake, "admin") as admin:
        folder = admin.post(
            "/dash/api/folders", json={"name": "Closed", "viewers": ["user:engineer"]}
        ).json()
        hidden = admin.post("/dash/api/diagrams", json=unit(folder_id=folder["folder_id"])).json()
    with client_for(runtime, fake, "operator") as operator:
        seen = operator.get("/dash/api/objects/diagram").json()["items"]
        assert [item["id"] for item in seen] == [made["diagram_id"]]
        assert operator.get(f"/dash/api/objects/diagram/{hidden['diagram_id']}").status_code == 404
