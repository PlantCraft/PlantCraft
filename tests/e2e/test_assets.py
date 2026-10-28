"""The asset model in a real browser: a loop's record edited in place, and the type catalog."""

from __future__ import annotations

import re

from playwright.sync_api import expect


def test_engineer_edits_a_loop_record_and_it_shows_in_history(page):
    page.goto("/assets/FIC-101")
    expect(page.get_by_role("heading", name="FIC-101")).to_be_visible()
    record = page.get_by_role("form", name="Record")
    record.get_by_label("Loop type", exact=True).select_option("level")
    record.get_by_label("Criticality", exact=True).select_option("high")
    record.get_by_role("button", name="Save record").click()
    expect(record.get_by_role("button", name="Save record")).to_be_disabled()
    page.reload()
    record = page.get_by_role("form", name="Record")
    expect(record.get_by_label("Loop type", exact=True)).to_have_value("level")
    expect(record.get_by_label("Criticality", exact=True)).to_have_value("high")
    page.get_by_role("link", name="History", exact=True).click()
    expect(page).to_have_url(re.compile(r"\?tab=history$"))
    expect(page.get_by_text(re.compile(r"Record changed: .*Loop type: .*level"))).to_be_visible()
    # The tree filters by type and shows one column per attribute.
    page.goto("/assets?type=loop")
    table = page.get_by_role("table")
    expect(table.get_by_role("columnheader", name="Loop type")).to_be_visible()
    expect(table.get_by_role("row", name=re.compile("FIC-101"))).to_contain_text("level")


def test_an_asset_page_has_tabs_and_no_links_that_lead_nowhere(page):
    """Owner, 2026-10-21: the asset page redone in tabs; the "Open in" links are gone."""

    page.goto("/assets/FIC-101")
    expect(page.get_by_role("navigation", name="Open in")).to_have_count(0)
    tabs = page.get_by_role("navigation", name="Asset")
    tabs.get_by_role("link", name=re.compile(r"^Signals")).click()
    expect(page).to_have_url(re.compile(r"/assets/FIC-101\?tab=signals$"))
    table = page.locator(".as-sig-table")
    expect(table.get_by_role("columnheader", name="Role")).to_be_visible()
    expect(table.get_by_role("row", name=re.compile(r"^PV"))).to_be_visible()
    page.reload()
    expect(tabs.get_by_role("link", name=re.compile(r"^Signals"))).to_have_attribute(
        "aria-current", "page"
    )


def test_old_asset_addresses_move_to_assets(page):
    page.goto("/plant/FIC-101?tab=x")
    expect(page).to_have_url(re.compile(r"/assets/FIC-101\?tab=x$"))
    expect(page.get_by_role("heading", name="FIC-101")).to_be_visible()
    page.goto("/plant")
    expect(page).to_have_url(re.compile(r"/assets$"))
    expect(page.get_by_role("heading", name="Assets", exact=True)).to_be_visible()


def test_admin_opens_the_type_catalog_and_a_type(page):
    page.goto("/assets")
    page.get_by_role("link", name="Asset types", exact=True).click()
    expect(page).to_have_url(re.compile(r"/asset-types$"))
    expect(page.get_by_role("link", name="Asset types", exact=True)).to_have_attribute(
        "aria-current", "page"
    )
    page.get_by_role("link", name=re.compile("Control loop")).click()
    expect(page).to_have_url(re.compile(r"/asset-types/loop$"))
    attributes = page.get_by_role("table", name="Attributes")
    expect(attributes.locator("input[value='loop_type']")).to_be_visible()
    roles = page.get_by_role("table", name="Signal roles")
    expect(roles.locator("input[value='pv']")).to_be_visible()


def test_a_role_binds_a_signal_picked_by_its_api_v1_id(page):
    """The picker lists <source id>:<tag> ids; the role then shows the tag and its value."""

    made = page.context.request.post(
        "/api/assets", data={"asset_id": "FIC-950", "name": "FIC-950", "kind": "loop"}
    )
    assert made.ok, made.text()
    page.goto("/assets/FIC-950?tab=signals")
    page.get_by_role("button", name="Bind signal").first.click()
    page.get_by_label("Search signals").fill("neighbor")
    picked = page.get_by_role("button", name=re.compile(r"^scenario:neighbor_pv"))
    picked.click()
    bound = page.locator(".as-sig-table tr", has_text="neighbor_pv")
    expect(bound).to_be_visible()
    expect(bound.get_by_role("button", name="Remove neighbor_pv")).to_be_visible()


def test_an_asset_shows_its_situation_and_ctrl_k_finds_it(page):
    """Owner, 2026-10-23: the Situation tab, and the suite's search from any screen."""

    page.goto("/assets/FIC-101?tab=situation")
    tabs = page.get_by_role("navigation", name="Asset")
    expect(tabs.get_by_role("link", name="Situation")).to_have_attribute("aria-current", "page")
    expect(page.locator(".as-situation-head h2")).to_be_visible()
    expect(page.get_by_role("heading", name="Open actions")).to_be_visible()
    page.goto("/")
    expect(page.get_by_role("button", name=re.compile("Search the suite"))).to_be_visible()
    box = page.get_by_role("dialog", name="Search the suite")
    # The shortcut is listened for in an effect that runs just after the button is drawn: a key
    # pressed in those few milliseconds (13 in 40 fresh pages here) is lost. Press again then.
    for _ in range(3):
        page.keyboard.press("Control+k")
        try:
            expect(box).to_be_visible(timeout=2000)
            break
        except AssertionError:
            continue
    box.get_by_role("combobox").fill("FIC-101")
    hit = box.get_by_role("option").filter(has_text="FIC-101").first
    expect(hit).to_be_visible()
    page.keyboard.press("Enter")
    expect(page).to_have_url(re.compile(r"/assets/FIC-101$"))
    expect(page.get_by_role("dialog", name="Search the suite")).to_have_count(0)
