"""Diagrams in a real browser: draw one by dragging symbols and joining their ports, bind a value,
save it, then watch it live and play the window back."""

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
        page.wait_for_timeout(700)
        page.screenshot(path=str(screenshots / f"diagram-{name}.png"), full_page=True)


def _drop(page, title: str, x: float, y: float) -> None:
    """Drag a symbol from the library onto the canvas at (x, y) of the stage."""

    item = page.locator(".dg-palette-item", has_text=title).first
    stage = page.locator(".dg-editor-stage")
    item.drag_to(stage, target_position={"x": x, "y": y})


def test_an_editor_draws_binds_saves_and_plays_back_a_diagram(signed_in, app_url, screenshots):
    page = signed_in
    page.set_viewport_size({"width": 1500, "height": 950})
    page.goto(f"{app_url}/dash/diagrams")
    expect(page.get_by_role("heading", name="Process", exact=True)).to_be_visible()
    page.get_by_role("button", name="New process display").first.click()
    expect(page.get_by_role("toolbar", name="Process display editor")).to_be_visible()
    page.get_by_role("searchbox", name="Find a symbol").fill("centrifugal pump")
    expect(page.locator(".dg-palette-item").first).to_be_visible()
    _drop(page, "Centrifugal pump", 200, 220)
    page.get_by_role("searchbox", name="Find a symbol").fill("tank")
    _drop(page, "Tank", 520, 200)
    symbols = page.locator(".dg-canvas .dg-sym")
    expect(symbols).to_have_count(2)
    # Join the pump's first port to the tank: drag from one port and drop on the other symbol.
    pump_port = page.locator(".dg-ports").first.locator(".dg-port").last
    tank = symbols.nth(1)
    pump_port.drag_to(tank)
    expect(page.locator(".dg-canvas .dg-line")).to_have_count(1)
    # Bind the tank to an asset and show its PV beside it.
    tank.click()
    inspector = page.get_by_role("complementary", name="Properties")
    inspector.get_by_role("textbox", name="Asset", exact=True).fill("LIC-102")
    inspector.get_by_role("button", name=re.compile("LIC-102")).first.click()
    page.get_by_role("button", name="Value").click()
    expect(page.locator(".dg-canvas .dg-value")).to_have_count(1)
    _shot(page, screenshots, "1-editor")
    page.get_by_role("button", name="Save").click()
    expect(page).to_have_url(re.compile(r"/dash/diagrams/[0-9a-f]{12}$"))
    expect(page.get_by_role("button", name="Live")).to_be_visible()
    expect(page.locator(".dg-value .dg-value-number")).not_to_have_text("—")
    _shot(page, screenshots, "2-live")
    page.get_by_role("slider", name="Instant shown").press("Home")
    expect(page.locator(".dg-timebar time")).not_to_have_text("Now")
    _shot(page, screenshots, "3-playback")


def test_an_editor_draws_a_unit_from_its_assets(signed_in, app_url, screenshots):
    page = signed_in
    page.set_viewport_size({"width": 1500, "height": 950})
    page.goto(f"{app_url}/dash/diagrams/new")
    page.get_by_role("button", name="From assets").click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_role("combobox", name="Unit")).to_be_visible()
    dialog.get_by_role("button", name="Draw").click()
    expect(dialog).to_have_count(0)
    expect(page.locator(".dg-canvas .dg-sym").nth(2)).to_be_visible()
    expect(page.locator(".dg-canvas .dg-line").first).to_be_attached()
    _shot(page, screenshots, "4-from-assets")
    page.get_by_role("button", name="Save").click()
    expect(page).to_have_url(re.compile(r"/dash/diagrams/[0-9a-f]{12}$"))
    expect(page.locator(".dg-value .dg-value-number").first).not_to_have_text("—")
    _shot(page, screenshots, "5-from-assets-live")


def _box(locator):
    box = locator.bounding_box()
    assert box is not None
    return box


def test_an_editor_resizes_bends_and_brings_back_a_version(signed_in, app_url, screenshots):
    page = signed_in
    page.set_viewport_size({"width": 1500, "height": 950})
    page.goto(f"{app_url}/dash/diagrams/new")
    page.get_by_role("searchbox", name="Find a symbol").fill("tank")
    _drop(page, "Tank", 260, 160)
    page.get_by_role("searchbox", name="Find a symbol").fill("centrifugal pump")
    _drop(page, "Centrifugal pump", 520, 300)
    symbols = page.locator(".dg-canvas .dg-sym")
    expect(symbols).to_have_count(2)
    page.get_by_role("button", name="Save").click()
    expect(page).to_have_url(re.compile(r"/dash/diagrams/[0-9a-f]{12}$"))
    page.get_by_role("button", name="Edit", exact=True).click()
    _shot(page, screenshots, "6a-reopened")
    # Join them (the pump's port to the tank), then resize the tank and bend the line.
    page.locator(".dg-ports").nth(1).locator(".dg-port").last.drag_to(
        page.locator(".dg-canvas .dg-sym").first
    )
    line = page.locator(".dg-canvas .dg-line")
    expect(line).to_have_count(1)
    tank = page.locator(".dg-canvas .dg-sym").first
    tank.click()
    before = _box(tank)
    handle = _box(page.locator(".dg-handle-se"))
    page.mouse.move(handle["x"] + handle["width"] / 2, handle["y"] + handle["height"] / 2)
    page.mouse.down()
    page.mouse.move(handle["x"] + 80, handle["y"] + 80, steps=6)
    page.mouse.up()
    after = _box(tank)
    assert after["width"] > before["width"] * 1.3
    # Click the line halfway along it (the middle of its box may be off a bent line).
    halfway = line.locator(".dg-line-hit").evaluate(
        "(path) => { const at = path.getPointAtLength(path.getTotalLength() / 2)"
        ".matrixTransform(path.getScreenCTM()); return [at.x, at.y]; }"
    )
    page.mouse.click(*halfway)
    segment = page.locator(".dg-handle-ns, .dg-handle-ew").first
    expect(segment).to_be_visible()
    grip = _box(segment)
    page.mouse.move(grip["x"] + grip["width"] / 2, grip["y"] + grip["height"] / 2)
    page.mouse.down()
    page.mouse.move(grip["x"] + 40, grip["y"] + 40, steps=5)
    page.mouse.up()
    _shot(page, screenshots, "6-resized-bent")
    page.get_by_role("button", name="Save").click()
    expect(page.get_by_role("button", name="Edit", exact=True)).to_be_visible()
    page.get_by_role("button", name="Edit", exact=True).click()
    page.get_by_role("button", name="Versions").click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_role("row")).to_have_count(3)  # the header and the two saves
    dialog.get_by_role("button", name="Bring back").last.click()
    expect(dialog).to_have_count(0)
    expect(page.locator(".dg-canvas .dg-line")).to_have_count(0)
    _shot(page, screenshots, "7-version-back")


def _saved(page, app_url, **fields) -> str:
    from tests.test_diagrams import unit

    answer = page.request.post(f"{app_url}/dash/api/diagrams", data=unit(**fields))
    assert answer.ok, answer.text()
    return answer.json()["diagram_id"]


def test_a_diagram_shared_by_link_opens_live_and_as_a_kiosk(
    signed_in, anonymous, app_url, screenshots
):
    page = signed_in
    page.set_viewport_size({"width": 1400, "height": 900})
    page.goto(f"{app_url}/dash/diagrams")
    diagram_id = _saved(page, app_url, name="Feed by link")
    page.goto(f"{app_url}/dash/diagrams/{diagram_id}")
    page.get_by_role("button", name="Share").click()
    dialog = page.get_by_role("dialog", name=re.compile("Public links of"))
    dialog.get_by_label("Link label").fill("Control room")
    dialog.get_by_role("button", name="Create link").click()
    url = dialog.locator("#share-url").input_value()
    assert "/dash/share/diagram/" in url
    anonymous.set_viewport_size({"width": 1400, "height": 900})
    anonymous.goto(url)
    expect(anonymous.get_by_role("heading", name="Feed by link")).to_be_visible()
    expect(anonymous.locator(".dg-canvas .dg-sym")).to_have_count(3)
    expect(anonymous.locator(".dg-value .dg-value-number")).not_to_have_text("—")
    expect(anonymous.get_by_role("button", name="Edit")).to_have_count(0)
    expect(anonymous.get_by_role("button", name="Share")).to_have_count(0)
    expect(anonymous.locator(".pcs-sidebar")).to_have_count(0)
    # The time bar plays the window back through the link too.
    anonymous.get_by_role("slider", name="Instant shown").press("Home")
    expect(anonymous.locator(".dg-timebar time")).not_to_have_text("Now")
    _shot(anonymous, screenshots, "6-public-link")
    anonymous.goto(f"{url}?screen=1")
    expect(anonymous.locator(".dg-stage-full .dg-canvas")).to_be_visible()
    expect(anonymous.locator(".dg-kiosk-name")).to_have_text("Feed by link")
    _shot(anonymous, screenshots, "7-kiosk")


def test_a_dashboard_shows_a_diagram_card_that_opens_the_diagram(signed_in, app_url, screenshots):
    page = signed_in
    page.set_viewport_size({"width": 1400, "height": 950})
    page.goto(f"{app_url}/dash/diagrams")
    diagram_id = _saved(page, app_url, name="Feed panel")
    answer = page.request.post(
        f"{app_url}/dash/api/dashboards",
        data={
            "name": "Feed with diagram",
            "cards": [
                {"card_id": "k1", "kind": "stat", "items": [{"signal_id": "fake:FIC-101.PV"}]},
            ],
        },  # fmt: skip
    )
    assert answer.ok, answer.text()
    page.goto(f"{app_url}/dash/d/{answer.json()['dashboard_id']}")
    page.get_by_role("button", name="Edit", exact=True).click()
    page.get_by_role("button", name="Add panel").first.click()
    page.get_by_role("radio", name=re.compile("^Process display")).click()
    editor = page.get_by_role("dialog", name="New panel")
    editor.get_by_role("combobox", name="Process display").select_option(label="Feed panel")
    expect(editor.locator(".tc-preview .dg-canvas .dg-sym")).to_have_count(3)
    editor.get_by_role("button", name="Apply").click()
    page.get_by_role("button", name="Save").click()
    card = page.locator('.tc-card[data-kind="diagram"]')
    expect(card.locator(".dg-canvas .dg-sym")).to_have_count(3)
    expect(card.locator("h2")).to_have_text("Feed panel")
    expect(card.locator(".dg-value .dg-value-number")).not_to_have_text("—")
    _shot(page, screenshots, "8-dashboard-card")
    card.get_by_role("link", name="Open the process display Feed panel").click()
    expect(page).to_have_url(re.compile(rf"/dash/diagrams/{diagram_id}$"))


def test_a_process_display_has_pages_and_the_tabs_turn_them(signed_in, app_url, screenshots):
    page = signed_in
    page.set_viewport_size({"width": 1500, "height": 950})
    page.goto(f"{app_url}/dash/diagrams/new")
    page.get_by_role("searchbox", name="Find a symbol").fill("tank")
    _drop(page, "Tank", 260, 160)
    page.get_by_role("button", name="Add page").click()
    page.get_by_role("textbox", name="Page name").fill("Pumps")
    expect(page.locator(".dg-canvas .dg-sym")).to_have_count(0)
    page.get_by_role("searchbox", name="Find a symbol").fill("centrifugal pump")
    _drop(page, "Centrifugal pump", 300, 200)
    _drop(page, "Centrifugal pump", 450, 200)
    expect(page.locator(".dg-canvas .dg-sym")).to_have_count(2)
    tabs = page.get_by_role("navigation", name=re.compile("Pages of"))
    tabs.get_by_role("link", name="Page 1").click()
    expect(page.locator(".dg-canvas .dg-sym")).to_have_count(1)
    _shot(page, screenshots, "8-pages-editor")
    page.get_by_role("button", name="Save").click()
    expect(page).to_have_url(re.compile(r"/dash/diagrams/[0-9a-f]{12}$"))
    tabs = page.get_by_role("navigation", name=re.compile("Pages of"))
    expect(tabs.get_by_role("link")).to_have_count(2)
    expect(page.locator(".dg-canvas .dg-sym")).to_have_count(1)
    tabs.get_by_role("link", name="Pumps").click()
    expect(page).to_have_url(re.compile(r"\?page=p2$"))
    expect(page.locator(".dg-canvas .dg-sym")).to_have_count(2)
    expect(page.get_by_role("radio", name="Now")).to_have_attribute("aria-checked", "true")
    _shot(page, screenshots, "9-pages-viewer")
    page.reload()
    expect(page.locator(".dg-canvas .dg-sym")).to_have_count(2)


def test_a_whole_plant_on_one_page_zooms_and_moves(signed_in, app_url, screenshots):
    """The demo's plant (deploy/demo/diagrams) on one page: the whole of it first, then the
    wheel, a double click or the buttons zoom about a point, a drag moves the drawing and opens
    nothing, and "Show the whole drawing" comes back (owner, 2026-10-27)."""

    import json
    from pathlib import Path

    plant = Path(__file__).resolve().parents[4] / "deploy/demo/diagrams/riverbend-plant.json"
    page = signed_in
    body = json.loads(plant.read_text(encoding="utf-8"))
    answer = page.request.post(f"{app_url}/dash/api/diagrams", data=body)
    assert answer.ok, answer.text()
    made = answer.json()
    page.goto(f"{app_url}/dash/diagrams/{made['diagram_id']}")
    canvas = page.locator(".dg-stage svg.dg-canvas")
    expect(canvas).to_have_attribute("viewBox", "0 0 4800 2700")
    expect(page.get_by_role("navigation", name="Pages of Riverbend plant")).to_have_count(0)
    level = page.locator(".dg-zoom-level")
    expect(level).to_have_text("100 %")
    _shot(page, screenshots, "10-plant-whole")
    stage = page.locator(".dg-zoom-stage")
    box = stage.bounding_box()
    page.mouse.dblclick(box["x"] + box["width"] * 0.2, box["y"] + box["height"] * 0.2)
    expect(level).to_have_text("200 %")
    page.get_by_role("button", name="Zoom in").click()
    expect(level).to_have_text("400 %")
    _shot(page, screenshots, "11-plant-zoomed")
    before = canvas.get_attribute("viewBox")
    page.mouse.move(box["x"] + 300, box["y"] + 300)
    page.mouse.down()
    page.mouse.move(box["x"] + 200, box["y"] + 250, steps=5)
    page.mouse.up()
    expect(canvas).not_to_have_attribute("viewBox", before)
    expect(page).to_have_url(re.compile(rf"/dash/diagrams/{made['diagram_id']}"))
    page.get_by_role("button", name="Show the whole drawing").click()
    expect(canvas).to_have_attribute("viewBox", "0 0 4800 2700")
    # An off-page button zooms to the part it names: Preheat's "Column" to the column's tile.
    page.locator('[data-element="preh-go-1"]').click()
    expect(canvas).to_have_attribute("viewBox", "1600 0 1600 900")
    expect(level).to_have_text("300 %")


def test_a_display_opens_trends_and_assets_over_itself_full_screen_too(
    signed_in, app_url, screenshots
):
    """A click on a value draws its trend in a window over the display, and a click on a piece
    of equipment opens its panel beside it; neither leaves the display, and both open inside
    the browser's own full screen. The tank's liquid follows the tank's outline (owner,
    2026-10-27)."""

    page = signed_in
    page.set_viewport_size({"width": 1400, "height": 900})
    page.goto(f"{app_url}/dash/diagrams")
    diagram_id = _saved(page, app_url, name="Feed over itself")
    page.goto(f"{app_url}/dash/diagrams/{diagram_id}")
    address = page.url
    # The liquid is clipped by the tank's own outline, with its surface drawn.
    tank = page.locator('[data-element="tk1"]')
    expect(tank.locator(".dg-level clipPath")).to_have_count(1)
    expect(tank.locator(".dg-level .dg-level-surface")).to_have_count(1)
    page.locator('[data-element="pv"]').click()
    dialog = page.get_by_role("dialog")
    expect(dialog.locator(".tc-trend-plot")).to_be_visible()
    expect(dialog.get_by_label("Period")).to_be_visible()
    assert page.url == address
    _shot(page, screenshots, "12-value-trend")
    dialog.get_by_role("button", name="Close").first.click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    tank.click()
    panel = page.get_by_role("complementary", name=re.compile("^Asset"))
    expect(panel.get_by_role("heading", level=2)).to_be_visible()
    expect(panel.get_by_role("link", name="Asset page")).to_have_attribute(
        "href", "/assets/lic-102"
    )
    assert page.url == address
    _shot(page, screenshots, "13-asset-panel")
    panel.get_by_role("button", name="Trend", exact=True).click()
    expect(page.get_by_role("dialog").locator(".tc-trend-plot")).to_be_visible()
    page.get_by_role("dialog").get_by_role("button", name="Close").first.click()
    panel.get_by_role("button", name="Close").click()
    expect(panel).to_have_count(0)
    # Full screen is the browser's: the stage itself, with the trend inside it.
    page.get_by_role("button", name="Full screen").click()
    page.wait_for_function("document.fullscreenElement?.classList.contains('dg-stage')")
    page.locator('[data-element="pv"]').click()
    inside = page.evaluate(
        "Boolean(document.fullscreenElement.querySelector('[role=dialog] .tc-trend-plot'))"
    )
    expect(page.locator(".dg-stage [role=dialog] .tc-trend-plot")).to_be_visible()
    assert inside or page.locator(".dg-stage [role=dialog] .tc-trend-plot").count() == 1
    _shot(page, screenshots, "14-full-screen-trend")


def test_a_whole_plant_has_tabs_back_to_its_overview(signed_in, app_url, screenshots):
    """Overview and a tab per part over the one-page plant (owner, 2026-10-28): a tab zooms to
    its part, Overview comes back to the whole drawing, and the tab of the part in view is
    the current one, full screen too."""

    import json
    from pathlib import Path

    plant = Path(__file__).resolve().parents[4] / "deploy/demo/diagrams/riverbend-plant.json"
    page = signed_in
    page.set_viewport_size({"width": 1400, "height": 900})
    answer = page.request.post(
        f"{app_url}/dash/api/diagrams", data=json.loads(plant.read_text(encoding="utf-8"))
    )
    assert answer.ok, answer.text()
    page.goto(f"{app_url}/dash/diagrams/{answer.json()['diagram_id']}")
    canvas = page.locator(".dg-stage svg.dg-canvas")
    tabs = page.get_by_role("navigation", name="Parts of Riverbend plant")
    expect(tabs.get_by_role("link", name="Overview")).to_have_attribute("aria-current", "page")
    tabs.get_by_role("link", name="Column").click()
    expect(canvas).to_have_attribute("viewBox", "1600 0 1600 900")
    expect(tabs.get_by_role("link", name="Column")).to_have_attribute("aria-current", "page")
    assert "part=column" in page.url
    _shot(page, screenshots, "15-plant-part-tabs")
    # An off-page button moves the current tab with it.
    page.locator('[data-element="colu-go-1"]').first.click()
    expect(tabs.get_by_role("link", name="Overview")).not_to_have_attribute("aria-current", "page")
    tabs.get_by_role("link", name="Overview").click()
    expect(canvas).to_have_attribute("viewBox", "0 0 4800 2700")
    page.get_by_role("button", name="Full screen").click()
    page.wait_for_function("document.fullscreenElement?.classList.contains('dg-stage')")
    inside = page.locator(".dg-full-tabs").get_by_role("link", name="Utilities")
    inside.click()
    expect(canvas).to_have_attribute("viewBox", "1600 1800 1600 900")
    _shot(page, screenshots, "16-plant-tabs-full-screen")
