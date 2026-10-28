"""Round 7's visual check (owner, 2026-10-24: "teste todos os elementos visualmente"): a gallery
dashboard with every kind of card in several shapes and options, drawn in the light and the dark
theme, on a wide screen and a phone. Each drawing is checked for what a person would see wrong:
a value or a chart spilling out of its card, a title or a value hard to read on its background,
a card that never finished reading. With ``DASHCRAFT_E2E_SCREENSHOTS`` every drawing is kept.

Moving and resizing cards (the grid, B1) is checked with the mouse, as a person does it.
"""

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

pytestmark = pytest.mark.slow

STEPS = {
    "mode": "absolute",
    "steps": [
        {"level": "ok"},
        {"value": 50.5, "level": "warning"},
        {"value": 52.5, "level": "alarm"},
    ],
    "show": "lines+area",
}
LOOP = {"asset_id": "$loop", "role": "*"}


def _card(card_id, kind, x, y, w, h, **rest):
    return {
        "card_id": card_id,
        "title": rest.pop("title", ""),
        "kind": kind,
        "items": rest.pop("items", []),
        "agg": rest.pop("agg", "last"),
        "window": rest.pop("window", "8h"),
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        **rest,
    }


GALLERY = {
    "name": "Gallery",
    "description": "Every kind of card, for the visual check.",
    "refresh_seconds": 0,
    "variables": [
        {
            "name": "loop",
            "label": "Loop",
            "type": "asset",
            "asset_kind": "loop",
            "multi": True,
            "include_all": True,
            "default": "fic-101",
        },
        {
            "name": "period",
            "label": "Period",
            "type": "interval",
            "options": ["1h", "8h", "24h"],
            "default": "8h",
        },
    ],
    "cards": [
        _card(
            "stat-one",
            "stat",
            0,
            0,
            3,
            2,
            title="PV of ${loop}",
            items=[{"asset_id": "$loop", "role": "pv"}],
            field={"thresholds": STEPS},
            options={"graph": "area"},
        ),
        _card(
            "stat-many",
            "stat",
            3,
            0,
            6,
            2,
            title="Every signal, coloured background",
            items=[LOOP],
            field={"thresholds": STEPS},
            options={"color_by": "background"},
        ),
        _card(
            "stat-row",
            "stat",
            9,
            0,
            3,
            1,
            title="One row",
            items=[{"asset_id": "fic-101", "role": "op"}],
            field={"decimals": 1},
        ),
        _card("text", "text", 9, 1, 3, 1, text="Showing **${loop}** over ${period}."),
        _card(
            "gauge-one",
            "gauge",
            0,
            2,
            3,
            3,
            title="OP",
            items=[{"asset_id": "fic-101", "role": "op"}],
            field={
                "min": 0,
                "max": 100,
                "thresholds": {
                    "steps": [
                        {"level": "warning"},
                        {"value": 5, "level": "ok"},
                        {"value": 95, "level": "warning"},
                    ]
                },
            },
            options={"threshold_labels": True},
        ),
        _card(
            "gauge-many",
            "gauge",
            3,
            2,
            6,
            3,
            title="PV, SP and OP",
            items=[{"asset_id": "fic-101", "role": "*", "roles": ["pv", "sp", "op"]}],
            field={"thresholds": STEPS},
        ),
        _card(
            "bar-gauge",
            "bar",
            9,
            2,
            3,
            3,
            title="Bar gauges",
            items=[LOOP],
            field={"min": 0, "max": 100, "thresholds": STEPS},
            options={"bar_style": "gauge"},
        ),
        _card(
            "trend",
            "trend",
            0,
            5,
            8,
            4,
            title="${loop} over ${period}",
            window="$period",
            items=[{"asset_id": "$loop", "role": "*", "roles": ["pv", "sp"]}],
            field={"thresholds": STEPS},
            overrides=[
                {"match": {"by": "role", "value": "sp"}, "field": {"dash": "dash", "line_width": 2}}
            ],
            options={"legend": "table", "legend_values": ["last", "mean", "max"]},
        ),
        _card(
            "bar-v",
            "bar",
            8,
            5,
            4,
            4,
            title="Vertical bars",
            agg="mean",
            items=[LOOP],
            field={"thresholds": STEPS},
            options={"orientation": "vertical", "value_labels": "always"},
        ),
        _card(
            "table",
            "table",
            0,
            9,
            6,
            4,
            title="Table, coloured cells",
            window="24h",
            items=[LOOP, {"asset_id": "p-201", "role": "*"}],
            field={
                "thresholds": STEPS,
                "mappings": [{"type": "text", "value": "RUN", "text": "Running", "color": "green"}],
            },
            options={
                "columns": ["last", "mean", "min", "max", "time", "state"],
                "cell": "color_background",
                "row_color": True,
            },
        ),
        _card(
            "bar-h",
            "bar",
            6,
            9,
            6,
            4,
            title="Horizontal bars, sorted",
            agg="max",
            items=[LOOP],
            options={"orientation": "horizontal", "sort": "desc"},
        ),
        _card(
            "scatter",
            "scatter",
            0,
            13,
            4,
            4,
            title="PV against OP",
            items=[{"asset_id": "fic-101", "role": "op"}, {"asset_id": "fic-101", "role": "pv"}],
            options={"point_size": 4},
        ),
        _card(
            "trend-right",
            "trend",
            4,
            13,
            8,
            4,
            title="OP on the right axis",
            items=[{"asset_id": "fic-101", "role": "pv"}, {"asset_id": "fic-101", "role": "op"}],
            overrides=[
                {"match": {"by": "role", "value": "op"}, "field": {"axis": "right", "fill": 15}}
            ],
            options={"legend": "list", "legend_place": "right", "tooltip": "single"},
        ),
        _card(
            "repeat",
            "stat",
            0,
            17,
            4,
            2,
            title="${loop}",
            items=[{"asset_id": "$loop", "role": "pv"}],
            field={"thresholds": STEPS},
            repeat={"variable": "loop", "direction": "h", "max_per_row": 3},
        ),
    ],
}

# What a person would see wrong, measured in the page: an element drawn past its card's edges, a
# card title or a big value whose contrast with what is under it is too low.
CHECK = """() => {
  const rgb = (text) => (text.match(/[\\d.]+/g) || []).map(Number);
  const lum = ([r, g, b]) => { const f = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const background = (node) => { for (let n = node; n; n = n.parentElement) { const c = rgb(getComputedStyle(n).backgroundColor); if (c.length >= 3 && (c.length < 4 || c[3] > 0.5)) return c; } return [255, 255, 255]; };
  const problems = [];
  for (const card of document.querySelectorAll('.tc-card')) {
    const id = card.getAttribute('data-card');
    const box = card.getBoundingClientRect();
    if (card.querySelector('.tc-card-loading')) problems.push(`${id}: still reading`);
    if (card.querySelector('.tc-card-error')) problems.push(`${id}: ${card.querySelector('.tc-card-error').textContent}`);
    for (const node of card.querySelectorAll('.tc-card-body *')) {
      if (node.closest('.tc-table-wrap, .tc-bargauges, .tc-text, .tc-problems, .hoverlayer, .modebar-container')) continue;
      const r = node.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      if (r.bottom > box.bottom + 2 || r.right > box.right + 2 || r.left < box.left - 2) {
        problems.push(`${id}: ${node.tagName.toLowerCase()}.${node.getAttribute('class') || ''} spills out (${Math.round(r.right - box.right)}, ${Math.round(r.bottom - box.bottom)})`);
        break;
      }
    }
    for (const text of card.querySelectorAll('h2, .tc-kpi-value b, .tc-gauge-number b, .tc-stat-name, td')) {
      if (!text.textContent.trim() || !text.getClientRects().length) continue;
      const style = getComputedStyle(text);
      const ratioFound = ratio(rgb(style.color), background(text));
      const big = parseFloat(style.fontSize) >= 18.5 || (parseFloat(style.fontSize) >= 14 && Number(style.fontWeight) >= 700);
      if (ratioFound < (big ? 3 : 4.5)) problems.push(`${id}: "${text.textContent.trim().slice(0, 20)}" contrast ${ratioFound.toFixed(2)}`);
    }
  }
  return problems;
}"""


def _create(page, app_url, dashboard):
    page.goto(f"{app_url}/dash/dashboards")
    found = page.evaluate(
        """async (body) => { const r = await fetch('api/dashboards', {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify(body)}); return [r.status, await r.json()]; }""",
        dashboard,
    )
    assert found[0] in (200, 201), found
    return found[1]["dashboard_id"]


def _shot(page, screenshots, name):
    """The whole page: the window made as tall as the page first (Chromium's full-page capture
    changes the window under the grid, which then draws its cards anew)."""

    if not screenshots:
        return
    size = page.viewport_size
    height = page.evaluate("document.documentElement.scrollHeight")
    page.set_viewport_size({"width": size["width"], "height": max(size["height"], height)})
    page.wait_for_timeout(400)
    expect(page.locator(".tc-card-loading, .tc-card-meta .spin")).to_have_count(0, timeout=20000)
    page.wait_for_timeout(500)
    page.screenshot(path=str(screenshots / f"{name}.png"))
    page.set_viewport_size(size)


def _settle(page, cards):
    expect(page.locator(".tc-card")).to_have_count(cards, timeout=15000)
    expect(page.locator(".tc-card-loading, .tc-card-meta .spin")).to_have_count(0, timeout=20000)
    page.wait_for_timeout(700)


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("screen", ["wide", "phone"])
def test_every_card_is_drawn_inside_its_card_and_readable(
    signed_in, app_url, screenshots, theme, screen
):
    page = signed_in
    page.add_init_script(f"localStorage.setItem('plantcraft-ui:theme', '{theme}')")
    page.set_viewport_size(
        {"width": 1440, "height": 1000} if screen == "wide" else {"width": 390, "height": 844}
    )
    dashboard_id = _create(page, app_url, GALLERY)
    # Every loop at once: every-signal items list both loops, the repeated card draws twice.
    page.goto(f"{app_url}/dash/d/{dashboard_id}?var-loop=$__all")
    expect(page.locator("html")).to_have_attribute("data-theme", theme)
    # Three loops in the plant (FIC-109 has lost its PV): the repeated card draws three times.
    _settle(page, len(GALLERY["cards"]) + 2)
    _shot(page, screenshots, f"r7-gallery-{screen}-{theme}")
    problems = page.evaluate(CHECK)
    assert not problems, "\n".join(problems)
    # Variables are in the address, and their values in titles and texts.
    expect(page.locator("[data-card='text']")).to_contain_text(
        re.compile(r"Showing FIC-10\d, .*LIC-102.* over 8 hours")
    )
    expect(page.locator("[data-card='repeat'] h2")).to_have_count(3)
    # One loop: the cards follow; one stat, one copy.
    page.goto(f"{app_url}/dash/d/{dashboard_id}?var-loop=lic-102&var-period=1h")
    _settle(page, len(GALLERY["cards"]))
    expect(page.locator("[data-card='stat-one'] h2")).to_have_text("PV of LIC-102")
    expect(page.locator("[data-card='trend'] h2")).to_have_text("LIC-102 over 1 hour")
    problems = page.evaluate(CHECK)
    assert not problems, "\n".join(problems)
    _shot(page, screenshots, f"r7-gallery-one-loop-{screen}-{theme}")


def test_thresholds_colour_values_and_draw_labelled_lines(signed_in, app_url):
    page = signed_in
    page.set_viewport_size({"width": 1440, "height": 1000})
    dashboard_id = _create(page, app_url, GALLERY)
    page.goto(f"{app_url}/dash/d/{dashboard_id}")
    _settle(page, len(GALLERY["cards"]))
    # Each threshold line says what it is (round 7: "linha sem legenda").
    annotations = page.locator("[data-card='trend'] .annotation-text")
    expect(annotations.filter(has_text="Warning 50.5")).to_have_count(1)
    expect(annotations.filter(has_text="Critical 52.5")).to_have_count(1)
    # A table colours the last value by its step; a coloured background stat has white text.
    filled = page.locator("[data-card='table'] td.tc-cell-filled").first
    expect(filled).to_be_visible()
    assert filled.evaluate("(node) => getComputedStyle(node).backgroundColor") != "rgba(0, 0, 0, 0)"
    expect(page.locator("[data-card='stat-many'] .tc-stat-filled").first).to_be_visible()
    # Several gauges on one card, each with its name.
    expect(page.locator("[data-card='gauge-many'] .tc-gauge")).to_have_count(3)
    # Bars stand up when asked.
    assert page.locator("[data-card='bar-v'] .js-plotly-plot .bars").count() >= 1


def test_the_dark_tooltip_is_readable(signed_in, app_url, screenshots):
    """B2: the tooltip of a chart was white on white in the dark theme."""

    page = signed_in
    page.add_init_script("localStorage.setItem('plantcraft-ui:theme', 'dark')")
    page.set_viewport_size({"width": 1440, "height": 1000})
    dashboard_id = _create(page, app_url, GALLERY)
    page.goto(f"{app_url}/dash/d/{dashboard_id}")
    _settle(page, len(GALLERY["cards"]))
    plot = page.locator("[data-card='trend-right'] .nsewdrag").first
    plot.scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    box = plot.bounding_box()
    page.mouse.move(box["x"] + box["width"] * 0.6, box["y"] + box["height"] * 0.5)
    label = page.locator("[data-card='trend-right'] .hoverlayer .hovertext").first
    expect(label).to_be_visible()
    fill = label.locator("path").first.evaluate("(node) => getComputedStyle(node).fill")
    text = label.locator("text").first.evaluate("(node) => getComputedStyle(node).fill")
    assert fill != text and "255, 255, 255" not in fill, (fill, text)
    if screenshots:
        page.screenshot(path=str(screenshots / "r7-dark-tooltip.png"))


def test_cards_move_and_resize_with_the_mouse(signed_in, app_url, screenshots):
    """B1: the arrows moved the wrong cards. Cards are now dragged by their title to any place
    and resized from their corner; what is saved is what was drawn."""

    page = signed_in
    page.set_viewport_size({"width": 1440, "height": 1000})
    small = {
        **GALLERY,
        "name": "Move me",
        "cards": [
            _card(
                "a", "stat", 0, 0, 3, 2, title="A", items=[{"asset_id": "fic-101", "role": "pv"}]
            ),
            _card(
                "b", "stat", 3, 0, 3, 2, title="B", items=[{"asset_id": "fic-101", "role": "sp"}]
            ),
            _card(
                "c", "trend", 0, 2, 6, 4, title="C", items=[{"asset_id": "fic-101", "role": "pv"}]
            ),
        ],
    }
    dashboard_id = _create(page, app_url, small)
    page.goto(f"{app_url}/dash/d/{dashboard_id}?edit=1")
    _settle(page, 3)
    card = {name: page.locator(f"[data-card='{name}']") for name in "abc"}
    before = {name: card[name].bounding_box() for name in "abc"}
    # Drag A by its title to the right of B.
    handle = card["a"].locator("header").bounding_box()
    page.mouse.move(handle["x"] + 30, handle["y"] + handle["height"] / 2)
    page.mouse.down()
    page.mouse.move(handle["x"] + 30 + 2 * before["b"]["width"], handle["y"] + 10, steps=12)
    page.mouse.up()
    page.wait_for_timeout(500)
    moved = card["a"].bounding_box()
    assert moved["x"] > before["b"]["x"] + before["b"]["width"] - 5, (moved, before["b"])
    # B, the card that was not moved, stays where it was: never swapped (B1).
    assert card["b"].bounding_box()["x"] == pytest.approx(before["b"]["x"], abs=3)
    # Pull C's corner two columns wider and one row taller.
    corner = card["c"].locator("xpath=..").locator(".react-resizable-handle").bounding_box()
    column = (before["c"]["width"] + 14) / 6
    page.mouse.move(corner["x"] + 5, corner["y"] + 5)
    page.mouse.down()
    page.mouse.move(corner["x"] + 5 + 2 * column, corner["y"] + 5 + 105, steps=12)
    page.mouse.up()
    page.wait_for_timeout(500)
    grown = card["c"].bounding_box()
    assert grown["width"] == pytest.approx(before["c"]["width"] + 2 * column, abs=6)
    assert grown["height"] == pytest.approx(5 * 91 + 4 * 14, abs=3)
    _shot(page, screenshots, "r7-moved-editing")
    page.get_by_role("button", name="Save").click()
    expect(page.get_by_text("Saved.")).to_be_visible()
    page.reload()
    _settle(page, 3)
    assert card["a"].bounding_box()["x"] == pytest.approx(moved["x"], abs=3)
    assert card["c"].bounding_box()["height"] == pytest.approx(5 * 91 + 4 * 14, abs=3)
    saved = page.evaluate(
        f"async () => (await (await fetch('{app_url}/dash/api/dashboards/{dashboard_id}')).json()).cards"
    )
    places = {
        item["card_id"]: (item["x"], item["y"], item["width"], item["height"]) for item in saved
    }
    assert places["c"][2:] == (8, 5), places
    assert places["b"][:2] == (3, 0), places


def test_the_editor_picks_the_kind_first_and_changes_it_keeping_the_signals(
    signed_in, app_url, screenshots
):
    page = signed_in
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(f"{app_url}/dash/dashboards")
    page.get_by_role("button", name="New dashboard").first.click()
    page.get_by_role("dialog", name="New dashboard").get_by_role(
        "button", name="Open the editor"
    ).click()
    page.get_by_role("button", name="Add panel").first.click()
    picker = page.get_by_role("radiogroup", name="Panel type")
    expect(picker.get_by_role("radio")).to_have_count(8)
    picker.get_by_role("radio", name=re.compile("^Time series")).click()
    editor = page.get_by_role("dialog", name="New panel")
    traces = editor.locator(".tc-preview .js-plotly-plot .scatterlayer .trace")
    expect(traces.first).to_be_visible()
    # A threshold: a labelled line on the preview.
    editor.get_by_role("button", name="Add threshold").click()
    expect(editor.locator(".tc-preview .annotation-text")).to_have_count(1)
    # The search keeps only the options that match.
    editor.get_by_label("Search options").fill("legend")
    expect(editor.locator(".tc-opt:visible .tc-opt-label").first).to_have_text("Mode")
    expect(editor.get_by_text("Soft min")).to_be_hidden()
    editor.get_by_label("Search options").fill("")
    if screenshots:
        page.screenshot(path=str(screenshots / "r7-editor-trend.png"))
    # Another visualization keeps the signals and the thresholds.
    editor.get_by_role("button", name=re.compile("^Time series")).click()
    page.get_by_role("radiogroup", name="Panel type").get_by_role(
        "radio", name=re.compile("^Gauge")
    ).click()
    expect(editor.locator(".tc-preview .tc-gauge").first).to_be_visible()
    expect(editor.locator(".tc-step")).to_have_count(2)
    if screenshots:
        page.screenshot(path=str(screenshots / "r7-editor-gauge.png"))
    editor.get_by_role("button", name="Apply").click()
    expect(page.locator(".tc-card .tc-gauge").first).to_be_visible()


def test_cards_follow_the_sidebar_folding_and_unfolding(signed_in, app_url):
    # A chart follows its card, not only the window (ui 0.40.0): fold the sidebar, let the cards
    # draw wide, unfold it, and every chart is back inside its narrower card.
    page = signed_in
    page.set_viewport_size({"width": 1440, "height": 1000})
    dashboard_id = _create(page, app_url, GALLERY)
    page.goto(f"{app_url}/dash/d/{dashboard_id}?var-loop=$__all")
    page.get_by_role("button", name="Collapse the menu").click()
    _settle(page, len(GALLERY["cards"]) + 2)
    page.get_by_role("button", name="Expand the menu").click()
    page.wait_for_timeout(1200)
    problems = page.evaluate(CHECK)
    assert not problems, "\n".join(problems)
