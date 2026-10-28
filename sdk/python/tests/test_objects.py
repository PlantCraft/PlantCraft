"""An app's objects and examples for notebooks: the [contributes] tables, the routes every app
serves the same way, the runtime zip and the checks apptest runs."""

from __future__ import annotations

import io
import json
import sys
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_contributes import _data, _problems
from test_server import _repo, _runtime

from plantcraft_sdk.app_manifest import parse_manifest
from plantcraft_sdk.apptest import contribution_problems, objects_problems
from plantcraft_sdk.notebooks import MODULE, Example, cell, example_problems
from plantcraft_sdk.server.objects import (
    FORMAT,
    AppObjects,
    notebooks_router,
    object_item,
    runtime_zip,
)
from plantcraft_sdk.server.web import mount, suite_api
from plantcraft_sdk.testing import FakePlantCraft

OBJECTS_TOML = """
[[contributes.objects]]
kind = "thing"
title = "Thing"
run = "local"

[[contributes.objects]]
kind = "report"
title = "Report"

[[contributes.objects]]
kind = "job"
title = "Job"
run = "app"

[contributes.notebooks]
examples = true
runtime = ["demoruntime"]
entry = "demoruntime.notebook"
"""

THINGS = {"t-1": {"name": "First", "size": 3}, "t-2": {"name": "Second", "size": 5}}
EXAMPLES = [
    Example("count-things", "Count things", "How many things.", lambda: [cell("code", "1 + 1")])
]


def test_a_manifest_declares_its_objects_and_notebooks():
    contributes = parse_manifest(_data(OBJECTS_TOML)).contributes
    assert [item.kind for item in contributes.objects] == ["thing", "report", "job"]
    assert contributes.objects[0].run == "local" and contributes.objects[1].run == "none"
    assert contributes.notebooks.entry == "demoruntime.notebook"


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (
            "[[contributes.objects]]\nkind = 'thing'\ntitle = 'x'\n"
            "[[contributes.objects]]\nkind = 'thing'\ntitle = 'y'",
            "object kind declared more than once",
        ),
        (
            "[[contributes.objects]]\nkind = 'thing'\ntitle = 'x'\nrun = 'local'",
            "names the runtime",
        ),
        ("[contributes.notebooks]\nruntime = ['a']", "runtime and its entry together"),
        ("[contributes.notebooks]\nruntime = ['a']\nentry = 'b.run'", "a module of its runtime"),
        ("[[contributes.objects]]\nkind = 'thing'\ntitle = 'x'\nrun = 'server'", "objects.0.run"),
    ],
)
def test_an_objects_table_that_breaks_a_rule_is_named(extra, message):
    assert message in _problems(extra)


@pytest.fixture()
def runtime_package(tmp_path, monkeypatch):
    package = tmp_path / "site" / "demoruntime"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "notebook.py").write_text("def run(kind, item, plant, app, **options):\n    ...\n")
    (package / "help.md").write_text("# Help\n")
    (package / "__pycache__").mkdir()
    (package / "__pycache__" / "notebook.cpython-313.pyc").write_bytes(b"x")
    monkeypatch.syspath_prepend(str(tmp_path / "site"))
    yield package
    sys.modules.pop("demoruntime", None)
    runtime_zip.cache_clear()


@pytest.fixture()
def app(tmp_path, runtime_package):
    fake = FakePlantCraft()
    objects = AppObjects()

    @objects.lister("thing")
    def things(_user, _rt):
        return [
            object_item(key, value["name"], size=value["size"]) for key, value in THINGS.items()
        ]

    @objects.getter("thing")
    def thing(_user, _rt, thing_id):
        found = THINGS.get(thing_id)
        return None if found is None else {**found, "parts": ["a", "b"]}

    @objects.lister("report")
    def reports(_user, _rt):
        return []

    jobs: dict[str, dict] = {}

    @objects.lister("job")
    def job_list(_user, _rt):
        return [object_item(key, key, status=value["status"]) for key, value in jobs.items()]

    @objects.getter("job")
    def job(_user, _rt, job_id):
        return jobs.get(job_id)

    @objects.runner("job")
    def start(user, _rt, thing_id, options):
        if thing_id not in THINGS:
            raise HTTPException(status_code=404, detail="Not found.")
        if not user.can_edit:
            raise HTTPException(status_code=403, detail="Read-only.")
        job_id = f"job-{len(jobs) + 1}"
        jobs[job_id] = {"name": job_id, "status": "queued", "thing": thing_id, **options}
        return {"kind": "job", "id": job_id}

    manifest = parse_manifest(_data(OBJECTS_TOML))
    runtime = _runtime(fake)
    api = suite_api(
        runtime,
        title="Demo",
        version="0.1.0",
        files=_repo(tmp_path),
        routers=[objects.router(), notebooks_router(EXAMPLES, manifest)],
    )
    client = TestClient(mount(api, runtime, version="0.1.0"))
    client.headers["Authorization"] = f"Bearer {fake.token('engineer')}"
    return client


def test_every_app_answers_its_objects_in_one_format(app):
    listing = app.get("/demo/api/objects/thing").json()
    assert listing["format"] == FORMAT and listing["kind"] == "thing"
    assert listing["items"][0] == {"id": "t-1", "name": "First", "size": 3}
    one = app.get("/demo/api/objects/thing/t-2").json()
    assert one == {"id": "t-2", "name": "Second", "size": 5, "parts": ["a", "b"], "kind": "thing"}
    assert app.get("/demo/api/objects/thing/t-9").status_code == 404
    assert app.get("/demo/api/objects/nothing").status_code == 404
    assert app.get("/demo/api/objects/thing", headers={"Authorization": ""}).status_code == 401


def test_examples_are_notebooks_that_start_like_every_notebook(app):
    items = app.get("/demo/api/notebooks/examples").json()["items"]
    assert items == [{"id": "count-things", "title": "Count things", "summary": "How many things."}]
    notebook = app.get("/demo/api/notebooks/examples/count-things").json()
    assert notebook["nbformat"] == 4
    assert MODULE in notebook["cells"][1]["source"] and notebook["cells"][2]["source"] == "1 + 1"
    assert app.get("/demo/api/notebooks/examples/nope").status_code == 404
    assert example_problems(EXAMPLES) == []
    twice = [EXAMPLES[0], EXAMPLES[0]]
    assert "example id used more than once: count-things" in example_problems(twice)


def test_the_runtime_is_the_installed_packages_in_one_stable_zip(app, runtime_package):
    first = app.get("/demo/api/notebooks/runtime")
    assert first.status_code == 200 and first.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(first.content))
    assert sorted(archive.namelist()) == [
        "demoruntime/__init__.py",
        "demoruntime/help.md",
        "demoruntime/notebook.py",
        "plantcraft-runtime.json",
    ]
    manifest = json.loads(archive.read("plantcraft-runtime.json"))
    assert manifest["entry"] == "demoruntime.notebook" and manifest["packages"] == ["demoruntime"]
    etag = first.headers["etag"]
    again = app.get("/demo/api/notebooks/runtime", headers={"If-None-Match": etag})
    assert again.status_code == 304
    runtime_zip.cache_clear()
    assert app.get("/demo/api/notebooks/runtime").content == first.content


def test_apptest_checks_the_objects_an_app_declares(app, tmp_path):
    root = tmp_path / "declared"
    root.mkdir()
    (root / "app.toml").write_text(
        '[app]\nid = "demoapp"\nversion = "0.1.0"\n' + OBJECTS_TOML, encoding="utf-8"
    )
    assert objects_problems(app, "/demo", root) == []
    routes = [("GET", "/api/widgets/{widget_id}")]
    problems = contribution_problems(root, "demoapp", routes)
    assert "objects are declared but no route serves /api/objects/<kind>" in problems
    assert any("/api/notebooks/runtime" in problem for problem in problems)
    broken = SimpleNamespace(get=lambda path, **_: SimpleNamespace(status_code=500))
    assert "objects 'thing': the list answered 500" in objects_problems(broken, "/demo", root)


def test_a_kind_that_runs_in_the_app_starts_a_run_and_says_what_to_read_back(app):
    started = app.post("/demo/api/objects/job/run", json={"id": "t-1", "options": {"stop": 10}})
    assert started.status_code == 201, started.text
    body = started.json()
    assert body["format"] == FORMAT and body["started"] == {"kind": "job", "id": "job-1"}
    assert app.get("/demo/api/objects/job/job-1").json()["stop"] == 10
    assert app.post("/demo/api/objects/job/run", json={"id": "t-9"}).status_code == 404
    assert app.post("/demo/api/objects/thing/run", json={"id": "t-1"}).status_code == 404
    too_many = {"id": "t-1", "options": {f"k{n}": n for n in range(101)}}
    assert app.post("/demo/api/objects/job/run", json=too_many).status_code == 422
