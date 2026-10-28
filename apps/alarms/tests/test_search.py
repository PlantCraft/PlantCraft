"""Alarms' part of the suite's search (Ctrl+K): alarms by name, signal, asset or area."""

from __future__ import annotations

from tests.conftest import high


def test_search_finds_alarms_by_name_and_asset(client):
    alarm = {"alarm_id": client.post("/api/rules", json=high()).json()["rule_id"]}
    body = client.get("/api/search", params={"q": "fic-1001 high"}).json()
    assert body["format"] == "plantcraft-search/1"
    [hit] = body["items"]
    assert hit["title"] == "FIC-1001 PV high" and hit["type"] == "Alarm"
    assert hit["href"] == f"/alarms/{alarm['alarm_id']}"
    assert "FIC-1001" in hit["detail"]
    assert client.get("/api/search", params={"q": "level low"}).json()["items"] == []
