"""E2E fixtures: FakePlantCraft and PlantCraft Alarms served over HTTP, and a headless Chromium
(``plantcraft_sdk.e2e``: the fake in a forked server, Alarms in a uvicorn thread with the built
interface, the browser signed in with PlantCraft's cookie). ``ALARMCRAFT_E2E_REQUIRED=1`` makes a
missing tool a failure; ``ALARMCRAFT_E2E_SCREENSHOTS`` names a folder for screenshots.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from plantcraft_sdk import e2e
from plantcraft_sdk.auth import TokenVerifier
from plantcraft_sdk.client import PlantCraftClient
from plantcraft_sdk.contract import TOKEN_COOKIE

from alarmcraft import APP_ID
from alarmcraft.api.app import create_app, ui_folder
from alarmcraft.api.runtime import Runtime
from alarmcraft.config import Settings
from tests.plant import APP_KEY, make_fake


def _reported(fake, number: int, kind: str, minutes_ago: int, **payload) -> dict:
    """An event as Link publishes it, already in PlantCraft when Alarms starts."""

    return {
        "id": number,
        "at": (fake.now - timedelta(minutes=minutes_ago)).isoformat(),
        "app": "linkcraft",
        "kind": kind,
        "subject": "asset:FIC-1001",
        "actor": "app:linkcraft",
        "summary": f"FIC-1001 {payload.get('severity', 'run')}",
        "severity": payload.get("severity", "info"),
        "refs": ["asset:FIC-1001"],
        "payload": {"schedule_id": "unit-100-health", "owner": "user:engineer", **payload},
    }


@pytest.fixture(scope="session")
def fake():
    found = make_fake()
    # What Link reported in the last hour: Events shows it, a rule can start from it.
    for number, minutes in enumerate((50, 30, 10), start=1):
        found.links.events.append(
            _reported(found, number, "linkcraft.run.failed", minutes, severity="critical")
        )
    # What Link declares (its app.toml catalog): the Catalog page lists it, a rule starts from it.
    found.declare_events(
        {
            "app": {"id": "linkcraft"},
            "publishes": {
                "events": [
                    {
                        "name": "schedule.stalled",
                        "title": "Schedule stalled",
                        "description": "A schedule has not run for twice its interval.",
                        "category": "run",
                        "phase": "interval",
                        "rule": {"when": "open", "minutes": 30, "priority": "high"},
                    }
                ]
            },
        }
    )
    return found


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
                data_dir=tmp_path_factory.mktemp("e2e"),
                monitor=False,
            ),
            verifier=TokenVerifier(processcraft_url, APP_ID, http_client=http),
            service_client=PlantCraftClient(
                processcraft_url, app=APP_ID, key=APP_KEY, http_client=http
            ),
            http_client=http,
            clock=lambda: fake.now,
        )
        runtime.start()
        try:
            with e2e.serving(create_app(runtime), "PlantCraft Alarms") as url:
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
