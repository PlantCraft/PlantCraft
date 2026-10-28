"""HTTP routes: single sign-on with the company's OpenID Connect provider, and what the sign-in
page offers (docs/corporate-login.md). Open to anyone: these routes are how people sign in."""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from processcraft.api.deps import Runtime
from processcraft.api.identity import refresh_browser_token
from processcraft.api.routers.session import audit_sign_in, open_session
from processcraft.directory import DirectoryRefused, DirectoryUnavailable, new_flow
from processcraft.i18n import t

router = APIRouter()
LOGGER = logging.getLogger(__name__)
FLOW = "sso_flow"
ERROR = "sso_error"
# A sign-in started more than this long ago is not finished (the person left the provider's page).
FLOW_SECONDS = 600


def _safe_next(value: str | None) -> str:
    """A path on this site to land on after signing in; anything else lands on the home page."""

    text = (value or "").strip()
    if not text.startswith("/") or text.startswith("//") or "\\" in text or len(text) > 500:
        return "/"
    return text


@router.get("/api/sso/methods")
def methods(request: Request, rt: Runtime) -> dict[str, Any]:
    """The ways in the sign-in page shows, and why the last single sign-on failed (once)."""

    error = request.session.pop(ERROR, None)
    if not rt.auth.enabled:
        return {"ldap": False, "oidc": False, "oidc_label": None, "error": None}
    return {**rt.directory.methods(), "error": error if isinstance(error, str) else None}


def _fail(request: Request, message: str) -> RedirectResponse:
    # The reason stays in the signed session, never in the address: a link someone sends cannot
    # make the sign-in page show words of their choosing.
    request.session.pop(FLOW, None)
    request.session[ERROR] = message[:300]
    return RedirectResponse("/login?sso=failed", status_code=303)


@router.get("/api/sso/oidc/start")
def oidc_start(request: Request, rt: Runtime, next: str | None = None) -> RedirectResponse:
    """Sends the browser to the company's sign-in page."""

    settings = rt.directory.settings()
    if not rt.auth.enabled or not settings.method_enabled("oidc"):
        return _fail(request, t("Single sign-on is not turned on in this installation."))
    flow = new_flow()
    try:
        target = rt.directory.oidc(settings).authorization_url(flow)
    except DirectoryUnavailable as exc:
        LOGGER.warning("OIDC provider unavailable: %s", exc)
        return _fail(request, str(exc))
    request.session[FLOW] = {**flow, "next": _safe_next(next), "at": int(time.time())}
    return RedirectResponse(target, status_code=303)


@router.get("/api/sso/oidc/callback")
def oidc_callback(
    request: Request,
    rt: Runtime,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> RedirectResponse:
    """Where the provider sends the browser back: checks everything, then opens the session."""

    flow = request.session.get(FLOW)
    settings = rt.directory.settings()
    if not rt.auth.enabled or not settings.method_enabled("oidc"):
        return _fail(request, t("Single sign-on is not turned on in this installation."))
    if not isinstance(flow, dict) or not state or state != flow.get("state"):
        return _fail(request, t("This sign-in link is not valid anymore. Start again."))
    if time.time() - float(flow.get("at") or 0) > FLOW_SECONDS:
        return _fail(request, t("The sign-in took too long. Start again."))
    if error:
        reason = (error_description or error)[:200]
        return _fail(request, t("The company's sign-in page said: {reason}", reason=reason))
    if not code or len(code) > 4096:
        return _fail(request, t("This sign-in link is not valid anymore. Start again."))
    try:
        person = rt.directory.oidc(settings).finish(code, flow)
        username = rt.directory.sign_in(person, reserved={rt.auth.username})
    except DirectoryUnavailable as exc:
        LOGGER.warning("OIDC sign-in unavailable: %s", exc)
        audit_sign_in(
            rt, request, "-", "session.sign_in_failed", method="oidc", reason="unavailable"
        )
        return _fail(request, str(exc))
    except DirectoryRefused as exc:
        LOGGER.info("OIDC sign-in refused: %s", exc)
        audit_sign_in(
            rt, request, "-", "session.sign_in_failed", method="oidc", reason=str(exc)[:200]
        )
        return _fail(request, str(exc))
    target = _safe_next(flow.get("next"))
    audit_sign_in(rt, request, username, "session.sign_in", method="oidc")
    open_session(request, rt, username)
    response = RedirectResponse(target, status_code=303)
    refresh_browser_token(request, response, rt)
    return response
