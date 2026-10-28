"""HTTP routes: the email server (Settings, administrators), each person's notification
preferences (docs/notifications.md) and Messages' Notifications (``/api/notifications``,
processcraft/api/feed.py)."""

from __future__ import annotations

import re
import smtplib
import ssl
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from processcraft.api.deps import AdminUser, CurrentUser, Runtime, marks_owner, open_to
from processcraft.api.feed import mark_key, notification_feed
from processcraft.auth.users import is_email
from processcraft.i18n import t

router = APIRouter()

Priority = Literal["critical", "high", "medium", "low"]


class MailPayload(BaseModel):
    enabled: bool = False
    host: str = Field(default="", max_length=253)
    port: int = Field(default=587, ge=1, le=65535)
    security: Literal["starttls", "tls", "none"] = "starttls"
    username: str = Field(default="", max_length=200)
    # Left empty: the stored password stays.
    password: str = Field(default="", max_length=500)
    clear_password: bool = False
    sender: str = Field(default="", max_length=200)
    verify_certificate: bool = True


class MailTest(BaseModel):
    to: str = Field(default="", max_length=200)


class Preferences(BaseModel):
    email: bool = True
    email_min_priority: Priority = "high"


@router.get("/api/mail")
def mail(_admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """The email server's settings (never its password) and the outbox's counts."""

    return rt.notifications.public_settings()


@router.put("/api/mail")
def save_mail(payload: MailPayload, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    try:
        saved = rt.notifications.save_settings(payload.model_dump(), admin)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    detail = payload.model_dump(exclude={"password"})
    detail["password_changed"] = bool(payload.password) or payload.clear_password
    rt.workspace.audit.record(admin, "mail.settings", "mail", detail, app_id="processcraft")
    return saved


@router.post("/api/mail/test")
def test_mail(payload: MailTest, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """Sends a test email now: to the address given, else to the administrator's own."""

    to = payload.to.strip() or (
        ((rt.workspace.users.get_user(admin) or {}).get("profile") or {}).get("email") or ""
    )
    if not is_email(to):
        raise HTTPException(
            status_code=422,
            detail=t("Enter the address to send to, or add your email to your profile."),
        )
    try:
        rt.notifications.test(to)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (OSError, smtplib.SMTPException, ssl.SSLError) as exc:
        return {"sent": False, "to": to, "error": str(exc) or type(exc).__name__}
    return {"sent": True, "to": to}


@router.get("/api/me/notifications")
@open_to("dashboards")
def my_notifications(user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    return {
        **rt.notifications.preferences(user),
        "email_ready": rt.notifications.store.settings().ready,
    }


@router.put("/api/me/notifications")
@open_to("dashboards")
def save_my_notifications(payload: Preferences, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    saved = rt.notifications.set_preferences(user, payload.model_dump())
    return {**saved, "email_ready": rt.notifications.store.settings().ready}


# Messages' Notifications ------------------------------------------------------------------------


class Marks(BaseModel):
    keys: list[str] = Field(min_length=1, max_length=300)
    # read, archived, or back to unread (null).
    state: Literal["read", "archived"] | None = None


@router.get("/api/notifications")
def notifications_feed(request: Request, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """What came to the person besides conversations, newest first: apps' notifications (one
    thread per app and key), changes others made to their actions, alarms on what they follow."""

    items = notification_feed(rt, user, marks_owner(request, rt, user))
    counts = {
        state: sum(1 for item in items if item["state"] == state)
        for state in ("unread", "read", "archived")
    }
    return {"items": items, "counts": counts}


@router.post("/api/notifications/marks")
@open_to("viewer")
def mark_notifications(
    payload: Marks, request: Request, user: CurrentUser, rt: Runtime
) -> dict[str, Any]:
    """Read, done (archived) or unread again. A thread with a newer event comes back as unread.
    A public demo visit marks for itself only."""

    owner = marks_owner(request, rt, user)
    state = {"read": "read", "archived": "done", None: "unread"}[payload.state]
    for key in dict.fromkeys(item.strip() for item in payload.keys if item.strip()):
        rt.desk.set_triage(owner, key[:300], state)
    return {"state": payload.state, "keys": len(payload.keys)}


# Favorites and unread again (owner, 2026-10-28) -------------------------------------------------

# A notification (``notice:``, ``action:``, ``result:``), a conversation or an assistant chat.
MARK_KEY = re.compile(r"^(notice|action|result):.{1,290}$|^(conversation|chat):\d{1,12}$")


class PersonMark(BaseModel):
    key: str = Field(min_length=1, max_length=300)
    mark: Literal["star", "unread"]
    on: bool = True


@router.put("/api/me/marks")
@open_to("viewer")
def set_mark(
    payload: PersonMark, request: Request, user: CurrentUser, rt: Runtime
) -> dict[str, Any]:
    """Mark a notification, a conversation or an assistant chat as a favorite, or a conversation
    or a chat as unread until it is opened again. Only for the person (a demo visit: the visit)."""

    key = payload.key.strip()
    if not MARK_KEY.match(key):
        raise HTTPException(status_code=422, detail=t("That cannot be marked."))
    if payload.mark == "unread" and not key.startswith(("conversation:", "chat:")):
        raise HTTPException(status_code=422, detail=t("That cannot be marked."))
    rt.desk.set_mark(marks_owner(request, rt, user), mark_key(key), payload.mark, payload.on)
    return {"key": mark_key(key), "mark": payload.mark, "on": payload.on}
