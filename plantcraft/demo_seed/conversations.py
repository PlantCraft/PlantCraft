"""The team's conversations in Messages, and the follow-ups that link them to what they opened."""

from __future__ import annotations

from typing import Any

from .base import VISITOR, Http, SeedError, Suite, _ident, _items, log
from .links import Links

# Today's conversations: (title, who starts it, members besides the admin and the visitor, the
# first message, the replies before the action exists, the replies that link it once it does).
CONVERSATIONS: list[dict[str, Any]] = [
    {
        "title": "FIC-1003 recycle valve",
        "by": "ana.lima",
        "members": ["carlos.menezes", "marina.costa"],
        "text": (
            "Analytics flags stiction on the recycle flow loop #asset:FIC-1003: the valve moves "
            "in jumps and the flow cycles about every four minutes. I asked the assistant to line "
            "up a week of rounds: the stiction index climbs since Monday."
        ),
        "replies": [
            (
                "carlos.menezes",
                "I can check the positioner and the packing at the next window. Put it in the "
                "actions, please. {{PRO-U200-012}} lets us test it without stopping the unit.",
            ),
            (
                VISITOR,
                "Same valve model as FIC-1102 after the turnaround? If so, the positioner is the "
                "first suspect.",
            ),
            (
                "ana.lima",
                "Same model, yes. The assistant found that case too and quoted the FIC-1102 "
                "action, so we start with the positioner.",
            ),
        ],
        "after": [
            (
                "ana.lima",
                "Opened {{Inspect the FIC-1003 recycle valve for stiction|the action}} for you, "
                "with the checklist from {{PRO-U200-012}}. The {{Control room}} dashboard shows the "
                "valve live, and my {{Why does FIC-1003 cycle?|assistant chat}} sums up the evidence.",
            ),
            ("carlos.menezes", "Got it. First two items ticked; valve test tomorrow morning."),
            (
                "marina.costa",
                "The shift keeps the loop in auto until the test. I'll tell the operators at the "
                "handover.",
            ),
            (VISITOR, "Thanks, all. I'm following the action from Desk."),
        ],
    },
    {
        "title": "Furnace outlet temperature drift",
        "by": "marina.costa",
        "members": ["ana.lima", "carlos.menezes"],
        "text": (
            "The furnaces model in Analytics says #asset:TIC-1209 reads higher than expected since "
            "yesterday. Operators see nothing on the panel. Sensor or process?"
        ),
        "replies": [
            (
                "ana.lima",
                "Fuel and feed hold still, so most likely the sensor. {{DOC-U100-OM-001}} 7.1 "
                "describes exactly this; the {{Plant overview}} trend shows the gap.",
            ),
        ],
        "after": [
            (
                "ana.lima",
                "{{Calibrate the TIC-1209 thermocouple|Calibration action}} opened for Carlos; "
                "the reasoning is in {{Is TIC-1209 drifting or is the furnace hotter?|this chat}}.",
            ),
        ],
    },
    {
        "title": "PIC-1202 alarm at every peak",
        "by": "marina.costa",
        "members": ["ana.lima", "juliana.rocha"],
        "text": (
            "Night shift acknowledged the #asset:PIC-1202 high-pressure alarm 14 times. Can we "
            "fix the loop instead of shelving the alarm?"
        ),
        "replies": [
            (
                "ana.lima",
                "Yes: it is the tuning, a 12-minute cycle. {{INC-2026-007}} is the same story on "
                "PIC-1002. The {{Alarm summary, weekly}} report will show the count drop.",
            ),
        ],
        "after": [
            (
                "ana.lima",
                "{{Retune PIC-1202: aggressive tuning makes it oscillate|Retune action}} is on my "
                "list for this week.",
            ),
            (
                VISITOR,
                "Let's look at the alarm count in Alarms after the retune; if it drops, we close "
                "the case in the weekly review.",
            ),
        ],
    },
]


def conversations(
    suite: Suite, passwords: dict[str, str], links: Links | None = None, workspace: Any = None
) -> list:
    """Today's conversations; the ones just started, for ``follow_ups`` once the actions exist.
    The visitor's replies go through PlantCraft's store when the seed reaches it: a public demo
    refuses the visitor's writes."""

    links = links or Links()
    ana = suite.session("ana.lima", passwords["ana.lima"])
    listed = _items(ana.get("/api/messages/conversations"), "conversations")
    for item in listed:
        if item.get("title"):
            links.add(item["title"], f"conversation:{_ident(item)}")
    sessions: dict[str, Http] = {}

    def person(username: str) -> Http:
        if username not in sessions:
            secret = suite.visitor_password if username == VISITOR else passwords[username]
            sessions[username] = suite.session(username, secret)
        return sessions[username]

    def say(ident: Any, author: str, text: str) -> None:
        if author == VISITOR and workspace is not None:
            workspace.messages.post(int(ident), VISITOR, text)
            return
        try:
            person(author).post(f"/api/messages/conversations/{ident}/messages", {"text": text})
        except SeedError as error:
            if author != VISITOR:
                raise
            log(f"the visitor's reply skipped ({error}): run the seed inside PlantCraft")

    started = []
    for spec in CONVERSATIONS:
        if spec["title"] in links.refs:
            continue
        answer = person(spec["by"]).post(
            "/api/messages/conversations",
            {
                "title": spec["title"],
                "members": [suite.admin, VISITOR, *spec["members"]],
                "text": links.fill(spec["text"]),
            },
        )
        ident = _ident(answer["conversation"])
        links.add(spec["title"], f"conversation:{ident}")
        for author, text in spec["replies"]:
            say(ident, author, links.fill(text))
        started.append((ident, spec, say))
        log(f"conversation '{spec['title']}'")
    return started


def follow_ups(started: list, links: Links) -> None:
    """The replies that link the actions the conversations asked for."""

    for ident, spec, say in started:
        for author, text in spec["after"]:
            say(ident, author, links.fill(text))
