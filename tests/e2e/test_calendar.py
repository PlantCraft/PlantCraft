"""Desk's calendar: an event made by dragging over the hours, repeated,
moved by dragging (the whole series moves) and deleted; the apps' runs start hidden."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from playwright.sync_api import expect

TITLE = "Calendar journey: shift handover"
SHOTS = os.environ.get("PLANTCRAFT_E2E_SHOTS", "")


def _slot(page, hour: str):
    slot = page.locator(f'.fc-timegrid-slot-lane[data-time="{hour}"]').first
    slot.scroll_into_view_if_needed()
    box = slot.bounding_box()
    assert box
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def _drag(page, start: tuple[float, float], end: tuple[float, float]) -> None:
    page.mouse.move(*start)
    page.mouse.down()
    page.mouse.move(start[0], start[1] + 5, steps=3)
    page.mouse.move(*end, steps=8)
    page.mouse.up()


def _mine(page) -> list[dict]:
    today = datetime.now().astimezone().date().isoformat()
    events = page.request.get(f"/api/desk/calendar?start={today}&end={today}").json()["events"]
    return [item for item in events if item["kind"] == "event" and item["title"] == TITLE]


def test_an_event_is_made_by_dragging_repeated_and_moved(page):
    today = datetime.now().astimezone().date().isoformat()
    page.goto(f"/calendar?date={today}")
    expect(page.locator(".fc-timeGridDay-view")).to_be_visible()
    runs = page.get_by_role("group", name="Show").get_by_role("button", name="Scheduled runs")
    expect(runs).to_have_attribute("aria-pressed", "false")
    try:
        _drag(page, _slot(page, "10:00:00"), _slot(page, "11:00:00"))
        dialog = page.get_by_role("dialog", name="New event")
        expect(dialog).to_be_visible()
        dialog.get_by_label("Title").fill(TITLE)
        dialog.get_by_label("Repeat").select_option("weekdays")
        if SHOTS:
            dialog.screenshot(path=str(Path(SHOTS) / "calendar-new-event.png"))
        dialog.get_by_role("button", name="Save").click()
        expect(dialog).to_be_hidden()
        event = page.locator(".fc-event", has_text=TITLE)
        expect(event).to_be_visible()
        if SHOTS:
            page.get_by_role("button", name="week", exact=True).click()
            page.screenshot(path=str(Path(SHOTS) / "calendar-week.png"), full_page=True)
            page.get_by_role("button", name="day", exact=True).click()
        [made] = _mine(page)
        assert made["repeat"] == "weekdays"
        assert made["start"][11:16] != made["end"][11:16]
        before = datetime.fromisoformat(made["start"].replace("Z", "+00:00")).astimezone()
        assert before.hour == 10
        # Dragged three hours later: the series moves with it.
        box = event.bounding_box()
        assert box
        top = (box["x"] + box["width"] / 2, box["y"] + 6)
        target = _slot(page, "13:00:00")
        _drag(page, top, (top[0], top[1] + (target[1] - _slot(page, "10:00:00")[1])))
        # The drag mirror stays until the move is saved; a slow runner still shows both.
        expect(page.locator(".fc-event-mirror")).to_have_count(0)
        expect(page.locator(".fc-event", has_text=TITLE)).to_be_visible()
        page.wait_for_function(
            """(title) => fetch(`/api/desk/calendar?start=${new Date().toLocaleDateString('sv')}&end=${new Date().toLocaleDateString('sv')}`)
              .then((r) => r.json()).then((d) => d.events.some((e) => e.title === title && new Date(e.series_start).getHours() === 13))""",
            arg=TITLE,
        )
        page.locator(".fc-event", has_text=TITLE).click()
        edit = page.get_by_role("dialog", name="Event")
        expect(edit.get_by_text("changes every time it repeats")).to_be_visible()
        edit.get_by_role("button", name="Delete").click()
        expect(page.locator(".fc-event", has_text=TITLE)).to_have_count(0)
    finally:
        for item in _mine(page):
            page.request.delete(f"/api/desk/events/{item['event_id']}")


def test_the_title_jumps_to_a_month_or_the_whole_year(page):
    # Round 8: the title opens a picker (a year with arrows, its twelve months); the year opens
    # the year view.
    page.goto("/calendar?date=2026-12-15")
    page.get_by_role("button", name="month", exact=True).click()
    title = page.locator(".fc-pickDate-button")
    expect(title).to_have_text("December 2026")
    title.click()
    picker = page.get_by_role("dialog", name="Go to a month")
    expect(picker.get_by_role("button", name="Dec")).to_have_attribute("aria-pressed", "true")
    picker.get_by_role("button", name="Previous year").click()
    picker.get_by_role("button", name="Mar").click()
    expect(picker).to_be_hidden()
    expect(title).to_have_text("March 2025")
    title.click()
    picker.get_by_role("button", name="2025").click()
    expect(page.locator(".fc-multiMonthYear-view")).to_be_visible()
    expect(title).to_have_text("2025")
    if SHOTS:
        page.screenshot(path=str(Path(SHOTS) / "calendar-year.png"), full_page=True)
