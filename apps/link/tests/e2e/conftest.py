"""E2E fixtures: FakePlantCraft and PlantCraft Analytics served over HTTP, and a headless Chromium
(``plantcraft_sdk.e2e``: the fake in a forked server, Link in a uvicorn thread with the built
interface, the browser signed in with PlantCraft's cookie). The fake serves the known-fault
loops of ``tests/plant.py`` as PlantCraft's asset catalog, with loop types and one incomplete
record. ``LINKCRAFT_E2E_REQUIRED=1`` makes a missing tool a failure;
``LINKCRAFT_E2E_SCREENSHOTS`` names a folder for screenshots.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from plantcraft_sdk import e2e
from plantcraft_sdk.auth import TokenVerifier
from plantcraft_sdk.client import PlantCraftClient
from plantcraft_sdk.contract import TOKEN_COOKIE

from linkcraft import APP_ID
from linkcraft.api.app import create_app, ui_folder
from linkcraft.api.runtime import Runtime
from linkcraft.config import AnalysisConfig, Settings
from linkcraft.engine.compute import ComputePool
from tests.plant import HOURS, SAMPLE_SECONDS, make_fake


@pytest.fixture(scope="session")
def fake():
    return make_fake(catalog=True)


@pytest.fixture(scope="session")
def app_url(fake, tmp_path_factory):
    if ui_folder() is None:
        e2e.unavailable(
            APP_ID, "The interface is not built: run `npm ci && npm run build` in frontend/"
        )
    with e2e.served(fake.app) as processcraft_url:
        http = httpx.Client(timeout=30)
        runtime = Runtime(
            Settings(
                processcraft_url=processcraft_url,
                data_dir=tmp_path_factory.mktemp("link-e2e"),
                scheduler_enabled=False,
                analysis=AnalysisConfig(window_minutes=HOURS * 60, resample_seconds=SAMPLE_SECONDS),
                # The recorded plant is HOURS long: the Signal quality window is the same.
                signal_window_hours=HOURS,
            ),
            verifier=TokenVerifier(processcraft_url, APP_ID, http_client=http),
            service_client=PlantCraftClient(
                processcraft_url, app=APP_ID, key="test-app-key", http_client=http
            ),
            http_client=http,
            compute=ComputePool(0),
        )
        runtime.run_signal_quality()
        runtime.run_round()
        # One run a person asked for: the Runs tab opens a kept run (round 9, D22).
        manual = runtime.jobs.create_job(
            loop_id="fic-101",
            name="Try",
            kind="manual",
            profile_id="flow_loop",
            method_config={"profile_id": "flow_loop"},
            created_by="engineer",
        )
        runtime.monitor.execute_job(manual)
        runtime.engine.sampler.sample()  # the queue's panel has a first point
        try:
            with e2e.serving(create_app(runtime), "PlantCraft Analytics") as url:
                yield url
        finally:
            http.close()


@pytest.fixture(scope="session")
def browser():
    with e2e.chromium(APP_ID) as instance:
        yield instance


@pytest.fixture
def page(browser):
    with e2e.page(browser) as opened:
        yield opened


@pytest.fixture
def signed_in(browser, fake, app_url):
    """A page whose browser holds a PlantCraft token for an editor."""

    cookie = {"name": TOKEN_COOKIE, "value": fake.token("engineer"), "url": app_url}
    with e2e.page(browser, [cookie]) as opened:
        yield opened


@pytest.fixture(scope="session")
def screenshots() -> Path | None:
    return e2e.screenshots(APP_ID)
