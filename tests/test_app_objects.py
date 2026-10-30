"""The apps' objects for notebooks (owner, 2026-10-26): ``/api/v1/objects``, the reads PlantCraft
forwards to an app with the person's identity, the apps' examples in the Examples folder, and
``pc.app`` in a notebook, against a fake app inside the suite's network."""

from __future__ import annotations

import io
import json
import sys
import zipfile

import httpx
import pytest
from fastapi.testclient import TestClient

from plantcraft.api import app_proxy as proxy
from plantcraft.api import notebook_examples as examples
from plantcraft_sdk.contributes import ContributionsIn
from tests.test_notebooks import _routed, _turn_on, dist, pc  # noqa: F401
from tests.test_route_permissions import _login, app  # noqa: F401

BLOCKS = [{"id": "stats.mean", "name": "Mean", "library": "stats"}]
EXAMPLE = {
    "nbformat": 4,
    "nbformat_minor": 5,
    "metadata": {},
    "cells": [{"cell_type": "markdown", "metadata": {}, "source": "# Example: Run a block"}],
}
RUNTIME_CODE = (
    "def run(kind, item, plant, app, **options):\n"
    "    return {'kind': kind, 'id': item['id'], 'app': app.id, 'options': options}\n"
)


def _runtime() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "plantcraft-runtime.json",
            json.dumps({"format": "plantcraft-runtime/1", "entry": "fakelink.notebook"}),
        )
        archive.writestr("fakelink/__init__.py", "")
        archive.writestr("fakelink/notebook.py", RUNTIME_CODE)
    return buffer.getvalue()


class FakeLink:
    """Link inside the suite's network: what it was asked, and with which identity."""

    def __init__(self) -> None:
        self.asked: list[httpx.Request] = []
        self.failing = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        if self.failing:
            return httpx.Response(500, json={"detail": "boom"})
        path = request.url.path.removeprefix("/link/")
        if path == "api/objects/block":
            return httpx.Response(
                200, json={"format": "plantcraft-objects/1", "kind": "block", "items": BLOCKS}
            )
        if path == "api/objects/block/stats.mean":
            return httpx.Response(200, json={**BLOCKS[0], "kind": "block", "inputs": []})
        if path == "api/notebooks/examples":
            item = {"id": "run-a-block", "title": "Run a block", "summary": "Blocks here."}
            return httpx.Response(200, json={"format": "plantcraft-notebooks/1", "items": [item]})
        if path == "api/notebooks/examples/run-a-block":
            return httpx.Response(200, json=EXAMPLE)
        if path == "api/notebooks/runtime":
            return httpx.Response(
                200,
                content=_runtime(),
                headers={"content-type": "application/zip", "etag": '"abc"'},
            )
        return httpx.Response(404, json={"detail": "Not found."})


@pytest.fixture
def link(monkeypatch):
    fake = FakeLink()
    monkeypatch.setenv("PLANTCRAFT_APPS", "linkcraft=/link/")
    monkeypatch.setenv("PLANTCRAFT_OPS_URLS", "linkcraft=http://linkcraft:8140/link")
    monkeypatch.setattr(proxy, "transport", lambda: httpx.MockTransport(fake))
    examples.clear()
    yield fake
    examples.clear()


def _offer(app) -> None:  # noqa: F811
    app.state.runtime.contributions.put(
        "linkcraft",
        ContributionsIn.model_validate(
            {
                "contributes": {
                    "objects": [
                        {"kind": "block", "title": "Blocks", "run": "local"},
                        {"kind": "algorithm", "title": "Algorithms", "run": "local"},
                    ],
                    "notebooks": {
                        "examples": True,
                        "runtime": ["linkcraft", "plantcraft_sdk"],
                        "entry": "linkcraft.notebook",
                    },
                }
            }
        ),
    )


def test_a_person_reads_an_apps_objects_through_plantcraft(app, dist, link):  # noqa: F811
    with TestClient(app):
        _turn_on(app)
        _offer(app)
        vera = _login(app, "vera", "vera-strong-password")
        token = vera.post("/api/assistant-access/mine", json={"label": "laptop"}).json()["token"]
        reader = TestClient(app, headers={"Authorization": f"Bearer {token}"})

        [offer] = reader.get("/api/v1/objects").json()["apps"]
        assert offer["app"] == "linkcraft" and offer["runtime"] is True and offer["examples"]
        assert [kind["kind"] for kind in offer["kinds"]] == ["block", "algorithm"]

        listed = reader.get("/api/v1/apps/linkcraft/objects/block").json()
        assert listed["items"] == BLOCKS
        assert reader.get("/api/v1/apps/linkcraft/objects/block/stats.mean").json()["kind"] == (
            "block"
        )
        # The app gets a signed identity of the person, never the access token.
        sent = link.asked[-1].headers["authorization"]
        assert sent.startswith("Bearer ") and token not in sent
        assert reader.get("/api/v1/apps/linkcraft/objects/model").status_code == 404
        assert reader.get("/api/v1/apps/histcraft/objects/block").status_code == 404
        runtime = reader.get("/api/v1/apps/linkcraft/notebooks/runtime")
        assert runtime.status_code == 200 and runtime.headers["etag"] == '"abc"'

        link.failing = True
        assert reader.get("/api/v1/apps/linkcraft/objects/block").status_code == 502


def test_an_app_that_does_not_answer_says_so(app, dist, link, monkeypatch):  # noqa: F811
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    monkeypatch.setattr(proxy, "transport", lambda: httpx.MockTransport(refuse))
    with TestClient(app):
        _turn_on(app)
        _offer(app)
        vera = _login(app, "vera", "vera-strong-password")
        token = vera.post("/api/assistant-access/mine", json={"label": "laptop"}).json()["token"]
        reader = TestClient(app, headers={"Authorization": f"Bearer {token}"})
        assert reader.get("/api/v1/apps/linkcraft/objects/block").status_code == 503
        # Its examples are left out; PlantCraft's own are still there.
        names = {item["folder"] for item in vera.get("/api/notebooks").json()["examples"]}
        assert names == {"PlantCraft"}


def test_only_the_apps_own_reads_are_forwarded():
    with pytest.raises(ValueError):
        proxy.get(None, "linkcraft", "api/settings", "vera")
    with pytest.raises(ValueError):
        proxy.get(None, "linkcraft", "api/objects/../settings", "vera")


def test_an_apps_examples_are_a_folder_of_their_own(app, dist, link):  # noqa: F811
    with TestClient(app):
        _turn_on(app)
        _offer(app)
        vera = _login(app, "vera", "vera-strong-password")
        listed = vera.get("/api/notebooks").json()["examples"]
        mine = [item for item in listed if item["app"] == "linkcraft"]
        assert [(item["id"], item["path"]) for item in mine] == [
            ("linkcraft:run-a-block", "Examples/Analytics/Run a block.ipynb")
        ]
        base = "/notebooks/lite/"
        folders = vera.get(f"{base}api/contents/Examples/all.json").json()["content"]
        assert [entry["name"] for entry in folders] == ["PlantCraft", "Analytics"]
        inside = vera.get(f"{base}api/contents/Examples/Analytics/all.json").json()["content"]
        assert [entry["name"] for entry in inside] == ["Run a block.ipynb"]
        assert vera.get(f"{base}files/Examples/Analytics/Run a block.ipynb").json() == EXAMPLE
        opened = vera.post(
            "/api/notebooks", json={"kind": "example", "example": "linkcraft:run-a-block"}
        )
        assert opened.status_code == 201 and opened.json()["path"] == mine[0]["path"]


def test_a_notebook_lists_and_runs_an_apps_objects(app, dist, link, monkeypatch, tmp_path):  # noqa: F811
    with TestClient(app):
        _turn_on(app)
        _offer(app)
        vera = _login(app, "vera", "vera-strong-password")
        token = vera.post("/api/assistant-access/mine", json={"label": "laptop"}).json()["token"]
        reader = TestClient(app)
        monkeypatch.setattr(pc.Client, "_computer", _routed(reader))
        monkeypatch.setattr(
            pc.Client,
            "download",
            lambda self, path: (
                reader.get(path, headers={"Authorization": f"Bearer {self.token}"}).content
            ),
        )
        monkeypatch.setenv("PLANTCRAFT_RUNTIME_DIR", str(tmp_path / "runtimes"))
        # The runtime goes on sys.path and is kept per session: both put back after the test.
        monkeypatch.setattr(sys, "path", list(sys.path))
        monkeypatch.setattr(sys.modules["plantcraft_notebook.apps"], "_RUNTIMES", {})
        monkeypatch.delitem(sys.modules, "fakelink", raising=False)
        monkeypatch.delitem(sys.modules, "fakelink.notebook", raising=False)
        pc.connect("http://testserver", token=token)

        assert list(pc.apps().index) == ["linkcraft"]
        found = pc.app("Link")
        assert found is not None and pc.app("link").id == found.id == "linkcraft"
        assert list(found.blocks().index) == ["stats.mean"]
        block = found.get("block", "stats.mean")
        assert block["name"] == "Mean"
        ran = block.run(asset="FIC-101", start="-1h")
        assert ran == {
            "kind": "block",
            "id": "stats.mean",
            "app": "linkcraft",
            "options": {"asset": "FIC-101", "start": "-1h"},
        }
        assert (tmp_path / "runtimes").iterdir()
        with pytest.raises(pc.PlantCraftError):
            pc.app("nowhere")
        with pytest.raises(pc.PlantCraftError):
            found.list("model")


def test_a_notebook_asks_an_app_to_run_an_object_and_only_that(app, dist, link, monkeypatch):  # noqa: F811
    asked: list[httpx.Request] = []

    def models(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        if request.method == "POST" and request.url.path == "/model/api/objects/model/run":
            body = json.loads(request.content)
            return httpx.Response(
                201,
                json={
                    "format": "plantcraft-objects/1",
                    "kind": "model",
                    "id": body["id"],
                    "started": {"kind": "run", "id": "r-1"},
                },
            )
        return link(request)

    monkeypatch.setenv("PLANTCRAFT_APPS", "linkcraft=/link/,modelcraft=/model/")
    monkeypatch.setenv(
        "PLANTCRAFT_OPS_URLS",
        "linkcraft=http://linkcraft:8140/link,modelcraft=http://modelcraft:8130/model",
    )
    monkeypatch.setattr(proxy, "transport", lambda: httpx.MockTransport(models))
    with TestClient(app):
        _turn_on(app)
        _offer(app)
        app.state.runtime.contributions.put(
            "modelcraft",
            ContributionsIn.model_validate(
                {
                    "contributes": {
                        "objects": [
                            {"kind": "model", "title": "Models", "run": "app"},
                            {"kind": "run", "title": "Runs"},
                        ]
                    }
                }
            ),
        )
        vera = _login(app, "vera", "vera-strong-password")
        token = vera.post("/api/assistant-access/mine", json={"label": "laptop"}).json()["token"]
        reader = TestClient(app, headers={"Authorization": f"Bearer {token}"})
        started = reader.post(
            "/api/v1/apps/modelcraft/objects/model/run",
            json={"id": "tank/Tank", "options": {"stop": 100}},
        )
        assert started.status_code == 201, started.text
        assert started.json()["started"] == {"kind": "run", "id": "r-1"}
        sent = json.loads(asked[-1].content)
        assert sent == {"id": "tank/Tank", "options": {"stop": 100}}
        assert token not in asked[-1].headers["authorization"]
        # Only a kind the app runs itself; the token still writes nothing else.
        for path in (
            "/api/v1/apps/modelcraft/objects/run/run",
            "/api/v1/apps/linkcraft/objects/block/run",
        ):
            assert reader.post(path, json={"id": "x"}).status_code == 404
        assert reader.post("/api/v1/events", json={"kind": "x"}).status_code == 403
        huge = {"id": "tank/Tank", "options": {"text": "x" * 20000}}
        assert (
            reader.post("/api/v1/apps/modelcraft/objects/model/run", json=huge).status_code == 413
        )
        audit = app.state.runtime.workspace.audit.list(limit=20)
        assert any(row["action"] == "notebooks.app_run" for row in audit)
