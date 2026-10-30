"""Desk: each person's day (docs/desk.md). Their to-dos and lists, the assets they follow,
their calendar (own events, actions, to-dos, alarms on followed assets, the apps'
scheduled runs and calendars read from elsewhere), the day's suggestions and, for
a group leader, their team.

Everything here is the person's own: a reader (viewer) keeps their own to-dos and calendar
too (``open_to("viewer")``). Actions, conversations and results are read through the stores
that own them, with the person's own sight of them.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from plantcraft.actions import OPEN_STATUSES
from plantcraft.actions import STATUSES as ACTION_STATUSES
from plantcraft.api.deps import (
    AdminUser,
    CurrentUser,
    Runtime,
    UserAccess,
    action_visibility,
    is_admin,
    marks_owner,
    open_to,
)
from plantcraft.api.feed import visit_reads
from plantcraft.api.routers.messages import _resolve, present_ref
from plantcraft.auth.suite import app_access
from plantcraft.config import plant_today
from plantcraft.db import utc_text
from plantcraft.desk import (
    FEED_MINUTES,
    CalendarError,
    feed_url,
    occurrences,
    parse_ics,
    read_feed,
    repeats,
    suggest,
    todo_due,
    todo_repeats,
)
from plantcraft.i18n import t
from plantcraft.refs import parse_ref

router = APIRouter()

DAY = r"^\d{4}-\d{2}-\d{2}$"
# The calendar answers for two months at most at once (a month view with its edges).
# The calendar's widest view is a year (round 8), with the days of the weeks around it.
MAX_SPAN_DAYS = 380


def _today(day: str | None) -> date:
    if not day:
        return date.fromisoformat(plant_today())
    try:
        return date.fromisoformat(day)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=t("The day must be a date (YYYY-MM-DD).")
        ) from exc


def _bad(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


def _my_groups(rt: Any, user: str) -> list[str]:
    return [group["group_id"] for group in rt.workspace.groups.of(user)]


def _worst(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    rank = {"alarm": 3, "warning": 2, "unknown": 1, "ok": 0}
    worst: dict[str, dict[str, Any]] = {}
    for result in results:
        current = worst.get(result["subject"])
        if current is None or rank.get(result["status"], 0) > rank.get(current["status"], 0):
            worst[result["subject"]] = result
    return worst


def _open_refs(rt: Any, user: str) -> Counter[str]:
    """Open actions per item, of those ``user`` sees (another group's do not count)."""

    counts: Counter[str] = Counter()
    found = rt.workspace.actions.list(
        statuses=list(OPEN_STATUSES), visible=action_visibility(rt, user), limit=5000
    )
    for action in found:
        counts.update(set(action["refs"]))
    return counts


def followed_assets(rt: Any, user: str) -> list[dict[str, Any]]:
    """The assets the person follows with their worst current result and open actions."""

    # An asset that left the person's asset scope is no longer followed (docs/asset-scope.md).
    scope = rt.asset_scope(user)
    refs = [ref for ref in rt.desk.follows(user) if scope.subject(ref)]
    if not refs:
        return []
    now = utc_text()
    current = [
        item
        for item in rt.workspace.results.results(subjects=refs, apps=rt.apps_for(user))
        if not item.get("expires_at") or item["expires_at"] > now
    ]
    worst = _worst(current)
    open_refs = _open_refs(rt, user)
    items = []
    for ref in refs:
        resolved = present_ref(_resolve(rt, ref, user))
        result = worst.get(ref)
        items.append(
            {
                "ref": ref,
                "name": resolved.get("title") or ref.split(":", 1)[-1],
                "kind_label": resolved.get("kind_label"),
                "href": resolved.get("href"),
                "exists": resolved.get("exists"),
                "subject": ref,
                "status": result["status"] if result else "unknown",
                "summary": result["summary"] if result else "",
                "app": result["app"] if result else None,
                "kind": result["kind"] if result else None,
                "at": result["at"] if result else None,
                "open_actions": open_refs.get(ref, 0),
            }
        )
    return items


# Today ----------------------------------------------------------------------------------------


@router.get("/api/desk/today")
def today(
    request: Request,
    user: CurrentUser,
    rt: Runtime,
    day: Annotated[str | None, Query(pattern=DAY)] = None,
) -> dict[str, Any]:
    """What the Overview's Desk widgets read at once: the day's to-dos (My day), the person's
    open actions by due date, the assets they follow and the day's suggestions."""

    when = _today(day)
    seen = action_visibility(rt, user)
    mine = rt.workspace.actions.list(
        statuses=list(OPEN_STATUSES), visible=seen, view="mine", limit=500
    )
    followed = followed_assets(rt, user)
    owner = marks_owner(request, rt, user)
    conversations = rt.workspace.messages.list_for(user, limit=50, read_upto=visit_reads(rt, owner))
    triage = rt.desk.triage(owner)
    iso = when.isoformat()
    overdue = [item for item in mine if item.get("due_at") and item["due_at"][:10] < iso]
    due_today = [item for item in mine if item.get("due_at") and item["due_at"][:10] == iso]
    return {
        "day": iso,
        "todos": _today_todos(rt, user, when),
        "actions": {"open": len(mine), "overdue": len(overdue), "today": len(due_today)},
        "followed": followed,
        "suggestions": suggest(
            username=user,
            today=when,
            actions=mine,
            followed=followed,
            conversations=conversations,
            triage=triage,
        ),
        "unread": sum(int(item.get("unread") or 0) for item in conversations),
    }


# To-do ----------------------------------------------------------------------------------------


class TodoIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    list_id: int | None = None
    due: str | None = Field(default=None, pattern=DAY)
    repeat: str = Field(default="", max_length=20)
    days: list[Annotated[int, Field(ge=0, le=6)]] = Field(default_factory=list, max_length=7)
    my_day: bool = False
    notes: str = Field(default="", max_length=2000)
    steps: list[dict[str, Any]] = Field(default_factory=list, max_length=30)


class TodoChange(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    list_id: int | None = None
    due: str | None = Field(default=None, pattern=DAY)
    repeat: str | None = Field(default=None, max_length=20)
    days: list[Annotated[int, Field(ge=0, le=6)]] | None = Field(default=None, max_length=7)
    my_day: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)
    steps: list[dict[str, Any]] | None = Field(default=None, max_length=30)
    done: bool | None = None
    position: int | None = None


class ListIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    group_id: str | None = Field(default=None, max_length=60)
    color: str | None = Field(default=None, max_length=20)


class ListChange(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    color: str | None = Field(default=None, max_length=20)


class TodoAction(BaseModel):
    owner: str | None = Field(default=None, max_length=60)
    group_id: str | None = Field(default=None, max_length=60)


def _leads(rt: Any, user: str) -> set[str]:
    """Groups whose shared lists this person sets up: those they lead and every group below."""

    return set(rt.workspace.groups.scope(user)["led"])


def _list_for(rt: Any, user: str, list_id: int | None) -> dict[str, Any] | None:
    """A list the person may put to-dos in (theirs or one of their groups'); None for their
    own to-dos outside any list. 404 for a list they cannot see."""

    if list_id is None:
        return None
    item = rt.desk.todo_list(list_id)
    if item is None or not (
        item["owner"] == user or (item["group_id"] and item["group_id"] in _my_groups(rt, user))
    ):
        raise HTTPException(status_code=404, detail=t("List not found."))
    return item


def _may_set_up(rt: Any, user: str, item: dict[str, Any]) -> bool:
    """Who renames or deletes a list: its owner; for a group's, its leaders and admins."""

    if item.get("owner"):
        return item["owner"] == user
    return is_admin(rt, user) or item.get("group_id") in _leads(rt, user)


def _todo_for(rt: Any, user: str, todo_id: int) -> dict[str, Any]:
    item = rt.desk.todo(todo_id)
    if item is None or not (
        (item["group_id"] is None and item["username"] == user)
        or (item["group_id"] and item["group_id"] in _my_groups(rt, user))
    ):
        raise HTTPException(status_code=404, detail=t("To-do not found."))
    return item


def _today_todos(rt: Any, user: str, day: date) -> list[dict[str, Any]]:
    """My day: what is due by ``day`` (late ones too) or was picked for it, and what was done
    on it."""

    iso = day.isoformat()
    groups = _my_groups(rt, user)
    open_ = [
        item
        for item in rt.desk.todos(user, groups, done=False)
        if (item["due"] and item["due"] <= iso) or item["my_day"] == iso
    ]
    done = [
        item
        for item in rt.desk.todos(user, groups, done=True, limit=200)
        if (item["done_at"] or "")[:10] == iso or item["due"] == iso
    ]
    return open_ + done


def _app_names(rt: Any) -> dict[str, str]:
    return {item.id: item.name for item in rt.suite_apps()}


def app_feeds(rt: Any, apps: dict[str, str]) -> dict[str, dict[str, Any]]:
    """The calendar feeds the apps a person opens declared (``[[contributes.calendar]]``), by
    ``<app>:<feed>``, in the suite's order."""

    names = _app_names(rt)
    found: dict[str, dict[str, Any]] = {}
    for row in rt.contributions.listing(list(apps)):
        for feed in (row.get("contributes") or {}).get("calendar", []):
            found[f"{row['app']}:{feed['id']}"] = {
                "id": f"{row['app']}:{feed['id']}",
                "app": row["app"],
                "app_name": names.get(row["app"], row["app"]),
                "title": feed["title"],
                "description": feed.get("description") or "",
                "visible": feed.get("visible", True),
            }
    return found


def app_todos(rt: Any, user: str, access: Any, *, done: bool = False) -> list[dict[str, Any]]:
    """The to-dos the apps a person opens gave them or their groups, with the app's name and
    the kind's title."""

    apps = app_access(access, rt.suite_apps())
    names = _app_names(rt)
    kinds = {
        (row["app"], kind["id"]): kind["title"]
        for row in rt.contributions.listing(list(apps))
        for kind in (row.get("contributes") or {}).get("todo", [])
    }
    group_names = {group["group_id"]: group["name"] for group in rt.workspace.groups.list()}
    items = rt.app_items.todos_for(
        user, _my_groups(rt, user), apps=set(apps), done=done, limit=50 if done else 500
    )
    out = []
    for item in items:
        target_kind, _, target = item["for"].partition(":")
        out.append(
            {
                **item,
                "app_name": names.get(item["app"], item["app"]),
                "kind_title": kinds.get((item["app"], item["kind"]), item["kind"]),
                "group_name": group_names.get(target) if target_kind == "group" else None,
            }
        )
    return out


@router.get("/api/desk/todos")
def todos(
    user: CurrentUser,
    rt: Runtime,
    access: UserAccess,
    view: Annotated[str, Query(pattern=r"^(today|planned|all|done|list|apps)$")] = "today",
    list_id: int | None = None,
) -> dict[str, Any]:
    """The person's to-dos: ``today`` (My day: due by today, picked for today, done today, with
    the day's actions and events beside them), ``planned`` (with a date), ``all`` (open),
    ``done``, one ``list`` or ``apps`` (what the apps asked of them, ``app_todos``). The lists
    come along, with what each holds open."""

    groups = _my_groups(rt, user)
    when = date.fromisoformat(plant_today())
    lists = rt.desk.todo_lists(user, groups)
    names = {group["group_id"]: group["name"] for group in rt.workspace.groups.list()}
    open_items = rt.desk.todos(user, groups, done=False)
    counts = Counter(item["list_id"] for item in open_items)
    from_apps = app_todos(rt, user, access)
    out: dict[str, Any] = {
        "day": when.isoformat(),
        "view": view,
        "repeats": todo_repeats(),
        "lists": [
            {
                **item,
                "group_name": names.get(item["group_id"] or ""),
                "open": counts.get(item["list_id"], 0),
                "editable": _may_set_up(rt, user, item),
            }
            for item in lists
        ],
        "counts": {
            "today": sum(1 for item in _today_todos(rt, user, when) if not item["done"]),
            "planned": sum(1 for item in open_items if item["due"]),
            "all": len(open_items),
            "inbox": counts.get(None, 0),
            "apps": len(from_apps),
        },
        "groups": [
            {"group_id": group_id, "name": names.get(group_id, group_id)}
            for group_id in sorted(set(groups) | _leads(rt, user))
            if is_admin(rt, user) or group_id in _leads(rt, user)
        ],
    }
    if view == "today":
        items = _today_todos(rt, user, when)
        iso = when.isoformat()
        seen = action_visibility(rt, user)
        out["actions"] = [
            {
                "action_id": action["action_id"],
                "title": action["title"],
                "due_at": action["due_at"],
                "href": f"/actions/{action['action_id']}",
                "late": action["due_at"][:10] < iso,
            }
            for action in rt.workspace.actions.list(
                statuses=list(OPEN_STATUSES), visible=seen, view="mine", limit=500
            )
            if action.get("due_at") and action["due_at"][:10] <= iso
        ]
        out["events"] = own_events(rt, user, when, when)
        out["app_todos"] = [item for item in from_apps if item["due"] and item["due"] <= iso]
    elif view == "apps":
        items = []
        out["app_todos"] = from_apps + app_todos(rt, user, access, done=True)
    elif view == "planned":
        items = sorted(
            (item for item in open_items if item["due"]),
            key=lambda item: (item["due"], item["position"]),
        )
    elif view == "done":
        items = rt.desk.todos(user, groups, done=True, limit=200)
    elif view == "list":
        items = [item for item in open_items if item["list_id"] == list_id] + [
            item
            for item in rt.desk.todos(user, groups, done=True, limit=200)
            if item["list_id"] == list_id
        ][:50]
    else:
        items = open_items
    out["items"] = items
    return out


@router.post("/api/desk/todos", status_code=201)
@open_to("viewer")
def create_todo(body: TodoIn, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    target = _list_for(rt, user, body.list_id)
    try:
        return rt.desk.create_todo(
            title=body.title,
            username=None if target and target["group_id"] else user,
            group_id=target["group_id"] if target else None,
            list_id=body.list_id,
            actor=user,
            due=body.due,
            repeat=body.repeat,
            days=body.days,
            my_day=body.my_day,
            notes=body.notes,
            steps=body.steps,
        )
    except ValueError as exc:
        raise _bad(exc) from exc


class AppTodoDone(BaseModel):
    done: bool


@router.post("/api/desk/app-todos/{app}/{key:path}")
@open_to("viewer")
def complete_app_todo(
    app: str, key: str, body: AppTodoDone, user: CurrentUser, rt: Runtime, access: UserAccess
) -> dict[str, Any]:
    """A to-do an app gave the person (or their group), ticked or unticked; the app reads it
    back in ``GET /api/v1/todos``."""

    item = rt.app_items.todo(app, key)
    reaches = item is not None and (
        item["for"] == f"user:{user}"
        or item["for"] in {f"group:{group}" for group in _my_groups(rt, user)}
    )
    if not reaches or app not in app_access(access, rt.suite_apps()):
        raise HTTPException(status_code=404, detail=t("No such to-do."))
    return rt.app_items.complete(app, key, body.done, user) or {}


@router.patch("/api/desk/todos/{todo_id}")
@open_to("viewer")
def change_todo(todo_id: int, body: TodoChange, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """Only the fields sent change (``due: null`` takes the date away, ``list_id: null`` moves
    it out of every list). ``done`` on a repeated to-do moves it to its next day."""

    _todo_for(rt, user, todo_id)
    change = body.model_dump(include=body.model_fields_set)
    done = change.pop("done", None)
    for key in ("title", "repeat", "days", "my_day", "notes", "steps", "position"):
        if key in change and change[key] is None:
            change.pop(key)
    if "list_id" in change:
        target = _list_for(rt, user, change["list_id"])
        change["group_id"] = target["group_id"] if target else None
        change["username"] = None if change["group_id"] else user
    try:
        item = rt.desk.update_todo(todo_id, change)
        if done is not None:
            item = rt.desk.complete_todo(todo_id, done, user)
    except ValueError as exc:
        raise _bad(exc) from exc
    return item or {}


@router.delete("/api/desk/todos/{todo_id}")
@open_to("viewer")
def delete_todo(todo_id: int, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    _todo_for(rt, user, todo_id)
    rt.desk.delete_todo(todo_id)
    return {"deleted": todo_id}


@router.post("/api/desk/todos/{todo_id}/action", status_code=201)
def todo_to_action(
    todo_id: int, body: TodoAction, user: CurrentUser, rt: Runtime
) -> dict[str, Any]:
    """A to-do that needs someone else becomes an action (its notes and steps in the
    description, its date as the due date); the to-do is done and points to it."""

    from plantcraft.api.routers.actions import ActionDraft, create_action

    item = _todo_for(rt, user, todo_id)
    lines = [item["notes"]] if item["notes"] else []
    lines += [f"- [{'x' if step['done'] else ' '}] {step['text']}" for step in item["steps"]]
    action = create_action(
        ActionDraft(
            title=item["title"],
            description="\n".join(lines)[:4000],
            owner=body.owner if body.owner is not None else (None if body.group_id else user),
            group_id=body.group_id,
            due_at=item["due"],
        ),
        user,
        rt,
    )
    rt.desk.link_action(todo_id, action["action_id"], user)
    return {
        "todo_id": todo_id,
        "action_id": action["action_id"],
        "href": f"/actions/{action['action_id']}",
    }


@router.post("/api/desk/todo-lists", status_code=201)
@open_to("viewer")
def create_list(body: ListIn, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """A list of the person's own or, for a group's leader, a list the group shares."""

    if body.group_id:
        if rt.workspace.groups.get(body.group_id) is None:
            raise HTTPException(status_code=422, detail=t("Group not found."))
        if not (is_admin(rt, user) or body.group_id in _leads(rt, user)):
            raise HTTPException(
                status_code=403, detail=t("Only the group's leader sets up its shared lists.")
            )
    try:
        return rt.desk.create_list(
            name=body.name,
            owner=None if body.group_id else user,
            group_id=body.group_id,
            color=body.color,
            actor=user,
        )
    except ValueError as exc:
        raise _bad(exc) from exc


def _own_list(rt: Any, user: str, list_id: int) -> dict[str, Any]:
    item = _list_for(rt, user, list_id) or {}
    if not _may_set_up(rt, user, item):
        raise HTTPException(
            status_code=403, detail=t("Only the group's leader sets up its shared lists.")
        )
    return item


@router.patch("/api/desk/todo-lists/{list_id}")
@open_to("viewer")
def change_list(list_id: int, body: ListChange, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    _own_list(rt, user, list_id)
    try:
        return rt.desk.update_list(list_id, name=body.name, color=body.color) or {}
    except ValueError as exc:
        raise _bad(exc) from exc


@router.delete("/api/desk/todo-lists/{list_id}")
@open_to("viewer")
def delete_list(list_id: int, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    _own_list(rt, user, list_id)
    rt.desk.delete_list(list_id)
    return {"deleted": list_id}


# Notes ----------------------------------------------------------------------------------------


class NoteIn(BaseModel):
    title: str = Field(default="", max_length=200)
    body: dict[str, Any] = Field(default_factory=dict)
    text: str = Field(default="", max_length=100_000)
    shared: list[Annotated[str, Field(max_length=80)]] = Field(default_factory=list, max_length=50)
    event_ref: str | None = Field(default=None, max_length=200)


class NoteChange(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    body: dict[str, Any] | None = None
    text: str | None = Field(default=None, max_length=100_000)
    shared: list[Annotated[str, Field(max_length=80)]] | None = Field(default=None, max_length=50)
    pinned: bool | None = None
    event_ref: str | None = Field(default=None, max_length=200)


def _check_shares(rt: Any, shared: list[str]) -> None:
    for item in shared:
        kind, _, name = item.partition(":")
        known = (
            rt.workspace.users.is_person(name)
            if kind == "user"
            else kind == "group" and rt.workspace.groups.get(name) is not None
        )
        if not known:
            raise HTTPException(
                status_code=422, detail=t("{name} is not a person or a group.", name=item)
            )


def _note_for(rt: Any, user: str, note_id: int) -> dict[str, Any]:
    note = rt.desk.note(note_id)
    if note is None or not rt.desk.note_visible(note, user, _my_groups(rt, user)):
        raise HTTPException(status_code=404, detail=t("Note not found."))
    return note


def _present_note(rt: Any, user: str, note: dict[str, Any]) -> dict[str, Any]:
    names = {item["username"]: item["display_name"] for item in rt.workspace.users.list_users()}
    groups = {group["group_id"]: group["name"] for group in rt.workspace.groups.list()}
    shared = [
        {
            "ref": item,
            "name": (names if item.startswith("user:") else groups).get(
                item.split(":", 1)[1], item
            ),
        }
        for item in note.get("shared") or []
    ]
    return {
        **note,
        "mine": note["owner"] == user,
        "owner_name": names.get(note["owner"], note["owner"]),
        "shared": shared,
    }


@router.get("/api/desk/notes")
def notes(
    user: CurrentUser,
    rt: Runtime,
    q: Annotated[str, Query(max_length=200)] = "",
    event: Annotated[str | None, Query(max_length=200)] = None,
) -> dict[str, Any]:
    """The person's notes and those shared with them (no bodies), pinned first; ``q`` searches
    titles and text, ``event`` finds a calendar event's note."""

    items = rt.desk.notes(user, _my_groups(rt, user), q=q, event_ref=event)
    return {
        "items": [
            {**_present_note(rt, user, item), "body_text": item["body_text"][:160]}
            for item in items
        ]
    }


def note_mentions(body: Any) -> list[str]:
    """The ``#`` mentions written in a note's body (Tiptap ``mention`` nodes), in order."""

    found: list[str] = []
    stack = [body]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if node.get("type") == "mention":
                ref = str((node.get("attrs") or {}).get("id") or "")
                if ref and ref not in found:
                    found.append(ref)
            stack.extend(reversed(node.get("content") or []))
    return found[:100]


def _with_refs(rt: Any, user: str, note: dict[str, Any]) -> dict[str, Any]:
    return {
        **_present_note(rt, user, note),
        "refs": [present_ref(_resolve(rt, ref, user)) for ref in note_mentions(note.get("body"))],
    }


@router.get("/api/desk/notes/{note_id}")
def note(note_id: int, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    return _with_refs(rt, user, _note_for(rt, user, note_id))


@router.post("/api/desk/notes", status_code=201)
@open_to("viewer")
def create_note(body: NoteIn, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """A note, private unless ``shared`` names people (``user:ana``) or groups (``group:x``)."""

    _check_shares(rt, body.shared)
    try:
        made = rt.desk.create_note(
            user,
            title=body.title,
            body=body.body,
            text=body.text,
            shared=body.shared,
            event_ref=body.event_ref,
        )
    except ValueError as exc:
        raise _bad(exc) from exc
    return _with_refs(rt, user, made)


@router.patch("/api/desk/notes/{note_id}")
@open_to("viewer")
def change_note(note_id: int, body: NoteChange, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """Whoever sees a note writes in it; only its owner shares it, pins it or ties it to an
    event."""

    current = _note_for(rt, user, note_id)
    change = {key: value for key, value in body.model_dump(include=body.model_fields_set).items()}
    if current["owner"] != user and {"shared", "pinned", "event_ref"} & set(change):
        raise HTTPException(status_code=403, detail=t("Only the note's owner shares it."))
    if change.get("shared") is not None:
        _check_shares(rt, change["shared"])
    if change.get("body") is None:
        change.pop("body", None)
        change.pop("text", None)
    try:
        updated = rt.desk.update_note(note_id, change, user)
    except ValueError as exc:
        raise _bad(exc) from exc
    return _with_refs(rt, user, updated or current)


@router.delete("/api/desk/notes/{note_id}")
@open_to("viewer")
def delete_note(note_id: int, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    current = _note_for(rt, user, note_id)
    if current["owner"] != user:
        raise HTTPException(status_code=403, detail=t("Only the note's owner deletes it."))
    rt.desk.delete_note(note_id)
    return {"deleted": note_id}


# Followed assets ------------------------------------------------------------------------------


class FollowIn(BaseModel):
    ref: str = Field(min_length=3, max_length=400)


@router.get("/api/desk/follows")
def follows(
    user: CurrentUser, rt: Runtime, ref: Annotated[str | None, Query(max_length=400)] = None
) -> dict[str, Any]:
    """The assets the person follows, worst first; with ``ref``, only whether they follow it."""

    if ref is not None:
        return {"ref": ref, "following": ref in rt.desk.follows(user)}
    rank = {"alarm": 0, "warning": 1, "unknown": 2, "ok": 3}
    items = sorted(
        followed_assets(rt, user), key=lambda item: (rank.get(item["status"], 2), item["name"])
    )
    return {"items": items}


@router.put("/api/desk/follows")
@open_to("viewer")
def follow(body: FollowIn, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    try:
        ref = str(parse_ref(body.ref))
    except ValueError as exc:
        raise _bad(exc) from exc
    if not ref.startswith("asset:"):
        raise HTTPException(status_code=422, detail=t("Only assets can be followed."))
    if not rt.asset_scope(user).subject(ref):
        raise HTTPException(status_code=404, detail=t("Asset not found."))
    try:
        rt.desk.follow(user, ref)
    except ValueError as exc:
        raise _bad(exc) from exc
    return {"ref": ref, "following": True}


@router.delete("/api/desk/follows")
@open_to("viewer")
def unfollow(
    user: CurrentUser, rt: Runtime, ref: Annotated[str, Query(min_length=3, max_length=400)]
) -> dict[str, Any]:
    rt.desk.unfollow(user, ref)
    return {"ref": ref, "following": False}


# Calendars ------------------------------------------------------------------------------------


class CalendarIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # The text of an .ics file, or a published calendar link.
    ics: str | None = Field(default=None, max_length=2_000_000)
    url: str | None = Field(default=None, max_length=2000)


def _public_calendar(item: dict[str, Any]) -> dict[str, Any]:
    keep = ("calendar_id", "name", "kind", "color", "fetched_at", "error", "count")
    found = {key: item.get(key) for key in keep}
    if "events" in item:
        found["count"] = len(item["events"])
    # A published link carries a secret token in its path: never shown again in full.
    if item.get("url"):
        found["host"] = item["url"].split("/")[2] if "//" in item["url"] else ""
    return found


@router.get("/api/desk/calendars")
def calendars(user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    return {
        "items": [_public_calendar(item) for item in rt.desk.calendars(user)],
        "links": rt.desk.settings()["calendar_links"],
    }


@router.post("/api/desk/calendars", status_code=201)
@open_to("viewer")
def add_calendar(body: CalendarIn, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    if bool(body.ics) == bool(body.url):
        raise HTTPException(
            status_code=422, detail=t("Import an .ics file or give a calendar link.")
        )
    try:
        if body.ics:
            events = parse_ics(body.ics)
            created = rt.desk.add_calendar(
                user, name=body.name, kind="file", url=None, events=events
            )
        else:
            settings = rt.desk.settings()
            if not settings["calendar_links"]:
                raise HTTPException(
                    status_code=403,
                    detail=t(
                        "An administrator has not turned on calendar links. Import an .ics file instead."
                    ),
                )
            link = feed_url(body.url or "")
            events = parse_ics(read_feed(link, settings["hosts"]))
            created = rt.desk.add_calendar(
                user, name=body.name, kind="url", url=link, events=events
            )
    except ValueError as exc:
        raise _bad(exc) from exc
    return _public_calendar(created)


def _refresh(rt: Any, user: str, calendar: dict[str, Any], *, force: bool = False) -> None:
    """A calendar link read again when it is older than 15 minutes (or ``force``)."""

    if calendar.get("kind") != "url" or not calendar.get("url"):
        return
    fetched = calendar.get("fetched_at")
    if not force and fetched:
        try:
            moment = datetime.fromisoformat(fetched)
            if datetime.now(moment.tzinfo) - moment < timedelta(minutes=FEED_MINUTES):
                return
        except ValueError:
            pass
    settings = rt.desk.settings()
    if not settings["calendar_links"]:
        rt.desk.set_events(
            calendar["calendar_id"], None, t("An administrator has turned calendar links off.")
        )
        return
    try:
        rt.desk.set_events(
            calendar["calendar_id"], parse_ics(read_feed(calendar["url"], settings["hosts"]))
        )
    except CalendarError as exc:
        rt.desk.set_events(calendar["calendar_id"], None, str(exc))


@router.post("/api/desk/calendars/{calendar_id}/refresh")
@open_to("viewer")
def refresh_calendar(calendar_id: int, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    calendar = rt.desk.calendar(user, calendar_id)
    if calendar is None:
        raise HTTPException(status_code=404, detail=t("Calendar not found."))
    _refresh(rt, user, calendar, force=True)
    return _public_calendar(rt.desk.calendar(user, calendar_id) or calendar)


@router.delete("/api/desk/calendars/{calendar_id}")
@open_to("viewer")
def delete_calendar(calendar_id: int, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    if not rt.desk.delete_calendar(user, calendar_id):
        raise HTTPException(status_code=404, detail=t("Calendar not found."))
    return {"deleted": calendar_id}


# Own events -----------------------------------------------------------------------------------


class EventIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    start: str = Field(min_length=10, max_length=40)
    end: str | None = Field(default=None, max_length=40)
    all_day: bool = False
    repeat: str = Field(default="", max_length=20)
    until: str | None = Field(default=None, pattern=DAY)
    notes: str = Field(default="", max_length=2000)


class EventChange(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    start: str | None = Field(default=None, min_length=10, max_length=40)
    end: str | None = Field(default=None, max_length=40)
    all_day: bool | None = None
    repeat: str | None = Field(default=None, max_length=20)
    until: str | None = Field(default=None, pattern=DAY)
    notes: str | None = Field(default=None, max_length=2000)


@router.get("/api/desk/events/{event_id}")
def own_event(event_id: int, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    event = rt.desk.event(user, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail=t("Event not found."))
    return {**event, "repeats": repeats()}


@router.post("/api/desk/events", status_code=201)
@open_to("viewer")
def create_event(body: EventIn, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """An event of the person's own: once, or repeated every day, on weekdays, every week or
    every month (until a day, or with no end)."""

    try:
        return rt.desk.create_event(user, **body.model_dump())
    except ValueError as exc:
        raise _bad(exc) from exc


@router.patch("/api/desk/events/{event_id}")
@open_to("viewer")
def change_event(
    event_id: int, body: EventChange, user: CurrentUser, rt: Runtime
) -> dict[str, Any]:
    """Only the fields sent change; ``until: null`` lets a repeat go on with no end. Moving or
    resizing one time of a repeat moves the whole series (the calendar sends the series' new
    start and end)."""

    change = body.model_dump(include=body.model_fields_set)
    for key in ("title", "start", "all_day", "repeat", "notes"):
        if key in change and change[key] is None:
            change.pop(key)
    try:
        event = rt.desk.update_event(user, event_id, **change)
    except ValueError as exc:
        raise _bad(exc) from exc
    if event is None:
        raise HTTPException(status_code=404, detail=t("Event not found."))
    return event


@router.delete("/api/desk/events/{event_id}")
@open_to("viewer")
def delete_event(event_id: int, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    if not rt.desk.delete_event(user, event_id):
        raise HTTPException(status_code=404, detail=t("Event not found."))
    return {"deleted": event_id}


def own_events(rt: Any, user: str, low: date, high: date) -> list[dict[str, Any]]:
    """The person's events laid out on the plant days [low, high], one entry each time."""

    found = []
    for event in rt.desk.events(user, low, high):
        for start, end in occurrences(event, low, high):
            found.append(
                {
                    "id": f"event:{event['event_id']}"
                    + (f":{start[:10]}" if event["repeat"] else ""),
                    "event_id": event["event_id"],
                    "title": event["title"],
                    "start": start,
                    "end": end,
                    "all_day": event["all_day"],
                    "kind": "event",
                    "editable": True,
                    "repeat": event["repeat"],
                    "series_start": event["start"],
                    "series_end": event["end"],
                    "detail": event["notes"][:200],
                }
            )
    return found


def scheduled_runs(schedules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The apps' next scheduled runs, those in the same hour together as one entry ("6
    scheduled runs") so that a busy hour stays one line."""

    hours: dict[str, list[dict[str, Any]]] = {}
    for schedule in schedules:
        hours.setdefault(schedule["next_run"][:13], []).append(schedule)
    found = []
    for hour, items in hours.items():
        if len(items) == 1:
            schedule = items[0]
            found.append(
                {
                    "id": f"schedule:{schedule['app']}:{schedule['id']}",
                    "title": schedule["name"] or schedule["id"],
                    "start": schedule["next_run"],
                    "all_day": False,
                    "kind": "schedule",
                    "app": schedule["app"],
                    "href": schedule.get("url"),
                    "editable": False,
                    "detail": schedule.get("cadence") or "",
                }
            )
            continue
        items.sort(key=lambda item: (item["next_run"], item["name"] or item["id"]))
        found.append(
            {
                "id": f"runs:{hour}",
                "title": t("{count} scheduled runs", count=len(items)),
                "start": items[0]["next_run"],
                "all_day": False,
                "kind": "schedule",
                "editable": False,
                "detail": ", ".join(item["name"] or item["id"] for item in items[:5]),
                "runs": [
                    {
                        "title": item["name"] or item["id"],
                        "start": item["next_run"],
                        "app": item["app"],
                        "href": item.get("url"),
                        "detail": item.get("cadence") or "",
                    }
                    for item in items
                ],
            }
        )
    return found


def _overlaps(start: str, end: str | None, low: str, high: str) -> bool:
    return start[:10] <= high and (end or start)[:10] >= low


@router.get("/api/desk/calendar")
def calendar(
    user: CurrentUser,
    rt: Runtime,
    access: UserAccess,
    start: Annotated[str, Query(pattern=DAY)],
    end: Annotated[str, Query(pattern=DAY)],
) -> dict[str, Any]:
    """Everything with a date in [start, end]: the person's own events (repeats laid out), their
    actions and their groups' (by due date), their to-dos (repeats laid out on the days ahead),
    alarms on assets they follow, the scheduled runs of the apps they open (those in the same
    hour together), the feeds those apps keep (``feeds``, one chip each) and the calendars they
    added."""

    low, high = _today(start), _today(end)
    if high < low or (high - low).days > MAX_SPAN_DAYS:
        raise HTTPException(status_code=422, detail=t("Ask for a year at most."))
    lo, hi = low.isoformat(), high.isoformat()
    events: list[dict[str, Any]] = []
    seen = action_visibility(rt, user)
    for view in ("mine", "groups"):
        for action in rt.workspace.actions.list(visible=seen, view=view, limit=1000):
            due = action.get("due_at")
            if not due or not lo <= due[:10] <= hi or action["status"] == "cancelled":
                continue
            events.append(
                {
                    "id": f"action:{action['action_id']}",
                    "title": action["title"],
                    "start": due[:10],
                    "all_day": True,
                    "kind": "action",
                    "href": f"/actions/{action['action_id']}",
                    "done": action["status"] == "done",
                    "editable": seen.everything
                    or action.get("owner") == user
                    or action.get("created_by") == user,
                    "detail": action.get("owner_name") or action.get("group_name") or "",
                }
            )
    events = list({item["id"]: item for item in events}.values())
    today_iso = date.fromisoformat(plant_today()).isoformat()
    # To-dos on their day; a repeated one also on the days ahead it falls on.
    for item in rt.desk.todos(user, _my_groups(rt, user), due_to=hi, limit=3000):
        if not item["due"] or (item["done"] and not lo <= item["due"] <= hi):
            continue
        base = {
            "title": item["title"],
            "all_day": True,
            "kind": "todo",
            "href": f"/todo?item={item['todo_id']}",
            "done": item["done"],
            "editable": False,
        }
        if lo <= item["due"] <= hi:
            events.append({**base, "id": f"todo:{item['todo_id']}", "start": item["due"]})
        if item["repeat"] and not item["done"]:
            day = max(low, date.fromisoformat(item["due"]) + timedelta(days=1))
            while day <= high:
                if todo_due(item, day):
                    events.append(
                        {
                            **base,
                            "id": f"todo:{item['todo_id']}:{day.isoformat()}",
                            "start": day.isoformat(),
                        }
                    )
                day += timedelta(days=1)
    for item in followed_assets(rt, user):
        if (
            item["status"] in ("alarm", "warning")
            and item.get("at")
            and lo <= item["at"][:10] <= hi
        ):
            events.append(
                {
                    "id": f"result:{item['ref']}:{item['app']}:{item['kind']}",
                    "title": f"{item['name']}: {item['summary'] or item['status']}",
                    "start": item["at"][:10],
                    "all_day": True,
                    "kind": "alarm",
                    "state": item["status"],
                    "href": item.get("href"),
                    "editable": False,
                }
            )
    events.extend(own_events(rt, user, low, high))
    apps = app_access(access, rt.suite_apps())
    events.extend(
        scheduled_runs(
            [
                schedule
                for schedule in rt.workspace.results.schedules()
                if schedule["app"] in apps
                and schedule.get("enabled")
                and schedule.get("next_run")
                and lo <= schedule["next_run"][:10] <= hi
            ]
        )
    )
    feeds = app_feeds(rt, apps)
    for item in rt.app_items.calendar(
        lo, hi, apps={key.split(":")[0] for key in feeds}, user=user, groups=_my_groups(rt, user)
    ):
        feed = feeds.get(f"{item['app']}:{item['feed']}")
        if feed is None:
            continue
        events.append(
            {
                "id": f"feed:{feed['id']}:{item['id']}",
                "title": item["title"],
                "start": item["start"],
                "end": item["end"],
                "all_day": item["all_day"],
                "kind": "feed",
                "feed": feed["id"],
                "app": item["app"],
                "href": item["url"],
                "ref": item["ref"],
                "editable": False,
                "detail": item["detail"] or feed["title"],
            }
        )
    calendars_out = []
    for item in rt.desk.calendars(user, events=True):
        _refresh(rt, user, item)
    for item in rt.desk.calendars(user, events=True):
        calendars_out.append(_public_calendar(item))
        for event in item["events"]:
            if _overlaps(event["start"], event.get("end"), lo, hi):
                events.append(
                    {
                        **event,
                        "id": f"cal:{item['calendar_id']}:{event['id']}",
                        "kind": "external",
                        "calendar": item["name"],
                        "color": item["color"],
                        "editable": False,
                        "detail": event.get("location") or "",
                    }
                )
    events.sort(key=lambda item: (item["start"], 0 if item.get("all_day") else 1, item["title"]))
    return {
        "start": lo,
        "end": hi,
        "today": today_iso,
        "events": events,
        "calendars": calendars_out,
        "feeds": list(feeds.values()),
        "links": rt.desk.settings()["calendar_links"],
        "repeats": repeats(),
    }


# Triage ----------------------------------------------------------------------------------------


class TriageIn(BaseModel):
    key: str = Field(min_length=1, max_length=300)
    state: str | None = Field(default=None, pattern=r"^(done|snoozed|read)$")
    until: str | None = Field(default=None, pattern=DAY)


@router.post("/api/desk/triage")
@open_to("viewer")
def triage(body: TriageIn, request: Request, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """A suggestion done, snoozed until a day, or back (``state`` null). Messages' Notifications
    keep their read and archived marks here too (``/api/notifications``). A public demo visit
    keeps its own (``marks_owner``)."""

    until = body.until or (date.fromisoformat(plant_today()) + timedelta(days=1)).isoformat()
    try:
        rt.desk.set_triage(
            marks_owner(request, rt, user),
            body.key,
            body.state,
            until if body.state == "snoozed" else None,
        )
    except ValueError as exc:
        raise _bad(exc) from exc
    return {"key": body.key, "state": body.state}


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


# Settings -------------------------------------------------------------------------------------


class DeskSettingsIn(BaseModel):
    enabled: bool = False
    hosts: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list, max_length=20)


@router.get("/api/desk/settings")
def desk_settings(_admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    return rt.desk.settings()


class TeamPageIn(BaseModel):
    enabled: bool


@router.get("/api/desk/team-page")
def team_page(_user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """Whether Desk shows its Team page (off until an administrator turns it on)."""

    return {"enabled": rt.desk.team_page()}


@router.put("/api/desk/team-page")
def save_team_page(body: TeamPageIn, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    enabled = rt.desk.save_team_page(body.enabled, actor=admin)
    rt.workspace.audit.record(
        admin, "desk.team_page", "setting:team_page", {"enabled": enabled}, app_id="processcraft"
    )
    return {"enabled": enabled}


@router.put("/api/desk/settings")
def save_desk_settings(body: DeskSettingsIn, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    try:
        saved = rt.desk.save_settings(enabled=body.enabled, hosts=body.hosts, actor=admin)
    except ValueError as exc:
        raise _bad(exc) from exc
    rt.workspace.audit.record(
        admin,
        "desk.calendar_links",
        "setting:calendar_links",
        {"enabled": saved["enabled"], "hosts": saved["hosts"]},
        app_id="processcraft",
    )
    return saved
