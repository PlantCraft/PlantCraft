"""The demo story: fills a fresh installation with data that explains the suite by itself.

``processcraft demo seed`` (run by ``install.sh --demo`` inside the PlantCraft container) signs
in as the administrator and goes through every app's own HTTP API, exactly as a person would in
the browser, so the story only uses what the apps already offer. One plant, Riverbend Refinery
(the Simulator: four units, 50 loops), and one week of a team that looks after it:

1. PlantCraft: the plant map (the OPC UA source, units, areas and loops), ten people in their
   groups, the read-only visitor ``demo``, a valve specialist, conversations and actions, and
   three weeks of their past.
2. Historian: the Simulator's last 48 hours archived, the lab's analyses (a CSV source) and a
   finished test run imported.
3. Analytics: loops with their criticality and three monitors: Control loop
   performance on every loop, Signal quality on every signal and the process model beside the
   plant (Furnaces says TIC-1209 drifts), with 48 hours of results replayed.
4. View: Plant overview (public link), Control room (pages in kiosk mode) and Loop detail, four
   descriptive reports sent on a schedule (loop performance, alarms, the unit's day, valves and
   instruments), and the process display "Riverbend plant" (an overview page, then a page per
   part of a unit with its loops' values, health and mode).
5. Alarms: seven example rules (Simple, Blocks and Python), two days of the pressure alarm's past
   and a silence on U-300.
6. Models: a simulation of each example, one fed by the plant, two grid studies, an optimization
   of the level controller and the Furnaces FMU published to Analytics.
7. Documents: the plant's twelve documents, linked to their assets.
8. Desk: notes, to-dos, the calendar, the team's day, assistant chats and two notebooks of loop
   data.

The plant's problems are the Simulator's own (``simcraft loops serve``): FIC-1003 has a sticky
valve, PIC-1202 oscillates, TIC-1209 drifts, TIC-1104 sees a cyclic disturbance; FIC-1001 is the
healthy loop to compare with. Every day and time is the plant's (the installation's zone).

Every step is idempotent: running the seed again adds only what is missing. The HTTP steps use
only the Python standard library.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEMO_MAP = "plantcraft-50-loops-map.json"
VISITOR = "demo"
# The four valves the Simulator simulates with stiction, and the loops that oscillate.
STICTION_LOOPS = ["FIC-1003", "FIC-1102", "FIC-1206", "FIC-1214"]
CRITICALITY = {
    "FIC-1001": "high",
    "FIC-1003": "high",
    "PIC-1002": "high",
    "PIC-1202": "high",
    "TIC-1104": "high",
    "TIC-1209": "high",
    "LIC-1004": "medium",
    "FIC-1102": "medium",
    "PIC-1103": "medium",
}
# Averaging levels: the team gave them the surge-level protocol (hold a band, dampen the feed),
# instead of the level protocol that asks them to hold their setpoint tightly.
SURGE_LEVELS = ["LIC-1105", "LIC-1107", "LIC-1208", "LIC-1211", "LIC-1218", "LIC-1225"]


# The demo's people: sector (``role``), a filled profile and their groups (GROUPS). Emails use the
# reserved example domain; nothing is ever sent there.
def _member(
    username: str,
    name: str,
    sector: str,
    title: str,
    unit: str,
    *,
    level: str = "editor",
    external: str = "",
) -> dict[str, Any]:
    return {
        "username": username,
        "display_name": name,
        "role": sector,
        "access_level": level,
        "profile": {
            "job_title": title,
            "affiliation": "external" if external else "internal",
            "organization": external or "Riverbend Refinery",
            "email": f"{username}@riverbend.example",
            "phone": "",
            "unit": unit,
        },
    }


CAST = [
    _member("ana.lima", "Ana Lima", "Process engineering", "Process engineer", "U-100 and U-200"),
    _member(
        "carlos.menezes",
        "Carlos Menezes",
        "Instrumentation and control",
        "Instrumentation technician",
        "All units",
    ),
    _member(
        "marina.costa", "Marina Costa", "Operations", "Operations supervisor", "U-100 and U-200"
    ),
    _member("rafael.souza", "Rafael Souza", "Operations", "Control room operator", "U-100"),
    _member("juliana.rocha", "Juliana Rocha", "Operations", "Control room operator", "U-200"),
    _member(
        "pedro.alves",
        "Pedro Alves",
        "Maintenance",
        "Electrical maintenance technician",
        "All units",
    ),
    _member(
        "beatriz.nunes", "Beatriz Nunes", "Maintenance", "Rotating equipment engineer", "All units"
    ),
    _member(
        "lucas.ferreira",
        "Lucas Ferreira",
        "Instrumentation and control",
        "Field service engineer, control valves",
        "Riverbend site",
        level="viewer",
        external="Valve vendor (contractor)",
    ),
    _member(
        "tiago.ramos", "Tiago Ramos", "IT and automation", "OT network and servers", "All units"
    ),
    _member(
        "camila.duarte",
        "Camila Duarte",
        "IT and automation",
        "Automation engineer, historian and interfaces",
        "All units",
    ),
]
# Groups by area (a unit of the plant) and by discipline, under three departments whose leader
# sees the work below (actions): the Alarms notify them. Parents come first.
GROUPS = [
    {
        "group_id": "operations",
        "name": "Operations",
        "kind": "department",
        "description": "Both process units, all shifts, and the engineers on call.",
        "coordinator": "marina.costa",
        "members": ["marina.costa"],
    },
    {
        "group_id": "engineering",
        "name": "Engineering",
        "kind": "department",
        "description": "Process engineering and instrumentation and control.",
        "coordinator": "ana.lima",
        "members": ["ana.lima"],
    },
    {
        "group_id": "maintenance",
        "name": "Maintenance",
        "kind": "department",
        "description": "Electrical and mechanical maintenance of every unit.",
        "coordinator": "beatriz.nunes",
        "members": ["beatriz.nunes"],
    },
    {
        "group_id": "u-100-operations",
        "parent_id": "operations",
        "name": "U-100 operations",
        "kind": "area",
        "asset_id": "U-100",
        "description": "Control room and field operators of the crude distillation unit, all shifts.",
        "coordinator": "marina.costa",
        # The visitor sits in, so that Desk's Team shows a group (read-only, like everything).
        "members": ["rafael.souza", "marina.costa", "ana.lima", VISITOR],
    },
    {
        "group_id": "u-200-operations",
        "parent_id": "operations",
        "name": "U-200 operations",
        "kind": "area",
        "asset_id": "U-200",
        "description": "Control room and field operators of the hydrotreating unit, all shifts.",
        "coordinator": "marina.costa",
        "members": ["juliana.rocha", "marina.costa"],
    },
    {
        "group_id": "process-engineering",
        "parent_id": "engineering",
        "name": "Process engineering",
        "kind": "discipline",
        "description": "Loop performance, operating limits and alarm rationalization.",
        "coordinator": "ana.lima",
        "members": ["ana.lima"],
    },
    {
        "group_id": "instrumentation",
        "parent_id": "engineering",
        "name": "Instrumentation and control",
        "kind": "discipline",
        "description": "Transmitters, control valves and analyzers; the valve vendor's field engineer.",
        "coordinator": "carlos.menezes",
        # The visitor too: the role guides open the Control loops folder's reports and dashboard
        # (View shows that folder to this group only).
        "members": ["carlos.menezes", "lucas.ferreira", VISITOR],
    },
    {
        "group_id": "electrical-maintenance",
        "parent_id": "maintenance",
        "name": "Electrical maintenance",
        "kind": "discipline",
        "description": "Motors, drives and power supply of pumps and compressors.",
        "coordinator": "pedro.alves",
        "members": ["pedro.alves"],
    },
    {
        "group_id": "mechanical-maintenance",
        "parent_id": "maintenance",
        "name": "Mechanical maintenance",
        "kind": "discipline",
        "description": "Pumps, compressors, heat exchangers and furnaces.",
        "coordinator": "beatriz.nunes",
        "members": ["beatriz.nunes"],
    },
    {
        # The administrator leads it (``ADMIN`` becomes the seed's admin account), so that the
        # person who installs the suite finds a team of their own in Desk's Team (round 8).
        "group_id": "it-automation",
        "name": "IT and automation",
        "kind": "department",
        "description": "The servers, the plant network, the historian and the control system's "
        "interfaces.",
        "coordinator": "ADMIN",
        "members": ["ADMIN", "tiago.ramos", "camila.duarte"],
    },
    {
        "group_id": "on-call",
        "parent_id": "operations",
        "name": "On call",
        "kind": "team",
        "description": "Engineers on call at night and at weekends; the operations supervisor leads.",
        "coordinator": "marina.costa",
        "members": ["ana.lima", "carlos.menezes"],
    },
]
# The scripted "Valve specialist" of earlier demos (it no longer makes sense
# next to the assistant): removed, with the conversation it took part in.
RETIRED_SPECIALIST = "valve.expert"


class SeedError(RuntimeError):
    pass


class _InsidePolicy(http.cookiejar.DefaultCookiePolicy):
    """Sends the session cookie over plain HTTP too: the seed talks to the containers directly,
    behind the proxy that terminates HTTPS (the cookie is ``Secure`` there)."""

    def return_ok_secure(self, cookie, request):  # noqa: ANN001
        return True


@dataclass
class Http:
    """A tiny JSON client with a cookie jar (the PlantCraft session) and a bearer token."""

    base: str
    token: str = ""
    jar: http.cookiejar.CookieJar = field(
        default_factory=lambda: http.cookiejar.CookieJar(policy=_InsidePolicy())
    )
    timeout: float = 120.0

    def __post_init__(self) -> None:
        self.base = self.base.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        ok: tuple[int, ...] = (),
        raw: bytes | None = None,
        content_type: str = "application/json",
    ) -> tuple[int, Any]:
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", content_type)
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.status, _decode(response.read())
        except urllib.error.HTTPError as error:
            payload = _decode(error.read())
            if error.code in ok:
                return error.code, payload
            raise SeedError(
                f"{method} {self.base}{path}: {error.code} {_detail(payload)}"
            ) from None
        except urllib.error.URLError as error:
            raise SeedError(f"{method} {self.base}{path}: {error.reason}") from None

    def get(self, path: str, **kw: Any) -> Any:
        return self.call("GET", path, **kw)[1]

    def post(self, path: str, body: Any = None, **kw: Any) -> Any:
        return self.call("POST", path, body, **kw)[1]

    def put(self, path: str, body: Any = None, **kw: Any) -> Any:
        return self.call("PUT", path, body, **kw)[1]

    def patch(self, path: str, body: Any = None, **kw: Any) -> Any:
        return self.call("PATCH", path, body, **kw)[1]


def _decode(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode("utf-8", "replace")


def _detail(payload: Any) -> str:
    if isinstance(payload, dict) and "detail" in payload:
        return json.dumps(payload["detail"])[:400]
    return str(payload)[:400]


def log(message: str) -> None:
    print(f"[demo] {message}", flush=True)


def _day(ahead: int = 0) -> str:
    """A day where the plant is (``YYYY-MM-DD``), ``ahead`` days from today: the demo's to-dos,
    appointments and due dates fall on the plant's calendar, never on UTC's."""

    from datetime import datetime, timedelta

    from plantcraft.config import plant_timezone

    return (datetime.now(plant_timezone()) + timedelta(days=ahead)).date().isoformat()


def wait_until(what: str, check: Any, seconds: float, every: float = 3.0) -> Any:
    deadline = time.monotonic() + seconds
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            answer = check()
            if answer:
                return answer
        except SeedError as error:
            last = error
        time.sleep(every)
    raise SeedError(f"timed out waiting for {what}" + (f" ({last})" if last else ""))


@dataclass
class Suite:
    processcraft: str
    apps: dict[str, str]
    admin: str
    password: str
    visitor_password: str
    demo_map: Path
    wait: float = 600.0

    def session(self, username: str, password: str) -> Http:
        client = Http(self.processcraft)
        client.post("/api/login", {"username": username, "password": password})
        return client

    def app(self, session: Http, app_id: str) -> Http | None:
        base = self.apps.get(app_id)
        if not base:
            return None
        token = session.post("/api/v1/auth/token")["token"]
        return Http(base, token=token)


# PlantCraft ---------------------------------------------------------------------------------


def plant_map(admin: Http, suite: Suite) -> None:
    raw = suite.demo_map.read_bytes()
    name = urllib.parse.quote(suite.demo_map.name)
    answer = admin.post(f"/api/map/apply?filename={name}", raw=raw)
    log(f"plant map applied: {_short(answer)}")
    name_the_plant(admin)


# The demo plant, as the asset tree's root shows it (the installation calls it "Plant").
PLANT = {
    "name": "Riverbend Refinery",
    "description": "A demonstration refinery simulated by PlantCraft Simulator: four units and 50 "
    "control loops, with their equipment, transmitters and valves.",
}
PLANT_RECORD = {"location": "Simulated site", "operator": "PlantCraft demo"}


def name_the_plant(admin: Http) -> None:
    """The root of the tree gets the refinery's name (edited by hand, so restarts keep it)."""

    tree = admin.get("/api/assets")
    root = tree.get("root_id") if isinstance(tree, dict) else None
    if not root:
        return
    current = next((item for item in tree["items"] if item["asset_id"] == root), {})
    if current.get("name") != PLANT["name"]:
        admin.patch(f"/api/assets/{urllib.parse.quote(root)}", PLANT)
    try:
        admin.patch(f"/api/assets/{urllib.parse.quote(root)}/attributes", {"values": PLANT_RECORD})
    except SeedError as error:  # an admin removed the attributes from the Plant type
        log(f"plant record skipped: {error}")
    log(f"plant named {PLANT['name']}")


def _short(answer: Any) -> str:
    if isinstance(answer, dict):
        keys = [k for k, v in answer.items() if isinstance(v, (int, str)) and k != "detail"]
        return ", ".join(f"{k}={answer[k]}" for k in keys[:8]) or "ok"
    return "ok"


def archive_signals(admin: Http, suite: Suite) -> None:
    """Every signal of the Simulator read (Historian archives them when it is the data layer)."""

    def tags() -> list[str]:
        page = admin.get("/api/data/sources/plantcraft/signals?limit=1000")
        return [item["tag"] for item in page.get("items", [])]

    found = wait_until("the Simulator's signals", tags, suite.wait)
    answer = admin.post(
        "/api/data/sources/plantcraft/signals/use", {"tags": found, "monitored": True}
    )
    log(f"{len(found)} the Simulator's signals in use ({answer.get('updated')} new)")


def people(admin: Http, suite: Suite) -> dict[str, str]:
    """The cast (random passwords, kept only for this run) and the visitor account."""

    passwords: dict[str, str] = {}
    existing = {item["username"] for item in _items(admin.get("/api/users/accounts"), "users")}
    for person in CAST:
        password = secrets.token_urlsafe(18)
        passwords[person["username"]] = password
        if person["username"] in existing:
            admin.post(f"/api/users/{person['username']}/password", {"password": password})
            admin.put(
                f"/api/users/{person['username']}",
                {k: person[k] for k in ("display_name", "role", "access_level", "profile")}
                | {"applications": None, "active": True},
            )
            continue
        admin.post("/api/users", {**person, "password": password, "applications": None})
        log(f"person {person['display_name']} ({person['role']})")
    visitor = {
        "username": VISITOR,
        "display_name": "Demo visitor",
        "role": "Visitor (read-only)",
        "access_level": "viewer",
        "applications": None,
    }
    if VISITOR in existing:
        admin.post(f"/api/users/{VISITOR}/password", {"password": suite.visitor_password})
    else:
        admin.post("/api/users", {**visitor, "password": suite.visitor_password})
        log(f"visitor account '{VISITOR}' (read-only)")
    return passwords


def groups(admin: Http, username: str = "admin") -> None:
    """The demo's groups, as GROUPS says (created, or set back to it); ``ADMIN`` there is the
    administrator the seed signs in as."""

    existing = {item["group_id"] for item in _items(admin.get("/api/groups"), "groups")}
    for group in GROUPS:
        group = {
            **group,
            "coordinator": username if group["coordinator"] == "ADMIN" else group["coordinator"],
            "members": [username if item == "ADMIN" else item for item in group["members"]],
        }
        if group["group_id"] in existing:
            admin.put(f"/api/groups/{group['group_id']}", group)
        else:
            admin.post("/api/groups", group)
    log(f"{len(GROUPS)} groups: departments, areas, disciplines, IT and on call")


def retire_specialist(admin: Http, workspace: Any) -> None:
    """Removes the retired valve specialist and, where the seed reaches PlantCraft's database, the
    conversations it was part of, so ``conversations`` starts them again without it."""

    status, _ = admin.call("DELETE", f"/api/specialists/{RETIRED_SPECIALIST}", ok=(404,))
    if status != 404:
        log(f"specialist '{RETIRED_SPECIALIST}' removed")
    if workspace is None:
        return
    messages = workspace.messages
    with messages._lock, messages._write() as connection:
        gone = connection.execute(
            """
            DELETE FROM conversations WHERE conversation_id IN (
                SELECT conversation_id FROM conversation_members WHERE username = ?
                UNION SELECT conversation_id FROM conversation_messages WHERE author = ?
            )
            """,
            (RETIRED_SPECIALIST, RETIRED_SPECIALIST),
        ).rowcount
    if gone:
        log(f"{gone} conversation(s) with the retired specialist removed")


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


def _doc(*blocks: dict[str, Any]) -> dict[str, Any]:
    return {"type": "doc", "content": list(blocks)}


def _para(*parts: Any) -> dict[str, Any]:
    return {
        "type": "paragraph",
        "content": [
            {"type": "text", "text": part} if isinstance(part, str) else part for part in parts
        ],
    }


def _mention(ref: str, label: str) -> dict[str, Any]:
    return {"type": "mention", "attrs": {"id": ref, "label": label}}


def _checklist(*items: tuple[bool, dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "taskList",
        "content": [
            {"type": "taskItem", "attrs": {"checked": done}, "content": [line]}
            for done, line in items
        ],
    }


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


# Desk's Team on a demo day (round 8): someone away, someone busy, and the IT team's work, one
# action late, so that every group shows how its people are doing.
TEAM_DAY = (
    ("camila.duarte", "Vendor training", True),
    ("juliana.rocha", "Day off", True),
    ("tiago.ramos", "Firewall change window", False),
)
IT_ACTIONS = (
    ("Renew the historian server certificate", "tiago.ramos", -2, "high"),
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


# The story's links ---------------------------------------------------------------------------

# Everything the team writes points at what it is about ("conectar tudo"): an
# action names the document it follows, the dashboard that shows it and the chat that explained
# it; a message links the action it opened. Texts write ``{{name}}`` (or ``{{name|label}}``) for
# such a thing: a document by its number, a dashboard or report by its name, an action, chat or
# conversation by its title. It becomes a link once the thing exists, its label otherwise.
NAMED = re.compile(r"\{\{([^{}|]+)(?:\|([^{}]+))?\}\}")
# Where a kind's page is, for the assistant's Markdown (a message or note links by reference).
PAGES = {
    "doc": "/doc/documents/{id}",
    "dashboard": "/dash/dashboards/{id}",
    "report": "/dash/reports/{id}",
    "asset": "/assets/{id}",
}


@dataclass
class Links:
    """What the story points at, by name: ``"DOC-MH-001"`` -> ``"doc:<id>"``."""

    refs: dict[str, str] = field(default_factory=dict)

    def add(self, name: str, ref: str) -> None:
        self.refs[name] = ref

    def ref(self, name: str) -> str | None:
        """``name``'s reference (an ``asset:`` reference is its own), or None."""

        name = name.strip()
        return name if name.startswith("asset:") else self.refs.get(name)

    def of(self, *names: str) -> list[str]:
        """The references of ``names`` that exist."""

        return list(dict.fromkeys(ref for ref in map(self.ref, names) if ref))

    def rich(self, text: str) -> tuple[list[Any], str]:
        """``text`` as a note's paragraph parts (mentions for the links) and its plain text."""

        parts: list[Any] = []
        plain, last = [], 0
        for match in NAMED.finditer(text):
            parts.append(text[last : match.start()])
            plain.append(text[last : match.start()])
            label = (match[2] or match[1].removeprefix("asset:")).strip()
            ref = self.ref(match[1])
            parts.append(_mention(ref, label) if ref else label)
            plain.append(f"#{label}" if ref else label)
            last = match.end()
        parts.append(text[last:])
        plain.append(text[last:])
        return [part for part in parts if part], "".join(plain)

    def fill(self, text: str) -> str:
        """``{{name}}`` as a mention, ``#[label](kind:id)``, or its label when it is missing."""

        def mention(match: re.Match[str]) -> str:
            label = (match[2] or match[1].removeprefix("asset:")).strip()
            ref = self.ref(match[1])
            return f"#[{label}]({ref})" if ref else label

        return NAMED.sub(mention, text)

    def markdown(self, text: str) -> str:
        """``{{name}}`` as a Markdown link to its page (the assistant's answers), or bold."""

        def link(match: re.Match[str]) -> str:
            label = (match[2] or match[1].removeprefix("asset:")).strip()
            kind, _, ident = (self.ref(match[1]) or "").partition(":")
            page = PAGES.get(kind)
            return f"[{label}]({page.format(id=ident)})" if page else f"**{label}**"

        return NAMED.sub(link, text)


def story_links(suite: Suite, admin: Http) -> Links:
    """The documents, dashboards and reports the apps hold now, by number and name. Each is
    explained to PlantCraft too (API v1 knowledge, as their app's editor), so a link to it reads
    its name, not its id, and the assistant knows what it is."""

    links = Links()
    texts = []
    found = [
        ("doccraft", "/api/documents", "documents", "number", "doc_id", "doc"),
        ("dashcraft", "/api/dashboards", "dashboards", "name", "dashboard_id", "dashboard"),
        ("dashcraft", "/api/reports", "reports", "name", "report_id", "report"),
    ]
    for app_id, path, key, name, ident, kind in found:
        client = suite.app(admin, app_id)
        if client is None:
            continue
        status, answer = client.call("GET", path, ok=(404, 502, 503))
        for item in _items(answer, key) if status < 300 else []:
            if not item.get(name) or item.get(ident) is None:
                continue
            ref = f"{kind}:{item[ident]}"
            links.add(item[name], ref)
            about = " ".join(str(item.get(field) or "") for field in ("title", "description"))
            texts.append(
                {
                    "app": app_id,
                    "ref": ref,
                    "kind": kind,
                    "title": str(item[name])[:200],
                    "text": f"{item[name]}: {about.strip()}"[:2000]
                    if about.strip()
                    else item[name],
                    "url": PAGES[kind].format(id=item[ident]),
                }
            )
    if texts:
        platform = Http(suite.processcraft, token=admin.post("/api/v1/auth/token")["token"])
        status, answer = platform.call("PUT", "/api/v1/knowledge", texts, ok=(403, 404, 422))
        if status < 300 and answer.get("errors"):
            log(f"WARNING knowledge: {_detail(answer['errors'][:2])}")
    return links


# The pages of what a reference names, for the demo's guides by role (frontend/src/demoGuides.tsx).
GUIDE_PAGES = {
    **PAGES,
    "action": "/actions/{id}",
    "conversation": "/messages/{id}",
    "chat": "/assistant/{id}",
    "diagram": "/dash/diagrams/{id}",
    "study": "/model/studies/{id}",
}


def guide_links(workspace: Any, suite: Suite, admin: Http, links: Links) -> int:
    """Where each name of the story opens now (``demo_guide_links``): the guides by role point at
    "Plant overview" or "DOC-MH-001", whose ids are this installation's. Also the View process
    displays and the Models studies, which the story's texts do not name."""

    _named(links, workspace.actions, workspace.messages, suite.admin)
    pages: dict[str, str] = {}
    for name, ref in links.refs.items():
        kind, _, ident = ref.partition(":")
        if kind in GUIDE_PAGES and ident:
            pages[name] = GUIDE_PAGES[kind].format(id=urllib.parse.quote(ident, safe=""))
    found = [
        ("dashcraft", "/api/diagrams", "name", "diagram_id", "diagram"),
        ("modelcraft", "/api/studies", "name", "id", "study"),
    ]
    for app_id, path, name, ident, kind in found:
        client = suite.app(admin, app_id)
        if client is None:
            continue
        try:
            status, answer = client.call("GET", path, ok=(404, 502, 503))
        except SeedError as error:
            log(f"WARNING guides: {error}")
            continue
        for item in answer if status < 300 and isinstance(answer, list) else []:
            if item.get(name) and item.get(ident) is not None:
                pages.setdefault(str(item[name]), GUIDE_PAGES[kind].format(id=item[ident]))
    workspace.demo_visits.set_guide_links(pages)
    return len(pages)


def _named(links: Links, store: Any, messages: Any, admin: str) -> None:
    """The actions and conversations PlantCraft holds, by title."""

    for item in store.list(limit=1000):
        links.add(item["title"], f"action:{item['action_id']}")
    for item in messages.list_for(admin, limit=1000):
        if item.get("title"):
            links.add(item["title"], f"conversation:{item['conversation_id']}")


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


# PlantCraft's past --------------------------------------------------------------------------

# Weeks of the team's work before today, written straight into PlantCraft's database with the
# moment each step happened (``recorded_at``): actions finished, cancelled and under way, and the
# conversations around them. Times are days and hours before now, so a seed run next month tells
# the same story. Steps: (days ago, hour, who, what) per action; what is "create", "comment:<text>"
# or a status (in_progress, blocked, done, cancelled).
PAST_ACTIONS: list[dict[str, Any]] = [
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


# Desk's Assistant and Notebooks -----------------------------------------------------------------

# Chats with the assistant as the team keeps them, written for the demo: what a language model
# answers from Analytics' results and the plant's documents. Each was asked on the page it is
# about (``place``, ``about``) and lists its sources under the answer (``sources``: names, see
# ``Links``); Ana's and Carlos's are shared with everyone, so the visitor reads them in "Shared
# with me"; the visitor has one too. ``{{name}}`` in an answer links that thing's page.
DEMO_ANSWER = "Example answer, written for the demo"
ASSISTANT_CHATS: list[dict[str, Any]] = [
    {
        "owner": "ana.lima",
        "title": "Why does FIC-1003 cycle?",
        "place": "Analytics › FIC-1003",
        "about": "asset:FIC-1003",
        "question": "Why does the recycle flow FIC-1003 cycle with a saw-tooth output?",
        "answer": "**A sticky valve: FV-1003 has stiction.**\n\n"
        "- Analytics' *Control loop performance* flags stiction on [FIC-1003](/assets/FIC-1003): the "
        "output ramps while the flow stays put, then the flow jumps (the PV against OP plot draws "
        "flat steps, not a line).\n"
        "- The maintenance history ({{DOC-MH-001}}, FV-1003) measured a dead band of **2.8 %** "
        "after the graphite packing was tightened for a stem leak (WO-25-1182, 2025-05-20).\n"
        "- The troubleshooting guide ({{DOC-TG-001}}, 4.1) lists FIC-1003, FIC-1102, FIC-1206 and "
        "FIC-1214 as the loops with known stiction.\n\n"
        "**Next:** the valve test of {{PRO-U200-012}} (steps of 0.5 % in manual, 30 s apart; stop "
        "if the flow falls below 40 m³/h), then the PTFE V-ring packing the history proposes. "
        "Retuning would only hide it. The action is already open for Carlos Menezes.",
        "sources": [
            "asset:FIC-1003",
            "DOC-MH-001",
            "DOC-TG-001",
            "PRO-U200-012",
            "Inspect the FIC-1003 recycle valve for stiction",
        ],
        "shared": True,
    },
    {
        "owner": "ana.lima",
        "title": "Is TIC-1209 drifting or is the furnace hotter?",
        "place": "Analytics › TIC-1209",
        "about": "asset:TIC-1209",
        "question": "The furnaces model says TIC-1209 reads higher than expected. Sensor or process?",
        "answer": "**Most likely the sensor, TT-1209.**\n\n"
        "- Analytics' Furnaces model sees the outlet temperature leave the model slowly while the "
        "fuel and the feed hold still: a process change would move them too.\n"
        "- The U-100 operating manual ({{DOC-U100-OM-001}}, 7.1) warns that a drifting TT-1209 "
        "keeps TIC-1209 at its setpoint while the column runs colder, and asks for a check with "
        "a portable thermometer.\n"
        "- The datasheets ({{DOC-DS-001}}) calibrate TT-1209 every 6 months; the maintenance "
        "history proposes a type N thermocouple, which drifts less.\n\n"
        "**Next:** compare with a portable reading at the next round; the calibration action is "
        "open for instrumentation.",
        "sources": [
            "asset:TIC-1209",
            "DOC-U100-OM-001",
            "DOC-DS-001",
            "Calibrate the TIC-1209 thermocouple",
        ],
        "shared": True,
    },
    {
        "owner": "ana.lima",
        "title": "Why does the PIC-1202 pressure alarm ring so often?",
        "place": "Alarms › PIC-1202 high pressure",
        "about": "asset:PIC-1202",
        "question": "The PIC-1202 high-pressure alarm rang dozens of times in two days. Why?",
        "answer": "**The loop oscillates; the alarm only follows it.**\n\n"
        "- The alarm rises at each peak of a cycle of about **12 minutes**: Analytics' oscillation "
        "watch finds the same period on [PIC-1202](/assets/PIC-1202) and rates it critical.\n"
        "- The output swings as much as the pressure, with no stiction signature: the tuning is "
        "too aggressive for the separator's time constant.\n"
        "- {{INC-2026-007}} tells the same story on PIC-1002: shelving the alarm hid it for a "
        "week, retuning fixed it. The {{DOC-TG-001}} (section 3) has the retuning steps.\n\n"
        "**Next:** retune rather than raise the limit or shelve (an alarm that rings at every "
        "cycle is a *chattering* alarm in ISA-18.2 terms). Ana's retune action is open.",
        "sources": [
            "asset:PIC-1202",
            "INC-2026-007",
            "DOC-TG-001",
            "Retune PIC-1202: aggressive tuning makes it oscillate",
        ],
        "shared": True,
    },
    {
        "owner": "carlos.menezes",
        "title": "How do I test FV-1003 without stopping the unit?",
        "place": "Documents › PRO-U200-012",
        "about": "",
        "question": "How do I test the FV-1003 valve stroke with the unit running?",
        "answer": "Follow {{PRO-U200-012}} (in Portuguese; the steps in short):\n\n"
        "1. Agree the test with the control room and put **FIC-1003 in manual**.\n"
        "2. Move the output in steps of **0.5 %**, 30 s apart, first up, then down.\n"
        "3. Write down the output at which the flow starts to move: the gap between up and down "
        "is the dead band. Above **1 %** the valve needs work.\n"
        "4. Stop if the flow falls below **40 m³/h** and go back to automatic.\n\n"
        "The last test on FV-1003 ({{DOC-MH-001}}) found 2.8 %, after the packing was tightened.",
        "sources": ["PRO-U200-012", "DOC-MH-001", "asset:FIC-1003"],
        "shared": True,
    },
    {
        "owner": VISITOR,
        "title": "Which loops need attention today?",
        "place": "Desk › Assistant",
        "about": "",
        "question": "Which loops of the plant need attention today, and why?",
        "answer": "Four loops stand out in Analytics' results this morning:\n\n"
        "| Loop | Level | Why |\n|---|---|---|\n"
        "| [FIC-1003](/assets/FIC-1003) | Critical | Sticky valve (stiction), the flow cycles |\n"
        "| [PIC-1202](/assets/PIC-1202) | Critical | Oscillates: tuned too hard; the pressure "
        "alarm rings at its peaks |\n"
        "| [TIC-1209](/assets/TIC-1209) | Warning | Drifts away from the Furnaces model: a "
        "sensor drift is likely |\n"
        "| [TIC-1104](/assets/TIC-1104) | Warning | A cyclic disturbance from the furnace draft |\n\n"
        "[FIC-1001](/assets/FIC-1001), the feed, is healthy: compare them on the {{Plant overview}} "
        "dashboard in View. Each problem has an open action in Desk.",
        "sources": [
            "asset:FIC-1003",
            "asset:PIC-1202",
            "asset:TIC-1209",
            "Plant overview",
        ],
        "shared": False,
    },
    # More of the team's chats (about twenty, from several apps).
    {
        "owner": "ana.lima",
        "title": "Which loops got worse this week?",
        "place": "Analytics › Results",
        "about": "",
        "question": "Which loops got worse this week compared with last week?",
        "answer": "**Three loops lost ground; one recovered.**\n\n- [FIC-1003](/assets/FIC-1003): from warning to critical, stiction growing since Monday.\n- [PIC-1202](/assets/PIC-1202): critical all week, the 12-minute oscillation did not change.\n- [TIC-1104](/assets/TIC-1104): a cyclic disturbance appears in the afternoons, with the furnace draft.\n- [FIC-1102](/assets/FIC-1102) recovered after its positioner was replaced.\n\nThe {{Control loops weekly performance}} report lists them all with their indices.",
        "sources": [
            "asset:FIC-1003",
            "asset:PIC-1202",
            "asset:TIC-1104",
            "asset:FIC-1102",
            "Control loops weekly performance",
        ],
        "shared": True,
    },
    {
        "owner": "carlos.menezes",
        "title": "What does the FV-1003 packing history say?",
        "place": "Documents › DOC-MH-001",
        "about": "asset:FIC-1003",
        "question": "What maintenance did FV-1003 get in the last two years?",
        "answer": "From {{DOC-MH-001}}:\n\n1. **2024-11**: positioner recalibrated after a feed change.\n2. **2025-05-20** (WO-25-1182): graphite packing tightened for a stem leak; the dead band went up to 2.8 %.\n3. **Proposed**: a PTFE V-ring packing, which holds the stem with less friction.\n\nThe stiction Analytics sees now matches the 2025 tightening.",
        "sources": ["DOC-MH-001", "asset:FIC-1003"],
        "shared": True,
    },
    {
        "owner": "marina.costa",
        "title": "What should the night shift watch on U-200?",
        "place": "Desk › Assistant",
        "about": "",
        "question": "What should the night shift watch on U-200 tonight?",
        "answer": "**Two things on U-200:**\n\n- [PIC-1202](/assets/PIC-1202) oscillates: its high-pressure alarm will ring at the peaks. Do not shelve it; the retune is planned this week.\n- [FIC-1003](/assets/FIC-1003) keeps cycling until its valve test tomorrow morning: keep it in automatic.\n\nEverything else on U-200 is healthy in Analytics' last round.",
        "sources": ["asset:PIC-1202", "asset:FIC-1003"],
        "shared": True,
    },
    {
        "owner": "ana.lima",
        "title": "Is LIC-1004 stable after the retune?",
        "place": "Analytics › LIC-1004",
        "about": "asset:LIC-1004",
        "question": "Did the LIC-1004 retune hold through the feed changes?",
        "answer": "**Yes.** Since the retune, Analytics rates [LIC-1004](/assets/LIC-1004) healthy in every round: the level settles in about 4 minutes after a feed change, with no overshoot above 5 %. The trend is on the {{Plant overview}} dashboard.",
        "sources": ["asset:LIC-1004", "Plant overview"],
        "shared": True,
    },
    {
        "owner": "juliana.rocha",
        "title": "How do I acknowledge a group of alarms?",
        "place": "Alarms › Alarms",
        "about": "",
        "question": "How do I acknowledge several alarms at once?",
        "answer": "In Alarms, open **Alarms**, tick the rows you have seen and press **Acknowledge**. Each alarm also reaches its people in Notifications, where the same button works. An acknowledged alarm stops its reminders but stays in the list until its rule clears it.",
        "sources": [],
        "shared": True,
    },
    {
        "owner": "lucas.ferreira",
        "title": "Which transmitters are due for calibration?",
        "place": "Documents › DOC-DS-001",
        "about": "",
        "question": "Which U-100 transmitters are due for calibration this month?",
        "answer": "From the datasheets ({{DOC-DS-001}}), with their last calibration in the maintenance history:\n\n| Transmitter | Every | Due |\n|---|---|---|\n| TT-1209 | 6 months | now (and drifting) |\n| FT-1001 | 12 months | in 3 weeks |\n| LT-1004 | new | next year |\n\nTT-1209 already has its calibration action.",
        "sources": ["DOC-DS-001", "DOC-MH-001", "Calibrate the TIC-1209 thermocouple"],
        "shared": True,
    },
    {
        "owner": "ana.lima",
        "title": "Draft the weekly loop review",
        "place": "Desk › Assistant",
        "about": "",
        "question": "Draft the summary for Monday's weekly loop review.",
        "answer": "**Weekly loop review: draft**\n\n- Fixed: FIC-1102 (positioner), LIC-1004 (retuned).\n- Open: FIC-1003 (valve test tomorrow), PIC-1202 (retune this week), TIC-1209 (calibration).\n- Watch: TIC-1104 (afternoon disturbance), FIC-1214 (in manual until its valve is checked).\n\nNumbers from the {{Control loops weekly performance}} report.",
        "sources": ["Control loops weekly performance", "asset:FIC-1003", "asset:PIC-1202"],
        "shared": True,
    },
    {
        "owner": "carlos.menezes",
        "title": "What spares do we need for the valve work?",
        "place": "Desk › Assistant",
        "about": "",
        "question": "What spare parts do the open valve actions need?",
        "answer": "From the open actions and {{DOC-MH-001}}:\n\n- FV-1003: a PTFE V-ring packing set (proposed) and stem gaskets.\n- FV-1214: a positioner, the same model as FIC-1102's.\n- FV-1206: a packing set, to fit together with FV-1214.\n\nCheck the store before the window: the positioner takes two weeks to arrive.",
        "sources": ["DOC-MH-001", "asset:FIC-1214", "asset:FIC-1206"],
        "shared": True,
    },
    {
        "owner": "marina.costa",
        "title": "Why did the plant lose data last night?",
        "place": "Alarms › Events",
        "about": "",
        "question": "We had a 'No data from the plant' alarm at 03:10. What happened?",
        "answer": "The Historian's OPC UA collector lost its connection for **12 minutes** (03:10 to 03:22) and reconnected by itself: every U-100 signal shows the same gap. Nothing changed in the process. If it happens again, check the network switch in the rack room, which IT replaced last month.",
        "sources": [],
        "shared": True,
    },
    {
        "owner": VISITOR,
        "title": "What does the stiction index mean?",
        "place": "Analytics › Blocks",
        "about": "",
        "question": "What does Analytics' stiction index measure, and when is it bad?",
        "answer": "It measures how much the valve **sticks, then jumps**: the output moves while the flow stays still, then the flow catches up at once. Analytics plots the PV against the OP: a healthy valve draws a line, a sticky one flat steps.\n\n- Below **0.3**: healthy.\n- **0.3 to 0.6**: watch it.\n- Above **0.6**: plan a valve test.\n\n[FIC-1003](/assets/FIC-1003) is at 0.74 this morning.",
        "sources": ["asset:FIC-1003"],
        "shared": False,
    },
    {
        "owner": VISITOR,
        "title": "Compare the two furnace outlets",
        "place": "View › Trends",
        "about": "",
        "question": "Compare TIC-1209 with TIC-1104 over the last day.",
        "answer": "Both outlets hold their setpoints, in different ways: [TIC-1209](/assets/TIC-1209) drifts slowly up against the Furnaces model (a sensor drift is likely), while [TIC-1104](/assets/TIC-1104) swings a few degrees every afternoon with the draft. The saved trend *Furnace outlets: TIC-1209 against TIC-1104* in View shows both.",
        "sources": ["asset:TIC-1209", "asset:TIC-1104"],
        "shared": False,
    },
    {
        "owner": "ana.lima",
        "title": "Can a model predict PIC-1202's new tuning?",
        "place": "Models › Studies",
        "about": "asset:PIC-1202",
        "question": "Can Models tell which tuning stops the PIC-1202 oscillation?",
        "answer": "Yes: a study on the separator model runs a grid of gains and integral times and ranks them by overshoot and settling time. The best runs halve the gain and double the integral time; the oscillation disappears, with a 4-minute settling. Try it on the plant in small steps, as {{DOC-TG-001}} section 3 says.",
        "sources": ["asset:PIC-1202", "DOC-TG-001"],
        "shared": True,
    },
]
NOTEBOOKS = [
    # (owner, name, loop, roles, period): a notebook of the loop's signals over the period.
    (VISITOR, "FIC-1003 sticky valve, last 12 h", "FIC-1003", ("pv", "sp", "op"), "-12h"),
    ("ana.lima", "PIC-1202 oscillation, last 24 h", "PIC-1202", ("pv", "sp", "op"), "-24h"),
]


def _signals_of(admin: Http, loop: str, roles: tuple[str, ...]) -> list[str]:
    asset = admin.get(f"/api/assets/{urllib.parse.quote(loop)}") or {}
    found = {
        item.get("role"): f"{item['source_id']}:{item['signal_id']}"
        for item in asset.get("signals") or []
        if item.get("source_id") and item.get("signal_id")
    }
    return [found[role] for role in roles if role in found]


def assistant_and_notebooks(
    workspace: Any, admin: Http, admin_name: str, links: Links | None = None
) -> dict[str, int]:
    """The team's assistant chats and two notebooks of loop data in people's folders; Notebooks
    is turned on (it ships off). Idempotent: a chat or notebook already there is kept. The chats
    are in ``links`` after, by title."""

    from plantcraft.assistant_chat import ChatStore
    from plantcraft.notebooks import file_name
    from plantcraft.notebooks.templates import series_notebook

    links = links or Links()
    written = {"chats": 0, "notebooks": 0}
    chats = ChatStore(workspace.db)
    for spec in ASSISTANT_CHATS:
        found = next(
            (item for item in chats.chats(spec["owner"]) if item["title"] == spec["title"]), None
        )
        if found is None:
            found = chats.create(
                spec["owner"], spec["title"], ref=spec["about"], place=spec["place"]
            )
            chats.add(found["chat_id"], "user", spec["question"])
            chats.add(
                found["chat_id"],
                "assistant",
                links.markdown(spec["answer"]),
                meta={"model": DEMO_ANSWER},
            )
            if spec["shared"]:
                chats.share(found["chat_id"], spec["owner"], ["everyone"])
            written["chats"] += 1
        else:
            # A chat seeded before the links: its answer as written now.
            answers = [m for m in chats.messages(found["chat_id"]) if m["role"] == "assistant"]
            text = links.markdown(spec["answer"])
            if answers and answers[-1]["meta"].get("model") == DEMO_ANSWER:
                if answers[-1]["text"] != text:
                    chats.update(answers[-1]["message_id"], text=text)
        links.add(spec["title"], f"chat:{found['chat_id']}")
    store = workspace.notebooks
    if store.settings()["allowed"] and not store.enabled():
        store.save_settings(actor=admin_name, enabled=True)
    for owner, name, loop, roles, period in NOTEBOOKS:
        if any(item.get("name") == file_name(name) for item in store.list(owner)):
            continue
        signals = _signals_of(admin, loop, roles)
        if not signals:
            continue
        _title, notebook = series_notebook(signals, period, "now", step=10, origin=f"{loop}'s page")
        store.create(owner, name, notebook)
        written["notebooks"] += 1
    return written


def chat_sources(workspace: Any, links: Links) -> None:
    """Each demo answer's sources, once the actions they name exist (run again: the same)."""

    from plantcraft.assistant_chat import ChatStore

    chats = ChatStore(workspace.db)
    for spec in ASSISTANT_CHATS:
        ref = links.refs.get(spec["title"], "")
        if not ref.startswith("chat:"):
            continue
        answers = [
            item
            for item in chats.messages(int(ref.removeprefix("chat:")))
            if item["role"] == "assistant"
        ]
        if answers:
            chats.update(answers[-1]["message_id"], refs=links.of(*spec["sources"]))


# Historian ------------------------------------------------------------------------------------

# The Simulator simulates 48 hours before it starts; copying them takes a minute or two.
BACKFILL_HOURS = 48
BACKFILL_WAIT = 900.0
SOURCE_FIELDS = (
    "id",
    "name",
    "kind",
    "endpoint",
    "namespace_uri",
    "username",
    "password_env",
    "enabled",
    "options",
    "retention_days",
    "default_scan_seconds",
    "default_deviation_percent",
    "default_max_seconds",
)


def histcraft(hist: Http, suite: Suite) -> None:
    """The Simulator's 48 simulated hours before the demo started copied from its own OPC UA
    history into Historian's archive (a backfill), so every app has a history on the first visit
    and reads it from the archive. A Historian without backfill reads them from the source
    (mode ``both``)."""

    def source() -> dict[str, Any] | None:
        listed = _items(hist.get("/api/sources"), "sources")
        found = next((item for item in listed if item.get("id") == "plantcraft"), None)
        return found if found and found.get("points") else None

    found = wait_until("The Simulator's signals in Historian", source, suite.wait)
    status, queued = hist.call(
        "POST", "/api/sources/plantcraft/backfill", {"hours": BACKFILL_HOURS}, ok=(404, 405)
    )
    answer: dict[str, Any] = {}
    if status == 202:
        request = queued["request"]

        def finished() -> dict[str, Any] | None:
            got = hist.get(f"/api/requests/{request}")
            return got if got.get("status") != "pending" else None

        try:
            answer = wait_until(
                "Historian's backfill of the Simulator", finished, max(suite.wait, BACKFILL_WAIT)
            )
        except SeedError as error:
            answer = {"result": {"detail": str(error)}}
    body = {key: found[key] for key in SOURCE_FIELDS if key in found}
    if answer.get("status") == "ok":
        if found.get("mode") == "both":
            hist.put("/api/sources/plantcraft", {**body, "mode": "", "password": None})
        result = answer.get("result") or {}
        log(
            f"Historian: {result.get('values', 0)} values of the Simulator's last {BACKFILL_HOURS} "
            f"hours archived ({result.get('signals', 0)} signals)"
        )
        return
    if found.get("mode") != "both":
        hist.put("/api/sources/plantcraft", {**body, "mode": "both", "password": None})
    detail = (answer.get("result") or {}).get("detail") or "no backfill in this Historian"
    log(f"Historian: the Simulator's history read from the source ({detail})")


# The lab's analyses: a second type of source (a CSV file) beside the Simulator's OPC UA server.
LAB_SOURCE = "lab"
LAB_DAYS = 30
LAB_EVERY_HOURS = 4
# Tag, name, unit, nominal value, spread (one sigma), slow drift over the month.
LAB_TAGS = (
    ("LAB-U100.CRUDE.BSW", "Crude to the unit, water and sediment", "% vol", 0.35, 0.08, 0.1),
    ("LAB-U100.DIESEL.SULFUR", "Diesel S10, sulfur", "mg/kg", 7.2, 0.9, 1.5),
    ("LAB-U100.DIESEL.DENSITY", "Diesel S10, density at 20 °C", "kg/m³", 836.0, 1.8, 2.0),
    ("LAB-U100.DIESEL.FLASH", "Diesel S10, flash point", "°C", 46.0, 1.2, -1.0),
    ("LAB-U100.NAPHTHA.RVP", "Light naphtha, Reid vapour pressure", "kPa", 62.0, 2.5, 3.0),
)


def lab_csv(now: float | None = None) -> bytes:
    """The lab's analyses of the last month, one sample every four hours, as the LIMS exports
    them: a wide CSV, the time in UTC first, one column per analysis. Simulated like the plant
    (a fixed seed: the same month always gives the same values); an analysis is now and then
    skipped, as in a real lab."""

    import math
    import random

    rng = random.Random(20261022)
    step = LAB_EVERY_HOURS * 3600
    end = int((now if now is not None else time.time()) // step * step)
    start = end - LAB_DAYS * 86400
    lines = ["time," + ",".join(tag for tag, *_ in LAB_TAGS)]
    for stamp in range(start + step, end + 1, step):
        share = (stamp - start) / (end - start)
        cells = []
        for _tag, _name, _unit, nominal, spread, drift in LAB_TAGS:
            value = nominal + drift * share + spread * rng.gauss(0, 1)
            value += 0.5 * spread * math.sin(2 * math.pi * stamp / 86400)
            cells.append("" if rng.random() < 0.04 else f"{value:.4g}")
        when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stamp))
        lines.append(when + "," + ",".join(cells))
    return ("\n".join(lines) + "\n").encode()


IMPORT_FILE = "pilot-test-run-2026-09.csv"
# Tag and nominal value of the pilot unit's test run, a one-off file kept as an import.
IMPORT_TAGS = (
    ("PILOT.TI-201", 182.0),
    ("PILOT.PI-202", 4.6),
    ("PILOT.FI-203", 12.5),
)


def import_csv() -> bytes:
    """Six hours of a past test run, one row a minute, the same values every time."""

    import calendar
    import math
    import random

    rng = random.Random(20260915)
    start = calendar.timegm((2026, 9, 15, 8, 0, 0))
    lines = ["time," + ",".join(tag for tag, _ in IMPORT_TAGS)]
    for minute in range(6 * 60):
        cells = [
            f"{nominal * (1 + 0.04 * math.sin(minute / 45)) + 0.01 * nominal * rng.gauss(0, 1):.4g}"
            for _tag, nominal in IMPORT_TAGS
        ]
        when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start + 60 * minute))
        lines.append(when + "," + ",".join(cells))
    return ("\n".join(lines) + "\n").encode()


def histcraft_import(hist: Http) -> None:
    """A finished test run's CSV, imported once as an example of Import & export. A Historian
    without imports skips it."""

    status, listed = hist.call("GET", "/api/imports", ok=(404,))
    if status == 404:
        log("Historian: no imports in this version, the example import is skipped")
        return
    if any(item.get("file_name") == IMPORT_FILE for item in listed or []):
        return
    checked = hist.post(
        # The file's times carry their offset (Z): the zone only names naive ones.
        f"/api/imports/check?name={IMPORT_FILE}&timezone=UTC",
        raw=import_csv(),
        content_type="text/csv",
    )
    if not checked.get("ok"):
        raise SeedError(f"Historian: the example import has errors: {checked.get('report')}")
    done = hist.post(
        "/api/imports", {"token": checked["token"], "name": "Pilot unit test run (Sep 2026)"}
    )
    log(f"Historian: example import {done['id']} ({checked['report'].get('values', 0)} values)")


def histcraft_lab(hist: Http) -> None:
    """The lab's CSV sent to Historian (the same file name refreshes it) and read as the source
    ``lab``, with its five analyses as points. A Historian without file upload skips it."""

    status, sent = hist.call(
        "POST",
        "/api/sources/files?name=lab-analyses.csv",
        raw=lab_csv(),
        content_type="text/csv",
        ok=(404, 405),
    )
    if status != 201:
        log("Historian: no file upload in this version, the lab's CSV is skipped")
        return
    listed = _items(hist.get("/api/sources"), "sources")
    if not any(item.get("id") == LAB_SOURCE for item in listed):
        hist.post(
            "/api/sources",
            {
                "id": LAB_SOURCE,
                "name": "Laboratory (LIMS export)",
                "kind": "csv",
                "endpoint": sent["path"],
                "options": {"timezone": "UTC"},
                "mode": "",
                "password": None,
                "enabled": True,
            },
        )
    points = [
        {
            "tag": tag,
            "source_id": LAB_SOURCE,
            "address": tag,
            "name": name,
            "description": name,
            "unit": unit,
            "kind": "number",
        }
        for tag, name, unit, *_ in LAB_TAGS
    ]
    added = hist.post("/api/points", {"points": points})
    log(
        f"Historian: the lab's CSV ({sent.get('rows', 0)} samples), "
        f"{len(added.get('added') or [])} new analyses"
    )


# Calculated signals (Historian's source ``calc``): one of each kind a person makes, a sum, a
# deviation from setpoint, a unit conversion and a totalizer, on the Simulator's archived tags.
# Tag, formula, unit, description.
CALC_SIGNALS = (
    (
        "U100.FEED.TOTAL",
        "[plantcraft:CPM.Loops.FIC-1001.PV] + [plantcraft:CPM.Loops.FIC-1007.PV]",
        "m³/h",
        "Total feed to the unit: feed flow plus charge flow",
    ),
    (
        "TIC-1209.DEV",
        "[plantcraft:CPM.Loops.TIC-1209.PV] - [plantcraft:CPM.Loops.TIC-1209.SP]",
        "°C",
        "Furnace outlet temperature, deviation from its setpoint (it drifts)",
    ),
    (
        "FIC-1210.KGH",
        "[plantcraft:CPM.Loops.FIC-1210.PV] * 0.8",
        "kg/h",
        "Fuel gas, mass flow (0.8 kg/Nm³)",
    ),
    (
        "FIC-1001.TODAY",
        'total([plantcraft:CPM.Loops.FIC-1001.PV], per="h", reset="day")',
        "m³",
        "Feed flow, total since midnight (UTC)",
    ),
)


def histcraft_calc(hist: Http) -> None:
    """The example calculated signals, added once (a signal that is there is skipped). A
    Historian without calculated signals, or without one of the inputs, skips them."""

    body = {
        "points": [
            {
                "source_id": "calc",
                "tag": tag,
                "address": formula,
                "unit": unit,
                "description": description,
                "name": description,
            }
            for tag, formula, unit, description in CALC_SIGNALS
        ]
    }
    status, done = hist.call("POST", "/api/points", body, ok=(400, 404, 422))
    if status not in (200, 201):
        log(
            f"Historian: no calculated signals in this version ({status}), the examples are skipped"
        )
        return
    skipped = [item for item in done.get("skipped") or [] if "exist" not in str(item).lower()]
    log(
        f"Historian: {len(done.get('added') or [])} example calculated signals"
        + (f", skipped {skipped}" if skipped else "")
    )


# Analytics ------------------------------------------------------------------------------------


def linkcraft(link: Http, suite: Suite) -> None:
    link.post("/api/loops/sync")
    loops = wait_until(
        "Analytics's loops",
        lambda: [item for item in _items(link.get("/api/loops"), "loops")],
        suite.wait,
    )
    log(f"Analytics: {len(loops)} loops")
    for loop_id, criticality in CRITICALITY.items():
        link.patch(f"/api/loops/{loop_id}", {"criticality": criticality}, ok=(404, 422))
    for loop_id in SURGE_LEVELS:
        link.patch(f"/api/loops/{loop_id}", {"profile_id": "surge_drum"}, ok=(404, 422))
    link.post("/api/round", ok=(409,))
    link.post("/api/signal-quality/run", ok=(409,))
    log("Analytics: Control loop performance and Signal quality started")
    # The archive's past as if Analytics had been watching: hourly rounds (each loop's health trend)
    # and every schedule's past runs. In the background; moments already there are skipped.
    status, answer = link.call(
        "POST",
        "/api/history/replay",
        {"hours": BACKFILL_HOURS, "step_minutes": 60},
        ok=(404, 405),
    )
    if status == 202:
        log(f"Analytics: replaying the last {BACKFILL_HOURS} hours of rounds and schedules")


def _ident(item: dict[str, Any]) -> Any:
    for key in ("id", "dashboard_id", "twin_id", "schedule_id", "action_id", "conversation_id"):
        if item.get(key) is not None:
            return item[key]
    raise SeedError(f"no id in {str(item)[:200]}")


def _items(answer: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(answer, dict):
        for name in (key, "items", "results"):
            if isinstance(answer.get(name), list):
                return answer[name]
        return []
    return answer or []


# View ------------------------------------------------------------------------------------


def _kpi(card_id: str, title: str, loop_id: str) -> dict[str, Any]:
    """A loop's health (0-100) on a dial: red under 50, amber under 75."""

    return {
        "card_id": card_id,
        "title": title,
        "kind": "gauge",
        "items": [{"asset_id": loop_id, "result": "linkcraft.loop_health", "label": loop_id}],
        "agg": "last",
        "window": "1d",
        "gauge_min": 0,
        "gauge_max": 100,
        "thresholds": {"low_alarm": 50, "low_warn": 75},
        "decimals": 0,
        "width": 3,
        # View draws a dial at least 2 rows high (a card of 1 row is a number).
        "height": 2,
    }


def _scatter(card_id: str, title: str, loop_id: str) -> dict[str, Any]:
    """PV against OP: a sticky valve draws flat steps, a healthy loop a cloud along a line."""

    return {
        "card_id": card_id,
        "title": title,
        "kind": "scatter",
        "items": [
            {"asset_id": loop_id, "role": "op", "label": "OP"},
            {"asset_id": loop_id, "role": "pv", "label": "PV"},
        ],
        "window": "12h",
        "width": 6,
        "height": 2,
    }


def _note(card_id: str, text: str, width: int = 12) -> dict[str, Any]:
    return {
        "card_id": card_id,
        "title": "",
        "kind": "text",
        "items": [],
        "text": text,
        "width": width,
    }


def _trend(card_id: str, title: str, loop_id: str, width: int = 6) -> dict[str, Any]:
    return {
        "card_id": card_id,
        "title": title,
        "kind": "trend",
        "items": [
            {"asset_id": loop_id, "role": "pv", "label": "PV"},
            {"asset_id": loop_id, "role": "sp", "label": "SP"},
            {"asset_id": loop_id, "role": "op", "label": "OP"},
        ],
        "agg": "mean",
        "window": "12h",
        "width": width,
        "height": 2,
    }


OVERVIEW = {
    "name": "Plant overview",
    "description": (
        "Demo: the health Analytics gives the loops with a problem, and their trends. "
        "FIC-1003 has a sticky valve, PIC-1202 oscillates, TIC-1209 drifts."
    ),
    "context_kind": "",
    "refresh_seconds": 60,
    "cards": [
        _note(
            "about",
            "Loop health from Analytics (0-100; red under 50, amber under 75) and the trends behind "
            "it. FIC-1003 has a sticky valve, PIC-1202 oscillates, TIC-1209 drifts; FIC-1001 "
            "is healthy, for comparison. Open a trend in full screen with its corner button.",
        ),
        _kpi("h1003", "Recycle flow FIC-1003", "FIC-1003"),
        _kpi("h1202", "Hydrotreater pressure PIC-1202", "PIC-1202"),
        _kpi("h1209", "Furnace outlet TIC-1209", "TIC-1209"),
        _kpi("h1001", "Feed flow FIC-1001 (healthy)", "FIC-1001"),
        _trend("t1003", "FIC-1003: the sticky valve's stick-slip", "FIC-1003"),
        _trend("t1202", "PIC-1202: oscillation from aggressive tuning", "PIC-1202"),
        _trend("t1209", "TIC-1209: slow sensor drift", "TIC-1209"),
        _trend("t1001", "FIC-1001: a healthy loop, for comparison", "FIC-1001"),
    ],
}


def _result_kpi(card_id: str, title: str, loop_id: str, result: str) -> dict[str, Any]:
    return {**_kpi(card_id, title, loop_id), "items": [{"asset_id": loop_id, "result": result}]}


# The area of the furnace loops (the plant map), where Analytics' Furnaces model algorithm runs, and
# the result kind of its "Model deviation" output.
FURNACE_AREA = "u-100-furnaces"
MODEL_DEVIATION = "linkcraft.out_model_deviation"

# View's folders: Operation for everyone, Control loops for its group (round 6, 2026-10-23; named
# Instrumentation until 2026-10-25, when the owner asked for Platform, Control loops and General).
OPERATION = {
    "name": "Operation",
    "description": "Screens for the control room and the shift; everyone sees them.",
    "viewers": [],
    "editors": [],
}
INSTRUMENTATION = {
    "name": "Control loops",
    "description": "Loop and valve diagnostics; only the Instrumentation and control group sees them.",
    "viewers": ["group:instrumentation"],
    "editors": [],
}


def _on(page: str, cards: Any) -> list[dict[str, Any]]:
    return [{**card, "page_id": page} for card in cards]


CONTROL_ROOM = {
    "name": "Control room",
    "description": (
        "Demo of a dashboard with pages: in full screen it turns from Overview to Loops to Valves "
        "every minute, without the toolbar (kiosk)."
    ),
    "context_kind": "",
    "refresh_seconds": 60,
    "pages": [
        {"page_id": "overview", "name": "Overview"},
        {"page_id": "loops", "name": "Loops"},
        {"page_id": "valves", "name": "Valves"},
    ],
    "page_seconds": 60,
    "tags": ["control room", "Unit 100"],
    "shared_cursor": True,
    "kiosk": True,
    "cards": [
        *_on(
            "overview",
            [
                _note(
                    "about",
                    "Three pages that turn every minute in full screen (Config › Time). Hovering "
                    "a trend marks the same moment on the others (Config › Display).",
                ),
                _kpi("h1003", "FIC-1003 recycle flow", "FIC-1003"),
                _kpi("h1202", "PIC-1202 hydrotreater pressure", "PIC-1202"),
                _kpi("h1209", "TIC-1209 furnace outlet", "TIC-1209"),
                _result_kpi("ffur", "Furnaces against the model", FURNACE_AREA, MODEL_DEVIATION),
            ],
        ),
        *_on(
            "loops",
            [
                _trend("t1003", "FIC-1003: stick-slip of a sticky valve", "FIC-1003"),
                _trend("t1202", "PIC-1202: oscillation from aggressive tuning", "PIC-1202"),
                _trend("t1209", "TIC-1209: slow sensor drift", "TIC-1209"),
                _trend("t1104", "TIC-1104: a cyclic disturbance", "TIC-1104"),
            ],
        ),
        *_on(
            "valves",
            [
                *(_kpi(f"v{loop[-4:]}", loop, loop) for loop in STICTION_LOOPS),
                *(
                    _scatter(f"vs{loop[-4:]}", f"{loop}: PV against OP", loop)
                    for loop in STICTION_LOOPS
                ),
            ],
        ),
    ],
}
LOOP_DETAIL = "Loop detail"


def _folders(dash: Http) -> dict[str, str]:
    """Operation and Control loops, by name: their ids."""

    ids = {item["name"]: item["folder_id"] for item in dash.get("/api/folders") or []}
    for folder in (OPERATION, INSTRUMENTATION):
        if folder["name"] not in ids:
            ids[folder["name"]] = dash.post("/api/folders", folder)["folder_id"]
            log(f"View: folder '{folder['name']}'")
    return ids


def dashcraft(dash: Http) -> None:
    """Three example dashboards ("só uns 3 exemplos"): Plant overview with a
    public link, Control room (three pages turning in kiosk mode) and Loop detail, from View's
    own template."""

    folders = _folders(dash)
    operation, instrumentation = folders["Operation"], folders[INSTRUMENTATION["name"]]
    kept = {item.get("name"): item for item in _items(dash.get("/api/dashboards"), "dashboards")}
    overview = kept.get(OVERVIEW["name"])
    if overview is None:
        overview = dash.post("/api/dashboards", {**OVERVIEW, "folder_id": operation})
        log("View: dashboard 'Plant overview'")
    if CONTROL_ROOM["name"] not in kept:
        dash.post("/api/dashboards", {**CONTROL_ROOM, "folder_id": operation})
        log("View: dashboard 'Control room' (three pages)")
    if LOOP_DETAIL not in kept:
        templates = dash.get("/api/templates") or []
        template = next(
            (item for item in templates if item.get("template_id") == "loop-detail"), None
        )
        if template:
            dash.post("/api/dashboards", {**template["draft"], "folder_id": instrumentation})
            log("View: dashboard 'Loop detail' from its template")
    shares = _items(dash.get(f"/api/dashboards/{_ident(overview)}/shares", ok=(503,)), "shares")
    if not shares:
        status, answer = dash.call(
            "POST",
            f"/api/dashboards/{_ident(overview)}/shares",
            {"label": "Public demo"},
            ok=(503,),
        )
        if status < 300:
            log(f"View: public link {answer.get('path')}")


# View's reports (2026-10-25): a document over one period, sent as PDF on a schedule; since
# 2026-10-26 a notebook of Markdown cells whose headings make its sections ---------------------


def _text(section_id: str, title: str, text: str = "", level: int = 1) -> dict[str, Any]:
    """A Markdown cell: its heading (``#`` level), then its text."""

    heading = f"{'#' * level} {title}" if title else ""
    return {"section_id": section_id, "kind": "text", "text": f"{heading}\n\n{text}".strip()}


def _card(section_id: str, card: dict[str, Any], width: str = "full") -> dict[str, Any]:
    return {"section_id": section_id, "kind": "card", "card": card, "width": width}


def _events(
    section_id: str, title: str, kinds: list[str], limit: int = 20, width: str = "full"
) -> dict[str, Any]:
    events = {"kinds": kinds, "limit": limit}
    return {
        "section_id": section_id,
        "kind": "events",
        "title": title,
        "events": events,
        "width": width,
    }


def _pvs(card_id: str, title: str, loops: list[str], kind: str = "stat") -> dict[str, Any]:
    """Each loop's PV over the period: one tile (or one table row) per loop."""

    return {
        "card_id": card_id,
        "title": title,
        "kind": kind,
        "items": [{"asset_id": loop, "role": "pv", "label": loop} for loop in loops],
        "agg": "mean",
        "window": "24h",
        "width": 12,
        "height": 1 if kind == "stat" else 3,
        "options": {"columns": ["mean", "min", "max", "unit", "state"]} if kind == "table" else {},
    }


def _health(card_id: str, title: str, loops: list[str], kind: str) -> dict[str, Any]:
    """Analytics' loop health of each loop: now (gauges, a table) or over the period (a trend)."""

    return {
        **_kpi(card_id, title, loops[0]),
        "kind": kind,
        "items": [
            {"asset_id": loop, "result": "linkcraft.loop_health", "label": loop} for loop in loops
        ],
        "agg": "last" if kind != "trend" else "mean",
        "width": 12,
        "height": 2 if kind == "gauge" else 3,
        **({"options": {"columns": ["last", "state"]}} if kind == "table" else {}),
    }


def _ranked(
    section_id: str, title: str, kinds: list[str], group_by: str, limit: int = 10
) -> dict[str, Any]:
    """An events section that counts the period's events by ``group_by`` and ranks the groups."""

    return {
        **_events(section_id, title, kinds, limit),
        "events": {"kinds": kinds, "limit": limit, "group_by": group_by},
    }


def _ranking(card_id: str, title: str, loops: list[str]) -> dict[str, Any]:
    """Analytics' health of ``loops`` as bars, the worst first, coloured by its band."""

    card = _health(card_id, title, loops, "bar")
    return {**card, "height": max(3, len(loops) // 2), "options": {"sort": "asc"}}


# Unit 100, the crude distillation unit, as the map has it: feed, heat exchange, furnaces and
# the column (12 of its 15 loops: a panel shows up to 12 signals).
U100_LOOPS = [
    "FIC-1001",
    "FIC-1007",
    "FIC-1112",
    "TIC-1009",
    "TIC-1111",
    "TIC-1104",
    "TIC-1209",
    "FIC-1210",
    "FIC-1101",
    "FIC-1102",
    "TIC-1213",
    "FIC-1214",
]
U100_LEVELS = ["LIC-1106", "LIC-1113", "LIC-1211"]
# The loops the weekly report follows: every loop with a known problem of the plant's two
# process units, the critical loops, and FIC-1001, the healthy reference.
WATCHED_LOOPS = [
    "FIC-1003",
    "FIC-1102",
    "FIC-1206",
    "FIC-1214",
    "PIC-1002",
    "PIC-1103",
    "PIC-1202",
    "TIC-1209",
    "LIC-1004",
    "TIC-1005",
    "AIC-1006",
    "FIC-1001",
]
VALVE_LOOPS = [
    "FIC-1003",
    "FIC-1102",
    "FIC-1206",
    "FIC-1214",
    "LIC-1004",
    "FIC-1109",
    "PIC-1207",
    "FIC-1219",
    "LIC-1113",
    "FIC-1001",
]
SENSOR_LOOPS = [
    "AIC-1006",
    "AIC-1108",
    "AIC-1205",
    "AIC-1215",
    "PIC-1008",
    "TIC-1111",
    "TIC-1209",
    "AIC-1224",
    "TIC-1114",
]
FINDINGS = ["linkcraft.finding.opened"]
ALARM_EVENTS = ["alarmcraft.alarm.raised", "alarmcraft.alarm.cleared", "alarmcraft.flood.started"]
RAISED = ["alarmcraft.alarm.raised"]

HEALTH_SCALE = (
    "Analytics rates every loop from **0 to 100** after each round of its methods: "
    "**75 and above** is healthy (green), **50 to 75** needs attention (amber) and "
    "**under 50** is a problem (red). The score is limited by the worst finding of the "
    "loop's methods, and the *Summary* column names that finding in words."
)

REPORTS: list[dict[str, Any]] = [
    {
        "name": "Control loops weekly performance",
        "description": "Which control loops had problems this week, which problems were the "
        "most frequent, the worst loops, and the valves with stiction, explained.",
        "folder": INSTRUMENTATION["name"],
        "period": "7d",
        "schedule": {"every": "week", "weekday": "mon", "at": "07:00"},
        "recipients": ["group:instrumentation", "group:process-engineering"],
        "sections": [
            _text(
                "summary",
                "Control loop performance, last 7 days",
                "This report reviews the control loops of **Riverbend Refinery** over the last "
                "seven days, as PlantCraft Analytics judged them. It answers four questions: "
                "*which loops had problems*, *which problems were the most frequent*, *which "
                "loop is the worst*, and *what should be done next*. Every table and chart is "
                "computed when the report is made; the text explains how to read them.\n\n"
                "### How loops are judged\n\n"
                + HEALTH_SCALE
                + "\n\nA **finding** opens when one method starts flagging a loop (for example "
                "*Possible valve stiction screening* or *Oscillation screening by "
                "autocorrelation*) and closes when the method stops flagging it. Counting the "
                "findings opened in the week shows where the problems come from; a loop whose "
                "finding opens and closes again and again has an intermittent problem, often "
                "worse than a steady one.",
            ),
            _text(
                "where",
                "Which loops had problems",
                "The table counts the findings opened this week **by loop**, the most first. "
                "*Share* is the loop's part of all the week's findings, *Latest* when its "
                "last finding opened and *Latest event* what Analytics said then. A colour bar "
                "marks the worst severity among its findings (red: bad, amber: warning).",
                2,
            ),
            _ranked("by-loop", "Findings opened this week, by loop", FINDINGS, "subject", 10),
            _text(
                "what",
                "The most frequent problems",
                "The same findings counted **by method**, that is by the kind of problem. "
                "A problem that appears on several loops usually has a common cause: a "
                "tuning practice (oscillation), a valve type or its maintenance (stiction), "
                "or an operating habit (manual mode).\n\n"
                "| Method | What it means | Usual fix |\n"
                "|---|---|---|\n"
                "| Oscillation screening by autocorrelation | The PV swings around its setpoint with a regular "
                "period | Lower the controller gain, check for a sticky valve or an interaction |\n"
                "| Possible valve stiction screening | The valve sticks, then jumps: the PV moves in steps "
                "| Valve maintenance; meanwhile a deadband or a stiction compensator |\n"
                "| Controller output saturation fraction | The controller output sits at a limit: the valve is too "
                "small or the setpoint unreachable | Resize the valve, review the setpoint |\n"
                "| Manual mode fraction | The loop spends long periods in manual | Ask "
                "operations why; retune or repair what makes them take it |\n"
                "| Sensor noise ratio | The measurement carries high-frequency noise | Filter "
                "the measurement, check the transmitter and its wiring |",
                2,
            ),
            _ranked(
                "by-problem",
                "Findings opened this week, by method",
                FINDINGS,
                "payload.method_id",
                10,
            ),
            _text(
                "worst",
                "The worst loops now",
                "The loops under watch ranked by their health **now**, the worst first: every "
                "loop with a known problem in units 100 and 200, the critical loops, and "
                "FIC-1001, a healthy loop kept for comparison. The table under it gives each "
                "loop's state and the finding that limits its score.",
                2,
            ),
            _card("ranking", _ranking("ranking", "Loop health now, worst first", WATCHED_LOOPS)),
            _card(
                "health-table",
                _health("health-table", "What limits each loop", WATCHED_LOOPS, "table"),
            ),
            _card(
                "week",
                {
                    **_health(
                        "week",
                        "Health of the problem loops over the week",
                        ["FIC-1003", "PIC-1202", "TIC-1209", "FIC-1001"],
                        "trend",
                    ),
                    "height": 3,
                },
            ),
            _text(
                "week-read",
                "",
                "**How to read the trend.** A line that stays under 50 is a steady problem "
                "(a sticky valve does not heal by itself). A line that dips and recovers is "
                "an intermittent one, often tied to the operation (a load change, a campaign). "
                "FIC-1001 should stay near the top: if it drops too, suspect the data before "
                "the loops.",
            ),
            {"section_id": "stiction-break", "kind": "break"},
            _text(
                "stiction",
                "Valve stiction",
                "**Stiction** (static friction) makes a control valve stick: the controller "
                "output (OP) keeps moving while the valve stays put, until the force is enough "
                "and the valve jumps. The process value (PV) then moves in steps instead of "
                "following the output smoothly, and the loop cycles around its setpoint "
                "even when it is well tuned. Stiction wears the valve and the process, and no "
                "retuning cures it: the valve needs maintenance.\n\n"
                "### How to see it\n\n"
                "- **OP against PV** (the scatter below): a healthy valve draws a cloud along "
                "a line; a sticky valve draws a parallelogram of flat steps, the OP moving "
                "while the PV does not.\n"
                "- **The trend**: a saw-tooth OP with a square-wave PV, at a steady period.\n\n"
                "### The valves Analytics suspects\n\n"
                "| Loop | Service | Criticality | What is seen |\n"
                "|---|---|---|---|\n"
                "| FIC-1003 | Recycle flow, U-200 | high | static friction, jumpy movement |\n"
                "| FIC-1102 | Reflux flow, U-100 | medium | stepwise valve movement |\n"
                "| FIC-1206 | Quench flow, U-200 | medium | friction and stepwise movement |\n"
                "| FIC-1214 | Side draw flow, U-100 | medium | static friction in the product "
                "valve |\n\n"
                "The chart under the scatters ranks the four by their health now; the "
                "*by method* table above says how often stiction was flagged this week.\n\n"
                "FIC-1003 is the clearest case: its scatter is shown next to the healthy "
                "FIC-1001 so the difference is visible.",
                2,
            ),
            _card(
                "stick",
                {
                    **_scatter("stick", "FIC-1003: OP against PV (flat steps)", "FIC-1003"),
                    "height": 3,
                },
                "half",
            ),
            _card(
                "healthy",
                {
                    **_scatter("healthy", "FIC-1001: OP against PV (healthy)", "FIC-1001"),
                    "height": 3,
                },
                "half",
            ),
            _card(
                "stick-trend",
                {
                    **_trend(
                        "stick-trend",
                        "FIC-1003 over the week: OP saw-tooth, PV steps",
                        "FIC-1003",
                        12,
                    ),
                    "height": 3,
                },
            ),
            _card(
                "stick-health",
                _ranking("stick-health", "Health of the suspected valves", STICTION_LOOPS),
            ),
            _text(
                "oscillation",
                "Oscillation",
                "An oscillating loop swings around its setpoint with a regular period. The "
                "usual cause is a controller tuned too hard (gain too high, integral time too "
                "short); a sticky valve or an interaction with another loop can cause it too. "
                "**PIC-1202** (reactor inlet pressure, U-200) and **PIC-1002** (vessel "
                "pressure) oscillate from aggressive tuning; the alarms on PIC-1202 come from "
                "these swings. Lowering the gain by a third and lengthening the integral time "
                "is the usual first step, watched for one shift.",
                2,
            ),
            _card("osc", {**_trend("osc", "PIC-1202 over the week", "PIC-1202", 12), "height": 3}),
            _text(
                "next",
                "Recommended actions",
                "1. **Valves with stiction** (FIC-1003 first, then FIC-1102, FIC-1206 and "
                "FIC-1214): plan the maintenance with instrumentation at the next opportunity; "
                "until then, keep the loops in automatic and accept the cycling.\n"
                "2. **PIC-1202 and PIC-1002**: retune (lower gain) and confirm the oscillation "
                "is gone in next week's report.\n"
                "3. **TIC-1209**: the temperature element drifts; check it against a hand-held "
                "reading and recalibrate.\n"
                "4. Any loop new to the first table: open it in Analytics and read its "
                "finding before the weekly meeting.\n\n"
                "*This report is made every Monday at 07:00 for instrumentation and process "
                "engineering. The counts cover the seven days up to the time it is made.*",
                2,
            ),
        ],
    },
    {
        "name": "Alarm summary, weekly",
        "description": "How the alarm system did this week against ISA-18.2 and EEMUA 191: the "
        "alarm load, the bad actors, the priorities and the floods, explained.",
        "folder": "Operation",
        "period": "7d",
        "schedule": {"every": "week", "weekday": "mon", "at": "08:00"},
        "recipients": ["group:u-100-operations", "group:u-200-operations", "user:marina.costa"],
        "sections": [
            _text(
                "summary",
                "Alarm system performance, last 7 days",
                "An alarm asks an operator to act. When there are too many, the important "
                "ones are lost among the rest, so plants measure their alarm system the way "
                "ISA-18.2 and EEMUA 191 describe. This report gives the week's alarm load, the "
                "**bad actors** (the few alarms that ring most), the mix of priorities and the "
                "floods, and says what to fix first.\n\n"
                "### The targets\n\n"
                "| Measure | Target | What it means |\n"
                "|---|---|---|\n"
                "| Average alarm rate | about 1 per 10 minutes per console (6 an hour, about "
                "1,000 a week) or less | above it the operator cannot respond to every alarm |\n"
                "| Floods | under 1% of the time | a flood is more than 10 alarms in 10 minutes |\n"
                "| Top 10 bad actors | a small share of all alarms | in a poor system they "
                "make half or more |\n"
                "| Priorities | about 80% low, 15% high, 5% critical | when everything is "
                "urgent, nothing is |",
            ),
            _text(
                "load",
                "The alarm load",
                "How many alarms were raised and cleared, and how many floods began. Compare "
                "the number raised with the target of about 1,000 a week per console; the "
                "raised and cleared counts should be close (an alarm raised and never "
                "cleared is a standing alarm).",
                2,
            ),
            _ranked("by-kind", "Alarm events this week", ALARM_EVENTS, "kind", 5),
            _text(
                "bad-actors",
                "Bad actors",
                "The alarms raised this week counted **by what they are about**, the most "
                "first. Fixing the top few (a wrong limit, a missing deadband, an oscillating "
                "loop behind them) usually removes a large part of the load. *Share* is the "
                "part of all alarms raised this week.",
                2,
            ),
            _ranked("by-subject", "Top 10 bad actors", RAISED, "subject", 10),
            _text(
                "priorities",
                "Priorities",
                "The same alarms by **priority**. Compare with the target mix: about 80% low, "
                "15% high and 5% critical. Too many high or critical alarms mean the "
                "priorities were not set by the consequence and the time to respond.",
                2,
            ),
            _ranked(
                "by-priority", "Alarms raised this week, by priority", RAISED, "payload.priority", 4
            ),
            _text(
                "behind",
                "Behind the top bad actor",
                "In this plant the pressure alarms of **PIC-1202** (reactor inlet, U-200) come "
                "from the loop itself: it oscillates from aggressive tuning, so its pressure "
                "crosses the alarm limit on every swing. Adding a deadband would hide the "
                "symptom; retuning the loop removes the cause. The trend shows the swings.",
                2,
            ),
            _card("pic", {**_trend("pic", "PIC-1202 over the week", "PIC-1202", 12), "height": 3}),
            _text("floods-head", "Floods and the latest alarms", "", 2),
            _events("floods", "Floods this week", ["alarmcraft.flood.started"], 10),
            _events("latest", "The latest alarms", RAISED, 15),
            _text(
                "next",
                "Recommended actions",
                "1. Review the **top three bad actors** with operations: is the limit right, "
                "does it need a deadband or an on-delay, is a loop behind it?\n"
                "2. Retune **PIC-1202** (see the *Control loops weekly performance* report).\n"
                "3. Review the priority of any alarm marked critical that rang more than once "
                "a day.\n\n"
                "*Made every Monday at 08:00 for the operations of units 100 and 200.*",
                2,
            ),
        ],
    },
    {
        "name": "U-100 daily report",
        "description": "The crude distillation unit's last 24 hours for the morning handover: "
        "throughput, furnaces, column, the loops and alarms of the day, explained.",
        "folder": "Operation",
        "period": "24h",
        "schedule": {"every": "day", "at": "06:00"},
        "recipients": ["group:u-100-operations", "user:marina.costa"],
        "sections": [
            _text(
                "summary",
                "Unit 100, the last 24 hours",
                "The daily report of **Unit 100**, the crude distillation unit, for the "
                "06:00 handover. It covers the 24 hours up to 06:00: the feed and the "
                "products, the furnaces, the column, the state of the unit's control loops "
                "and the alarms of the day. Values are the period's means unless a table says "
                "otherwise; a section that could not be read says so, and the rest of the "
                "report is still made.\n\n"
                "The unit has four areas: **Feed** (crude charge from TK-1001 by P-1001), "
                "**Heat exchange** (the feed/product exchanger E-1009), **Furnaces** (the "
                "atmospheric furnace F-1104) and **Distillation** (the column C-1101 with "
                "its overhead accumulator D-1106).",
            ),
            _text(
                "throughput",
                "Feed and throughput",
                "**FIC-1001** is the crude feed to the unit, **FIC-1007** the charge flow set "
                "by the campaign and **FIC-1112** the production flow. The feed should follow "
                "its setpoint closely; a gap between PV and SP that lasts means the pump or "
                "the valve cannot deliver.",
                2,
            ),
            _card("feed", {**_trend("feed", "Crude feed FIC-1001", "FIC-1001", 12), "height": 3}),
            _card(
                "flows",
                _pvs(
                    "flows",
                    "Feed and product flows (means of the day)",
                    ["FIC-1001", "FIC-1007", "FIC-1112", "FIC-1101"],
                ),
            ),
            _text(
                "furnace",
                "Furnaces",
                "The furnace heats the crude before the column. **TIC-1104** controls the "
                "furnace temperature by the fuel gas flow **FIC-1210**; **TIC-1209** measures "
                "the furnace outlet. TIC-1209's temperature element drifts slowly: if its "
                "value creeps away from TIC-1104 with the same firing, trust TIC-1104 and "
                "ask instrumentation to check the element.",
                2,
            ),
            _card(
                "furnace-trend",
                {
                    **_trend("furnace-trend", "Furnace temperature TIC-1104", "TIC-1104", 6),
                    "height": 3,
                },
                "half",
            ),
            _card(
                "outlet-trend",
                {**_trend("outlet-trend", "Furnace outlet TIC-1209", "TIC-1209", 6), "height": 3},
                "half",
            ),
            _text(
                "column",
                "Column",
                "The column separates the products. **FIC-1102** is the reflux, **TIC-1213** "
                "the top temperature that sets the product specification, and **FIC-1214** the "
                "side draw. FIC-1102 and FIC-1214 have valves that move in steps (stiction): "
                "a small, steady cycling on them is known and is in the weekly loop report.",
                2,
            ),
            _card(
                "column-table",
                _pvs(
                    "column-table",
                    "Column and levels, the day's range",
                    ["FIC-1102", "TIC-1213", "FIC-1214", *U100_LEVELS],
                    "table",
                ),
            ),
            _text(
                "loops",
                "The unit's control loops",
                HEALTH_SCALE + " Loops in amber or red are worth a word at the handover.",
                2,
            ),
            _card("ranking", _ranking("ranking", "Unit 100 loops, worst first", U100_LOOPS)),
            _card(
                "loops-table", _health("loops-table", "What limits each loop", U100_LOOPS, "table")
            ),
            _text(
                "alarms",
                "Alarms of the day",
                "The alarms raised in the 24 hours, counted by what they are about, then the "
                "latest of them. A unit in steady operation raises a few an hour at most.",
                2,
            ),
            _ranked("alarm-count", "Alarms raised, by what they are about", RAISED, "subject", 8),
            _events("alarm-list", "The latest alarms", ALARM_EVENTS[:2], 12),
            _text(
                "handover",
                "For the handover",
                "- Check any loop in red in the table above and say whether it was in manual.\n"
                "- Note any alarm that rang more than three times: it belongs in the weekly "
                "alarm review.\n"
                "- Write what the next shift must know in a Desk note.",
                2,
            ),
        ],
    },
    {
        "name": "Valve and instrument health, monthly",
        "description": "The month's view for maintenance planning: sticky and saturated "
        "valves, noisy and drifting measurements, ranked, with what each problem means.",
        "folder": INSTRUMENTATION["name"],
        "period": "30d",
        "schedule": {"every": "month", "day": 1, "at": "07:00"},
        "recipients": ["group:instrumentation"],
        "sections": [
            _text(
                "summary",
                "Valves and instruments, last 30 days",
                "Many loop problems are not tuning problems: a valve that sticks or cannot "
                "open enough, a transmitter that is noisy or drifts. Retuning does not fix "
                "them; maintenance does. This monthly report lists what Analytics found on "
                "the **final elements** (valves and actuators) and the **measurements** "
                "(transmitters and analyzers) over the last 30 days, so instrumentation can "
                "plan the work for the next maintenance window.\n\n" + HEALTH_SCALE,
            ),
            _text(
                "month",
                "Findings of the month",
                "Every finding Analytics opened in the 30 days, by method and then by loop. "
                "Over a month, a loop high in the second table with a valve or sensor problem "
                "is the first candidate for the maintenance list.",
                2,
            ),
            _ranked(
                "by-method",
                "Findings opened this month, by method",
                FINDINGS,
                "payload.method_id",
                10,
            ),
            _ranked("by-loop", "Findings opened this month, by loop", FINDINGS, "subject", 10),
            _text(
                "valves-about",
                "Valves and actuators",
                "Two valve problems matter most:\n\n"
                "- **Stiction**: the valve sticks, then jumps. The PV moves in steps and the "
                "loop cycles. Fix: repack or overhaul the valve; a positioner check first.\n"
                "- **Saturation**: the controller output sits at 0% or 100%. The valve is "
                "too small for the flow asked, or the actuator cannot reach its travel. Fix: "
                "check the actuator's supply and stroke; resize the valve if it is always "
                "fully open. **LIC-1004** (separator level) and **FIC-1109** (steam) show it.\n\n"
                "The chart ranks the valves under watch by their loop's health now.",
                2,
            ),
            _card("valves", _ranking("valves", "Valves under watch, worst first", VALVE_LOOPS)),
            _card(
                "valve-table",
                _health("valve-table", "What Analytics says of each valve", VALVE_LOOPS, "table"),
            ),
            _card(
                "saturation",
                {
                    **_trend(
                        "saturation",
                        "LIC-1004: the output pinned at its upper limit",
                        "LIC-1004",
                        12,
                    ),
                    "height": 3,
                },
            ),
            _text(
                "sensors-about",
                "Measurements and analyzers",
                "- **Noise**: high-frequency noise on a measurement makes the controller move "
                "the valve for nothing. Analyzers (the AIC loops) are the usual cases. Fix: "
                "check the sample system and the wiring; add a light filter.\n"
                "- **Drift**: a sensor that slowly moves away from the true value. The loop "
                "holds the wrong process value perfectly, so nothing looks wrong on the "
                "trend. Compare with a second measurement or a hand-held reading. "
                "**TIC-1209** (furnace outlet), **PIC-1008** (header pressure) and "
                "**AIC-1224** (effluent pH) are known to drift.",
                2,
            ),
            _card(
                "sensors",
                _ranking("sensors", "Measurements under watch, worst first", SENSOR_LOOPS),
            ),
            _card(
                "noise",
                {**_trend("noise", "AIC-1006: a noisy analyzer", "AIC-1006", 6), "height": 3},
                "half",
            ),
            _card(
                "drift",
                {**_trend("drift", "TIC-1209: a slow drift", "TIC-1209", 6), "height": 3},
                "half",
            ),
            _text(
                "plan",
                "For the maintenance plan",
                "1. Valves with stiction confirmed in this report and last month's: overhaul "
                "at the next window (FIC-1003 is the priority: high criticality).\n"
                "2. Saturated valves: check the actuator first; raise a resizing request only "
                "if the valve is fully open at normal throughput.\n"
                "3. Drifting sensors: recalibrate; noisy analyzers: inspect the sample "
                "system.\n\n"
                "*Made on the first day of each month at 07:00 for instrumentation.*",
                2,
            ),
        ],
    },
]

# Example reports of earlier demos, replaced by the four above (2026-10-27): the seed removes
# them where it made them, by name.
RETIRED_REPORTS = (
    "Plant overview, daily",
    "Loop detail, weekly",
    "Control room shift report",
    "Suite health weekly",
)


def view_reports(dash: Http) -> None:
    """The example reports, each made and sent once when it is created or rewritten, so
    Messages and the report's Sent tab show a PDF at once (after Alarms' replay: the alarm
    sections are full). A report of an earlier demo with the same name is rewritten (its
    description tells the editions apart); the retired examples are removed."""

    status, listed = dash.call("GET", "/api/reports", ok=(404,))
    if status == 404:
        return
    folders = _folders(dash)
    found = {item.get("name"): item for item in listed or []}
    for name in RETIRED_REPORTS:
        if name in found:
            dash.call("DELETE", f"/api/reports/{found[name]['report_id']}", ok=(403, 404))
            log(f"View: retired example report '{name}'")
    for spec in REPORTS:
        body = {key: value for key, value in spec.items() if key != "folder"}
        body["folder_id"] = folders.get(spec["folder"], "")
        old = found.get(spec["name"])
        if old is not None and old.get("description") == spec["description"]:
            continue
        if old is None:
            report = dash.post("/api/reports", body)["report_id"]
        else:
            report = old["report_id"]
            dash.put(f"/api/reports/{report}", body)
        status, run = dash.call("POST", f"/api/reports/{report}/send", ok=(422, 502, 503))
        sent = f", sent to {run.get('delivered', 0)} people" if status < 300 else ""
        log(f"View: report '{spec['name']}'{'' if old is None else ' (rewritten)'}{sent}")


# View's process display (2026-10-27): the whole plant on one page, every loop of the map drawn
# exactly once (deploy/demo/diagrams/*.json) --------------------------------------------------------

DIAGRAMS_FOLDER = "diagrams"
# The eight one-page diagrams earlier seeds made, now parts of "Riverbend plant".
OLD_DIAGRAMS = (
    "Riverbend Refinery",
    "Crude feed, preheat and furnace",
    "Atmospheric column",
    "Hydrotreater reactor loop",
    "Reaction and separation",
    "Amine treating and sulfur recovery",
    "Steam, cooling water and gases",
    "Effluent treatment and slop",
)


def _diagram_specs(suite: Suite) -> list[dict[str, Any]]:
    """The demo's process displays, one file each."""

    folder = suite.demo_map.parent / DIAGRAMS_FOLDER
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*.json"))]


# View's saved trends (well-named ones a visitor opens, not a test).
def _loop_lines(tag: str, *roles: str) -> list[dict[str, Any]]:
    return [
        {"signal_id": f"plantcraft:CPM.Loops.{tag}.{role}", "label": f"{tag} {role}"}
        for role in roles
    ]


VIEW_TRENDS: list[dict[str, Any]] = [
    {
        "name": "FIC-1003 sticky valve, last 12 h",
        "description": "Flow against setpoint over the valve output: the saw-tooth of stiction.",
        "plots": [
            {"title": "Recycle flow", "lines": _loop_lines("FIC-1003", "PV", "SP")},
            {"title": "Valve output", "lines": _loop_lines("FIC-1003", "OP")},
        ],
        "period": {"mode": "relative", "window": "12h"},
    },
    {
        "name": "PIC-1202 pressure oscillation",
        "description": "The 12-minute cycle behind the high-pressure alarm at every peak.",
        "plots": [
            {"title": "Pressure", "lines": _loop_lines("PIC-1202", "PV", "SP")},
            {"title": "Output", "lines": _loop_lines("PIC-1202", "OP")},
        ],
        "period": {"mode": "relative", "window": "6h"},
    },
    {
        "name": "Furnace outlets: TIC-1209 against TIC-1104",
        "description": "TIC-1209 drifts up while the twin furnace holds: a sensor, not the process.",
        "plots": [
            {
                "title": "Outlet temperatures",
                "lines": _loop_lines("TIC-1209", "PV") + _loop_lines("TIC-1104", "PV"),
            }
        ],
        "period": {"mode": "relative", "window": "24h"},
    },
]


TEST_TREND_NAMES = {"test", "teste", "new trend"}
RENAMED_TEST_TREND = "Control loop analysis"


def view_trends(dash: Http) -> None:
    """View's saved trends; run again, it adds only the missing ones."""

    listed = _items(dash.get("/api/trends"), "trends")
    # A test trend left on the demo gets a name a visitor understands.
    for item in listed:
        if str(item.get("name") or "").strip().lower() in TEST_TREND_NAMES:
            dash.put(f"/api/trends/{item['trend_id']}", {**item, "name": RENAMED_TEST_TREND})
            item["name"] = RENAMED_TEST_TREND
    kept = {item.get("name") for item in listed}
    for trend in VIEW_TRENDS:
        if trend["name"] not in kept:
            dash.post("/api/trends", {**trend, "step_seconds": None})
    log(f"View: {len(VIEW_TRENDS)} saved trends")


def view_diagrams(dash: Http, suite: Suite) -> None:
    """The process display of Riverbend Refinery in the Operation folder: the whole plant on one
    page, with the loops' values, health and mode on them. Created once (by name); the paged
    display and the one-page diagrams of earlier seeds give way to it."""

    status, listed = dash.call("GET", "/api/diagrams", ok=(404,))
    if status == 404:
        return
    specs = _diagram_specs(suite)
    if not specs:
        return
    operation = _folders(dash)["Operation"]
    kept = {item.get("name"): item for item in listed or []}
    for spec in specs:
        old = kept.get(spec["name"])
        if old is None:
            dash.post("/api/diagrams", {**spec, "folder_id": operation})
            log(f"View: process display '{spec['name']}'")
            continue
        # The paged demo display of earlier seeds becomes the one-page plant (2026-10-27); a
        # display someone redrew (no longer tagged demo, or already one page) is left alone.
        _, stored = dash.call("GET", f"/api/diagrams/{old['diagram_id']}", ok=(404,))
        if not stored or "demo" not in (stored.get("tags") or []):
            continue
        paged = len(stored.get("pages") or []) > len(spec.get("pages") or [])
        # The one-page display of 2026-10-27 had no parts: it gets the tabs (2026-10-28).
        partless = bool(spec.get("parts")) and not stored.get("parts")
        if not paged and not partless:
            continue
        dash.call(
            "PUT",
            f"/api/diagrams/{old['diagram_id']}",
            {
                **spec,
                "folder_id": stored.get("folder_id", operation),
                "base_updated_at": stored.get("updated_at"),
            },
            ok=(409,),
        )
        log(f"View: process display '{spec['name']}' redrawn on one page, with its parts")
    for item in listed or []:
        if item.get("name") in OLD_DIAGRAMS and "demo" in (item.get("tags") or []):
            dash.call("DELETE", f"/api/diagrams/{item['diagram_id']}", ok=(404,))
            log(f"View: old diagram '{item['name']}' replaced by its page")


# Analytics's model examples ------------------------------------------------------------------


def link_models(link: Http, suite: Suite) -> None:
    """The plant's model examples in Analytics (Furnaces, FIC-1001 and LIC-1010 process), calibrated
    on the archive's last hours, and run once now so their results are there at once."""

    examples = wait_until(
        "the plant's loops in Analytics",
        lambda: link.get("/api/models/examples"),
        suite.wait,
    )
    if any(not item.get("exists") for item in examples):
        created = link.post("/api/models/examples")
        waiting = [item["name"] for item in created if not item.get("calibrated")]
        log(
            f"Analytics: {len(created)} model examples"
            + (f" (not calibrated yet: {', '.join(waiting)})" if waiting else "")
        )
    for item in examples:
        link.post(f"/api/algorithms/{item['algorithm_id']}/run", ok=(404, 409, 502))


# PlantCraft Alarms --------------------------------------------------------------------------

ALARM_REPLAY_HOURS = 48
ALARM_OPERATOR = "marina.costa"
U100 = "group:u-100-operations"
U200 = "group:u-200-operations"
INSTRUMENTS = "group:instrumentation"
ON_CALL = "group:on-call"
PROCESS = "group:process-engineering"
SUPERVISOR = "user:marina.costa"
# The installation's own clock (Alarms resolves "local" where it is used).
PLANT_ZONE = "local"
DAY_SHIFT = [{"days": ["mon", "tue", "wed", "thu", "fri"], "start": "07:00", "end": "17:00"}]
TO_COORDINATOR = [{"after_minutes": 15, "recipients": ["coordinator"], "email": True}]
# The alarm a value rule shows from the start: PIC-1202's limit is the value its archived minutes
# of the last two days stay below this share of the time, so the replayed past holds its peaks.
PRESSURE_LOOP = "PIC-1202"
PRESSURE_QUANTILE = 0.98


# The example rules ("uns 5 alarmes, só para ter como exemplo"; round 11:
# one in Python too): what the apps report becomes an alarm only by a rule,
# and one rule covers a whole unit.
def _simple(*conditions: dict[str, Any], clear_after: float = 0.0) -> dict[str, Any]:
    """A rule's Simple form (Alarms round 11): its conditions, joined by and."""

    return {
        "editor": "simple",
        "simple": {"conditions": list(conditions), "clear_after_seconds": clear_after},
    }


def _event(kinds: list[str], *, about: str = "subject", **fields: Any) -> dict[str, Any]:
    severities = fields.pop("severities", [])
    event = {"kinds": kinds, "severities": severities, "about": about}
    return {"input": "event", "event": event, **fields}


ALARM_RULES: list[dict[str, Any]] = [
    {
        "name": "Analytics monitor failed",
        "creates": "notice",
        "priority": "high",
        "where": {},
        **_simple(
            _event(
                ["linkcraft.run.failed", "linkcraft.schedule.stalled"],
                about="any",
                test="count",
                count=1,
                window_minutes=120,
            )
        ),
        "owner": PROCESS,
        "discipline": "process",
        "notify": {"recipients": ["owner"], "group_seconds": 300, "repeat_minutes": 0},
        "cause": "An Analytics monitor could not run, or stopped running.",
        "consequence": "Its loops are not judged: a problem on them goes unseen.",
        "action": "Open the monitor's last run in Analytics and fix what it says.",
    },
    {
        "name": "Loop critical for over 1 h",
        "creates": "alarm",
        "priority": "medium",
        "where": {"under": ["U-100"]},
        **_simple(
            _event(
                ["linkcraft.status.changed"],
                severities=["critical"],
                test="open",
                for_seconds=3600,
            )
        ),
        "owner": PROCESS,
        "discipline": "process",
        "notify": {"recipients": ["owner"], "group_seconds": 300, "repeat_minutes": 240},
        "cause": "Analytics has found the loop critical for over an hour: not a one-off.",
        "consequence": "The loop keeps disturbing the unit (oscillation, a sticky valve).",
        "action": "Open the loop in Analytics, read the finding and plan the fix with the engineer.",
    },
    {
        "name": "PIC-1202 pressure high",
        "creates": "alarm",
        "priority": "high",
        "where": {"assets": [PRESSURE_LOOP]},
        # The limit and deadband are set from the archive (``_pressure_limit``).
        **_simple(
            {
                "input": "value",
                "value": {"role": "pv", "unit": ""},
                "op": ">=",
                "limit": None,
                "deadband": 0.0,
                "for_seconds": 30.0,
            },
            clear_after=60.0,
        ),
        "owner": U200,
        "discipline": "process",
        "notify": {
            "recipients": [U200],
            "email": True,
            "group_seconds": 120,
            "repeat_minutes": 60,
            "escalations": TO_COORDINATOR,
        },
        "cause": "The pressure loop oscillates: its peaks cross the limit.",
        "consequence": "Relief valve lifts; flaring and product loss.",
        "action": "Put PIC-1202 in manual at its average output and call the process engineer.",
    },
    {
        "name": "No data from the plant",
        "creates": "notice",
        "priority": "medium",
        "where": {"under": ["U-100"]},
        **_simple(_event(["histcraft.point.no_data"], test="open", for_seconds=600)),
        "owner": INSTRUMENTS,
        "discipline": "instrumentation",
        "notify": {
            "recipients": [INSTRUMENTS],
            "group_seconds": 600,
            "repeat_minutes": 0,
            "hours_mode": "inside",
            "hours": DAY_SHIFT,
            "timezone": PLANT_ZONE,
        },
        "cause": "A Unit 100 measurement sent nothing for 10 minutes.",
        "consequence": "Its loop and its alarms run blind.",
        "action": "Check the transmitter and the collector in Historian (Sources).",
    },
    {
        "name": "Loop finding open for a day",
        "creates": "notice",
        "priority": "low",
        "where": {"anywhere": True},
        **_simple(
            _event(
                ["linkcraft.finding.opened", "linkcraft.finding.closed"],
                test="open",
                for_seconds=24 * 3600,
            )
        ),
        "owner": INSTRUMENTS,
        "discipline": "instrumentation",
        "notify": {"recipients": ["owner"], "group_seconds": 600, "repeat_minutes": 0},
        "cause": "An Analytics finding on the loop (a sticking valve, an oscillation) is open for a day.",
        "consequence": "The loop cycles; the valve wears and the product varies.",
        "action": "Plan the loop's fix (valve packing, positioner, tuning) with instrumentation.",
    },
]


# The other way to write a rule (Alarms round 11): a Python block over a few values.
def _node(node_id: str, block: str, x: int, y: int, label: str = "", **parameters: Any) -> dict:
    return {
        "id": node_id,
        "block": block,
        "label": label or node_id,
        "x": x,
        "y": y,
        "parameters": parameters,
    }


def _wire(source: str, source_port: str, target: str, target_port: str) -> dict[str, str]:
    return {
        "source": source,
        "source_port": source_port,
        "target": target,
        "target_port": target_port,
    }


SATURATION_CODE = """def check(inputs):
    # A valve at its end (open or shut) while the loop is still far from its setpoint.
    if inputs.op is None or inputs.pv is None or inputs.sp is None:
        return False, ""
    far = abs(inputs.pv - inputs.sp) > 0.05 * max(abs(inputs.sp), 1.0)
    if inputs.op >= 98 and far:
        return True, f"valve wide open ({inputs.op:.0f} %), PV {inputs.pv:.4g} vs SP {inputs.sp:.4g}"
    if inputs.op <= 2 and far:
        return True, f"valve shut ({inputs.op:.0f} %), PV {inputs.pv:.4g} vs SP {inputs.sp:.4g}"
    return False, ""
"""
SATURATION_DIAGRAM = {
    "version": 2,
    "nodes": [
        _node("pv", "alarm.value", 0, 0, "pv", role="pv"),
        _node("sp", "alarm.value", 0, 150, "sp", role="sp"),
        _node("op", "alarm.value", 0, 300, "op", role="op"),
        _node("python", "alarm.python", 300, 150, "Python", code=SATURATION_CODE),
        _node("alarm", "alarm.raise", 600, 150, "Raise", clear_after_seconds=300.0),
    ],
    "edges": [
        _wire("pv", "value", "python", "values"),
        _wire("sp", "value", "python", "values"),
        _wire("op", "value", "python", "values"),
        _wire("python", "condition", "alarm", "condition"),
    ],
}
ALARM_RULES += [
    {
        "name": "U-100 measurement frozen",
        "creates": "notice",
        "priority": "low",
        "where": {"under": ["U-100"]},
        # A frozen value (owner's review, 2026-10-27: Blocks retired): did not change for 30 min.
        **_simple(
            {
                "input": "value",
                "value": {"role": "pv", "unit": "", "name": "PV"},
                "op": "unchanged",
                "for_seconds": 1800,
            },
            clear_after=60.0,
        ),
        "owner": INSTRUMENTS,
        "discipline": "instrumentation",
        "notify": {"enabled": False},
        "cause": "A Unit 100 PV has not moved for 30 minutes: a stuck transmitter or a frozen tag.",
        "consequence": "Its loop controls on a value that no longer follows the process.",
        "action": "Compare with the field reading and check the transmitter and its tag.",
    },
    {
        "name": "Valve saturated, loop off setpoint",
        "creates": "alarm",
        "priority": "medium",
        "where": {"under": ["U-100"]},
        "editor": "python",
        "diagram": SATURATION_DIAGRAM,
        "owner": PROCESS,
        "discipline": "process",
        "notify": {"recipients": ["owner"], "group_seconds": 300, "repeat_minutes": 240},
        "cause": "The valve is at its end and the loop still cannot reach its setpoint.",
        "consequence": "The loop has lost control: the unit runs off its target.",
        "action": "Check the valve's capacity and the setpoint; bypass or reduce the load.",
    },
]
ALARM_PHILOSOPHY: dict[str, Any] = {
    "statement": (
        "An alarm tells an operator of an abnormal situation that needs an action within the "
        "time its priority gives: critical at once, high within the hour, medium and low within "
        "the shift. Every alarm names its cause, its consequence and the action, and has one "
        "responsible. What needs no action is an alert. A rule that chatters or stands for more "
        "than a day is reviewed with its owner."
    ),
    "digest_times": ["07:00", "19:00"],
    "timezone": PLANT_ZONE,
}
ALARM_SILENCE = {
    "areas": ["U-300"],
    "minutes": 24 * 60,
    "reason": "Sulfur recovery train 2 in planned maintenance (permit 2291)",
}


def _pressure_limit(alarm: Http, suite: Suite) -> tuple[float, float]:
    """PIC-1202's high limit and deadband. From the archive's last two days, as the replay reads
    them (one value a minute), so the replayed past holds occurrences: the
    ``PRESSURE_QUANTILE`` of those values (a short archive: what it holds)."""

    archived = wait_until(
        f"{PRESSURE_LOOP}'s archive", lambda: _pressure_archive(suite) or None, suite.wait, 1.0
    )
    ordered = sorted(archived)
    limit = ordered[int(PRESSURE_QUANTILE * (len(ordered) - 1))]
    spread = ordered[int(0.75 * (len(ordered) - 1))] - ordered[int(0.25 * (len(ordered) - 1))]
    return float(f"{limit:.4g}"), float(f"{max(spread / 8, 1e-6):.3g}")


def _pressure_archive(suite: Suite) -> list[float]:
    """PIC-1202's PV over the replayed hours, one value a minute (empty when unreadable)."""

    try:
        admin = suite.session(suite.admin, suite.password)
        asset = admin.get(f"/api/assets/{PRESSURE_LOOP}") or {}
        signal = next(
            f"{item['source_id']}:{item['signal_id']}"
            for item in asset.get("signals") or []
            if item.get("role") == "pv"
        )
        end = time.time()
        answer = admin.post(
            "/api/v1/series",
            {
                "signals": [signal],
                "start": _iso(end - ALARM_REPLAY_HOURS * 3600),
                "end": _iso(end),
                "step": 60,
            },
        )
    except (SeedError, StopIteration, KeyError, TypeError):
        return []
    series = (answer or {}).get("series") or [{}]
    return [float(value) for value in series[0].get("v") or [] if isinstance(value, (int, float))]


def _iso(moment: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(moment))


def alarmcraft(alarm: Http, suite: Suite) -> None:
    """Seven example rules (what Analytics reports, a pressure limit, no data from Unit 100, a
    finding still open, a frozen measurement in Blocks, a saturated valve in Python), two days of
    the pressure alarm's past replayed from the archive (acknowledged by the shift supervisor) and
    a silence on U-300. Re-runnable: the rules are set back to the demo's."""

    have = {item["name"]: item for item in alarm.get("/api/rules") or []}
    for body in ALARM_RULES:
        body = dict(body)
        found = have.get(body["name"])
        first = ((body.get("simple") or {}).get("conditions") or [{}])[0]
        if first.get("input") == "value":
            before = ((found or {}).get("simple") or {}).get("conditions") or [{}]
            if before[0].get("limit") is not None:
                limit, deadband = before[0]["limit"], before[0].get("deadband") or 0.0
            else:
                limit, deadband = _pressure_limit(alarm, suite)
            body["simple"] = {
                **body["simple"],
                "conditions": [{**first, "limit": limit, "deadband": deadband}],
            }
        if found is None:
            alarm.post("/api/rules", body)
            log(f"Alarms: rule {body['name']}")
        else:
            alarm.put(
                f"/api/rules/{found['rule_id']}",
                {**body, "base_updated_at": found.get("updated_at")},
            )
    # The installation's alarm philosophy (Alarms 0.5+): the public targets, the plant's shifts.
    status, current = alarm.call("GET", "/api/philosophy", ok=(404,))
    if status == 200 and isinstance(current, dict) and not current.get("updated_by"):
        alarm.call("PUT", "/api/philosophy", {**current["defaults"], **ALARM_PHILOSOPHY})
        log("Alarms: alarm philosophy")
    status, _answer = alarm.call(
        "POST",
        "/api/history/replay",
        {"hours": ALARM_REPLAY_HOURS, "acknowledged_by": ALARM_OPERATOR},
        ok=(404, 405, 503),
    )
    if status == 202:
        state = wait_until(
            "Alarms' history replay",
            lambda: (lambda got: got if not got.get("running") else None)(
                alarm.get("/api/history/replay")
            ),
            max(suite.wait, BACKFILL_WAIT),
        )
        raised = sum(item.get("occurrences", 0) for item in (state.get("alarms") or {}).values())
        log(f"Alarms: {raised} occurrences of the last {ALARM_REPLAY_HOURS} hours replayed")
    if not any(item.get("active") for item in alarm.get("/api/silences") or []):
        alarm.post("/api/silences", ALARM_SILENCE)
        log(f"Alarms: silence on U-300 ({ALARM_SILENCE['reason']})")
    alarm.post("/api/run", ok=(409, 503))


# PlantCraft Models --------------------------------------------------------------------------

# (model, label): one run of each example with its own simulation settings, as Run on the
# model's page does (Executions groups them as the model's single runs).
MODEL_RUNS = [
    ("PlantCraftExamples.TankLevelControl", "Base case"),
    ("PlantCraftExamples.HeatExchangerOutlet", "Base case"),
    ("PlantCraftExamples.FirstOrderDeadTimeLoop", "Base case"),
]
# Grid studies the demo leaves ready to compare ("a tank of several sizes").
MODEL_STUDIES = [
    {
        "model": "PlantCraftExamples.TankLevelControl",
        "name": "Tank size",
        "description": "Which tank holds the level best through the setpoint and outlet steps: "
        "five cross-sections by three outlet valves.",
        "sweep": [
            {"name": "tank.A", "mode": "range", "start": 2, "stop": 6, "count": 5},
            {"name": "tank.Cv", "mode": "list", "values": [0.03, 0.05, 0.08]},
        ],
        "indicators": ["tank.level", "pump.speed"],
    },
    {
        "model": "PlantCraftExamples.HeatExchangerOutlet",
        "name": "Heat exchanger area",
        "description": "How much area cools the hot outlet enough after the hot flow rises.",
        "sweep": [{"name": "exchanger.A", "mode": "list", "values": [5, 10, 15, 20, 30]}],
        "indicators": ["exchanger.Th_out", "exchanger.duty"],
    },
]
# An optimization study (Models, 2026-10-26): the level controller's gain and integral time that
# follow the setpoint step with the least error, overshooting it by 5 % at most.
MODEL_OPTIMIZATION = {
    "model": "PlantCraftExamples.TankLevelControl",
    "name": "Tune the level controller",
    "description": "The gain and integral time that bring the tank's level to its new setpoint "
    "with the least error (IAE), overshooting it by 5 % at most. COBYLA, one simulation at a time.",
    "indicators": ["tank.level", "pump.speed"],
    "optimization": {
        "variables": [
            {"name": "controller.k", "start": 4, "min": 1, "max": 10},
            {"name": "controller.Ti", "start": 60, "min": 10, "max": 300},
        ],
        "objective": {"variable": "tank.level", "statistic": "iae", "goal": "minimize"},
        "constraints": [
            {"variable": "tank.level", "statistic": "overshoot", "op": "<=", "value": 5}
        ],
        "method": "cobyla",
        "max_simulations": 40,
    },
}
MODEL_FMU = "PlantCraftTwin.Furnaces"
MODEL_FMU_LABEL = "Furnaces for Analytics"
MODEL_PLANT_LABEL = "{loop} on the last hour"
# The loop a LoopProcess simulation is fed by, with its parameters in the Simulator (Analytics'
# FIC-1001 model example).
PLANT_LOOP = "FIC-1001"
PLANT_LOOP_PARAMETERS = {"K": 0.55, "tau": 110.0, "theta": 8.0, "y0": 55.0}
CALIBRATION_HOURS = 6


def _model_run(model: Http, project_id: str, kind: str, body: dict[str, Any], wait: float) -> Any:
    run = model.post(f"/api/projects/{project_id}/{kind}", body)
    return wait_until(
        f"Models: {body['model']} ({kind})",
        lambda: (
            lambda found: found if found["status"] in ("done", "failed", "cancelled") else None
        )(model.get(f"/api/runs/{run['id']}")),
        wait,
        every=4.0,
    )


def _settings(model: Http, project_id: str, name: str) -> dict[str, Any]:
    """The model's own simulation settings, as a study's start, stop, intervals and solver."""

    found = model.get(f"/api/models/{project_id}/{urllib.parse.quote(name, safe='')}")["settings"]
    start, stop = float(found["start"]), float(found["stop"])
    intervals = max(1, min(200_000, round((stop - start) / float(found["interval"]))))
    return {
        "start": start,
        "stop": stop,
        "intervals": intervals,
        "tolerance": found["tolerance"],
        "method": found["solver"],
    }


def _signal_of(platform: Http, source: dict[str, Any], cache: dict[str, Any]) -> str | None:
    if source.get("signal_id"):
        return source["signal_id"]
    asset = source.get("asset_id")
    if not asset:
        return None
    if asset not in cache:
        cache[asset] = platform.call(
            "GET", f"/api/v1/assets/{urllib.parse.quote(asset)}", ok=(404,)
        )[1]
    return ((cache[asset] or {}).get("signals") or {}).get(source.get("role") or "")


def _plant_run(platform: Http) -> tuple[str, dict[str, Any]] | None:
    """A simulation of FIC-1001's process model on the plant's last hour, compared with it."""

    cache: dict[str, Any] = {}
    valve = _signal_of(platform, {"asset_id": PLANT_LOOP, "role": "op"}, cache)
    measured = _signal_of(platform, {"asset_id": PLANT_LOOP, "role": "pv"}, cache)
    if not valve or not measured:
        return None
    end = time.time() - 60
    stamp = lambda moment: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(moment))  # noqa: E731
    return PLANT_LOOP, {
        "model": "PlantCraftTwin.LoopProcess",
        "start": 0,
        "stop": 3600,
        "intervals": 720,
        "overrides": {**PLANT_LOOP_PARAMETERS, "y_start": PLANT_LOOP_PARAMETERS["y0"]},
        "label": MODEL_PLANT_LABEL.format(loop=PLANT_LOOP),
        "plant": {
            "start": stamp(end - 3600),
            "end": stamp(end),
            "step": 5,
            "inputs": {"u": valve},
            "compare": {"y": measured},
        },
    }


def _model_study(model: Http, project_id: str, plan: dict[str, Any], wait: float) -> None:
    """A grid study, started once and followed until its simulations end."""

    body = {"model": plan["model"], **_settings(model, project_id, plan["model"])}
    body.update({key: value for key, value in plan.items() if key != "model"})
    study = model.post(f"/api/projects/{project_id}/studies", body)
    found = wait_until(
        f"Models: the study {plan['name']}",
        lambda: (lambda got: got if not got["queued"] and not got["running"] else None)(
            model.get(f"/api/studies/{study['id']}")
        ),
        wait,
        every=4.0,
    )
    log(f"Models: study '{plan['name']}', {found['done']} of {found['total']} simulations done")


def modelcraft(model: Http, suite: Suite, link: Http | None, platform: Http) -> None:
    """A run of each example diagram, one simulation on plant data, the grid studies "Tank size"
    and "Heat exchanger area" ready to compare, and the Furnaces FMU running in Analytics.
    Re-runnable: a run whose label is already there is not started again, nor a study."""

    wait_until(
        "the Modelica runner",
        lambda: model.get("/api/runner").get("available"),
        suite.wait,
        every=5.0,
    )
    projects = {item["name"]: item for item in model.get("/api/projects")}
    examples = projects.get("Examples")
    twins = projects.get("Analytics models")
    if not examples or not twins:
        raise SeedError("the example projects are missing in Models")
    done = {(run["model"], run.get("label")) for run in model.get("/api/runs?limit=1000")}
    for name, label in MODEL_RUNS:
        if (name, label) in done:
            continue
        run = model.post(
            f"/api/models/{examples['id']}/{urllib.parse.quote(name, safe='')}/run",
            {"label": label},
        )
        found = wait_until(
            f"Models: {name}",
            lambda run=run: (
                lambda got: got if got["status"] in ("done", "failed", "cancelled") else None
            )(model.get(f"/api/runs/{run['id']}")),
            suite.wait,
            every=4.0,
        )
        log(f"Models: {name} '{label}' {found['status']}")
    plan = _plant_run(platform)
    if plan and (plan[1]["model"], plan[1]["label"]) not in done:
        status, run = model.call(
            "POST", f"/api/projects/{twins['id']}/simulate", plan[1], ok=(422,)
        )
        if status == 422:
            log(f"Models: {plan[0]} on plant data skipped ({_detail(run)})")
        else:
            log(f"Models: LoopProcess fed by {plan[0]}'s last hour")
    studies = {item["name"] for item in model.get("/api/studies")}
    for plan_study in MODEL_STUDIES:
        if plan_study["name"] not in studies:
            _model_study(model, examples["id"], plan_study, suite.wait)
    if MODEL_OPTIMIZATION["name"] not in studies:
        # Started and left to the queue: it runs on while the seed goes on (a few minutes).
        body = {
            **_settings(model, examples["id"], MODEL_OPTIMIZATION["model"]),
            **MODEL_OPTIMIZATION,
        }
        status, answer = model.call(
            "POST", f"/api/projects/{examples['id']}/studies", body, ok=(422,)
        )
        log(
            f"Models: optimization '{MODEL_OPTIMIZATION['name']}' started"
            if status < 300
            else f"Models: optimization skipped ({_detail(answer)})"
        )
    fmu = next(
        (
            run
            for run in model.get("/api/runs?kind=fmu&limit=1000")
            if run.get("label") == MODEL_FMU_LABEL and run["status"] == "done"
        ),
        None,
    )
    if fmu is None:
        body = {"model": MODEL_FMU, "version": "2.0", "type": "cs", "label": MODEL_FMU_LABEL}
        fmu = _model_run(model, twins["id"], "fmu", body, suite.wait)
        if fmu["status"] != "done":
            raise SeedError(f"the {MODEL_FMU} FMU failed: {fmu.get('summary')}")
        log(f"Models: {MODEL_FMU} exported as an FMI 2.0 co-simulation FMU")


# Entry point ----------------------------------------------------------------------------------


# Documents ------------------------------------------------------------------------------------

# Where each kind of the demo documents goes: who reads them is the same for all (everyone).
DOC_FOLDERS = {
    "Operating manuals and procedures": ("Operating manual", "Procedure"),
    "Process control": ("Control narrative", "Troubleshooting guide", "P&ID", "Datasheet"),
    "Maintenance and incidents": ("Maintenance record", "Incident report"),
}


def doccraft(docs: Http, suite: Suite) -> None:
    """The Simulator plant's documents (deploy/demo/documents): manuals, control narratives,
    troubleshooting guide, maintenance history, incidents, each linked to its assets. A document
    whose number is already in the library is left as it is."""

    folder = suite.demo_map.parent / "documents"
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    folders = {item["name"]: item["folder_id"] for item in docs.get("/api/folders") or []}
    for name in DOC_FOLDERS:
        if name not in folders:
            folders[name] = docs.post("/api/folders", {"name": name})["folder_id"]
    present = {item["number"] for item in docs.get("/api/documents") or []}
    sent = 0
    for item in manifest["documents"]:
        if item["number"] in present:
            continue
        place = next((name for name, kinds in DOC_FOLDERS.items() if item["kind"] in kinds), "")
        fields = {
            "filename": item["file"],
            "folder": folders.get(place, ""),
            "number": item["number"],
            "title": item["title"],
            "kind": item["kind"],
            "unit": item.get("unit", ""),
            "language": item.get("language", ""),
            "revision": item.get("revision", ""),
            "issued": item.get("date", ""),
        }
        query = urllib.parse.urlencode({key: value for key, value in fields.items() if value})
        raw = (folder / item["file"]).read_bytes()
        doc = docs.post(f"/api/documents?{query}", raw=raw, content_type="application/octet-stream")
        if item.get("assets"):
            docs.put(f"/api/documents/{doc['doc_id']}/assets", {"assets": item["assets"]})
        sent += 1
    log(f"documents: {sent} sent, {len(present)} already there; reading them takes a minute")


def run(suite: Suite) -> int:
    log(f"PlantCraft at {suite.processcraft}")
    admin = wait_until(
        "PlantCraft",
        lambda: suite.session(suite.admin, suite.password),
        suite.wait,
    )
    plant_map(admin, suite)
    archive_signals(admin, suite)
    passwords = people(admin, suite)
    groups(admin, suite.admin)
    workspace = _workspace()
    retire_specialist(admin, workspace)
    steps = [
        (
            "histcraft",
            lambda client, _suite: (
                histcraft(client, _suite),
                histcraft_lab(client),
                histcraft_import(client),
                histcraft_calc(client),
            ),
        ),
        ("linkcraft", linkcraft),
        ("dashcraft", lambda client, _suite: dashcraft(client)),
        ("linkcraft", link_models),
        ("alarmcraft", alarmcraft),
        ("dashcraft", lambda client, _suite: view_reports(client)),
        ("dashcraft", lambda client, _suite: view_trends(client)),
        ("dashcraft", view_diagrams),
        (
            "modelcraft",
            lambda client, _suite: modelcraft(
                client,
                _suite,
                suite.app(admin, "linkcraft"),
                Http(suite.processcraft, token=admin.post("/api/v1/auth/token")["token"]),
            ),
        ),
        ("doccraft", doccraft),
    ]
    failed = []
    for app_id, step in steps:
        client = suite.app(admin, app_id)
        if client is None:
            log(f"{app_id} is not installed: skipped")
            continue
        try:
            step(client, suite)
        except SeedError as error:
            failed.append(app_id)
            log(f"WARNING {app_id}: {error}")
    # What the team wrote, last: it links what the apps now hold (Links).
    links = story_links(suite, admin)
    if workspace is None:
        log("PlantCraft's past skipped: run the seed inside the PlantCraft container")
    else:
        written = past(workspace, suite.admin, links=links)
        log(
            f"PlantCraft's past: {written['actions']} actions and "
            f"{written['conversations']} conversations of the last three weeks"
        )
        made = assistant_and_notebooks(workspace, admin, suite.admin, links)
        log(f"Notifications: {visitor_alarms(workspace)} from the apps for the visitor")
        log(f"Desk: {made['chats']} assistant chats, {made['notebooks']} notebooks of loop data")
    started = conversations(suite, passwords, links, workspace)
    actions(suite, passwords, links)
    follow_ups(started, links)
    if workspace is not None:
        chat_sources(workspace, links)
    desk(suite, passwords, workspace, links)
    team_day(suite, passwords)
    if workspace is not None:
        log(f"Messages: {visitor_unread(workspace)} unread for the visitor")
        log(f"guides by role: {guide_links(workspace, suite, admin, links)} pages they open")
    log(f"links: {len(links.refs)} documents, dashboards, reports, chats, actions and talks")
    log(
        f"done. The read-only visitor account is '{VISITOR}' (the sign-in page offers it"
        " only on a public demo, install.sh --public-demo)"
        + (f"; failed: {', '.join(failed)}" if failed else "")
    )
    return 1 if failed else 0


def _apps_from_env(default_host: bool) -> dict[str, str]:
    """Where each app answers: the compose service names, or PLANTCRAFT_DEMO_<APP>_URL."""

    services = {
        "linkcraft": "http://linkcraft:8140/link",
        "dashcraft": "http://dashcraft:8080/dash",
        "histcraft": "http://histcraft:8100/hist",
        "alarmcraft": "http://alarmcraft:8110/alarm",
        "modelcraft": "http://modelcraft:8130/model",
        "doccraft": "http://doccraft:8150/doc",
    }
    installed = {
        entry.split("=", 1)[0].strip()
        for entry in os.environ.get("PLANTCRAFT_APPS", "").split(",")
        if "=" in entry
    }
    apps = {}
    for app_id, url in services.items():
        override = os.environ.get(f"PLANTCRAFT_DEMO_{app_id.upper()}_URL")
        if override:
            apps[app_id] = override
        elif app_id in installed and default_host:
            apps[app_id] = url
    return apps


def _password(args: argparse.Namespace) -> str:
    if args.password_file:
        return Path(args.password_file).read_text(encoding="utf-8").strip()
    password = os.environ.get("PLANTCRAFT_PASSWORD") or os.environ.get(
        "PLANTCRAFT_BASIC_AUTH_PASSWORD", ""
    )
    file = os.environ.get("PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE")
    if not password and file and Path(file).is_file():
        password = Path(file).read_text(encoding="utf-8").strip()
    if not password:
        raise SeedError("no administrator password: --password-file or PLANTCRAFT_PASSWORD")
    return password


def _demo_map(args: argparse.Namespace) -> Path:
    candidates = [args.map] if args.map else []
    here = Path(__file__).resolve().parents[1]
    candidates += [here / "deploy" / "demo" / DEMO_MAP, Path("/app/deploy/demo") / DEMO_MAP]
    for path in candidates:
        if path and Path(path).is_file():
            return Path(path)
    raise SeedError(f"{DEMO_MAP} not found (--map)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="processcraft demo seed",
        description="Fill a fresh installation with the Simulator demo story (idempotent).",
    )
    parser.add_argument(
        "--url", default=os.environ.get("PLANTCRAFT_DEMO_URL", "http://127.0.0.1:8060")
    )
    parser.add_argument(
        "--admin", default=os.environ.get("PLANTCRAFT_BASIC_AUTH_USERNAME", "admin")
    )
    parser.add_argument("--password-file")
    parser.add_argument(
        "--visitor-password",
        default=os.environ.get("PLANTCRAFT_PUBLIC_DEMO_PASSWORD") or "plantcraft-demo",
        help="Password of the read-only visitor account 'demo'.",
    )
    parser.add_argument("--map", type=Path)
    parser.add_argument("--wait", type=float, default=600.0, help="Seconds to wait for each app.")
    parser.add_argument(
        "--app",
        action="append",
        default=[],
        metavar="ID=URL",
        help="Where an app answers, e.g. linkcraft=http://127.0.0.1:8140/link (repeatable).",
    )
    args = parser.parse_args(argv)
    try:
        apps = _apps_from_env(default_host=not args.app)
        for entry in args.app:
            app_id, _, url = entry.partition("=")
            apps[app_id.strip()] = url.strip()
        suite = Suite(
            processcraft=args.url,
            apps=apps,
            admin=args.admin,
            password=_password(args),
            visitor_password=args.visitor_password,
            demo_map=_demo_map(args),
            wait=args.wait,
        )
        return run(suite)
    except SeedError as error:
        print(f"[demo] ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
