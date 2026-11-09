"""Desk's to-dos and lists, and the to-dos and calendar feeds the apps put in Desk."""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Annotated, Any

from fastapi import HTTPException, Query
from pydantic import BaseModel, Field

from plantcraft.actions import OPEN_STATUSES
from plantcraft.api.deps import (
    CurrentUser,
    Runtime,
    UserAccess,
    action_visibility,
    is_admin,
    open_to,
)
from plantcraft.api.routers.desk.app_items import app_todos
from plantcraft.api.routers.desk.common import (
    DAY,
    _bad,
    _my_groups,
    _today_todos,
    own_events,
    router,
)
from plantcraft.auth.suite import app_access
from plantcraft.config import plant_today
from plantcraft.desk import todo_repeats
from plantcraft.i18n import t

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
