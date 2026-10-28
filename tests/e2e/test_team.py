"""Desk's Team (owner, round 7, 2026-10-24): a group's people, its board (the leader drags a
card to someone else), the week ahead and the day's shift handover note."""

from __future__ import annotations

import os
import re
import secrets
from pathlib import Path

from playwright.sync_api import expect

SHOTS = os.environ.get("PLANTCRAFT_E2E_SHOTS", "")
GROUP = "team-journey"
CARD = "Team journey: replace the TIC-1209 thermocouple"


def test_a_leader_hands_a_card_over_and_writes_the_handover(page):
    # 409 when an earlier run made him: fine.
    page.request.post(
        "/api/users",
        data={
            "username": "team.rui",
            "display_name": "Rui Team",
            "role": "Operator",
            "password": secrets.token_urlsafe(18),
            "access_level": "editor",
        },
    )
    page.request.post(
        "/api/groups",
        data={
            "group_id": GROUP,
            "name": "Team journey",
            "kind": "area",
            "members": ["admin", "team.rui"],
            "coordinator": "admin",
        },
    )
    action = page.request.post(
        "/api/actions",
        data={
            "title": CARD,
            "description": "",
            "priority": "high",
            "owner": None,
            "group_id": GROUP,
            "due_at": None,
            "refs": [],
        },
    ).json()
    try:
        page.goto(f"/team?group={GROUP}")
        expect(page.get_by_role("heading", name="Team", exact=True)).to_be_visible()
        people = page.get_by_role("region", name="People")
        expect(people.get_by_text("Rui Team")).to_be_visible()
        expect(people.get_by_role("button", name="Message Rui Team")).to_be_visible()
        board = page.get_by_role("region", name="Group board")
        board.get_by_role("button", name="By person").click()
        card = board.locator(f"[data-action='{action['action_id']}']")
        expect(board.locator("[data-column='']").get_by_text(CARD)).to_be_visible()
        rui = board.locator("[data-column='team.rui']")
        # On a busy CI runner a drag can miss (the card stays put, no request is sent). Dropping
        # on the column the card is already in changes nothing, so a missed drag is tried again.
        for _ in range(3):
            card.drag_to(rui)
            try:
                expect(rui.get_by_text(CARD)).to_be_visible(timeout=3000)
                break
            except AssertionError:
                continue
        expect(rui.get_by_text(CARD)).to_be_visible()
        assert page.request.get(f"/api/actions/{action['action_id']}").json()["owner"] == "team.rui"
        if SHOTS:
            page.screenshot(path=str(Path(SHOTS) / "team.png"), full_page=True)
        page.get_by_role("button", name="Write today's handover").click()
        expect(page.get_by_role("textbox", name="Title")).to_have_value(
            re.compile(r"^Handover · Team journey · ")
        )
        expect(page.locator(".dk-note-share .dk-chip", has_text="Team journey")).to_be_visible()
        page.goto(f"/team?group={GROUP}")
        expect(page.get_by_role("button", name="Open today's handover")).to_be_visible()
        # Round 8: all groups at a glance; the administrator sees every group.
        page.goto("/team?group=all")
        glance = page.get_by_role("region", name="Team journey")
        expect(glance.get_by_text("Rui Team")).to_be_visible()
        glance.get_by_role("button", name="Team journey").click()
        expect(page.get_by_role("region", name="Group board")).to_be_visible()
    finally:
        for note in page.request.get("/api/desk/notes").json()["items"]:
            if (note.get("event_ref") or "").startswith(f"handover:{GROUP}:"):
                page.request.delete(f"/api/desk/notes/{note['note_id']}")
        page.request.put(
            f"/api/actions/{action['action_id']}",
            data={
                "title": CARD,
                "description": "",
                "priority": "high",
                "status": "cancelled",
                "owner": None,
                "group_id": None,
                "due_at": None,
                "refs": [],
            },
        )
        page.request.delete(f"/api/groups/{GROUP}")
