"""The main journeys in a real browser: sign-in, a dashboard from a template, the editor, its
Config, folders and a public link."""

from __future__ import annotations

import os
import re

import pytest

try:
    from playwright.sync_api import expect
except ImportError:
    if os.environ.get("DASHCRAFT_E2E_REQUIRED") == "1":
        raise
    pytest.skip("Playwright is not installed", allow_module_level=True)


def _shot(page, screenshots, name):
    if screenshots:
        page.wait_for_timeout(600)
        page.screenshot(path=str(screenshots / f"{name}.png"), full_page=True)


def test_a_browser_without_a_token_is_sent_to_sign_in(anonymous, app_url):
    anonymous.goto(f"{app_url}/dash/")
    assert re.search(r"/login\?next=/dash/", anonymous.url), anonymous.url


def _add_card(page, kind: str) -> None:
    """Add card › the kind (round 7: the kind comes first, then the editor)."""

    page.get_by_role("button", name="Add panel").first.click()
    page.get_by_role("radiogroup", name="Panel type").get_by_role(
        "radio", name=re.compile(f"^{kind}")
    ).click()


def _from_template(page, app_url, template: str, name: str | None = None) -> None:
    """New dashboard › start from a template › Save: nothing is saved before Save."""

    page.goto(f"{app_url}/dash/dashboards")
    page.get_by_role("button", name="New dashboard").first.click()
    dialog = page.get_by_role("dialog", name="New dashboard")
    dialog.get_by_role("radio", name=re.compile(template)).check()
    if name:
        dialog.get_by_label("Name").fill(name)
    dialog.get_by_role("button", name="Open the editor").click()
    expect(page.get_by_text("Editing")).to_be_visible()
    page.get_by_role("button", name="Save").click()
    expect(page).to_have_url(re.compile(r"/dash/d/[0-9a-f]{12}"))


def test_a_template_dashboard_follows_the_picked_asset(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/dash/dashboards")
    expect(page.get_by_text("Process Engineer")).to_be_visible()
    page.get_by_role("button", name="New dashboard").first.click()
    _shot(page, screenshots, "1-new-dashboard")
    page.get_by_role("button", name="Cancel").click()
    _from_template(page, app_url, "Loop detail")
    expect(page.get_by_role("heading", name="Loop detail")).to_be_visible()
    # The old asset picker is the dashboard's variable "asset" (round 7), named by its kind.
    picker = page.get_by_label("loop", exact=True)
    expect(picker).to_have_value("fic-101")
    pv = page.locator("[data-card='kpi-pv']")
    expect(pv.locator(".tc-kpi-value b")).to_have_text(re.compile(r"^\d"))
    expect(pv).to_contain_text("m3/h")
    expect(
        page.locator("[data-card='trend-pv'] .js-plotly-plot .scatterlayer .trace")
    ).to_have_count(2)
    # Round 4: the value with its line, OP on a dial, PV against OP and a note.
    expect(pv.locator("svg.tc-spark")).to_be_visible()
    expect(page.locator("[data-card='kpi-op'] .tc-gauge svg")).to_be_visible()
    expect(
        page.locator("[data-card='scatter-op-pv'] .js-plotly-plot .scatterlayer .trace")
    ).to_have_count(1)
    expect(page.locator("[data-card='note'] .tc-text")).to_contain_text("sticky valve")
    _shot(page, screenshots, "2-loop-detail")
    trend_card = page.locator("[data-card='trend-pv']")
    trend_card.get_by_role("button", name="Full screen").click()
    full = page.get_by_role("dialog", name="PV and SP")
    expect(full.locator(".modebar")).to_be_attached()
    expect(full.locator(".modebar-btn[data-title='Lasso Select']")).to_have_count(0)
    _shot(page, screenshots, "2-card-full-screen")
    page.keyboard.press("Escape")
    expect(full).to_have_count(0)
    # A card's data downloads as CSV, as the card shows it (one row per sample for a trend).
    with page.expect_download() as download:
        page.locator("[data-card='trend-pv']").get_by_role("button", name=re.compile("CSV")).click()
    assert download.value.suggested_filename.endswith(".csv")
    lines = open(download.value.path(), encoding="utf-8-sig").read().splitlines()
    # The time column names its zone (fileTimeHeader): "time (UTC)" on this test's clock.
    header = r"time \([^)]+\),label,signal,value,unit"
    assert re.fullmatch(header, lines[0]) and len(lines) > 10, lines[:3]
    picker.select_option("lic-102")
    expect(page).to_have_url(re.compile(r"var-asset=lic-102"))
    expect(pv).to_contain_text("%")


def test_build_a_dashboard_with_the_editor(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/dash/dashboards")
    page.get_by_role("button", name="New dashboard").first.click()
    page.get_by_role("dialog", name="New dashboard").get_by_role(
        "button", name="Open the editor"
    ).click()
    expect(page.get_by_text("Editing")).to_be_visible()
    # Round 7: the kind first, then the editor (Grafana's).
    _add_card(page, "Time series")
    dialog = page.get_by_role("dialog", name="New panel")
    dialog.locator("[data-item='0'] select").nth(1).select_option("role:pv")
    dialog.get_by_role("button", name="Add a signal").click()
    dialog.locator("[data-item='1'] select").nth(1).select_option("role:sp")
    dialog.get_by_role("button", name="Add threshold").click()
    expect(dialog.locator(".tc-preview .js-plotly-plot .scatterlayer .trace")).to_have_count(2)
    _shot(page, screenshots, "3-card-editor")
    dialog.get_by_role("button", name="Apply").click()
    page.get_by_role("button", name="Config").click()
    settings = page.get_by_role("dialog", name=re.compile("^Config of "))
    settings.get_by_label("Name", exact=True).fill("Feed section")
    settings.get_by_role("button", name="Apply").click()
    page.get_by_role("button", name="Save").click()
    expect(page.get_by_role("heading", name="Feed section")).to_be_visible()
    expect(page.locator(".tc-card .js-plotly-plot .scatterlayer .trace")).to_have_count(2)
    page.reload()
    expect(page.get_by_role("heading", name="Feed section")).to_be_visible()
    # Share · Config · Edit, Config outside the editor saves at once and keeps every version.
    toolbar = page.locator(".tc-toolbar .button:not(.button-icon)")
    expect(toolbar).to_have_text(["Share", "Config", "Edit"])
    page.get_by_role("button", name="Config").click()
    settings = page.get_by_role("dialog", name=re.compile("^Config of "))
    settings.get_by_role("link", name="Time").click()
    settings.get_by_label("Opens with").select_option("24h")
    _shot(page, screenshots, "3-config")
    settings.get_by_role("button", name="Save").click()
    expect(page.get_by_text("Saved.")).to_be_visible()
    expect(page.get_by_label("Time window")).to_have_value("24h")
    page.get_by_role("button", name="Config").click()
    page.get_by_role("dialog", name=re.compile("^Config of ")).get_by_role(
        "link", name="Versions"
    ).click()
    expect(page.locator(".tc-config tbody tr")).to_have_count(2)
    _shot(page, screenshots, "3-versions")


def test_a_public_link_opens_read_only_without_sign_in(signed_in, anonymous, app_url, screenshots):
    page = signed_in
    _from_template(page, app_url, "Unit 100 overview")
    page.get_by_role("button", name="Share").click()
    dialog = page.get_by_role("dialog", name="Public links")
    dialog.get_by_label("Link label").fill("Control room")
    dialog.get_by_role("button", name="Create link").click()
    link = dialog.locator("#share-url")
    expect(link).to_have_value(re.compile(r"/dash/share/"))
    url = link.input_value()
    anonymous.goto(url)
    expect(anonymous.get_by_role("heading", name="Unit 100 overview")).to_be_visible()
    expect(anonymous.locator("table.tc-table tbody tr")).to_have_count(3)
    expect(anonymous.get_by_role("button", name="Edit")).to_have_count(0)
    expect(anonymous.locator(".pcs-sidebar")).to_have_count(0)  # public links stay frameless
    _shot(anonymous, screenshots, "4-public-link")


def test_the_suite_pages_asset_and_help(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/dash/dashboards")
    _from_template(page, app_url, "Loop detail")
    page.goto(f"{app_url}/dash/assets/lic-102")
    # The page's top is the asset's name only (ui 0.41.0).
    expect(page.locator(".page-heading h1")).to_have_text(re.compile("LIC-102", re.I))
    _shot(page, screenshots, "5-asset-page")
    page.get_by_role("link", name=re.compile("Loop detail")).first.click()
    expect(page).to_have_url(re.compile(r"/dash/d/.+asset=lic-102"))
    expect(page.get_by_label("loop", exact=True)).to_have_value("lic-102")
    # The app's own guides (the person's menu opens the suite's Help, ui 0.32.0).
    page.goto(f"{app_url}/dash/help")
    # Guides in folders (the suite's help browser): the first folder is open.
    expect(page.get_by_role("button", name="Dashboards", exact=True)).to_be_visible()
    page.get_by_role("button", name="Building dashboards").click()
    expect(page.get_by_role("button", name="Panels")).to_be_visible()
    page.get_by_role("button", name="Sharing").click()
    page.get_by_role("button", name="Public links").click()
    expect(page.get_by_role("heading", name="Public links")).to_be_visible()
    expect(page).to_have_url(re.compile(r"/dash/help\?doc=public-links"))
    _shot(page, screenshots, "6-help")


def test_a_card_shows_linkcrafts_loop_health(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/dash/dashboards")
    page.get_by_role("button", name="New dashboard").first.click()
    page.get_by_role("dialog", name="New dashboard").get_by_role(
        "button", name="Open the editor"
    ).click()
    expect(page.get_by_text("Editing")).to_be_visible()
    _add_card(page, "Stat")
    dialog = page.get_by_role("dialog", name="New panel")
    dialog.get_by_role("button", name="Asset", exact=True).click()
    item = dialog.locator("[data-item='0'] select")
    item.nth(0).select_option("fic-101")
    item.nth(1).select_option("result:linkcraft.loop_health")
    preview = dialog.locator(".tc-preview")
    expect(preview).to_contain_text("62.5")
    expect(preview).to_contain_text("Oscillating, period 4 min")
    expect(preview).to_contain_text("Warning")
    _shot(page, screenshots, "7-loop-health-card")


def test_a_trend_draws_the_loop_health_linkcraft_archives(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/dash/dashboards")
    page.get_by_role("button", name="New dashboard").first.click()
    page.get_by_role("dialog", name="New dashboard").get_by_role(
        "button", name="Open the editor"
    ).click()
    _add_card(page, "Time series")
    dialog = page.get_by_role("dialog", name="New panel")
    dialog.get_by_role("button", name="Asset", exact=True).click()
    item = dialog.locator("[data-item='0'] select")
    item.nth(0).select_option("fic-101")
    item.nth(1).select_option("result:linkcraft.loop_health")
    expect(dialog.locator(".tc-preview .js-plotly-plot .scatterlayer .trace")).to_have_count(1)
    _shot(page, screenshots, "8-loop-health-trend")


def test_an_item_switched_to_signal_picks_a_signal_by_search(signed_in, app_url):
    page = signed_in
    page.goto(f"{app_url}/dash/dashboards")
    page.get_by_role("button", name="New dashboard").first.click()
    page.get_by_role("dialog", name="New dashboard").get_by_role(
        "button", name="Open the editor"
    ).click()
    _add_card(page, "Stat")
    dialog = page.get_by_role("dialog", name="New panel")
    dialog.get_by_role("button", name="Signal", exact=True).click()
    search = dialog.get_by_label("Search signals")
    expect(search).to_be_visible()
    search.fill("LIC-102")
    dialog.get_by_role("button", name=re.compile("fake:LIC-102.PV")).click()
    expect(dialog.locator(".tc-preview .tc-kpi-value b")).to_have_text(re.compile(r"^\d"))


def test_the_suite_frame_and_a_frameless_full_screen(signed_in, app_url, screenshots):
    """The sidebar of every app (@plantcraft/ui): DashCraft's pages, Apps, Help and the user
    menu with the theme and About; full screen leaves only the dashboard for a wall screen."""

    page = signed_in
    page.goto(f"{app_url}/dash/")
    sidebar = page.locator(".pcs-sidebar")
    expect(sidebar.get_by_role("link", name="Overview")).to_have_class(re.compile("pcs-active"))
    # One Help for the suite (ui 0.32.0): in the person's menu, at PlantCraft's Help on this app.
    expect(sidebar.get_by_role("link", name="Help")).to_have_count(0)
    sidebar.locator(".pcs-profile").click()
    expect(page.get_by_role("menuitem", name="Help")).to_have_attribute(
        "href", re.compile(r"help\?app=dashcraft$")
    )
    sidebar.locator(".pcs-profile").click()
    # The app switcher at the top (ui 0.28.0) lists the apps; PlantCraft comes last, set apart,
    # so the platform is one click away.
    apps = sidebar.locator(".pcs-app-item")
    expect(apps).to_have_count(0)
    sidebar.get_by_role("button", name="Switch app").click()
    expect(sidebar.locator(".pcs-switcher-pop hr + .pcs-app-item")).to_have_text("PlantCraft")
    page.keyboard.press("Escape")
    expect(apps).to_have_count(0)
    expect(
        sidebar.locator(".pcs-quick").get_by_role("button", name="Collapse the menu")
    ).to_be_visible()
    expect(page.locator(".topbar")).to_have_count(0)  # no menu of its own
    sidebar.locator(".pcs-profile").click()
    expect(page.get_by_role("radiogroup", name="Theme")).to_be_visible()
    expect(page.locator(".pcs-user-pop .pcs-version")).to_contain_text("0.5.0")
    page.locator(".pcs-theme button").nth(1).click()  # dark
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    page.keyboard.press("Escape")
    sidebar.get_by_role("link", name="Dashboards", exact=True).click()
    _from_template(page, app_url, "Unit 100 overview")
    page.locator(".tc-toolbar").get_by_role("button", name="Full screen").click()
    expect(sidebar).to_be_hidden()
    _shot(page, screenshots, "8-full-screen")


def test_a_trend_with_two_subplots_is_saved_and_reopened(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/dash/trends")
    expect(page.get_by_role("heading", name="Trends", exact=True)).to_be_visible()
    search = page.get_by_label("Search signals")
    search.fill("FIC-101.PV")
    page.get_by_role("button", name=re.compile("fake:FIC-101.PV")).click()
    page.get_by_role("button", name="Add a subplot").click()
    page.get_by_label("Search signals").last.fill("FIC-101.OP")
    page.get_by_role("button", name=re.compile("fake:FIC-101.OP")).click()
    chart = page.locator(".tc-trend-chart .js-plotly-plot .scatterlayer .trace")
    expect(chart).to_have_count(2)
    full = page.get_by_role("button", name="Full screen")
    expect(full).to_be_visible()
    # Above the chart, clear of Plotly's own buttons (owner, 2026-10-23).
    modebar = page.locator(".tc-trend-chart .modebar-container").bounding_box()
    button = full.bounding_box()
    assert modebar and button and button["y"] + button["height"] <= modebar["y"]
    # The chart's own theme, whatever the platform's: dark here, kept for the next visit.
    page.get_by_label("Chart").select_option("dark")
    expect(page.locator(".tc-trend-chart .main-svg").first).to_have_css(
        "background-color", "rgb(28, 28, 30)"
    )
    _shot(page, screenshots, "5-dark-chart")
    assert page.evaluate("localStorage.getItem('dashcraft.chart-theme')") == "dark"
    page.get_by_label("Chart").select_option("auto")
    page.get_by_label("Interval").select_option(label="10 minutes")
    # A line's summary and style: the OP as its maximum per interval, drawn as red steps with points.
    page.get_by_role("button", name=re.compile("fake:FIC-101.OP")).first.click()
    editor = page.get_by_role("dialog", name=re.compile("FIC-101.OP"))
    editor.get_by_label("Each interval shows").select_option("max")
    editor.get_by_label("Draw as").select_option("lines+markers")
    editor.get_by_label("Between samples").select_option("hv")
    editor.get_by_label("Automatic").uncheck()
    _shot(page, screenshots, "5-line-editor")
    editor.get_by_role("button", name="Apply").click()
    expect(page.locator(".tc-line-chip").last).to_contain_text("max")
    expect(chart).to_have_count(2)
    page.get_by_placeholder("Name of the trend").fill("FIC-101 check")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page).to_have_url(re.compile(r"/dash/trends/[0-9a-f]+$"))
    expect(page.locator(".tc-trend-list")).to_contain_text("FIC-101 check")
    _shot(page, screenshots, "5-trend")
    page.reload()
    expect(page.get_by_role("heading", name="FIC-101 check")).to_be_visible()
    expect(chart).to_have_count(2)


def test_a_dashboard_with_two_pages_and_cards_of_any_height(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/dash/dashboards")
    page.get_by_role("button", name="New dashboard").first.click()
    page.get_by_role("dialog", name="New dashboard").get_by_role(
        "button", name="Open the editor"
    ).click()
    _add_card(page, "Stat")
    dialog = page.get_by_role("dialog", name="New panel")
    dialog.get_by_role("button", name="Layout").click()
    dialog.locator(".tc-opt", has_text="Width").locator("select").select_option("5")
    dialog.locator(".tc-opt", has_text="Height").locator("select").select_option("1")
    dialog.get_by_role("button", name="Apply").click()
    page.get_by_role("button", name="Add page").click()
    tabs = page.get_by_role("navigation", name=re.compile("Pages of"))
    expect(tabs.get_by_role("link")).to_have_count(2)
    page.get_by_label("Page name").fill("Pumps")
    _add_card(page, "Time series")
    dialog.get_by_role("button", name="Layout").click()
    dialog.locator(".tc-opt", has_text="Height").locator("select").select_option("6")
    expect(dialog.locator(".tc-opt", has_text="Page").locator("select")).to_have_value("p2")
    dialog.get_by_role("button", name="Apply").click()
    _shot(page, screenshots, "9-pages-editing")
    page.get_by_role("button", name="Save").click()
    expect(page.get_by_text("Saved.")).to_be_visible()
    expect(tabs.get_by_role("link", name="Pumps")).to_have_attribute("aria-current", "page")
    trend = page.locator(".tc-card")
    expect(trend).to_have_count(1)
    expect(trend.locator(".js-plotly-plot")).to_be_visible()
    assert trend.bounding_box()["height"] == pytest.approx(6 * 91 + 5 * 14, abs=2)
    _shot(page, screenshots, "9-pages")
    tabs.get_by_role("link", name="Page 1").click()
    expect(page).to_have_url(re.compile(r"page=p1"))
    kpi = page.locator(".tc-card")
    expect(kpi.locator(".tc-kpi-value b")).to_have_text(re.compile(r"^\d"))
    assert kpi.bounding_box()["height"] == pytest.approx(91, abs=2)
    _shot(page, screenshots, "9-pages-first")
    page.reload()
    expect(tabs.get_by_role("link")).to_have_count(2)


def test_the_overview_is_widgets_and_the_dashboards_have_their_page(
    signed_in, app_url, screenshots
):
    """Every app's first page is an Overview of widgets (AppOverview); View's dashboards list is
    its own page after it."""

    page = signed_in
    page.goto(f"{app_url}/dash/")
    expect(page.get_by_role("heading", name="Overview", exact=True)).to_be_visible()
    # The page's top is its title and buttons only (ui 0.41.0): no line above or under the title.
    expect(page.locator(".page-heading .eyebrow, .page-heading p")).to_have_count(0)
    titles = page.locator(".pc-wg-card .pc-wg-card-head h2")
    # Saved trends first, then the lists, each row a name and when it changed (owner, 2026-10-27).
    expect(titles).to_have_text(
        ["Saved trends", "Dashboards", "Reports", "Process displays", "Public links"]
    )
    expect(page.get_by_role("button", name="New dashboard")).to_have_count(0)
    if screenshots:
        page.screenshot(path=str(screenshots / "overview.png"), full_page=True)
    sidebar = page.locator(".pcs-sidebar")
    sidebar.get_by_role("link", name="Dashboards", exact=True).click()
    expect(page).to_have_url(re.compile(r"/dash/dashboards$"))
    expect(page.get_by_role("heading", name="Dashboards", exact=True)).to_be_visible()


def test_a_folder_for_a_group(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/dash/dashboards")
    page.get_by_role("button", name="New folder").click()
    dialog = page.get_by_role("dialog", name="New folder")
    dialog.get_by_label("Name").fill("Instrumentation")
    who = dialog.get_by_role("group", name="Who sees its dashboards and reports")
    who.get_by_role("radio", name=re.compile("Only these")).check()
    who.locator(".pc-search input").fill("Process")
    who.get_by_role("button", name=re.compile("Process engineering")).click()
    _shot(page, screenshots, "5-folder")
    dialog.get_by_role("button", name="Save").click()
    folder = page.locator("details.tc-folder", has_text="Instrumentation")
    expect(folder).to_contain_text("1 group")
    _from_template(page, app_url, "Unit 100 overview", name="Unit 100 instruments")
    page.get_by_role("button", name="Config").click()
    page.get_by_role("dialog", name=re.compile("^Config of ")).get_by_label("Folder").select_option(
        label="Instrumentation"
    )
    page.get_by_role("dialog", name=re.compile("^Config of ")).get_by_role(
        "button", name="Save"
    ).click()
    page.goto(f"{app_url}/dash/dashboards")
    expect(folder.get_by_role("link", name=re.compile("Unit 100 instruments"))).to_be_visible()
    _shot(page, screenshots, "5-list-folders")


def test_a_report_is_built_made_into_a_pdf_and_kept(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/dash/reports")
    page.get_by_role("button", name="New report").first.click()
    dialog = page.get_by_role("dialog", name="New report")
    dialog.get_by_label("Name").fill("Unit 100 day")
    dialog.get_by_role("radio", name=re.compile("Every day")).check()
    dialog.get_by_role("button", name="Create and edit").click()
    expect(page.locator(".tc-title h1")).to_contain_text("Unit 100 day")
    expect(page.locator(".tc-title h1")).to_contain_text("Editing")
    # A text cell is Markdown, written in place: its headings make the side navigation.
    page.locator(".tc-report-writable").first.dblclick()
    cell = page.get_by_label("Markdown of the cell")
    cell.fill("# Unit 100 day\n\nThe **feed** and the levels.\n\n## Levels\n\n- LIC-102")
    expect(page.locator(".tc-report-text-preview h2")).to_have_text("Levels")
    _shot(page, screenshots, "8-report-cell")
    cell.press("Shift+Enter")
    outline = page.get_by_role("navigation", name="Sections of the report")
    expect(outline.get_by_role("link")).to_have_text(["Unit 100 day", "Levels"])
    # A card section: the dashboards' editor, without a window of its own.
    page.locator(".tc-report-add-button", has_text="Panel").click()
    page.get_by_role("radio", name=re.compile("^Stat")).click()
    expect(page.locator(".tc-kind-picker")).to_have_count(0)
    dialog = page.get_by_role("dialog", name="New panel")
    dialog.get_by_role("button", name="Signal", exact=True).click()
    dialog.get_by_label("Search signals").fill("LIC-102")
    dialog.get_by_role("button", name=re.compile("fake:LIC-102.PV")).click()
    expect(dialog.locator(".tc-preview .tc-kpi-value b")).to_have_text(re.compile(r"^\d"))
    expect(dialog.get_by_label("Period")).to_have_value("24 hours")
    dialog.get_by_role("button", name="Apply").click()
    # A page break: the PDF starts a new page there.
    page.locator(".tc-report-add-button", has_text="Page break").click()
    expect(page.locator(".tc-report-break")).to_be_visible()
    page.get_by_role("button", name="Save").click()
    expect(page.get_by_role("status")).to_contain_text("Saved.")
    expect(page.locator(".tc-report-section .tc-kpi-value").first).to_be_visible()
    _shot(page, screenshots, "8-report")
    page.get_by_role("button", name="Download", exact=True).click()
    exports = page.get_by_role("dialog", name="Download the report")
    _shot(page, screenshots, "8-report-download")
    for label, suffix in (("Word (.docx)", ".docx"), ("Web page (.html)", ".html")):
        with page.expect_download() as download:
            exports.get_by_role("link", name=re.compile(re.escape(label))).click()
        assert download.value.suggested_filename.startswith("unit-100-day-")
        assert download.value.suggested_filename.endswith(suffix)
        if exports.count() == 0:
            page.get_by_role("button", name="Download", exact=True).click()
    with page.expect_download() as download:
        exports.get_by_role("button", name=re.compile("^PDF")).click()
    assert download.value.suggested_filename.startswith("unit-100-day-")
    page.get_by_role("link", name=re.compile("Sent")).click()
    expect(page.locator("table")).to_contain_text("Download")
    expect(page.locator("table")).to_contain_text("Nobody (download)")
    _shot(page, screenshots, "8-report-sent")


def test_a_report_shared_by_link_reads_as_a_web_page(signed_in, anonymous, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/dash/reports")
    answer = page.request.post(
        f"{app_url}/dash/api/dashboards",
        data={
            "name": "Feed pair",
            "cards": [
                {
                    "card_id": "t1",
                    "kind": "trend",
                    "title": "Feed",
                    "items": [{"signal_id": "fake:FIC-101.PV"}],
                    "width": 12,
                }
            ],
        },  # fmt: skip
    )
    assert answer.ok, answer.text()
    page.get_by_role("button", name="New report").first.click()
    dialog = page.get_by_role("dialog", name="New report")
    dialog.get_by_label("Name").fill("Feed by link")
    dialog.get_by_role("radio", name=re.compile("^A dashboard")).check()
    dialog.get_by_label("The dashboard it starts from").select_option(label="Feed pair")
    dialog.get_by_role("button", name="Create and edit").click()
    expect(page.locator(".tc-title h1")).to_contain_text("Feed by link")
    page.get_by_role("button", name="Save").click()
    expect(page.get_by_role("status")).to_contain_text("Saved.")
    page.get_by_role("button", name="Share").click()
    share = page.get_by_role("dialog", name=re.compile("Public links of"))
    share.get_by_role("button", name="Create link").click()
    url = share.locator("#share-url").input_value()
    assert "/dash/share/report/" in url
    anonymous.goto(url)
    expect(anonymous.locator(".rc-cover h1")).to_have_text("Feed by link")
    chart = anonymous.locator(".rc-chart svg").first
    if chart.count():
        box = chart.bounding_box()
        anonymous.mouse.move(box["x"] + box["width"] * 0.6, box["y"] + 60)
        expect(anonymous.locator(".rc-tip").first).to_be_visible()
    _shot(anonymous, screenshots, "8-report-public")
    page.goto(f"{app_url}/dash/reports")
    expect(page.locator("details.tc-folder").first).to_be_visible()
    _shot(page, screenshots, "8-reports-folders")
