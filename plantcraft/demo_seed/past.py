"""PlantCraft's past: three weeks of finished and open actions and past conversations, and what
reaches the visitor (unread messages, the apps' notifications)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .base import SURGE_LEVELS, VISITOR
from .links import Links, _named

# PlantCraft's past --------------------------------------------------------------------------

# Weeks of the team's work before today, written straight into PlantCraft's database with the
# moment each step happened (``recorded_at``): actions finished, cancelled and under way, and the
# conversations around them. Times are days and hours before now, so a seed run next month tells
# the same story. Steps: (days ago, hour, who, what) per action; what is "create", "comment:<text>"
# or a status (in_progress, blocked, done, cancelled).
PAST_ACTIONS: list[dict[str, Any]] = [
    {
        # Open and late, but opened nine days ago: an action seeded today and already overdue
        # read "Open for 20 min" next to its late due date (owner, 2026-11-06).
        "title": "Renew the historian server certificate",
        "description": (
            "The historian's TLS certificate expires at the end of the month; renew it and "
            "restart the OPC UA gateway in the Sunday window."
        ),
        "priority": "high",
        "owner": "tiago.ramos",
        "group_id": "it-automation",
        "refs": [],
        "steps": [(9, 10, "camila.duarte", "create")],
    },
    {
        "title": "Give the averaging levels the surge-level protocol",
        "description": (
            "Six drum levels only have to stay in their band and dampen the feed; Analytics judged "
            "them with the level protocol, which asks for a tight setpoint, and called them "
            "critical."
        ),
        "priority": "medium",
        "owner": "ana.lima",
        "refs": [f"asset:{loop}" for loop in SURGE_LEVELS],
        "links": ["DOC-CN-001"],
        "steps": [
            (21, 10, "ana.lima", "create"),
            (
                21,
                15,
                "ana.lima",
                "comment:Done in Analytics: surge-level protocol on the six levels.",
            ),
            (21, 15, "ana.lima", "done"),
        ],
    },
    {
        "title": "Replace the FIC-1102 valve positioner",
        "description": (
            "Analytics' stiction screening flagged FIC-1102 for a week; the positioner's feedback "
            "linkage was worn. Replace it and repeat the bump test."
        ),
        "priority": "high",
        "owner": "carlos.menezes",
        "refs": ["asset:FIC-1102"],
        "links": ["PRO-U200-012", "DOC-MH-001"],
        "steps": [
            (19, 9, "ana.lima", "create"),
            (18, 14, "carlos.menezes", "in_progress"),
            (17, 10, "carlos.menezes", "comment:Spare positioner ordered; arrives Thursday."),
            (
                15,
                16,
                "carlos.menezes",
                "comment:Positioner replaced, bump test per {{PRO-U200-012}} shows a clean step. "
                "Logged in {{DOC-MH-001}}.",
            ),
            (15, 16, "carlos.menezes", "done"),
            (14, 9, "ana.lima", "comment:Two days of rounds without stiction. Closing for good."),
        ],
    },
    {
        "title": "Retune LIC-1004 after the level transmitter swap",
        "description": (
            "The new transmitter reads with less noise: the old tuning is too slow now and the "
            "drum level wanders on feed changes."
        ),
        "priority": "medium",
        "owner": "ana.lima",
        "refs": ["asset:LIC-1004"],
        "links": ["Plant overview"],
        "steps": [
            (13, 11, "marina.costa", "create"),
            (12, 15, "ana.lima", "in_progress"),
            (
                11,
                10,
                "ana.lima",
                "comment:Gain up 30 %, integral time halved; watching a shift on the "
                "{{Plant overview}}.",
            ),
            (10, 8, "ana.lima", "done"),
        ],
    },
    {
        "title": "Check the PIC-1103 impulse line for plugging",
        "description": (
            "Analytics sees a slow oscillation on the separator pressure that comes and goes with the "
            "ambient temperature: a partly plugged impulse line is the first suspect."
        ),
        "priority": "medium",
        "owner": "carlos.menezes",
        "refs": ["asset:PIC-1103"],
        "links": ["DOC-TG-001", "INC-2026-007"],
        "steps": [
            (9, 9, "ana.lima", "create"),
            (8, 13, "carlos.menezes", "in_progress"),
            (7, 9, "carlos.menezes", "comment:Line blown down, no plugging found. Tracing is ok."),
            (
                6,
                10,
                "ana.lima",
                "comment:Still oscillating: keep it open, the tuning is next ({{DOC-TG-001}} 3.2).",
            ),
            (6, 10, "ana.lima", "blocked"),
        ],
    },
    {
        "title": "Put FIC-1214 back in automatic",
        "description": "Operations ran the loop in manual during the exchanger cleaning.",
        "priority": "low",
        "owner": "marina.costa",
        "refs": ["asset:FIC-1214"],
        "steps": [
            (8, 7, "marina.costa", "create"),
            (
                5,
                18,
                "marina.costa",
                "comment:Kept in manual on purpose until the stiction check; see the valve action.",
            ),
            (5, 18, "marina.costa", "cancelled"),
        ],
    },
    {
        "title": "Bump test FIC-1206 after the packing adjustment",
        "description": (
            "The packing was tightened on the last shutdown. Check whether the valve now sticks, "
            "with a few small steps in manual."
        ),
        "priority": "medium",
        "owner": "carlos.menezes",
        "refs": ["asset:FIC-1206"],
        "links": ["PRO-U200-012"],
        "steps": [
            (4, 10, "ana.lima", "create"),
            (2, 9, "carlos.menezes", "in_progress"),
            (1, 15, "carlos.menezes", "comment:Steps of 1 % move nothing until 3 %: it sticks."),
        ],
    },
    {
        "title": "Review the TIC-1104 feed-forward from the furnace draft",
        "description": (
            "The twin of the furnaces shows a cyclic disturbance on TIC-1104 that the feedback "
            "loop only follows. A feed-forward from the draft may remove most of it."
        ),
        "priority": "medium",
        "owner": "ana.lima",
        "refs": ["asset:TIC-1104"],
        "links": ["DOC-CN-001", "Control room"],
        "steps": [(3, 14, "marina.costa", "create")],
    },
]
# (days ago, hour, minute, author, text) per message; the title names the conversation.
PAST_CONVERSATIONS: list[dict[str, Any]] = [
    {
        "title": "Turnaround follow-up: valves to check",
        "members": ["marina.costa", "ana.lima", "carlos.menezes"],
        "messages": [
            (
                20,
                8,
                40,
                "marina.costa",
                "Unit back from the turnaround. Which valves should instrumentation look at first?",
            ),
            (
                20,
                10,
                5,
                "ana.lima",
                "Analytics' first week of rounds points at #asset:FIC-1102 and #asset:FIC-1206 "
                "(stiction) and #asset:PIC-1103 (oscillation). I'll open the actions.",
            ),
            (
                20,
                11,
                30,
                "carlos.menezes",
                "FIC-1102 first, then: its positioner was already on my list.",
            ),
            (
                19,
                9,
                10,
                "ana.lima",
                "Opened {{Replace the FIC-1102 valve positioner|the FIC-1102 action}}; the online "
                "valve test is {{PRO-U200-012}}.",
            ),
            (15, 17, 10, "carlos.menezes", "FIC-1102 done, positioner replaced."),
            (14, 9, 20, "ana.lima", "Confirmed by two days of rounds: FIC-1102 is healthy again."),
        ],
    },
    {
        "title": "LIC-1004 after the transmitter swap",
        "members": ["ana.lima", "marina.costa"],
        "messages": [
            (
                13,
                10,
                50,
                "marina.costa",
                "Operators say the drum level #asset:LIC-1004 is lazy since the new transmitter.",
            ),
            (
                13,
                11,
                15,
                "ana.lima",
                "The old tuning compensated the noisy transmitter. I'll retune it this week.",
            ),
            (
                10,
                8,
                30,
                "ana.lima",
                "Retuned ({{Retune LIC-1004 after the level transmitter swap|action}}). The trend "
                "on the {{Plant overview}} dashboard shows it.",
            ),
            (10, 9, 0, "marina.costa", "Shift confirms it holds on feed changes. Thanks!"),
        ],
    },
    {
        "title": "Weekly loop review",
        "members": ["ana.lima", "marina.costa", "carlos.menezes"],
        "messages": [
            (
                7,
                9,
                0,
                "ana.lima",
                "Review of the week: one valve fixed (FIC-1102), LIC-1004 retuned, PIC-1103 still "
                "oscillates ({{Check the PIC-1103 impulse line for plugging|its action}}). The Daily "
                "review monitor in Analytics covers the critical loops from now on, and the "
                "{{Control loops weekly performance}} report comes every Monday.",
            ),
            (
                7,
                9,
                40,
                "marina.costa",
                "Good. Can we keep FIC-1214 in manual until its valve is checked?",
            ),
            (7, 10, 5, "carlos.menezes", "Yes, it sticks too. I'll fit it with FIC-1206."),
            (
                7,
                10,
                20,
                VISITOR,
                "I'll put FIC-1214 on next week's review, then. Ana, can the assistant draft the "
                "summary from the report?",
            ),
            (7, 10, 45, "ana.lima", "Yes, it reads the report and lists the loops; I'll check it."),
        ],
    },
    # More of the team's talk (about fifteen conversations, the visitor in them).
    {
        "title": "Night shift handover: U-200",
        "members": ["marina.costa", "juliana.rocha"],
        "messages": [
            (
                6,
                6,
                50,
                "juliana.rocha",
                "Quiet night on U-200 except #asset:PIC-1202: its alarm rang four times between 01:00 and 04:00.",
            ),
            (
                6,
                7,
                5,
                "marina.costa",
                "Same cycle as last week. Did anyone change its output by hand?",
            ),
            (
                6,
                7,
                12,
                "juliana.rocha",
                "No, it stayed in automatic. I asked the assistant and it showed the 12-minute period again.",
            ),
            (
                6,
                7,
                30,
                VISITOR,
                "Thanks, Juliana. I'll bring it to the weekly review so it gets a retune, not a shelve.",
            ),
        ],
    },
    {
        "title": "Calibration plan for October",
        "members": ["lucas.ferreira", "carlos.menezes"],
        "messages": [
            (
                5,
                10,
                0,
                "lucas.ferreira",
                "October calibrations: TT-1209, FT-1001 and the two U-100 level transmitters. The datasheets say TT-1209 is overdue.",
            ),
            (
                5,
                10,
                20,
                "carlos.menezes",
                "TT-1209 first, then: Analytics already sees it drifting against the Furnaces model.",
            ),
            (
                5,
                10,
                45,
                VISITOR,
                "Can you put the dates in the calendar? The control room wants to know which loops go to manual.",
            ),
            (
                5,
                11,
                2,
                "lucas.ferreira",
                "Done: one action per transmitter, with its day. They show in Desk's calendar.",
            ),
        ],
    },
    {
        "title": "Assistant answers in Portuguese?",
        "members": ["ana.lima"],
        "messages": [
            (
                4,
                15,
                10,
                VISITOR,
                "Ana, does the assistant answer in Portuguese? Some operators would rather ask that way.",
            ),
            (
                4,
                15,
                25,
                "ana.lima",
                "Yes: it answers in the language of the question, and the documents search reads both. PRO-U200-012 is in Portuguese and it cites it fine.",
            ),
            (4, 15, 31, VISITOR, "Great, I'll tell the shift."),
        ],
    },
    {
        "title": "FIC-1214 in manual",
        "members": ["marina.costa", "carlos.menezes", "rafael.souza"],
        "messages": [
            (
                3,
                8,
                15,
                "rafael.souza",
                "#asset:FIC-1214 is in manual since yesterday, as agreed. Output fixed at 42 %.",
            ),
            (
                3,
                8,
                40,
                "carlos.menezes",
                "Thanks. The positioner arrives next week; I'll fit it together with FV-1206.",
            ),
            (
                3,
                9,
                0,
                VISITOR,
                "Please keep an eye on the downstream level while it is in manual. Analytics flags it if it drifts.",
            ),
            (3, 9, 5, "marina.costa", "Noted in the handover. The level alarm stays on."),
        ],
    },
    {
        "title": "Dashboard for the control room",
        "members": ["ana.lima", "rafael.souza"],
        "messages": [
            (
                2,
                13,
                0,
                "rafael.souza",
                "Can the control room have one screen with the critical loops and their alarms?",
            ),
            (
                2,
                13,
                30,
                "ana.lima",
                "The {{Control room}} dashboard in View does that: the critical loops, live, and the open alarms. It has a public link for the wall screen.",
            ),
            (
                2,
                13,
                42,
                VISITOR,
                "I opened it: very clear. Could it also show TIC-1104's afternoon swings?",
            ),
            (
                2,
                14,
                5,
                "ana.lima",
                "Added a trend panel with TIC-1104 against its setpoint, last 12 hours.",
            ),
            (2, 14, 10, "rafael.souza", "Perfect, it is on the wall now."),
        ],
    },
]


def _past(days: int, hour: int, minute: int = 0, *, now: Any = None) -> Any:
    from datetime import datetime, timedelta

    from plantcraft.config import plant_timezone

    now = now or datetime.now(plant_timezone())
    moment = (now - timedelta(days=days)).replace(hour=hour, minute=minute, second=0)
    return min(moment, now - timedelta(minutes=5))


def _workspace() -> Any:
    """PlantCraft's own stores, when the seed runs where PlantCraft keeps its database."""

    from plantcraft.api.runtime import DEFAULT_SCENARIO, PROJECT_ROOT
    from plantcraft.config import load_scenario
    from plantcraft.platform.workspace import Workspace

    path = Path(os.environ.get("PLANTCRAFT_SCENARIO") or DEFAULT_SCENARIO)
    if not path.is_file():
        return None
    database = Path(load_scenario(path.resolve(), project_root=PROJECT_ROOT).storage.sqlite_path)
    return Workspace(database) if database.is_file() else None


def past(
    workspace: Any, admin: str, *, now: Any = None, links: Links | None = None
) -> dict[str, int]:
    """The weeks before today: finished and open actions, past conversations (idempotent). Each
    names what ``links`` holds of what it follows; then ``links`` holds them too."""

    from plantcraft.db import recorded_at

    links = links or Links()
    store, messages = workspace.actions, workspace.messages
    have = {item["title"]: item for item in store.list(limit=1000)}
    written = {"actions": 0, "conversations": 0}
    for action in PAST_ACTIONS:
        if action["title"] in have:
            _relink(store, have[action["title"]], links.of(*action.get("links", ())))
            continue
        current: dict[str, Any] = {}
        for days, hour, actor, step in action["steps"]:
            with recorded_at(_past(days, hour, now=now)):
                if step == "create":
                    current = store.create(
                        title=action["title"],
                        actor=actor,
                        description=action["description"],
                        priority=action["priority"],
                        owner=action["owner"],
                        group_id=action.get("group_id"),
                        due_at=_past(days - 7, 12, now=now).date().isoformat(),
                        refs=[*action["refs"], *links.of(*action.get("links", ()))],
                    )
                elif step.startswith("comment:"):
                    text = links.fill(step.removeprefix("comment:"))
                    store.comment(current["action_id"], actor, text)
                else:
                    fields = ("title", "description", "priority", "owner", "due_at", "refs")
                    current, _ = store.update(
                        current["action_id"],
                        actor=actor,
                        status=step,
                        **{key: current[key] for key in fields},
                    )
        written["actions"] += 1
    _named(links, store, messages, admin)
    known = {item.get("title") for item in messages.list_for(admin, limit=1000)}
    for conversation in PAST_CONVERSATIONS:
        if conversation["title"] in known:
            continue
        members = [*conversation["members"], admin, VISITOR]
        first = conversation["messages"][0]
        with recorded_at(_past(first[0], first[1], first[2], now=now)):
            started = messages.start(first[3], members, title=conversation["title"])
        ident = started["conversation_id"]
        for days, hour, minute, author, text in conversation["messages"]:
            with recorded_at(_past(days, hour, minute, now=now)):
                messages.post(ident, author, links.fill(text))
        for member in members:
            messages.mark_read(ident, member)
        links.add(conversation["title"], f"conversation:{ident}")
        written["conversations"] += 1
    return written


# How many chat messages wait for a visitor: a few, the rest read.
VISITOR_UNREAD = 4


def visitor_unread(workspace: Any) -> int:
    """The visitor's conversations with people read, but for the newest message of the latest
    ``VISITOR_UNREAD``: a person back from a morning in the field. Apps' notices and assistant
    chats are left as they are (Notifications counts the former apart). Each visit reads on top
    of this (``visit_reads``), so every visitor finds the same."""

    messages = workspace.messages
    chats = [
        item
        for item in messages.list_for(VISITOR, limit=1000)
        if item.get("last_message")
        and all(member["kind"] == "person" for member in item["members"])
    ]
    for item in chats:
        messages.mark_read(item["conversation_id"], VISITOR)
    waiting = [item for item in chats if item["last_message"]["author"] != VISITOR]
    for item in waiting[:VISITOR_UNREAD]:
        messages.set_read(item["conversation_id"], VISITOR, item["last_message"]["message_id"] - 1)
    return min(len(waiting), VISITOR_UNREAD)


# What Alarms sent the visitor over the last days (the demo's notifications
# should be mostly alarms, then the other apps, not action changes): (days ago, hour, minute, priority, key, title,
# what happened, rule). Written as Alarms writes them; the live rules add more as the plant runs.
VISITOR_ALARMS = (
    (
        0,
        7,
        52,
        "high",
        "demo-alarm:pic-1202:1",
        "PIC-1202 pressure high: raised",
        "PIC-1202 pressure high: raised, PV 13.6 bar over the 13.2 bar limit",
        "PIC-1202 pressure high",
    ),
    (
        0,
        6,
        15,
        "medium",
        "demo-alarm:fic-1003:1",
        "FIC-1003 valve saturated, loop off setpoint: still active",
        "Valve saturated, loop off setpoint: still active, OP at 98% for 20 min",
        "Valve saturated, loop off setpoint",
    ),
    (
        1,
        22,
        40,
        "high",
        "demo-alarm:pic-1202:0",
        "PIC-1202 pressure high: not acknowledged, escalated",
        "PIC-1202 pressure high: not acknowledged, escalated to the shift coordinator",
        "PIC-1202 pressure high",
    ),
    (
        1,
        14,
        5,
        "low",
        "demo-alarm:ti-1105:0",
        "TI-1105 measurement frozen: cleared",
        "U-100 measurement frozen: cleared, the value moves again after 35 min",
        "U-100 measurement frozen",
    ),
    (
        2,
        9,
        30,
        "medium",
        "demo-alarm:fic-1206:0",
        "FIC-1206 critical for over 1 h: raised",
        "Loop critical for over 1 h: raised, Analytics rates the loop critical since 08:20",
        "Loop critical for over 1 h",
    ),
    (
        3,
        3,
        10,
        "medium",
        "demo-alarm:u-100-data:0",
        "No data from the plant: cleared",
        "No data from the plant: cleared, the collector is back after 12 min",
        "No data from the plant",
    ),
)


# What the other apps sent the visitor: (days ago, hour, minute, app, app's name, category,
# priority, key, title, text, page).
VISITOR_APP_NOTICES = (
    (
        0,
        6,
        0,
        "linkcraft",
        "Analytics",
        "run",
        "medium",
        "demo-run:daily-review:0",
        "Daily review: 2 loops critical",
        "FIC-1003 (stiction) and PIC-1202 (oscillation) are critical in this morning's round.",
        "/link/executions",
    ),
    (
        1,
        7,
        0,
        "dashcraft",
        "View",
        "info",
        "low",
        "demo-report:weekly:0",
        "Report sent: Control loops weekly performance",
        "The PDF of last week is in View, under Reports.",
        "/dash/reports",
    ),
    (
        2,
        16,
        40,
        "modelcraft",
        "Models",
        "run",
        "low",
        "demo-study:pic-1202:0",
        "Study finished: PIC-1202 tuning",
        "24 simulations ranked by settling time; the best halves the gain.",
        "/model/studies",
    ),
)


def visitor_alarms(workspace: Any, *, now: Any = None) -> int:
    """``VISITOR_ALARMS`` from Alarms and ``VISITOR_APP_NOTICES`` from the other apps in the
    visitor's Notifications, each in the conversation that app's own notifications use
    (idempotent by key)."""

    from plantcraft.db import recorded_at
    from plantcraft.notify import NotificationStore

    messages = workspace.messages
    threads = NotificationStore(workspace.db)
    sent = {
        (item.get("meta") or {}).get("key")
        for item in messages.notices_for(VISITOR, since="2000-01-01T00:00:00Z")
    }
    written = 0

    def deliver(robot: str, name: str, when: Any, body: str, meta: dict[str, Any]) -> None:
        nonlocal written
        found = workspace.users.get_user(robot)
        if found is None:
            workspace.users.upsert_user(robot, name, "App notifications", kind="system")
        elif found.get("kind") == "person":
            return
        with recorded_at(when):
            thread = threads.thread(robot, VISITOR)
            if thread is None or not messages.is_member(thread, VISITOR):
                thread = messages.start(robot, [VISITOR], title=name)["conversation_id"]
                threads.set_thread(robot, VISITOR, int(thread))
            messages.post(
                int(thread), robot, body, meta={"kind": "notification", "app": robot, **meta}
            )
        written += 1

    notices = [
        (
            _past(days, hour, minute, now=now),
            "alarmcraft",
            "Alarms",
            f"**{title}**\n\n- [{priority.capitalize()}] {line}\n\n"
            f"Rule: {rule}. Acknowledge in Alarms to stop the reminders.",
            {"priority": priority, "url": "/alarm/alarms", "key": key, "category": "alarm"},
        )
        for days, hour, minute, priority, key, title, line, rule in VISITOR_ALARMS
    ] + [
        (
            _past(days, hour, minute, now=now),
            app,
            name,
            f"**{title}**\n\n{text}",
            {"priority": priority, "url": url, "key": key, "category": category},
        )
        for days, hour, minute, app, name, category, priority, key, title, text, url in (
            VISITOR_APP_NOTICES
        )
    ]
    for when, robot, name, body, meta in sorted(notices, key=lambda item: item[0]):
        if meta["key"] not in sent:
            deliver(robot, name, when, body, {**meta, "actions": []})
    return written


def _relink(store: Any, action: dict[str, Any], refs: list[str]) -> None:
    """An action seeded before the links gets them, as of when it was written."""

    from datetime import datetime

    from plantcraft.db import recorded_at

    if not set(refs) - set(action["refs"]):
        return
    keys = ("title", "description", "priority", "owner", "group_id", "due_at", "status")
    with recorded_at(datetime.fromisoformat(action["created_at"])):
        store.update(
            action["action_id"],
            actor=action["created_by"],
            refs=list(dict.fromkeys([*action["refs"], *refs])),
            **{key: action[key] for key in keys},
        )
