"""The suite's app standard: ``app.toml`` agrees with the code and image, and every app serves
``/healthz``, ``/api/meta``, ``/api/help`` and ``assets/<id>`` the same way."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from dashcraft import APP_ID, __version__
from dashcraft.config import Settings
from dashcraft.dashboards.model import CONTEXT
from dashcraft.meta import HELP_CATEGORIES, OTHER_CATEGORY, help_page, manifest
from tests.conftest import client_for, dashboard, kpi

ROOT = Path(__file__).resolve().parents[1]
APP = tomllib.loads((ROOT / "app.toml").read_text(encoding="utf-8"))
SUITE_ROW = {"id": "dashcraft", "prefix": "/dash/", "port": 8080, "uid": 10006}


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
    answer = client.get("/dash/api/meta").json()
    assert answer["app"]["id"] == "dashcraft" and "revision" in answer
    assert answer == {**manifest(), "revision": answer["revision"]}
    with client_for(runtime, fake, None) as anonymous:
        assert anonymous.get("/dash/api/meta").status_code == 401


def test_help_index_and_pages(client):
    index = client.get("/dash/api/help").json()
    assert {"dashboards", "cards", "public-links"} <= {page["id"] for page in index}
    page = client.get("/dash/api/help/cards").json()
    assert page["title"] and page["markdown"].startswith("# ")
    assert client.get("/dash/api/help/nope").status_code == 404
    assert help_page("../app") is None and help_page("..%2Fapp") is None


def test_help_pages_come_in_folders_for_the_help_browser(client):
    """Every guide has a category (the suite's HelpBrowser makes folders of it), and every
    guide in docs/help is listed in HELP_CATEGORIES, getting started first."""

    index = client.get("/dash/api/help").json()
    assert index[0] == {"id": "dashboards", "title": "Dashboards", "category": "Getting started"}
    assert all(page["category"] and page["category"] != OTHER_CATEGORY for page in index)
    assert {page["id"] for page in index} == set(HELP_CATEGORIES)


def test_an_asset_page_lists_the_dashboards_that_show_it(client):
    per_loop = dashboard(
        name="Loop detail", context_kind="loop", cards=[kpi(asset_id=CONTEXT, role="pv")]
    )
    names_it = dashboard(name="FIC-101 only", cards=[kpi(asset_id="fic-101", role="pv")])
    other = dashboard(name="Pumps", context_kind="pump", cards=[kpi(asset_id=CONTEXT, role="flow")])
    for body in (per_loop, names_it, other):
        assert client.post("/dash/api/dashboards", json=body).status_code == 201, body
    answer = client.get("/dash/api/asset-dashboards", params={"asset": "fic-101"}).json()
    asset = answer["asset"]
    assert (asset["id"], asset["kind"]) == ("fic-101", "loop")
    # What the asset panel of a process display shows: its signals by role.
    assert asset["signals"].get("pv") and isinstance(asset["description"], str)
    shown = {item["name"]: item["picks_asset"] for item in answer["dashboards"]}
    assert shown == {"Loop detail": True, "FIC-101 only": False}
    assert client.get("/dash/api/asset-dashboards", params={"asset": "nope"}).status_code == 404
