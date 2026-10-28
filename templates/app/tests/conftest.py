"""Shared fixtures: the fake PlantCraft of ``tests/plant.py`` and a StarterCraft wired to it."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from plantcraft_sdk.testing import BASE_URL

from starter.api.app import create_app
from starter.api.runtime import Runtime
from starter.config import Settings
from tests.plant import APP_KEY, make_fake


def make_runtime(tmp_path, fake, *, app_key: bool = True, **settings) -> Runtime:
    return Runtime(
        Settings(processcraft_url=BASE_URL, data_dir=tmp_path, **settings),
        verifier=fake.verifier("starter"),
        service_client=fake.client(None, app="starter", key=APP_KEY) if app_key else None,
        http_client=fake.http_client(),
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
        create_app(runtime), base_url="http://testserver/starter/", raise_server_exceptions=False
    )
    if username:
        client.headers["Authorization"] = f"Bearer {fake.token(username)}"
    return client


@pytest.fixture
def client(runtime, fake):
    with client_for(runtime, fake) as test_client:
        yield test_client


def note(**fields) -> dict:
    """A note on FIC-1001, a loop of the test plant."""

    return {"asset_id": "FIC-1001", "text": "Valve sticks below 20 % opening.", **fields}


def pytest_sessionfinish(session, exitstatus):
    """The app's token used only what app.toml [permissions] declares (PlantCraft answers 403)."""

    from pathlib import Path

    from plantcraft_sdk import apptest

    problems = apptest.permission_problems(Path(__file__).resolve().parents[1], "starter")
    if problems and exitstatus == 0:
        print("\n" + "\n".join(problems))
        session.exitstatus = 1
