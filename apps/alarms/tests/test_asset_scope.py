"""A person who sees only part of the plant (PlantCraft's token claim ``assets``, its
docs/asset-scope.md) sees in Alarms only the alarms on that part: the lists, the summary, the
journal, the search, the alarm pages and the actions on them. Everyone else sees every alarm."""

from __future__ import annotations

import pytest
from plantcraft_sdk.asset_scope import forget

from tests.conftest import client_for, high, make_rule


@pytest.fixture(autouse=True)
def _fresh():
    forget()
    yield
    forget()


def limited(runtime, fake, username="engineer"):
    """``username`` limited to the loop FIC-1001."""

    client = client_for(runtime, fake, None)
    client.headers["Authorization"] = f"Bearer {fake.token(username, assets=['FIC-1001'])}"
    return client


def test_alarms_keep_to_the_part(runtime, fake, client):
    rule = make_rule(client, high(name="PV high", assets=[], under=["U-SIM"], limit=1.0))
    every = {row["alarm_id"] for row in rule["alarm_rows"]}
    assert "pv-high--fic-1001" in every and len(every) > 2
    client.post("/api/run")
    other = sorted(every - {"pv-high--fic-1001"})[0]

    with limited(runtime, fake) as engineer:
        listed = engineer.get("/api/alarms")
        assert listed.status_code == 200, listed.text
        assert {row["alarm_id"] for row in listed.json()} == {"pv-high--fic-1001"}
        assert engineer.get(f"/api/alarms/{other}").status_code == 404
        assert engineer.get(f"/api/alarms/{other}/history").status_code == 404
        assert engineer.post(f"/api/alarms/{other}/ack").status_code == 404
        assert engineer.get("/api/alarms/pv-high--fic-1001").status_code == 200

        summary = engineer.get("/api/summary").json()
        assert {row["alarm_id"] for row in summary["alarms"]} <= {"pv-high--fic-1001"}
        assert summary["counts"]["total"] == 1

        journal = engineer.get("/api/journal").json()
        assert journal and {row["alarm_id"] for row in journal} == {"pv-high--fic-1001"}

        rules = engineer.get("/api/rules").json()
        assert rules[0]["alarms"] == 1

        found = engineer.get("/api/search", params={"q": "PV high"}).json()["items"]
        assert [item["href"] for item in found] == ["/alarms/pv-high--fic-1001"]

        done = engineer.post("/api/ack", json={}).json()["acknowledged"]
        assert done <= 1

    # Everyone else sees every alarm, and the others are still to acknowledge.
    assert {row["alarm_id"] for row in client.get("/api/alarms").json()} == every
    assert client.get(f"/api/alarms/{other}").json()["status"] != "acked"
