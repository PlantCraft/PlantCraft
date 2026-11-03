"""The cast: ten people in their groups, the read-only visitor and the retired valve specialist."""

from __future__ import annotations

import secrets
from typing import Any

from .base import VISITOR, Http, Suite, _items, log


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
