"""Deep links (docs/app-standard.md, sections 2 and 7): an asset opens at /assets/<id>, the old
/plant/<id> still opens the page (the interface moves it to /assets/<id>), and the built files are
served from /static/, never swallowed by the page."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from plantcraft.api import app as app_module

ROOT = Path(__file__).resolve().parents[1]
PAGE = "<!doctype html><title>PlantCraft</title>"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "static").mkdir(parents=True)
    (dist / "index.html").write_text(PAGE)
    (dist / "static" / "index-abc.js").write_text("console.log(1)")
    (dist / "favicon.svg").write_text("<svg/>")
    monkeypatch.setattr(app_module, "FRONTEND_DIST", dist)
    scenario = json.loads((ROOT / "scenarios" / "generic_demo.json").read_text())
    scenario["storage"]["sqlite_path"] = str(tmp_path / "workspace.sqlite3")
    scenario["source"]["path"] = str(ROOT / scenario["source"]["path"])
    (tmp_path / "scenario.json").write_text(json.dumps(scenario))
    monkeypatch.setenv("PLANTCRAFT_SCENARIO", str(tmp_path / "scenario.json"))
    monkeypatch.delenv("PLANTCRAFT_BASIC_AUTH_ENABLED", raising=False)
    with TestClient(app_module.create_app()) as test_client:
        yield test_client


@pytest.mark.parametrize(
    "path", ["/assets", "/assets/FIC-101", "/assets/a%2Fb", "/plant", "/plant/FIC-101", "/data"]
)
def test_pages_and_asset_deep_links_answer_the_interface(client, path):
    response = client.get(path)
    assert response.status_code == 200 and response.text == PAGE


def test_built_files_are_served_from_static(client):
    response = client.get("/static/index-abc.js")
    assert response.status_code == 200 and "console.log" in response.text
    assert client.get("/favicon.svg").text == "<svg/>"


@pytest.mark.parametrize("path", ["/static/missing.js", "/static", "/api/nope", "/api"])
def test_missing_files_and_routes_are_not_answered_with_the_page(client, path):
    response = client.get(path)
    assert response.status_code == 404 and response.text != PAGE


def test_an_asset_reference_links_to_its_deep_link(client):
    refs = client.get("/api/refs", params={"ref": "asset:FIC-101"}).json()
    assert refs["asset:FIC-101"]["href"] == "/assets/FIC-101"


def test_the_build_puts_its_files_under_static():
    config = (ROOT / "frontend" / "vite.config.ts").read_text()
    assert 'assetsDir: "static"' in config
