"""View's part of the suite's search (Ctrl+K): dashboards and saved trends."""

from __future__ import annotations

from tests.conftest import client_for, dashboard
from tests.test_diagrams import unit
from tests.test_trends import VIEW


def test_search_finds_dashboards_and_trends(runtime, fake):
    with client_for(runtime, fake) as client:
        made = client.post("/dash/api/dashboards", json=dashboard(name="Furnace overview")).json()
        trend = client.post("/dash/api/trends", json={"name": "Furnace check", **VIEW}).json()
        body = client.get("/dash/api/search", params={"q": "furnace"}).json()
        assert body["format"] == "plantcraft-search/1"
        found = {(item["type"], item["href"]) for item in body["items"]}
        assert ("Dashboard", f"/d/{made['dashboard_id']}") in found
        assert ("Trend", f"/trends/{trend['trend_id']}") in found
        assert client.get("/dash/api/search", params={"q": "nothing here"}).json()["items"] == []


def test_search_finds_the_diagrams_a_person_sees(runtime, fake):
    with client_for(runtime, fake, "admin") as admin:
        folder = admin.post(
            "/dash/api/folders", json={"name": "Closed", "viewers": ["user:engineer"]}
        ).json()
        open_one = admin.post(
            "/dash/api/diagrams", json=unit(name="Furnace graphic", tags=["heater"])
        ).json()
        admin.post(
            "/dash/api/diagrams", json=unit(name="Furnace hidden", folder_id=folder["folder_id"])
        )
        body = admin.get("/dash/api/search", params={"q": "heater"}).json()
        assert [(item["type"], item["href"]) for item in body["items"]] == [
            ("Process display", f"/diagrams/{open_one['diagram_id']}")
        ]
    with client_for(runtime, fake, "operator") as operator:
        found = operator.get("/dash/api/search", params={"q": "furnace"}).json()["items"]
        assert [item["title"] for item in found] == ["Furnace graphic"]
