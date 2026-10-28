"""The suite's app standard: ``app.toml`` agrees with the code and image, and every app serves
``/healthz``, ``/api/meta``, ``/api/help`` and ``assets/<id>`` the same way."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from plantcraft_sdk.app_manifest import SUITE

from starter import APP_ID, __version__
from starter.config import Settings
from starter.meta import HELP_CATEGORIES, OTHER_CATEGORY, help_page, manifest
from tests.conftest import client_for

ROOT = Path(__file__).resolve().parents[1]
APP = tomllib.loads((ROOT / "app.toml").read_text(encoding="utf-8"))


def test_manifest_matches_the_code_and_the_package():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert APP["app"]["id"] == APP_ID == pyproject["project"]["name"]
    assert re.fullmatch(r"[a-z][a-z0-9]{2,30}", APP["app"]["id"])
    assert APP["app"]["version"] == pyproject["project"]["version"] == __version__
    assert APP["runtime"]["prefix"] == Settings().root_path + "/"
    assert APP["permissions"]["plant_write"] is False
    assert APP["permissions"]["outbound"] == []
    sdk = re.search(r"plantcraft-sdk==([0-9.]+)", (ROOT / "Makefile").read_text())
    assert sdk and APP["requires"]["sdk"] == sdk.group(1)


def test_an_app_of_its_own_takes_nothing_of_the_suite_table():
    # The suite's own apps have a row (PlantCraft docs/app-standard.md, section 7); any other
    # app keeps clear of every row's id, prefix, port and container user.
    assert APP_ID not in SUITE
    for row in SUITE.values():
        assert APP["runtime"]["prefix"] != row.prefix
        assert APP["runtime"]["port"] != row.port
        assert APP["runtime"]["uid"] != row.uid


def test_makefile_has_the_suite_target_names():
    targets = set(re.findall(r"^([a-z0-9-]+):", (ROOT / "Makefile").read_text(), re.M))
    assert {
        "ci",
        "deps",
        "lint",
        "format",
        "test",
        "test-fast",
        "frontend",
        "e2e",
        "image",
    } <= targets
    assert {"package", "rename", "dev"} <= targets


def test_meta_serves_the_manifest_to_signed_in_people_only(runtime, fake, client):
    answer = client.get("/api/meta").json()
    assert answer["app"]["id"] == APP_ID and "revision" in answer
    assert answer == {**manifest(), "revision": answer["revision"]}
    with client_for(runtime, fake, None) as anonymous:
        assert anonymous.get("/api/meta").status_code == 401


def test_help_pages_come_in_folders_for_the_help_browser(client):
    index = client.get("/api/help").json()
    assert index[0]["id"] == APP_ID and index[0]["category"] == "Getting started"
    assert all(page["category"] and page["category"] != OTHER_CATEGORY for page in index)
    assert {page["id"] for page in index} == set(HELP_CATEGORIES)
    page = client.get(f"/api/help/{APP_ID}").json()
    assert page["markdown"].startswith("# ")
    assert client.get("/api/help/nope").status_code == 404
    assert help_page("../app") is None


def test_health_answers_at_the_root_and_under_the_prefix(runtime):
    from fastapi.testclient import TestClient

    from starter.api.app import create_app

    with TestClient(create_app(runtime)) as bare:
        assert bare.get("/healthz").json()["status"] == "ok"
        assert bare.get(f"{APP['runtime']['prefix']}healthz").json()["status"] == "ok"
