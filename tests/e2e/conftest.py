"""Browser journeys: the real UI (frontend/dist) against a real API on a free port.

They need Playwright with Chromium and a built frontend (``npm run build``);
otherwise they are skipped. CI runs them in the ``e2e`` job.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from pathlib import Path

import pytest

# The suite's guided tour opens on a first visit and would cover the page; journeys switch it
# off (@plantcraft/ui reads this key), and the tour has a journey of its own.
TOURS_OFF = "try { localStorage.setItem('plantcraft-ui:tours-off', '1') } catch (error) {}"


ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "frontend" / "dist" / "index.html"

playwright_api = pytest.importorskip("playwright.sync_api")
ADMIN_PASSWORD = "e2e-admin-secret"
# The application the server runs, for a test that drives its runtime (the suite watch's tick).
APP = None


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def server(tmp_path_factory):
    if not DIST.exists():
        pytest.skip("frontend/dist missing: run npm run build in frontend/")
    import uvicorn

    tmp = tmp_path_factory.mktemp("e2e")
    scenario = json.loads((ROOT / "scenarios" / "generic_demo.json").read_text())
    scenario["storage"]["sqlite_path"] = str(tmp / "workspace.sqlite3")
    scenario["source"]["path"] = str(ROOT / scenario["source"]["path"])
    path = tmp / "scenario.json"
    path.write_text(json.dumps(scenario))
    saved = dict(os.environ)
    secret = tmp / "admin-password"
    secret.write_text(ADMIN_PASSWORD)
    os.environ.update(
        PLANTCRAFT_SCENARIO=str(path),
        PLANTCRAFT_PREWARM_HISTORY="false",
        # Sign-in on, as in a real installation; the environment's administrator signs in.
        PLANTCRAFT_BASIC_AUTH_ENABLED="true",
        PLANTCRAFT_BASIC_AUTH_USERNAME="admin",
        PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE=str(secret),
        # Analytics installed beside PlantCraft: the launcher must show it.
        PLANTCRAFT_APPS="linkcraft=/link/@0.1.0",
    )
    _fake_installer(tmp)
    from plantcraft.api.app import create_app

    port = _free_port()
    app = create_app()
    global APP
    APP = app
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    instance = uvicorn.Server(config)
    thread = threading.Thread(target=instance.run, daemon=True)
    thread.start()
    deadline = time.time() + 60
    while not instance.started and time.time() < deadline:
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    instance.should_exit = True
    thread.join(timeout=10)
    os.environ.clear()
    os.environ.update(saved)


def _fake_installer(tmp: Path) -> None:
    """The installer service with a fake Docker CLI, in a thread: the Apps page works end to end."""

    import sys

    from plantcraft.apps import installer
    from tests import app_packages

    key, trusted = app_packages.publisher(tmp / "publisher", "e2e-publisher")
    install_dir, requests = tmp / "install", tmp / "app-requests"
    install_dir.mkdir()
    (install_dir / "compose.yaml").write_text("services: {}\n")
    docker = tmp / "bin" / "docker"
    docker.parent.mkdir()
    fake = ROOT / "tests" / "fake_docker.py"
    docker.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{fake}" "$@"\n')
    docker.chmod(0o755)
    os.environ.update(
        PLANTCRAFT_TRUSTED_PUBLISHERS=str(trusted),
        PLANTCRAFT_APP_REQUESTS=str(requests),
        PLANTCRAFT_INSTALLER_STATE=str(install_dir / "data" / "installer"),
        FAKE_DOCKER_DIR=str(tmp / "docker"),
        E2E_PUBLISHER_KEY=str(key),
    )
    service = installer.Installer(
        install_dir,
        requests_dir=requests,
        trusted_dir=trusted,
        helper_image="processcraft-installer:e2e",
        docker=installer.Docker(str(docker)),
        project="pc-e2e",
    )

    def loop() -> None:
        while True:
            service.heartbeat()
            service.process_pending()
            time.sleep(0.5)

    threading.Thread(target=loop, name="fake-installer", daemon=True).start()


# Module scope: Playwright's sync API keeps an event loop running while open,
# which would break asyncio.run() in the tests collected after this package.
@pytest.fixture(scope="module")
def browser():
    executable = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or None
    with playwright_api.sync_playwright() as runner:
        try:
            instance = runner.chromium.launch(executable_path=executable)
        except Exception as exc:  # No browser installed: nothing to drive.
            pytest.skip(f"Chromium unavailable: {exc}")
        yield instance
        instance.close()


def _open_page(browser, server, locale, tours=False):
    context = browser.new_context(
        base_url=server, viewport={"width": 1440, "height": 900}, locale=locale
    )
    if not tours:
        context.add_init_script(TOURS_OFF)
    page = context.new_page()
    errors: list[str] = []
    outside: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    # Offline by default: the interface never fetches anything beyond its own server.
    page.on(
        "request",
        lambda request: (
            None
            if request.url.startswith((server, "data:", "blob:"))
            else outside.append(request.url)
        ),
    )
    return context, page, errors, outside


def _sign_in(context) -> None:
    response = context.request.post(
        "/api/login", data={"username": "admin", "password": ADMIN_PASSWORD}
    )
    assert response.ok, response.text()


@pytest.fixture()
def runtime(server):
    """The server's runtime, for a test that drives it (the suite watch's tick)."""

    return APP.state.runtime


@pytest.fixture()
def page(browser, server):
    """Signed in as the administrator, in English (``test_offline_english.py`` checks Portuguese)."""

    context, page, errors, outside = _open_page(browser, server, "en-US")
    _sign_in(context)
    yield page
    context.close()
    assert not errors, f"JavaScript errors on the page: {errors}"
    assert not outside, f"Requests outside the server: {outside}"


@pytest.fixture()
def signed_out_page(browser, server):
    """A fresh browser with no session: the sign-in screen."""

    context, page, errors, outside = _open_page(browser, server, "en-US")
    yield page
    context.close()
    assert not errors, f"JavaScript errors on the page: {errors}"
    assert not outside, f"Requests outside the server: {outside}"


@pytest.fixture()
def first_visit_page(browser, server):
    """Signed in as the administrator, with the guided tour as a first visitor gets it."""

    context, page, errors, outside = _open_page(browser, server, "en-US", tours=True)
    _sign_in(context)
    yield page
    context.close()
    assert not errors, f"JavaScript errors on the page: {errors}"
    assert not outside, f"Requests outside the server: {outside}"
