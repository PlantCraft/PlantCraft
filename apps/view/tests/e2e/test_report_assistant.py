"""An assistant section in a real browser (prototype E2): picked from the report's cells, its
assets and analyses ticked, written when the PDF is made, and its feedback turned into the next
requirements (the fake's model answers the same text every time)."""

from __future__ import annotations

import os

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


def test_an_assistant_section_is_set_up_written_and_tuned(signed_in, app_url, screenshots):
    page = signed_in
    answer = page.request.post(
        f"{app_url}/dash/api/reports",
        data={"name": "Unit 100 weekly", "period": "7d", "sections": []},
    )
    assert answer.ok, answer.text()
    report_id = answer.json()["report_id"]
    page.goto(f"{app_url}/dash/reports/{report_id}")
    page.locator(".tc-toolbar").get_by_role("button", name="Edit", exact=True).click()
    page.locator(".tc-report-add-button", has_text="Assistant").click()
    dialog = page.get_by_role("dialog", name="Assistant section")
    expect(dialog.get_by_label("Control loop performance")).to_be_checked()
    dialog.get_by_label("Alarms").check()
    dialog.locator(".tc-report-asset-list label", has_text="Unit 100").get_by_role(
        "checkbox"
    ).check()
    _shot(page, screenshots, "9-assistant-setup")
    dialog.get_by_role("button", name="Apply").click()
    page.get_by_role("button", name="Save").click()
    expect(page.get_by_role("status")).to_contain_text("Saved.")
    expect(page.locator(".tc-report-assistant")).to_contain_text("Not written yet")
    page.get_by_role("button", name="Download", exact=True).click()
    page.get_by_role("dialog", name="Download the report").get_by_role(
        "button", name="PDF"
    ).first.click()
    page.reload()
    expect(page.locator(".tc-report-assistant .pc-markdown")).to_be_visible()
    page.get_by_label("Feedback for the next edition").fill("Shorter: the worst loops first.")
    page.get_by_role("button", name="Propose new requirements").click()
    expect(page.get_by_label("Proposed requirements")).to_be_visible()
    _shot(page, screenshots, "9-assistant-proposal")
    page.locator(".tc-report-feedback").get_by_role("button", name="Apply").click()
    expect(page.locator(".tc-report-feedback")).to_contain_text("Requirements v2 saved")
    _shot(page, screenshots, "9-assistant-written")
