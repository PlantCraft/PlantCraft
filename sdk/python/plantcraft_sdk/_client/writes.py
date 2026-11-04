"""``PlantCraftClient``'s derived series, audit records, people, groups and notifications."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from plantcraft_sdk.contract import (
    AuditReceipt,
)
from plantcraft_sdk.derived import (
    MAX_DERIVED_ITEMS,
    MAX_DERIVED_VALUES,
    MAX_RUN_ITEMS,
    DerivedReceipt,
)
from plantcraft_sdk.people import Group, NotificationReceipt, NotificationResolution, Person


class _WriteCalls:
    """The client's calls for derived series, audit and notifications (mixed into ``PlantCraftClient``)."""

    def put_series(self, items: Iterable[Mapping[str, Any]]) -> DerivedReceipt:
        """``PUT /api/v1/series``: the app's computed series, as derived signals.

        Each item is ``{"signal": "app-<app id>:<name>", "t": [iso...], "v": [...]}`` with
        optional ``name``, ``unit`` (``"/100"`` for a score), ``kind``, ``subject``
        (``asset:<id>``) and ``result`` (the result kind it comes from). Needs a service token.
        Sent in requests of at most 500 items and 100,000 values (a longer series is split);
        ``errors`` carry the index in the whole list. A write at an instant already written
        replaces that value, so sending again is safe.
        """

        pieces: list[tuple[int, dict[str, Any]]] = []
        for index, item in enumerate(items):
            body = dict(item)
            stamps, values = list(body.get("t") or []), list(body.get("v") or [])
            if len(values) <= MAX_DERIVED_VALUES:
                pieces.append((index, body))
                continue
            for start in range(0, len(values), MAX_DERIVED_VALUES):
                part = {
                    **body,
                    "t": stamps[start : start + MAX_DERIVED_VALUES],
                    "v": values[start : start + MAX_DERIVED_VALUES],
                }
                pieces.append((index, part))
        written, errors = 0, []
        batch: list[tuple[int, dict[str, Any]]] = []
        size = 0

        def send() -> None:
            nonlocal written, batch, size
            if not batch:
                return
            answer = self._send("PUT", "/api/v1/series", json=[body for _, body in batch])
            written += int(answer.get("written") or 0)
            for error in answer.get("errors") or []:
                local = int(error.get("index", 0))
                original = batch[local][0] if 0 <= local < len(batch) else local
                errors.append({**error, "index": original})
            batch, size = [], 0

        for index, body in pieces:
            count = len(body.get("v") or [])
            if len(batch) >= MAX_DERIVED_ITEMS or size + count > MAX_DERIVED_VALUES:
                send()
            batch.append((index, body))
            size += count
        send()
        return {"written": written, "errors": errors}

    def put_series_runs(self, items: Iterable[Mapping[str, Any]]) -> DerivedReceipt:
        """``PUT /api/v1/series/runs``: one whole series per execution, on runs points.

        Each item is ``{"signal": "app-<app id>:<name>", "run_at": iso, "t": [iso...], "v":
        [number...]}`` with optional ``keep_runs`` (default 10), ``keep_days``, ``managed_by``,
        ``name``, ``unit``, ``description``, ``subject`` and ``result``. A run sent again at
        the same ``run_at`` replaces it. Sent 500 runs per request; ``errors`` carry the index
        in the whole list. Needs a service token.
        """

        wanted = [dict(item) for item in items]
        written, errors = 0, []
        for start in range(0, len(wanted), MAX_RUN_ITEMS):
            answer = self._send(
                "PUT", "/api/v1/series/runs", json=wanted[start : start + MAX_RUN_ITEMS]
            )
            written += int((answer or {}).get("written") or 0)
            for error in (answer or {}).get("errors") or []:
                errors.append({**error, "index": int(error.get("index", 0)) + start})
        return {"written": written, "errors": errors}

    def retire_series(self, signals: Iterable[str]) -> dict[str, Any]:
        """``POST /api/v1/series/retire``: the app's derived series it no longer writes.

        Only its own (``app-<app id>:...``); at most 500 per request (longer lists are split).
        A retired series is no longer listed nor read. ``{"retired": [ids], "errors": [...]}``.
        """

        wanted = list(dict.fromkeys(signals))
        retired: list[str] = []
        errors: list[Any] = []
        for start in range(0, len(wanted), 500):
            answer = self._send(
                "POST", "/api/v1/series/retire", json={"signals": wanted[start : start + 500]}
            )
            retired.extend((answer or {}).get("retired") or [])
            errors.extend((answer or {}).get("errors") or [])
        return {"retired": retired, "errors": errors}

    def audit(
        self, action: str, subject: str, detail: Any = None, *, app: str | None = None
    ) -> AuditReceipt:
        """Record a user's change in PlantCraft's audit log.

        Tagged with ``app``, else with this client's app id when it knows it.
        """

        body: dict[str, Any] = {"action": action, "subject": subject, "detail": detail}
        if app or self.app:
            body["app"] = app or self.app
        return self._send("POST", "/api/v1/audit", json=body, idempotent=False)

    def people(self) -> list[Person]:
        """``GET /api/v1/people``: the active people, with their groups (no email or phone)."""

        return self._send("GET", "/api/v1/people")

    def groups(self) -> list[Group]:
        """``GET /api/v1/groups``: every group with its members."""

        return self._send("GET", "/api/v1/groups")

    def notification_settings(self) -> dict[str, bool]:
        """``GET /api/v1/notifications``: ``{"email": bool}``, whether the platform can send
        email now (an administrator set up its server), so an app offers email only then."""

        return self._send("GET", "/api/v1/notifications")

    def notify(
        self,
        recipients: Iterable[str],
        title: str,
        text: str = "",
        *,
        priority: str = "medium",
        url: str | None = None,
        email: bool = False,
        refs: Iterable[str] = (),
        key: str | None = None,
        category: str | None = None,
        actions: Iterable[dict[str, str]] = (),
    ) -> NotificationReceipt:
        """``POST /api/v1/notifications`` (a service token): a message to each person named
        (``user:<username>``) or in each group (``group:<id>``), and an email when ``email`` and
        the platform and the person allow it. Not retried: a repeat would notify twice.

        In Messages' Notifications the same ``key`` from the same app is one thread (an alarm's
        "alarm:12:3": fired, reminded, cleared), unread again on each send; ``category`` (alarm,
        run, action, info) chooses its icon and filter; ``actions`` are up to three buttons beside
        Open: ``{"label": "Open the rule", "href": "/alarm/rules/4"}`` opens a page of the suite,
        ``{"label": "Acknowledge", "href": "/alarm/api/alarms/12/ack", "method": "POST"}`` runs
        the call in this app as the person who clicks (a path under this app's own prefix).
        When it is settled, :meth:`resolve_notification` takes it off everyone's count."""

        body: dict[str, Any] = {
            "recipients": list(recipients),
            "title": title,
            "text": text,
            "priority": priority,
            "email": email,
            "refs": list(refs),
        }
        if url:
            body["url"] = url
        if key:
            body["key"] = key
        if category:
            body["category"] = category
        buttons = [
            {"label": item["label"], "href": item["href"]}
            | ({"method": "POST"} if item.get("method") == "POST" else {})
            for item in actions
        ]
        if buttons:
            body["actions"] = buttons
        return self._send("POST", "/api/v1/notifications", json=body, idempotent=False)

    def resolve_notification(self, key: str, note: str = "") -> NotificationResolution:
        """``POST /api/v1/notifications/resolve`` (a service token, platform with SDK 0.53.0):
        what this app notified under ``key`` is settled (an alarm acknowledged, here or from the
        notification's button, or cleared). The thread leaves the unread count of everyone who
        received it and shows ``note`` ("Acknowledged by Ana") instead of its buttons; a later
        :meth:`notify` with the same key opens it again. Safe to repeat."""

        body = {"key": key, "note": note}
        return self._send("POST", "/api/v1/notifications/resolve", json=body)
