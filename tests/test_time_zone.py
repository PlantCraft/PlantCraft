"""Times are stored in UTC; the browser learns the plant's zone to show them in local time."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from processcraft.api.app import TIME_ZONE_COOKIE, create_app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    scenario = json.loads((ROOT / "scenarios" / "generic_demo.json").read_text())
    scenario["storage"]["sqlite_path"] = str(tmp_path / "workspace.sqlite3")
    scenario["source"]["path"] = str(ROOT / scenario["source"]["path"])
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario))
    monkeypatch.setenv("PLANTCRAFT_SCENARIO", str(path))
    monkeypatch.setenv("PLANTCRAFT_PREWARM_HISTORY", "false")
    monkeypatch.setenv("PLANTCRAFT_TIMEZONE", "America/Sao_Paulo")
    monkeypatch.delenv("PLANTCRAFT_BASIC_AUTH_ENABLED", raising=False)
    with TestClient(create_app()) as test_client:
        yield test_client


def test_the_plant_time_zone_reaches_the_browser_once(client):
    first = client.get("/api/health")
    assert first.cookies.get(TIME_ZONE_COOKIE) == "America%2FSao_Paulo"
    assert "httponly" not in first.headers["set-cookie"].lower()
    # The browser now holds it: no cookie on every answer.
    assert TIME_ZONE_COOKIE not in client.get("/api/health").headers.get("set-cookie", "")
