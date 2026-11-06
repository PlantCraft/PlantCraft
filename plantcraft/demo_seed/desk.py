"""Desk: notes, to-dos, the calendar, the visitor's day, the "Start here" note and the team's
day."""

from __future__ import annotations

import urllib.parse
from typing import Any

from .base import VISITOR, Http, Suite, _day, _items, log
from .links import Links, _checklist, _doc, _mention, _para
from .people import GROUPS

VALVE_NOTE = "FIC-1003 recycle valve: plan"
SHIFT_LIST = "U-100 shift start"


VALVE_PLAN = (
    ("Why", ["Analytics flags stiction on {{asset:FIC-1003}}; {{DOC-MH-001}} explains why."]),
    (
        "Next",
        [
            "Follow {{Inspect the FIC-1003 recycle valve for stiction|the action}} and "
            "{{FIC-1003 recycle valve|the conversation}}.",
        ],
    ),
)
VALVE_STEPS = (
    (True, "Read the stiction finding in Analytics and {{Why does FIC-1003 cycle?|the chat}}"),
    (False, "Valve test with {{PRO-U200-012}} at the next window"),
    (False, "Retune {{asset:FIC-1003}} only after the valve is fixed"),
)


def _heading(text: str) -> dict[str, Any]:
    return {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": text}]}


# The group's shift-start list: one to-do every weekday, the others once a week on their own day
# (the calendar was full of the same three items every day).
SHIFT_TODOS = (
    ("Read the logbook", "weekdays", []),
    ("Walk the furnace area", "days", [1]),
    ("Check the flare drum level", "days", [3]),
)


def shift_list(marina: Http, group: str) -> None:
    """U-100's shift-start list; run again, it sets the repeats of the to-dos already there."""

    listed = marina.get("/api/desk/todos?view=all")
    found = next((item for item in _items(listed, "lists") if item["name"] == SHIFT_LIST), None)
    if found is None:
        found = marina.post(
            "/api/desk/todo-lists", {"name": SHIFT_LIST, "group_id": group, "color": "#00726b"}
        )
    items = {
        item["title"]: item
        for item in _items(listed, "items")
        if item.get("list_id") == found["list_id"]
    }
    for title, repeat, days in SHIFT_TODOS:
        # A weekly one starts on its own next day (Monday is 0), so the first week is right too.
        due = _day(next(n for n in range(7) if not days or _weekday(n) in days))
        wanted = {"repeat": repeat, "days": days}
        item = items.get(title)
        if item is None:
            marina.post(
                "/api/desk/todos",
                {"title": title, "list_id": found["list_id"], "due": due, **wanted},
            )
        elif item.get("repeat") != repeat or list(item.get("days") or []) != days:
            marina.patch(f"/api/desk/todos/{item['todo_id']}", {**wanted, "due": due})


def _weekday(ahead: int) -> int:
    """The weekday (Monday is 0) ``ahead`` days from the plant's today."""

    from datetime import date

    return date.fromisoformat(_day(ahead)).weekday()


def desk_day(
    ana: Http, marina: Http, visitor: Http, store: Any = None, links: Links | None = None
) -> None:
    """Desk's own things (owner, round 7): a note shared with U-100 operations, the group's
    shift-start list and today's handover, and the visitor's own to-dos and a weekly meeting.
    Run again, it adds only what is missing."""

    links = links or Links()
    group = "u-100-operations"
    note = next(
        (i for i in _items(ana.get("/api/desk/notes"), "items") if i["title"] == VALVE_NOTE), None
    )
    blocks, plain = [], []
    for heading, lines in VALVE_PLAN:
        blocks.append(_heading(heading))
        plain.append(heading)
        for line in lines:
            parts, text = links.rich(line)
            blocks.append(_para(*parts))
            plain.append(text)
    steps = []
    for done, line in VALVE_STEPS:
        parts, text = links.rich(line)
        steps.append((done, _para(*parts)))
        plain.append(text)
    written = {"body": _doc(*blocks, _checklist(*steps)), "text": "\n".join(plain)}
    if note is None:
        ana.post("/api/desk/notes", {"title": VALVE_NOTE, **written, "shared": [f"group:{group}"]})
    elif note.get("body_text") != written["text"][:160]:
        ana.patch(f"/api/desk/notes/{note['note_id']}", written)
    shift_list(marina, group)
    handover = marina.post(f"/api/desk/team/{group}/handover")
    if handover and not handover.get("body_text"):
        marina.patch(
            f"/api/desk/notes/{handover['note_id']}",
            {
                "body": _doc(
                    _para("Night shift was quiet. Crude feed steady at the planned rate."),
                    _para("Watch ", _mention("asset:FIC-1003", "FIC-1003"), ": it still cycles."),
                ),
                "text": "Night shift was quiet. Crude feed steady at the planned rate.\nWatch "
                "#FIC-1003: it still cycles.",
            },
        )
    visitor_day(visitor, store)
    log("Desk: a shared note, U-100's shift-start list and handover, the visitor's to-dos")


VISITOR_TODOS = (
    ("Open the FIC-1003 valve report", True),
    ("Read today's handover", True),
    ("Look at the furnace dashboard", False),
)


# The visitor's own calendar (fewer items, real ones, not the same every
# day): one meeting every weekday, one every week, one every month, and a few one-off days.
# (title, days ahead, start, end, repeat); an end of None is an all-day event.
VISITOR_EVENTS = (
    ("Shift handover", 0, "07:00", "07:30", "weekdays"),
    ("U-100 weekly performance review", 3, "14:00", "15:00", "weekly"),
    ("FIC-1003 valve test window", 2, "09:00", "11:00", ""),
    ("Vendor visit: FV-1003 packing", 6, "13:30", "15:00", ""),
    ("Monthly safety meeting", 8, "10:00", "11:00", "monthly"),
    ("Turnaround planning workshop", 12, None, None, ""),
)


def _workday(ahead: int) -> str:
    """The first weekday at least ``ahead`` days from the plant's today."""

    while _weekday(ahead) >= 5:
        ahead += 1
    return _day(ahead)


def _visitor_event(title: str, ahead: int, start: str | None, end: str | None, repeat: str):
    """An event of ``VISITOR_EVENTS`` as Desk takes it."""

    day = _day(ahead) if repeat else _workday(ahead)
    if start is None:
        return {"title": title, "start": day, "all_day": True, "repeat": repeat}
    return {"title": title, "start": f"{day}T{start}", "end": f"{day}T{end}", "repeat": repeat}


def visitor_day(visitor: Http, store: Any = None) -> None:
    """The visitor's own to-dos and calendar. A public demo refuses the visitor's writes, so
    where the seed runs beside PlantCraft's database they go straight into Desk's store
    (``store``); through the API otherwise. Run again, a one-off day already past moves ahead."""

    from datetime import date, timedelta

    today = date.fromisoformat(_day())
    if store is not None:
        mine = {item["title"] for item in store.todos(VISITOR, [])}
        for title, my_day in VISITOR_TODOS:
            if title not in mine:
                store.create_todo(
                    title=title,
                    username=VISITOR,
                    group_id=None,
                    list_id=None,
                    actor=VISITOR,
                    my_day=my_day,
                )
        known = {
            item["title"]: item
            for item in store.events(
                VISITOR, today - timedelta(days=90), today + timedelta(days=90)
            )
        }
        for spec in VISITOR_EVENTS:
            event = _visitor_event(*spec)
            found = known.get(event["title"])
            if found is None:
                store.create_event(VISITOR, **event)
            elif not event["repeat"] and str(found["start"])[:10] < today.isoformat():
                store.update_event(VISITOR, found["event_id"], **event)
        return
    mine = {item["title"] for item in _items(visitor.get("/api/desk/todos?view=all"), "items")}
    for title, my_day in VISITOR_TODOS:
        if title not in mine:
            visitor.post("/api/desk/todos", {"title": title, "my_day": my_day})
    window = {"start": today.isoformat(), "end": (today + timedelta(days=40)).isoformat()}
    events = visitor.get("/api/desk/calendar?" + urllib.parse.urlencode(window))
    titles = {item.get("title") for item in _items(events, "events")}
    for spec in VISITOR_EVENTS:
        if spec[0] not in titles:
            visitor.post("/api/desk/events", _visitor_event(*spec))


def desk(
    suite: Suite, passwords: dict[str, str], workspace: Any = None, links: Links | None = None
) -> None:
    from plantcraft.desk import DeskStore

    store = DeskStore(workspace.db) if workspace is not None else None
    desk_day(
        suite.session("ana.lima", passwords["ana.lima"]),
        suite.session("marina.costa", passwords["marina.costa"]),
        suite.session(VISITOR, suite.visitor_password),
        store,
        links,
    )
    if store is not None:
        start_here(store, suite.admin, links)


# The first thing a visitor reads (Desk › Notes, pinned): where each part of the story is.
START_HERE = "Start here: a week at Riverbend Refinery"
TOUR = (
    (
        "Analytics › Results",
        "four loops in trouble and one healthy: {{asset:FIC-1003}} has a sticky valve, "
        "{{asset:PIC-1202}} oscillates, {{asset:TIC-1209}} drifts, {{asset:FIC-1001}} is fine.",
    ),
    (
        "Follow one problem",
        "{{asset:FIC-1003}} found by Analytics, explained in {{Why does FIC-1003 cycle?|a chat}}, "
        "discussed in {{FIC-1003 recycle valve|a conversation}}, fixed by "
        "{{Inspect the FIC-1003 recycle valve for stiction|an action}} that follows "
        "{{PRO-U200-012}}. Last month's twin, {{Replace the FIC-1102 valve positioner|FIC-1102}}, "
        "is closed.",
    ),
    (
        "View › Dashboards",
        "{{Plant overview}} and {{Control room}} show the same loops; each has its report in "
        "View › Reports, sent on a schedule ({{U-100 daily report}}).",
    ),
    (
        "Alarms › Alarms",
        "the {{asset:PIC-1202}} pressure alarm of the last two days, and "
        "{{Why does the PIC-1202 pressure alarm ring so often?|why it rings}}; Rules has examples "
        "in Simple, Blocks and Python.",
    ),
    (
        "Historian › Sources",
        "the Simulator's OPC UA server and the lab's CSV; Imports holds a pilot test run.",
    ),
    (
        "Models › Studies",
        "a tank sized by a grid study and its level controller tuned by an optimization.",
    ),
    (
        "Documents",
        "the plant's manuals, narratives and maintenance history ({{DOC-TG-001}}); search "
        '"stiction".',
    ),
    ("Desk › Actions", "what the team does about it: open, under way, blocked and done."),
    ("Notebooks › My notebooks", "the sticky valve's signals in Python."),
)


def start_here(store: Any, admin: str, links: Links | None = None) -> None:
    """A note the administrator wrote for everyone who opens Desk, pinned: a tour of the story."""

    links = links or Links()
    groups = [group["group_id"] for group in GROUPS]
    found = next((item for item in store.notes(admin, groups) if item["title"] == START_HERE), None)
    lines, plain = [], []
    for place, text in TOUR:
        parts, flat = links.rich(text)
        bold = {"type": "text", "text": place, "marks": [{"type": "bold"}]}
        lines.append((False, _para(bold, ": ", *parts)))
        plain.append(f"{place}: {flat}")
    body = _doc(
        _para(
            "Riverbend Refinery is simulated: its problems are real enough to find, and nothing "
            "you open here can change it. Tick what you have seen."
        ),
        _checklist(*lines),
    )
    if found is not None:
        # Written again: the tour of the story as it is now, with its links.
        store.update_note(found["note_id"], {"body": body, "text": "\n".join(plain)}, admin)
        return
    made = store.create_note(
        admin,
        title=START_HERE,
        body=body,
        text="\n".join(plain),
        shared=[f"user:{VISITOR}"] + [f"group:{group}" for group in groups],
    )
    store.update_note(made["note_id"], {"pinned": True}, admin)


# Desk's Team on a demo day (round 8): someone away, someone busy, and the IT team's work. Its
# late action (the certificate) is seeded in ``past`` so it is not born overdue (owner, 2026-11-06).
TEAM_DAY = (
    ("camila.duarte", "Vendor training", True),
    ("juliana.rocha", "Day off", True),
    ("tiago.ramos", "Firewall change window", False),
)
IT_ACTIONS = (
    ("Add the U-200 analyzers to the OPC UA gateway", "camila.duarte", 3, "medium"),
    ("Test the nightly backup restore", "tiago.ramos", 5, "medium"),
)


def team_day(suite: Suite, passwords: dict[str, str]) -> None:
    """Today's away and busy people and the IT team's actions; run again, it adds only what is
    missing."""

    today = _day()
    query = urllib.parse.urlencode({"start": today, "end": today})
    for username, title, all_day in TEAM_DAY:
        person = suite.session(username, passwords[username])
        events = _items(person.get(f"/api/desk/calendar?{query}"), "events")
        if any(item.get("title") == title for item in events):
            continue
        person.post(
            "/api/desk/events",
            {"title": title, "start": today, "all_day": True}
            if all_day
            else {"title": title, "start": f"{today}T00:00", "end": f"{today}T23:59"},
        )
    admin = suite.session(suite.admin, suite.password)
    titles = {item.get("title") for item in _items(admin.get("/api/actions"), "actions")}
    for title, owner, days, priority in IT_ACTIONS:
        if title in titles:
            continue
        due = _day(days)
        admin.post(
            "/api/actions",
            {
                "title": title,
                "priority": priority,
                "owner": owner,
                "group_id": "it-automation",
                "due_at": due,
            },
        )
    log("Desk: who is away or busy today, and the IT team's actions")
