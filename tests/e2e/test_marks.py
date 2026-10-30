"""A person's own marks in the browser: a notification checked done from its row
and from the page it opened, seen and not seen with one button, favorites in the notifications and
the conversations."""

from __future__ import annotations

import os
import re
from pathlib import Path

from playwright.sync_api import expect

from tests.e2e.conftest import _open_page
from tests.test_collaboration import PASSWORD

SHOTS = os.environ.get("PLANTCRAFT_E2E_SHOTS")


def _shot(page, name: str) -> None:
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(SHOTS) / name), full_page=True)


def _colleague(page, browser, server):
    """Rui comments on the action the administrator gave them and writes to them: a notification, a
    chat."""

    made = page.request.post(
        "/api/users",
        data={
            "username": "rui-marks",
            "display_name": "Rui Marks",
            "role": "Operations",
            "password": PASSWORD,
            "access_level": "editor",
        },
    )
    assert made.ok, made.text()
    action = page.request.post(
        "/api/actions",
        data={
            "title": "Check FIC-1003 valve",
            "description": "",
            "priority": "high",
            "owner": "rui-marks",
            "due_at": None,
            "refs": [],
        },
    ).json()
    context, other, _errors, _outside = _open_page(browser, server, "en-US")
    assert context.request.post(
        "/api/login", data={"username": "rui-marks", "password": PASSWORD}
    ).ok
    assert context.request.post(
        f"/api/actions/{action['action_id']}/comments", data={"text": "Stem is sticking."}
    ).ok
    assert context.request.post(
        "/api/messages/conversations", data={"members": ["admin"], "text": "Can you look at it?"}
    ).ok
    context.close()
    return action


def test_a_notification_is_checked_where_it_is_handled(page, browser, server):
    action = _colleague(page, browser, server)
    page.goto("/messages/notifications")
    row = page.locator(".nt-row").filter(has_text="Check FIC-1003 valve").first
    expect(row).to_be_visible()
    row.hover()
    row.get_by_role("button", name="Add to favorites").click()
    expect(row.get_by_role("button", name="Remove from favorites")).to_be_visible()
    # One button, both ways.
    row.get_by_role("button", name="Mark as seen").click()
    expect(row.locator(".nt-item")).not_to_have_class(re.compile("unread"))
    row.get_by_role("button", name="Mark as not seen").click()
    expect(row.locator(".nt-item")).to_have_class(re.compile("unread"))
    _shot(page, "marks-1-notification-row.png")

    page.get_by_role("button", name="Favorites", exact=True).click()
    expect(page.locator(".nt-row").filter(has_text="Check FIC-1003 valve")).to_have_count(1)
    page.get_by_role("button", name="All", exact=True).click()

    # Open it, then its page: the bar there checks it done.
    row.locator(".nt-item").click()
    pane = page.locator(".nt-pane")
    expect(pane.get_by_role("button", name="Mark as done")).to_be_visible()
    _shot(page, "marks-2-notification-open.png")
    pane.get_by_role("link", name="Open").click()
    expect(page).to_have_url(re.compile(rf"/actions/{action['action_id']}$"))
    bar = page.locator(".nt-follow")
    expect(bar).to_contain_text("Check FIC-1003 valve")
    _shot(page, "marks-3-bar-on-the-action.png")
    bar.get_by_role("button", name="Mark as done").click()
    expect(bar).to_contain_text("Notification marked done")
    page.goto("/messages/notifications")
    expect(page.locator(".nt-row").filter(has_text="Check FIC-1003 valve")).to_have_count(0)
    page.get_by_role("button", name="Done", exact=True).click()
    expect(page.locator(".nt-row").filter(has_text="Check FIC-1003 valve")).to_have_count(1)


def test_a_conversation_is_starred_and_unread_again(page, browser, server):
    page.goto("/messages")
    row = page.locator(".msg-row-item").filter(has_text="Rui Marks").first
    expect(row).to_be_visible()
    row.hover()
    row.get_by_role("button", name="Mark as read").click()
    expect(row.locator(".msg-item")).not_to_have_class(re.compile("unread"))
    row.get_by_role("button", name="Mark as unread").click()
    expect(row.locator(".msg-item")).to_have_class(re.compile("unread"))
    row.get_by_role("button", name="Add to favorites").click()
    expect(row.locator(".nt-starred")).to_be_visible()
    _shot(page, "marks-4-conversations.png")
    # Opened, it is read; from its header, unread again.
    row.locator(".msg-item").click()
    head = page.locator(".msg-chat-head")
    expect(head.get_by_role("button", name="Remove from favorites")).to_be_visible()
    head.get_by_role("button", name="Mark as unread").click()
    expect(page).to_have_url(re.compile(r"/messages$"))
    expect(row.locator(".msg-item")).to_have_class(re.compile("unread"))
