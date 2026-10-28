"""The default language is English, and no page reaches beyond the server."""

from __future__ import annotations

import pytest

expect = pytest.importorskip("playwright.sync_api").expect

PAGES = [
    "/",
    "/inbox",
    "/calendar",
    "/todo",
    "/team",
    "/admin",
    "/assets",
    "/asset-types",
    "/data",
    "/asset-import",
    "/health",
    "/backups",
    "/updates",
    "/users",
    "/app-keys",
    "/apps",
    "/help",
]


def test_main_pages_load_in_english_without_outside_requests(page):
    for path in PAGES:
        page.goto(path)
        page.wait_for_load_state("networkidle")
    page.goto("/")
    expect(page.locator("html")).to_have_attribute("lang", "en")


def test_translations_are_off_and_no_language_picker_shows(page):
    # Portuguese is switched off until the interface settles: English everywhere, no picker.
    page.goto("/admin")
    page.locator(".pcs-profile").click()
    expect(page.locator(".pcs-language")).to_have_count(0)
    expect(page.locator("html")).to_have_attribute("lang", "en")
