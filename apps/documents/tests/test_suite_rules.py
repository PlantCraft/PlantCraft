"""The suite's rules (``plantcraft_sdk.apptest``, PlantCraft ``docs/testing.md``): offline by
default, layers that only point down, the image that follows ``app.toml``, junk never answers 500,
and the API floor."""

from __future__ import annotations

import tomllib
from pathlib import Path

from plantcraft_sdk import apptest

from doccraft.api.app import create_app
from tests.conftest import client_for, guide, make_runtime
from tests.plant import make_fake

ROOT = Path(__file__).resolve().parents[1]
FLOORS = tomllib.loads((ROOT / "tests" / "floors.toml").read_text(encoding="utf-8"))
# | Layer | Packages |
# | -1 | i18n (everything may use t()) |
# | 0 | config, meta (the store is plantcraft_sdk.server.store) |
# | 1 | suite (what the app sends to PlantCraft; nothing yet) |
# | 2 | library (the app's own object: reading, passages, search, its store and its service) |
# | 3 | api, cli |
LAYERS = {"i18n": -1, "config": 0, "meta": 0, "suite": 1, "library": 2, "api": 3, "cli": 3}


def test_offline_by_default():
    assert not apptest.offline_problems(ROOT, "doccraft")


def test_layers_only_point_down_and_plant_data_comes_from_processcraft():
    assert not apptest.layer_problems(ROOT, "doccraft", LAYERS)


def test_only_suite_talks_to_plantcraft_for_the_app():
    assert not apptest.suite_problems(ROOT, "doccraft")


def test_routers_go_through_the_services():
    assert not apptest.router_problems(ROOT, "doccraft")


def test_what_app_toml_contributes_is_wired(runtime):
    routes = apptest.api_routes(create_app(runtime))
    assert not apptest.contribution_problems(ROOT, "doccraft", routes)


def test_the_screens_use_the_shared_ui_instead_of_copies():
    assert not apptest.ui_copy_problems(ROOT)


def test_the_image_follows_the_manifest():
    assert not apptest.image_problems(ROOT)


def test_api_floor(tmp_path, fake):
    runtime = make_runtime(tmp_path, fake)
    try:
        assert len(apptest.api_routes(create_app(runtime))) >= FLOORS["api"]["operations"]
    finally:
        runtime.shutdown()


def test_every_api_route_answers_junk_without_a_server_error(tmp_path):
    fake = make_fake()
    runtime = make_runtime(tmp_path, fake)
    try:
        with client_for(runtime, fake, "admin") as client:
            real = guide(client, runtime)
            folder = client.post("/api/folders", json={"name": "Kept"}).json()
            failures, answered = apptest.hostile_failures(
                client,
                real={"doc_id": real["doc_id"], "folder_id": folder["folder_id"]},
                keep={real["doc_id"], folder["folder_id"]},
                bodies=[
                    {"query": "x" * 600},
                    {"document": "doc:" + "x" * 70, "page": -1},
                    {"name": "General", "viewers": ["nobody"]},
                    {"assets": ["../etc"]},
                    {"title": ""},
                ],
                queries=[{"asset": "nowhere"}, {"filename": "../../x.pdf"}, {"page": "0"}],
            )
    finally:
        runtime.shutdown()
    assert not failures, "\n".join(failures[:40])
    assert answered > 20  # the routes were reached, not missed


def test_no_api_route_answers_without_a_token(runtime, fake):
    """A route that forgot its access check fails here (docs/contributing-safety.md)."""

    with client_for(runtime, fake, None) as client:
        client.headers.pop("Authorization", None)
        leaks, reached = apptest.open_routes(client, prefix="")
    assert not leaks, "routes answering without a token:\n" + "\n".join(leaks)
    assert reached > 10
