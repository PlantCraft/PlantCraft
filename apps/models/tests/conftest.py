"""Shared fixtures: the fake PlantCraft of ``tests/plant.py``, the fake Modelica runner of
``tests/fake_runner.py`` and a PlantCraft Models wired to both."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from plantcraft_sdk.testing import BASE_URL

from modelcraft.api.app import create_app
from modelcraft.api.runtime import Runtime
from modelcraft.config import Settings
from tests.fake_runner import FakeExecutor
from tests.plant import APP_KEY, make_fake


def make_runtime(tmp_path, fake, *, app_key: bool = True, executor=None, **settings) -> Runtime:
    # The example study queues runs at start; the tests that count runs start without it.
    settings.setdefault("example_study", False)
    runtime = Runtime(
        Settings(processcraft_url=BASE_URL, data_dir=tmp_path, **settings),
        verifier=fake.verifier("modelcraft"),
        service_client=fake.client(None, app="modelcraft", key=APP_KEY) if app_key else None,
        http_client=fake.http_client(),
        executor=executor or FakeExecutor(tmp_path / "fake-runner"),
    )
    runtime.workbench.ensure_library(wait=True)
    return runtime


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
        create_app(runtime), base_url="http://testserver/model/", raise_server_exceptions=False
    )
    if username:
        client.headers["Authorization"] = f"Bearer {fake.token(username)}"
    return client


@pytest.fixture
def client(runtime, fake):
    with client_for(runtime, fake) as test_client:
        yield test_client


def example(client) -> dict:
    """The "Examples" project the server seeds at its first start."""

    return next(p for p in client.get("/api/projects").json() if p["name"] == "Examples")


def editable_example(client, name: str = "My examples") -> dict:
    """A copy of the examples a test may change (the examples themselves are read-only)."""

    return client.post(
        f"/api/projects/{example(client)['id']}/duplicate", json={"name": name}
    ).json()


def wait_for(client, run_id: str, seconds: float = 10) -> dict:
    deadline = time.monotonic() + seconds
    while True:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in ("done", "failed") or time.monotonic() > deadline:
            return run
        time.sleep(0.02)


TLC = "PlantCraftExamples.TankLevelControl"
TLC_FILE = "PlantCraftExamples/TankLevelControl.mo"


def pytest_sessionfinish(session, exitstatus):
    """The app's token used only what app.toml [permissions] declares (PlantCraft answers 403)."""

    from pathlib import Path

    from plantcraft_sdk import apptest

    problems = apptest.permission_problems(Path(__file__).resolve().parents[1], "modelcraft")
    if problems and exitstatus == 0:
        print("\n" + "\n".join(problems))
        session.exitstatus = 1
