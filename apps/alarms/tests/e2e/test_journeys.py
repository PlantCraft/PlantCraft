"""The main journeys in a real browser: sign-in, a Simple rule made with the editor and tested on
history, Alarms (evaluate, acknowledge, shelve, an alarm's history), performance, a rule started
from an event's page in Events, a rule switched off in Rules, the targets, a rule in Python and an
asset's page."""

from __future__ import annotations

import os
import re

import pytest

try:
    from playwright.sync_api import expect
except ImportError:
    if os.environ.get("ALARMCRAFT_E2E_REQUIRED") == "1":
        raise
    pytest.skip("Playwright is not installed", allow_module_level=True)

from plantcraft_sdk import e2e
from plantcraft_sdk.contract import TOKEN_COOKIE

SLOW = 30_000


def _shot(page, screenshots, name):
    if screenshots:
        page.wait_for_timeout(800)
        page.screenshot(path=str(screenshots / f"{name}.png"), full_page=True)


def test_a_browser_without_a_token_is_sent_to_sign_in(anonymous, app_url):
    anonymous.goto(f"{app_url}/alarm/")
    assert re.search(r"/login\?next=/alarm/", anonymous.url), anonymous.url


def test_make_a_rule_then_operate_it(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/alarm/alarms")
    expect(page.get_by_text("Process Engineer")).to_be_visible()
    expect(page.get_by_text("No alarms yet")).to_be_visible()
    _shot(page, screenshots, "1-empty-alarms")

    page.goto(f"{app_url}/alarm/rules/new")
    page.get_by_label("Name").fill("FIC-1001 feed flow high")
    page.get_by_role("radiogroup", name="Where").get_by_role(
        "radio", name=re.compile("^Assets")
    ).click()
    page.get_by_label("Assets", exact=True).fill("FIC-1001")
    page.get_by_role("button", name=re.compile("FIC-1001")).first.click()
    expect(page.locator(".al-chip", has_text="FIC-1001")).to_be_visible()
    # The Simple form starts on each asset's PV: above a limit, with a deadband.
    page.get_by_label("Limit", exact=True).fill("50")
    page.get_by_role("spinbutton", name=re.compile("^Deadband")).fill("0.5")
    page.get_by_label("Priority").select_option("high")
    page.get_by_label("Corrective action").fill("Reduce the feed pump speed")
    page.get_by_role("button", name="Test", exact=True).click()
    expect(page.get_by_text(re.compile(r"alarms in 24h"))).to_be_visible(timeout=SLOW)
    expect(page.locator(".js-plotly-plot")).to_have_count(1)
    _shot(page, screenshots, "2-editor-test")
    page.get_by_role("button", name="Save").click()
    expect(page.get_by_role("heading", name="FIC-1001 feed flow high")).to_be_visible()
    _shot(page, screenshots, "3-rule")

    page.goto(f"{app_url}/alarm/alarms")
    page.get_by_role("button", name="Evaluate now").click()
    row = page.locator(".al-row").first
    expect(row).to_contain_text("Unacknowledged", timeout=SLOW)
    _shot(page, screenshots, "4-alarms-unacked")
    row.get_by_role("button", name="Acknowledge").click()
    expect(row).to_contain_text("Acknowledged")
    row.get_by_role("button", name="Shelve").click()
    page.get_by_label("Why").fill("Pump under maintenance")
    page.get_by_role("dialog").get_by_role("button", name="Shelve").click()
    expect(page.locator(".al-row").first).to_contain_text("Shelved")
    _shot(page, screenshots, "5-alarms-shelved")

    # A row opens its alarm: its facts, its value, its history and the messages sent.
    page.locator(".al-row").first.locator("td").nth(4).click()
    expect(page.get_by_role("heading", name="FIC-1001 feed flow high")).to_be_visible()
    for word in ("Raised", "Acknowledged", "Shelved", "Created"):
        expect(page.locator("tbody").get_by_text(word, exact=True).first).to_be_visible()
    expect(page.get_by_role("heading", name="Messages sent")).to_be_visible()
    _shot(page, screenshots, "6-alarm")

    page.goto(f"{app_url}/alarm/performance")
    expect(page.get_by_text("Average alarms per hour")).to_be_visible()
    expect(page.get_by_role("link", name="FIC-1001 feed flow high")).to_be_visible()
    _shot(page, screenshots, "7-performance")

    page.goto(f"{app_url}/alarm/")
    expect(page.get_by_role("heading", name="Overview")).to_be_visible()
    expect(page.locator(".pc-wg-card-head h2", has_text="By priority")).to_be_visible()
    expect(page.locator(".pc-wg-card-head h2", has_text="Alarm rate")).to_be_visible()
    expect(page.get_by_text("FIC-1001 feed flow high").first).to_be_visible(timeout=SLOW)
    _shot(page, screenshots, "0-overview")

    page.goto(f"{app_url}/alarm/assets/FIC-1001")
    expect(page.get_by_role("heading", name="FIC-1001")).to_be_visible()
    expect(page.get_by_role("link", name="FIC-1001 feed flow high")).to_be_visible()


def test_a_rule_from_what_link_reported(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/alarm/alarms")
    page.get_by_role("button", name="Evaluate now").click()
    page.goto(f"{app_url}/alarm/events")
    expect(page.get_by_role("heading", name="Events", exact=True)).to_be_visible()
    page.get_by_role("button", name="All", exact=True).click()
    rows = page.locator("tbody tr", has_text="FIC-1001 critical")
    expect(rows).to_have_count(3, timeout=SLOW)
    _shot(page, screenshots, "8-events")
    # A row opens the event: where it came from, what Link sent, the rules that read it.
    rows.first.click()
    expect(page.get_by_role("heading", name="Where it came from")).to_be_visible()
    expect(page.get_by_text("unit-100-health").first).to_be_visible()
    expect(page.get_by_text(re.compile("No rule reads this type of event"))).to_be_visible()
    _shot(page, screenshots, "8b-event")
    page.get_by_role("link", name="Create a rule from it").click()
    expect(page.get_by_role("heading", name="New rule")).to_be_visible()
    expect(page.locator(".al-chip", has_text="linkcraft.run.failed")).to_be_visible()
    page.get_by_label("Name").fill("FIC-1001 failed 3 times in 1 h")
    page.get_by_label("How many times").fill("3")
    page.get_by_role("button", name="Test", exact=True).click()
    expect(page.get_by_text(re.compile(r"1 alarms in 24h"))).to_be_visible(timeout=SLOW)
    _shot(page, screenshots, "9-rule-from-event")
    page.get_by_role("button", name="Save").click()
    expect(page.get_by_role("heading", name="FIC-1001 failed 3 times in 1 h")).to_be_visible()
    page.goto(f"{app_url}/alarm/rules")
    expect(page.get_by_role("link", name="FIC-1001 failed 3 times in 1 h")).to_be_visible()
    # On and off at a click, from the list.
    switch = page.get_by_role("switch", name="FIC-1001 failed 3 times in 1 h on")
    expect(switch).to_be_checked()
    switch.click()
    expect(switch).not_to_be_checked()
    _shot(page, screenshots, "10-rules")


def test_my_alarms_and_a_silence(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/alarm/alarms")
    page.get_by_label("Only mine").check()
    page.get_by_role("button", name="All", exact=True).click()
    _shot(page, screenshots, "11-all-alarms")
    page.goto(f"{app_url}/alarm/silences")
    page.get_by_role("button", name="New silence").click()
    page.get_by_role("dialog").get_by_label("Why").fill("U-100 planned shutdown")
    expect(page.get_by_role("dialog").get_by_role("button", name="Silence")).to_be_disabled()


def test_the_targets(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/alarm/performance")
    page.get_by_role("link", name="Targets", exact=True).click()
    expect(page.get_by_role("heading", name="Targets", exact=True)).to_be_visible()
    page.get_by_label("Statement").fill("An alarm needs an action.")
    page.get_by_label("Shift summaries at").fill("06:00, 18:00")
    page.get_by_role("button", name="Save").click()
    expect(page.get_by_text(re.compile("Saved. The next shift summary goes at"))).to_be_visible()
    _shot(page, screenshots, "13-targets")


def test_the_two_ways_to_write_a_rule(browser, fake, app_url, screenshots):
    """Simple, then Python in the suite's code editor (an administrator), expanded full screen."""

    cookie = {"name": TOKEN_COOKIE, "value": fake.token("admin"), "url": app_url}
    with e2e.page(browser, [cookie]) as page:
        page.goto(f"{app_url}/alarm/rules/new")
        page.get_by_label("Name").fill("FIC-1001 high in Python")
        page.get_by_role("radiogroup", name="Where").get_by_role(
            "radio", name=re.compile("^Assets")
        ).click()
        page.get_by_label("Assets", exact=True).fill("FIC-1001")
        page.get_by_role("button", name=re.compile("FIC-1001")).first.click()
        written = page.get_by_role("radiogroup", name="Written as")
        expect(written.get_by_role("radio")).to_have_count(2)
        expect(page.get_by_role("button", name="Add a condition")).to_be_visible()
        _shot(page, screenshots, "2b-simple-form")
        written.get_by_role("radio", name=re.compile("^Python")).click()
        expect(page.locator(".pc-code .cm-content")).to_contain_text("def check(inputs):")
        expect(page.locator(".al-python-guide")).to_contain_text("return True")
        _shot(page, screenshots, "14-python")
        page.get_by_role("button", name="Expand").click()
        expect(page.get_by_role("dialog").locator(".pc-code")).to_be_visible()
        _shot(page, screenshots, "15-python-expanded")
        page.get_by_role("dialog").get_by_role("button", name="Done").click()


def test_import_the_dcs_alarm_list_review_and_apply(signed_in, app_url, screenshots, tmp_path):
    page = signed_in
    exported = tmp_path / "dcs-alarms.csv"
    exported.write_text(
        "Tag;Alarm type;Limit;EU;Priority;Description;Operator action\n"
        "FIC-1001.PV;PVHI;58;m3/h;2;Feed flow very high (DCS);Close FV-1001\n"
        "FIC-1001.PV;PVLO;5;m3/h;3;Feed flow low (DCS);Check the feed pump\n"
        "NOPE-9.PV;HI;1;;2;Not a signal;\n"
    )
    page.goto(f"{app_url}/alarm/rules")
    page.get_by_role("link", name="Import alarm list").click()
    page.locator("input[type=file]").set_input_files(str(exported))
    expect(page.get_by_text("2 new, 0 changed, 0 removed, 0 the same")).to_be_visible()
    expect(page.get_by_text("Rows not read: 1")).to_be_visible()
    # Leave the LO alarm out, then apply the rest.
    page.get_by_label("Apply FIC-1001.PV/LO").uncheck()
    _shot(page, screenshots, "8-alarm-list-review")
    page.get_by_role("button", name="Apply the changes (1)").click()
    expect(
        page.get_by_text("1 rules created, 0 changed, 0 turned off, 1 left out.")
    ).to_be_visible()
    page.goto(f"{app_url}/alarm/rules")
    expect(page.get_by_role("link", name="Feed flow very high (DCS)")).to_be_visible()
    expect(page.get_by_role("link", name="Feed flow low (DCS)")).to_have_count(0)


def test_a_rule_only_while_its_permissive_holds(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/alarm/rules/new")
    page.get_by_role("button", name="Only while…").click()
    expect(page.get_by_role("group", name="Only while")).to_be_visible()
    page.get_by_label("Permissive limit").fill("1")
    page.get_by_label("Enabled after (s)").fill("30")
    _shot(page, screenshots, "9-only-while")
    page.get_by_role("button", name="Remove the permissive").click()
    expect(page.get_by_role("button", name="Only while…")).to_be_visible()


def test_consoles_split_the_load_by_operator(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/alarm/targets")
    page.get_by_role("button", name="Add a console").click()
    board = page.locator(".al-console").first
    board.get_by_label("Console name").fill("Unit board")
    board.get_by_label("Alarms an hour, at most").fill("4")
    board.get_by_label("Areas", exact=True).fill("Simulated")
    page.get_by_role("button", name=re.compile("Simulated unit")).first.click()
    expect(board.locator(".al-chip", has_text="Simulated unit")).to_be_visible()
    board.get_by_label("Operators", exact=True).select_option(index=1)
    expect(board.locator(".al-chip")).to_have_count(2)
    _shot(page, screenshots, "10-consoles")
    page.get_by_role("button", name="Save").click()
    expect(page.get_by_text(re.compile("Saved. The next shift summary goes at"))).to_be_visible()

    page.goto(f"{app_url}/alarm/performance")
    table = page.get_by_role("table", name="Consoles")
    expect(table.get_by_role("button", name="Unit board")).to_be_visible()
    page.get_by_label("Console", exact=True).select_option(label="Unit board")
    expect(
        page.get_by_text("Console Unit board: at most 4 alarms an hour for its operator.")
    ).to_be_visible()
    _shot(page, screenshots, "11-performance-by-console")


def test_limits_by_product_grade(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/alarm/rules/new")
    page.get_by_label("Limit", exact=True).fill("60")
    page.get_by_role("button", name="Limits by grade…").click()
    expect(page.get_by_role("group", name="Limits by grade")).to_be_visible()
    page.get_by_role("group", name="The grade comes from").get_by_role(
        "button", name="An event"
    ).click()
    expect(page.get_by_label("Field with the grade")).to_have_value("grade")
    page.get_by_label("Grade 1", exact=True).fill("HD-5")
    page.get_by_label("Limit for grade 1").fill("50")
    page.get_by_role("button", name="Add a grade").click()
    page.get_by_label("Grade 2", exact=True).fill("LD-2")
    page.get_by_label("Limit for grade 2").fill("90")
    _shot(page, screenshots, "12-limits-by-grade")
    page.get_by_role("button", name="Remove grade 2").click()
    expect(page.get_by_label("Grade 2", exact=True)).to_have_count(0)
    page.get_by_role("button", name="Remove the limits by grade").click()
    expect(page.get_by_role("button", name="Limits by grade…")).to_be_visible()
