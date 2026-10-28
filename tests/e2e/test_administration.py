"""Administration (owner, 2026-10-24): Health, Backups and Updates are separate pages, Setup keeps
only the settings done once, and the old addresses land on the new pages."""

from __future__ import annotations

import re

from playwright.sync_api import expect


def test_health_backups_and_updates_are_their_own_pages(page):
    page.goto("/operations")
    expect(page).to_have_url(re.compile(r"/health$"))
    expect(page.get_by_role("heading", level=1, name="System health", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Download diagnostic bundle")).to_be_visible()
    nav = page.locator(".pcs-nav, nav").first
    for name in ("System health", "Backups", "Updates"):
        expect(nav.get_by_role("link", name=name, exact=True)).to_be_visible()
    page.goto("/setup/backups")
    expect(page).to_have_url(re.compile(r"/backups$"))
    expect(page.get_by_role("heading", level=1, name="Backups", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Back up now")).to_be_visible()
    expect(page.get_by_label("Daily backup time")).to_have_value(re.compile(r"\d\d:\d\d"))
    page.goto("/updates")
    expect(page.get_by_role("heading", level=1, name="Updates", exact=True)).to_be_visible()
    page.goto("/setup")
    expect(page.get_by_text("Configuration file")).to_have_count(0)
    expect(page.locator("main").get_by_text("Backups", exact=True)).to_have_count(0)


def test_plantcraft_menu_puts_setup_last_and_the_team_page_is_a_switch(page):
    """Owner, 2026-10-25: Overview, Assets, Health and Preferences on top for everyone, no "Plant"
    heading; administration below, Setup last. Team shows in Desk once Setup › Desk turns it on."""

    page.goto("/admin")
    nav = page.locator("nav.pcs-nav")
    expect(nav.get_by_role("link", name="Settings", exact=True)).to_be_visible()
    names = [name.strip() for name in nav.get_by_role("link").all_inner_texts()]
    assert names[:4] == ["Overview", "Assets", "System health", "Preferences"], names
    assert names[-1] == "Settings", names
    expect(nav.get_by_text("Plant", exact=True)).to_have_count(0)
    page.goto("/setup/calendars")
    expect(page.get_by_role("heading", level=1, name="Desk", exact=True)).to_be_visible()
    switch = page.get_by_label("Show the Team page in Desk")
    expect(switch).not_to_be_checked()
    switch.check()
    expect(page.get_by_text("Desk shows the Team page.")).to_be_visible()
    page.goto("/actions")
    expect(
        page.locator(".pcs-sidebar").get_by_role("link", name="Team", exact=True)
    ).to_be_visible()
    page.goto("/setup/calendars")
    page.get_by_label("Show the Team page in Desk").uncheck()
    expect(page.get_by_text("Desk no longer shows the Team page.")).to_be_visible()
