"""The apps' first steps for a new plant (``[[contributes.start]]``, owner 2026-10-27, review D5,
F4): once an import is applied, Assets › Import lists the steps the installed apps declare, and
taking one sends the app what the import wrote, as the administrator who takes it. Against a fake
Analytics inside the suite's network; the steps themselves are tested in each app."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from plantcraft_sdk.contributes import ContributionsIn
from processcraft.api import app_proxy as proxy
from processcraft.api.app import create_app
from tests.test_collaboration import _scenario
from tests.test_plant_draft import TAGS

STEP = {
    "id": "analyze-loops",
    "title": "Monitor the loops",
    "description": "Reads the loops the import wrote and queues their first round.",
    "open": "/link/loops",
}


class Analytics:
    def __init__(self) -> None:
        self.asked: list[httpx.Request] = []
        self.status = 200

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        if request.url.path != "/link/api/start/analyze-loops":
            return httpx.Response(404, json={"detail": "Not found."})
        if self.status != 200:
            return httpx.Response(self.status, json={"detail": "Only editors monitor loops."})
        loops = [item for item in json.loads(request.content)["assets"] if item["kind"] == "loop"]
        return httpx.Response(
            200,
            json={"summary": f"{len(loops)} loops monitored.", "counts": {"loops": len(loops)}},
        )


@pytest.fixture
def suite(tmp_path, monkeypatch):
    _scenario(tmp_path, monkeypatch)
    monkeypatch.setenv("PLANTCRAFT_APPS", "linkcraft=/link/")
    monkeypatch.setenv("PLANTCRAFT_OPS_URLS", "linkcraft=http://linkcraft:8140/link")
    secret = tmp_path / "secret"
    secret.write_text("admin-secret")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_ENABLED", "true")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_USERNAME", "admin")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE", str(secret))
    analytics = Analytics()
    monkeypatch.setattr(proxy, "transport", lambda: httpx.MockTransport(analytics))
    with TestClient(create_app()) as client:
        login = client.post("/api/login", json={"username": "admin", "password": "admin-secret"})
        assert login.status_code == 200
        client.app.state.runtime.contributions.put(
            "linkcraft", ContributionsIn.model_validate({"contributes": {"start": [STEP]}})
        )
        client.analytics = analytics  # type: ignore[attr-defined]
        yield client


def _import(client: TestClient) -> dict:
    review = client.post(
        "/api/asset-file/draft", json={"tags": TAGS, "file": "browse", "documents": False}
    ).json()
    applied = client.post("/api/asset-file/apply", json=review)
    assert applied.status_code == 200 and applied.json()["applied"], applied.text
    return applied.json()


def test_the_steps_are_offered_after_an_import_and_sent_as_the_person(suite):
    assert suite.get("/api/asset-file/start").json()["steps"] == []
    assert suite.post("/api/asset-file/start/linkcraft/analyze-loops").status_code == 409
    _import(suite)
    listed = suite.get("/api/asset-file/start").json()
    [step] = listed["steps"]
    assert step["app"] == "linkcraft" and step["default"] and step["open"] == "/link/loops"
    assert listed["import"]["summary"]["created"] > 0

    done = suite.post("/api/asset-file/start/linkcraft/analyze-loops")
    assert done.status_code == 200, done.text
    assert done.json() == {"summary": "50 loops monitored.", "counts": {"loops": 50}, "open": None}
    [asked] = suite.analytics.asked
    body = json.loads(asked.content)
    assert asked.headers["authorization"].startswith("Bearer ")
    assert {item["role"] for item in body["signals"]} >= {"pv", "sp", "op"}
    # The rules' draft has no units: its top assets are the groups the steps work by.
    kinds = {item["id"]: item["kind"] for item in body["assets"]}
    assert body["units"] and all(kinds[unit] for unit in body["units"])

    # Only declared steps of installed apps; the app's refusal comes back in its words.
    assert suite.post("/api/asset-file/start/linkcraft/delete-all").status_code == 404
    assert suite.post("/api/asset-file/start/histcraft/collect-signals").status_code == 404
    suite.analytics.status = 403
    refused = suite.post("/api/asset-file/start/linkcraft/analyze-loops")
    assert refused.status_code == 403 and refused.json()["detail"] == "Only editors monitor loops."

    # After an undo there is nothing to start from.
    assert suite.post("/api/asset-file/undo").status_code == 200
    assert suite.get("/api/asset-file/start").json()["steps"] == []


def test_only_administrators_take_the_steps(suite):
    _import(suite)
    suite.post("/api/logout")
    assert suite.get("/api/asset-file/start").status_code in (401, 403)
    assert suite.post("/api/asset-file/start/linkcraft/analyze-loops").status_code in (401, 403)
