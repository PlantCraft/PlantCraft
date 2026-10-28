"""The suite's app standard: ``app.toml`` agrees with the code and image, and every app serves
``/healthz``, ``/api/meta``, ``/api/help`` and ``assets/<id>`` the same way."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from alarmcraft import APP_ID, __version__
from alarmcraft.config import Settings
from alarmcraft.meta import HELP_CATEGORIES, OTHER_CATEGORY, help_page, manifest
from tests.conftest import client_for

ROOT = Path(__file__).resolve().parents[1]
APP = tomllib.loads((ROOT / "app.toml").read_text(encoding="utf-8"))
SUITE_ROW = {"id": "alarmcraft", "prefix": "/alarm/", "port": 8110, "uid": 10009}


def test_manifest_matches_the_code_the_package_and_the_suite_table():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert APP["app"]["id"] == APP_ID == SUITE_ROW["id"]
    assert re.fullmatch(r"[a-z][a-z0-9]{2,30}", APP["app"]["id"])
    assert APP["app"]["version"] == pyproject["project"]["version"] == __version__
    assert APP["runtime"]["prefix"] == SUITE_ROW["prefix"] == Settings().root_path + "/"
    assert APP["runtime"]["port"] == SUITE_ROW["port"]
    assert APP["runtime"]["uid"] == SUITE_ROW["uid"]
    assert APP["permissions"]["plant_write"] is False
    assert APP["permissions"]["outbound"] == []
    sdk = re.search(r"plantcraft-sdk==([0-9.]+)", (ROOT / "Makefile").read_text())
    assert sdk and APP["requires"]["sdk"] == sdk.group(1)


def test_makefile_has_the_suite_target_names():
    targets = set(re.findall(r"^([a-z0-9]+):", (ROOT / "Makefile").read_text(), re.M))
    assert {
        "ci",
        "deps",
        "lint",
        "format",
        "test",
        "frontend",
        "e2e",
        "image",
        "package",
    } <= targets


def test_meta_serves_the_manifest_to_signed_in_people_only(runtime, fake, client):
    answer = client.get("/api/meta").json()
    assert answer["app"]["id"] == "alarmcraft" and "revision" in answer
    assert answer == {**manifest(), "revision": answer["revision"]}
    with client_for(runtime, fake, None) as anonymous:
        assert anonymous.get("/api/meta").status_code == 401


def test_help_index_and_pages(client):
    index = client.get("/api/help").json()
    assert {"alarms", "operating", "configuring", "performance"} <= {page["id"] for page in index}
    page = client.get("/api/help/performance").json()
    assert page["title"] == "Alarm performance" and page["markdown"].startswith("# ")
    assert client.get("/api/help/nope").status_code == 404
    assert help_page("../app") is None and help_page("..%2Fapp") is None


def test_help_pages_come_in_folders_for_the_help_browser(client):
    """Every guide has a category (the suite's HelpBrowser makes folders of it), and every
    guide in docs/help is listed in HELP_CATEGORIES, getting started first."""

    index = client.get("/api/help").json()
    assert index[0] == {"id": "alarms", "title": "Alarms", "category": "Getting started"}
    assert all(page["category"] and page["category"] != OTHER_CATEGORY for page in index)
    assert {page["id"] for page in index} == set(HELP_CATEGORIES)


def test_health_answers_at_the_root_and_under_the_prefix(runtime, fake):
    from fastapi.testclient import TestClient

    from alarmcraft.api.app import create_app

    with TestClient(create_app(runtime)) as bare:
        assert bare.get("/healthz").json()["status"] == "ok"
        assert bare.get("/alarm/healthz").json()["status"] == "ok"
