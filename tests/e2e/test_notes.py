"""Desk's Notes (owner, round 7, 2026-10-24): a note written with a heading, a checklist and a
`#` mention of an asset, saved as one types; a line of it turned into a to-do; the note shared
and pinned; and a calendar event's note opened from the event."""

from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import expect

SHOTS = os.environ.get("PLANTCRAFT_E2E_SHOTS", "")
TITLE = "Notes journey: night shift"
LINE = "Notes journey: check the positioner"
EVENT = "Notes journey meeting"


def _clean(page) -> None:
    for item in page.request.get("/api/desk/notes").json()["items"]:
        if item["title"].startswith("Notes journey"):
            page.request.delete(f"/api/desk/notes/{item['note_id']}")
    for view in ("all", "done"):
        for item in page.request.get(f"/api/desk/todos?view={view}").json()["items"]:
            if item["title"].startswith("Notes journey"):
                page.request.delete(f"/api/desk/todos/{item['todo_id']}")


def test_a_note_with_a_checklist_a_mention_and_a_todo(page):
    page.goto("/notes")
    expect(page.get_by_role("heading", name="Notes", exact=True)).to_be_visible()
    try:
        page.get_by_role("button", name="New note").click()
        page.get_by_role("textbox", name="Title").fill(TITLE)
        body = page.get_by_role("textbox", name="Note")
        body.click()
        page.keyboard.type("Handover")
        page.get_by_role("button", name="Heading").click()
        page.keyboard.press("End")
        page.keyboard.press("Enter")
        page.get_by_role("button", name="Checklist").click()
        page.keyboard.type(LINE + " ")
        page.keyboard.type("#FIC")
        options = page.get_by_role("listbox", name="References")
        expect(options.get_by_role("option").first).to_be_visible()
        page.keyboard.press("Enter")
        expect(body.locator(".dk-mention")).to_have_count(1)
        expect(page.get_by_role("status").filter(has_text="Saved")).to_be_visible()
        # The line under the cursor becomes a to-do.
        page.get_by_role("button", name="Line to to-do").click()
        expect(page.get_by_text("To-do added:")).to_be_visible()
        # Shared (with the first person or group offered) and pinned; the list shows both.
        share = page.get_by_label("Share with", exact=True)
        name = share.locator("optgroup option").first.text_content()
        share.select_option(label=name)
        expect(page.locator(".dk-note-share .dk-chip", has_text=name)).to_be_visible()
        page.get_by_role("button", name="Pin", exact=True).click()
        row = page.locator(".dk-note-row", has_text=TITLE)
        expect(row.get_by_label("Pinned")).to_be_visible()
        expect(row.get_by_label("Shared")).to_be_visible()
        if SHOTS:
            page.screenshot(path=str(Path(SHOTS) / "notes.png"), full_page=True)
        # Back again: the body was saved with its mention.
        page.reload()
        page.locator(".dk-note-row", has_text=TITLE).click()
        expect(page.get_by_role("textbox", name="Note").locator(".dk-mention")).to_have_count(1)
        todos = page.request.get("/api/desk/todos?view=all").json()["items"]
        assert any(item["title"].startswith(LINE) for item in todos)
    finally:
        _clean(page)


def test_an_event_opens_its_note(page):
    made = page.request.post(
        "/api/desk/events",
        data={"title": EVENT, "start": "2026-10-26T09:00", "end": "2026-10-26T10:00"},
    ).json()
    try:
        page.goto(f"/notes?event=event:{made['event_id']}&title={EVENT}")
        expect(page.get_by_role("textbox", name="Title")).to_have_value(EVENT)
        expect(page.locator(".dk-note-meta").get_by_text("Calendar event")).to_be_visible()
        # The second time, the same note opens again.
        page.goto(f"/notes?event=event:{made['event_id']}&title={EVENT}")
        expect(page.get_by_role("textbox", name="Title")).to_have_value(EVENT)
        notes = page.request.get(f"/api/desk/notes?event=event:{made['event_id']}").json()
        assert len(notes["items"]) == 1
    finally:
        _clean(page)
        page.request.delete(f"/api/desk/events/{made['event_id']}")
