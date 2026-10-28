"""The main journey in a real browser: sign-in, then a note written, opened and deleted."""

from __future__ import annotations

import os
import re

import pytest

try:
    from playwright.sync_api import expect
except ImportError:
    if os.environ.get("STARTER_E2E_REQUIRED") == "1":
        raise
    pytest.skip("Playwright is not installed", allow_module_level=True)


def _shot(page, screenshots, name):
    if screenshots:
        page.wait_for_timeout(800)
        page.screenshot(path=str(screenshots / f"{name}.png"), full_page=True)


def test_a_browser_without_a_token_is_sent_to_sign_in(anonymous, app_url):
    anonymous.goto(f"{app_url}/starter/")
    assert re.search(r"/login\?next=/starter/", anonymous.url), anonymous.url


def test_write_a_note_open_it_and_delete_it(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/starter/")
    expect(page.get_by_text("No notes yet")).to_be_visible()
    _shot(page, screenshots, "1-empty")

    page.get_by_label("Asset").fill("FIC-1001")
    page.get_by_label("Note", exact=True).fill("Valve sticks below 20 % opening.")
    page.get_by_role("button", name="Save note").click()
    row = page.get_by_role("row", name=re.compile("Valve sticks"))
    expect(row).to_be_visible()
    _shot(page, screenshots, "2-a-note")

    page.get_by_role("link", name=re.compile("Valve sticks")).click()
    expect(page.get_by_text("Valve sticks below 20 % opening.")).to_be_visible()
    page.get_by_role("button", name="Delete").click()
    expect(page.get_by_text("No notes yet")).to_be_visible()
