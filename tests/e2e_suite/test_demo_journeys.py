"""A first visitor walks the demo story, app by app, as the home page's tour tells them to.

The story is the one ``processcraft demo seed`` writes on the Simulator's plant: FIC-1003 has a sticky
valve, PIC-1202 oscillates, TIC-1209 drifts, Link's Furnaces model names TIC-1209, the team
talks about FIC-1003 (the visitor too), Alarms holds two days of their alarms, and Models
holds simulations of its examples and exports the Furnaces FMU. The
journeys run in order on one signed-in page.
"""

from __future__ import annotations

import re

from playwright.sync_api import expect

from tests.e2e_suite.conftest import URL, app, go


def test_01_the_sign_in_page_offers_the_demo_and_the_tour_walks_the_platform(visitor):
    go(visitor, "/login")
    # A visit needs no password since the demo visits (#357): a timed, read-only seat.
    note = visitor.get_by_role("note").filter(has_text="Public demo")
    expect(note).to_contain_text("A visit lasts")
    visitor.get_by_role("button", name="Enter the demo").click()
    tour = visitor.get_by_role("dialog")
    expect(tour.get_by_role("heading", name="Welcome to PlantCraft")).to_be_visible()
    expect(tour.get_by_text("nothing you change is saved", exact=False)).to_be_visible()
    tour.get_by_role("button", name="Start the tour").click()
    titles = []
    for _ in range(12):
        titles.append(tour.locator("#pct-title").inner_text())
        if tour.get_by_role("button", name="Finish").count():
            break
        tour.get_by_role("button", name="Next").click()
        visitor.wait_for_load_state("networkidle")
    assert "One asset, one page" in titles, titles
    assert titles[-1] == "Your apps", titles
    for name in ("Analytics", "View", "Historian", "Models", "Alarms"):
        expect(tour.get_by_text(name, exact=True).first).to_be_visible()
    tour.get_by_role("button", name="Finish").click()
    expect(visitor.get_by_role("dialog")).to_have_count(0)


def test_02_the_plant_asset_has_its_loop_and_signals(visitor):
    go(visitor, "/assets/FIC-1003")
    # since ui 0.41 a page's top shows only its title (the description is not drawn)
    expect(visitor.get_by_role("heading", name=re.compile("FIC-1003"))).to_be_visible()
    expect(visitor.get_by_role("article").filter(has_text="Record").first).to_be_visible()
    expect(visitor.get_by_text(re.compile(r"CPM\.Loops\.FIC-1003\.PV")).first).to_be_visible()


def test_02b_an_app_opens_its_own_tour_the_first_time(visitor):
    go(visitor, "/link/loops/FIC-1003")
    try:
        tour = app(visitor).get_by_role("dialog")
        expect(tour.get_by_role("heading", name="Welcome to Analytics")).to_be_visible()
        tour.get_by_role("button", name="Not now").click()
        expect(app(visitor).get_by_role("dialog")).to_have_count(0)
    finally:
        # the other apps' tours are not part of these journeys; off even when this one failed,
        # or a tour's blocker would take every later journey's clicks
        visitor.evaluate("localStorage.setItem('plantcraft-ui:tours-off', '1')")


def test_03_link_names_the_sticky_valve_with_its_evidence(visitor):
    go(visitor, "/link/loops/FIC-1003")
    expect(app(visitor).get_by_role("heading", name=re.compile("FIC-1003"))).to_be_visible()
    findings = app(visitor).locator("table").filter(has_text="Stiction screening")
    expect(findings).to_be_visible()
    expect(findings.get_by_text(re.compile("Critical|Warning")).first).to_be_visible()
    # the trends are drawn from the history (the Historian's archive)
    expect(app(visitor).locator(".js-plotly-plot").first).to_be_visible()


def test_04_link_overview_shows_the_schedules_and_their_runs(visitor):
    # the overview never ranks by criticality (owner, round 7): schedules, queue, latest runs
    go(visitor, "/link/")
    monitors = app(visitor).get_by_role("article", name="Monitors")
    expect(
        monitors.get_by_role("link", name=re.compile("^Control loop performance"))
    ).to_be_visible()
    expect(app(visitor).get_by_role("heading", name="Queue")).to_be_visible()
    # every result on one health map, by area (owner, 2026-10-27)
    expect(app(visitor).get_by_role("heading", name="Health map")).to_be_visible()


def test_05_an_algorithm_is_blocks_and_its_runs(visitor):
    # the old address of a protocol opens the algorithm
    go(visitor, "/link/protocols/flow_loop")
    expect(visitor).to_have_url(re.compile(r"/link/algorithms/flow_loop$"))
    # the read-only diagram shows its blocks, the data check first
    go(visitor, "/link/algorithms/flow_loop/diagram")
    expect(app(visitor).get_by_text("Loop data check").first).to_be_visible()
    go(visitor, "/link/runs")
    expect(app(visitor).get_by_text("Completed").first).to_be_visible()


def test_06_the_furnaces_model_names_the_drifting_thermocouple(visitor):
    # PlantCraft Twin's old address opens Link's algorithms, where the twins now run
    go(visitor, "/twin/")
    expect(visitor).to_have_url(re.compile(r"/link/algorithms$"))
    go(visitor, "/link/algorithms/example_furnaces")
    expect(app(visitor).get_by_role("heading", name="Furnaces", level=1)).to_be_visible()
    # the model algorithm judges every minute or so after the plant starts (Used by lists its runs)
    go(visitor, "/link/algorithms/example_furnaces/used-by")
    expect(app(visitor).get_by_text(re.compile(r"TIC-?1209\S* explains")).first).to_be_visible(
        timeout=120_000
    )


def test_06b_alarms_hold_five_rules_and_two_days_of_the_story(visitor):
    go(visitor, "/alarm/alarms")
    expect(app(visitor).get_by_role("heading", name="Alarms", level=1)).to_be_visible()
    # one table of every alarm; All lists them whether the simulated plant has alarms active now
    app(visitor).get_by_role("button", name="All", exact=True).click()
    expect(app(visitor).locator(".al-row").first).to_be_visible()
    # a row opens the alarm, with its history (the seed replays two days of the archive)
    app(visitor).locator(".al-row").first.locator("td").nth(4).click()
    expect(app(visitor).get_by_role("heading", name="History")).to_be_visible()
    go(visitor, "/alarm/rules")
    # the seed's example rules, one of them over every loop of Unit 100
    for name in (
        "Analytics monitor failed",
        "Loop critical for over 1 h",
        "PIC-1202 pressure high",
    ):
        expect(app(visitor).get_by_role("link", name=name)).to_be_visible()
    go(visitor, "/alarm/events")
    expect(app(visitor).get_by_role("heading", name="Events", exact=True)).to_be_visible()
    # the seeded alarm philosophy (on the plant's own zone), and the performance against it
    go(visitor, "/alarm/targets")
    expect(app(visitor).get_by_label("Time zone")).to_have_value("local")
    go(visitor, "/alarm/performance")
    expect(app(visitor).get_by_text("Average alarms per hour").first).to_be_visible()


def test_06c_models_simulate_and_export_an_fmu(visitor):
    go(visitor, "/model/")
    expect(app(visitor).get_by_role("heading", name="Overview")).to_be_visible()
    # the seed's examples it simulates and the Furnaces model it exports as an FMU
    models = app(visitor).get_by_role("article", name="Models")
    expect(models.get_by_role("link", name=re.compile("^Furnaces"))).to_be_visible()
    expect(app(visitor).get_by_role("article", name="Latest simulations")).to_be_visible()
    # Simulations › Queue shows the runner's workers; the FMU export is one of Models' runs
    go(visitor, "/model/executions/queue")
    expect(app(visitor).get_by_role("heading", name="Queue", exact=True).first).to_be_visible()
    exports = visitor.request.get(URL + "/model/api/runs?kind=fmu&status=done").json()
    assert "Furnaces for Analytics" in [run.get("label") for run in exports], exports


def test_07_dashboards_draw_the_plant_overview(visitor):
    go(visitor, "/dash/")
    app(visitor).get_by_text("Plant overview").first.click()
    visitor.wait_for_load_state("networkidle")
    expect(app(visitor).locator(".js-plotly-plot").first).to_be_visible()


def test_08_the_historian_archives_plantcraft(visitor):
    go(visitor, "/hist/")
    expect(app(visitor).get_by_text(re.compile("Simulator|plantcraft")).first).to_be_visible()


def test_09_the_team_and_the_visitor_talk_about_the_valve(visitor):
    go(visitor, "/messages")
    visitor.get_by_text("FIC-1003 recycle valve").first.click()
    expect(visitor.get_by_text(re.compile("Same valve model")).first).to_be_visible()
    expect(visitor.get_by_text(re.compile("positioner")).first).to_be_visible()
    go(visitor, "/actions")
    expect(
        visitor.get_by_text("Inspect the FIC-1003 recycle valve for stiction").first
    ).to_be_visible()


def test_10_the_visitor_cannot_change_anything(visitor):
    answer = visitor.request.post(URL + "/api/actions", data={"title": "spam"})
    assert answer.status == 403 and "read-only" in answer.text()
    answer = visitor.request.post(
        URL + "/api/messages/conversations",
        data={"members": ["admin"], "title": "spam", "text": "spam"},
    )
    assert answer.status == 403


def test_11_nothing_failed_and_nothing_left_the_installation(visitor, watch):
    assert watch.outside == [], watch.outside
    assert watch.failed == [], watch.failed
    assert watch.errors == [], (watch.errors, watch.forbidden)


def test_12_an_unknown_visitor_meets_the_sign_in_page(anonymous):
    anonymous.goto(URL + "/link/")
    anonymous.wait_for_load_state("networkidle")
    expect(
        anonymous.get_by_role("button", name=re.compile("Sign in|Enter the demo")).first
    ).to_be_visible()
    assert anonymous.request.get(URL + "/api/v1/signals").status in (401, 403)
