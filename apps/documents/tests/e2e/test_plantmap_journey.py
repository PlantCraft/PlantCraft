"""The plant map in a real browser: the demo's P&IDs sent, found as diagrams, joined into a map."""

from __future__ import annotations

import os
import time

import httpx
import pytest

try:
    from playwright.sync_api import expect
except ImportError:
    if os.environ.get("DOCCRAFT_E2E_REQUIRED") == "1":
        raise
    pytest.skip("Playwright is not installed", allow_module_level=True)

reportlab = pytest.importorskip("reportlab")


def _shot(page, screenshots, name):
    if screenshots:
        page.wait_for_timeout(800)
        page.screenshot(path=str(screenshots / f"{name}.png"), full_page=True)


def test_pids_become_diagrams_and_a_plant_map(signed_in, app_url, fake, tmp_path, screenshots):
    from doccraft.plantmap.sample.draw import draw_all

    headers = {"Authorization": f"Bearer {fake.token('engineer')}"}
    with httpx.Client(base_url=f"{app_url}/doc", headers=headers, timeout=30) as http:
        for sheet, canvas, _ in draw_all():
            pdf = tmp_path / f"{sheet}.pdf"
            canvas.pdf(pdf)
            answer = http.post(
                "/api/documents",
                params={"filename": pdf.name, "number": sheet, "kind": "P&ID"},
                content=pdf.read_bytes(),
            )
            assert answer.status_code == 201, answer.text
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and len(http.get("/api/diagrams").json()) < 14:
            time.sleep(0.5)
        assert len(http.get("/api/diagrams").json()) == 14

    page = signed_in
    page.set_viewport_size({"width": 1500, "height": 950})
    page.goto(f"{app_url}/doc/diagrams")
    expect(page.get_by_role("heading", name="Diagrams")).to_be_visible()
    expect(page.get_by_text("PID-U-100-01").first).to_be_visible()
    _shot(page, screenshots, "map-1-diagrams")
    page.get_by_role("link", name="PID-U-100-04").first.click()
    expect(page.get_by_role("heading", name="Found on this page")).to_be_visible()
    page.get_by_role("button", name="D-1106").first.click()
    expect(page.locator(".diagram-picked")).to_contain_text("LT-1106")
    _shot(page, screenshots, "map-2-diagram")
    page.goto(f"{app_url}/doc/plant-map")
    expect(page.get_by_role("heading", name="Plant map")).to_be_visible()
    expect(page.get_by_text("Loops complete")).to_be_visible()
    page.locator(".map-node", has_text="E-1009").first.click()
    expect(page.locator(".map-item")).to_contain_text("P-1001")
    # From the map to the plant: a loop PlantCraft has opens its asset, its signals in the
    # Historian and what the apps say about it.
    page.locator("tr", has_text="FIC-1001").first.click()
    signals = page.locator(".map-item").get_by_role("link", name="its signals")
    expect(signals).to_have_attribute("href", "/assets/FIC-1001?tab=signals")
    page.locator(".map-node", has_text="E-1009").first.click()
    _shot(page, screenshots, "map-3-plant-map")

    # An editor checks the map: Correct makes an item sure, Wrong takes a line out, Undo
    # brings it back.
    card = page.locator(".map-item")
    card.locator(".map-review").first.get_by_role("button", name="Correct").click()
    expect(card.locator(".map-review").first).to_contain_text("Checked")
    line = card.locator("li", has_text="P-1001").first
    line.get_by_role("button", name="Wrong").click()
    rejected = page.locator(".panel", has=page.get_by_role("heading", name="Rejected"))
    expect(rejected).to_contain_text("P-1001 feeds E-1009")
    _shot(page, screenshots, "map-4-checked")
    rejected.get_by_role("button", name="Undo").click()
    expect(page.get_by_role("heading", name="Rejected")).to_have_count(0)

    # The plant's own tag list, compared in the browser.
    tag_list = tmp_path / "tags.csv"
    tag_list.write_text("tag,description\nP-1001,Feed pump\nE-1009,Cooler\nXV-9999,Not drawn\n")
    page.get_by_label("Tag list").set_input_files(str(tag_list))
    match = page.locator(".map-match")
    expect(match).to_contain_text("2 tags on both")
    expect(match).to_contain_text("XV-9999")
    _shot(page, screenshots, "map-5-tag-list")
