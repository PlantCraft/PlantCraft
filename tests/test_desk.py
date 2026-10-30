# ruff: noqa: F811  (the fixture ``signed`` comes from test_collaboration.py)
"""Desk, each person's day (docs/desk.md): checklist and routines, followed assets, calendars,
triage, suggestions and a leader's team."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from plantcraft.api.routers.desk import note_mentions
from plantcraft.config import plant_today
from plantcraft.desk import (
    CalendarError,
    event_times,
    feed_url,
    host_allowed,
    next_due,
    occurrences,
    parse_ics,
    suggest,
    todo_due,
)
from tests.test_collaboration import _asset_id, _person, _publish_result, signed  # noqa: F401

ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:standup@test
DTSTART:20261019T090000Z
DTEND:20261019T091500Z
RRULE:FREQ=WEEKLY;BYDAY=MO,WE;COUNT=6
EXDATE:20261021T090000Z
SUMMARY:Shift meeting
LOCATION:Control room
END:VEVENT
BEGIN:VEVENT
UID:visit@test
DTSTART;VALUE=DATE:20261022
DTEND;VALUE=DATE:20261023
SUMMARY:Supplier visit
END:VEVENT
BEGIN:VEVENT
UID:gone@test
DTSTART:20261020T100000Z
STATUS:CANCELLED
SUMMARY:Cancelled
END:VEVENT
END:VCALENDAR
"""


def test_todos_repeat_on_their_days():
    monday, friday, saturday = date(2026, 10, 19), date(2026, 10, 23), date(2026, 10, 24)
    assert todo_due({"repeat": "daily"}, saturday)
    assert todo_due({"repeat": "weekdays"}, monday) and not todo_due(
        {"repeat": "weekdays"}, saturday
    )
    assert todo_due({"repeat": "days", "days": [5]}, saturday)
    assert not todo_due({"repeat": "days", "days": [0]}, saturday)
    assert next_due({"repeat": "weekdays"}, friday) == date(2026, 10, 26)
    assert next_due({"repeat": "days", "days": [2]}, friday) == date(2026, 10, 28)
    assert next_due({"repeat": ""}, friday) is None


def test_ics_events_are_read_with_their_repeats_and_exceptions():
    events = parse_ics(ICS, today=date(2026, 10, 23))
    titles = [(item["title"], item["start"][:10], item["all_day"]) for item in events]
    # Six Monday/Wednesday meetings, one taken out; the visit is all day; the cancelled one is gone.
    assert [item for item in titles if item[0] == "Shift meeting"][:3] == [
        ("Shift meeting", "2026-10-19", False),
        ("Shift meeting", "2026-10-26", False),
        ("Shift meeting", "2026-10-28", False),
    ]
    assert len([item for item in titles if item[0] == "Shift meeting"]) == 5
    assert ("Supplier visit", "2026-10-22", True) in titles
    assert "Cancelled" not in [item[0] for item in titles]
    assert events[0]["location"] == "Control room"
    try:
        parse_ics("hello")
    except CalendarError:
        pass
    else:  # pragma: no cover
        raise AssertionError("a text that is not a calendar must be refused")


def test_own_events_repeat_in_the_plant_time_zone(monkeypatch):
    monkeypatch.setenv("PLANTCRAFT_TIMEZONE", "America/New_York")
    # 09:00 in New York on a Friday before the change of summer time (2026-11-01).
    start, end = event_times("2026-10-30T09:00", "2026-10-30T09:30", False)
    assert (start, end) == ("2026-10-30T13:00:00.000Z", "2026-10-30T13:30:00.000Z")
    weekly = {"start": start, "end": end, "all_day": False, "repeat": "weekly", "until": None}
    times = occurrences(weekly, date(2026, 10, 1), date(2026, 11, 14))
    # Still 09:00 there after the change: 14:00 UTC.
    assert [item[0] for item in times] == [
        "2026-10-30T13:00:00.000Z",
        "2026-11-06T14:00:00.000Z",
        "2026-11-13T14:00:00.000Z",
    ]
    weekdays = {**weekly, "repeat": "weekdays", "until": "2026-11-03"}
    days = [item[0][:10] for item in occurrences(weekdays, date(2026, 10, 1), date(2026, 11, 30))]
    assert days == ["2026-10-30", "2026-11-02", "2026-11-03"]
    once = {**weekly, "repeat": ""}
    assert occurrences(once, date(2026, 10, 31), date(2026, 11, 30)) == []
    # All day: the end is the day after, as in iCalendar; a several-day event shows while it runs.
    trip = event_times("2026-10-28", "2026-10-31", True)
    assert trip == ("2026-10-28", "2026-10-31")
    shown = occurrences(
        {"start": trip[0], "end": trip[1], "all_day": True, "repeat": ""},
        date(2026, 10, 30),
        date(2026, 11, 2),
    )
    assert shown == [("2026-10-28", "2026-10-31")]
    monthly = {
        "start": "2026-10-31",
        "end": "2026-11-01",
        "all_day": True,
        "repeat": "monthly",
        "until": None,
    }
    assert [item[0] for item in occurrences(monthly, date(2026, 10, 1), date(2026, 12, 31))] == [
        "2026-10-31",
        "2026-12-31",
    ]
    with pytest.raises(ValueError):
        event_times("2026-10-30T10:00", "2026-10-30T09:00", False)
    with pytest.raises(ValueError):
        event_times("2026-01-01", "2026-12-31", True)


def test_calendar_links_are_https_and_only_to_allowed_hosts():
    assert feed_url("webcal://outlook.office365.com/owa/calendar/x/calendar.ics").startswith(
        "https://"
    )
    for bad in ("ftp://x.com/a.ics", "https://user:pw@x.com/a.ics", "file:///etc/passwd"):
        try:
            feed_url(bad)
        except CalendarError:
            continue
        raise AssertionError(bad)
    assert host_allowed("https://outlook.office365.com/a.ics", ["office365.com"])
    assert not host_allowed("https://evil-office365.com/a.ics", ["office365.com"])
    assert not host_allowed("https://10.0.0.5/a.ics", ["office365.com"])


def test_suggestions_say_why_and_respect_what_was_dismissed():
    today = date(2026, 10, 23)
    now = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
    actions = [
        {
            "action_id": 1,
            "title": "Recalibrate PT-204",
            "owner": "ana",
            "due_at": "2026-10-21",
            "updated_at": "2026-10-21T08:00:00+00:00",
        },
        {
            "action_id": 2,
            "title": "Replace positioner",
            "owner": "ana",
            "due_at": "2026-10-23",
            "updated_at": "2026-10-22T08:00:00+00:00",
        },
        {
            "action_id": 3,
            "title": "Filter review",
            "owner": "ana",
            "due_at": None,
            "updated_at": "2026-09-01T08:00:00+00:00",
        },
    ]
    followed = [
        {
            "subject": "asset:FIC-101",
            "name": "FIC-101",
            "status": "alarm",
            "summary": "Oscillating",
            "open_actions": 0,
            "app": "linkcraft",
            "kind": "health",
            "at": "2026-10-23T06:00:00+00:00",
        },
        {
            "subject": "asset:LIC-7",
            "name": "LIC-7",
            "status": "alarm",
            "summary": "Noisy",
            "open_actions": 1,
        },
    ]
    conversations = [
        {
            "conversation_id": 9,
            "unread": 2,
            "display_title": "Carlos",
            "last_message": {
                "message_id": 40,
                "author": "carlos",
                "created_at": "2026-10-22T09:00:00+00:00",
            },
        }
    ]
    found = suggest(
        username="ana",
        today=today,
        actions=actions,
        followed=followed,
        conversations=conversations,
        triage={},
        now=now,
    )
    kinds = [item["key"].split(":")[0] for item in found]
    assert kinds == ["overdue", "followed", "due", "reply", "stale"]
    assert found[0]["reason"] == "Past its due date by 2 days."
    assert found[1]["href"].startswith("/actions?new=1&ref=asset:FIC-101")
    # Done stays away; snoozed until a later day stays away until then.
    triage = {
        found[0]["key"]: {"state": "done", "until": None},
        found[3]["key"]: {"state": "snoozed", "until": "2026-10-24"},
    }
    again = suggest(
        username="ana",
        today=today,
        actions=actions,
        followed=followed,
        conversations=conversations,
        triage=triage,
        now=now,
    )
    assert [item["key"].split(":")[0] for item in again] == ["followed", "due", "stale"]


def test_todos_lists_my_day_and_follows(signed):
    ana = _person(signed, "ana", level="viewer")
    today = plant_today()
    # A reader keeps their own to-dos.
    created = ana.post(
        "/api/desk/todos", json={"title": "Call the analyzer supplier", "my_day": True}
    )
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["my_day"] == today and item["list_id"] is None
    lst = ana.post("/api/desk/todo-lists", json={"name": "Morning"}).json()
    daily = ana.post(
        "/api/desk/todos",
        json={
            "title": "Read the night's alarms",
            "list_id": lst["list_id"],
            "repeat": "daily",
            "steps": [{"text": "Unit 1"}, {"text": "Unit 2", "done": True}],
        },
    ).json()
    assert daily["due"] == today and [step["done"] for step in daily["steps"]] == [False, True]
    mine = ana.get("/api/desk/todos?view=today").json()
    assert [entry["title"] for entry in mine["items"]] == [
        "Read the night's alarms",
        "Call the analyzer supplier",
    ]
    assert mine["lists"][0]["open"] == 1 and mine["counts"]["today"] == 2
    # Done: a repeated one moves to tomorrow, its steps unchecked, and leaves a done copy.
    rolled = ana.patch(f"/api/desk/todos/{daily['todo_id']}", json={"done": True}).json()
    tomorrow = (date.fromisoformat(today) + timedelta(days=1)).isoformat()
    assert rolled["done"] is False and rolled["due"] == tomorrow
    assert not any(step["done"] for step in rolled["steps"])
    done = ana.get("/api/desk/todos?view=done").json()["items"]
    assert [entry["title"] for entry in done] == ["Read the night's alarms"]
    assert ana.patch(f"/api/desk/todos/{item['todo_id']}", json={"done": True}).json()["done"]
    assert len(ana.get("/api/desk/today").json()["todos"]) == 2
    # Off My day, a date taken away, moved out of the list.
    moved = ana.patch(
        f"/api/desk/todos/{daily['todo_id']}", json={"list_id": None, "due": None, "repeat": ""}
    ).json()
    assert (moved["list_id"], moved["due"], moved["repeat"]) == (None, None, "")
    # A reader cannot hand work to others: an action needs editing rights.
    assert ana.post(f"/api/desk/todos/{daily['todo_id']}/action", json={}).status_code == 403
    # Someone else's to-do and list are not theirs.
    bob = _person(signed, "bob")
    assert bob.patch(f"/api/desk/todos/{item['todo_id']}", json={"done": False}).status_code == 404
    assert bob.delete(f"/api/desk/todo-lists/{lst['list_id']}").status_code == 404
    assert ana.delete(f"/api/desk/todo-lists/{lst['list_id']}").status_code == 200

    asset = _asset_id(signed)
    _publish_result(signed, subject=f"asset:{asset}", status="alarm")
    assert ana.put("/api/desk/follows", json={"ref": f"asset:{asset}"}).json()["following"] is True
    assert ana.put("/api/desk/follows", json={"ref": "user:bob"}).status_code == 422
    followed = ana.get("/api/desk/follows").json()["items"]
    assert followed[0]["status"] == "alarm" and followed[0]["summary"] == "Valve stiction suspected"
    today = ana.get("/api/desk/today").json()
    assert any(item["key"].startswith(f"followed:asset:{asset}") for item in today["suggestions"])
    # The alarm reaches Messages' Notifications; archived, it stays among the archived ones.
    feed = ana.get("/api/notifications").json()
    alarm = next(item for item in feed["items"] if item["kind"] == "followed")
    assert alarm["category"] == "alarm" and alarm["state"] == "unread"
    marked = ana.post(
        "/api/notifications/marks", json={"keys": [alarm["key"]], "state": "archived"}
    )
    assert marked.status_code == 200
    states = {item["key"]: item["state"] for item in ana.get("/api/notifications").json()["items"]}
    assert states[alarm["key"]] == "archived"


def test_a_group_list_is_shared_and_set_up_by_its_leader(signed):
    ana = _person(signed, "ana")
    bob = _person(signed, "bob")
    group = signed.post(
        "/api/groups",
        json={"name": "Utilities", "kind": "area", "members": ["ana", "bob"], "coordinator": "ana"},
    )
    assert group.status_code == 201, group.text
    group_id = group.json()["group_id"]
    body = {"name": "Shift start", "group_id": group_id}
    assert bob.post("/api/desk/todo-lists", json=body).status_code == 403
    shared = ana.post("/api/desk/todo-lists", json=body)
    assert shared.status_code == 201, shared.text
    list_id = shared.json()["list_id"]
    todo = ana.post(
        "/api/desk/todos",
        json={"title": "Read the logbook", "list_id": list_id, "repeat": "weekdays"},
    ).json()
    # Everyone in the group sees it and may check it; only the leader renames the list.
    lists = bob.get("/api/desk/todos?view=list&list_id=" + str(list_id)).json()
    assert [entry["title"] for entry in lists["items"]] == ["Read the logbook"]
    assert lists["lists"][0]["editable"] is False and lists["lists"][0]["group_name"] == "Utilities"
    assert bob.patch(f"/api/desk/todos/{todo['todo_id']}", json={"my_day": True}).status_code == 200
    assert bob.patch(f"/api/desk/todo-lists/{list_id}", json={"name": "Mine"}).status_code == 403
    # It becomes an action for bob; the to-do is done and points to it.
    made = ana.post(f"/api/desk/todos/{todo['todo_id']}/action", json={"owner": "bob"})
    assert made.status_code == 201, made.text
    assert (
        signed.get(made.json()["href"].replace("/actions/", "/api/actions/")).json()["owner"]
        == "bob"
    )
    action = signed.post(
        "/api/actions",
        json={
            "title": "Inspect E-101",
            "owner": "bob",
            "group_id": group_id,
            "due_at": (date.fromisoformat(plant_today()) - timedelta(days=2)).isoformat(),
        },
    )
    assert action.status_code == 201, action.text
    action_id = action.json()["action_id"]
    # Team: every member sees the group; the leader also moves its cards.
    bob.post(
        "/api/desk/events",
        json={"title": "Dentist", "start": plant_today(), "all_day": True},
    )
    team = ana.get("/api/desk/team").json()
    assert [item["group_id"] for item in team["groups"]] == [group_id]
    seen = team["group"]
    assert seen["leader"] is True
    people = {item["username"]: item for item in seen["people"]}
    assert people["ana"]["leader"] is True and people["bob"]["late"] == 1
    assert people["bob"]["availability"] == "away"
    assert [card["title"] for card in seen["board"] if card["late"]] == ["Inspect E-101"]
    assert any(item["kind"] == "away" for item in seen["agenda"])
    assert all("Dentist" not in item["title"] for item in seen["agenda"])
    assert seen["lists"][0]["name"] == "Shift start"
    as_bob = bob.get(f"/api/desk/team?group={group_id}").json()["group"]
    assert as_bob["leader"] is False and len(as_bob["board"]) == len(seen["board"])
    move = {"action_id": action_id, "owner": "ana", "status": "in_progress"}
    assert bob.post(f"/api/desk/team/{group_id}/assign", json=move).status_code == 403
    moved = ana.post(f"/api/desk/team/{group_id}/assign", json=move)
    assert moved.status_code == 200, moved.text
    assert moved.json() == {"action_id": action_id, "owner": "ana", "status": "in_progress"}
    outsider = {"action_id": action_id, "owner": "nobody"}
    assert ana.post(f"/api/desk/team/{group_id}/assign", json=outsider).status_code == 422
    # The day's handover note: made once, shared with the group.
    first = bob.post(f"/api/desk/team/{group_id}/handover")
    assert first.status_code == 200, first.text
    assert first.json()["shared"][0]["ref"] == f"group:{group_id}"
    again = ana.post(f"/api/desk/team/{group_id}/handover").json()
    assert again["note_id"] == first.json()["note_id"]
    assert ana.get("/api/desk/team").json()["group"]["handover"]["note_id"] == again["note_id"]
    carla = _person(signed, "carla")
    assert carla.get("/api/desk/team").json() == {"groups": [], "group": None, "overview": None}
    assert carla.get(f"/api/desk/team?group={group_id}").json()["group"] is None
    assert carla.post(f"/api/desk/team/{group_id}/handover").status_code == 404
    # An administrator sees every group's team (round 8), one at a time or all at a glance.
    glance = signed.get("/api/desk/team?group=all").json()
    assert glance["group"] is None
    row = next(item for item in glance["overview"] if item["group_id"] == group_id)
    assert row["leader"] is True and row["open"] == 2 and row["late"] == 1 and row["away"] == 1
    assert {person["username"] for person in row["people"]} == {"ana", "bob"}
    assert signed.get(f"/api/desk/team?group={group_id}").json()["group"]["leader"] is True
    # With one group the page opens on it; with more, on all of them.
    signed.post("/api/groups", json={"name": "Lab", "kind": "team", "members": ["ana"]})
    both = ana.get("/api/desk/team").json()
    assert both["group"] is None and len(both["overview"]) == 2


def test_calendar_brings_dated_work_together(signed):
    ana = _person(signed, "ana")
    today = date.fromisoformat(plant_today())
    signed.post(
        "/api/actions",
        json={
            "title": "Tune LIC-07",
            "owner": "ana",
            "due_at": (today + timedelta(days=3)).isoformat(),
        },
    )
    ana.post("/api/desk/todos", json={"title": "Validate lab data", "due": today.isoformat()})
    ana.post("/api/desk/todos", json={"title": "Five worst loops", "repeat": "daily"})
    imported = ana.post(
        "/api/desk/calendars",
        json={
            "name": "Outlook",
            "ics": ICS.replace("20261019", today.strftime("%Y%m%d"))
            .replace("20261022", today.strftime("%Y%m%d"))
            .replace("20261023", (today + timedelta(days=1)).strftime("%Y%m%d")),
        },
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["count"] >= 1
    # Links stay off until an administrator turns them on and names the hosts.
    assert (
        ana.post(
            "/api/desk/calendars",
            json={"name": "Google", "url": "https://calendar.google.com/x.ics"},
        ).status_code
        == 403
    )
    assert (
        ana.put("/api/desk/settings", json={"enabled": True, "hosts": ["google.com"]}).status_code
        == 403
    )
    assert (
        signed.put("/api/desk/settings", json={"enabled": True, "hosts": ["https://x"]}).status_code
        == 422
    )
    assert (
        signed.put(
            "/api/desk/settings", json={"enabled": True, "hosts": ["calendar.google.com"]}
        ).json()["calendar_links"]
        is True
    )
    start, end = (today - timedelta(days=1)).isoformat(), (today + timedelta(days=7)).isoformat()
    events = ana.get(f"/api/desk/calendar?start={start}&end={end}").json()["events"]
    kinds = {item["kind"] for item in events}
    assert {"action", "todo", "external"} <= kinds
    # The daily to-do is on today and on every day ahead.
    assert len([item for item in events if item["title"] == "Five worst loops"]) == 8
    action = next(item for item in events if item["kind"] == "action")
    assert action["editable"] is True and action["title"] == "Tune LIC-07"
    # The widest view is a year (round 8); more is refused.
    assert ana.get("/api/desk/calendar?start=2026-01-01&end=2026-12-31").status_code == 200
    assert ana.get("/api/desk/calendar?start=2026-01-01&end=2027-03-01").status_code == 422
    calendar_id = imported.json()["calendar_id"]
    assert ana.delete(f"/api/desk/calendars/{calendar_id}").status_code == 200


def test_own_events_on_the_calendar(signed):
    ana = _person(signed, "ana")
    today = date.fromisoformat(plant_today())
    first = (today + timedelta(days=1)).isoformat()
    made = ana.post(
        "/api/desk/events",
        json={
            "title": "Shift handover",
            "start": f"{first}T07:00:00Z",
            "end": f"{first}T07:30:00Z",
            "repeat": "daily",
            "until": (today + timedelta(days=3)).isoformat(),
        },
    )
    assert made.status_code == 201, made.text
    event_id = made.json()["event_id"]
    assert (
        ana.post(
            "/api/desk/events", json={"title": "x", "start": first, "repeat": "yearly"}
        ).status_code
        == 422
    )
    start, end = today.isoformat(), (today + timedelta(days=7)).isoformat()
    own = [
        item
        for item in ana.get(f"/api/desk/calendar?start={start}&end={end}").json()["events"]
        if item["kind"] == "event"
    ]
    assert len(own) == 3 and all(item["editable"] for item in own)
    assert own[0]["series_start"] == f"{first}T07:00:00.000Z"
    # Moving one time moves the series; a null end day lets it go on.
    moved = ana.patch(
        f"/api/desk/events/{event_id}",
        json={"start": f"{first}T08:00:00Z", "end": f"{first}T09:00:00Z", "until": None},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["until"] is None and moved.json()["start"].endswith("T08:00:00.000Z")
    again = [
        item
        for item in ana.get(f"/api/desk/calendar?start={start}&end={end}").json()["events"]
        if item["kind"] == "event"
    ]
    assert len(again) == 7
    # All day on: the day stays, the end becomes the next day.
    whole = ana.patch(f"/api/desk/events/{event_id}", json={"all_day": True}).json()
    assert (whole["start"], whole["all_day"]) == (first, True)
    # Each person's own: another person neither sees nor changes it.
    bob = _person(signed, "bob")
    assert bob.patch(f"/api/desk/events/{event_id}", json={"title": "Mine"}).status_code == 404
    assert not [
        item
        for item in bob.get(f"/api/desk/calendar?start={start}&end={end}").json()["events"]
        if item["kind"] == "event"
    ]
    assert ana.delete(f"/api/desk/events/{event_id}").status_code == 200
    assert ana.get(f"/api/desk/events/{event_id}").status_code == 404


def test_scheduled_runs_in_the_same_hour_come_together():
    from plantcraft.api.routers.desk import scheduled_runs

    runs = scheduled_runs(
        [
            {"app": "link", "id": "a", "name": "Loops", "next_run": "2026-10-24T10:05:00.000Z"},
            {"app": "link", "id": "b", "name": "Valves", "next_run": "2026-10-24T10:20:00.000Z"},
            {"app": "models", "id": "c", "name": "", "next_run": "2026-10-24T11:00:00.000Z"},
        ]
    )
    assert [item["title"] for item in runs] == ["2 scheduled runs", "c"]
    assert [item["title"] for item in runs[0]["runs"]] == ["Loops", "Valves"]


def test_old_checklists_and_routines_become_todos(tmp_path):
    from plantcraft.db import Database
    from plantcraft.desk import DeskStore

    db = Database(tmp_path / "desk.db")
    DeskStore(db)
    today = date.fromisoformat(plant_today())
    past = (today - timedelta(days=1)).isoformat()
    now = "2026-10-20T08:00:00.000Z"
    with db.write() as connection:
        connection.execute(
            "INSERT INTO desk_routines (title, items_json, cadence, days_json, owner, created_by, created_at, updated_at) "
            "VALUES ('Morning', '[\"Read the alarms\", \"Check the handover\"]', 'weekly', '[0, 3]', 'ana', 'ana', ?, ?)",
            (now, now),
        )
        connection.execute(
            "INSERT INTO desk_routines (title, items_json, cadence, group_id, created_by, created_at, updated_at) "
            "VALUES ('Shift', '[\"Read the logbook\"]', 'weekdays', 'utilities', 'boss', ?, ?)",
            (now, now),
        )
        rows = [
            ("ana", past, "Call the supplier", 0, None),
            ("ana", past, "Read the alarms", 1, 1),
            ("ana", past, "Check the handover", 0, 1),
        ]
        for username, day, title, done, routine in rows:
            connection.execute(
                "INSERT INTO desk_checklist (username, day, title, done, done_at, routine_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (username, day, title, done, now if done else None, routine, now),
            )
    store = DeskStore(db)
    lists = store.todo_lists("ana", ["utilities"])
    assert [(item["name"], item["owner"], item["group_id"]) for item in lists] == [
        ("Morning", "ana", None),
        ("Shift", None, "utilities"),
    ]
    open_ = store.todos("ana", ["utilities"], done=False)
    assert sorted((item["title"], item["repeat"], tuple(item["days"])) for item in open_) == [
        ("Call the supplier", "", ()),
        ("Check the handover", "days", (0, 3)),
        ("Read the alarms", "days", (0, 3)),
        ("Read the logbook", "weekdays", ()),
    ]
    # What was done stays done; the routine's past item left undone goes.
    assert [item["title"] for item in store.todos("ana", [], done=True)] == ["Read the alarms"]
    # Once only.
    assert store.migrate_routines() == 0


def test_notes_are_private_until_shared(signed):
    ana = _person(signed, "ana", level="viewer")
    bob = _person(signed, "bob")
    carla = _person(signed, "carla")
    body = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Valve FV-12 sticks"}]}
        ],
    }
    made = ana.post(
        "/api/desk/notes",
        json={
            "title": "Shift meeting",
            "body": body,
            "text": "Valve FV-12 sticks",
            "event_ref": "event:7",
        },
    )
    assert made.status_code == 201, made.text
    note_id = made.json()["note_id"]
    assert made.json()["mine"] is True and made.json()["shared"] == []
    assert bob.get(f"/api/desk/notes/{note_id}").status_code == 404
    assert [item["title"] for item in ana.get("/api/desk/notes?q=FV-12").json()["items"]] == [
        "Shift meeting"
    ]
    assert ana.get("/api/desk/notes?event=event:7").json()["items"][0]["note_id"] == note_id
    assert "body" not in ana.get("/api/desk/notes").json()["items"][0]
    assert (
        ana.patch(f"/api/desk/notes/{note_id}", json={"shared": ["user:nobody"]}).status_code == 422
    )
    shared = ana.patch(f"/api/desk/notes/{note_id}", json={"shared": ["user:bob"], "pinned": True})
    assert shared.json()["shared"][0]["ref"] == "user:bob" and shared.json()["pinned"] is True
    # Bob reads and writes in it; only Ana shares or deletes it.
    seen = bob.get(f"/api/desk/notes/{note_id}").json()
    assert seen["mine"] is False and seen["body"] == body
    assert (
        bob.patch(f"/api/desk/notes/{note_id}", json={"title": "Shift meeting, notes"}).status_code
        == 200
    )
    assert (
        bob.patch(f"/api/desk/notes/{note_id}", json={"shared": ["user:carla"]}).status_code == 403
    )
    assert bob.delete(f"/api/desk/notes/{note_id}").status_code == 403
    group = signed.post(
        "/api/groups",
        json={"name": "Operations", "kind": "area", "members": ["carla"], "coordinator": "carla"},
    ).json()["group_id"]
    ana.patch(f"/api/desk/notes/{note_id}", json={"shared": [f"group:{group}"]})
    assert carla.get(f"/api/desk/notes/{note_id}").status_code == 200
    assert bob.get(f"/api/desk/notes/{note_id}").status_code == 404
    assert ana.delete(f"/api/desk/notes/{note_id}").status_code == 200


def test_a_notes_mentions_come_back_resolved(signed):
    asset = _asset_id(signed)
    mention = {"type": "mention", "attrs": {"id": f"asset:{asset}", "label": asset}}
    body = {
        "type": "doc",
        "content": [
            {
                "type": "taskList",
                "content": [
                    {
                        "type": "taskItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "Check "}, mention],
                            }
                        ],
                    }
                ],
            },
            {
                "type": "paragraph",
                "content": [mention, {"type": "mention", "attrs": {"id": "action:999999"}}],
            },
        ],
    }
    assert note_mentions(body) == [f"asset:{asset}", "action:999999"]
    made = signed.post("/api/desk/notes", json={"title": "Round", "body": body, "text": "Check"})
    refs = made.json()["refs"]
    assert [item["ref"] for item in refs] == [f"asset:{asset}", "action:999999"]
    assert refs[0]["exists"] is True and refs[0]["href"]
    assert refs[1]["exists"] is False
    assert signed.get(f"/api/desk/notes/{made.json()['note_id']}").json()["refs"] == refs


def test_boards_keep_their_places(signed):
    board = [
        {
            "i": "desk:calendar",
            "widget": "desk:calendar",
            "x": 0,
            "y": 0,
            "w": 12,
            "h": 4,
            "config": {"days": 7},
        },
        {
            "i": "desk:actions~2",
            "widget": "desk:actions",
            "x": 0,
            "y": 4,
            "w": 6,
            "h": 3,
            "title": "My group",
        },
        "linkcraft:worst",
    ]
    saved = signed.put("/api/home/layout?page=desk", json={"widgets": board})
    assert saved.status_code == 200, saved.text
    assert signed.get("/api/home/layout?page=desk").json()["widgets"] == board
    bad = [{"i": "a", "widget": "Bad Id", "x": 0, "y": 0, "w": 1, "h": 1}]
    assert signed.put("/api/home/layout?page=desk", json={"widgets": bad}).status_code == 422
    assert (
        signed.put(
            "/api/home/layout?page=desk",
            json={"widgets": [{"i": "a", "widget": "a", "x": 13, "y": 0, "w": 1, "h": 1}]},
        ).status_code
        == 422
    )


def test_notes_and_todos_are_mentioned_without_showing_what_they_are(signed):
    ana = _person(signed, "ana")
    bob = _person(signed, "bob")
    note = ana.post("/api/desk/notes", json={"title": "Pump P-3 seal plan"}).json()
    todo = ana.post("/api/desk/todos", json={"title": "Order the P-3 seal"}).json()
    picked = {item["ref"]: item for item in ana.get("/api/messages/references?q=P-3").json()}
    assert picked[f"note:{note['note_id']}"]["title"] == "Pump P-3 seal plan"
    assert picked[f"todo:{todo['todo_id']}"]["title"] == "Order the P-3 seal"
    others = [item["ref"] for item in bob.get("/api/messages/references?q=P-3").json()]
    assert f"note:{note['note_id']}" not in others and f"todo:{todo['todo_id']}" not in others
    rt = signed.app.state.runtime
    seen = rt.platform.refs.resolve(f"note:{note['note_id']}")
    assert seen["exists"] is True and "Pump" not in seen["title"]
    assert seen["href"] == f"/notes?note={note['note_id']}"
    assert rt.platform.refs.resolve("todo:999999")["exists"] is False
    assert rt.platform.refs.resolve(f"todo:{todo['todo_id']}")["kind_label"] == "To-do"


def test_the_demo_seed_fills_desk_once(signed):
    from plantcraft import demo_seed

    def client(test_client):
        class Client(demo_seed.Http):
            def call(self, method, path, body=None, *, ok=(), raw=None, content_type=""):
                response = test_client.request(method, path, json=body)
                if response.status_code >= 400 and response.status_code not in ok:
                    raise demo_seed.SeedError(f"{method} {path}: {response.text}")
                return response.status_code, response.json() if response.content else None

        return Client("http://test")

    ana = _person(signed, "seed.ana")
    marina = _person(signed, "seed.marina")
    visitor = _person(signed, "visit", level="viewer")
    signed.post(
        "/api/groups",
        json={
            "group_id": "u-100-operations",
            "name": "U-100 operations",
            "kind": "area",
            "members": ["seed.ana", "seed.marina", "visit"],
            "coordinator": "seed.marina",
        },
    )
    for _ in range(2):
        demo_seed.desk_day(client(ana), client(marina), client(visitor))
    team = visitor.get("/api/desk/team").json()["group"]
    assert team["handover"] is not None and team["lists"][0]["name"] == demo_seed.SHIFT_LIST
    assert team["lists"][0]["open"] == 3
    # One to-do every weekday, the others once a week (owner, 2026-10-28).
    shift = [i for i in visitor.get("/api/desk/todos?view=all").json()["items"] if i["list_id"]]
    assert sorted((item["repeat"], tuple(item["days"])) for item in shift) == [
        ("days", (1,)),
        ("days", (3,)),
        ("weekdays", ()),
    ]
    notes = [item["title"] for item in visitor.get("/api/desk/notes").json()["items"]]
    assert notes.count(demo_seed.VALVE_NOTE) == 1 and len(notes) == 2
    mine = visitor.get("/api/desk/todos?view=today").json()["items"]
    assert sorted(item["title"] for item in mine if item["list_id"] is None) == [
        "Open the FIC-1003 valve report",
        "Read today's handover",
    ]


def test_the_demo_seed_writes_the_visitors_desk_into_the_store(signed):
    # A public demo refuses the visitor's own writes: beside the database the seed writes them
    # straight into Desk's store, once.
    from datetime import datetime, timedelta

    from plantcraft import demo_seed

    class Refused(demo_seed.Http):
        def call(self, method, path, body=None, *, ok=(), raw=None, content_type=""):
            raise demo_seed.SeedError(
                f"{method} {path}: This is a public demo: you can try everything, but nothing is saved."
            )

    store = signed.app.state.runtime.desk
    for _ in range(2):
        demo_seed.visitor_day(Refused("http://test"), store)
    titles = sorted(item["title"] for item in store.todos(demo_seed.VISITOR, []))
    assert titles == sorted(title for title, _ in demo_seed.VISITOR_TODOS)
    today = datetime.now().astimezone().date()
    events = [item["title"] for item in store.events(demo_seed.VISITOR, today, today)]
    assert events == ["Shift handover"]
    # Owner, 2026-10-28: a few real items, each repeat once (daily, weekly, monthly, one-off).
    ahead = store.events(demo_seed.VISITOR, today, today + timedelta(days=30))
    assert sorted(item["title"] for item in ahead) == sorted(
        spec[0] for spec in demo_seed.VISITOR_EVENTS
    )
    assert {item["repeat"] for item in ahead} == {"weekdays", "weekly", "monthly", ""}


def test_the_team_page_is_hidden_until_an_administrator_shows_it(signed):
    """Owner, 2026-10-25: Desk lists Team only after Setup › Desk turns it on."""

    ana = _person(signed, "ana")
    assert ana.get("/api/desk/team-page").json() == {"enabled": False}
    assert ana.put("/api/desk/team-page", json={"enabled": True}).status_code == 403
    assert signed.put("/api/desk/team-page", json={"enabled": True}).json() == {"enabled": True}
    assert ana.get("/api/desk/team-page").json() == {"enabled": True}
    actions = [item["action"] for item in signed.get("/api/audit?limit=20").json()["rows"]]
    assert "desk.team_page" in actions


def test_the_demo_gives_the_visitor_actions_of_their_own():
    """Owner, 2026-10-27: whoever enters the demo sees actions in Desk's "My actions"; one in
    each column of the board, each following an action of the team seeded before it."""

    from plantcraft import demo_seed

    titles = [spec["title"] for spec in demo_seed.OPEN_ACTIONS]
    mine = [spec for spec in demo_seed.OPEN_ACTIONS if spec["owner"] == demo_seed.VISITOR]
    assert sorted(spec["status"] for spec in mine) == ["blocked", "in_progress", "open"]
    for spec in mine:
        earlier = titles[: titles.index(spec["title"])]
        assert any(name in earlier for name in spec["links"]), spec["title"]
        assert spec["group_id"] == "u-100-operations"
        # A comment is posted as its author, who must see the action (404 otherwise).
        group = next(item for item in demo_seed.GROUPS if item["group_id"] == spec["group_id"])
        for author, _ in spec["comments"]:
            assert author in group["members"], (spec["title"], author)
