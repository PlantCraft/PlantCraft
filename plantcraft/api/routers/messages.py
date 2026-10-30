"""HTTP routes: conversations between people and specialists (Messages, docs/collaboration.md)."""

from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from plantcraft.api.deps import CurrentUser, Runtime, action_visibility, marks_owner, open_to
from plantcraft.api.feed import mark_conversation_read, marked_unread_chats, visit_reads
from plantcraft.i18n import t
from plantcraft.refs import kind_label, parse_ref
from plantcraft.specialists import models_allowed

router = APIRouter()

# Words that could be an asset's id: FIC-101, TI_204, u-demo.
WORD = re.compile(r"(?<![#\w:@])[A-Za-z0-9][A-Za-z0-9_.\-]*[A-Za-z0-9]")
AUTO_LINKS = 6


class ConversationPayload(BaseModel):
    members: list[Annotated[str, Field(max_length=60)]] = Field(min_length=1, max_length=100)
    title: str = Field(default="", max_length=120)
    text: str = Field(default="", max_length=4000)
    ref: str | None = Field(default=None, max_length=400)


class ChatMessagePayload(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    ref: str | None = Field(default=None, max_length=400)


class MembersPayload(BaseModel):
    members: list[Annotated[str, Field(max_length=60)]] = Field(min_length=1, max_length=100)


class ReadPayload(BaseModel):
    message_id: int | None = Field(default=None, ge=0)


def _resolve(rt: Any, ref: str, viewer: str | None = None) -> dict[str, Any]:
    """What ``ref`` is, as ``viewer`` may read it (``RefResolvers.resolve``)."""

    try:
        return rt.platform.refs.resolve(ref, viewer=viewer)
    except ValueError:
        kind, _, item_id = ref.partition(":")
        return {
            "ref": ref,
            "kind": kind,
            "id": item_id,
            "exists": False,
            "title": ref,
            "href": None,
        }


def detect_refs(rt: Any, text: str) -> list[str]:
    """Asset ids written plainly in the text ("how is FIC-101 doing?")."""

    found: list[str] = []
    for word in dict.fromkeys(match.group(0) for match in WORD.finditer(text)):
        if not re.search(r"[\d_\-]", word):
            continue
        asset = rt.workspace.assets.get(word) or rt.workspace.assets.get(word.rstrip("."))
        if asset is not None:
            ref = f"asset:{asset['asset_id']}"
            if ref not in found:
                found.append(ref)
        if len(found) >= AUTO_LINKS:
            break
    return found


def _checked_ref(rt: Any, ref: str | None) -> list[str]:
    if not ref:
        return []
    try:
        value = str(parse_ref(ref))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not _resolve(rt, value).get("exists"):
        raise HTTPException(
            status_code=422, detail=t("{ref} does not exist in the platform.", ref=value)
        )
    return [value]


def present_ref(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "ref": item["ref"],
        "kind": item.get("kind"),
        "id": item.get("id"),
        "kind_label": item.get("kind_label") or kind_label(str(item.get("kind") or "")),
        "title": item.get("title"),
        "href": item.get("href"),
        "status": item.get("status"),
        "exists": bool(item.get("exists")),
    }


def _present_message(
    rt: Any, message: dict[str, Any], cache: dict[str, dict[str, Any]], viewer: str
) -> dict[str, Any]:
    refs = []
    for ref in message.get("refs") or []:
        if ref not in cache:
            cache[ref] = _resolve(rt, ref, viewer)
        refs.append(present_ref(cache[ref]))
    return {**message, "refs": refs}


def _subjects(rt: Any) -> dict[str, str]:
    return {item["username"]: item["subject"] for item in rt.specialists.list()}


def _present_conversation(
    conversation: dict[str, Any], viewer: str, subjects: dict[str, str]
) -> dict[str, Any]:
    conversation = dict(conversation)
    # A specialist is introduced by its subject, not by its account role.
    conversation["members"] = [
        {**item, "role": subjects.get(item["username"]) or item["role"]}
        if item["kind"] == "specialist"
        else item
        for item in conversation["members"]
    ]
    others = [item for item in conversation["members"] if item["username"] != viewer]
    conversation["display_title"] = (
        conversation["title"] or ", ".join(item["display_name"] for item in others) or t("Just you")
    )
    conversation["has_specialist"] = any(item["kind"] == "specialist" for item in others)
    conversation["busy"] = [
        item["username"] for item in conversation["members"] if item.get("busy")
    ]
    return conversation


def _with_marks(conversation: dict[str, Any], stars: set[str], unread: set[str]) -> dict[str, Any]:
    """The person's own marks on a conversation (owner, 2026-10-28): a favorite, and unread again
    (at least one unread until they open it)."""

    key = f"conversation:{conversation['conversation_id']}"
    marked = key in unread
    return {
        **conversation,
        "starred": key in stars,
        "marked_unread": marked,
        "unread": max(int(conversation.get("unread") or 0), 1 if marked else 0),
    }


def _marks(rt: Any, owner: str) -> tuple[set[str], set[str]]:
    return rt.desk.marks(owner, "star"), rt.desk.marks(owner, "unread")


def _member_conversation(rt: Any, conversation_id: int, user: str) -> dict[str, Any]:
    rt.workspace.messages.sync(user)
    conversation = rt.workspace.messages.get(conversation_id, viewer=user)
    if conversation is None:
        raise HTTPException(status_code=404, detail=t("Conversation not found."))
    if not any(item["username"] == user for item in conversation["members"]):
        raise HTTPException(status_code=403, detail=t("You are not part of this conversation."))
    return conversation


def _post(
    rt: Any, conversation: dict[str, Any], user: str, text: str, ref: str | None
) -> dict[str, Any]:
    refs = _checked_ref(rt, ref) + detect_refs(rt, text)
    try:
        message = rt.workspace.messages.post(conversation["conversation_id"], user, text, refs=refs)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rt.specialist_chat.handle(conversation, message, user)
    return _present_message(rt, message, {}, user)


def _require_person(rt: Any, user: str) -> None:
    if not rt.workspace.users.is_person(user):
        raise HTTPException(status_code=403, detail=t("Only people can write messages."))


@router.get("/api/messages/contacts")
def contacts(
    user: CurrentUser,
    rt: Runtime,
    ref: Annotated[str | None, Query(max_length=400)] = None,
) -> dict[str, Any]:
    """Everyone a person can write to: the active people and the active specialists.

    With ``ref``, ``suggested`` names the specialists whose apps published a
    result about that object.
    """

    people = [
        {
            "username": item["username"],
            "display_name": item["display_name"],
            "role": item["role"],
            "kind": "person",
        }
        for item in rt.workspace.users.list_users(kind="person")
        if item["username"] != user
    ]
    allowed = models_allowed()
    specialists = [
        {
            "username": item["username"],
            "display_name": item["display_name"],
            "role": item["subject"],
            "subject": item["subject"],
            "kind": "specialist",
            "model_on": allowed and item["model"]["ready"],
        }
        for item in rt.specialists.list(include_inactive=False)
    ]
    suggested: list[str] = []
    if ref:
        try:
            subject = str(parse_ref(ref))
        except ValueError:
            subject = ""
        apps = {item["app"] for item in rt.workspace.results.results(subjects=[subject])}
        suggested = [
            item["username"]
            for item in rt.specialists.list(include_inactive=False)
            if apps & set(item["apps"])
        ]
    # Groups: choosing one adds its people; a member also opens the group's own conversation.
    groups = [
        {
            "group_id": item["group_id"],
            "name": item["name"],
            "kind_label": item["kind_label"],
            "members": [
                member["username"]
                for member in item["members"]
                if member["active"] and member["username"] != user
            ],
            "mine": any(member["username"] == user for member in item["members"]),
        }
        for item in rt.workspace.groups.list()
    ]
    return {
        "people": people,
        "specialists": specialists,
        "groups": [item for item in groups if item["members"] or item["mine"]],
        "suggested": suggested,
        "model_allowed": allowed,
    }


@router.get("/api/messages/references")
def references(
    user: CurrentUser,
    rt: Runtime,
    q: Annotated[str, Query(max_length=80)] = "",
) -> list[dict[str, Any]]:
    """Objects a message can be about: assets and actions."""

    text = q.strip()
    items: list[dict[str, Any]] = []
    for asset in rt.workspace.assets.search(text, limit=10):
        items.append(
            {
                "ref": f"asset:{asset['asset_id']}",
                "kind": "asset",
                "kind_label": kind_label("asset"),
                "title": asset["name"],
                "detail": asset["asset_id"],
            }
        )
    seen = action_visibility(rt, user)
    for action in rt.workspace.actions.list(query=text or None, limit=6, visible=seen):
        items.append(
            {
                "ref": f"action:{action['action_id']}",
                "kind": "action",
                "kind_label": kind_label("action"),
                "title": f"AC-{action['action_id']}",
                "detail": action["title"],
            }
        )
    items.extend(_desk_references(rt, user, text))
    return items[:20]


def _desk_references(rt: Any, user: str, text: str) -> list[dict[str, Any]]:
    """The person's own notes and open to-dos (Desk), which only they see in the picker."""

    groups = [group["group_id"] for group in rt.workspace.groups.of(user)]
    found = [
        {
            "ref": f"note:{note['note_id']}",
            "kind": "note",
            "kind_label": kind_label("note"),
            "title": note["title"] or t("Untitled"),
            "detail": note["body_text"][:80],
        }
        for note in rt.desk.notes(user, groups, q=text)[:4]
    ]
    needle = text.lower()
    todos = [
        todo
        for todo in rt.desk.todos(user, groups, done=False, limit=500)
        if needle in todo["title"].lower()
    ]
    found.extend(
        {
            "ref": f"todo:{todo['todo_id']}",
            "kind": "todo",
            "kind_label": kind_label("todo"),
            "title": todo["title"],
            "detail": todo["due"] or "",
        }
        for todo in todos[:4]
    )
    return found


@router.get("/api/messages/conversations")
def conversations(request: Request, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    store = rt.workspace.messages
    subjects = _subjects(rt)
    owner = marks_owner(request, rt, user)
    reads = visit_reads(rt, owner)
    stars, unread = _marks(rt, owner)
    items = [
        _with_marks(_present_conversation(item, user, subjects), stars, unread)
        for item in store.list_for(user, read_upto=reads)
    ]
    marked = sum(1 for item in items if item["marked_unread"] and item["unread"] == 1)
    return {"unread": store.unread_total(user, read_upto=reads) + marked, "items": items}


@router.post("/api/messages/conversations", status_code=201)
@open_to("viewer")
def start_conversation(
    payload: ConversationPayload, user: CurrentUser, rt: Runtime
) -> dict[str, Any]:
    _require_person(rt, user)
    try:
        started = rt.workspace.messages.start(user, payload.members, title=payload.title)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conversation_id = started["conversation_id"]
    found = rt.workspace.messages.get(conversation_id, viewer=user) or started
    message = _post(rt, found, user, payload.text, payload.ref) if payload.text.strip() else None
    view = rt.workspace.messages.get(conversation_id, viewer=user) or found
    return {"conversation": _present_conversation(view, user, _subjects(rt)), "message": message}


@router.post("/api/messages/groups/{group_id}")
@open_to("viewer")
def group_conversation(group_id: str, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """The group's own conversation (created the first time), for the group's members."""

    _require_person(rt, user)
    group = rt.workspace.groups.get(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail=t("Group not found."))
    members = rt.workspace.groups.members(group_id)
    if user not in members:
        raise HTTPException(
            status_code=403, detail=t("Only the group's members take part in its conversation.")
        )
    found = rt.workspace.messages.for_group(group_id, group["name"], members)
    view = rt.workspace.messages.get(found["conversation_id"], viewer=user) or found
    return _present_conversation(view, user, _subjects(rt))


@router.get("/api/messages/conversations/{conversation_id}")
def conversation(
    conversation_id: int,
    request: Request,
    user: CurrentUser,
    rt: Runtime,
    after: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    found = _member_conversation(rt, conversation_id, user)
    cache: dict[str, dict[str, Any]] = {}
    messages = rt.workspace.messages.messages(conversation_id, after=after, limit=300)
    stars, unread = _marks(rt, marks_owner(request, rt, user))
    return {
        "conversation": _with_marks(
            _present_conversation(found, user, _subjects(rt)), stars, unread
        ),
        "messages": [_present_message(rt, item, cache, user) for item in messages],
    }


@router.post("/api/messages/conversations/{conversation_id}/messages", status_code=201)
@open_to("viewer")
def send_message(
    conversation_id: int, payload: ChatMessagePayload, user: CurrentUser, rt: Runtime
) -> dict[str, Any]:
    _require_person(rt, user)
    found = _member_conversation(rt, conversation_id, user)
    return _post(rt, found, user, payload.text, payload.ref)


@router.post("/api/messages/conversations/{conversation_id}/read")
@open_to("viewer")
def read(
    conversation_id: int,
    request: Request,
    user: CurrentUser,
    rt: Runtime,
    payload: ReadPayload | None = None,
) -> dict[str, Any]:
    _member_conversation(rt, conversation_id, user)
    owner = marks_owner(request, rt, user)
    mark_conversation_read(
        rt, user, owner, conversation_id, payload.message_id if payload else None
    )
    # Opened: no longer marked unread.
    if f"conversation:{conversation_id}" in rt.desk.marks(owner, "unread"):
        rt.desk.set_mark(owner, f"conversation:{conversation_id}", "unread", False)
    return {
        "unread": rt.workspace.messages.unread_total(user, read_upto=visit_reads(rt, owner))
        + marked_unread_chats(rt, user, owner)
    }


@router.post("/api/messages/conversations/{conversation_id}/members")
@open_to("viewer")
def add_members(
    conversation_id: int, payload: MembersPayload, user: CurrentUser, rt: Runtime
) -> dict[str, Any]:
    _require_person(rt, user)
    found = _member_conversation(rt, conversation_id, user)
    if found.get("group_id"):
        raise HTTPException(
            status_code=422,
            detail=t("A group's conversation has the group's people: change the group instead."),
        )
    if len(found["members"]) == 2 and not found["title"]:
        raise HTTPException(
            status_code=422, detail=t("To add more people, start a group with everyone.")
        )
    try:
        rt.workspace.messages.add_members(conversation_id, payload.members)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    view = rt.workspace.messages.get(conversation_id, viewer=user) or found
    return _present_conversation(view, user, _subjects(rt))
