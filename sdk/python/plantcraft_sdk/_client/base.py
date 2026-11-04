"""The errors ``PlantCraftClient`` raises, by status, and what its calls share: timeouts and small helpers."""

from __future__ import annotations

import time
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

try:
    import httpx
except ImportError:  # An app's notebook runtime (server/objects.py) reads only the errors here.
    httpx = None  # type: ignore[assignment]


# A series read waits its turn for the Historian's read budget (``HISTCRAFT_QUERY_TIMEOUT``, 30 s)
# and may then run as long again, and PlantCraft waits 75 s for the Historian: a client that gave
# up at 15 s asked again while its first read still ran, and a busy Historian never caught up
# (Analytics rounds failing with "timed out" on the demo, 2026-10-29).
SERIES_TIMEOUT = 90.0


# A language model may take a while to write its answer.
LLM_TIMEOUT = 120.0


class PlantCraftError(Exception):
    """PlantCraft answered with an error, or could not be reached."""

    def __init__(self, message: str, *, status_code: int | None = None, detail: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail if detail is not None else message


class BadRequest(PlantCraftError):
    """4xx other than the ones below: the request breaks the contract (bad window, step...)."""


class Unauthorized(PlantCraftError):
    """401: no token, or it expired or was not accepted."""


class Forbidden(PlantCraftError):
    """403: the user (or app) may not do this."""


class NotFound(PlantCraftError):
    """404: no such asset or signal."""


class DemoVisitWrite(Forbidden):
    """A write to PlantCraft with the app's own key during an isolated demo visit
    (``plantcraft_sdk.server.demo_slots``): refused here, so a visit's play never reaches what
    everyone else sees."""


# Requests that only read although they are not a GET (a series read with its list of signals,
# a model asked a question): a demo visit may still send them.
DEMO_READS = (("POST", "/api/v1/series"), ("POST", "/api/v1/llm/"))


def _demo_visit_write(method: str, path: str) -> bool:
    """A write with the app's key during an isolated demo visit."""

    from plantcraft_sdk.server import demo_slots

    if demo_slots.visit_key() is None:
        return False
    for read_method, prefix in DEMO_READS:
        if method == read_method and (
            path == prefix or (prefix.endswith("/") and path.startswith(prefix))
        ):
            return False
    return True


class Unavailable(PlantCraftError):
    """PlantCraft or its data source could not answer (connection error, timeout, 5xx)."""


def error_for(status_code: int, detail: Any, reason: str = "") -> PlantCraftError:
    """The typed error for an HTTP status and the server's ``detail`` (also per batch signal)."""

    if isinstance(detail, list):
        text = "; ".join(str(item.get("msg", item)) for item in detail if isinstance(item, dict))
    else:
        text = str(detail) if detail else reason or "error"
    message = f"PlantCraft answered {status_code}: {text}"
    kind = {401: Unauthorized, 403: Forbidden, 404: NotFound}.get(status_code)
    if kind is None:
        kind = Unavailable if status_code >= 500 else BadRequest
    return kind(message, status_code=status_code, detail=detail)


def _error(response: httpx.Response) -> PlantCraftError:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    return error_for(response.status_code, detail, response.reason_phrase)


def _token_app(token: str | None) -> str | None:
    """The app a token belongs to, read without verifying it (only to tag audit records)."""

    if not token:
        return None
    from plantcraft_sdk import jwt

    try:
        claims = jwt.unverified_claims(token)
    except (jwt.TokenError, ValueError):
        return None
    subject = str(claims.get("sub") or "")
    return subject[4:] if subject.startswith("app:") and len(subject) > 4 else None


def _time(value: str | datetime | None) -> str | None:
    if value is None or isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _expiry(grant: Mapping[str, Any]) -> float:
    try:
        stamp = datetime.fromisoformat(str(grant.get("expires_at")).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.timestamp()
    except ValueError:
        return time.time() + 300
