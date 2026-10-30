"""Time zones: picked from a list with Local time and UTC first, the
installation's zone in Setup › Installation, and each person's choice in Preferences."""

from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import expect

SHOTS = os.environ.get("PLANTCRAFT_E2E_SHOTS", "")


def _shot(page, name: str) -> None:
    if SHOTS:
        page.screenshot(path=str(Path(SHOTS) / name), full_page=True)


def test_the_installation_zone_is_picked_from_a_list(page):
    page.goto("/setup/installation")
    picker = page.get_by_role("combobox", name="Time zone")
    expect(picker).to_be_visible()
    try:
        picker.select_option("America/Sao_Paulo")
        page.get_by_role("button", name="Save").click()
        expect(page.get_by_role("status")).to_contain_text("Saved")
        expect(page.get_by_text("Now at the plant")).to_contain_text("UTC−3")
        _shot(page, "setup-installation.png")
        assert page.request.get("/api/v1/installation").json()["time_zone"] == "America/Sao_Paulo"
        # The backups' schedule offers Local time first, now named after the plant.
        page.goto("/backups")
        zone = page.locator("#ops-schedule").get_by_role("combobox", name="Time zone")
        expect(zone.locator("option").first).to_have_text("Local time · São Paulo (UTC−3)")
        expect(zone.locator("option").nth(1)).to_have_text("UTC")
        expect(zone).to_have_value("local")
        _shot(page, "backups-schedule.png")
    finally:
        page.request.put("/api/setup/installation", data={"time_zone": "UTC"})


def test_preferences_choose_where_times_are_shown(page):
    page.goto("/admin")
    page.locator(".pcs-profile").click()
    page.get_by_role("menuitem", name="Preferences").click()
    expect(page.get_by_role("heading", name="Preferences", level=1)).to_be_visible()
    choices = page.get_by_role("radiogroup", name="Times")
    expect(choices.get_by_role("radio").first).to_be_checked()
    _shot(page, "preferences.png")
    try:
        choices.get_by_text("UTC", exact=True).click()
        with page.expect_navigation():
            page.get_by_role("button", name="Save").click()
        assert page.request.get("/api/me/preferences").json()["time_zone"] == "utc"
        # Read the browser's storage on a page of the same origin without the app's script, which
        # may reload once more to follow the saved choice (and would end the evaluation).
        page.goto("/api/me/preferences")
        assert page.evaluate("localStorage.getItem('processcraft.timeZoneMode')") == "utc"
    finally:
        page.request.put("/api/me/preferences", data={"time_zone": "plant", "language": "en"})
        page.goto("/api/me/preferences")
        page.evaluate("localStorage.removeItem('processcraft.timeZoneMode')")
