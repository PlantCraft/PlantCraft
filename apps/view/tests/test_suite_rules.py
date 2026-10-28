"""The suite's rules (``plantcraft_sdk.apptest``, PlantCraft ``docs/testing.md``): offline by
default, layers that only point down, the image that follows ``app.toml``, junk never answers 500,
and the API floor. The [oracles] floor is checked by the oracle tests themselves."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from plantcraft_sdk import apptest

from dashcraft.api.app import create_app
from tests.conftest import client_for, dashboard, kpi, make_runtime
from tests.plant import make_fake

ROOT = Path(__file__).resolve().parents[1]
FLOORS = tomllib.loads((ROOT / "tests" / "floors.toml").read_text(encoding="utf-8"))
# | Layer | Packages |
# | -1 | i18n (everything may use t()) |
# | 0 | config, meta (the store is plantcraft_sdk.server.store) |
# | 1 | dashboards (card contract, store, starter dashboards), suite (what View tells PlantCraft) |
# | 2 | query (card data from API v1), reports (report contract, store, schedule, PDF) |
# | 3 | delivery (reports read, made, kept and sent) |
# | 4 | api, cli |
LAYERS = {
    "i18n": -1,
    "config": 0,
    "meta": 0,
    "dashboards": 1,
    "suite": 1,
    "query": 2,
    "reports": 2,
    "delivery": 3,
    "diagrams": 3,
    "api": 4,
    "cli": 4,
}


def test_offline_by_default():
    assert not apptest.offline_problems(ROOT, "dashcraft")


def test_layers_only_point_down_and_plant_data_comes_from_processcraft():
    assert not apptest.layer_problems(ROOT, "dashcraft", LAYERS)


def test_only_suite_talks_to_plantcraft_for_the_app():
    assert not apptest.suite_problems(ROOT, "dashcraft")


def test_routers_import_no_store():
    assert not apptest.router_problems(ROOT, "dashcraft")


def test_what_app_toml_contributes_is_wired(tmp_path, fake):
    runtime = make_runtime(tmp_path, fake)
    try:
        routes = apptest.api_routes(create_app(runtime))
    finally:
        runtime.shutdown()
    assert not apptest.contribution_problems(ROOT, "dashcraft", routes)


def test_the_screens_use_the_shared_ui_instead_of_copies():
    assert not apptest.ui_copy_problems(ROOT, ROOT.parents[1] / "ui" / "src")


def test_the_image_follows_the_manifest():
    assert not apptest.image_problems(ROOT)


def test_api_floor(tmp_path, fake):
    runtime = make_runtime(tmp_path, fake)
    try:
        assert len(apptest.api_routes(create_app(runtime))) >= FLOORS["api"]["operations"]
    finally:
        runtime.shutdown()


@pytest.mark.slow
def test_every_api_route_answers_junk_without_a_server_error(tmp_path):
    """Also run against a real dashboard, card and public link, so the handlers past the 404
    see the junk too."""

    fake = make_fake()
    runtime = make_runtime(tmp_path, fake)
    try:
        with client_for(runtime, fake, "admin") as setup:
            created = setup.post(
                "/dash/api/dashboards",
                json=dashboard(context_kind="loop", cards=[kpi(asset_id="$context", role="pv")]),
            ).json()
            share = setup.post(
                f"/dash/api/dashboards/{created['dashboard_id']}/shares", json={}
            ).json()
            client = TestClient(
                setup.app, base_url="http://testserver/dash/", raise_server_exceptions=False
            )
            client.headers.update(setup.headers)
            failures, answered = apptest.hostile_failures(
                client,
                real={
                    "dashboard_id": created["dashboard_id"],
                    "card_id": "k1",
                    "token": share["path"].rsplit("/", 1)[-1],
                },
                keep={created["dashboard_id"]},
                bodies=[
                    {"name": "ok", "cards": [{"card_id": "k", "kind": "kpi", "items": [{}]}]},
                    {"name": "ok", "cards": [kpi(window="-1d")]},
                    {"name": "ok", "refresh_seconds": "soon", "cards": "many"},
                    {
                        "card": {
                            "card_id": "k",
                            "kind": "trend",
                            "items": [{"signal_id": "x" * 301}],
                        }
                    },
                    {"card": kpi(), "context": "nowhere", "window": "9999999d"},
                    {"label": "x" * 500},
                ],
                queries=[{"context": "nowhere", "window": "1w"}],
            )
    finally:
        runtime.shutdown()
    assert not failures, "\n".join(failures[:40])
    assert answered > 100  # the routes were reached, not missed


def test_no_api_route_answers_without_a_token(runtime, fake):
    """A route that forgot its access check fails here (docs/contributing-safety.md)."""

    # A dashboard's or a diagram's public link opens without signing in (its token is the access).
    with client_for(runtime, fake, None) as client:
        client.headers.pop("Authorization", None)
        leaks, reached = apptest.open_routes(
            client,
            prefix="/dash",
            open_paths={
                "/api/public/{token}",
                "/api/public/{token}/cards/{card_id}",
                "/api/public/{token}/context",
                "/api/public/{token}/variables/{name}",
                "/api/public/diagram/{token}",
                "/api/public/diagram/{token}/data",
            },
        )
    assert not leaks, "routes answering without a token:\n" + "\n".join(leaks)
    assert reached > 10
