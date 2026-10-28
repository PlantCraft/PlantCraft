"""A public demo's visits in an app: editors shown, nothing saved, a few requests at once.

PlantCraft's public demo (docs/public-demo.md) gives each visit tokens with a ``demo`` claim::

    {"visit": "<id>", "ends": <unix seconds>, "queries": 2, "queries_total": 4}

The visitor stays a viewer: every write an app guards with ``EditorUser`` is refused, with a
message that says nothing is saved. ``/api/me`` still says ``can_edit``, so the interface shows its
editors and the visitor can try everything. ``DemoVisitLimit`` (added by ``web.mount``) holds a
visit to ``queries`` requests in flight in this app, and every visit together to
``queries_total``: a visitor clicking around never slows the demo for the others. A request over
the limit waits its turn, up to ``WAIT_SECONDS``, then gets a 429.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from plantcraft_sdk import jwt
from plantcraft_sdk.contract import TOKEN_COOKIE
from plantcraft_sdk.i18n import t

CLAIM = "demo"
WAIT_SECONDS = 30.0


def demo_of(claims: dict[str, Any] | None) -> dict[str, Any] | None:
    """The ``demo`` claim of a public demo visit's token, else None."""

    value = (claims or {}).get(CLAIM)
    return value if isinstance(value, dict) and value.get("visit") else None


def _number(value: Any, default: int, high: int) -> int:
    try:
        return min(max(int(value), 1), high)
    except (TypeError, ValueError):
        return default


def _token(scope: dict[str, Any]) -> str:
    headers = {key.decode("latin-1").lower(): value for key, value in scope.get("headers") or ()}
    scheme, _, value = headers.get("authorization", b"").decode("latin-1").partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    for part in headers.get("cookie", b"").decode("latin-1").split(";"):
        name, _, value = part.strip().partition("=")
        if name == TOKEN_COOKIE:
            return value.strip().strip('"')
    return ""


def _claimed(scope: dict[str, Any]) -> dict[str, Any] | None:
    """The demo claim the request's token says it has, before any check of its signature.

    Enough to count: a token whose claims were changed is refused by the route anyway (401), so
    leaving the claim out of a forged token wins nothing, and adding it only slows the forger.
    """

    token = _token(scope)
    if not token:
        return None
    try:
        return demo_of(jwt.unverified_claims(token))
    except (jwt.TokenError, ValueError, json.JSONDecodeError):
        return None


class DemoVisitLimit:
    """ASGI middleware: a demo visit's requests to this app's API, a few in flight at once."""

    def __init__(self, app: Any, wait_seconds: float = WAIT_SECONDS):
        self.app = app
        self.wait_seconds = wait_seconds
        # Visit -> (its own places, requests holding or waiting for one).
        self._visits: dict[str, list[Any]] = {}
        self._shared: asyncio.Semaphore | None = None
        self._shared_size = 0

    def _shared_for(self, size: int) -> asyncio.Semaphore:
        if self._shared is None or size != self._shared_size:
            self._shared, self._shared_size = asyncio.Semaphore(size), size
        return self._shared

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        demo = (
            _claimed(scope)
            if scope["type"] == "http" and "/api/" in scope.get("path", "")
            else None
        )
        if demo is None:
            await self.app(scope, receive, send)
            return
        visit = str(demo["visit"])[:64]
        entry = self._visits.setdefault(
            visit, [asyncio.Semaphore(_number(demo.get("queries"), 2, 32)), 0]
        )
        entry[1] += 1
        shared = self._shared_for(_number(demo.get("queries_total"), 4, 512))
        held: list[asyncio.Semaphore] = []
        try:
            for place in (entry[0], shared):
                try:
                    await asyncio.wait_for(place.acquire(), self.wait_seconds)
                except asyncio.TimeoutError:
                    await self._busy(scope, receive, send)
                    return
                held.append(place)
            await self.app(scope, receive, send)
        finally:
            for place in held:
                place.release()
            entry[1] -= 1
            if entry[1] <= 0:
                self._visits.pop(visit, None)

    @staticmethod
    async def _busy(scope: Any, receive: Any, send: Any) -> None:
        from starlette.responses import JSONResponse

        response = JSONResponse(
            {"detail": t("The demo is busy right now. Try again in a moment.")},
            status_code=429,
            headers={"Retry-After": "5"},
        )
        await response(scope, receive, send)


__all__ = ["CLAIM", "DemoVisitLimit", "demo_of"]
