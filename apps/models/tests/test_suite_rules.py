"""The suite's rules (``plantcraft_sdk.apptest``, PlantCraft ``docs/testing.md``): offline by
default, layers that only point down, the image that follows ``app.toml``, junk never answers 500,
and the API floor. Models adds one of its own: the runner is the standard library only."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest
from plantcraft_sdk import apptest

from modelcraft.api.app import create_app
from tests.conftest import TLC, TLC_FILE, client_for, example, make_runtime, wait_for
from tests.plant import make_fake

ROOT = Path(__file__).resolve().parents[1]
FLOORS = tomllib.loads((ROOT / "tests" / "floors.toml").read_text(encoding="utf-8"))
# | Layer | Packages |
# | -1 | i18n (everything may use t()) |
# | 0 | config, meta, examples (the store is plantcraft_sdk.server.store) |
# | 1 | suite (what Models sends PlantCraft), projects (projects and files), modelica (Modelica text) |
# | 2 | omc (the runner, its jobs and what its answers become) |
# | 3 | runs (run records and the workbench) |
# | 4 | api, cli |
LAYERS = {
    "i18n": -1,
    "config": 0,
    "meta": 0,
    "examples": 0,
    "notebook_examples": 0,
    "suite": 1,
    "projects": 1,
    "modelica": 1,
    "omc": 2,
    "runs": 3,
    "api": 4,
    "cli": 4,
}


def test_only_suite_talks_to_plantcraft_for_the_app():
    assert not apptest.suite_problems(ROOT, "modelcraft")


def test_routers_import_no_store():
    assert not apptest.router_problems(ROOT, "modelcraft")


def test_what_app_toml_contributes_is_wired(runtime):
    routes = apptest.api_routes(create_app(runtime))
    assert not apptest.contribution_problems(ROOT, "modelcraft", routes)


def test_the_screens_use_the_shared_ui_instead_of_copies():
    assert not apptest.ui_copy_problems(ROOT, ROOT.parents[1] / "ui" / "src")


def test_offline_by_default():
    assert not apptest.offline_problems(ROOT, "modelcraft")


def test_layers_only_point_down_and_plant_data_comes_from_processcraft():
    assert not apptest.layer_problems(ROOT, "modelcraft", LAYERS)


def test_the_runner_uses_the_standard_library_only():
    """The runner container has Python 3.10 and nothing else: no package, no modelcraft."""

    for name in apptest.imports(ROOT / "src" / "modelcraft" / "omc" / "runner.py"):
        top = name.split(".")[0]
        assert top in sys.stdlib_module_names or top == "__future__", f"runner.py imports {name}"


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
    """Also run against a real project, file and run, so the handlers past the 404 see the junk
    too (bad class names, paths outside the project, absurd simulation settings, edits that would
    write code)."""

    fake = make_fake()
    runtime = make_runtime(tmp_path, fake)
    try:
        with client_for(runtime, fake, "admin") as client:
            project = example(client)
            run = client.post(
                f"/api/projects/{project['id']}/simulate", json={"model": TLC, "stop": 900}
            ).json()
            wait_for(client, run["id"])
            tank = TLC_FILE
            failures, answered = apptest.hostile_failures(
                client,
                real={
                    "project_id": project["id"],
                    "run_id": run["id"],
                    "path": TLC_FILE,
                    "revision_id": "1",
                    "model": TLC,
                },
                keep={project["id"], run["id"]},
                bodies=[
                    {"model": 'A); system("id'},
                    {"model": TLC, "stop": "soon", "intervals": -1, "method": "rm -rf"},
                    {"model": TLC, "stop": 1e308, "tolerance": 0, "overrides": {"a=1 -b": 1}},
                    {"model": TLC, "overrides": {"k": "nan"}},
                    {
                        "model": TLC,
                        "plant": {"start": "never", "end": "x", "inputs": {"u": "x" * 400}},
                    },
                    {
                        "model": TLC,
                        "plant": {"start": "2026-10-01T00:00:00Z", "end": "2025-10-01T00:00:00Z"},
                    },
                    {"model": TLC, "version": "9.0", "type": "x"},
                    {"path": "../../etc/passwd", "content": "x"},
                    {"path": "A.mo", "content": "\x00"},
                    {"content": "model X end X;", "base_updated_at": "x" * 100},
                    {"files": {"/abs.mo": "x"}},
                    {
                        "model": TLC,
                        "file": "../x.mo",
                        "op": "add",
                        "type": "A;B",
                        "extent": [[0, 0], ["a", 1]],
                    },
                    {
                        "model": TLC,
                        "file": tank,
                        "op": "modifiers",
                        "name": "tank",
                        "values": {"A": "1); x(", "B[1]": "2"},
                    },
                    {"model": TLC, "file": tank, "op": "connect", "left": "a b", "right": "c"},
                    {"names": ["x" * 500] * 50, "max_points": 1},
                    {"label": "x" * 500},
                ],
                queries=[
                    {"limit": "abc", "model": "x;y"},
                    {"project": "x" * 400, "parent": "\x00", "name": "Modelica.Nope", "kind": "x"},
                    {"asset": "nowhere", "prefix": "x" * 500, "model": TLC},
                ],
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
