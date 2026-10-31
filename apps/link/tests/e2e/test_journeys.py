"""The main journey in a real browser: sign-in redirect, the suite frame and the Overview, signals,
a signal page, the Signal quality algorithm and its runs, loops, a loop page, run, algorithm and
its editor window, blocks (a shipped one's code; one written, versioned and diffed), PDF,
an incomplete asset record, where each setting comes from, the help browser and method help, the
asset deep link and the suite's status words. With ``LINKCRAFT_E2E_SCREENSHOTS`` set, the last
journey saves every page in light and dark, on a desktop and on a phone."""

from __future__ import annotations

import os
import re

import pytest
from plantcraft_sdk import e2e
from plantcraft_sdk.contract import TOKEN_COOKIE

try:
    from playwright.sync_api import expect
except ImportError:
    if os.environ.get("LINKCRAFT_E2E_REQUIRED") == "1":
        raise
    pytest.skip("Playwright is not installed", allow_module_level=True)

# As in conftest.py: the first-visit tour would cover the page.
TOURS_OFF = "try { localStorage.setItem('plantcraft-ui:tours-off', '1') } catch (error) {}"


def test_a_browser_without_a_token_is_sent_to_sign_in(page, app_url):
    page.goto(f"{app_url}/link/")
    assert re.search(r"/login\?next=/link/", page.url), page.url


def test_the_loops_list_shows_every_loop_with_its_status(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/link/loops")
    table = page.locator("table.table")
    for loop_id in ("fic-101", "lic-102", "pic-103", "tic-104", "fic-105", "fic-106"):
        expect(table.get_by_role("link", name=loop_id, exact=True)).to_be_visible()
    if screenshots:
        page.screenshot(path=str(screenshots / "loops-list.png"), full_page=True)


def test_a_loop_page_shows_trends_findings_and_health(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/link/loops")
    page.get_by_role("link", name="lic-102", exact=True).click()
    expect(page).to_have_url(re.compile(r"/link/loops/lic-102$"))
    expect(page.get_by_role("heading", name=re.compile("lic-102"))).to_be_visible()
    expect(page.locator(".js-plotly-plot").first).to_be_visible()
    expect(page.locator(".js-plotly-plot .scatterlayer .trace").first).to_be_attached()
    findings = page.locator("table.table").first
    expect(findings.get_by_text("Oscillation", exact=False).first).to_be_visible()
    expect(page.locator(".kpi-card").first).to_contain_text("Result")
    expect(page.locator(".kpi-card").first.locator(".pc-num, .health").first).to_be_visible()
    if screenshots:
        page.screenshot(path=str(screenshots / "loop-page.png"), full_page=True)


def test_run_now_queues_a_run(signed_in, app_url):
    page = signed_in
    page.goto(f"{app_url}/link/loops/fic-105")
    # The sticky valve's likely cause leads the list, with what to do first.
    expect(page.get_by_test_id("likely-causes")).to_contain_text("Valve stiction")
    page.get_by_role("button", name="Run now").click()
    expect(page.get_by_text(re.compile(r"Run queued \(\w+\)"))).to_be_visible()


def test_an_algorithm_page_and_its_editor_window(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/link/algorithms")
    # One list: PlantCraft's own and the site's, with tags, author, owner, version and use.
    row = page.locator("tr", has=page.get_by_role("link", name="Flow loop", exact=True))
    expect(row.locator(".tag", has_text="control loop")).to_be_visible()
    expect(row.get_by_role("cell", name="PlantCraft", exact=True).first).to_be_visible()
    if screenshots:
        page.screenshot(path=str(screenshots / "algorithm-list.png"), full_page=True)
    row.get_by_role("link", name="Flow loop", exact=True).click()
    expect(page).to_have_url(re.compile(r"/link/algorithms/flow_loop$"))
    # The overview is what it is for; what it reads and gives is the next tab (D19).
    expect(page.get_by_role("heading", name="What it is for")).to_be_visible()
    expect(page.get_by_role("heading", name="What it reads and gives")).to_have_count(0)
    expect(page.locator(".alg-diagram")).to_have_count(0)
    tabs = page.get_by_role("navigation", name="Algorithm").get_by_role("link")
    expect(tabs).to_have_text(
        ["Overview", "Inputs and outputs", "Diagram", "Test", "Used by", "Versions", "Settings"]
    )
    if screenshots:
        page.screenshot(path=str(screenshots / "algorithm-page.png"), full_page=True)
    page.get_by_role("link", name="Diagram", exact=True).click()
    expect(page).to_have_url(re.compile(r"/link/algorithms/flow_loop/diagram$"))
    expect(page.locator(".alg-diagram .react-flow__node").first).to_be_visible()
    # Read-only, the diagram's toolbar keeps only what works there (round 9).
    tools = page.locator(".alg-diagram .be-tools")
    expect(tools.get_by_role("button", name="Fit to screen")).to_be_visible()
    expect(tools.locator(".be-tool", has_text="Arrange")).to_have_count(0)
    expect(tools.locator('[title^="Delete"]')).to_have_count(0)
    expect(page.get_by_text("The diagram is valid")).to_have_count(0)
    page.get_by_role("link", name="Inputs and outputs").click()
    expect(page.get_by_role("heading", name="What it reads and gives")).to_be_visible()
    expect(page.locator(".alg-parameters")).to_have_count(1)
    if screenshots:
        page.screenshot(path=str(screenshots / "algorithm-inputs.png"), full_page=True)
    # Who answers for it and where it runs are Settings, not versions.
    page.get_by_role("navigation", name="Algorithm").get_by_role("link", name="Settings").click()
    expect(page.locator(".alg-who", has_text="About it")).to_contain_text("PlantCraft")
    expect(page.locator(".alg-who", has_text="Where it runs")).to_have_count(1)
    page.get_by_role("link", name="Versions", exact=True).click()
    expect(page.locator(".alg-who")).to_have_count(0)
    versions = page.locator(".pc-versions")
    expect(versions.get_by_role("button", name=re.compile("Version 1"))).to_have_attribute(
        "aria-pressed", "true"
    )
    if screenshots:
        page.screenshot(path=str(screenshots / "algorithm-versions.png"), full_page=True)
    # PlantCraft's own are locked (round 10): no New version, Duplicate makes one's own.
    expect(versions.locator(".pc-version-lock")).to_contain_text("Ships with PlantCraft")
    expect(page.get_by_role("link", name="New version")).to_have_count(0)
    expect(page.get_by_role("button", name="Duplicate")).to_be_visible()
    expect(page.get_by_role("button", name="Edit a copy")).to_have_count(0)
    # The editor window still opens by its address; PlantCraft's algorithms are read-only there.
    page.goto(f"{app_url}/link/editor/flow_loop")
    editor = page
    expect(editor.locator(".be-editor .react-flow__node").first).to_be_visible()
    expect(editor.locator(".pcs-nav")).to_have_count(0)
    expect(editor.get_by_text(re.compile("Duplicate it to change a copy"))).to_be_visible()
    expect(editor.locator(".be-palette")).to_have_count(0)


def test_the_loop_pdf_downloads(signed_in, app_url):
    page = signed_in
    page.goto(f"{app_url}/link/loops/pic-103")
    with page.expect_download() as info:
        page.get_by_role("link", name="PDF report").click()
    download = info.value
    path = download.path()
    with open(path, "rb") as handle:
        assert handle.read(5) == b"%PDF-"
    assert download.suggested_filename.endswith(".pdf")


def test_an_incomplete_asset_record_is_listed_with_what_is_missing(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/link/results?q=fic-106")
    row = page.locator("tr", has=page.get_by_role("link", name="fic-106", exact=True))
    expect(row.get_by_text(re.compile(r"no signal for OP"))).to_be_visible()
    row.get_by_role("link", name="fic-106", exact=True).click()
    expect(page).to_have_url(re.compile(r"/link/loops/fic-106$"))
    panel = page.locator(".incomplete-record")
    expect(panel.get_by_role("heading", name="Incomplete record")).to_be_visible()
    expect(panel.get_by_text("Missing", exact=True)).to_be_visible()
    expect(panel.get_by_text(re.compile("asset's page in PlantCraft"))).to_be_visible()
    expect(
        panel.get_by_role("link", name=re.compile("Open the asset in PlantCraft"))
    ).to_have_attribute("href", re.compile(r"/assets/fic-106$"))
    expect(page.get_by_role("button", name="Run now")).to_have_count(0)
    if screenshots:
        page.screenshot(path=str(screenshots / "incomplete-record.png"), full_page=True)


def test_the_loop_page_says_where_each_setting_comes_from(signed_in, app_url):
    page = signed_in
    page.goto(f"{app_url}/link/loops/fic-101")
    settings = page.locator("section.panel", has=page.get_by_role("heading", name="Settings"))
    expect(settings.locator("[data-source=asset]").first).to_have_text("from the asset record")
    expect(settings.get_by_text("flow", exact=True)).to_be_visible()
    # The 0.2 protocol of the asset record opens the algorithm that replaced it.
    expect(settings.get_by_role("combobox").first).to_have_value("flow_loop")


def test_a_finding_links_to_its_method_help(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/link/loops/lic-102")
    row = page.locator("tr", has=page.get_by_role("link", name="Oscillation", exact=True))
    row.get_by_role("link", name="How to read this").click()
    expect(page).to_have_url(re.compile(r"/link/help/methods/oscillation_autocorrelation$"))
    document = page.locator(".pcs-help-document")
    for heading in (
        "What it detects",
        "Reference",
        "Parameters",
        "How to read the finding",
        "Limits",
    ):
        expect(document.get_by_role("heading", name=heading, exact=True)).to_be_visible()
    expect(document.locator("table").get_by_text("min_lag_samples")).to_be_visible()
    expect(document.get_by_text(re.compile("Thornhill")).first).to_be_visible()
    if screenshots:
        page.screenshot(path=str(screenshots / "method-help.png"), full_page=True)


def test_the_help_browser_has_guides_and_method_folders(signed_in, app_url):
    page = signed_in
    page.goto(f"{app_url}/link/help")
    index = page.locator(".pcs-help-index")
    for folder in ("Guides", "Methods"):
        expect(index.get_by_text(folder, exact=True).first).to_be_visible()
    expect(page.locator(".pcs-help-document h1")).to_have_text("Overview")
    page.goto(f"{app_url}/link/help?doc=guides/loop-types")
    table = page.locator(".pcs-help-document table")
    expect(table.get_by_text("composition", exact=True)).to_be_visible()
    page.goto(f"{app_url}/link/help/methods/sq_spikes")
    expect(page.locator(".pcs-help-document h1")).to_have_text("Spikes")


def test_the_overview_shows_what_is_bad_and_where(signed_in, app_url, screenshots):
    """Which loops and signals are bad now, and where: results by status,
    the days in alarm, the health map by area and the worst; the monitors and the queue below.
    The same for every kind of subject."""

    page = signed_in
    page.goto(f"{app_url}/link/")
    expect(page.get_by_role("heading", name="Overview", exact=True)).to_be_visible()
    # The page's top is its title and buttons only (ui 0.41.0): no line above or under the title.
    expect(page.locator(".page-heading .eyebrow, .page-heading p")).to_have_count(0)
    cards = page.locator(".pc-wg-card .pc-wg-card-head h2")
    expect(cards).to_have_text(
        [
            "Results by status",
            "In alarm, 14 days",
            "Health map",
            "Worst results",
            "Monitors",
            "Queue",
            "Loop-hours lost, 7 days",
            "Effective control",
        ]
    )
    # Every loop and signal a square, each opening its page.
    health = page.get_by_role("article", name="Health map")
    expect(health.locator("a.pc-wg-square[href='/link/loops/lic-102']")).to_have_count(1)
    schedules = page.get_by_role("article", name="Monitors")
    expect(
        schedules.get_by_role("link", name=re.compile("^Control loop performance"))
    ).to_be_visible()
    # A widget about one thing: its gear picks which, and the card takes its name.
    page.get_by_role("button", name="Customize").click()
    page.get_by_role("button", name="Set up Results by status").click()
    dialog = page.get_by_role("dialog", name="Widget settings")
    choice = dialog.get_by_label("Kind")
    expect(choice.locator("option")).not_to_have_count(1)
    choice.select_option(index=2)
    picked = choice.locator("option:checked").inner_text().split(" · ")[0]
    dialog.get_by_role("button", name="Apply").click()
    expect(page.get_by_role("article", name=picked, exact=True)).to_be_visible()
    page.get_by_role("button", name="Done").click()
    # the same widgets frame as every app: each person arranges them (AppOverview)
    page.get_by_role("button", name="Customize").click()
    page.get_by_role("button", name="Remove Worst results").click()
    expect(cards.filter(has_text=re.compile("^Worst results$"))).to_have_count(0)
    page.get_by_role("button", name="Done").click()
    if screenshots:
        page.screenshot(path=str(screenshots / "overview.png"), full_page=True)
    # An Overview only shows: no buttons on top.
    expect(page.locator(".heading-actions")).to_have_count(0)
    nav = page.locator(".pcs-nav")
    # In the order of the work; the old Results page is inside this Results.
    labels = ["Overview", "Blocks", "Algorithms", "Monitors", "Results"]
    expect(nav.get_by_role("link")).to_have_text(labels)
    # The assistant is the suite's button at the top, not a page of Link's.
    expect(nav.get_by_role("link", name="Assistant", exact=True)).to_have_count(0)
    expect(nav.get_by_role("link", name="Runs", exact=True)).to_have_count(0)


def test_signals_list_and_a_signal_page(signed_in, app_url):
    page = signed_in
    page.goto(f"{app_url}/link/signals")
    expect(page).to_have_url(re.compile(r"/link/results\?asset_type=signal$"))
    table = page.locator(".results-table table")
    expect(table.locator("tbody tr").first).to_be_visible()
    # Paged and sorted on the page (no table without pages).
    page.get_by_role("button", name="Asset", exact=True).click()
    expect(page.locator("th[aria-sort=ascending]")).to_contain_text("Asset")
    expect(table.locator(".pill").first).to_be_visible()
    table.locator("tbody tr a").first.click()
    expect(page).to_have_url(re.compile(r"/link/signals/.+"))
    expect(page.get_by_role("heading", name="Input signals")).to_be_visible()
    expect(page.locator(".check-item").first).to_be_visible()


def test_the_signal_quality_algorithm_and_its_runs(signed_in, app_url):
    page = signed_in
    page.goto(f"{app_url}/link/algorithms")
    page.get_by_role("link", name="Signal quality", exact=True).click()
    expect(page).to_have_url(re.compile(r"/link/algorithms/signal_quality$"))
    expect(page.get_by_role("heading", name="Signal quality", exact=True)).to_be_visible()
    page.get_by_role("link", name="Diagram", exact=True).click()
    expect(page.locator(".alg-diagram .react-flow__node").first).to_be_visible()
    page.get_by_role("navigation", name="Algorithm").get_by_role("link", name="Settings").click()
    expect(page).to_have_url(re.compile(r"/link/algorithms/signal_quality/settings$"))
    expect(page.locator(".toggles li")).to_have_count(11)  # sq_source_quality (#79), sq_rate and sq_fault_level (#85)
    expect(page.get_by_role("heading", name="Where it is used")).to_be_visible()
    # 0.2 addresses still open it.
    page.goto(f"{app_url}/link/protocols/signal-quality")
    expect(page).to_have_url(re.compile(r"/link/algorithms/signal_quality/settings$"))
    # The old Runs page is Results > Run history: one list for every algorithm.
    page.goto(f"{app_url}/link/runs")
    expect(page).to_have_url(re.compile(r"/link/results/runs$"))
    history = page.locator(".pc-dt table")
    history.locator("tbody tr", has_text="Signal quality").first.locator("a").first.click()
    expect(page).to_have_url(re.compile(r"/link/runs/signal-quality-\d+$"))
    # The page's top is the title only (ui 0.41.0): the algorithm and when it ran.
    expect(page.get_by_role("heading", name=re.compile(r"^Signal quality, "))).to_be_visible()


def test_blocks_list_each_library_and_open_a_block(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/link/methods")
    expect(page).to_have_url(re.compile(r"/link/blocks$"))
    page.get_by_role("button", name=re.compile("Data quality")).click()
    page.get_by_role("link", name=re.compile("Spikes")).click()
    expect(page).to_have_url(re.compile(r"/link/blocks/dq\.spikes$"))
    # The overview is the block's description; its contract is the next tab (D15).
    expect(page.get_by_role("heading", name="About this block")).to_be_visible()
    expect(page.locator(".blk-contract")).to_have_count(0)
    # A shipped block is drawn too, without a picture (round 9 M1).
    expect(page.locator(".pc-block-drawing .pc-bd-box img")).to_have_count(0)
    expect(page.get_by_role("link", name=re.compile("^Versions"))).to_be_visible()
    page.get_by_role("link", name="Code", exact=True).click()
    expect(page).to_have_url(re.compile(r"/link/blocks/dq\.spikes/code$"))
    expect(
        page.get_by_text("The code Analytics ships for this block, read-only.", exact=False)
    ).to_be_visible()
    # One calculation, not the declaration around it.
    expect(page.locator(".pc-code")).to_have_count(1)
    expect(page.locator(".pc-code .cm-content").first).to_contain_text("def ")
    expect(page.locator(".pc-code .cm-content").first).not_to_contain_text("@method")
    if screenshots:
        page.screenshot(path=str(screenshots / "block-code.png"), full_page=True)
    page.get_by_role("link", name="Inputs and outputs").click()
    expect(page.locator(".blk-contract")).to_have_count(1)
    # The defaults change with New version: no separate form here (round 9, D16).
    expect(page.get_by_role("heading", name="Change the defaults")).to_have_count(0)
    if screenshots:
        page.screenshot(path=str(screenshots / "block-inputs.png"), full_page=True)
    page.get_by_role("link", name="Test", exact=True).click()
    expect(page.locator("#blkt-asset")).to_be_visible()
    expect(page.locator(".blkt-points tbody tr").first).to_be_visible()
    if screenshots:
        page.screenshot(path=str(screenshots / "block-test.png"), full_page=True)


@pytest.fixture
def admin(browser, fake, app_url):
    cookie = {"name": TOKEN_COOKIE, "value": fake.token("admin"), "url": app_url}
    with e2e.page(browser, [cookie]) as opened:
        yield opened


def test_a_block_is_written_in_the_form_versioned_and_diffed(admin, app_url, screenshots):
    """An administrator writes a block in the form, saves version 1, changes its code and saves
    version 2, and its code compares with version 1."""

    page = admin
    page.goto(f"{app_url}/link/blocks")
    page.get_by_role("link", name="New block").click()
    expect(page).to_have_url(re.compile(r"/link/blocks/new$"))
    # Two ways; the assistant is the button beside the title (round 9).
    expect(page.locator(".blkn-way")).to_have_count(2)
    page.get_by_role("button", name=re.compile("Fill in the form")).click()
    page.locator("#blkf-name").fill("Smoothed level")
    page.locator("#blkf-summary").fill("A moving average of a level, to read its trend.")
    expect(page.get_by_text("The block is valid", exact=False)).to_be_visible()
    # Its picture (round 9 M2): chosen in the form, kept with the version.
    page.locator("#blkf-image").set_input_files(
        {"name": "level.png", "mimeType": "image/png", "buffer": e2e.png()}
    )
    expect(page.locator(".pc-bif-preview img")).to_be_visible()
    # Every field a shipped block has (D20): other input types, an output's normal range and
    # which way is good, and whether it runs without data.
    page.get_by_role("checkbox", name="Inputs 1: also accepts State").check()
    page.get_by_role("spinbutton", name="Outputs 1: normal low").fill("0")
    page.get_by_role("combobox", name="Outputs 1: better when").select_option("lower")
    expect(page.locator("#blkf-runs-on-missing")).not_to_be_checked()
    expect(page.get_by_text("The block is valid", exact=False)).to_be_visible()
    page.locator(".pc-code").first.scroll_into_view_if_needed()
    page.wait_for_timeout(500)
    if screenshots:
        page.screenshot(path=str(screenshots / "block-new-form.png"), full_page=True)
    page.locator(".blkf-bar").get_by_role("button", name="Create the block").click()
    dialog = page.get_by_role("dialog", name="Create the block")
    dialog.get_by_role("button", name="Create the block").click()
    expect(page).to_have_url(re.compile(r"/link/blocks/custom\.smoothed_level$"))
    expect(page.get_by_role("heading", name="Smoothed level", exact=True)).to_be_visible()
    # The owner's tab order, the overview without the contract (D15).
    tabs = page.get_by_role("navigation", name="Block").get_by_role("link")
    expect(tabs).to_have_text(
        [
            "Overview",
            "Inputs and outputs",
            "Code",
            "Test",
            re.compile("^Used by"),
            re.compile("^Versions"),
        ]
    )
    expect(page.locator(".blk-contract")).to_have_count(0)
    # The overview draws it as the diagram does, with its picture (round 9 M1, M2).
    drawing = page.locator(".pc-block-drawing")
    expect(drawing.locator(".pc-bd-inputs")).to_contain_text("Signal")
    picture = drawing.locator(".pc-bd-box img")
    expect(picture).to_be_visible()
    page.wait_for_function("() => document.querySelector('.pc-bd-box img')?.naturalWidth === 24")

    # New version is on the Versions tab (round 10).
    page.get_by_role("link", name=re.compile("^Versions")).click()
    page.locator(".pc-versions").get_by_role("link", name="New version").click()
    expect(page.get_by_role("heading", name="New version of Smoothed level")).to_be_visible()
    editor = page.locator(".pc-code .cm-content").first
    editor.click()
    page.keyboard.press("Control+End")
    page.keyboard.type("\n# Version two.\n")
    expect(page.get_by_text("The block is valid", exact=False)).to_be_visible()
    page.locator(".blkf-bar").get_by_role("button", name=re.compile("^Save as version")).click()
    dialog = page.get_by_role("dialog", name="Save as new version")
    dialog.locator("#blk-version-name").fill("A comment")
    dialog.locator("#blk-version-description").fill("Says which version it is.")
    dialog.get_by_role("button", name="Save as new version").click()
    page.get_by_role("link", name=re.compile("^Versions")).click()
    versions = page.locator(".pc-versions")
    expect(versions.get_by_text("A comment")).to_be_visible()
    expect(versions.get_by_text("Says which version it is.")).to_be_visible()
    if screenshots:
        page.screenshot(path=str(screenshots / "block-versions.png"), full_page=True)
    # A version opens the block's page at that version, not its code (D17).
    versions.get_by_role("button", name=re.compile("Version 1")).click()
    expect(page).to_have_url(re.compile(r"/link/blocks/custom\.smoothed_level\?version=1$"))
    shown = page.locator(".blk-shown")
    expect(shown).to_contain_text("Showing version 1 of Smoothed level")
    if screenshots:
        page.screenshot(path=str(screenshots / "block-version-1.png"), full_page=True)
    page.get_by_role("link", name="Code", exact=True).click()
    expect(page).to_have_url(re.compile(r"/code\?version=1$"))
    expect(page.locator(".pc-code .cm-content").first).not_to_contain_text("Version two")
    # New version starts from the version shown and saves the next number.
    page.get_by_role("link", name=re.compile("^Versions")).click()
    page.locator(".pc-versions").get_by_role("link", name="New version").click()
    expect(page.get_by_role("button", name="Save as version 3")).to_be_visible()
    page.get_by_role("button", name="Cancel").first.click()
    expect(page).to_have_url(re.compile(r"/link/blocks/custom\.smoothed_level\?version=1$"))
    # Select version: version 1 is the one in use again.
    page.locator(".blk-shown").get_by_role("button", name="Select this version").click()
    expect(page).to_have_url(re.compile(r"/link/blocks/custom\.smoothed_level$"))
    expect(page.locator(".blk-shown")).to_have_count(0)
    page.get_by_role("link", name=re.compile("^Versions")).click()
    in_use = page.locator(".pc-version-list li", has=page.locator(".tag", has_text="current"))
    expect(in_use).to_contain_text("Version 1")
    page.goto(f"{app_url}/link/blocks/custom.smoothed_level/code?version=2")
    page.get_by_role("button", name="Compare with 1").click()
    expect(page.locator(".pc-diff-added").first).to_contain_text("Version two")
    # Compare versions (D18): two ticked, run on the same asset and window, side by side.
    page.goto(f"{app_url}/link/blocks/custom.smoothed_level/versions")
    picker = page.get_by_role("region", name="Compare versions")
    picker.get_by_role("checkbox", name="Version 1").check()
    picker.get_by_role("checkbox", name="Version 2").check()
    picker.get_by_role("button", name="Compare 2 versions").click()
    expect(page).to_have_url(re.compile(r"custom\.smoothed_level/compare\?versions=1,2$"))
    page.get_by_role("button", name="Run and compare").click()
    compared = page.locator(".compare-view")
    expect(compared.get_by_role("columnheader", name="Version 2").first).to_be_visible(
        timeout=30_000
    )
    expect(compared.get_by_role("heading", name="What they read")).to_be_visible()
    if screenshots:
        page.wait_for_timeout(500)
        page.screenshot(path=str(screenshots / "block-compare.png"), full_page=True)


def test_a_block_plantcraft_ships_is_locked_and_duplicates_into_a_new_block(
    admin, app_url, screenshots
):
    """Round 10: a block PlantCraft ships gets no new version here, its
    Versions tab shows a lock; Duplicate, beside Download the file, opens its code as a new
    block in the library chosen, a library made from the form included."""

    page = admin
    page.goto(f"{app_url}/link/blocks/transform.moving_average")
    expect(page.get_by_role("link", name="New version")).to_have_count(0)
    page.get_by_role("link", name=re.compile("^Versions")).click()
    versions = page.locator(".pc-versions")
    expect(versions.locator(".pc-version-lock")).to_contain_text("Ships with PlantCraft")
    expect(versions.get_by_role("link", name="New version")).to_have_count(0)
    if screenshots:
        page.screenshot(path=str(screenshots / "block-locked.png"), full_page=True)
    expect(page.get_by_role("button", name="Download the file")).to_be_visible()
    page.get_by_role("link", name="Duplicate").click()
    expect(page).to_have_url(re.compile(r"/link/blocks/new\?from=transform\.moving_average$"))
    expect(page.locator("#blkf-name")).to_have_value("Moving average (copy)")
    expect(page.locator("#blkf-group")).to_have_count(0)
    page.locator(".blkf-library").get_by_role("button", name="New library").click()
    dialog = page.get_by_role("dialog", name="New library")
    dialog.locator("#blk-library-name").fill("Smoothing")
    dialog.get_by_role("button", name="Make the library").click()
    expect(page.locator("#blkf-library")).to_have_value("smoothing")
    expect(page.get_by_text("The block is valid", exact=False)).to_be_visible()
    page.locator(".blkf-bar").get_by_role("button", name="Create the block").click()
    page.get_by_role("dialog", name="Create the block").get_by_role(
        "button", name="Create the block"
    ).click()
    expect(page).to_have_url(re.compile(r"/link/blocks/smoothing\.moving_average_copy$"))
    # The site's block gets New version on its Versions tab.
    page.get_by_role("link", name=re.compile("^Versions")).click()
    expect(page.locator(".pc-versions").get_by_role("link", name="New version")).to_be_visible()
    # Its library is in the column, under Libraries, with no folders.
    page.goto(f"{app_url}/link/blocks?library=smoothing")
    column = page.get_by_role("navigation", name="Libraries")
    expect(column.get_by_role("heading", name="Libraries")).to_be_visible()
    expect(column.get_by_role("button", name=re.compile("^Smoothing"))).to_be_visible()
    expect(column.get_by_role("button", name="New folder")).to_have_count(0)
    expect(page.locator(".blk-card")).to_have_count(1)


def test_the_asset_page_lists_every_algorithm_s_result(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/link/assets/pic-103")
    expect(page).to_have_url(re.compile(r"/link/assets/pic-103$"))
    expect(page.get_by_role("heading", name=re.compile("pic-103", re.I)).first).to_be_visible()
    results = page.locator("table", has=page.get_by_role("columnheader", name="Algorithm"))
    expect(results.locator("tbody tr").first).to_be_visible()
    expect(results.get_by_role("link", name="Temperature or pressure loop")).to_be_visible()
    if screenshots:
        page.screenshot(path=str(screenshots / "asset-page.png"), full_page=True)
    page.get_by_role("link", name="Loop analysis").first.click()
    expect(page).to_have_url(re.compile(r"/link/loops/pic-103$"))
    page.goto(f"{app_url}/link/assets/area-a")
    expect(page.get_by_role("heading", name="No result yet")).to_be_visible()
    expect(
        page.get_by_text(re.compile("No algorithm of Analytics runs on this asset"))
    ).to_be_visible()
    expect(
        page.get_by_role("link", name=re.compile("Open the asset in PlantCraft"))
    ).to_have_attribute("href", re.compile(r"/assets/area-a$"))
    if screenshots:
        page.screenshot(path=str(screenshots / "asset-not-covered.png"), full_page=True)
    # Built files are under static/, so assets/ is free for the deep link.
    scripts = page.locator("script[src]")
    expect(scripts.first).to_have_attribute("src", re.compile(r"^/link/static/"))


def test_statuses_use_the_suite_words(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/link/loops/pic-103")
    card = page.locator(".kpi-card").first
    expect(card.locator(".pill", has_text="Critical").first).to_be_visible()
    findings = page.locator("table.table").first
    expect(findings.locator(".pill", has_text="Critical").first).to_be_visible()
    expect(findings.locator(".pill", has_text=re.compile("^(Bad|Warning)$"))).to_have_count(0)
    if screenshots:
        page.screenshot(path=str(screenshots / "suite-status.png"), full_page=True)


PAGES = {
    "overview": "/link/",
    "executions": "/link/executions",
    "executions-group": "/link/executions/round-cpm",
    "executions-subject": "/link/executions/round-cpm/fic-101",
    "queue": "/link/executions/queue",
    "results": "/link/results",
    "run-history": "/link/results/runs",
    "algorithms": "/link/algorithms",
    "algorithm": "/link/algorithms/flow_loop",
    "blocks": "/link/blocks",
    "block-code": "/link/blocks/dq.spikes/code",
    "block-new": "/link/blocks/new",
    "help": "/link/help",
}
VIEWPORTS = {"desktop": {"width": 1440, "height": 900}, "phone": {"width": 390, "height": 844}}


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_every_page_in_light_and_dark(browser, fake, app_url, screenshots, theme):
    """Each page of the frame renders with no script error; saved when screenshots are asked."""

    from plantcraft_sdk.contract import TOKEN_COOKIE

    for viewport, size in VIEWPORTS.items():
        if viewport == "phone" and not screenshots:
            continue
        context = browser.new_context(viewport=size, color_scheme=theme)
        context.add_init_script(TOURS_OFF)
        context.add_cookies(
            [{"name": TOKEN_COOKIE, "value": fake.token("engineer"), "url": app_url}]
        )
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        for name, path in PAGES.items():
            page.goto(f"{app_url}{path}")
            expect(page.locator(".pcs-content h1").first).to_be_visible()
            page.wait_for_load_state("networkidle")
            if screenshots and (viewport == "desktop" or name == "overview"):
                page.screenshot(
                    path=str(screenshots / f"{name}-{theme}-{viewport}.png"), full_page=True
                )
        context.close()
        assert not errors, f"JavaScript errors on the page: {errors}"


def test_an_algorithm_duplicated_on_screen_is_tested_saved_and_scheduled(
    signed_in, app_url, screenshots
):
    """An algorithm copied from PlantCraft's in the editor window, tested on a loop with what every
    wire carried, saved and scheduled, all in the browser."""

    page = signed_in
    # Wide enough that the diagram is drawn at a readable zoom.
    page.set_viewport_size({"width": 2000, "height": 1150})
    page.goto(f"{app_url}/link/editor/new?from=flow_loop")
    expect(page.locator(".alg-window-title b")).to_have_text("Flow loop (copy)")
    expect(page.locator(".be-palette")).to_be_visible()
    expect(page.locator(".be-editor .react-flow__node").first).to_be_visible()
    page.locator(".alg-test select").select_option("fic-105")
    page.get_by_role("button", name="Test", exact=True).click()
    expect(page.locator(".alg-window-test .pill")).to_be_visible()
    # Each block shows a light; what it said waits in the hover tip.
    expect(page.locator(".be-node .be-light").first).to_be_visible()
    stiction = page.locator('.be-node[data-block="cpm.stiction_screening"]')
    stiction.hover()
    expect(stiction.locator(".be-tip")).to_be_visible()
    # + Block goes to the palette's search (round 8: adding a block was not obvious).
    expect(page.locator(".be-palette-head")).to_contain_text("Add a block")
    page.locator(".be-tool-add").click()
    expect(page.get_by_role("textbox", name="Search blocks")).to_be_focused()
    # The libraries start folded; one opens at a time.
    expect(page.locator(".be-palette-item")).to_have_count(0)
    page.locator(".be-lib-toggle", has_text="Data quality").click()
    expect(page.locator(".be-palette-item", has_text="Frozen value")).to_be_visible()
    page.locator(".be-lib-toggle", has_text="Inputs").click()
    expect(page.locator(".be-palette-item", has_text="Frozen value")).to_have_count(0)
    # Values on the wires only when asked.
    expect(page.locator(".react-flow__edge-text")).to_have_count(0)
    page.get_by_role("button", name="Values on wires").click()
    expect(page.locator(".react-flow__edge-text").first).to_be_visible()
    if screenshots:
        page.screenshot(path=str(screenshots / "algorithm-editor-test.png"))
    # A block's own page in the inspector: what entered it and what left it, over time.
    stiction.locator("header").click()
    expect(page.locator(".be-test-run .be-chart svg").first).to_be_visible()
    if screenshots:
        page.screenshot(path=str(screenshots / "algorithm-editor-block.png"))
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.locator(".alg-window-notice.notice-ok")).to_contain_text("Saved")
    expect(page).to_have_url(re.compile(r"/link/editor/flow_loop_copy$"))
    page.goto(f"{app_url}/link/algorithms")
    # The copy keeps the tags and is the site's: its author is the person, version 1.
    row = page.locator("tr", has=page.get_by_role("link", name="Flow loop (copy)", exact=True))
    expect(row.locator(".tag", has_text="control loop")).to_be_visible()
    expect(row.get_by_text("PlantCraft", exact=True)).to_have_count(0)
    page.goto(f"{app_url}/link/schedules/new")
    page.get_by_role("textbox", name="Name").fill("Valve copy hourly")
    page.get_by_role("combobox", name=re.compile("^Algorithm")).select_option("flow_loop_copy")
    page.get_by_role("button", name="Create monitor").click()
    expect(page.get_by_role("heading", name="Valve copy hourly")).to_be_visible()
    page.goto(f"{app_url}/link/schedules")
    expect(page.get_by_role("link", name="Valve copy hourly")).to_be_visible()


def test_a_unit_twin_is_calibrated_in_the_editor_and_saved(signed_in, app_url, screenshots):
    """Unit twin copied in the editor window, its Deviation block calibrated on a loop asset over a
    period of the recorded plant from the block's inspector, then saved; its assets are chosen on
    its page (round 8)."""

    page = signed_in
    page.set_viewport_size({"width": 2000, "height": 1150})
    page.goto(f"{app_url}/link/editor/new?from=unit_twin")
    expect(page.locator(".alg-window-title b")).to_have_text("Unit twin (copy)")
    page.locator('.be-node[data-block="model.deviation"] header').click()
    tool = page.locator(".be-inspector-tools .calibrate")
    tool.locator("label", has_text="Asset").locator("select").select_option("fic-101")
    expect(tool).to_contain_text("Not calibrated yet")
    tool.locator("label", has_text="From").locator("input").fill("2026-10-01T07:00")
    tool.locator("label", has_text="To").locator("input").fill("2026-10-01T09:00")
    tool.get_by_role("button", name="Calibrate").click()
    expect(tool).to_contain_text("Calibrated on", timeout=60_000)
    expect(tool.locator(".calibrate-outputs li")).to_have_count(1)
    if screenshots:
        page.screenshot(path=str(screenshots / "algorithm-editor-calibrate.png"))
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.locator(".alg-window-notice.notice-ok")).to_contain_text("Saved")
    expect(page).to_have_url(re.compile(r"/link/editor/unit_twin_copy$"))
    # Its assets on its page, Used by: saving them is a new version.
    page.goto(f"{app_url}/link/algorithms/unit_twin_copy/used-by")
    page.locator(".asset-picker select").select_option("fic-101")
    page.locator(".asset-picker").get_by_role("button", name="Add").click()
    page.get_by_role("button", name="Save as new version").click()
    page.get_by_role("link", name="Versions", exact=True).click()
    expect(
        page.locator(".pc-versions").get_by_role("button", name=re.compile("Version 2"))
    ).to_be_visible()
    # New version: one form with the diagram inside, saved with its own name (D19).
    page.get_by_role("link", name="New version", exact=True).click()
    expect(page).to_have_url(re.compile(r"/link/algorithms/unit_twin_copy/edit$"))
    expect(page.locator("#alg-edit-diagram .be-editor .react-flow__node").first).to_be_visible()
    expect(page.locator("#alg-edit-diagram .be-palette")).to_be_visible()
    page.locator("#alg-description").fill("Edited in the new version form.")
    if screenshots:
        page.screenshot(path=str(screenshots / "algorithm-new-version.png"), full_page=True)
    page.get_by_role("button", name="Save as version 3").click()
    dialog = page.get_by_role("dialog", name="Save as version 3")
    dialog.locator("#alg-version-name").fill("New text")
    dialog.locator("#alg-version-note").fill("Says where it was edited.")
    dialog.get_by_role("button", name="Save as version 3").click()
    expect(page).to_have_url(re.compile(r"/link/algorithms/unit_twin_copy$"))
    expect(page.get_by_text("Edited in the new version form.").first).to_be_visible()
    # A version opens the page at that version; Use this version saves it as the newest.
    page.get_by_role("link", name="Versions", exact=True).click()
    versions = page.locator(".pc-versions")
    expect(versions.get_by_text("Says where it was edited.")).to_be_visible()
    versions.get_by_role("button", name=re.compile("Version 2")).click()
    expect(page).to_have_url(re.compile(r"/link/algorithms/unit_twin_copy\?version=2$"))
    expect(page.locator(".blk-shown")).to_contain_text("Showing version 2")
    page.locator(".blk-shown").get_by_role("button", name="Use this version").click()
    expect(page).to_have_url(re.compile(r"/link/algorithms/unit_twin_copy$"))
    expect(page.locator(".blk-shown")).to_have_count(0)
    expect(page.get_by_text("Edited in the new version form.")).to_have_count(0)
    # Compare versions (D18): versions 1 and 3 on the same asset and window.
    page.get_by_role("link", name="Versions", exact=True).click()
    picker = page.get_by_role("region", name="Compare versions")
    picker.get_by_role("checkbox", name="Version 1").check()
    picker.get_by_role("checkbox", name="Version 3").check()
    picker.get_by_role("button", name="Compare 2 versions").click()
    expect(page).to_have_url(re.compile(r"/unit_twin_copy/compare\?versions=1,3$"))
    page.get_by_role("button", name="Run and compare").click()
    compared = page.locator(".compare-view")
    expect(compared.get_by_role("heading", name="What each version said")).to_be_visible(
        timeout=30_000
    )
    expect(compared.get_by_role("columnheader", name="Version 3").first).to_be_visible()
    if screenshots:
        page.wait_for_timeout(500)
        page.screenshot(path=str(screenshots / "algorithm-compare.png"), full_page=True)

    # A schedule says what each execution records and for how long, with the cost, before it
    # is saved (round 8, D6).
    page.goto(f"{app_url}/link/schedules/new")
    page.get_by_role("textbox", name="Name").fill("Twin review")
    page.get_by_role("combobox", name=re.compile("^Algorithm")).select_option("unit_twin_copy")
    page.get_by_role("textbox", name="Add an asset").fill("fic-101")
    page.locator(".schedule-assets li button", has_text="fic-101").first.click()
    section = page.locator(
        ".schedule-section", has=page.locator("legend", has_text="Recorded outputs")
    )
    rows = section.locator(".schedule-outputs > li")
    expect(rows).to_have_count(3)
    # The twin's prediction, its residual and the T² over the window: whole series, the last
    # 10 executions by default.
    expect(rows.filter(has_text="A whole series per run")).to_have_count(3)
    series = rows.filter(has_text="residual")
    expect(series.locator("select")).to_have_value("runs:10")
    expect(series.locator(".schedule-output-cost")).to_contain_text("values a day")
    expect(section.locator(".schedule-output-total")).to_contain_text("In all, on 1 asset:")
    rows.filter(has_text="predicted").locator("input[type=checkbox]").uncheck()
    series.locator("select").select_option("runs:3")
    if screenshots:
        page.screenshot(path=str(screenshots / "schedule-recorded-outputs.png"), full_page=True)
    page.get_by_role("button", name="Create monitor").click()
    expect(page.get_by_role("heading", name="Twin review")).to_be_visible()
    rows = page.locator(".schedule-outputs > li")
    expect(rows.filter(has_text="residual").locator("select")).to_have_value("runs:3")
    expect(rows.filter(has_text="predicted").locator("input[type=checkbox]")).not_to_be_checked()


def test_the_first_visit_opens_links_own_tour(browser, fake, app_url):
    """An app's tour opens the first time someone comes in, walks its pages, and not again."""

    from plantcraft_sdk.contract import TOKEN_COOKIE

    context = browser.new_context(viewport={"width": 1440, "height": 900})
    context.add_cookies([{"name": TOKEN_COOKIE, "value": fake.token("engineer"), "url": app_url}])
    page = context.new_page()
    page.goto(f"{app_url}/link/blocks")
    tour = page.get_by_role("dialog")
    expect(tour.get_by_role("heading", name="Welcome to Analytics")).to_be_visible()
    # the welcome stays on the page the visitor opened; Next walks the app
    assert page.url.endswith("/link/blocks")
    tour.get_by_role("button", name="Start the tour").click()
    expect(tour.get_by_role("heading", name="Overview")).to_be_visible()
    tour.get_by_role("button", name="Next").click()
    expect(tour.get_by_role("heading", name="Blocks")).to_be_visible()
    expect(page).to_have_url(re.compile(r"/link/blocks$"))
    tour.get_by_role("button", name="Skip the tour").click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    page.reload()
    expect(page.locator(".pcs-content h1").first).to_be_visible()
    expect(page.get_by_role("dialog")).to_have_count(0)
    context.close()


def test_executions_go_schedule_then_asset_then_its_history(signed_in, app_url, screenshots):
    """Executions: the schedules, a schedule's assets by name with a word for
    their status, then one asset's latest result, its series over time and past executions."""

    page = signed_in
    page.goto(f"{app_url}/link/executions")
    expect(page.get_by_role("heading", name="Results", exact=True).first).to_be_visible()
    page.get_by_role("link", name="Control loop performance").first.click()
    expect(page).to_have_url(re.compile(r"/link/executions/round-cpm$"))
    subjects = page.locator(".pc-dt tbody tr")
    expect(subjects.first.locator(".status-word")).to_be_visible()
    subjects.first.locator("a").first.click()
    expect(page).to_have_url(re.compile(r"/link/executions/round-cpm/.+"))
    # Each output on its own, not only the health (round 9, D11).
    outputs = page.get_by_role("region", name="Outputs")
    expect(outputs.get_by_text("Stiction screening")).to_be_visible()
    expect(outputs.locator("tbody tr .status-word").first).to_be_visible()
    expect(page.get_by_role("heading", name="Over time")).to_be_visible()
    if screenshots:
        page.screenshot(path=str(screenshots / "executions-subject.png"), full_page=True)
    # Any output it records, over the period chosen (round 10).
    expect(page.locator("#subject-output option").first).to_have_text(re.compile("Health"))
    page.locator(".pc-period select").select_option("24h")
    expect(page.locator(".subject-chart")).to_be_visible()
    # Two tabs: the last run opens in the runs, on the diagram (round 10).
    expect(page.locator(".pcs-tabs a")).to_have_text(["Overview", "Runs"])
    expect(page.get_by_role("link", name="Loop page")).to_be_visible()
    page.get_by_role("link", name="Open the last run").click()
    expect(page).to_have_url(re.compile(r"\?tab=runs&run=.+"))
    nodes = page.locator(".alg-diagram .react-flow__node")
    expect(nodes.first).to_be_visible(timeout=15_000)
    expect(page.get_by_text("Click a block to see its charts")).to_be_visible()
    # A block's wires keep their samples on the last runs: its charts draw.
    nodes.first.click()
    expect(page.locator(".be-test-run .be-chart svg").first).to_be_visible(timeout=10_000)
    if screenshots:
        page.wait_for_timeout(500)
        page.screenshot(path=str(screenshots / "executions-last-run.png"), full_page=True)
    # The runs of a round open too, the last ones with their samples.
    page.get_by_role("link", name="All runs").click()
    rows = page.locator(".pc-dt tbody tr")
    expect(rows.first.get_by_role("link", name="Open")).to_be_visible()
    rows.first.click()
    expect(page.locator(".alg-diagram .react-flow__node").first).to_be_visible(timeout=15_000)


def test_a_run_opens_inside_its_execution(signed_in, app_url, screenshots):
    """Runs a person asked for are kept: one opens in the execution with its diagram; a run
    retention deleted says so (round 9, D22)."""

    page = signed_in
    page.goto(f"{app_url}/link/executions/manual/fic-101?tab=runs")
    rows = page.locator(".pc-dt tbody tr")
    expect(rows.first).to_be_visible()
    rows.first.click()
    expect(page).to_have_url(re.compile(r"tab=runs&run=.+"))
    expect(page.locator(".run-facts")).to_contain_text("Version")
    expect(page.locator(".alg-diagram .react-flow__node").first).to_be_visible(timeout=15_000)
    page.get_by_role("button", name="Show every sample").click()
    expect(page.get_by_text("Every sample of this window, run again just now")).to_be_visible(
        timeout=30_000
    )
    if screenshots:
        page.wait_for_timeout(500)
        page.screenshot(path=str(screenshots / "executions-run.png"), full_page=True)
    page.goto(f"{app_url}/link/executions/manual/fic-101?tab=runs&run=gone")
    expect(page.get_by_text("This run's diagram is no longer kept")).to_be_visible()


def test_executions_show_the_queue_and_every_execution(signed_in, app_url, screenshots):
    """The Queue tab: the queue's panel (now and over time) above every execution, newest first."""

    page = signed_in
    page.goto(f"{app_url}/link/executions")
    page.get_by_role("link", name="Queue", exact=True).click()
    expect(page).to_have_url(re.compile(r"/link/executions/queue$"))
    panel = page.locator(".pc-queue")
    expect(panel.get_by_text("In the queue").first).to_be_visible()
    expect(panel.get_by_text("Running").first).to_be_visible()
    expect(page.locator(".pc-dt tbody tr").first).to_be_visible()
    page.wait_for_timeout(500)
    if screenshots:
        page.screenshot(path=str(screenshots / "executions.png"), full_page=True)


def test_a_schedule_is_made_on_its_own_page_with_a_preview(signed_in, app_url, screenshots):
    """New schedule opens a full page in four parts (what it runs, when, if it fails, owner and
    priority); a calendar every 15 minutes on weekdays between two times reads back in words in
    the preview with the next occurrences; saving lands on the schedule's page (round 8)."""

    page = signed_in
    page.goto(f"{app_url}/link/schedules")
    expect(page.get_by_role("link", name="Control loop performance")).to_be_visible()
    if screenshots:
        page.screenshot(path=str(screenshots / "schedules.png"), full_page=True)
    page.get_by_role("link", name="New monitor").click()
    expect(page).to_have_url(re.compile(r"/link/schedules/new$"))
    page.get_by_role("textbox", name="Name").fill("Night run")
    for legend in ["What it runs", "When", "If it fails", "Owner and priority"]:
        expect(page.locator(".schedule-section > legend", has_text=legend)).to_have_count(1)
    # A real form (D21): each part's title on the left of its fields, the page's whole width.
    first = page.locator(".schedule-part").first
    head = first.locator(".schedule-part-head").bounding_box()
    body = first.locator(".schedule-part-body").bounding_box()
    assert (
        head and body and head["x"] + head["width"] <= body["x"] and abs(head["y"] - body["y"]) < 4
    )
    section = page.locator(".schedule-section").first.bounding_box()
    assert section and section["width"] > 900
    page.get_by_role("combobox", name=re.compile("^Runs")).select_option("minutes")
    page.get_by_role("spinbutton", name=re.compile("^Every")).fill("15")
    only_on = page.get_by_role("group", name="Only on")
    for day in ["Mon", "Tue", "Wed", "Thu", "Fri"]:
        only_on.get_by_role("button", name=day).click()
    page.get_by_role("checkbox", name="Only between two times of day").check()
    zone = page.get_by_role("combobox", name=re.compile("^Time zone"))
    expect(zone.locator("option").first).to_contain_text("Local time")
    expect(zone.locator("option[value='UTC']")).to_have_count(1)
    expect(page.get_by_role("checkbox", name=re.compile("^Try again"))).to_be_checked()
    page.get_by_role("spinbutton", name=re.compile("^Spread over")).fill("30")
    # The preview sits under the timing it describes (round 9, D10), not beside the form.
    preview = page.locator(".schedule-section .schedule-preview")
    expect(preview).to_contain_text("Every 15 minutes, Mon to Fri, 06:00 to 18:00")
    expect(preview).to_contain_text("runs each occurrence")
    expect(preview.locator("li")).to_have_count(5)
    page.wait_for_timeout(300)
    if screenshots:
        page.screenshot(path=str(screenshots / "schedule-new.png"), full_page=True)
        page.emulate_media(color_scheme="dark")
        page.screenshot(path=str(screenshots / "schedule-new-dark.png"), full_page=True)
        page.emulate_media(color_scheme="light")
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(400)
    if screenshots:
        page.screenshot(path=str(screenshots / "schedule-new-phone.png"), full_page=True)
    head = first.locator(".schedule-part-head").bounding_box()
    body = first.locator(".schedule-part-body").bounding_box()
    assert head and body and body["y"] >= head["y"] + head["height"] - 1
    page.set_viewport_size({"width": 1440, "height": 900})
    page.get_by_role("button", name="Create monitor").click()
    expect(page).to_have_url(re.compile(r"/link/schedules/[0-9a-f-]{36}$"))
    expect(page.get_by_role("heading", name="Night run")).to_be_visible()
    expect(page.get_by_role("combobox", name=re.compile("^Runs"))).to_have_value("minutes")
    expect(
        page.get_by_role("group", name="Only on").get_by_role("button", name="Sat")
    ).to_have_attribute("aria-pressed", "false")
    page.get_by_role("button", name="Run now").click()
    expect(page.get_by_text("Queued: it runs ahead of the monitors.")).to_be_visible()
    # The round's window is Link's default, not a 0 that cannot be saved.
    page.goto(f"{app_url}/link/schedules")
    page.get_by_role("link", name="Control loop performance").click()
    window = page.get_by_role("spinbutton", name=re.compile("^Data window"))
    expect(window).to_have_attribute("placeholder", "Analytics' default")


def test_results_filter_by_tag_and_print_what_they_keep(signed_in, app_url, screenshots):
    """Results of any algorithm: filters by algorithm, tag, asset type,
    group and status; Report prints what the filter keeps; nothing loop-specific."""

    page = signed_in
    page.goto(f"{app_url}/link/results?tag=control%20loop")
    table = page.locator(".results-table table")
    expect(table.locator("tbody tr").first).to_be_visible()
    expect(table.locator(".tag", has_text="data quality")).to_have_count(0)
    expect(page.get_by_role("button", name="New loop")).to_have_count(0)
    report = page.get_by_role("link", name="Report")
    expect(report).to_have_attribute("href", re.compile(r"/api/reports/results\.pdf\?tag=control"))
    if screenshots:
        page.screenshot(path=str(screenshots / "results-by-tag.png"), full_page=True)
    with page.expect_download() as info:
        report.click()
    with open(info.value.path(), "rb") as handle:
        assert handle.read(5) == b"%PDF-"


def test_folders_hold_algorithms_and_schedules_and_moving_is_deliberate(
    signed_in, app_url, screenshots
):
    """Folders (round 9, D14): made on the list, an object moved with Move to folder (who moved
    it is kept), an execution under its schedule's folder; blocks keep their libraries."""

    page = signed_in
    page.goto(f"{app_url}/link/algorithms")
    column = page.get_by_role("navigation", name="Folders")
    column.get_by_role("button", name="New folder").click()
    page.locator("#pc-folder-name").fill("Valve checks")
    page.get_by_role("button", name="Make the folder").click()
    expect(page).to_have_url(re.compile(r"/link/algorithms\?folder=.+"))
    expect(page.get_by_text("No algorithm in this folder.")).to_be_visible()
    page.goto(f"{app_url}/link/algorithms/flow_loop")
    line = page.locator(".pc-folder-place")
    expect(line).to_contain_text("In no folder")
    line.get_by_role("button", name="Move to folder").click()
    page.locator("#pc-folder-target").select_option(label="Valve checks")
    page.get_by_role("button", name="Move", exact=True).click()
    expect(line).to_contain_text("Valve checks")
    expect(line).to_contain_text("moved by")
    line.get_by_role("link", name="Valve checks").click()
    expect(page.locator(".pc-dt tbody tr")).to_have_count(1)
    expect(page.locator(".pc-dt tbody")).to_contain_text("Flow loop")
    if screenshots:
        page.screenshot(path=str(screenshots / "folders-algorithms.png"), full_page=True)
    # Schedules have their own folders; Executions shows them, made on Schedules.
    page.goto(f"{app_url}/link/schedules")
    page.get_by_role("navigation", name="Folders").get_by_role("button", name="New folder").click()
    page.locator("#pc-folder-name").fill("Daily")
    page.get_by_role("button", name="Make the folder").click()
    page.goto(f"{app_url}/link/executions")
    executions = page.get_by_role("navigation", name="Folders")
    expect(executions.get_by_role("button", name=re.compile("Daily"))).to_be_visible()
    expect(executions.get_by_role("button", name="New folder")).to_have_count(0)
    # Blocks have libraries only, no folders (round 10).
    page.goto(f"{app_url}/link/blocks")
    blocks = page.get_by_role("navigation", name="Libraries")
    expect(blocks.get_by_role("heading", name="Libraries")).to_be_visible()
    expect(blocks.get_by_role("heading", name="Folders")).to_have_count(0)
    if screenshots:
        page.screenshot(path=str(screenshots / "folders-blocks.png"), full_page=True)
