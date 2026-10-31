"""The suite contract of API v1: results, events, runs and schedules (app standard, section 6).

How apps link: Analytics publishes each loop's health as a result on its asset and as a derived
series, its signals' quality as results and derived series, its findings as events, its
algorithm executions as runs and its schedules. Everything goes through PlantCraft with the
SDK client (``put_results``, ``put_series``, ``results``, ``post_events``, ``put_runs``,
``put_schedules``); references are written with ``plantcraft_sdk.refs``. Analytics never calls
another app.

This module only makes publishing optional: a PlantCraft that does not serve an endpoint yet
answers 404, so the call is skipped, logged once, and tried again an hour later; any other
failure is logged and dropped. A round never fails because of this module. Items PlantCraft
refuses one by one (an unknown subject, a bad url) are logged and the rest is kept.

Events go as lists of up to 1,000 (``client.post_events``, API v1 since SDK 0.6.0); each event
comes back as taken or not, so a caller records only what PlantCraft took. A list refused as a
whole (422: a PlantCraft before lists, or one malformed item) is sent again one event at a time.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

from plantcraft_sdk.client import (
    MAX_EVENTS,
    BadRequest,
    Forbidden,
    NotFound,
    PlantCraftError,
)

LOGGER = logging.getLogger(__name__)

# Longest summary PlantCraft keeps for a result or an event (``plantcraft_sdk.links``).
MAX_SUMMARY = 300
# After a 404, how long an endpoint is left alone before it is tried again.
RETRY_MISSING_SECONDS = 3600.0
# Broken result assets left out of one sync before it gives up.
MAX_RESULT_RETRIES = 20


def summary_text(text: Any) -> str:
    """A summary cut to what PlantCraft keeps (an ellipsis marks the cut)."""

    text = " ".join(str(text or "").split())
    return text if len(text) <= MAX_SUMMARY else text[: MAX_SUMMARY - 1].rstrip() + "…"


def _missing_route(exc: NotFound) -> bool:
    """A 404 for the route itself (the web framework's bare "Not Found"), not for an item.

    PlantCraft names what it did not find (``Asset not found. (asset:x)``); a server that has
    no such route answers the framework's default.
    """

    text = str(exc.detail or "Not Found")
    if text.startswith("PlantCraft answered"):  # no JSON body: the client's own message
        text = text.rpartition(": ")[2]
    return text.strip().rstrip(".").lower() == "not found"


def _event_body(event: dict[str, Any]) -> dict[str, Any]:
    body = {
        "kind": event["kind"],
        "subject": event["subject"],
        "summary": summary_text(event.get("summary")),
        "refs": list(event.get("refs") or ()),
        "payload": dict(event.get("payload") or {}),
    }
    # The event's own fields (SDK 0.26, app.toml [[publishes.events]]); the catalog fills the rest.
    for field in ("severity", "key", "phase", "category"):
        if event.get(field):
            body[field] = event[field]
    return body


class SuiteClient:
    """Results, events, runs and schedules through one PlantCraft client (thread-safe)."""

    def __init__(self, client: Any, *, clock: Any = time.monotonic):
        self.client = client
        self.clock = clock
        self._missing: dict[str, float] = {}
        self._logged: set[str] = set()
        self._lock = threading.Lock()

    def available(self, endpoint: str) -> bool:
        with self._lock:
            since = self._missing.get(endpoint)
            return since is None or self.clock() - since >= RETRY_MISSING_SECONDS

    def _call(
        self, endpoint: str, name: str, *args: Any, passthrough: tuple = (), **kwargs: Any
    ) -> Any:
        """``client.<name>(...)``, or ``None`` when skipped or failed (``passthrough`` is raised)."""

        if not self.available(endpoint):
            return None
        method = getattr(self.client, name, None)
        if not callable(method):  # no app key: background publishing is off
            return None
        try:
            answer = method(*args, **kwargs)
        except NotFound as exc:
            if not _missing_route(exc):  # the route exists: this one item was refused
                LOGGER.warning("PlantCraft %s refused: %s", endpoint, exc)
                return None
            with self._lock:
                self._missing[endpoint] = self.clock()
                first = endpoint not in self._logged
                self._logged.add(endpoint)
            if first:
                LOGGER.warning(
                    "PlantCraft does not serve %s yet; Analytics carries on without it.", endpoint
                )
            return None
        except passthrough:
            raise
        except PlantCraftError as exc:
            LOGGER.warning("PlantCraft %s failed: %s", endpoint, exc)
            return None
        with self._lock:
            self._missing.pop(endpoint, None)
        return answer

    def _saved(self, endpoint: str, receipt: Any) -> bool:
        """True when the request went through; items refused one by one are logged."""

        if receipt is None:
            return False
        errors = receipt.get("errors") if isinstance(receipt, dict) else None
        for error in (errors or [])[:5]:
            LOGGER.warning("PlantCraft refused one of the %s: %s", endpoint, error)
        return True

    # Writing ---------------------------------------------------------------

    def put_results(self, rows: list[dict[str, Any]]) -> bool:
        if not rows:
            return False
        return self._saved("results", self._call("results", "put_results", rows))

    def post_events(self, events: list[dict[str, Any]]) -> list[bool]:
        """Post ``events`` in lists of ``MAX_EVENTS``; ``True`` for each one PlantCraft took.

        An event PlantCraft refuses on its own (unknown subject) is ``False`` and the rest go
        on. After a failed request (unreachable, 5xx, route missing) nothing more is sent: the
        events not taken go again next round.
        """

        taken = [False] * len(events)
        bodies = [_event_body(event) for event in events]
        for start in range(0, len(bodies), MAX_EVENTS):
            chunk = bodies[start : start + MAX_EVENTS]
            outcome = self._post_list(chunk)
            taken[start : start + len(outcome)] = outcome
            if len(outcome) < len(chunk):
                break
        return taken

    def _post_list(self, chunk: list[dict[str, Any]]) -> list[bool]:
        """One list request; shorter than ``chunk`` when the request failed."""

        try:
            receipt = self._call("events", "post_events", chunk, passthrough=(BadRequest,))
        except BadRequest as exc:
            with self._lock:
                first = "events_singly" not in self._logged
                self._logged.add("events_singly")
            if first:
                LOGGER.warning(
                    "PlantCraft refused a list of events (%s); sending them one at a time.", exc
                )
            return self._post_singly(chunk)
        ids = receipt.get("ids") if isinstance(receipt, dict) else None
        if not isinstance(ids, list) or len(ids) != len(chunk):
            if receipt is not None:
                LOGGER.warning("PlantCraft answered a list of events with %r.", receipt)
            return []
        self._saved("events", receipt)
        return [item is not None for item in ids]

    def _post_singly(self, chunk: list[dict[str, Any]]) -> list[bool]:
        """The one-event form, for a list refused as a whole; stops at a failed request."""

        taken: list[bool] = []
        for body in chunk:
            try:
                self.client.post_event(**body)
            except NotFound as exc:
                if _missing_route(exc):
                    return taken
                LOGGER.warning("PlantCraft refused an event: %s", exc)
                taken.append(False)
            except (BadRequest, Forbidden) as exc:  # this event only
                LOGGER.warning("PlantCraft refused an event: %s", exc)
                taken.append(False)
            except PlantCraftError as exc:
                LOGGER.warning("PlantCraft events failed: %s", exc)
                return taken
            else:
                taken.append(True)
        return taken

    def put_series(self, items: list[dict[str, Any]]) -> int:
        """Derived series (``client.put_series``, API v1 since SDK 0.7.0); the series written.

        The SDK splits a long list into requests of at most 500 series. A failed request is
        logged and the round goes on; the next round writes its own points.
        """

        if not items:
            return 0
        receipt = self._call("series", "put_series", items)
        if not self._saved("series", receipt):
            return 0
        return int(receipt.get("written") or 0) if isinstance(receipt, dict) else 0

    def put_series_runs(self, items: list[dict[str, Any]]) -> int:
        """Whole series per execution on runs points (``client.put_series_runs``, SDK 0.30.0);
        the runs written."""

        if not items:
            return 0
        receipt = self._call("series_runs", "put_series_runs", items)
        if not self._saved("series_runs", receipt):
            return 0
        return int(receipt.get("written") or 0) if isinstance(receipt, dict) else 0

    def sync_result_assets(self, items: list[dict[str, Any]]) -> dict[str, int] | None:
        """Link's whole set of result assets (``client.sync_result_assets``, SDK 0.29.0);
        None when not done. PlantCraft refuses the whole set for one broken item (an asset
        removed since): that item is left out and the rest sent again."""

        wanted = list(items)
        for _attempt in range(MAX_RESULT_RETRIES):
            try:
                receipt = self._call(
                    "result_assets", "sync_result_assets", wanted, passthrough=(BadRequest,)
                )
            except BadRequest as exc:
                found = re.match(r"\[(\d+)\]", str(exc.detail))
                if not found or int(found.group(1)) >= len(wanted):
                    LOGGER.warning("PlantCraft refused the result assets: %s", exc)
                    return None
                LOGGER.warning("PlantCraft refused a result asset: %s", exc.detail)
                del wanted[int(found.group(1))]
                continue
            return receipt if isinstance(receipt, dict) else None
        return None

    def own_signals(self, app: str) -> list[dict[str, Any]] | None:
        """The derived signals the app wrote (API v1 ``GET /signals?app=``); None when unread."""

        found = self._call("signals", "signals", app=app)
        return None if found is None else [dict(item) for item in found]

    def retire_series(self, signals: list[str]) -> list[str] | None:
        """Retire derived series the app no longer writes (SDK 0.24.0); None when not done."""

        if not signals:
            return []
        receipt = self._call("series_retire", "retire_series", signals)
        if not self._saved("series_retire", receipt):
            return None
        return list(receipt.get("retired") or []) if isinstance(receipt, dict) else []

    def put_runs(self, rows: list[dict[str, Any]]) -> bool:
        return self._saved("runs", self._call("runs", "put_runs", rows))

    def put_schedules(self, rows: list[dict[str, Any]]) -> bool:
        return self._saved("schedules", self._call("schedules", "put_schedules", rows))

    def put_knowledge(self, items: list[dict[str, Any]]) -> bool:
        """What Analytics explains (API v1 ``/knowledge``, PlantCraft 0.3 and SDK 0.10).

        An SDK without ``put_knowledge`` sends the request itself; a PlantCraft without the
        route answers 404 and the texts wait an hour (``_call``).
        """

        if not items:
            return False
        if callable(getattr(self.client, "put_knowledge", None)):
            return self._saved("knowledge", self._call("knowledge", "put_knowledge", items))
        receipt = self._call("knowledge", "_send", "PUT", "/api/v1/knowledge", json=items)
        return self._saved("knowledge", receipt)
