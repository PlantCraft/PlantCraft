"""End-to-end checks of the HTTP API on the self-contained CSV scenario."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from processcraft.api.app import create_app

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
    monkeypatch.delenv("PLANTCRAFT_BASIC_AUTH_ENABLED", raising=False)
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.mark.parametrize(
    "url",
    [
        "/healthz",
        "/api/session",
        "/api/home",
        "/api/users",
        "/api/assets",
        "/api/help",
        "/api/help/guide",
        "/api/map/format",
        "/api/data/sources",
    ],
)
def test_read_endpoints_answer(client, url):
    assert client.get(url).status_code == 200


def test_unknown_resources_return_404(client):
    assert client.get("/api/assets/NOPE").status_code == 404
    assert client.get("/api/help/nope").status_code == 404
    assert client.get("/api/data/sources/nope/status").status_code == 404
    # The routes of the apps live in the apps: here they are simply not found.
    for gone in ("/api/loops", "/api/jobs", "/api/methods", "/api/dashboards"):
        assert client.get(gone).status_code == 404, gone


def test_settings_page_is_gone(client):
    # Legacy (owner, 2026-10-20): each app has its own settings now.
    assert client.get("/api/settings").status_code == 404


def test_home_reports_the_version(client):
    assert client.get("/api/home").json()["version"]


def test_home_lists_the_installed_apps(client, monkeypatch):
    monkeypatch.setenv("PLANTCRAFT_APPS", "linkcraft=/link/@0.1.0")
    home = client.get("/api/home").json()
    assert home["apps"] == [
        {
            "id": "linkcraft",
            "name": "PlantCraft Analytics",
            "url": "/link/",
            "version": "0.1.0",
            "access": "editor",
            "asset_types": None,  # its manifest is unknown here: the asset page links it
        }
    ]
    assert home["counts"]["assets"]["loop"] == 1
    assert home["counts"]["signals"] >= 4


def test_scenario_loops_become_loop_assets_with_signals_by_role(client):
    loop = client.get("/api/assets/FIC-101").json()
    assert loop["asset"]["kind"] == "loop"
    roles = {item["role"]: item["signal_id"] for item in loop["signals"]}
    assert roles["pv"] == "pv" and {"sp", "op", "mode"} <= set(roles)
    assert [item["kind"] for item in loop["path"]][:3] == ["site", "unit", "area"]


def test_data_endpoints_browse_and_read_history(client):
    source = client.get("/api/data/sources").json()[0]
    signals = client.get(
        f"/api/data/sources/{source['source_id']}/signals", params={"q": "pv"}
    ).json()["items"]
    assert signals
    tag = signals[0]["tag"]
    history = client.get("/api/data/history", params={"tag": tag, "hours": 6}).json()
    assert len(history["series"][tag]) > 10
    assert client.get("/api/data/history").status_code == 422


def test_the_sign_in_page_names_the_installation(client):
    """Before signing in, the session names the plant and the version (the sign-in page shows them)."""
    installation = client.get("/api/session").json()["installation"]
    assert installation["name"] and installation["version"]
