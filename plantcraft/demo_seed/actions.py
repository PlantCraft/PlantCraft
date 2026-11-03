"""The open actions the team works on, with their references, checklists and comments."""

from __future__ import annotations

from typing import Any

from .base import VISITOR, Suite, _day, _ident, _items, log
from .links import Links

# The open actions of the week: what each follows (``links``) and its checklist, ticked or not.
OPEN_ACTIONS: list[dict[str, Any]] = [
    {
        "title": "Inspect the FIC-1003 recycle valve for stiction",
        "description": (
            "Analytics' Control loop performance flags stiction and the valve test agrees. Check the "
            "positioner, the packing friction and the air supply; a bump test after."
        ),
        "priority": "high",
        "owner": "carlos.menezes",
        "group_id": "instrumentation",
        "status": "in_progress",
        "links": [
            "asset:FIC-1003",
            "PRO-U200-012",
            "DOC-MH-001",
            "Control room",
            "Why does FIC-1003 cycle?",
            "FIC-1003 recycle valve",
        ],
        "items": [
            ("Read the stiction finding in Analytics' Control loop performance", True),
            ("Open the work order; bypass the valve on the day shift", True),
            ("Valve test in manual, steps of 0.5 % (PRO-U200-012)", False),
            ("Replace the packing with a PTFE V-ring set (see DOC-MH-001)", False),
            ("Bump test, then confirm two rounds clean in Analytics", False),
        ],
        "comments": [
            (
                "carlos.menezes",
                "Work order opened; the valve can be bypassed during the day shift.",
            ),
            (
                "ana.lima",
                "Same signature as {{Replace the FIC-1102 valve positioner|FIC-1102}} last month. "
                "{{DOC-MH-001}} has the packing history and {{PRO-U200-012}} the online test.",
            ),
        ],
    },
    {
        "title": "Retune PIC-1202: aggressive tuning makes it oscillate",
        "description": (
            "Oscillation of about 12 minutes on the hydrotreater pressure. Lower the gain "
            "and check the integral time against the process time constant."
        ),
        "priority": "medium",
        "owner": "ana.lima",
        "group_id": "process-engineering",
        "status": "open",
        "links": [
            "asset:PIC-1202",
            "INC-2026-007",
            "DOC-TG-001",
            "Plant overview",
            "Control loops weekly performance",
            "Why does the PIC-1202 pressure alarm ring so often?",
        ],
        "items": [
            ("Confirm the period and the amplitude on the Plant overview trend", True),
            ("Step test in manual to measure the process gain and time constant", False),
            ("New gain and integral time; watch one shift", False),
        ],
        "comments": [
            (
                "marina.costa",
                "The high-pressure alarm in Alarms rings at every peak; the operators "
                "acknowledge it a dozen times a shift.",
            ),
            (
                "ana.lima",
                "{{INC-2026-007}} describes the same cycle on PIC-1002, fixed by retuning. "
                "{{DOC-TG-001}} section 3 has the steps.",
            ),
        ],
    },
    {
        "title": "Calibrate the TIC-1209 thermocouple",
        "description": (
            "The furnaces model in Analytics sees the outlet temperature drifting away from it "
            "while the fuel and feed did not change: a sensor drift is likely."
        ),
        "priority": "high",
        "owner": "carlos.menezes",
        "group_id": "instrumentation",
        "status": "open",
        "links": [
            "asset:TIC-1209",
            "DOC-U100-OM-001",
            "DOC-DS-001",
            "Is TIC-1209 drifting or is the furnace hotter?",
            "Furnace outlet temperature drift",
        ],
        "items": [
            ("Compare with a portable thermometer at the next round", False),
            ("Calibrate TT-1209 (every 6 months, DOC-DS-001)", False),
            ("Quote a type N thermocouple", False),
        ],
        "comments": [
            (
                "ana.lima",
                "{{DOC-U100-OM-001}} 7.1 warns that a drifting TT-1209 keeps the loop at its "
                "setpoint while the column runs colder.",
            ),
        ],
    },
    # The visitor's own, so Desk's "My actions" is not empty for whoever enters the demo:
    # an operator's part in the three stories above, one in each column.
    # Whoever comments must see the action: its creator, its owner or a member of its group.
    {
        "title": "Hold the FIC-1003 flow during the valve test",
        "description": (
            "Carlos tests the FV-1003 stroke in manual on the day shift. The control room keeps "
            "the recycle flow above 40 m³/h and tells him at once if it falls."
        ),
        "priority": "high",
        "owner": VISITOR,
        "group_id": "u-100-operations",
        "status": "in_progress",
        "links": [
            "asset:FIC-1003",
            "PRO-U200-012",
            "Inspect the FIC-1003 recycle valve for stiction",
        ],
        "items": [
            ("Read PRO-U200-012 before the test", True),
            ("Agree the time with Carlos and the shift supervisor", True),
            ("Tell the control room when the valve goes to manual", False),
            ("Write down the flow at each 0.5 % step", False),
        ],
        "comments": [
            (
                "marina.costa",
                "Carlos starts tomorrow at 09:00. If the flow falls below 40 m³/h, put FIC-1003 "
                "back in automatic; {{PRO-U200-012}} step 4.",
            ),
        ],
    },
    {
        "title": "Count the PIC-1202 high-pressure alarms this shift",
        "description": (
            "Ana needs how often the high-pressure alarm rings before she retunes PIC-1202, to "
            "compare with the shifts after."
        ),
        "priority": "medium",
        "owner": VISITOR,
        "group_id": "u-100-operations",
        "status": "open",
        "links": [
            "asset:PIC-1202",
            "Retune PIC-1202: aggressive tuning makes it oscillate",
            "Why does the PIC-1202 pressure alarm ring so often?",
        ],
        "items": [
            ("Count the alarms per hour in Alarms", False),
            ("Write the count in today's handover", False),
        ],
        "comments": [
            (
                "ana.lima",
                "One shift is enough: the count before the retune is what we compare against.",
            ),
        ],
    },
    {
        "title": "Read TT-1209 with a portable thermometer on the round",
        "description": (
            "A reading beside TT-1209 tells whether the thermocouple drifts or the furnace "
            "outlet really runs hotter."
        ),
        "priority": "medium",
        "owner": VISITOR,
        "group_id": "u-100-operations",
        "status": "blocked",
        "links": [
            "asset:TIC-1209",
            "DOC-DS-001",
            "Calibrate the TIC-1209 thermocouple",
        ],
        "items": [
            ("Book the portable thermometer at the workshop", True),
            ("Read the outlet temperature next to TT-1209 and note both values", False),
        ],
        "comments": [
            (
                "marina.costa",
                "Blocked: the workshop's portable thermometer is away for calibration until "
                "Thursday.",
            ),
        ],
    },
]


def actions(suite: Suite, passwords: dict[str, str], links: Links | None = None) -> None:
    """The week's open actions, each with what it follows, its checklist and its comments. Run
    again (an installation seeded before the links), each gets what it misses of them."""

    links = links or Links()
    ana = suite.session("ana.lima", passwords["ana.lima"])
    people = {"ana.lima": ana}
    have = {item.get("title"): item for item in _items(ana.get("/api/actions"), "actions")}
    fields = ("title", "description", "priority", "owner", "group_id")
    for spec in OPEN_ACTIONS:
        body = {key: spec[key] for key in fields}
        refs = links.of(*spec["links"])
        found = have.get(spec["title"])
        if found is None:
            body.update(due_at=_day(3), refs=refs)
            ident = _ident(ana.post("/api/actions", body))
            if spec["status"] != "open":
                ana.put(f"/api/actions/{ident}", {**body, "status": spec["status"]})
            log(f"action: {spec['title']}")
        else:
            ident = _ident(found)
        links.add(spec["title"], f"action:{ident}")
        action = ana.get(f"/api/actions/{ident}")
        kept = [item["ref"] for item in action.get("refs") or []]
        if set(refs) - set(kept):
            keys = (*fields, "due_at", "status")
            merged = list(dict.fromkeys([*kept, *refs]))
            ana.put(f"/api/actions/{ident}", {**{k: action.get(k) for k in keys}, "refs": merged})
        listed = {item["text"]: item for item in action.get("items") or []}
        for text, done in spec["items"]:
            item = listed.get(text)
            if item is None:
                added = ana.post(f"/api/actions/{ident}/items", {"text": text})
                item = next(entry for entry in added["items"] if entry["text"] == text)
            if done and not item.get("done"):
                ana.patch(f"/api/actions/{ident}/items/{item['item_id']}", {"done": True})
        said = {
            entry["text"] for entry in action.get("history") or [] if entry["kind"] == "comment"
        }
        for author, text in spec["comments"]:
            if links.fill(text) in said:
                continue
            if author not in people:
                people[author] = suite.session(author, passwords[author])
            people[author].post(f"/api/actions/{ident}/comments", {"text": links.fill(text)})
