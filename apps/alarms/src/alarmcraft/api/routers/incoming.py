"""Incoming: the events the apps of the suite reported, with the rules each one counted for."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from alarmcraft.api.deps import CurrentUser, RuntimeDep
from alarmcraft.api.routers.alarms import window_of
from alarmcraft.i18n import t
from alarmcraft.monitor.suggest import counting_rules

router = APIRouter(prefix="/api", tags=["incoming"])


@router.get("/incoming")
def incoming(
    rt: RuntimeDep,
    user: CurrentUser,
    window: str = Query(default="24h", max_length=10),
    app: str | None = Query(default=None, max_length=40),
    kind: str | None = Query(default=None, max_length=120),
    severity: str | None = Query(default=None, max_length=20),
    subject: str | None = Query(default=None, max_length=310),
    limit: int = Query(default=1000, ge=1, le=5000),
) -> dict[str, Any]:
    """The events of the last ``window``, newest first, and how many of each kind arrived."""

    start = (rt.clock() - window_of(window)).isoformat()
    names = {rule["rule_id"]: rule["name"] for rule in rt.rules.list()}
    events = rt.incoming.listing(
        start=start, app=app, kind=kind, severity=severity, subject=subject, limit=limit
    )
    scope = rt.asset_scope(user)
    events = [event for event in events if scope.subject(event.get("subject"))]
    for event in events:
        event["rule_names"] = [names.get(rule, rule) for rule in event.get("rules") or []]
    status = rt.status()["monitor"]
    return {
        "events": events,
        "counts": rt.incoming.counts(start),
        "window": window,
        "error": status.get("events_error") or "",
        "read": status.get("events_read") or 0,
        "service_key": rt.has_service_key,
    }


@router.get("/incoming/condition")
def one_condition(
    rt: RuntimeDep,
    user: CurrentUser,
    app: str = Query(min_length=1, max_length=40),
    key: str = Query(min_length=1, max_length=200),
) -> dict[str, Any]:
    """An open condition's page: its newest event, else the condition alone."""

    found = rt.incoming.history(app, key, limit=1)
    if found:
        return _detail(rt, user, found[0])
    for item in rt.incoming.open_conditions():
        if item["app"] == app and item["key"] == key:
            if not rt.asset_scope(user).subject(item.get("subject")):
                break
            event = {
                "id": None,
                "at": item["opened_at"],
                "app": app,
                "kind": item["kind"],
                "subject": item["subject"],
                "summary": item["summary"],
                "severity": item["severity"],
                "phase": "start",
                "key": key,
                "payload": {},
                "refs": [],
                "rules": [],
            }
            return _detail(rt, user, event)
    raise HTTPException(404, t("Event not found."))


@router.get("/incoming/{event_id}")
def one_event(event_id: int, rt: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    """One event's page (owner's review, 2026-10-27: an event opens its own page, where it came
    from, before any rule): the event, what its app's catalog says about its kind, the other
    starts and ends of the same condition, the rules it counted for, and whether it is open."""

    event = rt.incoming.get(event_id) if 0 < event_id < 2**62 else None
    if event is None:
        raise HTTPException(404, t("Event not found."))
    return _detail(rt, user, event)


def _detail(rt: Any, user: Any, event: dict[str, Any]) -> dict[str, Any]:
    if not rt.asset_scope(user).subject(event.get("subject")):
        raise HTTPException(404, t("Event not found."))
    rules = rt.rules.list()
    names = {rule["rule_id"]: rule["name"] for rule in rules}
    event["rule_names"] = [names.get(rule, rule) for rule in event.get("rules") or []]
    declared: dict[str, Any] | None = None
    apps, _error = rt.event_catalog()
    for app in apps:
        for item in app["events"]:
            if item["kind"] == event["kind"]:
                declared = {
                    "title": item.get("title") or "",
                    "description": item.get("description") or "",
                    "app_name": app.get("name")
                    or app.get("title")
                    or app.get("app")
                    or event["app"],
                }
    key = event.get("key") or ""
    history = [item for item in rt.incoming.history(event["app"], key) if item["id"] != event["id"]]
    is_open = bool(key) and any(
        item["app"] == event["app"] and item["key"] == key for item in rt.incoming.open_conditions()
    )
    return {
        "event": event,
        "declared": declared,
        "history": history,
        "open": is_open,
        # The rules that hear this kind of event, whether or not this one raised them.
        "kind_rules": counting_rules(rules, event["kind"]),
    }
