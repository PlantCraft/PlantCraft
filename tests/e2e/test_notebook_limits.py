"""Setup › Notebooks: an administrator sets how much one person may ask the plant for."""

from __future__ import annotations

import os


def test_an_administrator_sets_the_limits_for_each_person(page):
    page.goto("/setup/notebooks")
    page.get_by_role("heading", name="Limits for each person").wait_for()
    requests = page.get_by_label("Requests a minute")
    assert requests.input_value() == "120"
    requests.fill("60")
    page.get_by_label("Reads at once").fill("3")
    page.get_by_role("button", name="Save").click()
    page.get_by_text("Every server process follows within 10 seconds.").wait_for()
    shots = os.environ.get("PLANTCRAFT_E2E_SHOTS")
    if shots:
        page.screenshot(path=os.path.join(shots, "setup-notebooks-limits.png"), full_page=True)
    limits = page.request.get("/api/notebooks").json()["limits"]
    assert (limits["per_minute"], limits["concurrent"], limits["updated_by"]) == (60, 3, "admin")
