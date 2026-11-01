"""HTTP routes: session (sign in, sign out and the current user)."""

from __future__ import annotations

import hmac
import logging
import math
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from plantcraft.api.deps import (
    Runtime,
    demo_visit,
    from_outside,
    password_fingerprint,
    session_user,
    user_access,
)
from plantcraft.api.identity import clear_token_cookie, refresh_browser_token
from plantcraft.api.routers.home import _version
from plantcraft.api.schemas import LoginPayload, SwitchUserPayload
from plantcraft.auth.public_demo import public_demo
from plantcraft.auth.sessions import new_session_id
from plantcraft.auth.throttle import address_key, pair_key
from plantcraft.directory import DirectoryRefused, DirectoryUnavailable, WrongCredentials
from plantcraft.i18n import t

router = APIRouter()
LOGGER = logging.getLogger(__name__)


def _session_payload(username: str | None, rt: Any, request: Request) -> dict[str, Any]:
    user = rt.workspace.users.get_user(username) if username else None
    visit = demo_visit(request, rt) if username else None
    access = user_access(rt, username)
    shown = access.as_dict() if access else None
    if shown is not None:
        # The administration pages this person reads: an administrator's, and the public demo
        # visitor's, read-only (api/deps.py, AdminView).
        visitor = (demo := public_demo()) is not None and username == demo.username
        shown["admin_view"] = bool(access and access.is_admin) or visitor
        # Temporary support access: when it ends (the shell says so).
        grant = rt.workspace.support_access.active(username) if username else None
        shown["support_until"] = grant["ends_at"] if grant else None
        # The companies this person sponsors at the plant: Operations › Partners opens for them.
        shown["sponsor_of"] = (
            [
                item["group_id"]
                for item in rt.workspace.groups.list()
                if item["kind"] == "company" and item.get("sponsor") == username
            ]
            if username
            else []
        )
    return {
        "authenticated": bool(username),
        "username": username,
        "display_name": (user or {}).get("display_name", username),
        "role": (user or {}).get("role"),
        "can_switch_user": not rt.auth.enabled,
        "is_admin": bool(access and access.is_admin),
        # Level (admin, editor, viewer, dashboards), applications (None: all) and
        # what the interface may offer; the API enforces the same rules.
        "access": shown,
        # A public demo offers "Enter the demo" on the sign-in page (its places and minutes).
        "public_demo": {
            **demo.as_dict(),
            # An update announced or under way: the sign-in page says so instead of "Enter".
            "updating": rt.workspace.demo_visits.update_at() is not None,
        }
        if (demo := public_demo())
        else None,
        # A visit of the public demo: its clock (shown all the time) and when it ends (the
        # clock, or sooner when unused).
        "demo_visit": {
            "clock_seconds": visit.clock_left(demo.minutes),
            "seconds_left": visit.seconds_left(),
            "minutes": demo.minutes,
            "idle_minutes": demo.idle_minutes,
        }
        if visit and demo
        else None,
        # The sign-in page names the installation: which plant, which version.
        "installation": {"name": rt.scenario.display_name, "version": _version()},
    }


@router.get("/api/session")
def session(request: Request, response: Response, rt: Runtime) -> dict[str, Any]:
    username = session_user(request, rt)
    if username:
        # The apps of the suite read this cookie (API v1); every page load renews it.
        refresh_browser_token(request, response, rt)
    return _session_payload(username, rt, request)


@router.post("/api/login")
def login(
    payload: LoginPayload, request: Request, response: Response, rt: Runtime
) -> dict[str, Any]:
    username = payload.username.strip().lower()
    demo = public_demo()
    if demo is not None and username == demo.username and from_outside(request):
        # From outside the visitor account is only a visit, which waits its turn (api/demo.py).
        raise HTTPException(
            status_code=403, detail=t("Use Enter the demo to visit the public demo.")
        )
    if rt.auth.enabled:
        # Failed sign-ins per name and address, and per address (plantcraft.auth.throttle):
        # the wait grows for one name typed wrong from one place, so nobody locks someone
        # else out from another address.
        address = request.client.host if request.client else "-"
        keys = [pair_key(username, address), address_key(address)]
        throttle = rt.workspace.login_throttle
        if (wait := throttle.wait(keys)) > 0:
            audit_sign_in(rt, request, username, "session.sign_in_blocked")
            raise HTTPException(
                status_code=429,
                detail=t("Too many attempts. Wait a few minutes and try again."),
                headers={"Retry-After": str(max(1, math.ceil(wait)))},
            )
        admin = hmac.compare_digest(_raw(username), _raw(rt.auth.username)) and hmac.compare_digest(
            _raw(payload.password), _raw(rt.auth.password)
        )
        local = (
            not admin
            and rt.directory.settings().local_passwords
            and rt.workspace.users.verify_password(username, payload.password, rehash=True)
        )
        if not admin and not local:
            # The company directory (LDAP or AD), when it is on: the name as typed there.
            try:
                found = _directory_login(payload.username.strip(), payload.password, rt)
            except HTTPException as exc:
                reason = "directory_unavailable" if exc.status_code == 503 else "refused"
                audit_sign_in(rt, request, username, "session.sign_in_failed", reason=reason)
                raise
            if found is None:
                throttle.record(keys)
                audit_sign_in(rt, request, username, "session.sign_in_failed", reason="password")
                raise HTTPException(status_code=401, detail=t("Incorrect username or password."))
            username = found
        ended = None if admin else rt.workspace.groups.access_ended(username)
        if ended:
            audit_sign_in(rt, request, username, "session.sign_in_failed", reason="access_ended")
            raise HTTPException(
                status_code=403,
                detail=t(
                    "Your company's access ended on {date}. Ask your sponsor at the plant to extend it.",
                    date=ended,
                ),
            )
        method = "admin" if admin else "local" if local else "ldap"
        audit_sign_in(rt, request, username, "session.sign_in", method=method)
    elif not rt.workspace.users.is_person(username):
        username = rt.default_user()
    open_session(request, rt, username)
    refresh_browser_token(request, response, rt)
    return _session_payload(username, rt, request)


def _raw(text: str) -> bytes:
    """Bytes to compare in constant time (``compare_digest`` refuses non-ASCII text)."""

    return text.encode("utf-8", "surrogatepass")


def audit_sign_in(rt: Any, request: Request, username: str, action: str, **detail: Any) -> None:
    """One ``session.*`` row of the audit log: who, from which address, and how or why not."""

    address = request.client.host if request.client else "-"
    name = username[:200] or "-"
    rt.workspace.audit.record(
        name, action, f"user:{name}", {"address": address, **detail}, app_id="processcraft"
    )


def open_session(request: Request, rt: Any, username: str) -> None:
    """A new session for ``username`` (any old one is dropped first: no session fixation)."""

    request.session.clear()
    request.session["cpm_username"] = username
    if rt.auth.enabled:
        # Its id goes on the list of ended sessions at sign-out (plantcraft.auth.sessions).
        request.session["cpm_sid"] = new_session_id()
        request.session["cpm_fp"] = password_fingerprint(rt, username)
        request.session["cpm_auth_at"] = int(time.time())


def _directory_login(typed: str, password: str, rt: Any) -> str | None:
    """The username the directory signed in, None for a wrong name or password."""

    settings = rt.directory.settings()
    if not settings.method_enabled("ldap"):
        return None
    name = typed.lower()
    if name == rt.auth.username:
        return None
    if rt.workspace.users.has_password(name) and rt.workspace.users.identity(name)[0] == "local":
        # Someone with a password here signs in with it, never as a directory namesake.
        return None
    try:
        return rt.directory.ldap_sign_in(typed, password, reserved={rt.auth.username})
    except DirectoryUnavailable as exc:
        LOGGER.warning("Directory sign-in unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=t(
                "The company directory did not answer. Try again in a moment, or ask your admin."
            ),
        ) from exc
    except WrongCredentials:
        return None
    except DirectoryRefused as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/api/session/switch")
def switch_user(
    payload: SwitchUserPayload, request: Request, response: Response, rt: Runtime
) -> dict[str, Any]:
    """Demo and local use only: act as another workspace user without a password."""

    if rt.auth.enabled:
        raise HTTPException(
            status_code=403, detail=t("Switching users is disabled: sign in with your password.")
        )
    if not rt.workspace.users.is_person(payload.username):
        raise HTTPException(status_code=404, detail=t("User not found."))
    request.session["cpm_username"] = payload.username
    # The apps' token follows the switch, so their audit rows name the same person.
    refresh_browser_token(request, response, rt)
    return _session_payload(payload.username, rt, request)


@router.post("/api/logout")
def logout(request: Request, response: Response, rt: Runtime) -> dict[str, bool]:
    username = request.session.get("cpm_username")
    if rt.auth.enabled and isinstance(username, str) and username:
        audit_sign_in(rt, request, username, "session.sign_out")
    if isinstance(sid := request.session.get("cpm_sid"), str) and sid:
        # A copy of this cookie stops working now, not when it would have expired.
        rt.workspace.ended_sessions.end(sid, 60 * 60 * 24 * rt.auth.session_days)
    if visit := request.session.get("demo_visit"):
        # A visitor who leaves gives their place to the next one.
        rt.workspace.demo_visits.leave(str(visit))
    request.session.clear()
    clear_token_cookie(response)
    return {"ok": True}
