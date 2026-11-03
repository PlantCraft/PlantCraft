"""The View guided tour on a phone: Next can be tapped on every step, to the end, and no page it
opens is wider than the screen (``plantcraft_sdk.e2e.walk_tour``)."""

import os

import pytest
from plantcraft_sdk import e2e
from plantcraft_sdk.contract import TOKEN_COOKIE

try:
    from playwright.sync_api import expect
except ImportError:
    if os.environ.get("DASHCRAFT_E2E_REQUIRED") == "1":
        raise
    pytest.skip("Playwright is not installed", allow_module_level=True)


def test_the_tour_goes_to_the_end_on_a_phone(browser, fake, app_url):
    cookie = {"name": TOKEN_COOKIE, "value": fake.token("engineer"), "url": app_url}
    with e2e.page(browser, [cookie], phone=True, tours=True) as page:
        page.goto(f"{app_url}/dash/")
        welcome = page.get_by_role("dialog").get_by_role("heading", name="Welcome to View")
        expect(welcome).to_be_visible()
        assert e2e.walk_tour(page) > 3
