"""The main journey in a real browser: sign-in, the plant map, the drawings and one sheet."""

from __future__ import annotations

import os
import re

import pytest

try:
    from playwright.sync_api import expect
except ImportError:
    if os.environ.get("PIDCRAFT_E2E_REQUIRED") == "1":
        raise
    pytest.skip("Playwright is not installed", allow_module_level=True)


def _shot(page, screenshots, name):
    if screenshots:
        page.wait_for_timeout(800)
        page.screenshot(path=str(screenshots / f"{name}.png"), full_page=True)


def test_a_browser_without_a_token_is_sent_to_sign_in(anonymous, app_url):
    anonymous.goto(f"{app_url}/pid/")
    assert re.search(r"/login\?next=/pid/", anonymous.url), anonymous.url


def test_the_plant_map_the_drawings_and_a_sheet(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/pid/")
    expect(page.get_by_role("heading", name="Plant map")).to_be_visible()
    _shot(page, screenshots, "1-plant-map")
    page.goto(f"{app_url}/pid/drawings")
    expect(page.get_by_role("button", name="Send drawings")).to_be_visible()
    expect(page.get_by_text("PID-U-100-01").first).to_be_visible()
    _shot(page, screenshots, "2-drawings")
    page.get_by_text("PID-U-100-01").first.click()
    page.get_by_role("link", name="PID-U-100-01").first.click()
    expect(page.get_by_text("Found on this page")).to_be_visible()
    _shot(page, screenshots, "3-sheet")
