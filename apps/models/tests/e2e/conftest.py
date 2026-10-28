"""E2E fixtures: FakePlantCraft and PlantCraft Models served over HTTP, and a headless Chromium
(``plantcraft_sdk.e2e``: the fake in a forked server, Models in a uvicorn thread with the built
interface, the browser signed in with PlantCraft's cookie). Jobs go to the fake runner
(``tests/fake_runner.py``), or to a real runner when ``MODELCRAFT_E2E_JOBS`` names the jobs folder
one serves. ``MODELCRAFT_E2E_REQUIRED=1`` makes a missing tool a failure;
``MODELCRAFT_E2E_SCREENSHOTS`` names a folder for screenshots.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest
from plantcraft_sdk import e2e
from plantcraft_sdk.auth import TokenVerifier
from plantcraft_sdk.client import PlantCraftClient
from plantcraft_sdk.contract import TOKEN_COOKIE

from modelcraft import APP_ID
from modelcraft.api.app import create_app, ui_folder
from modelcraft.api.runtime import Runtime
from modelcraft.config import Settings
from modelcraft.omc.jobs import QueueExecutor
from tests.fake_runner import FakeExecutor
from tests.plant import APP_KEY, make_fake


@pytest.fixture(scope="session")
def fake():
    return make_fake()


@pytest.fixture(scope="session")
def app_url(fake, tmp_path_factory):
    if ui_folder() is None:
        e2e.unavailable(
            APP_ID, "The interface is not built: run `npm ci && npm run build` in frontend/"
        )
    jobs = os.environ.get("MODELCRAFT_E2E_JOBS", "").strip()
    executor = (
        QueueExecutor(Path(jobs)) if jobs else FakeExecutor(tmp_path_factory.mktemp("runner"))
    )
    with e2e.served(fake.app) as processcraft_url:
        http = httpx.Client(timeout=30)
        runtime = Runtime(
            Settings(processcraft_url=processcraft_url, data_dir=tmp_path_factory.mktemp("e2e")),
            verifier=TokenVerifier(processcraft_url, APP_ID, http_client=http),
            service_client=PlantCraftClient(
                processcraft_url, app=APP_ID, key=APP_KEY, http_client=http
            ),
            http_client=http,
            executor=executor,
        )
        runtime.workbench.ensure_library(wait=True)
        runtime.start()
        try:
            with e2e.serving(create_app(runtime), "PlantCraft Models") as url:
                yield url
        finally:
            runtime.shutdown()
            http.close()


@pytest.fixture(scope="session")
def browser():
    with e2e.chromium(APP_ID) as instance:
        yield instance


@pytest.fixture
def anonymous(browser):
    with e2e.page(browser) as page:
        yield page


@pytest.fixture
def signed_in(browser, fake, app_url):
    """A page whose browser holds a PlantCraft token for an editor."""

    cookie = {"name": TOKEN_COOKIE, "value": fake.token("engineer"), "url": app_url}
    with e2e.page(browser, [cookie]) as page:
        yield page


@pytest.fixture(scope="session")
def screenshots() -> Path | None:
    return e2e.screenshots(APP_ID)
