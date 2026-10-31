"""HTTP routes: follow-up actions (docs/collaboration.md).

Viewers read and comment; editors create and change. Creating an action and
changing its status publish events with its references, so it shows in the
timeline of every asset it is about. Each person reaches only the actions they see
(``visibility``): theirs, their groups', those below a group they lead; administrators all.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from plantcraft.actions import (
    KINDS,
    OPEN_STATUSES,
    PRIORITIES,
    REQUEST_CATEGORIES,
    STATUSES,
    VIEWS,
    choices,
)
from plantcraft.api.deps import CurrentUser, Runtime, open_to, user_access
from plantcraft.api.deps import action_visibility as visibility
from plantcraft.api.routers.messages import present_ref
from plantcraft.i18n import t
from plantcraft.refs import find_refs

router = APIRouter()

VIEW_LABELS = {
    "visible": "All I can see",
    "mine": "Assigned to me",
    "groups": "My groups",
    "created": "Created by me",
}

Priority = Literal["low", "medium", "high", "critical"]
Status = Literal["open", "in_progress", "blocked", "done", "cancelled"]
View = Literal["visible", "mine", "groups", "created"]
Kind = Literal["action", "request"]
Category = Literal["error", "slow", "access", "data", "change", "other"]


class ActionDraft(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    priority: Priority = "medium"
    owner: str | None = Field(default=None, max_length=60)
    group_id: str | None = Field(default=None, max_length=60)
    due_at: str | None = Field(default=None, max_length=10)
    refs: list[Annotated[str, Field(max_length=400)]] = Field(default_factory=list, max_length=12)
    kind: Kind = "action"
    category: Category | None = None


class RequestDraft(BaseModel):
    """What anyone signed in asks of IT or an integrator (Operations › Requests)."""

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    category: Category = "other"
    priority: Priority = "medium"
    group_id: str | None = Field(default=None, max_length=60)
    refs: list[Annotated[str, Field(max_length=400)]] = Field(default_factory=list, max_length=12)


class HoursDraft(BaseModel):
    hours: float = Field(gt=0, le=24)
    day: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    note: str = Field(default="", max_length=300)
    billable: bool = True


class ActionUpdate(ActionDraft):
    status: Status = "open"


class CommentPayload(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class ItemDraft(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    owner: str | None = Field(default=None, max_length=60)
    due_at: str | None = Field(default=None, max_length=10)


class ItemChange(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=300)
    owner: str | None = Field(default=None, max_length=60)
    due_at: str | None = Field(default=None, max_length=10)
    done: bool | None = None


def _present(
    rt: Any,
    action: dict[str, Any],
    viewer: str,
    *,
    history: bool = False,
    resolved: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The action as the page shows it; ``resolved``: its references already resolved for
    ``viewer`` (a list resolves every reference of the page once)."""

    item = dict(action)
    refs = rt.platform.refs
    if resolved is None:
        resolved = refs.resolve_many(action["refs"], viewer=viewer)
    item["refs"] = [present_ref(resolved[ref]) for ref in action["refs"] if ref in resolved]
    if history:
        store = rt.workspace.actions
        item["history"] = store.history(action["action_id"])
        item["items"] = store.items(action["action_id"])
        item["hours"] = store.hours(action["action_id"])
        # #asset:FIC-101 or #user:ana.lima in the description and the comments, resolved once.
        texts = [action["description"]] + [
            entry["text"] for entry in item["history"] if entry["kind"] == "comment"
        ]
        found = list(dict.fromkeys(ref for text in texts for ref in find_refs(text)))[:60]
        mentioned = refs.resolve_many(found, viewer=viewer)
        item["mentions"] = [present_ref(mentioned[ref]) for ref in found if ref in mentioned]
    return item


def _group(rt: Any, group_id: str | None) -> str | None:
    if not group_id:
        return None
    if rt.workspace.groups.get(group_id) is None:
        raise HTTPException(status_code=422, detail=t("Group not found."))
    return group_id


def _owner(rt: Any, owner: str | None) -> str | None:
    if not owner:
        return None
    if not rt.workspace.users.is_person(owner):
        raise HTTPException(status_code=422, detail=t("The owner must be an active person."))
    return owner


def _get(rt: Any, action_id: int, user: str | None = None) -> dict[str, Any]:
    """The action, when ``user`` sees it (an action out of their sight is not found)."""

    action = rt.workspace.actions.get(action_id)
    if action is None or (user is not None and not visibility(rt, user).sees(action)):
        raise HTTPException(status_code=404, detail=t("Action not found."))
    return action


def _publish(rt: Any, kind: str, action: dict[str, Any], actor: str, summary: str) -> None:
    rt.platform.publish(
        kind,
        f"action:{action['action_id']}",
        source="processcraft",
        actor=actor,
        summary=summary[:600],
        payload={"status": action["status"], "priority": action["priority"]},
        refs=action["refs"],
    )


@router.get("/api/actions")
def list_actions(
    user: CurrentUser,
    rt: Runtime,
    status: Annotated[list[Status] | None, Query()] = None,
    owner: Annotated[str | None, Query(max_length=60)] = None,
    ref: Annotated[str | None, Query(max_length=400)] = None,
    q: Annotated[str | None, Query(max_length=80)] = None,
    group: Annotated[list[str] | None, Query(max_length=40)] = None,
    view: View = "visible",
    mine: bool = False,
    kind: Kind | None = None,
) -> dict[str, Any]:
    """The actions this person sees; ``view`` narrows them like Jira's quick filters:
    ``mine`` (they own), ``groups`` (assigned to their groups), ``created`` (by them)."""

    statuses = list(status) if status else None
    seen = visibility(rt, user)
    items = rt.workspace.actions.list(
        statuses=statuses,
        owner=owner,
        ref=ref,
        query=q,
        visible=seen,
        view="mine" if mine else view,
        group_ids=list(group) if group else None,
        kind=kind,
    )
    mine_groups = rt.workspace.groups.scope(user)["groups"]
    page_refs = list(dict.fromkeys(ref for item in items for ref in item["refs"]))
    resolved = rt.platform.refs.resolve_many(page_refs, viewer=user)
    return {
        "items": [_present(rt, item, user, resolved=resolved) for item in items],
        "statuses": choices(STATUSES),
        "priorities": choices(PRIORITIES),
        "open_statuses": list(OPEN_STATUSES),
        "people": [
            {"username": item["username"], "display_name": item["display_name"]}
            for item in rt.workspace.users.list_users(kind="person")
        ],
        "groups": [
            {
                "group_id": item["group_id"],
                "name": item["name"],
                "mine": item["group_id"] in mine_groups,
            }
            for item in rt.workspace.groups.list()
        ],
        "views": [{"id": key, "label": t(VIEW_LABELS[key])} for key in VIEWS],
        "kinds": choices(KINDS),
        "categories": choices(REQUEST_CATEGORIES),
        "everything": seen.everything,
    }


@router.post("/api/actions", status_code=201)
def create_action(payload: ActionDraft, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    try:
        action = rt.workspace.actions.create(
            title=payload.title,
            actor=user,
            description=payload.description,
            priority=payload.priority,
            owner=_owner(rt, payload.owner),
            group_id=_group(rt, payload.group_id),
            due_at=payload.due_at,
            refs=payload.refs,
            kind=payload.kind,
            category=payload.category,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _created(rt, action, user)
    return _present(rt, action, user, history=True)


def _created(rt: Any, action: dict[str, Any], user: str) -> None:
    summary = (
        t("Request: {title}", title=action["title"])
        if action["kind"] == "request"
        else t("Action created: {title}", title=action["title"])
    )
    _publish(rt, "action.created", action, user, summary)


@router.post("/api/requests", status_code=201)
@open_to("viewer")
def ask(payload: RequestDraft, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """A request to IT or an integrator, open to anyone who signs in (a viewer too: the people
    who use the suite are the ones who need help). Its queue is the group chosen."""

    try:
        action = rt.workspace.actions.create(
            title=payload.title,
            actor=user,
            description=payload.description,
            priority=payload.priority,
            group_id=_group(rt, payload.group_id),
            refs=payload.refs,
            kind="request",
            category=payload.category,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _created(rt, action, user)
    return _present(rt, action, user, history=True)


@router.get("/api/actions/{action_id}")
def get_action(action_id: int, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    return _present(rt, _get(rt, action_id, user), user, history=True)


@router.put("/api/actions/{action_id}")
@open_to("viewer")
def update_action(
    action_id: int, payload: ActionUpdate, user: CurrentUser, rt: Runtime
) -> dict[str, Any]:
    """Editors change any action they see; the Operations role (IT, an integrator's team) also
    answers requests, whatever its access level."""

    current = _get(rt, action_id, user)
    access = user_access(rt, user)
    if not (access and access.at_least("editor")) and not (
        access and access.can_operate and current["kind"] == "request"
    ):
        raise HTTPException(status_code=403, detail=t("Your access is read-only."))
    try:
        action, previous = rt.workspace.actions.update(
            action_id,
            actor=user,
            title=payload.title,
            description=payload.description,
            priority=payload.priority,
            status=payload.status,
            owner=_owner(rt, payload.owner),
            group_id=_group(rt, payload.group_id),
            due_at=payload.due_at,
            refs=payload.refs,
            category=payload.category,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if previous is not None:
        _publish(
            rt,
            "action.status_changed",
            action,
            user,
            t(
                "{title}: {status}",
                title=action["title"],
                status=action["status_label"],
            ),
        )
    return _present(rt, action, user, history=True)


@router.post("/api/actions/{action_id}/comments", status_code=201)
@open_to("viewer")
def comment(
    action_id: int, payload: CommentPayload, user: CurrentUser, rt: Runtime
) -> dict[str, Any]:
    _get(rt, action_id, user)
    try:
        rt.workspace.actions.comment(action_id, user, payload.text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _present(rt, _get(rt, action_id), user, history=True)


@router.post("/api/actions/{action_id}/items", status_code=201)
def add_item(action_id: int, payload: ItemDraft, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """A checklist item: what, who and by when."""

    _get(rt, action_id, user)
    try:
        rt.workspace.actions.add_item(
            action_id,
            actor=user,
            text=payload.text,
            owner=_owner(rt, payload.owner),
            due_at=payload.due_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _present(rt, _get(rt, action_id), user, history=True)


@router.patch("/api/actions/{action_id}/items/{item_id}")
def change_item(
    action_id: int, item_id: int, payload: ItemChange, user: CurrentUser, rt: Runtime
) -> dict[str, Any]:
    """Tick an item, or change its text, owner or due date (only the fields sent)."""

    _get(rt, action_id, user)
    changes = payload.model_dump(exclude_unset=True)
    if "owner" in changes:
        changes["owner"] = _owner(rt, changes["owner"])
    try:
        rt.workspace.actions.update_item(action_id, item_id, actor=user, changes=changes)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=t("Checklist item not found.")) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _present(rt, _get(rt, action_id), user, history=True)


@router.delete("/api/actions/{action_id}/items/{item_id}")
def delete_item(action_id: int, item_id: int, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    _get(rt, action_id, user)
    try:
        rt.workspace.actions.delete_item(action_id, item_id, actor=user)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=t("Checklist item not found.")) from exc
    return _present(rt, _get(rt, action_id), user, history=True)


@router.post("/api/actions/{action_id}/hours", status_code=201)
@open_to("viewer")
def log_hours(
    action_id: int, payload: HoursDraft, user: CurrentUser, rt: Runtime
) -> dict[str, Any]:
    """Time spent on an action the person sees (an integrator's team logs it on a request, often
    without being an editor)."""

    _get(rt, action_id, user)
    try:
        rt.workspace.actions.add_hours(
            action_id,
            actor=user,
            hours=payload.hours,
            day=payload.day,
            note=payload.note,
            billable=payload.billable,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _present(rt, _get(rt, action_id), user, history=True)


@router.delete("/api/actions/{action_id}/hours/{entry_id}")
@open_to("viewer")
def delete_hours(action_id: int, entry_id: int, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """One's own entry; an administrator removes anyone's."""

    _get(rt, action_id, user)
    entry = next(
        (item for item in rt.workspace.actions.hours(action_id) if item["entry_id"] == entry_id),
        None,
    )
    if entry is None:
        raise HTTPException(status_code=404, detail=t("Time entry not found."))
    access = user_access(rt, user)
    if entry["username"] != user and not (access and access.is_admin):
        raise HTTPException(
            status_code=403, detail=t("Only who logged the time, or an administrator, removes it.")
        )
    rt.workspace.actions.delete_hours(action_id, entry_id)
    rt.workspace.audit.record(
        user, "action.hours.deleted", f"action:{action_id}", entry, app_id="processcraft"
    )
    return _present(rt, _get(rt, action_id), user, history=True)
