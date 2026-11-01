"""Shared fixtures: the fake PlantCraft of ``tests/plant.py``, a PlantCraft PID wired to it,
and a licence signed by a test publisher key (the real key's private half never leaves the
publisher; ``licence_for`` builds a guard on a key made here)."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from plantcraft_sdk import licensing
from plantcraft_sdk.testing import BASE_URL

from pidcraft.api.app import create_app
from pidcraft.api.runtime import Runtime
from pidcraft.config import Settings
from pidcraft.licence import Licence
from tests.plant import APP_KEY, make_fake

# Drawings are read in this process in the tests (pidcraft.drawings.service).
os.environ.setdefault("PIDCRAFT_READ_SANDBOX", "inline")
KEY = licensing.new_key()


def licence_body(**fields) -> dict:
    return {
        "id": "test-1",
        "app": "pidcraft",
        "publisher": "PlantCraft",
        "customer": "Test plant",
        "installation": "*",
        "issued": "2026-01-01",
        "expires": "2099-12-31",
        **fields,
    }


def licence_for(data: bytes | None) -> Licence:
    """A licence state read from ``data`` (a .pclicense, or None) with the test key."""

    guard = licensing.LicenseGuard(app_id="pidcraft", public_key=KEY.public_key())
    guard.check(data, "test-installation")
    licence = Licence(guard)
    licence.refresh = lambda client: guard.current  # type: ignore[method-assign]
    return licence


def make_runtime(tmp_path, fake, *, app_key: bool = True, licence=None, **settings) -> Runtime:
    """No reader thread: a test reads the queue itself (``index``), so nothing races."""

    return Runtime(
        Settings(processcraft_url=BASE_URL, data_dir=tmp_path, **settings),
        verifier=fake.verifier("pidcraft"),
        service_client=fake.client(None, app="pidcraft", key=APP_KEY) if app_key else None,
        http_client=fake.http_client(),
        licence=licence or licence_for(licensing.issue(KEY, licence_body())),
        background=False,
    )


@pytest.fixture
def fake():
    return make_fake()


@pytest.fixture
def runtime(tmp_path, fake):
    rt = make_runtime(tmp_path, fake)
    yield rt
    rt.shutdown()


def client_for(runtime: Runtime, fake, username: str | None = "engineer") -> TestClient:
    client = TestClient(
        create_app(runtime), base_url="http://testserver/pid/", raise_server_exceptions=False
    )
    if username:
        client.headers["Authorization"] = f"Bearer {fake.token(username)}"
    return client


@pytest.fixture
def client(runtime, fake):
    with client_for(runtime, fake) as test_client:
        yield test_client


def send(client: TestClient, filename: str, data: bytes, **query) -> dict:
    """Send a drawing the way the page does (the body is the file); the answer's drawing."""

    answer = client.post("/api/drawings", params={"filename": filename, **query}, content=data)
    assert answer.status_code == 201, answer.text
    return {**answer.json(), "doc_id": answer.json()["drawing_id"]}


def index(runtime: Runtime) -> int:
    """Read every queued drawing now, as the reader thread would."""

    return runtime.drawings.read_queued()


def pytest_sessionfinish(session, exitstatus):
    """The app's token used only what app.toml [permissions] declares (PlantCraft answers 403)."""

    from pathlib import Path

    from plantcraft_sdk import apptest

    problems = apptest.permission_problems(Path(__file__).resolve().parents[1], "pidcraft")
    if problems and exitstatus == 0:
        print("\n" + "\n".join(problems))
        session.exitstatus = 1
