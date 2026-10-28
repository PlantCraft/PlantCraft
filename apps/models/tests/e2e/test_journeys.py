"""The main journeys in a real browser: sign-in, the Overview, the models, a model's block
diagram with its simulation settings, a run and its plot, a copy of an example changed and
saved, a grid study ranked by an indicator, Executions with the queue and the groups, the
blocks, the Modelica code, an FMU export, the addresses of earlier versions, an asset's page,
help and the guided tour."""

from __future__ import annotations

import os
import re

import pytest

try:
    from playwright.sync_api import expect
except ImportError:
    if os.environ.get("MODELCRAFT_E2E_REQUIRED") == "1":
        raise
    pytest.skip("Playwright is not installed", allow_module_level=True)

SLOW = 60_000
TLC = "PlantCraftExamples.TankLevelControl"


def _shot(page, screenshots, name):
    if screenshots:
        page.wait_for_timeout(800)
        page.screenshot(path=str(screenshots / f"{name}.png"), full_page=True)


def _open_model(page, app_url, name="TankLevelControl"):
    page.goto(f"{app_url}/model/models")
    page.locator("tbody tr", has_text=name).first.click()
    expect(page.get_by_role("heading", name=name, exact=True)).to_be_visible(timeout=SLOW)
    expect(page.get_by_role("navigation", name="Model")).to_be_visible(timeout=SLOW)


def _tab(page, name):
    page.get_by_role("navigation", name=re.compile("^(Model|Block)$")).get_by_role(
        "link", name=re.compile(f"^{name}")
    ).click()


def _save_version(page, number, name):
    """Save the page's changes as a new version: its name (and what changed) in the dialog,
    as Analytics' algorithms ask (#316)."""

    page.get_by_role("button", name=re.compile(f"^Save as version {number}")).click()
    dialog = page.get_by_role("dialog", name=f"Save as version {number}")
    # What changed is asked every time; the name is optional (owner, 2026-10-27).
    dialog.get_by_label("What changed").fill(f"{name}: a test change")
    dialog.get_by_label("Version name").fill(name)
    dialog.get_by_role("button", name=f"Save as version {number}").click()
    expect(dialog).to_have_count(0, timeout=SLOW)


def test_a_browser_without_a_token_is_sent_to_sign_in(anonymous, app_url):
    anonymous.goto(f"{app_url}/model/")
    assert re.search(r"/login\?next=/model/", anonymous.url), anonymous.url


def test_the_overview_shows_the_widgets(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/model/")
    expect(page.get_by_role("heading", name="Overview")).to_be_visible()
    titles = page.locator(".pc-wg-card-head h2")
    for title in (
        "Simulations per day",
        "Latest study",
        "Models",
        "Latest simulations",
        "Studies",
    ):
        expect(titles.filter(has_text=re.compile(f"^{title}$"))).to_have_count(1, timeout=SLOW)
    # The runner takes no card: a notice says so only while it is down.
    expect(titles.filter(has_text="Modelica runner")).to_have_count(0)
    expect(page.get_by_text("The Modelica runner is not available")).to_have_count(0)
    activity = page.get_by_role("article", name="Simulations per day")
    expect(activity).to_contain_text("simulations in 14 days", timeout=SLOW)
    # Owner, 2026-10-24: one level of menu, no sub-items.
    nav = page.locator(".pcs-nav")
    for name in ("Overview", "Models", "Studies", "Simulations", "Blocks"):
        expect(nav.get_by_role("link", name=name, exact=True)).to_be_visible()
    expect(page.locator(".pcs-nav-children")).to_have_count(0)
    _shot(page, screenshots, "0-overview")
    # No buttons on top (owner, 2026-10-27): New model is on Models, a page of its own (round 9),
    # as Link's New block: import a file or fill in the form.
    expect(page.get_by_role("link", name="New model")).to_have_count(0)
    page.goto(f"{app_url}/model/models")
    page.get_by_role("link", name="New model").click()
    expect(page).to_have_url(re.compile(r"/model/models/new$"))
    expect(page.get_by_role("button", name=re.compile("^Import a file"))).to_be_visible()
    page.get_by_role("button", name=re.compile("^Fill in the form")).click()
    expect(page.locator("#mcn-name")).to_be_visible()
    _shot(page, screenshots, "0-new-model")


def test_the_models_page_lists_the_examples(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/model/models")
    expect(page.get_by_role("heading", name="Models", exact=True)).to_be_visible()
    rows = page.locator("tbody")
    for name in ("TankLevelControl", "HeatExchangerOutlet", "FirstOrderDeadTimeLoop"):
        expect(rows).to_contain_text(name, timeout=SLOW)
    expect(page.locator("tbody tr", has_text="TankLevelControl").first).to_contain_text("8")
    # One kind of model: one written as code is one block (owner, 2026-10-24).
    expect(rows).to_contain_text("1 (code)")
    _shot(page, screenshots, "1-models")


def test_a_model_is_a_diagram_run_with_its_settings(signed_in, app_url, screenshots):
    page = signed_in
    _open_model(page, app_url)
    # Overview: what it is, no results and no Run on top; the inputs and outputs and the diagram
    # have tabs of their own, as Analytics' algorithms (owner, 2026-10-27).
    expect(page.locator(".mc-model-about")).to_contain_text("Shown by the scopes")
    expect(page.get_by_role("button", name="Run", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="New study")).to_have_count(0)
    _tab(page, "Inputs and outputs")
    expect(page.locator(".mc-contract")).to_contain_text("Shown by the scopes")
    expect(page.locator(".mc-value-source").first).to_be_visible()
    _tab(page, "Diagram")
    expect(page.locator(".be-node")).to_have_count(8, timeout=SLOW)
    _tab(page, "Settings")
    settings = page.locator(".mc-sim-settings")
    expect(settings).to_contain_text("Simulation settings")
    expect(settings.get_by_label("Stop")).to_have_value("3600")
    # An example stays as shipped: its diagram and settings are read-only.
    expect(page.locator(".pcs-content")).to_contain_text("Duplicate it to change it")
    expect(settings.get_by_label("Stop")).to_be_disabled()
    expect(page.get_by_role("region", name="About it")).to_be_visible()
    _shot(page, screenshots, "2-model")
    # Test: one simulation, a check (the studies run it for real).
    _tab(page, "Test")
    page.get_by_role("button", name="Run the test").click()
    results = page.locator(".mc-model-results")
    expect(results).to_contain_text("Done", timeout=SLOW)
    expect(results.locator(".js-plotly-plot")).to_have_count(1, timeout=SLOW)
    _shot(page, screenshots, "3-model-run")
    # The run's own page, under Executions.
    results.locator("a").first.click()
    expect(page.locator(".mc-variables")).to_contain_text("level", timeout=SLOW)
    expect(page.locator(".breadcrumb")).to_contain_text("Simulations")


def test_a_copy_of_an_example_is_changed_and_saved(signed_in, app_url, screenshots):
    page = signed_in
    _open_model(page, app_url)
    page.get_by_role("button", name="Duplicate").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Name").fill("Feed tank level")
    dialog.get_by_role("button", name=re.compile("Duplicate|Create")).click()
    expect(page.get_by_role("heading", name="Feed tank level")).to_be_visible(timeout=SLOW)
    # Parameters and settings change on the page, without the editor.
    _tab(page, "Settings")
    settings = page.locator(".mc-sim-settings")
    settings.get_by_label("Stop").fill("1800")
    # Round 9: saving the inputs makes a new version, listed in the Versions tab.
    _save_version(page, 2, "Shorter run")
    _tab(page, "Versions")
    versions = page.locator(".pc-versions")
    expect(versions).to_contain_text("Version 2", timeout=SLOW)
    expect(versions.locator(".tag", has_text="current")).to_have_count(1)
    _tab(page, "Settings")
    page.reload()
    expect(page.locator(".mc-sim-settings").get_by_label("Stop")).to_have_value(
        "1800", timeout=SLOW
    )
    _shot(page, screenshots, "4-model-copy")
    # The editor opens in a window of its own.
    _tab(page, "Diagram")
    with page.expect_popup() as opened:
        page.get_by_role("button", name="Open the editor").click()
    editor = opened.value
    expect(editor.locator(".mc-window-bar")).to_contain_text("Feed tank level", timeout=SLOW)
    expect(editor.locator(".be-node")).to_have_count(8, timeout=SLOW)
    expect(editor.get_by_role("button", name="Save")).to_be_disabled()
    _shot(editor, screenshots, "4-model-editor")
    editor.close()
    page.goto(f"{app_url}/model/models")
    expect(page.locator("tbody")).to_contain_text("Feed tank level", timeout=SLOW)


def test_a_models_versions_open_compare_and_come_back(signed_in, app_url, screenshots):
    """Round 9 M4, as Link's algorithms: open an older version read-only, run two versions on
    the same simulation settings, and use the older one again (saved as the newest)."""

    page = signed_in
    _open_model(page, app_url)
    page.get_by_role("button", name="Duplicate").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Name").fill("Versioned tank")
    dialog.get_by_role("button", name=re.compile("Duplicate|Create")).click()
    expect(page.get_by_role("heading", name="Versioned tank")).to_be_visible(timeout=SLOW)
    _tab(page, "Settings")
    page.locator(".mc-sim-settings").get_by_label("Stop").fill("1800")
    _save_version(page, 2, "Shorter run")
    _tab(page, "Versions")
    versions = page.locator(".pc-versions")
    expect(versions).to_contain_text("Version 2", timeout=SLOW)
    versions.get_by_role("button", name=re.compile("^Version 1")).click()
    notice = page.locator(".mc-version-notice")
    expect(notice).to_contain_text("Version 1 of 2", timeout=SLOW)
    _tab(page, "Settings")
    expect(page).to_have_url(re.compile(r"/settings\?version=1$"))
    expect(page.locator(".mc-sim-settings").get_by_label("Stop")).to_have_value(
        "3600", timeout=SLOW
    )
    _shot(page, screenshots, "15-model-version")
    # Compare: both run on the experiment of the version in use.
    _tab(page, "Versions")
    picker = page.get_by_role("region", name="Compare versions")
    picker.get_by_label("Version 1").check()
    picker.get_by_label("Version 2").check()
    picker.get_by_role("button", name="Compare 2 versions").click()
    expect(page).to_have_url(re.compile(r"/compare\?versions=1,2$"))
    page.get_by_role("button", name="Run and compare").click()
    table = page.locator(".mc-compare-table")
    expect(table.locator("tbody tr")).to_have_count(2, timeout=SLOW)
    expect(table).to_contain_text("Version 1")
    expect(table.locator("tbody")).not_to_contain_text("Queued", timeout=SLOW)
    expect(page.locator(".mc-compare .js-plotly-plot")).to_be_visible(timeout=SLOW)
    _shot(page, screenshots, "16-model-compare")
    # Use version 1 again: it comes back as version 3.
    page.goto(page.url.split("/compare")[0] + "?version=1")
    page.get_by_role("button", name="Use this version").click()
    page.get_by_role("alertdialog").get_by_role("button", name="Use this version").click()
    expect(page.locator(".mc-version-notice")).to_have_count(0, timeout=SLOW)
    expect(page.get_by_role("link", name="Versions (3)")).to_be_visible(timeout=SLOW)


def test_a_grid_study_ranks_its_runs(signed_in, app_url, screenshots):
    # Round 8 M2: a study starts from the Studies page, on a page of its own, with any model.
    page = signed_in
    page.goto(f"{app_url}/model/studies")
    # Round 9 (D13): an example study comes ready, its three simulations run.
    example_row = page.locator("tbody tr", has_text="Example: controller gain")
    expect(example_row).to_have_count(1, timeout=SLOW)
    expect(example_row).to_contain_text("3", timeout=SLOW)
    page.locator("main").get_by_role("link", name="New study").click()
    expect(page.get_by_role("heading", name="New study")).to_be_visible(timeout=SLOW)
    page.get_by_label("Model", exact=True).select_option(label="TankLevelControl")
    form = page.locator(".mc-study-form")
    form.get_by_label("Name").fill("Tank size")
    form.get_by_label("How tank.A is set").select_option("range", timeout=SLOW)
    form.get_by_label("From value of tank.A").fill("2")
    form.get_by_label("To value of tank.A").fill("6")
    form.get_by_label("How many values of tank.A").fill("5")
    form.get_by_label("How tank.Cv is set").select_option("list")
    form.get_by_label("Values of tank.Cv").fill("0.03 0.05 0.08")
    expect(form.locator(".mc-study-count")).to_contain_text("15 simulations", timeout=SLOW)
    expect(form.locator(".mc-study-sweep")).to_contain_text("5 values from 2 to 6")
    _shot(page, screenshots, "5-new-study")
    form.get_by_role("button", name="Start the study").click()

    expect(page.get_by_role("heading", name="Tank size")).to_be_visible(timeout=SLOW)
    expect(page.locator(".mc-study-bar")).to_contain_text("15 done", timeout=SLOW)
    ranking = page.locator(".mc-ranking")
    expect(ranking.locator(".mc-best-line")).to_contain_text("Best", timeout=SLOW)
    expect(ranking.locator("tbody tr")).to_have_count(15)
    expect(ranking.locator("tr.mc-best")).to_have_count(1)
    ranking.get_by_label("Statistic").select_option("overshoot")
    expect(ranking.locator("thead")).to_contain_text("Overshoot")
    _shot(page, screenshots, "6-study-ranking")
    # Side by side: one chart per tank.A value, each with its three tank.Cv runs.
    page.get_by_label("Variable", exact=True).fill("tank.level")
    page.get_by_label("Side by side").select_option("tank.A")
    charts = page.get_by_test_id("side-by-side").locator(".mc-side-chart")
    expect(charts).to_have_count(5, timeout=SLOW)
    expect(charts.first).to_contain_text("3 simulations")
    _shot(page, screenshots, "6b-study-side-by-side")
    expect(page.locator(".pcs-tabs")).to_have_count(0)
    page.locator(".mc-statistics summary").click()
    expect(page.locator(".mc-stats")).to_contain_text("sensor.y", timeout=SLOW)
    with page.expect_download() as download:
        page.get_by_role("link", name="Export for Jupyter").click()
    assert download.value.suggested_filename.endswith(".zip")


def test_executions_show_the_queue_and_the_groups(signed_in, app_url, screenshots):
    # Round 8 M3: Link's Executions with the study in the schedule's place and the simulation
    # in the asset's (the demo's "Tank size", started here through the API).
    page = signed_in
    projects = page.request.get(f"{app_url}/model/api/projects").json()
    examples = next(item for item in projects if item["name"] == "Examples")
    started = page.request.post(
        f"{app_url}/model/api/projects/{examples['id']}/studies",
        data={
            "model": "PlantCraftExamples.TankLevelControl",
            "name": "Tank size (demo)",
            "start": 0,
            "stop": 3600,
            "intervals": 720,
            "sweep": [
                {"name": "tank.A", "mode": "range", "start": 2, "stop": 6, "count": 5},
                {"name": "tank.Cv", "mode": "list", "values": [0.03, 0.05, 0.08]},
            ],
            "indicators": ["tank.level"],
        },
    )
    assert started.ok, started.text()
    _open_model(page, app_url, "HeatExchangerOutlet")
    _tab(page, "Test")
    page.get_by_role("button", name="Run the test").click()
    expect(page.locator(".mc-model-results")).to_contain_text("Done", timeout=SLOW)
    page.goto(f"{app_url}/model/executions")
    expect(page.get_by_role("heading", name="Simulations")).to_be_visible()
    example = page.locator("tbody tr", has_text="Tank size (demo)")
    expect(example).to_contain_text("tank.A 5 values from 2 to 6", timeout=SLOW)
    expect(example).to_contain_text("15 done", timeout=SLOW)
    expect(
        page.locator("tbody tr", has_text="Single simulations of HeatExchangerOutlet")
    ).to_be_visible()
    _shot(page, screenshots, "7-executions")
    example.click()
    expect(page.get_by_role("heading", name="Tank size (demo)")).to_be_visible(timeout=SLOW)
    summary = page.get_by_role("region", name="Summary")
    expect(summary).to_contain_text("TankLevelControl")
    expect(summary).to_contain_text("tank.Cv 3 values")
    expect(page.get_by_role("table", name="Simulations").locator("tbody tr")).to_have_count(15)
    _shot(page, screenshots, "7b-execution-group")
    page.get_by_role("table", name="Simulations").locator(
        "tbody tr", has_text="A=4, Cv=0.05"
    ).click()
    expect(page).to_have_url(re.compile("/runs/"), timeout=SLOW)
    page.goto(f"{app_url}/model/executions/queue")
    expect(page.locator(".pc-queue")).to_be_visible(timeout=SLOW)
    expect(page.get_by_role("table", name="Simulations")).to_contain_text("HeatExchangerOutlet")
    _shot(page, screenshots, "7c-executions-queue")
    page.goto(f"{app_url}/model/executions")
    page.locator("tbody tr", has_text="Single simulations of HeatExchangerOutlet").click()
    expect(
        page.get_by_role("heading", name="Single simulations of HeatExchangerOutlet")
    ).to_be_visible(timeout=SLOW)
    page.get_by_role("link", name="Open the model").click()
    expect(page.get_by_role("heading", name="HeatExchangerOutlet")).to_be_visible(timeout=SLOW)


def test_the_blocks_by_library_and_one_block(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/model/blocks")
    libraries = page.get_by_role("navigation", name="Libraries and folders")
    for name in ("Sources", "Math", "Continuous", "Control", "Process equipment", "Sinks"):
        expect(libraries).to_contain_text(name, timeout=SLOW)
    libraries.get_by_role("button", name=re.compile("Process equipment")).click()
    expect(page.locator(".mc-block-card", has_text="Tank").first).to_be_visible()
    _shot(page, screenshots, "8-blocks")
    page.get_by_label("Search blocks").fill("PID")
    page.locator(".mc-block-card", has_text="PID").first.click()
    expect(page.get_by_role("heading", name="PID", exact=True)).to_be_visible(timeout=SLOW)
    # A block's tabs, as Analytics' (owner, 2026-10-27): the Overview is its drawing and what it
    # does, how to read it and its formula; its inputs and outputs have a tab of their own.
    about = page.get_by_role("region", name="About this block")
    expect(about).to_contain_text("How to read it")
    expect(about.locator(".mc-formula")).to_contain_text("Ti")
    expect(page.locator(".mc-contract")).to_have_count(0)
    _shot(page, screenshots, "9-block")
    _tab(page, "Inputs and outputs")
    expect(page.locator(".mc-contract")).to_contain_text("Parameters")
    _tab(page, "Code")
    expect(page.locator(".mc-code")).to_contain_text("block PID")
    _tab(page, "Used by")
    expect(page.locator(".pcs-content")).to_contain_text("TankLevelControl", timeout=SLOW)
    # Any block can be duplicated into the site's library; there its defaults change as a version.
    page.get_by_role("button", name="Duplicate").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Name").fill("Slow PID")
    dialog.get_by_role("button", name="Duplicate").click()
    expect(page.get_by_role("heading", name="Slow PID", exact=True)).to_be_visible(timeout=SLOW)
    _tab(page, "Inputs and outputs")
    defaults = page.get_by_role("region", name="Defaults")
    defaults.get_by_label("Ti").fill("240")
    defaults.get_by_label("Ti").blur()
    defaults.get_by_role("button", name="Save as a new version").click()
    dialog = page.get_by_role("dialog", name="Save as a new version")
    dialog.get_by_label("What changed").fill("A slower integral")
    dialog.get_by_role("button", name="Save as a new version").click()
    expect(dialog).to_have_count(0, timeout=SLOW)
    expect(page.locator(".mc-contract")).to_contain_text("240", timeout=SLOW)
    _shot(page, screenshots, "9b-block-defaults")
    _tab(page, "Versions")
    expect(page.locator(".pc-versions")).to_contain_text("A slower integral", timeout=SLOW)


def test_a_study_drives_inputs_compares_integrators_and_keeps_its_runs(
    signed_in, app_url, screenshots
):
    # Round 9 Q7c (M6-M10): a model written as code has its inputs in the study (a step here),
    # the integrator is varied like a parameter, a run opens inside the study, and any variable
    # gets a chart of its own after the study ran.
    page = signed_in
    page.goto(f"{app_url}/model/studies/new")
    page.get_by_label("Model", exact=True).select_option(label="LoopProcess")
    form = page.locator(".mc-study-form")
    form.get_by_label("Name").fill("Valve step")
    expect(form.locator(".mc-sweep-group", has_text="Inputs")).to_be_visible(timeout=SLOW)
    form.get_by_label("How u is set").select_option("fixed")
    form.get_by_label("Value of u").fill("60")
    form.get_by_label("Shape of u").select_option("step")
    form.get_by_label("u before").fill("50")
    form.get_by_label("u at").fill("100")
    form.get_by_label("How Solver is set").select_option("list")
    ticks = form.get_by_role("group", name="Solvers to compare")
    ticks.get_by_label("DASSL (default)").check()
    ticks.get_by_label("IDA").check()
    expect(form.locator(".mc-study-count")).to_contain_text("2 simulations", timeout=SLOW)
    _shot(page, screenshots, "q7c-new-study-inputs")
    form.get_by_role("button", name="Start the study").click()

    expect(page.get_by_role("heading", name="Valve step")).to_be_visible(timeout=SLOW)
    expect(page.locator(".mc-study-bar")).to_contain_text("2 done", timeout=SLOW)
    table = page.get_by_role("table", name="Simulations")
    expect(table.locator("thead")).to_contain_text("Run time")
    page.get_by_role("button", name="Add a chart of another variable").click()
    expect(page.get_by_role("button", name="Remove this chart")).to_be_visible()
    _shot(page, screenshots, "q7c-study-results")
    table.locator("tbody tr", has_text="method=ida").click()
    expect(page).to_have_url(re.compile(r"/studies/[^/]+/runs/[^/]+$"), timeout=SLOW)
    crumbs = page.locator("nav.breadcrumb")
    expect(crumbs).to_contain_text("Studies")
    expect(crumbs).not_to_contain_text("Simulations")
    _shot(page, screenshots, "q7c-run-in-study")


def test_folders_hold_models_and_studies_and_moving_is_deliberate(signed_in, app_url, screenshots):
    """Folders (round 9, M5), as Link's: made on the list, an object moved with Move to folder
    (who moved it is kept), a new study made in the folder its list shows; blocks keep their
    libraries above the folders of the site's own blocks."""

    page = signed_in
    page.goto(f"{app_url}/model/models")
    column = page.get_by_role("navigation", name="Folders")
    column.get_by_role("button", name="New folder").click()
    page.locator("#pc-folder-name").fill("Tanks")
    page.get_by_role("button", name="Make the folder").click()
    expect(page).to_have_url(re.compile(r"/model/models\?folder=.+"))
    expect(page.get_by_text("No model in this folder.")).to_be_visible(timeout=SLOW)
    _open_model(page, app_url)
    line = page.locator(".pc-folder-place")
    expect(line).to_contain_text("In no folder", timeout=SLOW)
    line.get_by_role("button", name="Move to folder").click()
    page.locator("#pc-folder-target").select_option(label="Tanks")
    page.get_by_role("button", name="Move", exact=True).click()
    expect(line).to_contain_text("Tanks")
    expect(line).to_contain_text("moved by")
    line.get_by_role("link", name="Tanks").click()
    expect(page.locator(".pc-dt tbody tr")).to_have_count(1, timeout=SLOW)
    expect(page.locator(".pc-dt tbody")).to_contain_text("TankLevelControl")
    _shot(page, screenshots, "13-folders-models")
    # Studies: a folder, then New study from it puts the study there.
    page.goto(f"{app_url}/model/studies")
    page.get_by_role("navigation", name="Folders").get_by_role("button", name="New folder").click()
    page.locator("#pc-folder-name").fill("Tuning")
    page.get_by_role("button", name="Make the folder").click()
    expect(page).to_have_url(re.compile(r"/model/studies\?folder=.+"))
    page.locator("main").get_by_role("link", name="New study").click()
    page.get_by_label("Model", exact=True).select_option(label="TankLevelControl")
    form = page.locator(".mc-study-form")
    expect(form.get_by_label("Folder")).to_have_value(re.compile(".+"), timeout=SLOW)
    form.get_by_label("Name").fill("In a folder")
    form.get_by_role("button", name="Start the study").click()
    expect(page.get_by_role("heading", name="In a folder")).to_be_visible(timeout=SLOW)
    expect(page.locator(".pc-folder-place")).to_contain_text("Tuning", timeout=SLOW)
    page.locator(".pc-folder-place").get_by_role("link", name="Tuning").click()
    expect(page.locator(".pc-dt tbody tr")).to_have_count(1, timeout=SLOW)
    _shot(page, screenshots, "14-folders-studies")
    page.goto(f"{app_url}/model/blocks")
    blocks = page.get_by_role("navigation", name="Libraries and folders")
    expect(blocks.get_by_role("heading", name="Folders")).to_be_visible(timeout=SLOW)


def test_a_model_written_as_code_is_one_block(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/model/models")
    page.locator("tbody tr", has_text="1 (code)").first.click()
    expect(page.get_by_role("navigation", name="Model")).to_be_visible(timeout=SLOW)
    expect(page.locator(".pcs-content")).to_contain_text("Modelica code")
    _tab(page, "Diagram")
    expect(page.locator(".be-node")).to_have_count(1, timeout=SLOW)
    _shot(page, screenshots, "9-code-model")


def test_the_code_of_a_model(signed_in, app_url, screenshots):
    page = signed_in
    _open_model(page, app_url)
    page.get_by_role("link", name="Modelica code").click()
    expect(page.locator(".cm-content")).to_contain_text("TankLevelControl", timeout=SLOW)
    expect(page.locator(".cm-content")).to_contain_text("connect(")
    page.get_by_role("button", name="Check").click()
    expect(page.locator(".mc-messages header")).to_contain_text(
        re.compile("equation"), timeout=SLOW
    )
    _shot(page, screenshots, "10-code")


def test_export_an_fmu(signed_in, app_url, screenshots):
    page = signed_in
    _open_model(page, app_url)
    page.get_by_role("button", name="Export FMU").click()
    page.get_by_role("dialog").get_by_role("button", name="Export").click()
    expect(page.get_by_role("link", name="Download the FMU")).to_be_visible(timeout=SLOW)
    expect(page.locator(".pcs-content")).to_contain_text("linux64")
    # Owner, 2026-10-24: nothing goes to Link from Models this round.
    expect(page.get_by_role("button", name="Publish to Link")).to_have_count(0)
    _shot(page, screenshots, "11-fmu")


def test_addresses_of_earlier_versions_lead_to_their_new_place(signed_in, app_url):
    page = signed_in
    page.goto(f"{app_url}/model/projects")
    expect(page.get_by_role("heading", name="Models", exact=True)).to_be_visible(timeout=SLOW)
    page.goto(f"{app_url}/model/simulations")
    expect(page.get_by_role("heading", name="Simulations")).to_be_visible(timeout=SLOW)


def test_asset_page_and_help(signed_in, app_url):
    page = signed_in
    page.goto(f"{app_url}/model/assets/FIC-1001")
    expect(page.get_by_role("heading", name=re.compile("FIC-1001"))).to_be_visible(timeout=SLOW)
    page.goto(f"{app_url}/model/help")
    expect(page.get_by_role("heading", name="Help")).to_be_visible()
    expect(page.locator(".pcs-content")).to_contain_text("Building models")


def test_the_guided_tour_opens_on_a_first_visit(browser, fake, app_url):
    from plantcraft_sdk.contract import TOKEN_COOKIE

    context = browser.new_context(viewport={"width": 1440, "height": 900})
    context.add_cookies([{"name": TOKEN_COOKIE, "value": fake.token("engineer"), "url": app_url}])
    page = context.new_page()
    page.goto(f"{app_url}/model/")
    expect(page.get_by_text("Welcome to Models")).to_be_visible(timeout=SLOW)
    context.close()


def test_a_block_of_the_sites_library_takes_a_picture(signed_in, app_url, screenshots):
    """Round 9 M1, M2: a block's Overview draws it as the diagram does; a block of the site's own
    library takes a picture, written in its Icon annotation as a new version of the file."""

    from plantcraft_sdk import e2e

    page = signed_in
    library = page.request.post(f"{app_url}/model/api/blocks", data={"name": "Pictured"}).json()
    made = page.request.post(
        f"{app_url}/model/api/projects/{library['id']}/files",
        data={
            "path": "Pictured/Gain.mo",
            "content": 'within Pictured;\nblock Gain "Multiplies its input"\n'
            "  Modelica.Blocks.Interfaces.RealInput u;\n"
            "  Modelica.Blocks.Interfaces.RealOutput y;\n"
            "  parameter Real k = 2;\nequation\n  y = k * u;\nend Gain;\n",
        },
    )
    assert made.ok, made.text()
    page.goto(f"{app_url}/model/blocks/Pictured.Gain")
    drawing = page.locator(".pc-block-drawing")
    expect(drawing.locator(".pc-bd-inputs")).to_contain_text("u", timeout=SLOW)
    expect(drawing.locator(".pc-bd-outputs")).to_contain_text("y")
    expect(drawing.locator(".pc-bd-box img")).to_have_count(0)
    page.locator("#mc-block-image").set_input_files(
        {"name": "gain.png", "mimeType": "image/png", "buffer": e2e.png()}
    )
    expect(drawing.locator(".pc-bd-box img")).to_be_visible(timeout=SLOW)
    page.wait_for_function("() => document.querySelector('.pc-bd-box img')?.naturalWidth === 24")
    expect(page.get_by_role("link", name="Versions (2)")).to_be_visible(timeout=SLOW)
    _shot(page, screenshots, "17-block-picture")
    _tab(page, "Code")
    expect(page.locator(".mc-code")).to_contain_text("imageSource")
    # A block Models ships draws too, and keeps its picture.
    page.goto(f"{app_url}/model/blocks")
    page.goto(f"{app_url}/model/blocks/PlantCraftControl.OnOff")
    expect(page.locator(".pc-block-drawing .pc-bd-inputs")).to_contain_text(
        "Setpoint", timeout=SLOW
    )
    expect(page.locator("#mc-block-image")).to_have_count(0)
