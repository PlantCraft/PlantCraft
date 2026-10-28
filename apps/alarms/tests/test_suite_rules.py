"""The suite's rules (``plantcraft_sdk.apptest``, PlantCraft ``docs/testing.md``): offline by
default, layers that only point down, the image that follows ``app.toml``, junk never answers 500,
and the API floor."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from plantcraft_sdk import apptest

from alarmcraft.api.app import create_app
from tests.conftest import client_for, high, make_runtime
from tests.plant import make_fake

ROOT = Path(__file__).resolve().parents[1]
FLOORS = tomllib.loads((ROOT / "tests" / "floors.toml").read_text(encoding="utf-8"))
# | Layer | Packages |
# | -1 | i18n (everything may use t()) |
# | 0 | config, meta (the store is plantcraft_sdk.server.store) |
# | 1 | alarms (the alarm contract and store) |
# | 2 | engine (evaluation and performance) |
# | 3 | monitor (the background cycle and what it publishes) |
# | 4 | api, cli |
LAYERS = {
    "i18n": -1,
    "config": 0,
    "meta": 0,
    "notebook_examples": 0,
    "alarms": 1,
    "engine": 2,
    "monitor": 3,
    "api": 4,
    "cli": 4,
}


def test_offline_by_default():
    assert not apptest.offline_problems(ROOT, "alarmcraft")


def test_layers_only_point_down_and_plant_data_comes_from_processcraft():
    assert not apptest.layer_problems(ROOT, "alarmcraft", LAYERS)


def test_only_suite_talks_to_plantcraft_for_the_app():
    assert not apptest.suite_problems(ROOT, "alarmcraft")


def test_routers_import_no_store():
    assert not apptest.router_problems(ROOT, "alarmcraft")


def test_what_app_toml_contributes_is_wired(runtime):
    routes = apptest.api_routes(create_app(runtime))
    assert not apptest.contribution_problems(ROOT, "alarmcraft", routes)


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
    """Also run against a real alarm, so handlers past the 404 see the junk too (bad windows,
    unknown assets, absurd limits)."""

    fake = make_fake()
    runtime = make_runtime(tmp_path, fake)
    try:
        with client_for(runtime, fake, "admin") as client:
            rule = client.post("/api/rules", json=high()).json()
            failures, answered = apptest.hostile_failures(
                client,
                real={"alarm_id": rule["rule_id"], "rule_id": rule["rule_id"], "event_id": "1"},
                keep={rule["rule_id"]},
                bodies=[
                    high(limit="soon", on_delay_seconds=-1),
                    high(limit=1e308, deadband=-2),
                    high(kind="sideways", priority=3),
                    high(assets=[], signal_id="x" * 301),
                    high(assets=["nowhere"]),
                    high(assets=[], under=["nowhere"]),
                    high(kind="events", events={"kinds": ["x"]}),
                    high(kind="events", events={"kinds": ["linkcraft.*.x"]}, count=0),
                    high(notify={"recipients": ["owner"], "hours_mode": "inside"}),
                    {"rule": high(), "window": "9999999d"},
                    {"rule": high(assets=["nowhere"]), "window": "1h"},
                    {"rule": high(), "window": "-1h"},
                    {"minutes": 0, "reason": "x"},
                    {"minutes": 99999999, "reason": ""},
                    {"alarm_ids": ["x" * 400]},
                ],
                queries=[{"asset": "nowhere", "window": "7d", "alarm": "x"}],
            )
    finally:
        runtime.shutdown()
    assert not failures, "\n".join(failures[:40])
    assert answered > 200  # the routes were reached, not missed


def test_no_api_route_answers_without_a_token(runtime, fake):
    """A route that forgot its access check fails here (docs/contributing-safety.md)."""

    with client_for(runtime, fake, None) as client:
        client.headers.pop("Authorization", None)
        leaks, reached = apptest.open_routes(client, prefix="")
    assert not leaks, "routes answering without a token:\n" + "\n".join(leaks)
    assert reached > 10
