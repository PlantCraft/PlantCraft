"""The app standard's manifest and endpoints: app.toml, /api/meta, /api/help, assets/<id>.

``app.toml`` is the one source of Analytics' metadata; every other place that repeats a value
(pyproject, the package, the Dockerfile's build-arg defaults, the Vite base) must agree with it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import linkcraft
from linkcraft.api.app import create_app
from linkcraft.config import Settings, app_manifest
from tests.conftest import client_for
from tests.plant import sid

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = tomllib.loads((ROOT / "app.toml").read_text(encoding="utf-8"))
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")


def _arg(name: str) -> str:
    match = re.search(rf"^ARG {name}=(.+)$", DOCKERFILE, re.MULTILINE)
    assert match, f"Dockerfile has no ARG {name}"
    return match.group(1).strip().strip('"')


def test_the_manifest_has_every_section_of_the_standard():
    for section in ("app", "runtime", "requires", "permissions", "publishes", "consumes"):
        assert section in MANIFEST, section
    app, runtime = MANIFEST["app"], MANIFEST["runtime"]
    assert re.fullmatch(r"[a-z][a-z0-9]{2,30}", app["id"])
    # Only the platform keeps the Craft brand (D10): a module is "PlantCraft <name>".
    assert app["name"] == "PlantCraft Analytics" and app["mark"] == app["id"]
    assert (app["id"], runtime["prefix"], runtime["port"], runtime["uid"]) == (
        "linkcraft",
        "/link/",
        8140,
        10012,
    )  # the suite table, section 7
    assert runtime["health"] == "/healthz" and runtime["image"] == app["id"]
    assert MANIFEST["requires"]["asset_types"] == ["loop"]
    assert MANIFEST["requires"]["roles"] == {"loop": ["pv", "op"]}
    assert MANIFEST["permissions"]["plant_write"] is False
    assert MANIFEST["permissions"]["outbound"] == []
    assert MANIFEST["publishes"]["results"] == [
        {"kind": "loop_health", "subject": "asset:loop"},
        {"kind": "signal_quality", "subject": "signal"},
        {"kind": "signal_quality", "subject": "asset"},
    ]
    # Every event Link writes is declared (tests/test_event_catalog.py holds code and manifest
    # together).
    assert {item["name"] for item in MANIFEST["publishes"]["events"]} >= {
        "finding.opened",
        "finding.closed",
        "status.changed",
        "run.failed",
    }
    assert MANIFEST["consumes"]["results"] == []  # signal quality is Analytics' own now
    assert not re.search(r"https?://", MANIFEST["app"]["homepage"] + app["description"])


def test_the_asset_page_links_linkcraft_on_control_loops():
    """Section 2: PlantCraft links an app on an asset page when ``[requires] asset_types``
    lists the asset's type or an ancestor. Analytics covers Control loop (the starter type id
    ``loop``) and so every type derived from it; the sync reads the same id."""

    from plantcraft_sdk.assets import LOOP_TYPE, resolve_types, starter_types

    from tests.plant import ASSET_TYPES

    starter = {item["id"]: item for item in starter_types()}
    assert starter[LOOP_TYPE]["name"] == "Control loop"
    assert MANIFEST["requires"]["asset_types"] == [LOOP_TYPE] == [Settings().loop_asset_kind]
    covered = {
        item["id"]
        for item in resolve_types(ASSET_TYPES)
        if set(item["path"]) & set(MANIFEST["requires"]["asset_types"])
    }
    assert covered == {"loop", "cascade_loop"}


def test_the_repository_follows_the_suite_standard():
    """``plantcraft-app check .`` (also a step of ``make ci``)."""

    from plantcraft_sdk.app_cli import check

    report = check(ROOT)
    assert report.ok, report.errors
    assert "standard" in re.findall(r"^ci:(.*)$", (ROOT / "Makefile").read_text(), re.M)[0]


def test_nothing_else_disagrees_with_the_manifest():
    app, runtime = MANIFEST["app"], MANIFEST["runtime"]
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["version"] == app["version"] == linkcraft.__version__
    assert linkcraft.APP_ID == app["id"]
    assert MANIFEST["requires"]["sdk"] in project["dependencies"][0]
    assert f"SDK := plantcraft-sdk=={MANIFEST['requires']['sdk']}" in (ROOT / "Makefile").read_text(
        encoding="utf-8"
    )
    assert Settings().root_path + "/" == runtime["prefix"]
    vite = (ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
    assert f'base: "{runtime["prefix"]}"' in vite
    assert 'assetsDir: "static"' in vite
    assert _arg("APP_ID") == app["id"]
    # No version kept in the Dockerfile: the build refuses a VERSION that is not app.toml's.
    assert re.search(r"^ARG VERSION$", DOCKERFILE, re.MULTILINE)
    assert not re.search(r"^ARG VERSION=", DOCKERFILE, re.MULTILINE)
    assert "tomllib.load(open('app.toml', 'rb'))['app']['version']" in DOCKERFILE
    assert f'"{app["version"]}"' not in (ROOT / "src" / "linkcraft" / "__init__.py").read_text()
    assert _arg("APP_PREFIX") == runtime["prefix"]
    assert int(_arg("APP_PORT")) == runtime["port"] and int(_arg("APP_UID")) == runtime["uid"]
    assert _arg("SUMMARY") == app["summary"]


def test_the_image_carries_the_suite_labels_and_the_manifest():
    for label in ("id", "prefix", "port"):
        assert f"org.processcraft.app.{label}=" in DOCKERFILE
    assert "app.toml /app/" in DOCKERFILE and "LINKCRAFT_APP_TOML=/app/app.toml" in DOCKERFILE
    assert "LINKCRAFT_REVISION=${REVISION}" in DOCKERFILE
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^package: image$", makefile, re.MULTILINE)


def test_the_image_ships_its_sbom_like_the_other_apps():
    # The suite bundle collects each image's SBOM from /app/sbom.json; make package signs it.
    assert (
        'python -m plantcraft_sdk.sbom --here "${APP_ID}:${VERSION}" > /app/sbom.json' in DOCKERFILE
    )
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "/app/sbom.json > dist/sbom.spdx.json" in makefile
    # The app's workflow is at the repository's root (.github/workflows/link.yml).
    ci = (ROOT.parents[1] / ".github" / "workflows" / "link.yml").read_text(encoding="utf-8")
    assert "open('/app/sbom.json')" in ci


def test_sbom_here_lists_what_this_interpreter_holds():
    # What the Dockerfile runs inside the image, run here: SPDX, the app and its dependencies.
    found = subprocess.run(
        [sys.executable, "-m", "plantcraft_sdk.sbom", "--here", "linkcraft:0.0.0"],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "SBOM_CREATED": "2026-10-20T12:00:00"},
    )
    document = json.loads(found.stdout)
    assert document["spdxVersion"] == "SPDX-2.3"
    assert document["creationInfo"]["created"] == "2026-10-20T12:00:00Z"
    names = {package["name"] for package in document["packages"]}
    assert {"linkcraft", "fastapi", "plantcraft-sdk"} <= names


def test_meta_serves_the_manifest_and_the_revision(client, runtime, fake):
    answer = client.get("/link/api/meta")
    assert answer.status_code == 200
    body = answer.json()
    assert {key: value for key, value in body.items() if key != "revision"} == app_manifest()
    assert body["app"]["id"] == "linkcraft" and isinstance(body["revision"], str)
    assert "test-app-key" not in answer.text  # no secrets
    anonymous = TestClient(create_app(runtime), raise_server_exceptions=False)
    assert anonymous.get("/link/api/meta").status_code == 401


def test_starting_sends_the_manifest_contributions_to_plantcraft(runtime, fake, monkeypatch):
    # The SDK sends `files.manifest()` at start; without it Link's works, events and refs never
    # reached PlantCraft (the assistant offered no block card, 2026-10-26).
    sent: list[dict] = []
    monkeypatch.setattr(runtime, "send_contributions", sent.append, raising=False)
    with client_for(runtime, fake):
        pass
    assert sent == [app_manifest()]
    assert any(
        work.get("kind") == "create" for work in sent[0]["contributes"]["assistant"]["works"]
    )


def test_meta_reads_the_manifest_the_environment_names(monkeypatch, tmp_path):
    from linkcraft import config

    path = tmp_path / "app.toml"
    path.write_text('[app]\nid = "linkcraft"\nversion = "9.9.9"\n', encoding="utf-8")
    monkeypatch.setenv("LINKCRAFT_APP_TOML", str(path))
    monkeypatch.setenv("LINKCRAFT_REVISION", "abc1234")
    config.app_manifest.cache_clear()
    config.revision.cache_clear()
    try:
        assert config.app_manifest()["app"]["version"] == "9.9.9"
        assert config.revision() == "abc1234"
    finally:
        config.app_manifest.cache_clear()
        config.revision.cache_clear()


def test_help_index_lists_every_page_with_its_address(client):
    body = client.get("/link/api/help").json()
    assert body["app"] == "linkcraft"
    pages = {page["id"]: page for page in body["pages"]}
    assert pages["guides/overview"]["url"] == "/link/help?doc=guides/overview"
    method = pages["methods/sampling_quality"]
    assert method["kind"] == "method" and method["url"] == "/link/help/methods/sampling_quality"
    assert client.get(method["api"]).status_code == 200
    assert len([page for page in body["pages"] if page["kind"] == "method"]) >= 25


@pytest.mark.parametrize(
    ("asset_id", "covered"),
    [("fic-101", True), ("area-a", False), ("no-such-asset", False), ("pi:a/b c", False)],
)
def test_the_asset_page_lists_its_results_or_says_why_not(client, runtime, asset_id, covered):
    runtime.sync_loops()
    from urllib.parse import quote

    body = client.get(f"/link/api/assets/{quote(asset_id, safe='')}").json()
    assert body["asset_id"] == asset_id and body["covered"] is covered
    if covered:
        assert body["loop_id"] == asset_id and body["reason"] is None
        assert body["name"] and {role["role"] for role in body["signals"]} >= {"pv", "op"}
    else:
        assert body["loop_id"] is None and "No algorithm of Analytics runs" in body["reason"]
        assert body["results"] == []


def test_a_loop_defined_here_is_not_an_asset(client, runtime):
    from linkcraft.config import LoopConfig, LoopSignals

    runtime.loops.save_loop(
        LoopConfig(loop_id="mine", name="Mine", signals=LoopSignals(pv=sid("FIC-101.PV"))),
        origin="user",
    )
    assert client.get("/link/api/assets/mine").json()["covered"] is False


@pytest.fixture
def built_ui(tmp_path, monkeypatch):
    folder = tmp_path / "ui"
    (folder / "static").mkdir(parents=True)
    (folder / "index.html").write_text("<!doctype html><title>Analytics</title>", encoding="utf-8")
    (folder / "static" / "index-abc.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setenv("LINKCRAFT_UI_DIR", str(folder))
    return folder


def test_built_files_are_under_static_and_assets_is_the_deep_link(built_ui, runtime, fake):
    with client_for(runtime, fake) as client:
        script = client.get("/link/static/index-abc.js")
        assert script.status_code == 200 and "console.log" in script.text
        page = client.get("/link/assets/fic-101", headers={"Accept": "text/html"})
        assert page.status_code == 200 and "<title>Analytics</title>" in page.text
    anonymous = TestClient(create_app(runtime), raise_server_exceptions=False)
    redirect = anonymous.get(
        "/link/assets/fic-101", headers={"Accept": "text/html"}, follow_redirects=False
    )
    assert redirect.status_code == 303 and "next=" in redirect.headers["location"]
