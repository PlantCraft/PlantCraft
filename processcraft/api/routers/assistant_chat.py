"""HTTP routes: the assistant's chats in Desk (``processcraft/assistant_chat``, docs/assistant.md).

Each person sees and writes only their own chats. A question is kept at once and the answer is
written in the background; the page polls the chat with the last message id it has. The model
reads the plant through API v1 inside this process, with a token issued for the person who asked
at each read, so it sees exactly what they may see (``issue_user_token``).
"""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from processcraft.api.deps import (
    AdminUser,
    CurrentUser,
    Runtime,
    is_admin,
    marks_owner,
    open_to,
    user_access,
)
from processcraft.api.identity import READ_LEVELS, issue_user_token, user_claims, visible_apps
from processcraft.api.routers.messages import _resolve, present_ref
from processcraft.assistant_access import mcp
from processcraft.assistant_chat import (
    MAX_CONTEXT,
    MAX_FOLDER,
    MAX_PLACE,
    MAX_SHARES,
    MAX_TEXT,
    MAX_TITLE,
    chat_title,
)
from processcraft.assistant_chat.engine import Reader, Refused
from processcraft.assistant_chat.evals import Case
from processcraft.assistant_works import envelope, render
from processcraft.auth.public_demo import public_demo
from processcraft.i18n import t
from processcraft.refs import parse_ref
from processcraft.specialists.profiles import models_allowed_for

router = APIRouter(prefix="/api/assistant")


PAGE_CHARS = 8000


class PageInfo(BaseModel):
    """Where the person is, as the page says it (``useAssistantPage``): references and a few
    facts, never whole tables (assistant_works)."""

    page: str = Field(
        default="", max_length=80, pattern=r"^([a-z][a-z0-9]{1,30}:[a-z][a-z0-9-]{0,40})?$"
    )
    subject: str = Field(default="", max_length=400)
    facts: dict[str, Any] = Field(default_factory=dict)
    view: dict[str, Any] = Field(default_factory=dict)

    @field_validator("facts", "view")
    @classmethod
    def _small(cls, value: dict[str, Any]) -> dict[str, Any]:
        # A page sends a few facts and the rows on screen: rows beyond 8,000 characters are cut
        # (the longest list first, by halves) rather than refusing the chat.
        value = dict(value)
        while len(json.dumps(value, default=str)) > PAGE_CHARS:
            lists = [key for key, item in value.items() if isinstance(item, list) and item]
            if not lists:
                raise ValueError("8,000 characters at most")
            key = max(lists, key=lambda name: len(json.dumps(value[name], default=str)))
            value[key] = value[key][: len(value[key]) // 2]
        return value


class ChatStart(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    profile: str = Field(default="", max_length=60)
    ref: str = Field(default="", max_length=400)
    # The side panel of a page: what the page shows (for the model), where it is, and whether
    # the chat is listed in Desk (false: until the person continues it there).
    context: str = Field(default="", max_length=MAX_CONTEXT)
    place: str = Field(default="", max_length=MAX_PLACE)
    keep: bool = True
    # The work the person picked on the page (``<app>:<id>``) and the page's own description.
    work: str = Field(default="", max_length=120)
    page: PageInfo | None = None


class ProposalState(BaseModel):
    """What became of a proposal's card: the person created the object (its reference and page,
    from the object's own route) or put the proposal aside."""

    message_id: int = Field(ge=1)
    index: int = Field(ge=0, le=4)
    # "opened": the person took the fields to the object's own form (a work with a form).
    state: Literal["created", "opened", "discarded"]
    ref: str = Field(default="", max_length=400)
    href: str = Field(default="", max_length=400, pattern=r"^(/[^\s]*)?$")


class ChatQuestion(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT)


class ChatRename(BaseModel):
    """What the person changes on one of their chats; what is left out stays."""

    title: str | None = Field(default=None, min_length=1, max_length=MAX_TITLE)
    # One of the person's own groups of chats ("" takes it out of its group).
    folder: str | None = Field(default=None, max_length=MAX_FOLDER)
    archived: bool | None = None


class ChatSharing(BaseModel):
    # "everyone", "user:<name>" or "group:<id>"; empty stops sharing it.
    grants: list[str] = Field(default_factory=list, max_length=MAX_SHARES)


def _reader(app: Any, rt: Any, username: str) -> Reader:
    """Reads of this process's API v1 as ``username``, with a token issued at each read."""

    def read(method: str, path: str, values: dict[str, Any]) -> tuple[int, Any]:
        issued = issue_user_token(rt, username)
        if issued is None:
            return 403, {"detail": t("This person may no longer read the plant.")}

        return asyncio.run(mcp.request_in_process(app, issued["token"], method, path, values))

    return read


def _reader_of(rt: Any, user: str) -> str:
    """Only a person who may read the plant talks to the assistant."""

    claims = user_claims(rt, user)
    if rt.auth.enabled and (claims is None or claims["level"] not in READ_LEVELS):
        raise HTTPException(status_code=403, detail=t("Your access is limited to dashboards."))
    return user


def _owned(rt: Any, chat_id: int, user: str) -> dict[str, Any]:
    found = rt.assistant.store.chat(chat_id, user)
    if found is None:
        raise HTTPException(status_code=404, detail=t("Chat not found."))
    return found


def _grants(rt: Any, user: str) -> set[str]:
    """Who ``user`` is, as a chat's sharing names people: everyone, themselves, their groups."""

    return {
        "everyone",
        f"user:{user}",
        *(f"group:{group['group_id']}" for group in rt.workspace.groups.of(user)),
    }


def _readable(rt: Any, chat_id: int, user: str) -> dict[str, Any]:
    """The chat for its owner or for someone it is shared with (who only reads it)."""

    found = rt.assistant.store.readable(chat_id, user, _grants(rt, user))
    if found is None:
        raise HTTPException(status_code=404, detail=t("Chat not found."))
    return found


def _present_chat(
    rt: Any,
    chat: dict[str, Any],
    user: str | None = None,
    *,
    names: dict[str, str] | None = None,
    refs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A chat as the pages show it. ``names`` and ``refs``: the profiles' names and the chats'
    references resolved once for a whole list (``status``)."""

    item = dict(chat)
    owner = item.pop("username", None)
    # Someone else's chat, shared with this person: whose it is; only its owner sees the sharing.
    item["mine"] = user is None or owner == user
    if not item["mine"]:
        person = rt.workspace.users.get_user(owner) or {}
        item["owner"] = owner
        item["owner_name"] = person.get("display_name") or owner
        item.pop("shared", None)
        item.pop("folder", None)
    if names is None:
        names = _profile_names(rt)
    item["profile_name"] = names.get(chat["profile"], chat["profile"] or t("Assistant"))
    viewer = user or owner
    ref = chat.get("ref")
    if not ref:
        item["ref_view"] = None
    elif refs is not None and ref in refs:
        item["ref_view"] = present_ref(refs[ref])
    else:
        item["ref_view"] = present_ref(_resolve(rt, ref, viewer))
    return item


def _profile_names(rt: Any) -> dict[str, str]:
    return {profile["id"]: profile["name"] for profile in rt.assistant.profiles()}


def _present_refs(rt: Any, refs: list[str], viewer: str) -> list[dict[str, Any]]:
    shown = []
    for ref in refs:
        try:
            shown.append(present_ref(_resolve(rt, ref, viewer)))
        except Exception:  # an object gone or a reference of an app not installed
            shown.append({"ref": ref, "title": ref, "url": None})
    return shown


def _present_message(rt: Any, message: dict[str, Any], viewer: str) -> dict[str, Any]:
    item = dict(message)
    item["refs"] = _present_refs(rt, message.get("refs") or [], viewer)
    if item.get("charts"):
        trends = _trends_page(rt)
        item["charts"] = [
            {**chart, "trends": _trend_link(trends, chart) if trends else None}
            for chart in item["charts"]
        ]
    return item


def _trends_page(rt: Any) -> str:
    """The page that opens a new trend, of the app that declares the ``trend`` kind (View's
    /dash/trends/{id}): it also takes ?signal=&start=&end= (owner, 2026-10-26: a chart of the
    chat goes on in Trends)."""

    declared = getattr(rt.platform.refs, "declared", None)
    found = declared("trend") if callable(declared) else None
    return str(found["url"]).replace("/{id}", "") if found else ""


def _trend_link(page: str, chart: dict[str, Any]) -> str:
    query = [("signal", str(item.get("signal"))) for item in chart.get("series") or []]
    query += [("start", str(chart.get("start") or "")), ("end", str(chart.get("end") or ""))]
    return f"{page}?{urlencode(query)}"


def _with_marks(chat: dict[str, Any], stars: set[str], unread: set[str]) -> dict[str, Any]:
    """The person's own marks on a chat (owner, 2026-10-28): a favorite, unread until opened."""

    key = f"chat:{chat['chat_id']}"
    return {**chat, "starred": key in stars, "unread": key in unread}


@router.get("")
def status(request: Request, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """Whether the assistant answers here, with which profiles, and the person's chats."""

    _reader_of(rt, user)
    state = rt.assistant.status()
    access = user_access(rt, user)
    if state["allowed"] and not models_allowed_for(access.level if access else None):
        # A public demo's visitor: no assistant at all (the people an administrator created have it).
        state = {
            **state,
            "available": False,
            "allowed": False,
            "reason": t(
                "The assistant does not answer in this public demo. Open the team's chats below to "
                "see what it does."
            ),
            # The pages still show what it would do there (owner, 2026-10-28).
            "demo": True,
        }
    kept = rt.assistant.store.chats(user)
    shared = rt.assistant.store.shared_with(user, _grants(rt, user))
    # Every chat's profile name and reference at once, with one reader of the person's access
    # (per chat, each built it again; the list is asked by every screen's side panel).
    names = _profile_names(rt)
    wanted = list(dict.fromkeys(item["ref"] for item in [*kept, *shared] if item.get("ref")))
    refs = rt.platform.refs.resolve_many(wanted, viewer=user)
    once = {"names": names, "refs": refs}
    owner = marks_owner(request, rt, user)
    stars, unread = rt.desk.marks(owner, "star"), rt.desk.marks(owner, "unread")
    # Favorites first (the side panel lists the first few); the rest newest first.
    kept = sorted(kept, key=lambda item: f"chat:{item['chat_id']}" not in stars)

    def listed(item: dict[str, Any], viewer: str | None = None) -> dict[str, Any]:
        return _with_marks(_present_chat(rt, item, viewer, **once), stars, unread)

    return {
        **state,
        # An administrator is pointed to Setup, Language models, when the assistant is off.
        "can_set_up": is_admin(rt, user),
        "chats": [listed(item) for item in kept if not item["archived"]],
        # The ones the person archived (owner, 2026-10-26), apart: the side panel lists only the rest.
        "archived": [listed(item) for item in kept if item["archived"]],
        # Other people's chats shared with this person (owner, 2026-10-26), read-only.
        "shared": [listed(item, user) for item in shared],
    }


@router.post("/chats", status_code=201)
@open_to("viewer")
def start(payload: ChatStart, request: Request, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """A new chat, opened by the person's first question (and the object it is about)."""

    _reader_of(rt, user)
    ref = ""
    if payload.ref.strip():
        try:
            ref = str(parse_ref(payload.ref.strip()))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    context, work_key = payload.context, ""
    if payload.work or payload.page is not None:
        context, work_key = _page_context(rt, user, payload, ref)
        ref = ref or _subject_ref(payload)
    profile = payload.profile.strip().lower()
    if profile and profile not in {item["id"] for item in rt.assistant.profiles()}:
        raise HTTPException(
            status_code=422, detail=t("@{username} is not an active specialist.", username=profile)
        )
    try:
        chat = rt.assistant.store.create(
            user,
            chat_title(payload.text),
            profile=profile,
            ref=ref,
            context=context,
            place=payload.place,
            kept=payload.keep,
            work=work_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        question, answer = rt.assistant.ask(
            chat,
            user,
            payload.text,
            _reader(request.app, rt, user),
            visible_apps(rt, user),
            _level(rt, user),
        )
    except Refused as exc:
        rt.assistant.store.delete(chat["chat_id"], user)
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    found = rt.assistant.store.chat(chat["chat_id"], user) or chat
    return {
        "chat": _present_chat(rt, found),
        "messages": [_present_message(rt, question, user), _present_message(rt, answer, user)],
    }


def _subject_ref(payload: ChatStart) -> str:
    subject = payload.page.subject.strip() if payload.page else ""
    if not subject:
        return ""
    try:
        return str(parse_ref(subject))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _page_context(rt: Any, user: str, payload: ChatStart, ref: str) -> tuple[str, str]:
    """The chat's context from the page and the work picked there, built here in the sections
    of assistant_works (the page sends references and a few facts; the model reads the rest)."""

    page = payload.page or PageInfo()
    access = user_access(rt, user)
    level = access.level if access else None
    work = None
    if payload.work:
        work = rt.assistant.works.get(payload.work)
        if work is None or not work.offered_to(level):
            raise HTTPException(status_code=404, detail=t("This work is not offered here."))
        if page.page and page.page not in work.pages():
            raise HTTPException(status_code=422, detail=t("This work is not offered on this page."))
    subject_ref = ref or _subject_ref(payload)
    person = rt.workspace.users.get_user(user) or {}
    sections = envelope(
        work,
        place=payload.place,
        page=page.page,
        subject=present_ref(_resolve(rt, subject_ref, user)) if subject_ref else None,
        facts=page.facts,
        view=page.view,
        person={"username": user, "name": person.get("display_name") or user, "level": level},
    )
    text = render(sections)
    if payload.context.strip():
        text += "\n\n## page\n" + payload.context.strip()[:3000]
    return text, work.key if work else ""


@router.get("/works")
def works(
    user: CurrentUser, rt: Runtime, page: Annotated[str, Query(min_length=3, max_length=80)]
) -> dict[str, Any]:
    """The works the assistant offers this person on ``page`` (``<app>:<page id>``), the create
    works first (assistant_works)."""

    access = user_access(rt, user)
    level = access.level if access else None
    # A public demo's visitor sees them too, to know what the assistant does on each page (owner,
    # 2026-10-28); asking still needs a model (POST /chats refuses a visitor).
    visitor = (demo := public_demo()) is not None and user == demo.username
    shown = models_allowed_for(level) or visitor
    offered = rt.assistant.works.for_page(page, level) if shown else []
    return {"page": page, "works": [work.public() for work in offered]}


@router.post("/chats/{chat_id}/proposals")
@open_to("viewer")
def proposal(
    chat_id: int, payload: ProposalState, user: CurrentUser, rt: Runtime
) -> dict[str, Any]:
    """Record what the person did with a proposal's card. The object itself was created by its
    own route, with the person's session; this only keeps the card's state and the audit line."""

    _owned(rt, chat_id, user)
    message = next(
        (
            item
            for item in rt.assistant.store.messages(chat_id)
            if item["message_id"] == payload.message_id
        ),
        None,
    )
    proposals = list(((message or {}).get("meta") or {}).get("proposals") or [])
    if message is None or payload.index >= len(proposals):
        raise HTTPException(status_code=404, detail=t("Proposal not found."))
    item = {**proposals[payload.index], "state": payload.state}
    if payload.state in ("created", "opened"):
        item.update(ref=payload.ref, href=payload.href)
    proposals[payload.index] = item
    rt.assistant.store.update(payload.message_id, meta={**message["meta"], "proposals": proposals})
    rt.workspace.audit.record(
        user,
        f"assistant.proposal_{payload.state}",
        payload.ref or f"work:{item.get('work', '')}",
        {"chat_id": chat_id, "work": item.get("work"), "fields": sorted(item.get("fields") or {})},
        app_id="processcraft",
    )
    return {"proposal": item}


@router.get("/chats/{chat_id}")
def chat(
    chat_id: int,
    request: Request,
    user: CurrentUser,
    rt: Runtime,
    after: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """The chat and its messages after ``after``, plus the ones still being written. A chat
    shared with the person reads the same, marked as someone else's (``mine`` false). Opening it
    takes away the person's "unread" mark."""

    found = _readable(rt, chat_id, user)
    messages = rt.assistant.store.messages(chat_id)
    shown = [item for item in messages if item["message_id"] > after or item["state"] == "working"]
    owner = marks_owner(request, rt, user)
    if not after and f"chat:{chat_id}" in rt.desk.marks(owner, "unread"):
        rt.desk.set_mark(owner, f"chat:{chat_id}", "unread", False)
    stars = rt.desk.marks(owner, "star")
    return {
        "chat": _with_marks(_present_chat(rt, found, user), stars, set()),
        "messages": [_present_message(rt, item, user) for item in shown],
        "working": any(item["state"] == "working" for item in messages),
    }


@router.post("/chats/{chat_id}/messages", status_code=201)
@open_to("viewer")
def ask(
    chat_id: int, payload: ChatQuestion, request: Request, user: CurrentUser, rt: Runtime
) -> dict[str, Any]:
    _reader_of(rt, user)
    found = _owned(rt, chat_id, user)
    try:
        question, answer = rt.assistant.ask(
            found,
            user,
            payload.text,
            _reader(request.app, rt, user),
            visible_apps(rt, user),
            _level(rt, user),
        )
    except Refused as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return {"messages": [_present_message(rt, question, user), _present_message(rt, answer, user)]}


@router.post("/chats/{chat_id}/retry", status_code=201)
@open_to("viewer")
def retry(chat_id: int, request: Request, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """The last question asked again after its answer failed (Try again)."""

    _reader_of(rt, user)
    found = _owned(rt, chat_id, user)
    try:
        answer = rt.assistant.retry(
            found, user, _reader(request.app, rt, user), visible_apps(rt, user), _level(rt, user)
        )
    except Refused as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return {"messages": [_present_message(rt, answer, user)]}


def _level(rt: Any, user: str) -> str | None:
    access = user_access(rt, user)
    return access.level if access else None


@router.post("/chats/{chat_id}/keep")
@open_to("viewer")
def keep(chat_id: int, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """A side panel's chat continued in Desk: listed with the person's chats from now on."""

    _owned(rt, chat_id, user)
    return _present_chat(rt, rt.assistant.store.keep(chat_id, user) or {})


@router.patch("/chats/{chat_id}")
@open_to("viewer")
def rename(chat_id: int, payload: ChatRename, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """Rename one of the person's chats, put it in a group of theirs, archive it or bring it back."""

    _owned(rt, chat_id, user)
    try:
        found = rt.assistant.store.change(
            chat_id, user, title=payload.title, folder=payload.folder, archived=payload.archived
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _present_chat(rt, found or {})


@router.put("/chats/{chat_id}/sharing")
@open_to("viewer")
def share(chat_id: int, payload: ChatSharing, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """Who else may read the chat (owner, 2026-10-26: "share a chat like a dashboard"): everyone,
    people or groups of the workspace. They read it as it is and may continue it in a copy of
    their own; nobody else writes in it."""

    _owned(rt, chat_id, user)
    if "everyone" in payload.grants and _level(rt, user) != "admin":
        # The answers were read with the owner's access: shown to the whole workspace they
        # would carry documents and results others may not read (review decision D3).
        raise HTTPException(
            status_code=403, detail=t("Only an administrator shares a chat with everyone.")
        )
    for grant in payload.grants:
        kind, _, name = grant.partition(":")
        if kind == "user" and rt.workspace.users.get_user(name) is None:
            raise HTTPException(status_code=422, detail=t("Unknown person: {name}", name=name))
        if kind == "group" and rt.workspace.groups.get(name) is None:
            raise HTTPException(status_code=422, detail=t("Unknown group: {name}", name=name))
    try:
        found = rt.assistant.store.share(chat_id, user, payload.grants)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rt.workspace.audit.record(
        user,
        "assistant.chat_shared",
        f"chat:{chat_id}",
        {"grants": (found or {}).get("shared", [])},
        app_id="processcraft",
    )
    return _present_chat(rt, found or {})


@router.post("/chats/{chat_id}/copy", status_code=201)
@open_to("viewer")
def copy(chat_id: int, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """A chat the person may read (theirs or shared with them) as a new chat of their own, to
    continue it."""

    _reader_of(rt, user)
    found = _readable(rt, chat_id, user)
    try:
        made = rt.assistant.store.copy(found, user)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _present_chat(rt, made)


@router.delete("/chats/{chat_id}")
@open_to("viewer")
def delete(chat_id: int, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    _owned(rt, chat_id, user)
    rt.assistant.store.delete(chat_id, user)
    return {"deleted": chat_id}


# Evaluation: questions whose right answer is known (``assistant_chat/evals.py``), admins only.


class EvalStart(BaseModel):
    profile: str = Field(default="", max_length=60)
    # "questions": answers known from the plant's data; "works": each work as its page asks it.
    suite: Literal["questions", "works"] = "questions"


@router.get("/evals")
def evals(user: AdminUser, rt: Runtime) -> dict[str, Any]:
    """The latest evaluation runs, newest first, each with its cases' results."""

    return {
        "runs": rt.assistant.evals.runs() if rt.assistant.evals else [],
        "profiles": rt.assistant.profiles(),
    }


@router.post("/evals", status_code=202)
def start_eval(
    payload: EvalStart, request: Request, user: AdminUser, rt: Runtime
) -> dict[str, Any]:
    """Ask the cases to a profile's model now, as this administrator (in the background)."""

    profile = payload.profile.strip().lower()
    if profile and profile not in {item["id"] for item in rt.assistant.profiles()}:
        raise HTTPException(
            status_code=422, detail=t("@{username} is not an active specialist.", username=profile)
        )

    def context_for(case: Case) -> tuple[str, str]:
        """A work's case gets the context a person gets from that page (``_page_context``)."""

        page = case.page or {}
        start = ChatStart(
            text=case.question,
            work=case.work,
            place=page.get("place", ""),
            page=PageInfo(page=page.get("page", ""), subject=page.get("subject", "")),
        )
        return _page_context(rt, user, start, "")

    try:
        return rt.assistant.start_eval(
            user,
            profile,
            _reader(request.app, rt, user),
            visible_apps(rt, user),
            payload.suite,
            context_for,
        )
    except Refused as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@router.get("/evals/{run_id}")
def eval_run(run_id: int, user: AdminUser, rt: Runtime) -> dict[str, Any]:
    found = rt.assistant.evals.run(run_id) if rt.assistant.evals else None
    if found is None:
        raise HTTPException(status_code=404, detail=t("Evaluation not found."))
    return found
