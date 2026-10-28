"""Desk's To-do (owner, round 7, 2026-10-24): a to-do added to My day, opened with its steps
and repeat, put in a new list, done (a repeated one moves to its next day and leaves a done
copy), and another turned into an action."""

from __future__ import annotations

import os
import re
from pathlib import Path

from playwright.sync_api import expect

SHOTS = os.environ.get("PLANTCRAFT_E2E_SHOTS", "")
TITLE = "Todo journey: read the night log"
OTHER = "Todo journey: replace the FIC-101 positioner"
LIST = "Todo journey list"


def _clean(page) -> None:
    for view in ("all", "done"):
        for item in page.request.get(f"/api/desk/todos?view={view}").json()["items"]:
            if item["title"].startswith("Todo journey"):
                page.request.delete(f"/api/desk/todos/{item['todo_id']}")
    for item in page.request.get("/api/desk/todos?view=all").json()["lists"]:
        if item["name"] == LIST:
            page.request.delete(f"/api/desk/todo-lists/{item['list_id']}")


def test_a_todo_with_steps_a_repeat_and_a_list(page):
    page.goto("/todo")
    expect(page.get_by_role("heading", name="To-do", exact=True)).to_be_visible()
    expect(page.get_by_role("heading", name="My day")).to_be_visible()
    try:
        box = page.get_by_label("Add a to-do")
        box.fill(TITLE)
        box.press("Enter")
        row = page.locator(".dk-todo-row", has_text=TITLE)
        expect(row).to_be_visible()
        row.get_by_role("button", name=f"Open {TITLE}").click()
        detail = page.get_by_role("complementary", name="To-do")
        expect(detail.get_by_role("button", name="In My day")).to_be_visible()
        for step in ("Unit 1", "Unit 2"):
            detail.get_by_label("Add a step").fill(step)
            detail.get_by_label("Add a step").press("Enter")
            expect(detail.get_by_text(step, exact=True)).to_be_visible()
        detail.get_by_label("Repeat").select_option("weekdays")
        expect(row.get_by_label("Repeats")).to_be_visible()
        expect(row).to_contain_text("0/2 steps")
        # A new list, then the to-do moved into it.
        page.get_by_role("button", name="New list").click()
        page.get_by_label("List name").fill(LIST)
        page.get_by_label("List name").press("Enter")
        expect(page.get_by_role("heading", name=LIST)).to_be_visible()
        page.get_by_role("button", name="My day").first.click()
        page.locator(".dk-todo-row", has_text=TITLE).get_by_role(
            "button", name=f"Open {TITLE}"
        ).click()
        page.get_by_role("complementary", name="To-do").get_by_label("List").select_option(
            label=LIST
        )
        expect(page.locator(".dk-todo-row", has_text=TITLE)).to_contain_text(LIST)
        if SHOTS:
            page.screenshot(path=str(Path(SHOTS) / "todo-my-day.png"), full_page=True)
        # Done: it repeats, so it leaves My day for its next weekday and a copy goes to Done.
        page.locator(".dk-todo-items").first.get_by_role(
            "button", name=f"Mark {TITLE} done"
        ).click()
        expect(page.locator(".dk-todo-done summary")).to_contain_text("Done (")
        expect(page.locator(".dk-todo-items").first.get_by_text(TITLE)).to_have_count(0)
        page.get_by_role("button", name=LIST).click()
        expect(page.locator(".dk-todo-items").first.get_by_text(TITLE)).to_be_visible()
        # Another one becomes an action.
        page.get_by_role("button", name="My day").first.click()
        box.fill(OTHER)
        box.press("Enter")
        page.locator(".dk-todo-row", has_text=OTHER).get_by_role(
            "button", name=f"Open {OTHER}"
        ).click()
        page.get_by_role("button", name="Turn into an action").click()
        expect(page).to_have_url(re.compile(r"/actions/\d+$"))
        expect(page.get_by_text(OTHER).first).to_be_visible()
    finally:
        _clean(page)
