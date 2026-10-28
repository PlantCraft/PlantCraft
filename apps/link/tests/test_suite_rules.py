"""The suite's rules (``plantcraft_sdk.apptest``, PlantCraft ``docs/testing.md``): offline by
default, layers that only point down, the image that follows ``app.toml``, junk never answers 500,
and the floors. The [oracles] floors are checked by the oracle tests themselves."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from plantcraft_sdk import apptest

from linkcraft.api.app import create_app
from linkcraft.catalog.registry import METHOD_MODULES
from linkcraft.catalog.signal_checks import CHECKS
from tests.conftest import client_for, make_runtime
from tests.plant import make_fake
from tests.test_hostile_inputs import FRAMES
from tests.test_signal_hostile_inputs import SERIES

ROOT = Path(__file__).resolve().parents[1]
FLOORS = tomllib.loads((ROOT / "tests" / "floors.toml").read_text(encoding="utf-8"))
# | Layer | Packages |
# | -1 | i18n (any module may word text through t()) |
# | 0 | db, config (the store is plantcraft_sdk.server.store), notebook_examples |
# | 1 | methods, models (FMUs, their store, simulation and statistics) |
# | 2 | catalog, data |
# | 3 | engine |
# | 4 | loops, signals, assets, report, knowledge |
# | 5 | api, cli, bench, notebook (blocks and algorithms run in a notebook) |
LAYERS = {
    "i18n": -1,
    "db": 0,
    "config": 0,
    "notebook_examples": 0,
    "methods": 1,
    "models": 1,
    "catalog": 2,
    "data": 2,
    "blocks": 3,
    "engine": 3,
    "loops": 4,
    "signals": 4,
    "assets": 4,
    "report": 4,
    "knowledge": 4,
    "api": 5,
    "cli": 5,
    "bench": 5,
    "notebook": 5,
}


def test_offline_by_default():
    # bench.py measures against its own in-process fake on 127.0.0.1; blocks/sandbox.py imports
    # socket only to switch it off in the block workers.
    network = ("api/runtime.py", "bench.py")
    assert not apptest.offline_problems(
        ROOT,
        "linkcraft",
        network_modules=(*network, "blocks/sandbox.py"),
        client_builders=network,
    )


def test_layers_only_point_down_and_plant_data_comes_from_processcraft():
    assert not apptest.layer_problems(ROOT, "linkcraft", LAYERS)


def test_only_suite_talks_to_plantcraft_for_the_app():
    assert not apptest.suite_problems(ROOT, "linkcraft")


def test_routers_import_no_store():
    assert not apptest.router_problems(ROOT, "linkcraft")


def test_what_app_toml_contributes_is_wired(tmp_path, fake):
    runtime = make_runtime(tmp_path, fake)
    try:
        routes = apptest.api_routes(create_app(runtime))
    finally:
        runtime.shutdown()
    assert not apptest.contribution_problems(ROOT, "linkcraft", routes)


def test_the_screens_use_the_shared_ui_instead_of_copies():
    assert not apptest.ui_copy_problems(ROOT, ROOT.parents[1] / "ui" / "src")


def test_the_image_follows_the_manifest():
    # Link's health check reads the port from LINKCRAFT_PORT (ENV, set from APP_PORT).
    problems = [p for p in apptest.image_problems(ROOT) if "health check" not in p]
    assert not problems


def test_method_and_check_floors():
    assert len(METHOD_MODULES) >= FLOORS["methods"]["registered"]
    assert len(FRAMES) >= FLOORS["methods"]["hostile_frames"]
    assert len(CHECKS) >= FLOORS["signal_checks"]["registered"]
    assert len(SERIES) >= FLOORS["signal_checks"]["hostile_series"]


def test_api_floor(tmp_path, fake):
    runtime = make_runtime(tmp_path, fake)
    try:
        assert len(apptest.api_routes(create_app(runtime))) >= FLOORS["api"]["operations"]
    finally:
        runtime.shutdown()


@pytest.mark.slow
def test_every_api_route_answers_junk_without_a_server_error(tmp_path):
    """After one monitoring round, so the handlers past the 404 see the junk too."""

    fake = make_fake()
    runtime = make_runtime(tmp_path, fake)
    runtime.run_round()
    try:
        with client_for(runtime, fake, "admin") as setup:
            loop_id = setup.get("/link/api/loops").json()[0]["loop_id"]
            client = TestClient(
                setup.app, base_url="http://testserver/link/", raise_server_exceptions=False
            )
            client.headers.update(setup.headers)
            failures, answered = apptest.hostile_failures(
                client,
                real={"loop_id": loop_id},
                keep={loop_id},
                bodies=[{"window": "-1d", "limit": -5}],
                queries=[{"loop": "fic-101", "start": "never", "end": "2026-13-45"}],
            )
    finally:
        runtime.shutdown()
    assert not failures, "\n".join(failures[:40])
    assert answered > 200  # the routes were reached, not missed


def test_no_api_route_answers_without_a_token(runtime, fake):
    """A route that forgot its access check fails here (docs/contributing-safety.md)."""

    with client_for(runtime, fake) as client:
        client.headers.pop("Authorization", None)
        leaks, reached = apptest.open_routes(client, prefix="/link")
    assert not leaks, "routes answering without a token:\n" + "\n".join(leaks)
    assert reached > 10
