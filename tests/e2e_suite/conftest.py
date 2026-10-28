"""Journeys across the whole suite, on a live installation with the demo story.

They run against an installation made with ``deploy/install.sh --public-demo`` (or any install
after ``processcraft demo seed``), never in GitHub CI: run them locally or on the Mac mini runner
with ``make e2e-suite SUITE_URL=https://host/``. Without ``PLANTCRAFT_SUITE_URL`` they are
skipped.

- ``PLANTCRAFT_SUITE_URL``: the installation's address (``https://processcraft.company.local/``).
- The visitor enters with the sign-in page's "Enter the demo": a read-only demo visit.
- ``PLANTCRAFT_SUITE_CHROMIUM``: a Chromium binary, when Playwright's own is not installed.
- ``PLANTCRAFT_SUITE_STRICT_TLS=1``: check the certificate (an install's local CA is otherwise
  accepted without being installed in the test browser).
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

import pytest

URL = os.environ.get("PLANTCRAFT_SUITE_URL", "").rstrip("/")

if not URL:
    pytest.skip("PLANTCRAFT_SUITE_URL is not set: no installation to walk", allow_module_level=True)

playwright_api = pytest.importorskip("playwright.sync_api")


class Watch:
    """What the browser saw: console errors, failed answers and hosts other than the suite's."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.failed: list[str] = []
        self.outside: list[str] = []
        self.forbidden: list[str] = []

    def attach(self, page) -> None:
        host = urlsplit(URL).netloc
        page.on(
            "console", lambda m: self.errors.append(m.text[:300]) if m.type == "error" else None
        )
        page.on("pageerror", lambda e: self.errors.append(str(e)[:300]))

        def answered(response) -> None:
            # 403 is an answer the journeys provoke on purpose (read-only visitor).
            if response.status == 403:
                self.forbidden.append(response.url)
            elif response.status >= 400:
                self.failed.append(f"{response.status} {response.url}")

        page.on("response", answered)

        def requested(request) -> None:
            netloc = urlsplit(request.url).netloc
            if request.url.startswith(("http:", "https:", "ws:", "wss:")) and netloc != host:
                self.outside.append(request.url)

        page.on("request", requested)


@pytest.fixture(scope="session")
def browser():
    with playwright_api.sync_playwright() as playwright:
        options = {"args": ["--no-proxy-server"]}
        if os.environ.get("PLANTCRAFT_SUITE_CHROMIUM"):
            options["executable_path"] = os.environ["PLANTCRAFT_SUITE_CHROMIUM"]
        browser = playwright.chromium.launch(**options)
        yield browser
        browser.close()


def _context(browser):
    return browser.new_context(
        ignore_https_errors=os.environ.get("PLANTCRAFT_SUITE_STRICT_TLS") != "1",
        viewport={"width": 1440, "height": 1000},
        locale="en-US",
    )


@pytest.fixture(scope="session")
def watch():
    return Watch()


@pytest.fixture(scope="session")
def visitor(browser, watch):
    """One signed-in visitor page for every journey, as a first visitor walks the demo."""

    context = _context(browser)
    page = context.new_page()
    page.set_default_timeout(20_000)
    watch.attach(page)
    yield page
    context.close()


@pytest.fixture()
def anonymous(browser):
    context = _context(browser)
    page = context.new_page()
    page.set_default_timeout(20_000)
    yield page
    context.close()


def go(page, path: str) -> None:
    page.goto(URL + path)
    page.wait_for_load_state("networkidle")


def app(page):
    """The app drawn beside the platform's sidebar: its visible iframe (ui 0.39 frame)."""
    return page.frame_locator("iframe[data-pc-frame]:not([hidden])")
