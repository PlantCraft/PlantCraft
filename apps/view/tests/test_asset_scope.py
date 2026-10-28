"""A person who sees only part of the plant (PlantCraft's token claim ``assets``, its
docs/asset-scope.md): saved dashboards and reports read as that person, never with View's own
token, so a card on another part says it cannot read; and they set up nothing View would later
read with its own token (a public link, a scheduled send)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from plantcraft_sdk.asset_scope import forget

from dashcraft.api.app import create_app
from tests.conftest import dashboard, kpi
from tests.test_reports import report, stat


@pytest.fixture(autouse=True)
def _fresh():
    forget()
    yield
    forget()


def limited(runtime, fake, username="engineer") -> TestClient:
    """``username`` limited to the loop LIC-102 (the fake plant's asset ``lic-102``)."""

    client = TestClient(create_app(runtime), raise_server_exceptions=False)
    client.headers["Authorization"] = f"Bearer {fake.token(username, assets=['lic-102'])}"
    return client


def test_saved_dashboards_read_as_the_person(client, runtime, fake):
    body = dashboard(cards=[kpi("feed"), kpi("level", signal_id="fake:LIC-102.PV")])
    created = client.post("/dash/api/dashboards", json=body).json()
    base = f"/dash/api/dashboards/{created['dashboard_id']}/cards"
    with limited(runtime, fake, "operator") as operator:
        feed = operator.get(f"{base}/feed").json()["rows"][0]
        assert feed["value"] is None and feed["error"]
        assert operator.get(f"{base}/level").json()["rows"][0]["value"] is not None
    # Everyone else still reads with View's own token.
    assert client.get(f"{base}/feed").json()["rows"][0]["value"] is not None


def test_links_and_schedules_are_set_up_by_who_sees_the_whole_plant(client, runtime, fake):
    created = client.post("/dash/api/dashboards", json=dashboard()).json()
    scheduled = client.post("/dash/api/reports", json=report()).json()["report_id"]
    with limited(runtime, fake) as engineer:
        shared = engineer.post(f"/dash/api/dashboards/{created['dashboard_id']}/shares", json={})
        assert shared.status_code == 403
        assert engineer.post("/dash/api/reports", json=report()).status_code == 403
        draft = report(
            schedule={"every": "off"},
            sections=[{"section_id": "s1", "kind": "card", "card": stat()}],
        )
        made = engineer.post("/dash/api/reports", json=draft)
        assert made.status_code == 201, made.text
        rid = made.json()["report_id"]
        assert engineer.post(f"/dash/api/reports/{rid}/shares", json={"days": 7}).status_code == 403
        assert engineer.put(f"/dash/api/reports/{scheduled}", json=report()).status_code == 403


def test_kept_pdfs_are_the_persons_own_or_sent_to_them(client, runtime, fake):
    rid = client.post("/dash/api/reports", json=report(recipients=[])).json()["report_id"]
    theirs = client.post(f"/dash/api/reports/{rid}/pdf").json()["run_id"]
    with limited(runtime, fake, "operator") as operator:
        assert operator.get(f"/dash/api/reports/{rid}/runs").json() == []
        assert operator.get(f"/dash/api/reports/{rid}/runs/{theirs}/pdf").status_code == 404
        own = operator.post(f"/dash/api/reports/{rid}/pdf").json()["run_id"]
        assert [run["run_id"] for run in operator.get(f"/dash/api/reports/{rid}/runs").json()] == [
            own
        ]
    # Sent to them by the report's editors: theirs to open.
    sent_to = client.post("/dash/api/reports", json=report()).json()["report_id"]
    sent = client.post(f"/dash/api/reports/{sent_to}/send").json()["run_id"]
    with limited(runtime, fake, "operator") as operator:
        pdf = operator.get(f"/dash/api/reports/{sent_to}/runs/{sent}/pdf")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
