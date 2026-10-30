"""HTTP routes: API v1's people, groups and notifications (docs/api-v1.md, docs/notifications.md).

Apps list people and groups for their pickers (names, sector, groups; never an email or a
phone) and send notifications to ``user:<username>`` and ``group:<id>``: the platform delivers
them in Messages and, when set up, by email. Only an app's service token notifies.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, StringConstraints

from plantcraft.api.deps import Runtime
from plantcraft.api.identity import V1Caller, V1Reader
from plantcraft.auth.suite import suite_apps
from plantcraft.i18n import t
from plantcraft.notify import MAX_RECIPIENTS, MAX_TEXT, MAX_TITLE

router = APIRouter(prefix="/api/v1")

Recipient = Annotated[str, StringConstraints(min_length=3, max_length=80)]
Ref = Annotated[str, StringConstraints(min_length=3, max_length=300)]


class NotificationAction(BaseModel):
    label: str = Field(min_length=1, max_length=40)
    href: str = Field(min_length=1, max_length=500)
    # GET opens the page; POST runs the call in the sending app, as the person who clicks, and
    # must be under that app's own prefix (docs/quick-access.md, 2026-10-26).
    method: Literal["GET", "POST"] = "GET"


class NotificationResolve(BaseModel):
    key: str = Field(min_length=1, max_length=200)
    # Shown in place of the buttons: "Acknowledged by Ana".
    note: str = Field(default="", max_length=200)


class NotificationRequest(BaseModel):
    recipients: list[Recipient] = Field(min_length=1, max_length=MAX_RECIPIENTS)
    title: str = Field(min_length=1, max_length=MAX_TITLE)
    text: str = Field(default="", max_length=MAX_TEXT)
    priority: Literal["critical", "high", "medium", "low"] = "medium"
    # Where the person goes from the message: a path of the suite ("/alarm/alarms/12").
    url: str | None = Field(default=None, max_length=500)
    email: bool = False
    refs: list[Ref] = Field(default_factory=list, max_length=12)
    # The app's own id for what it notifies about ("alarm:12:3"): one thread in Messages'
    # Notifications per app and key (fired, reminded, escalated, cleared), unread again on each.
    key: str | None = Field(default=None, max_length=200)
    # What the notification is about, for its icon and Messages' filters (added 2026-10-24).
    category: Literal["alarm", "run", "action", "info"] | None = None
    # Up to three buttons beside "Open": a page to open ("Open the rule" -> /alarm/rules/4) or a
    # call to run as the person ("Acknowledge" -> POST /alarm/api/alarms/12/ack).
    actions: list[NotificationAction] = Field(default_factory=list, max_length=3)


@router.get("/people")
def people(_caller: V1Reader, rt: Runtime) -> list[dict[str, Any]]:
    """The active people: username, name, sector, job title, unit and groups."""

    memberships = rt.workspace.groups.memberships()
    return [
        {
            "username": user["username"],
            "name": user["display_name"],
            "role": user["role"],
            "job_title": (user.get("profile") or {}).get("job_title") or "",
            "unit": (user.get("profile") or {}).get("unit") or "",
            "groups": memberships.get(user["username"], []),
        }
        for user in rt.workspace.users.list_users(kind="person")
    ]


@router.get("/groups")
def groups(_caller: V1Reader, rt: Runtime) -> list[dict[str, Any]]:
    """Every group: id, name, kind, the asset it covers, its coordinator, the group it sits
    under and its members."""

    return [
        {
            "id": group["group_id"],
            "name": group["name"],
            "kind": group["kind"],
            "description": group["description"],
            "asset_id": group["asset_id"],
            "coordinator": group["coordinator"],
            "parent_id": group["parent_id"],
            "members": [member["username"] for member in group["members"] if member["active"]],
        }
        for group in rt.workspace.groups.list()
    ]


@router.get("/notifications")
def notification_settings(_caller: V1Reader, rt: Runtime) -> dict[str, Any]:
    """What a notification can reach now: ``email`` when an administrator set up the email
    server (Setup, Email), so an app offers email only where it can go out."""

    return {"email": bool(rt.notifications.store.settings().ready)}


def _safe_url(url: str | None) -> str | None:
    """A path of the suite only: a notification never sends people to another site."""

    if not url:
        return None
    value = url.strip()
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        raise HTTPException(
            status_code=422, detail=t("The link is a path of the suite, like /alarm/.")
        )
    return value


@router.post("/notifications")
def notify(payload: NotificationRequest, caller: V1Caller, rt: Runtime) -> dict[str, Any]:
    """Delivers a notification; ``{"delivered", "email_queued", "unknown"}``."""

    app_id = caller.app_id
    if app_id is None:
        raise HTTPException(
            status_code=403, detail=t("Only an app's service token sends notifications.")
        )
    name = rt.app_names().get(app_id, app_id)
    try:
        return rt.notifications.notify(
            app_id,
            name,
            recipients=payload.recipients,
            title=payload.title.strip(),
            text=payload.text.strip(),
            priority=payload.priority,
            url=_safe_url(payload.url),
            email=payload.email,
            refs=payload.refs,
            key=payload.key,
            category=payload.category,
            actions=[_action(action, app_id) for action in payload.actions],
        )
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _action(action: NotificationAction, app_id: str) -> dict[str, Any]:
    """A button as stored. A call (POST) reaches only the app that sent it: a path under its own
    prefix, so a notification never makes a person act in another app."""

    href = _safe_url(action.href)
    if action.method == "POST":
        prefix = next((item.url for item in suite_apps() if item.id == app_id), None)
        base = f"{prefix.rstrip('/')}/" if prefix and prefix.startswith("/") else None
        if not base or not href or not href.startswith(base) or ".." in href.split("/"):
            raise HTTPException(
                status_code=422,
                detail=t(
                    "A button that runs a call must point to this app's own paths ({prefix}).",
                    prefix=base or "-",
                ),
            )
    return {"label": action.label.strip(), "href": href, "method": action.method}


@router.post("/notifications/resolve")
def resolve(payload: NotificationResolve, caller: V1Caller, rt: Runtime) -> dict[str, Any]:
    """Settles a notification thread for everyone who received it (an alarm acknowledged or
    cleared): it leaves their unread count and shows ``note`` instead of its buttons.
    ``{"key", "resolved_at", "note"}``."""

    if caller.app_id is None:
        raise HTTPException(
            status_code=403, detail=t("Only an app's service token resolves notifications.")
        )
    return rt.notifications.resolve(caller.app_id, payload.key.strip(), payload.note.strip())
