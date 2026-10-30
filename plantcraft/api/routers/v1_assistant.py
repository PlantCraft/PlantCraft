"""HTTP routes: the assistant an app opens beside one of its objects (API v1 ``/assistant``).

An app's page (a run that failed, a protocol, a loop) offers "Ask the assistant", and an app
can give it a page of its own about everything it holds (``app:<id>``: "which loops are
worst?"): the
shared interface (``@plantcraft/ui``'s ``AssistantPanel``) asks which specialists know
about the object, starts a conversation about it and follows the replies here, with the
person's token cookie. The conversation is an ordinary one of Messages: it stays in the
person's inbox and the specialist answers from everything the platform knows about the
object (its results, events, actions and what its app explained, ``/knowledge``).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from plantcraft.api.deps import Runtime, claims_marks_owner
from plantcraft.api.feed import mark_conversation_read
from plantcraft.api.identity import READ_LEVELS, Caller, V1Caller
from plantcraft.api.routers.messages import (
    _member_conversation,
    _post,
    _present_conversation,
    _present_message,
    _resolve,
    _subjects,
    present_ref,
)
from plantcraft.i18n import t
from plantcraft.refs import parse_ref
from plantcraft.specialists import models_allowed

router = APIRouter(prefix="/api/v1/assistant")

RefText = Annotated[str, Field(min_length=3, max_length=400)]


class AssistantStart(BaseModel):
    specialist: str = Field(min_length=1, max_length=60)
    ref: RefText
    text: str = Field(min_length=1, max_length=4000)


class AssistantMessage(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


def _person(caller: Caller, rt: Any) -> str:
    """Only a person (not an app) with read access talks to an assistant."""

    if caller.app_id is not None:
        raise HTTPException(status_code=403, detail=t("The assistant talks to people."))
    if caller.level not in READ_LEVELS:
        raise HTTPException(status_code=403, detail=t("Your access is limited to dashboards."))
    if rt.auth.enabled and not rt.workspace.users.is_person(caller.username):
        raise HTTPException(status_code=403, detail=t("Only people can write messages."))
    return caller.username


def _ref(text: str) -> str:
    try:
        return str(parse_ref(text))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _apps_about(rt: Any, ref: str) -> set[str]:
    """The apps that know something about ``ref``: its owner, results and explanations."""

    kind, _, item_id = ref.partition(":")
    apps: set[str] = set()
    # Objects an app names under its own id (run:linkcraft/42, algorithm:linkcraft/loop_health).
    if kind in {"run", "protocol", "algorithm", "block"} and "/" in item_id:
        apps.add(item_id.split("/", 1)[0])
    if kind == "app":
        apps.add(item_id)
    apps |= {item["app"] for item in rt.workspace.results.results(subjects=[ref])}
    apps |= {item["app"] for item in rt.workspace.knowledge.about(ref)}
    return apps


def _specialists(rt: Any, ref: str) -> tuple[list[dict[str, Any]], list[str]]:
    allowed = models_allowed()
    items = rt.specialists.list(include_inactive=False)
    apps = _apps_about(rt, ref)
    specialists = [
        {
            "username": item["username"],
            "display_name": item["display_name"],
            "subject": item["subject"],
            "apps": item["apps"],
            "model_on": allowed and item["model"]["ready"],
        }
        for item in items
    ]
    suggested = [item["username"] for item in items if apps & set(item["apps"])]
    return specialists, suggested


@router.get("")
def assistant(
    caller: V1Caller,
    rt: Runtime,
    ref: Annotated[str, Query(min_length=3, max_length=400)],
) -> dict[str, Any]:
    """Who can talk about ``ref``, and the person's conversations that already cite it."""

    user = _person(caller, rt)
    value = _ref(ref)
    specialists, suggested = _specialists(rt, value)
    subjects = _subjects(rt)
    return {
        "ref": present_ref(_resolve(rt, value, user)),
        "specialists": specialists,
        "suggested": suggested,
        "model_allowed": models_allowed(),
        "conversations": [
            _present_conversation(item, user, subjects)
            for item in rt.workspace.messages.about(user, value)
        ],
        "messages_url": "/messages",
        "specialists_url": "/users/specialists",
    }


@router.post("/conversations", status_code=201)
def start(payload: AssistantStart, caller: V1Caller, rt: Runtime) -> dict[str, Any]:
    """A new conversation with one specialist about ``ref``, opened by the person's question."""

    user = _person(caller, rt)
    value = _ref(payload.ref)
    name = payload.specialist.strip().lower()
    if not any(item["username"] == name for item in rt.specialists.list(include_inactive=False)):
        raise HTTPException(
            status_code=422, detail=t("@{username} is not an active specialist.", username=name)
        )
    title = str(_resolve(rt, value, user).get("title") or value)[:120]
    try:
        started = rt.workspace.messages.start(user, [name], title=title)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    found = rt.workspace.messages.get(started["conversation_id"], viewer=user) or started
    message = _post(rt, found, user, payload.text, value)
    view = rt.workspace.messages.get(started["conversation_id"], viewer=user) or found
    return {"conversation": _present_conversation(view, user, _subjects(rt)), "message": message}


@router.get("/conversations/{conversation_id}")
def conversation(
    conversation_id: int,
    caller: V1Caller,
    rt: Runtime,
    after: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """The conversation and its messages after ``after`` (the panel polls with the last id)."""

    user = _person(caller, rt)
    found = _member_conversation(rt, conversation_id, user)
    cache: dict[str, dict[str, Any]] = {}
    messages = rt.workspace.messages.messages(conversation_id, after=after, limit=300)
    if messages:
        owner = claims_marks_owner(caller.username, caller.claims)
        mark_conversation_read(rt, user, owner, conversation_id, messages[-1]["message_id"])
    return {
        "conversation": _present_conversation(found, user, _subjects(rt)),
        "messages": [_present_message(rt, item, cache, user) for item in messages],
    }


@router.post("/conversations/{conversation_id}/messages", status_code=201)
def send(
    conversation_id: int, payload: AssistantMessage, caller: V1Caller, rt: Runtime
) -> dict[str, Any]:
    user = _person(caller, rt)
    found = _member_conversation(rt, conversation_id, user)
    return _post(rt, found, user, payload.text, None)
