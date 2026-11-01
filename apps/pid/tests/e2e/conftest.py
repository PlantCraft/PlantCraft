"""E2E fixtures: FakePlantCraft and PlantCraft PID served over HTTP, and a headless Chromium
(``plantcraft_sdk.e2e``: the fake in a forked server, the app in a uvicorn thread with the built
interface, the browser signed in with PlantCraft's cookie). ``PIDCRAFT_E2E_REQUIRED=1`` makes a
missing tool a failure; ``PIDCRAFT_E2E_SCREENSHOTS`` names a folder for screenshots.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from plantcraft_sdk import e2e, licensing
from plantcraft_sdk.auth import TokenVerifier
from plantcraft_sdk.client import PlantCraftClient
from plantcraft_sdk.contract import TOKEN_COOKIE

from pidcraft import APP_ID
from pidcraft.api.app import create_app, ui_folder
from pidcraft.api.runtime import Runtime
from pidcraft.config import Settings
from tests.conftest import KEY, licence_body, licence_for
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
    with e2e.served(fake.app) as processcraft_url:
        http = httpx.Client(timeout=30)
        runtime = Runtime(
            Settings(processcraft_url=processcraft_url, data_dir=tmp_path_factory.mktemp("e2e")),
            verifier=TokenVerifier(processcraft_url, APP_ID, http_client=http),
            service_client=PlantCraftClient(
                processcraft_url, app=APP_ID, key=APP_KEY, http_client=http
            ),
            http_client=http,
            licence=licence_for(licensing.issue(KEY, licence_body())),
        )
        runtime.start()
        # Two sheets of the demo plant, read before the browser opens.
        from pidcraft.drawings.models import DrawingFields
        from pidcraft.plantmap.sample.draw import draw_all

        for _, canvas, key in draw_all()[:2]:
            runtime.drawings.add(
                canvas.svg().encode(),
                f"{key['sheet']}.svg",
                DrawingFields(number=key["sheet"], unit="U-100"),
                "engineer",
            )
        runtime.drawings.read_queued()
        try:
            with e2e.serving(create_app(runtime), "PlantCraft PID") as url:
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
