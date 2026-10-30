"""The Executions page: every app's runs and schedules, read-only, each row linking into its app."""

from __future__ import annotations

import re

from playwright.sync_api import expect


def _publish(page) -> None:
    """LinkCraft reports a run and a schedule, as the app does with its key (here: the admin)."""

    api = page.context.request
    token = api.post("/api/v1/auth/token").json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    runs = [
        {"app": "linkcraft", "id": "e2e-round", "name": "E2E morning round", "status": "failed",
         "trigger": "schedule", "started_at": "2026-10-20T06:00:00Z", "subjects": ["signal:scenario:pv"],
         "summary": "Source unreachable", "url": "/link/runs/e2e-round"},
        {"app": "linkcraft", "id": "e2e-manual", "name": "E2E manual check", "status": "done",
         "trigger": "manual", "started_at": "2026-10-20T05:00:00Z"},
    ]  # fmt: skip
    answer = api.put("/api/v1/runs", data=runs, headers=headers)
    assert answer.ok and answer.json()["saved"] == 2, answer.text()
    schedules = [{"id": "daily", "name": "E2E daily round", "cadence": "every day at 06:00"}]
    answer = api.put("/api/v1/schedules?app=linkcraft", data=schedules, headers=headers)
    assert answer.ok, answer.text()


def test_executions_lists_runs_and_schedules_of_every_app(page):
    _publish(page)
    # Hidden from the menu, still served at its address.
    page.goto("/")
    expect(page.get_by_role("link", name="Runs and schedules")).to_have_count(0)
    page.goto("/executions")
    expect(page.get_by_role("heading", name="Runs and schedules", exact=True)).to_be_visible()
    runs = page.locator("section", has=page.get_by_role("heading", name="Runs"))
    failed = runs.locator("tbody tr", has_text="E2E morning round")
    expect(failed).to_contain_text("Failed")
    expect(failed).to_contain_text("Analytics")
    expect(failed.get_by_role("link", name="E2E morning round")).to_have_attribute(
        "href", "/link/runs/e2e-round"
    )
    expect(runs.locator("tbody tr", has_text="E2E manual check")).to_be_visible()
    # Column filters are the suite's MultiSelect (@plantcraft/ui 0.13.0).
    runs.locator(".pc-multi-button", has_text="Status").click()
    runs.get_by_role("option", name=re.compile(r"^Failed")).click()
    page.keyboard.press("Escape")
    expect(runs.locator("tbody tr", has_text="E2E manual check")).to_have_count(0)
    expect(failed).to_be_visible()
    schedules = page.locator("section", has=page.get_by_role("heading", name="Schedules"))
    schedules.locator(".pc-multi-button", has_text="App").click()
    schedules.get_by_role("option", name=re.compile(r"Analytics")).click()
    page.keyboard.press("Escape")
    expect(schedules.locator("tbody tr", has_text="E2E daily round")).to_contain_text(
        "every day at 06:00"
    )
