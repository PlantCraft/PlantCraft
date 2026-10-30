"""Sources and signals (the Historian's) and importing assets from a file, with its undo."""

from __future__ import annotations

import json
import re

from playwright.sync_api import expect


def test_sources_and_signals_point_to_the_historian(page):
    """plant data belongs to the Historian, not to the platform."""

    page.goto("/data")
    expect(
        page.get_by_role("heading", name="Sources and signals are in the Historian")
    ).to_be_visible()
    expect(page.locator(".src-table")).to_have_count(0)


def test_an_asset_import_is_applied_and_undone(page, tmp_path):
    """Setup's Configuration file is gone: the asset import remains, and the
    last import can be undone once, after a confirmation on the page."""

    page.goto("/data/import")  # the old address lands on the asset import
    expect(page).to_have_url(re.compile(r"/asset-import$"))
    path = tmp_path / "unit-950.json"
    unit = {"asset_id": "U-950", "name": "Unit 950", "type": "unit"}
    path.write_text(json.dumps({"assets": [unit]}))
    page.set_input_files("input[type=file]", str(path))
    expect(page.get_by_role("heading", name="Review the import")).to_be_visible()
    page.get_by_role("button", name="Apply", exact=True).click()
    expect(page.get_by_role("heading", name="Assets imported")).to_be_visible()
    page.goto("/asset-import")
    last = page.locator(".ai-last")
    expect(last).to_contain_text("1 created, 0 updated")
    last.get_by_role("button", name="Undo last import").click()
    last.get_by_role("button", name="Undo the import").click()
    expect(last).to_contain_text("Import undone. Assets removed: 1.")
    expect(last.get_by_role("button", name="Undo last import")).to_have_count(0)
    page.goto("/assets/U-950")
    expect(page.get_by_role("heading", name="Unit 950")).to_have_count(0)
