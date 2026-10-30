"""Reads PlantCraft forwards to an app for a person: their objects, examples and runtime.

A notebook reads an app's objects through API v1 (``/api/v1/apps/<app>/objects/<kind>``) with
the person's access token, which only PlantCraft knows. PlantCraft checks the token and the
person's access to the app, then asks the app inside the suite's network with a short token of
its own for that person, the same signed identity the app's pages carry: an app never sees an
access token, and answers with its own access checks. Only ``GET`` under the app's
``api/objects/`` and ``api/notebooks/``, and ``POST api/objects/<kind>/run`` for a kind that runs
in the app (``run = "app"``: a simulation), which the app allows only when its administrator
switched it on. An app's assistant tool (``[[contributes.assistant.tools]]``) is called with
``POST api/assistant/tools/<id>`` (``post_tool``), a read the app answers with its own access.
A first step the app takes for a new plant (``[[contributes.start]]``) is ``POST api/start/<id>``
(``post_start``), sent for the administrator who takes it on Assets › Import.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any

import httpx

from plantcraft.watch.recorder import server_urls

TIMEOUT = httpx.Timeout(30.0, connect=5.0)
# What a forwarded read may bring back (a runtime is a few MB of code).
MAX_BYTES = 50 * 1024 * 1024
ALLOWED = ("api/objects/", "api/notebooks/")
RUN_KIND = re.compile(r"^[a-z][a-z0-9-]{0,40}$")
TOOL_ID = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
START_ID = re.compile(r"^[a-z][a-z0-9-]{0,40}$")
# A start step writes many objects at once (a plant's signals, its dashboards).
START_TIMEOUT = httpx.Timeout(300.0, connect=5.0)
# Examples change with the app's version: kept this long, then asked again.
CACHE_SECONDS = 60.0


class AppUnreachable(Exception):
    """The app does not answer inside the suite's network (stopped, not installed)."""


@dataclass(frozen=True)
class Answer:
    status: int
    body: bytes
    content_type: str
    headers: dict[str, str]

    def json(self) -> Any:
        import json

        return json.loads(self.body or b"null")


def transport() -> httpx.BaseTransport | None:
    """The HTTP transport (tests replace it with the apps they fake)."""

    return None


def app_base(app: str) -> str | None:
    """Where ``app`` answers inside the suite's network, with its prefix (``…/link``)."""

    return server_urls().get(app)


def get(
    rt: Any,
    app: str,
    path: str,
    username: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Answer:
    """``GET <app>/<path>`` as ``username``. ``path`` is under ``api/objects/`` or
    ``api/notebooks/``; ``AppUnreachable`` when the app does not answer."""

    path = path.lstrip("/")
    if not path.startswith(ALLOWED) or ".." in path.split("/"):
        raise ValueError(f"PlantCraft forwards only {', '.join(ALLOWED)} to an app")
    return _send(rt, app, "GET", path, username, params=params, headers=headers)


def post_run(rt: Any, app: str, kind: str, username: str, body: dict[str, Any]) -> Answer:
    """``POST <app>/api/objects/<kind>/run`` as ``username``: the one write a notebook asks of an
    app (a simulation in its queue), which the app allows or refuses itself."""

    if not RUN_KIND.match(kind):
        raise ValueError("not a kind of object")
    return _send(rt, app, "POST", f"api/objects/{kind}/run", username, json=body)


def post_tool(rt: Any, app: str, tool_id: str, username: str, arguments: dict[str, Any]) -> Answer:
    """``POST <app>/api/assistant/tools/<id>`` as ``username``: one of the read-only tools the app
    adds to the assistant, with the arguments PlantCraft checked against its declaration."""

    if not TOOL_ID.match(tool_id):
        raise ValueError("not a tool id")
    return _send(rt, app, "POST", f"api/assistant/tools/{tool_id}", username, json=arguments)


def post_start(rt: Any, app: str, step_id: str, username: str, body: dict[str, Any]) -> Answer:
    """``POST <app>/api/start/<id>`` as ``username``: one of the app's first steps for the assets
    an import wrote (``plantcraft_sdk.contributes.StartIn``), which the app does with its own
    access checks."""

    if not START_ID.match(step_id):
        raise ValueError("not a start step")
    return _send(
        rt, app, "POST", f"api/start/{step_id}", username, json=body, timeout=START_TIMEOUT
    )


def _send(
    rt: Any,
    app: str,
    method: str,
    path: str,
    username: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    json: Any = None,
    timeout: httpx.Timeout = TIMEOUT,
) -> Answer:
    from plantcraft.api.identity import issue_user_token

    base = app_base(app)
    if not base:
        raise AppUnreachable(app)
    issued = issue_user_token(rt, username)
    if issued is None:
        return Answer(
            403, b'{"detail": "This person may not read this app."}', "application/json", {}
        )
    sent = {"Authorization": f"Bearer {issued['token']}", **(headers or {})}
    try:
        with httpx.Client(timeout=timeout, transport=transport(), follow_redirects=False) as client:
            with client.stream(
                method, f"{base.rstrip('/')}/{path}", params=params, headers=sent, json=json
            ) as answer:
                body = bytearray()
                for chunk in answer.iter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        raise AppUnreachable(f"{app} sent more than {MAX_BYTES} bytes")
                kept = {
                    key: answer.headers[key]
                    for key in ("etag", "x-runtime-sha256", "content-disposition")
                    if key in answer.headers
                }
                return Answer(
                    answer.status_code,
                    bytes(body),
                    answer.headers.get("content-type", "application/json"),
                    kept,
                )
    except httpx.HTTPError as exc:
        raise AppUnreachable(f"{app}: {type(exc).__name__}") from exc


class Cached:
    """Answers kept for ``CACHE_SECONDS`` by key: the same for every person (examples)."""

    def __init__(self, seconds: float = CACHE_SECONDS):
        self.seconds = seconds
        self._items: dict[Any, tuple[float, Any]] = {}
        self._lock = Lock()

    def get(self, key: Any, read: Any) -> Any:
        now = time.monotonic()
        with self._lock:
            found = self._items.get(key)
            if found and now - found[0] < self.seconds:
                return found[1]
        value = read()
        with self._lock:
            self._items[key] = (now, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


__all__ = [
    "Answer",
    "AppUnreachable",
    "Cached",
    "app_base",
    "get",
    "post_run",
    "post_tool",
    "transport",
]
