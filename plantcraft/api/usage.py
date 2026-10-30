"""Limits on how much one person asks API v1 for (``plantcraft.auth.usage``, docs/en/notebooks.md).

Which requests count:

- every API v1 request sent with a person's access token (``pcat_...``): notebooks on the
  person's computer, scripts and assistants; one budget per token;
- the series reads (``/api/v1/series``, ``/api/v1/signals/<id>/series`` and ``/value``) that
  a person's browser sends through the suite's proxy, as a notebook in the browser does; one
  budget per person.

The proxy marks the requests it forwards from outside (``X-PlantCraft-Edge``, set by Caddy in
``deploy/proxy/Caddyfile``, whatever the client sent). The apps of the suite call PlantCraft
inside the internal network, without it: their reads, even those made with a person's forwarded
token for a dashboard, never count, so Link, Alarms and View never wait because a notebook is busy.

Over the limit the answer is 429 with ``Retry-After``; the ``plantcraft-notebook`` package waits
and asks again by itself. The first refusal of a minute for each budget goes to the audit log.
"""

from __future__ import annotations

import hashlib
import re
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from plantcraft.api.identity import bearer_token
from plantcraft.auth.usage import Refusal, UsageStore
from plantcraft.i18n import t

EDGE_HEADER = "x-plantcraft-edge"
SERIES = re.compile(r"^/api/v1/(series|signals/.+/(series|value))$")
# The limits an administrator saves reach every process within this many seconds.
SETTINGS_SECONDS = 10.0
# How many budgets each process remembers having audited this minute.
AUDITED_MAX = 1000


def budget_key(request: Request, rt: Any) -> str | None:
    """Whose budget this request spends, or None when it is not counted.

    A token is checked before it names a budget, so a forged one never spends someone else's.
    """

    path = request.url.path
    if not path.startswith("/api/v1/") or path.startswith("/api/v1/auth/"):
        return None
    token = bearer_token(request)
    if token.startswith("pcat_"):
        return "token:" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]
    if not token or request.headers.get(EDGE_HEADER) != "1" or not SERIES.match(path):
        return None
    if request.method not in {"GET", "HEAD", "POST"}:
        return None
    try:
        claims = rt.tokens.verify(token)
    except Exception:  # noqa: BLE001 - an unknown token is the route's 401, never counted here
        return None
    subject = str(claims.get("sub") or "")
    if not subject or subject.startswith("app:"):
        return None
    demo = claims.get("demo")
    if isinstance(demo, dict) and demo.get("visit"):
        # The visits of a public demo are one account: each visit has its own budget.
        return "visit:" + str(demo["visit"])
    return "person:" + subject


def _who(rt: Any, request: Request) -> str:
    token = bearer_token(request)
    try:
        if token.startswith("pcat_"):
            record = rt.workspace.assistant_access.verify(token)
            return str(record["username"]) if record else "unknown"
        return str(rt.tokens.verify(token).get("sub") or "unknown")
    except Exception:  # noqa: BLE001 - the audit line still says a request was refused
        return "unknown"


def _audit(rt: Any, request: Request, refusal: Refusal, limits: dict[str, Any]) -> None:
    detail = {"reason": refusal.reason, "per_minute": limits["per_minute"]}
    detail["concurrent"] = limits["concurrent"]
    rt.workspace.audit.record(
        _who(rt, request), "usage.limited", request.url.path, detail, app_id="processcraft"
    )


class UsageLimits:
    """The middleware's state in one process: the saved limits and who was audited."""

    def __init__(self, store: UsageStore):
        self.store = store
        self._settings: dict[str, Any] = {}
        self._read_at = 0.0
        self._audited: dict[str, float] = {}

    def limits(self) -> dict[str, Any]:
        now = time.monotonic()
        if not self._settings or now - self._read_at > SETTINGS_SECONDS:
            self._settings, self._read_at = self.store.settings(), now
        return self._settings

    def forget(self) -> None:
        """This process reads the limits again on its next counted request."""

        self._settings = {}

    def first_this_minute(self, key: str) -> bool:
        now = time.monotonic()
        if now - self._audited.get(key, -60.0) < 60.0:
            return False
        if len(self._audited) >= AUDITED_MAX:
            self._audited.clear()
        self._audited[key] = now
        return True


def refusal_answer(refusal: Refusal, limits: dict[str, Any]) -> JSONResponse:
    if refusal.reason == "busy":
        detail = t(
            "Wait for your previous read to finish: at most {limit} at once for each person.",
            limit=limits["concurrent"],
        )
    else:
        detail = t(
            "Too many requests: at most {limit} a minute for each person. "
            "Try again in {seconds} s.",
            limit=limits["per_minute"],
            seconds=refusal.retry_after,
        )
    return JSONResponse(
        status_code=429,
        content={"detail": detail, "reason": refusal.reason},
        headers={"Retry-After": str(refusal.retry_after)},
    )


def install_usage_limits(app: FastAPI, rt: Any) -> None:
    state = UsageLimits(rt.workspace.usage)
    app.state.usage_limits = state

    @app.middleware("http")
    async def usage_limits(request: Request, call_next):
        key = budget_key(request, rt)
        if key is None:
            return await call_next(request)
        limits = state.limits()
        slot = await run_in_threadpool(
            rt.workspace.usage.begin,
            key,
            per_minute=limits["per_minute"],
            concurrent=limits["concurrent"],
        )
        if isinstance(slot, Refusal):
            if state.first_this_minute(key):
                await run_in_threadpool(_audit, rt, request, slot, limits)
            return refusal_answer(slot, limits)
        try:
            return await call_next(request)
        finally:
            await run_in_threadpool(rt.workspace.usage.end, slot)
