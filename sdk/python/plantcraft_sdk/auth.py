"""Verify the PlantCraft token on every request of an app.

::

    verifier = TokenVerifier(os.environ["PLANTCRAFT_URL"], app_id="linkcraft")

    # FastAPI: one dependency per route (or per router)
    CurrentUser = Annotated[User, Depends(verifier.dependency)]

    # or Starlette/FastAPI: every request, with paths left open
    app.add_middleware(TokenMiddleware, verifier=verifier, public_paths=("/healthz",))
    ...
    user = current_user(request)

The token comes from ``Authorization: Bearer`` or the ``processcraft_token``
cookie. It is checked offline against PlantCraft's public keys (fetched from
``/api/v1/auth/keys``, cached, refreshed when an unknown ``kid`` shows up),
then ``apps[app_id]`` must grant access. A browser without a valid token is
sent to ``/login?next=<this page>``; API calls get JSON 401 (or 403).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any
from urllib.parse import quote

import httpx

from plantcraft_sdk import jwt
from plantcraft_sdk.contract import (
    CENTRAL_AUDIENCE,
    REVOKED_PATH,
    TOKEN_COOKIE,
    subject_digest,
)
from plantcraft_sdk.i18n import t

KEYS_PATH = "/api/v1/auth/keys"
KEYS_TTL_SECONDS = 600
# An unknown kid refreshes the key set at most this often (a flood of forged kids
# must not turn into a flood of requests to PlantCraft).
MIN_REFRESH_SECONDS = 10
# How often the list of tokens PlantCraft ended early is read again: a person disabled (or
# given a new password or access) is shut out of every app within this many seconds.
REVOKED_TTL_SECONDS = 10
# Tokens already verified, kept until they expire: checking the Ed25519 signature again on every
# request of a page cost about 0.2 ms each. Revocation is still checked on every request.
VERIFIED_CACHE_SIZE = 4096


class AuthError(Exception):
    """The request cannot be let in; ``status_code`` is 401, 403 or 503."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class User:
    """Who is calling, from a verified token."""

    username: str
    name: str
    level: str
    apps: dict[str, str]
    # This app's access: "editor" or "viewer".
    access: str
    token: str = field(repr=False)
    claims: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_service(self) -> bool:
        return self.username.startswith("app:")

    @property
    def can_edit(self) -> bool:
        return self.access == "editor"

    @property
    def is_admin(self) -> bool:
        return self.level == "admin"

    @property
    def demo(self) -> dict[str, Any] | None:
        """A public demo visit's ``demo`` claim (``plantcraft_sdk.server.demo``), else None."""

        value = self.claims.get("demo")
        return value if isinstance(value, dict) and value.get("visit") else None


class TokenVerifier:
    """Checks tokens for one app against PlantCraft's published keys."""

    def __init__(
        self,
        processcraft_url: str,
        app_id: str,
        *,
        http_client: httpx.Client | None = None,
        keys_ttl: float = KEYS_TTL_SECONDS,
        login_url: str = "/login",
        timeout: float = 10.0,
        leeway: float = jwt.LEEWAY_SECONDS,
    ):
        self.processcraft_url = processcraft_url.rstrip("/")
        self.app_id = app_id
        self.audiences = {app_id, CENTRAL_AUDIENCE}
        self.http = http_client or httpx.Client(timeout=timeout)
        self.keys_ttl = keys_ttl
        self.login_url = login_url
        self.leeway = leeway
        self._keys: dict[str, Any] | None = None
        self._fetched = 0.0
        self._forced = -float("inf")
        self._lock = threading.Lock()
        self.revoked_ttl = REVOKED_TTL_SECONDS
        self._revoked: tuple[dict[str, int], set[str], set[str]] = ({}, set(), set())
        self._revoked_at = -float("inf")
        self._revoked_lock = threading.Lock()
        # token -> (claims, exp, kid); insertion order is the eviction order.
        self._verified: dict[str, tuple[dict[str, Any], float, str]] = {}

    # Keys -------------------------------------------------------------------

    def keys(self, *, refresh: bool = False) -> dict[str, Any]:
        """The key set (``{"keys": [...]}``), fetched again after ``keys_ttl`` or when asked."""

        with self._lock:
            now = time.monotonic()
            stale = self._keys is None or now - self._fetched > self.keys_ttl
            forced = refresh and now - self._forced >= MIN_REFRESH_SECONDS
            if forced:
                self._forced = now
            if stale or forced:
                try:
                    response = self.http.get(f"{self.processcraft_url}{KEYS_PATH}")
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
                        raise ValueError("unexpected key set")
                except (httpx.HTTPError, ValueError) as exc:
                    if self._keys is None:
                        raise AuthError(
                            503,
                            t("PlantCraft's signing keys could not be read: {error}", error=exc),
                        ) from exc
                    # Keep verifying with the keys we have while PlantCraft is away.
                    return self._keys
                self._keys, self._fetched = payload, now
            return self._keys

    def revoked(self) -> tuple[dict[str, int], set[str], set[str]]:
        """``({sha256 of sub: not_before}, {revoked key ids}, {sha256 of signed-out sessions})``,
        read again every few seconds.

        When PlantCraft cannot be reached (or is older and has no list), the last list read
        stays in force: tokens still expire on their own.
        """

        with self._revoked_lock:
            now = time.monotonic()
            if now - self._revoked_at < self.revoked_ttl:
                return self._revoked
            self._revoked_at = now
            try:
                # Short: requests wait on this read while it runs.
                response = self.http.get(f"{self.processcraft_url}{REVOKED_PATH}", timeout=2.0)
                if response.status_code == 404:
                    return self._revoked
                response.raise_for_status()
                payload = response.json()
                users = {
                    str(item["sub_sha256"]): int(item["not_before"])
                    for item in payload.get("users") or []
                }
                keys = {str(item["key_id"]) for item in payload.get("keys") or []}
                # Sessions signed out (PlantCraft 0.6): their tokens carry the digest as ``sid``.
                sessions = {str(item["sid_sha256"]) for item in payload.get("sessions") or []}
            except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
                return self._revoked
            self._revoked = (users, keys, sessions)
            return self._revoked

    def check_revoked(self, claims: dict[str, Any]) -> None:
        """``AuthError(401)`` when PlantCraft ended this token before it expires."""

        users, keys, sessions = self.revoked()
        subject = str(claims.get("sub") or "")
        if subject.startswith("app:"):
            if str(claims.get("key_id") or "") in keys:
                raise AuthError(401, t("This app key was revoked."))
            return
        not_before = users.get(subject_digest(subject))
        if not_before is not None and int(claims.get("iat") or 0) < not_before:
            raise AuthError(401, t("Your access changed. Sign in again."))
        sid = claims.get("sid")
        if isinstance(sid, str) and sid and sid in sessions:
            raise AuthError(401, t("You signed out. Sign in again."))

    # Verification -----------------------------------------------------------

    def claims(self, token: str) -> dict[str, Any]:
        """The verified claims; raises ``AuthError(401)`` with the reason."""

        if not token:
            raise AuthError(401, t("Sign in to continue: no PlantCraft token was sent."))
        hit = self._verified.get(token)
        if hit is not None:
            claims, expires, kid = hit
            # Still before its expiry, and its key still published (a key PlantCraft dropped
            # ends its tokens as before).
            if time.time() <= expires + self.leeway and kid in jwt.key_ids(self.keys()):
                return dict(claims)
            self._verified.pop(token, None)
        try:
            try:
                claims = jwt.decode(token, self.keys(), self.audiences, leeway=self.leeway)
            except jwt.UnknownKey:
                claims = jwt.decode(
                    token, self.keys(refresh=True), self.audiences, leeway=self.leeway
                )
        except jwt.ExpiredToken as exc:
            raise AuthError(401, t("Your session expired. Sign in again.")) from exc
        except jwt.TokenError as exc:
            raise AuthError(
                401, t("The PlantCraft token was not accepted: {error}", error=exc)
            ) from exc
        if len(self._verified) >= VERIFIED_CACHE_SIZE:
            try:
                self._verified.pop(next(iter(self._verified)))
            except (StopIteration, KeyError, RuntimeError):
                pass
        kid = str(jwt.unverified_header(token).get("kid") or "")
        self._verified[token] = (dict(claims), float(claims.get("exp") or 0), kid)
        return claims

    def user(self, token: str) -> User:
        """The verified user, who must have access to this app (else ``AuthError(403)``)."""

        claims = self.claims(token)
        self.check_revoked(claims)
        apps = claims.get("apps") if isinstance(claims.get("apps"), dict) else {}
        access = apps.get(self.app_id)
        if access not in ("editor", "viewer"):
            raise AuthError(403, t("You do not have access to this application."))
        username = str(claims.get("sub") or "")
        return User(
            username=username,
            name=str(claims.get("name") or username),
            level=str(claims.get("level") or "viewer"),
            apps={str(key): str(value) for key, value in apps.items()},
            access=access,
            token=token,
            claims=claims,
        )

    # Requests ---------------------------------------------------------------

    @staticmethod
    def token_from(headers: Any, cookies: Any) -> str:
        """The bearer token, else the ``processcraft_token`` cookie, else ``""``."""

        header = headers.get("authorization") or ""
        scheme, _, value = header.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
        return cookies.get(TOKEN_COOKIE) or ""

    def login_redirect(self, path: str, query: str = "") -> str:
        target = f"{path}?{query}" if query else path
        return f"{self.login_url}?next={quote(target, safe='/')}"

    @cached_property
    def dependency(self) -> Any:
        """FastAPI dependency: ``Annotated[User, Depends(verifier.dependency)]``."""

        from fastapi import HTTPException
        from starlette.requests import Request

        def verify(request: Request) -> User:
            try:
                return self.user(self.token_from(request.headers, request.cookies))
            except AuthError as error:
                if error.status_code == 401 and wants_html(request.method, request.headers):
                    location = self.login_redirect(request.url.path, request.url.query)
                    raise HTTPException(
                        303, error.detail, headers={"Location": location}
                    ) from error
                headers = {"WWW-Authenticate": "Bearer"} if error.status_code == 401 else None
                raise HTTPException(error.status_code, error.detail, headers=headers) from error

        # Real objects, not strings: FastAPI reads them to inject the request.
        verify.__annotations__ = {"request": Request, "return": User}
        return verify


def wants_html(method: str, headers: Any) -> bool:
    """A browser navigating to a page (not a script calling an API)."""

    accept = headers.get("accept") or ""
    return method in ("GET", "HEAD") and "text/html" in accept


class TokenMiddleware:
    """ASGI middleware: every HTTP request outside ``public_paths`` needs a valid token.

    The user is kept in ``request.state.processcraft_user`` (read it with
    ``current_user(request)``). ``public_paths`` are exact paths or prefixes
    ending in ``/``.
    """

    def __init__(self, app: Any, verifier: TokenVerifier, public_paths: Iterable[str] = ()):
        self.app = app
        self.verifier = verifier
        self.public_paths = tuple(public_paths)

    def _public(self, path: str) -> bool:
        return any(
            path == item or (item.endswith("/") and path.startswith(item))
            for item in self.public_paths
        )

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or self._public(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        from anyio import to_thread
        from starlette.requests import Request
        from starlette.responses import JSONResponse, RedirectResponse

        request = Request(scope)
        token = self.verifier.token_from(request.headers, request.cookies)
        try:
            user = await to_thread.run_sync(self.verifier.user, token)
        except AuthError as error:
            if error.status_code == 401 and wants_html(request.method, request.headers):
                response: Any = RedirectResponse(
                    self.verifier.login_redirect(request.url.path, request.url.query),
                    status_code=303,
                )
            else:
                headers = {"WWW-Authenticate": "Bearer"} if error.status_code == 401 else None
                response = JSONResponse(
                    {"detail": error.detail}, status_code=error.status_code, headers=headers
                )
            await response(scope, receive, send)
            return
        scope.setdefault("state", {})["processcraft_user"] = user
        await self.app(scope, receive, send)


def current_user(request: Any) -> User:
    """The user ``TokenMiddleware`` verified for this request."""

    user = getattr(request.state, "processcraft_user", None)
    if user is None:
        raise AuthError(401, "This request was not verified by TokenMiddleware.")
    return user


__all__ = ["AuthError", "TokenMiddleware", "TokenVerifier", "User", "current_user", "wants_html"]
