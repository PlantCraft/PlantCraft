"""Shared fixtures: the fake PlantCraft of ``tests/plant.py`` and a DashCraft wired to it."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from plantcraft_sdk.testing import BASE_URL

from dashcraft.api.app import create_app
from dashcraft.api.runtime import Runtime
from dashcraft.config import Settings
from tests.plant import APP_KEY, make_fake


def make_runtime(tmp_path, fake, *, app_key: bool = True, **settings) -> Runtime:
    # Reports are sent by the tests themselves (``runtime.report_scheduler.tick()``).
    settings.setdefault("report_seconds", 0)
    return Runtime(
        Settings(processcraft_url=BASE_URL, data_dir=tmp_path, **settings),
        verifier=fake.verifier("dashcraft"),
        service_client=fake.client(None, app="dashcraft", key=APP_KEY) if app_key else None,
        http_client=fake.http_client(),
        clock=lambda: fake.now,
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
    client = TestClient(create_app(runtime), raise_server_exceptions=False)
    if username:
        client.headers["Authorization"] = f"Bearer {fake.token(username)}"
    return client


@pytest.fixture
def client(runtime, fake):
    with client_for(runtime, fake) as test_client:
        yield test_client


def kpi(card_id: str = "k1", **item) -> dict:
    return {
        "card_id": card_id,
        "kind": "kpi",
        "items": [item or {"signal_id": "fake:FIC-101.PV"}],
        "agg": "last",
        "window": "1h",
    }


def dashboard(**fields) -> dict:
    return {"name": "Feed", "cards": [kpi()], **fields}


def pytest_sessionfinish(session, exitstatus):
    """The app's token used only what app.toml [permissions] declares (PlantCraft answers 403)."""

    from pathlib import Path

    from plantcraft_sdk import apptest

    problems = apptest.permission_problems(Path(__file__).resolve().parents[1], "dashcraft")
    if problems and exitstatus == 0:
        print("\n" + "\n".join(problems))
        session.exitstatus = 1
