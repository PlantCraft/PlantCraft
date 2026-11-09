"""``PlantCraftClient``'s results, events, runs, schedules, knowledge, contributions, model calls and desk."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any
from urllib.parse import quote

from plantcraft_sdk._client.base import LLM_TIMEOUT, _time
from plantcraft_sdk.links import (
    MAX_EVENTS,
    MAX_ITEMS,
    MAX_SUBJECTS,
    Event,
    EventsReceipt,
    PutReceipt,
    Result,
    ResultChange,
    Run,
    Schedule,
)
from plantcraft_sdk.llm import messages_body


class _LinksCalls:
    """The client's calls for results, events, runs and the desk (mixed into ``PlantCraftClient``)."""

    def _for_app(self, items: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """Items as sent: with a person's token each names the app (this client's, if not given)."""

        found = []
        for item in items:
            body = dict(item)
            if self.app and not body.get("app"):
                body["app"] = self.app
            found.append(body)
        return found

    def put_results(self, results: Iterable[Mapping[str, Any]]) -> PutReceipt:
        """``PUT /api/v1/results``: one item per (subject, kind), up to 500 per request.

        Larger lists are sent in several requests; ``errors`` (with the index in the
        whole list) name the items that were not saved, such as unknown subjects (404).
        """

        return self._put_chunks("/api/v1/results", self._for_app(results))

    def results(
        self,
        subjects: Iterable[str] | str | None = None,
        *,
        app: str | None = None,
        kind: str | None = None,
    ) -> list[Result]:
        """``GET /api/v1/results``: the latest results about ``subjects`` (expired ones stale).

        Each subject is its own ``subject`` parameter (ids may hold commas), up to 500
        per request; more are asked in several requests. Each request is read page by page
        (``X-Next-Cursor``, PlantCraft 2026-10-27), so no result is left out.
        """

        wanted = [subjects] if isinstance(subjects, str) else list(subjects or [])
        wanted = list(dict.fromkeys(item for item in wanted if item))
        found: list[Result] = []
        for start in range(0, max(1, len(wanted)), MAX_SUBJECTS):
            chunk = wanted[start : start + MAX_SUBJECTS]
            params = {"subject": chunk or None, "app": app, "kind": kind}
            found.extend(self._all_pages(self._exchange, "/api/v1/results", params))
        return found

    def result_history(
        self,
        subject: str,
        *,
        app: str | None = None,
        kind: str | None = None,
        after: str | datetime | None = None,
        limit: int | None = None,
    ) -> list[ResultChange]:
        """``GET /api/v1/results/history``: status changes about ``subject``, oldest first."""

        params = {"subject": subject, "app": app, "kind": kind, "after": _time(after)}
        params["limit"] = limit
        return self._send("GET", "/api/v1/results/history", params=params)

    def post_event(
        self,
        kind: str,
        subject: str,
        *,
        summary: str = "",
        refs: Iterable[str] = (),
        payload: Mapping[str, Any] | None = None,
        app: str | None = None,
        severity: str | None = None,
        key: str | None = None,
        phase: str | None = None,
        category: str | None = None,
    ) -> Event:
        """``POST /api/v1/events``: ``kind`` is ``<app id>.<noun>.<verb>``.

        ``severity`` (info, ok, warning, critical), ``category`` and an ``instant`` phase default
        to the app's catalog; a condition is sent as ``phase="start"`` then ``"end"`` with the
        same ``key`` (``plantcraft_sdk.events``).
        """

        body: dict[str, Any] = {
            "kind": kind,
            "subject": subject,
            "summary": summary,
            "refs": list(refs),
            "payload": dict(payload or {}),
        }
        for field, value in (
            ("severity", severity),
            ("key", key),
            ("phase", phase),
            ("category", category),
        ):
            if value is not None:
                body[field] = value
        if app or self.app:
            body["app"] = app or self.app
        return self._send("POST", "/api/v1/events", json=body, idempotent=False)

    def put_event_catalog(
        self, events: Iterable[Mapping[str, Any]], *, app: str | None = None
    ) -> dict[str, Any]:
        """``PUT /api/v1/events/catalog``: the app's declared events, replaced
        (``EventCatalog.to_json()``; the SDK's server sends it when the app starts)."""

        body: dict[str, Any] = {"events": [dict(item) for item in events]}
        if app or self.app:
            body["app"] = app or self.app
        return self._send("PUT", "/api/v1/events/catalog", json=body)

    def put_contributions(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """``PUT /api/v1/contributions``: what the app adds to PlantCraft, replaced
        (``contributes.contributions(manifest)``; the SDK's server sends it when the app starts,
        and PlantCraft puts its events in the catalog too)."""

        body = dict(body)
        if self.app and not body.get("app"):
            body["app"] = self.app
        return self._send("PUT", "/api/v1/contributions", json=body)

    def contributions(self) -> dict[str, Any]:
        """``GET /api/v1/contributions``: what every installed app adds, and the ``features``
        this PlantCraft draws."""

        return self._send("GET", "/api/v1/contributions")

    def llm(
        self,
        use: str,
        messages: list[Mapping[str, Any]] | str,
        *,
        system: str = "",
        images: Iterable[Any] = (),
        timeout: float = LLM_TIMEOUT,
    ) -> dict[str, Any]:
        """``POST /api/v1/llm/{use}``: one answer from the model PlantCraft gives one of the
        app's uses (``[[contributes.llm]]``): ``{"use", "model", "text"}``.

        ``messages`` is a question, or the turns of a chat (``role`` user or assistant). A use
        with no model now (off, or nothing set up) raises ``BadRequest`` with status 409: say
        so, and that an administrator chooses one in Setup › Language models.

        ``images`` (PNG bytes, or ``plantcraft_sdk.llm.image(data, media_type)``) go with the
        last user turn, for a model that reads images: at most 4, 5 MB each."""

        return self._send(
            "POST",
            f"/api/v1/llm/{quote(use, safe=':')}",
            json=messages_body(messages, system=system, images=images),
            idempotent=False,
            timeout=timeout,
        )

    def put_calendar(self, feed: str, items: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        """``PUT /api/v1/calendar/<feed>``: the feed's whole list of dated items
        (``desk.CalendarItemIn``), replaced; the feed is one of the app's
        ``[[contributes.calendar]]``."""

        return self._send(
            "PUT", f"/api/v1/calendar/{quote(feed, safe='')}", params=self._own(), json=list(items)
        )

    def put_todo(self, todo: Mapping[str, Any]) -> dict[str, Any]:
        """``POST /api/v1/todos``: a to-do for ``user:<name>`` or ``group:<id>``
        (``desk.TodoIn``: key, kind, title, for, due, ref, url, detail), made or changed by its
        ``key``; a done one stays done."""

        return self._send("POST", "/api/v1/todos", params=self._own(), json=dict(todo))

    def todos(self, state: str = "all") -> list[dict[str, Any]]:
        """``GET /api/v1/todos``: the app's own to-dos (``open``, ``done`` or ``all``), with
        ``done_by`` and ``done_at`` once a person ticked them in Desk."""

        return self._send("GET", "/api/v1/todos", params={**self._own(), "state": state})

    def close_todos(self, keys: Iterable[str]) -> dict[str, Any]:
        """``POST /api/v1/todos/close``: the app's to-dos with these keys are gone from every
        Desk; answers ``{"closed"}``, how many there were."""

        return self._send(
            "POST", "/api/v1/todos/close", params=self._own(), json={"keys": list(keys)}
        )

    def _own(self) -> dict[str, Any]:
        """``?app=`` for a person's token writing for an app; a service token names its own."""

        return {"app": self.app} if self.app else {}

    def app_settings(self) -> dict[str, Any]:
        """``GET /api/v1/contributions/settings``: this app's installation settings
        (``[[contributes.settings]]``) as the administrator set them in Setup › Apps, else their
        defaults, by key. An app's service token only."""

        return dict(self._send("GET", "/api/v1/contributions/settings").get("values") or {})

    def explore(self, asset: str | None = None, *, q: str = "") -> dict[str, Any]:
        """``GET /api/v1/explore``: the plant's top assets, one ``asset`` opened (its signals,
        the series apps computed about it, the events that named it, its children), or with
        ``q`` the assets, signals and series matching (``{"hits": [...]}``), each with its
        path (``plantcraft_sdk.explore``)."""

        params = {key: value for key, value in (("asset", asset), ("q", q)) if value}
        return self._send("GET", "/api/v1/explore", params=params or None)

    def event_catalog(self) -> list[dict[str, Any]]:
        """``GET /api/v1/events/catalog``: every app's declared events, PlantCraft's first."""

        return self._send("GET", "/api/v1/events/catalog")

    def post_events(self, events: Iterable[Mapping[str, Any]]) -> EventsReceipt:
        """``POST /api/v1/events`` with lists of up to 1,000 events per request.

        Each item has ``post_event``'s fields (``kind``, ``subject``, ``summary``,
        ``refs``, ``payload``; ``app`` defaults to this client's). ``ids[i]`` is
        item ``i``'s new event id, None when it is in ``errors`` (index in the whole
        list), such as an unknown subject (404). Not retried: a request that may
        have reached PlantCraft is not sent again.
        """

        items = self._for_app(events)
        saved, ids, errors, repeated = 0, [], [], 0
        for start in range(0, len(items), MAX_EVENTS):
            answer = self._send(
                "POST", "/api/v1/events", json=items[start : start + MAX_EVENTS], idempotent=False
            )
            saved += int(answer.get("saved") or 0)
            repeated += int(answer.get("repeated") or 0)
            ids.extend(answer.get("ids") or [])
            for error in answer.get("errors") or []:
                errors.append({**error, "index": int(error.get("index", 0)) + start})
        return {"saved": saved, "ids": ids, "errors": errors, "repeated": repeated}

    def events(
        self,
        *,
        ref: str | None = None,
        kind: str | None = None,
        after: int | None = None,
        limit: int | None = None,
        key: str | None = None,
    ) -> list[Event]:
        """``GET /api/v1/events``: oldest first; after the event id ``after``, else the latest.
        ``key`` keeps the events of one condition."""

        params = {"ref": ref, "kind": kind, "after": after, "limit": limit, "key": key}
        return self._send("GET", "/api/v1/events", params=params)

    def put_runs(self, runs: Iterable[Mapping[str, Any]]) -> PutReceipt:
        """``PUT /api/v1/runs``: one item per run id, replaced on every PUT."""

        return self._put_chunks("/api/v1/runs", self._for_app(runs))

    def put_knowledge(self, items: Iterable[Mapping[str, Any]]) -> PutReceipt:
        """``PUT /api/v1/knowledge``: the app's texts about its own objects (protocols, runs),
        one per ref, replaced on every PUT; specialists read them as context."""

        return self._put_chunks("/api/v1/knowledge", self._for_app(items))

    def delete_knowledge(self, refs: Iterable[str]) -> dict[str, Any]:
        """``POST /api/v1/knowledge/delete``: the app's texts about these refs are removed."""

        return self._send("POST", "/api/v1/knowledge/delete", json={"refs": list(refs)})

    def knowledge(
        self,
        *,
        ref: str | None = None,
        q: str | None = None,
        app: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """``GET /api/v1/knowledge``: texts about ``ref``, or matching ``q``."""

        params = {"ref": ref, "q": q, "app": app, "limit": limit}
        return self._send("GET", "/api/v1/knowledge", params=params)

    def runs(
        self,
        *,
        app: str | None = None,
        status: str | None = None,
        subject: str | None = None,
        by: str | None = None,
        limit: int | None = None,
    ) -> list[Run]:
        """``GET /api/v1/runs``, newest first; ``by`` the runs a person started."""

        params = {"app": app, "status": status, "subject": subject, "by": by, "limit": limit}
        return self._send("GET", "/api/v1/runs", params=params)

    def put_schedules(
        self, schedules: Iterable[Mapping[str, Any]], *, app: str | None = None
    ) -> PutReceipt:
        """``PUT /api/v1/schedules``: the app's whole list (an empty list clears it)."""

        params = {"app": app or self.app}
        return self._send(
            "PUT", "/api/v1/schedules", params=params, json=[dict(item) for item in schedules]
        )

    def schedules(self, *, app: str | None = None) -> list[Schedule]:
        return self._send("GET", "/api/v1/schedules", params={"app": app})

    def _put_chunks(self, path: str, items: list[dict[str, Any]]) -> PutReceipt:
        saved, errors = 0, []
        for start in range(0, len(items), MAX_ITEMS):
            answer = self._send("PUT", path, json=items[start : start + MAX_ITEMS])
            saved += int(answer.get("saved") or 0)
            for error in answer.get("errors") or []:
                errors.append({**error, "index": int(error.get("index", 0)) + start})
        return {"saved": saved, "errors": errors}
