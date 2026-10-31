"""Shared fixtures: a FakePlantCraft with known-fault loops and a Analytics wired to it."""

from __future__ import annotations

import logging
import os

import pytest
from fastapi.testclient import TestClient
from plantcraft_sdk.testing import BASE_URL

from linkcraft.api.app import create_app
from linkcraft.api.runtime import Runtime
from linkcraft.config import AnalysisConfig, Settings
from linkcraft.engine.compute import ComputePool
from tests.plant import HOURS, SAMPLE_SECONDS, make_fake

# Site blocks' code runs checked but in the test's process (tests/test_site_blocks.py starts
# real block workers where it means to).
os.environ.setdefault("LINKCRAFT_BLOCK_SANDBOX", "inline")


@pytest.fixture(autouse=True)
def _logging_as_it_was():
    """A test that runs the CLI configures the suite's JSON logging on the root logger; it must
    not stay for the tests after it (every request would be formatted and redacted twice)."""

    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    for handler in list(root.handlers):
        if handler not in handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level)


def make_runtime(
    tmp_path, fake, *, app_key: bool = True, analysis: AnalysisConfig | None = None
) -> Runtime:
    settings = Settings(
        processcraft_url=BASE_URL,
        data_dir=tmp_path,
        scheduler_enabled=False,
        analysis=analysis
        or AnalysisConfig(window_minutes=HOURS * 60, resample_seconds=SAMPLE_SECONDS),
    )
    return Runtime(
        settings,
        verifier=fake.verifier("linkcraft"),
        service_client=fake.client(None, app="linkcraft", key="test-app-key") if app_key else None,
        http_client=fake.http_client(),
        compute=ComputePool(0),
    )


@pytest.fixture
def fake():
    return make_fake()


@pytest.fixture
def runtime(tmp_path, fake):
    rt = make_runtime(tmp_path, fake)
    yield rt
    rt.shutdown()


def client_for(runtime: Runtime, fake, username: str = "engineer") -> TestClient:
    client = TestClient(create_app(runtime), raise_server_exceptions=False)
    client.headers["Authorization"] = f"Bearer {fake.token(username)}"
    return client


@pytest.fixture
def client(runtime, fake):
    with client_for(runtime, fake) as test_client:
        yield test_client


@pytest.fixture
def analysed(runtime):
    """A runtime whose loops were synced and analysed once."""

    runtime.run_round()
    return runtime


# Signal quality (the checks that came from DataCraft) ---------------------------------------


def make_signal_runtime(tmp_path, fake, *, app_key: bool = True, processes: int = 0) -> Runtime:
    """Analytics on the signal plant (``tests/signal_plant.py``), its window the plant's."""

    from tests.signal_plant import APP_KEY
    from tests.signal_plant import HOURS as SIGNAL_HOURS

    settings = Settings(
        processcraft_url=BASE_URL,
        data_dir=tmp_path,
        scheduler_enabled=False,
        signal_window_hours=SIGNAL_HOURS,
    )
    return Runtime(
        settings,
        verifier=fake.verifier("linkcraft"),
        service_client=fake.client(None, app="linkcraft", key=APP_KEY) if app_key else None,
        http_client=fake.http_client(),
        compute=ComputePool(processes),
    )


@pytest.fixture
def sq_fake():
    from tests.signal_plant import make_signal_fake

    return make_signal_fake()


@pytest.fixture
def sq_runtime(tmp_path, sq_fake):
    rt = make_signal_runtime(tmp_path, sq_fake)
    yield rt
    rt.shutdown()


@pytest.fixture
def sq_client(sq_runtime, sq_fake):
    with client_for(sq_runtime, sq_fake) as test_client:
        yield test_client


@pytest.fixture
def checked(sq_runtime):
    """A runtime whose signals were synced and checked once by the Signal quality protocol."""

    result = sq_runtime.run_signal_quality("manual")
    assert result["status"] == "ok", result
    return sq_runtime


def pytest_sessionfinish(session, exitstatus):
    """The app's token used only what app.toml [permissions] declares (PlantCraft answers 403)."""

    from pathlib import Path

    from plantcraft_sdk import apptest

    problems = apptest.permission_problems(Path(__file__).resolve().parents[1], "linkcraft")
    if problems and exitstatus == 0:
        print("\n" + "\n".join(problems))
        session.exitstatus = 1
