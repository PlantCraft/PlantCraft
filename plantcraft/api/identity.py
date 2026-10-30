"""API v1 identity: issuing tokens, the ``processcraft_token`` cookie and verifying callers.

The session cookie stays PlantCraft's own; the token cookie is what the apps
of the suite read (same origin behind the proxy). See ``docs/api-v1.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, Response, status

from plantcraft.api.deps import Runtime, demo_visit, session_user, user_access
from plantcraft.auth.public_demo import public_demo
from plantcraft.auth.suite import FORMER_IDS, app_access
from plantcraft.config import env_flag
from plantcraft.i18n import t
from plantcraft.platform.asset_scope import CLAIM, AssetScope, scope_roots
from plantcraft_sdk import jwt
from plantcraft_sdk.contract import (
    SERVICE_TOKEN_SECONDS,
    TOKEN_COOKIE,
    USER_TOKEN_SECONDS,
)

READ_LEVELS = {"viewer", "editor", "admin"}
# A public demo visit's tokens live this long at most: the frame renews them every minute, so a
# visit that ended or gave its place up loses the apps soon (docs/public-demo.md).
DEMO_TOKEN_SECONDS = 120


def expires_at(stamp: int) -> str:
    return datetime.fromtimestamp(stamp, tz=timezone.utc).isoformat()


def user_claims(rt: Any, username: str) -> dict[str, Any] | None:
    """Name, level and apps of a person, or None when they may not sign in."""

    access = user_access(rt, username)
    if access is None:
        return None
    user = rt.workspace.users.get_user(username) or {}
    fallback = "Administrator" if access.is_admin else username
    claims: dict[str, Any] = {
        "name": user.get("display_name") or fallback,
        "level": access.level,
        "apps": app_access(access, rt.suite_apps()),
    }
    # The roots of the asset tree the person sees (docs/asset-scope.md); absent: all of it.
    roots = None if access.is_admin else scope_roots(rt.workspace, username)
    if roots is not None:
        claims[CLAIM] = list(roots)
    return claims


def visible_apps(rt: Any, username: str) -> set[str]:
    """The apps whose published results, events and runs ``username`` may read: those they may
    open (and their former ids), plus the platform's own."""

    claims = user_claims(rt, username) or {"apps": {}}
    apps = set(claims["apps"])
    for app_id in list(apps):
        apps |= set(FORMER_IDS.get(app_id, ()))
    return apps | {"processcraft", "desk"}


def issue_user_token(
    rt: Any, username: str, *, ttl: int = USER_TOKEN_SECONDS, **extra: Any
) -> dict[str, str] | None:
    if username.startswith("app:"):
        # Only app keys get an ``app:`` subject (``issue_service_token``): never a person.
        return None
    claims = user_claims(rt, username)
    if claims is None:
        return None
    claims.update(extra)
    token, expiry = rt.tokens.issue(
        username,
        ttl=ttl,
        not_before=rt.workspace.users.tokens_valid_after(username),
        **claims,
    )
    return {"token": token, "expires_at": expires_at(expiry)}


def issue_service_token(rt: Any, app_id: str, key_id: str) -> dict[str, str]:
    token, expiry = rt.tokens.issue(
        f"app:{app_id}",
        ttl=SERVICE_TOKEN_SECONDS,
        name=app_id,
        level="viewer",
        apps={app_id: "viewer"},
        key_id=key_id,
    )
    return {"token": token, "expires_at": expires_at(expiry)}


def browser_user(request: Request, rt: Any) -> str | None:
    """Who the browser's session is. With sign-in off, the session's current user (the
    one the demo switched to, else the default user), so apps audit the same name."""

    return session_user(request, rt)


def set_token_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        TOKEN_COOKIE,
        token,
        max_age=USER_TOKEN_SECONDS,
        path="/",
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https" or env_flag("PLANTCRAFT_SESSION_HTTPS_ONLY"),
    )


def clear_token_cookie(response: Response) -> None:
    response.delete_cookie(TOKEN_COOKIE, path="/")


def refresh_browser_token(request: Request, response: Response, rt: Any) -> dict[str, str] | None:
    """A fresh user token for the browser's session, also set as the cookie."""

    username = browser_user(request, rt)
    if not username:
        return None
    visit = demo_visit(request, rt)
    if visit is not None:
        # A demo visit: short tokens, never past the visit's end, and the ``demo`` claim the apps
        # read (editors shown, nothing saved, requests held to a few at once).
        demo = public_demo()
        ttl = max(min(DEMO_TOKEN_SECONDS, visit.seconds_left()), 1)
        claim = demo.token_claim(visit.visit, visit.ends) if demo else {}
        grant = issue_user_token(rt, username, ttl=ttl, demo=claim)
    else:
        grant = issue_user_token(rt, username)
    if grant is not None:
        set_token_cookie(response, request, grant["token"])
    return grant


# Verifying callers -------------------------------------------------------------


@dataclass(frozen=True)
class Caller:
    username: str
    name: str
    level: str
    apps: dict[str, str]
    claims: dict[str, Any]

    @property
    def app_id(self) -> str | None:
        return self.username[4:] if self.username.startswith("app:") else None


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def bearer_token(request: Request) -> str:
    scheme, _, value = (request.headers.get("authorization") or "").partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return request.cookies.get(TOKEN_COOKIE) or ""


# A person's access token (``pcat_...``) reads API v1 from a notebook on their own computer
# (docs/en/notebooks.md): reads only, and the series reads, which are a POST. The one request a
# notebook may send: ask an app to run an object in its own queue (a simulation), which the app
# refuses unless its administrator switched notebook runs on (owner, 2026-10-26, D4). An app's
# assistant tool is a read sent as a POST too (``[[contributes.assistant.tools]]``, read-only).
_TOKEN_WRITES = {"/api/v1/series"}
_TOKEN_RUN = re.compile(r"^/api/v1/apps/[a-z][a-z0-9_-]{0,39}/objects/[a-z][a-z0-9-]{0,40}/run$")
_TOKEN_TOOL = re.compile(r"^/api/v1/apps/[a-z][a-z0-9_-]{0,39}/tools/[a-z][a-z0-9_]{1,40}$")


def _personal_caller(request: Request, rt: Any, token: str) -> Caller:
    if not rt.workspace.notebooks.enabled():
        raise _unauthorized(
            t("Notebooks are off: an administrator turns them on in PlantCraft › Notebooks.")
        )
    record = rt.workspace.assistant_access.verify(token)
    if record is None:
        raise _unauthorized(t("This access token was revoked or has expired."))
    path = request.url.path
    if (
        request.method not in {"GET", "HEAD"}
        and path not in _TOKEN_WRITES
        and not (request.method == "POST" and (_TOKEN_RUN.match(path) or _TOKEN_TOOL.match(path)))
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=t("An access token only reads.")
        )
    claims = user_claims(rt, record["username"])
    if claims is None:
        raise _unauthorized(t("This account is no longer active."))
    return Caller(
        username=record["username"],
        name=str(claims.get("name") or record["username"]),
        level=str(claims.get("level") or "viewer"),
        apps={str(key): str(value) for key, value in (claims.get("apps") or {}).items()},
        # When the token stops working: the Notebooks kit says so a week before.
        claims={**claims, "token_expires_at": record["expires_at"]},
    )


def v1_caller(request: Request, rt: Runtime) -> Caller:
    token = bearer_token(request)
    if not token:
        raise _unauthorized(t("Sign in to continue: no PlantCraft token was sent."))
    if token.startswith("pcat_"):
        return _personal_caller(request, rt, token)
    try:
        claims = rt.tokens.verify(token)
    except jwt.ExpiredToken as exc:
        raise _unauthorized(t("Your session expired. Sign in again.")) from exc
    except jwt.TokenError as exc:
        raise _unauthorized(t("The PlantCraft token was not accepted.")) from exc
    username = str(claims.get("sub") or "")
    if username.startswith("app:"):
        # A revoked app key ends its service tokens at once.
        if not rt.workspace.app_keys.is_active(str(claims.get("key_id") or "")):
            raise _unauthorized(t("This app key was revoked."))
        _hold_to_permissions(request, rt, username[4:])
    else:
        if rt.auth.enabled and username != rt.auth.username:
            user = rt.workspace.users.get_user(username)
            if not user or not user.get("active"):
                raise _unauthorized(t("This account is no longer active."))
        # Disabled, a new password or new access: tokens issued before that are ended.
        if int(claims.get("iat") or 0) < rt.workspace.users.tokens_valid_after(username):
            raise _unauthorized(t("Your access changed. Sign in again."))
    apps = claims.get("apps") if isinstance(claims.get("apps"), dict) else {}
    return Caller(
        username=username,
        name=str(claims.get("name") or username),
        level=str(claims.get("level") or "viewer"),
        apps={str(key): str(value) for key, value in apps.items()},
        claims=claims,
    )


def _hold_to_permissions(request: Request, rt: Any, app_id: str) -> None:
    """An app's own token uses only the routes its ``[permissions]`` name (scale review E4)."""

    scopes = getattr(rt, "app_scopes", None)
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if scopes is None or not path:
        return
    reason = scopes.refusal(app_id, request.method, path)
    if reason is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=t("This app may not do this: {reason}.", reason=reason),
        )


V1Caller = Annotated[Caller, Depends(v1_caller)]


def v1_reader(caller: V1Caller) -> Caller:
    """Plant data is for viewers and up; dashboards-only people read it through dashboards."""

    if caller.level not in READ_LEVELS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=t("Your access is limited to dashboards.")
        )
    return caller


V1Reader = Annotated[Caller, Depends(v1_reader)]


def v1_scope(request: Request, caller: V1Caller, rt: Runtime) -> AssetScope:
    """The assets the caller sees (docs/asset-scope.md), once per request: a person's from the
    database (never the claim alone), an app's own token the whole plant."""

    cached = getattr(request.state, "asset_scope", None)
    if cached is None:
        cached = request.state.asset_scope = rt.asset_scope(caller.username)
    return cached


V1Scope = Annotated[AssetScope, Depends(v1_scope)]
