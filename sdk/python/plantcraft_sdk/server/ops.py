"""What every server of the suite tells the monitor: requests, logs and uptime.

``RequestLog`` wraps the whole application (``mount`` adds it): it gives each request an id
(the proxy's ``X-Request-ID``, else a new one), sends it back in the answer, logs one line per
request with its status and duration, and counts requests and server errors. ``metrics()`` is
what ``GET /api/ops/metrics`` answers, read by PlantCraft's monitor with a token that carries
the ``ops`` scope (``docs/operations.md``). An app with a work queue names what it holds now
with ``report_queue``: the metrics then carry it, PlantCraft records it as signals and tells
the administrators when the queue does not drain. An app without an app key names the
conditions it has open now with ``report_conditions`` (``plantcraft_sdk.events.Condition``):
the metrics carry them and the app's event catalog, and PlantCraft writes them as the app's
events.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from plantcraft_sdk.events import MAX_CONDITIONS, Condition
from plantcraft_sdk.server import logs

LOGGER = logging.getLogger("processcraft.requests")
# The scope PlantCraft's monitor puts in its tokens; an admin may read the metrics too.
OPS_SCOPE = "ops"
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_QUIET = ("/healthz",)
_STARTED = time.time()
_lock = threading.Lock()
_requests = {"total": 0, "server_errors": 0}
_durations: deque[float] = deque(maxlen=1000)
# What the metrics carry of a queue (``plantcraft_sdk.server.queue.QueueNow``).
QUEUE_KEYS = ("queued", "running", "workers", "delay_seconds", "done_hour", "failed_hour")
_queue: Callable[[], Any] | None = None
_conditions: Callable[[], Any] | None = None
# The app's event catalog (``EventCatalog.to_json()``), carried for PlantCraft when the app
# cannot send it itself (no app key).
_catalog: list[dict[str, Any]] | None = None
# What the app adds to PlantCraft (``contributes.contributions``), carried the same way.
_contributions: dict[str, Any] | None = None


def _record(status: int, seconds: float) -> None:
    with _lock:
        _requests["total"] += 1
        _requests["server_errors"] += status >= 500
        _durations.append(seconds)


def report_queue(source: Callable[[], Any] | None) -> None:
    """Name what the app's queue holds now: a callable answering a ``QueueNow`` (or its dict);
    None stops reporting."""

    global _queue
    _queue = source


def report_conditions(source: Callable[[], Any] | None) -> None:
    """Name the conditions the app has open now: a callable answering ``Condition`` items (or
    their dicts), asked on each read of the metrics; None stops reporting."""

    global _conditions
    _conditions = source


def report_catalog(catalog: list[dict[str, Any]] | None) -> None:
    """The app's event catalog in the metrics (an app with no app key; ``send_event_catalog``)."""

    global _catalog
    _catalog = list(catalog) if catalog is not None else None


def report_contributions(body: dict[str, Any] | None) -> None:
    """What the app adds to PlantCraft in the metrics (an app with no app key;
    ``send_contributions``)."""

    global _contributions
    _contributions = dict(body) if body is not None else None


def _conditions_now() -> list[dict[str, Any]] | None:
    source = _conditions
    if source is None:
        return None
    try:
        items = list(source() or [])
    except Exception:  # the metrics still answer; PlantCraft keeps what it knew
        LOGGER.exception("reading the open conditions for the metrics failed")
        return None
    found: list[dict[str, Any]] = []
    for item in items[:MAX_CONDITIONS]:
        try:
            condition = item if isinstance(item, Condition) else Condition.model_validate(item)
        except ValidationError as exc:
            LOGGER.warning("open condition left out of the metrics: %s", exc.errors()[0]["msg"])
            continue
        found.append(condition.model_dump(mode="json", exclude_none=True))
    return found


def _queue_now() -> dict[str, Any] | None:
    source = _queue
    if source is None:
        return None
    try:
        now = source()
    except Exception:  # the metrics still answer without the queue
        LOGGER.exception("reading the queue for the metrics failed")
        return None
    data = now.as_dict() if hasattr(now, "as_dict") else dict(now or {})
    return {key: data.get(key) for key in QUEUE_KEYS}


def metrics(app: str, version: str) -> dict[str, Any]:
    """Counters since this process started (the monitor turns them into rates), and the queue
    when the app reports one."""

    with _lock:
        requests = dict(_requests)
        durations = sorted(_durations)
    p95 = durations[min(len(durations) - 1, int(len(durations) * 0.95))] if durations else 0.0
    answer = {
        "app": app,
        "version": version,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(_STARTED)),
        "uptime_s": round(time.time() - _STARTED, 1),
        "logs": logs.counts(),
        "requests": {**requests, "p95_ms": round(p95 * 1000, 1)},
    }
    queue = _queue_now()
    if queue is not None:
        answer["queue"] = queue
    conditions = _conditions_now()
    if conditions is not None:
        answer["conditions"] = conditions
    if _catalog is not None:
        answer["events"] = _catalog
    if _contributions is not None:
        answer["contributions"] = _contributions
    return answer


def can_read_metrics(user: Any) -> bool:
    """An admin, or PlantCraft's monitor (a token with the ``ops`` scope)."""

    claims = getattr(user, "claims", None) or {}
    return bool(getattr(user, "is_admin", False) or claims.get("scope") == OPS_SCOPE)


class RequestLog:
    """ASGI middleware: request id, one log line and the counters per HTTP request."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        given = ""
        for name, value in scope.get("headers") or ():
            if name == b"x-request-id":
                given = value.decode("latin-1")
                break
        request_id = given if _REQUEST_ID.match(given) else uuid.uuid4().hex
        token = logs.REQUEST_ID.set(request_id)
        started = time.perf_counter()
        status = 500

        async def answer(message: Any) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
                headers = [
                    item for item in message.get("headers", []) if item[0] != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, answer)
        finally:
            seconds = time.perf_counter() - started
            _record(status, seconds)
            path = scope.get("path", "")
            level = logging.DEBUG if path.endswith(_QUIET) and status < 400 else logging.INFO
            if status >= 500:
                # A warning: the error itself is logged where it happened.
                level = logging.WARNING
            LOGGER.log(
                level,
                "%s %s %s %.0f ms",
                scope.get("method", ""),
                path,
                status,
                seconds * 1000,
                extra={"status": status, "duration_ms": round(seconds * 1000, 1)},
            )
            logs.REQUEST_ID.reset(token)


__all__ = ["OPS_SCOPE", "RequestLog", "can_read_metrics", "metrics"]
