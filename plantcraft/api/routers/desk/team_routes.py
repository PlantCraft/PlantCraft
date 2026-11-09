"""Desk's team page: a group leader's board, people, assignments and handovers."""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import HTTPException, Query
from pydantic import BaseModel, Field

from plantcraft.actions import STATUSES as ACTION_STATUSES
from plantcraft.api.deps import CurrentUser, Runtime, action_visibility, is_admin, open_to
from plantcraft.api.routers.desk.common import (
    DAY,
    _bad,
    _with_refs,
    followed_assets,
    own_events,
    router,
)
from plantcraft.config import plant_today
from plantcraft.db import utc_text
from plantcraft.i18n import t

# Team -----------------------------------------------------------------------------------------


BOARD_STATUSES = ("open", "in_progress", "blocked")
HANDOVER_DAYS = 7


def _led_groups(rt: Any, user: str) -> set[str]:
    """The groups ``user`` leads, and every group under them."""

    led: set[str] = set()
    for group in rt.workspace.groups.list():
        if group["coordinator"] == user:
            led |= rt.workspace.groups.descendants(group["group_id"])
    return led


def availability(rt: Any, username: str, day: date, now: str) -> str:
    """``away`` (an all-day event of theirs today), ``busy`` (one going on now) or ``""``;
    the event itself stays private."""

    state = ""
    for event in own_events(rt, username, day, day):
        if event["all_day"]:
            return "away"
        if event["start"] <= now < event["end"]:
            state = "busy"
    return state


def handover_ref(group_id: str, day: str) -> str:
    return f"handover:{group_id}:{day}"


def _managed_groups(rt: Any, user: str) -> set[str]:
    """The groups whose team ``user`` sees and manages: those they lead and, for an
    administrator, every group (round 8: the admin checks how every team is doing)."""

    if is_admin(rt, user):
        return {item["group_id"] for item in rt.workspace.groups.list()}
    return _led_groups(rt, user)


def _team_group(rt: Any, user: str, group_id: str) -> tuple[dict[str, Any], bool]:
    """The group, when ``user`` is in it, leads it (or a group above it) or is an
    administrator; and whether they manage it."""

    group = rt.workspace.groups.get(group_id)
    managed = _managed_groups(rt, user)
    member = group is not None and any(item["username"] == user for item in group["members"])
    if group is None or not (member or group_id in managed):
        raise HTTPException(status_code=404, detail=t("Group not found."))
    return group, group_id in managed


def _team_board(rt: Any, user: str) -> list[dict[str, Any]]:
    """The not-done actions ``user`` sees, the material of every group's board."""

    return rt.workspace.actions.list(
        statuses=list(BOARD_STATUSES), visible=action_visibility(rt, user), limit=5000
    )


def _group_board(
    actions: list[dict[str, Any]], group_id: str, usernames: set[str]
) -> list[dict[str, Any]]:
    """A group's actions: those given to the group, and those of its people given to no group."""

    return [
        action
        for action in actions
        if action.get("group_id") == group_id
        or (not action.get("group_id") and action.get("owner") in usernames)
    ]


def _team_people(
    rt: Any,
    user: str,
    group: dict[str, Any],
    board: list[dict[str, Any]],
    today: date,
    now: str,
) -> list[dict[str, Any]]:
    """A group's active people: leader first, then by name, each with whether they are away or
    busy (their calendar, without saying why) and how many of the board's actions they hold
    and have late."""

    today_iso = today.isoformat()
    people = []
    for item in group["members"]:
        if not item["active"]:
            continue
        owned = [action for action in board if action.get("owner") == item["username"]]
        people.append(
            {
                "username": item["username"],
                "display_name": item["display_name"],
                "leader": item["username"] == group["coordinator"],
                "you": item["username"] == user,
                "availability": availability(rt, item["username"], today, now),
                "open": len(owned),
                "late": sum(
                    1
                    for action in owned
                    if (action.get("due_at") or "")[:10] < today_iso and action.get("due_at")
                ),
            }
        )
    people.sort(key=lambda item: (not item["leader"], item["display_name"].lower()))
    return people


def _team_overview(
    rt: Any, user: str, groups: list[dict[str, Any]], managed: set[str]
) -> list[dict[str, Any]]:
    """Every group the person sees at a glance (``?group=all``): its people and how they are,
    and how many actions it has open and late."""

    today = date.fromisoformat(plant_today())
    today_iso = today.isoformat()
    now = utc_text()
    actions = _team_board(rt, user)
    found = []
    for group in groups:
        usernames = {item["username"] for item in group["members"] if item["active"]}
        board = _group_board(actions, group["group_id"], usernames)
        people = _team_people(rt, user, group, board, today, now)
        found.append(
            {
                "group_id": group["group_id"],
                "name": group["name"],
                "kind_label": group["kind_label"],
                "leader": group["group_id"] in managed,
                "coordinator_name": group.get("coordinator_name"),
                "people": people,
                "open": len(board),
                "late": sum(
                    1
                    for action in board
                    if action.get("due_at") and action["due_at"][:10] < today_iso
                ),
                "away": sum(1 for person in people if person["availability"] == "away"),
                "busy": sum(1 for person in people if person["availability"] == "busy"),
            }
        )
    return found


@router.get("/api/desk/team")
def team(
    user: CurrentUser,
    rt: Runtime,
    group: Annotated[str | None, Query(max_length=80)] = None,
) -> dict[str, Any]:
    """How one of the person's groups is doing today and who can take what: its people (role,
    away or busy, open and late actions), its actions as a board, the week ahead, the shift
    handover notes, the assets its people follow that are in alarm, and its shared lists.
    Every member sees it; a leader (and an administrator, who sees every group) also moves
    the board's cards to someone else. ``group=all`` (the default with more than one group)
    answers every group at a glance instead (``overview``)."""

    managed = _managed_groups(rt, user)
    mine = {item["group_id"] for item in rt.workspace.groups.of(user)}
    visible = [item for item in rt.workspace.groups.list() if item["group_id"] in mine | managed]
    # The person's own groups first, then those they see as a leader or an administrator.
    visible.sort(key=lambda item: item["group_id"] not in mine)
    choices = [
        {
            "group_id": item["group_id"],
            "name": item["name"],
            "kind_label": item["kind_label"],
            "leader": item["group_id"] in managed,
            "mine": item["group_id"] in mine,
        }
        for item in visible
    ]
    if not choices:
        return {"groups": [], "group": None, "overview": None}
    if group == "all" or (group is None and len(choices) > 1):
        return {
            "groups": choices,
            "group": None,
            "overview": _team_overview(rt, user, visible, managed),
        }
    chosen = next((item for item in choices if item["group_id"] == group), choices[0])
    current, leader = _team_group(rt, user, chosen["group_id"])
    group_id = current["group_id"]
    today = date.fromisoformat(plant_today())
    today_iso = today.isoformat()
    week_end = (today + timedelta(days=6)).isoformat()
    now = utc_text()
    members = [item for item in current["members"] if item["active"]]
    usernames = {item["username"] for item in members}
    board = _group_board(_team_board(rt, user), group_id, usernames)
    people = _team_people(rt, user, current, board, today, now)
    cards = [
        {
            "action_id": action["action_id"],
            "title": action["title"],
            "status": action["status"],
            "status_label": action["status_label"],
            "priority": action["priority"],
            "priority_label": action["priority_label"],
            "owner": action.get("owner"),
            "owner_name": action.get("owner_name"),
            "due_at": (action.get("due_at") or "")[:10] or None,
            "late": bool(action.get("due_at")) and action["due_at"][:10] < today_iso,
            "href": f"/actions/{action['action_id']}",
        }
        for action in board
    ]
    cards.sort(key=lambda item: (item["due_at"] or "9999", item["action_id"]))
    agenda: list[dict[str, Any]] = [
        {
            "day": card["due_at"],
            "kind": "action",
            "title": card["title"],
            "who": card["owner_name"],
            "href": card["href"],
            "late": card["late"],
        }
        for card in cards
        if card["due_at"] and card["due_at"] <= week_end
    ]
    for todo in rt.desk.todos(user, [group_id], done=False, due_to=week_end):
        day = todo["due"]
        if todo["group_id"] == group_id and day and day <= week_end:
            agenda.append(
                {
                    "day": max(day, today_iso),
                    "kind": "todo",
                    "title": todo["title"],
                    "who": None,
                    "href": f"/todo?list={todo['list_id']}&item={todo['todo_id']}"
                    if todo["list_id"]
                    else f"/todo?view=all&item={todo['todo_id']}",
                    "late": day < today_iso,
                }
            )
    for item in members:
        for event in own_events(rt, item["username"], today, today + timedelta(days=6)):
            if event["all_day"]:
                agenda.append(
                    {
                        "day": max(event["start"][:10], today_iso),
                        "kind": "away",
                        "title": t("{name} away", name=item["display_name"]),
                        "who": item["display_name"],
                        "href": None,
                        "late": False,
                    }
                )
    agenda.sort(key=lambda item: (item["day"], item["kind"] != "away", item["title"]))
    # A leader or an administrator reads the handovers of the group they look at, too.
    groups_of_user = sorted(mine | {group_id})
    handovers = []
    prefix = f"handover:{group_id}:"
    for note in rt.desk.notes(user, groups_of_user):
        ref = note.get("event_ref") or ""
        if ref.startswith(prefix):
            handovers.append(
                {
                    "day": ref[len(prefix) :],
                    "note_id": note["note_id"],
                    "title": note["title"],
                    "snippet": note["body_text"][:160],
                    "updated_at": note["updated_at"],
                }
            )
    handovers.sort(key=lambda item: item["day"], reverse=True)
    alarms: dict[str, dict[str, Any]] = {}
    for item in members:
        for asset in followed_assets(rt, item["username"]):
            if asset["status"] in ("alarm", "warning") and asset["ref"] not in alarms:
                alarms[asset["ref"]] = {**asset, "followers": []}
            if asset["ref"] in alarms:
                alarms[asset["ref"]]["followers"].append(item["display_name"])
    open_todos = Counter(
        todo["list_id"]
        for todo in rt.desk.todos(user, [group_id], done=False)
        if todo["group_id"] == group_id
    )
    lists = [
        {**item, "open": open_todos.get(item["list_id"], 0)}
        for item in rt.desk.todo_lists(user, [group_id])
        if item["group_id"] == group_id
    ]
    return {
        "groups": choices,
        "overview": None,
        "group": {
            "group_id": group_id,
            "name": current["name"],
            "kind_label": current["kind_label"],
            "leader": leader,
            "coordinator_name": current.get("coordinator_name"),
            "day": today_iso,
            "people": people,
            "board": cards,
            "statuses": [
                {"id": status, "label": t(ACTION_STATUSES[status])} for status in BOARD_STATUSES
            ],
            "agenda": agenda[:100],
            "handover": next((item for item in handovers if item["day"] == today_iso), None),
            "handovers": handovers[:HANDOVER_DAYS],
            "assets": sorted(
                alarms.values(), key=lambda item: (item["status"] != "alarm", item["name"])
            ),
            "lists": lists,
        },
    }


class AssignIn(BaseModel):
    action_id: int = Field(ge=1)
    owner: str | None = Field(default=None, max_length=60)
    status: str | None = Field(default=None, max_length=20)


@router.post("/api/desk/team/{group_id}/assign")
def assign(group_id: str, body: AssignIn, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """A leader moves a card of the group's board: to another of its people (or to the group,
    with no owner) or to another status."""

    group, leader = _team_group(rt, user, group_id)
    if not leader:
        raise HTTPException(status_code=403, detail=t("Only the group's leaders move its cards."))
    action = rt.workspace.actions.get(body.action_id)
    if action is None or not action_visibility(rt, user).sees(action):
        raise HTTPException(status_code=404, detail=t("Action not found."))
    members = {item["username"] for item in group["members"] if item["active"]}
    owner = body.owner if "owner" in body.model_fields_set else action.get("owner")
    if owner and owner not in members:
        raise HTTPException(status_code=422, detail=t("{name} is not in the group.", name=owner))
    status = body.status or action["status"]
    if status not in BOARD_STATUSES:
        raise HTTPException(status_code=422, detail=t("Pick open, in progress or blocked."))
    try:
        updated, _previous = rt.workspace.actions.update(
            body.action_id,
            actor=user,
            title=action["title"],
            description=action.get("description") or "",
            priority=action["priority"],
            status=status,
            owner=owner or None,
            group_id=action.get("group_id") or (None if owner else group_id),
            due_at=action.get("due_at"),
            refs=action.get("refs") or [],
        )
    except ValueError as exc:
        raise _bad(exc) from exc
    return {
        "action_id": updated["action_id"],
        "owner": updated.get("owner"),
        "status": updated["status"],
    }


@router.post("/api/desk/team/{group_id}/handover")
@open_to("viewer")
def handover(
    group_id: str,
    user: CurrentUser,
    rt: Runtime,
    day: Annotated[str | None, Query(pattern=DAY)] = None,
) -> dict[str, Any]:
    """The group's shift handover note for a day (today by default): a note shared with the
    group that whoever comes in reads; made by the first who opens it."""

    group, _leader = _team_group(rt, user, group_id)
    when = day or plant_today()
    ref = handover_ref(group_id, when)
    groups = [item["group_id"] for item in rt.workspace.groups.of(user)]
    found = rt.desk.notes(user, groups, event_ref=ref)
    if found:
        return _with_refs(rt, user, rt.desk.note(found[0]["note_id"]))
    label = date.fromisoformat(when).strftime("%b %d").replace(" 0", " ")
    try:
        made = rt.desk.create_note(
            user,
            title=t("Handover · {group} · {day}", group=group["name"], day=label),
            shared=[f"group:{group_id}"],
            event_ref=ref,
        )
    except ValueError as exc:
        raise _bad(exc) from exc
    return _with_refs(rt, user, made)
