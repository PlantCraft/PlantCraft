"""The alarms the rules make: list them, one alarm's page and history (the value its rule read,
the events it heard), take one out of service."""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from plantcraft_sdk.contract import ContractError, parse_window
from pydantic import BaseModel, ConfigDict

from alarmcraft.alarms.model import DISCIPLINES, PRIORITIES, AlarmDraft, kind_matches
from alarmcraft.alarms.records import config_of, owner_of, status_of
from alarmcraft.api.deps import CurrentUser, EditorUser, RuntimeDep, alarm_or_404, guarded
from alarmcraft.api.runtime import Runtime
from alarmcraft.api.scope import seen
from alarmcraft.engine import routing
from alarmcraft.engine import run as engine
from alarmcraft.i18n import t
from alarmcraft.monitor.sync import subject_of

router = APIRouter(prefix="/api", tags=["alarms"])
MAX_TRY_POINTS = 5000


class Enabled(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


def window_of(text: str | None, default: str = "24h") -> timedelta:
    try:
        return parse_window(text or default)
    except ContractError as exc:
        raise HTTPException(422, str(exc)) from exc


def summary(rt: Runtime, alarm: dict[str, Any]) -> dict[str, Any]:
    """An alarm as the pages show it: its configuration, its state and its status."""

    state = alarm.get("state") or {}
    draft = None
    try:
        draft = AlarmDraft.model_validate(config_of(alarm))
    except ValueError:
        pass
    chain, area = rt.tree.area_of(alarm)
    return {
        **config_of(alarm),
        "alarm_id": alarm["alarm_id"],
        "owner": owner_of(alarm),
        "area_id": area.get("id") if area else None,
        "area_name": (area.get("name") or area.get("id")) if area else None,
        "area_path": chain,
        "discipline_label": DISCIPLINES.get(alarm.get("discipline") or "", ""),
        "status": status_of(alarm, rt.clock()),
        "condition": draft.condition() if draft else "",
        "priority_label": PRIORITIES.get(alarm.get("priority") or "", ""),
        "active": bool(state.get("active")),
        "suppressed": bool(state.get("suppressed")),
        "acked": bool(alarm.get("acked", True)),
        "acked_at": alarm.get("acked_at"),
        "acked_by": alarm.get("acked_by"),
        "value": state.get("value"),
        "value_at": state.get("value_at"),
        "raised_at": state.get("raised_at") if state.get("active") else None,
        "signal": state.get("signal"),
        "known": state.get("known"),
        "reason": state.get("reason") or "",
        "unit": state.get("unit") or "",
        "message": state.get("message") or "",
        "members_active": list(state.get("members_active") or []),
        "rule_name": (rt.rules.get(alarm["rule_id"]) or {}).get("name")
        if alarm.get("rule_id")
        else None,
        "last_summary": state.get("last_summary") or "",
        "severity": state.get("severity"),
        "schedule_id": state.get("schedule_id"),
        "run": state.get("run"),
        "shelved_until": alarm.get("shelved_until"),
        "shelved_by": alarm.get("shelved_by"),
        "shelve_reason": alarm.get("shelve_reason"),
        "updated_at": alarm.get("updated_at"),
        "updated_by": alarm.get("updated_by"),
        "created_by": alarm.get("created_by"),
    }


def mark_mine(rt: Runtime, rows: list[dict[str, Any]], username: str) -> list[dict[str, Any]]:
    """Set ``mine`` on each alarm row: the person is its responsible (or in the responsible
    group), or its rule's notifications name them (or one of their groups)."""

    members = rt.directory.members()
    policies = rt.notifier.all_policies()
    for row in rows:
        ctx = routing.context(row, row.get("area_path") or [], owner=row.get("owner"))
        refs = [row["owner"]] if row.get("owner") else []
        for policy in routing.routes(rt.notifier.policies_for(row, policies), ctx):
            refs += routing.recipients(policy, row.get("owner"))
        row["mine"] = routing.reaches(refs, username, members)
    return rows


def _close_open(rt: Runtime, alarm: dict[str, Any], why: str, by: str) -> None:
    """End an alarm's open occurrence (it was changed, taken out of service or deleted)."""

    state = alarm.get("state") or {}
    now = rt.clock().isoformat()
    if state.get("active") and state.get("occurrence"):
        rt.alarms.close_occurrence(int(state["occurrence"]), now, None)
        rt.alarms.log(alarm, "cleared", at=now, by=by, detail=why)


@router.get("/alarms")
def list_alarms(rt: RuntimeDep, user: CurrentUser) -> list[dict[str, Any]]:
    alarms = seen(rt.asset_scope(user), rt.alarms.list())
    return mark_mine(rt, [summary(rt, alarm) for alarm in alarms], user.username)


@router.get("/alarms/{alarm_id}")
def get_alarm(alarm_id: str, rt: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    return summary(rt, alarm_or_404(rt, alarm_id, user))


@router.post("/alarms/{alarm_id}/enabled")
def set_enabled(alarm_id: str, body: Enabled, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    """In service (true) or out of service (false): an alarm out of service is not evaluated."""

    alarm = alarm_or_404(rt, alarm_id, user)
    config = config_of(alarm)
    config["enabled"] = body.enabled
    if not body.enabled:
        _close_open(rt, alarm, t("Taken out of service"), user.username)
    try:
        draft = AlarmDraft.model_validate(config)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    changed = rt.alarms.update(
        alarm_id, draft.config(), by=user.username, reset_state=not body.enabled
    )
    action = "in_service" if body.enabled else "out_of_service"
    rt.alarms.log(alarm, action, at=rt.clock().isoformat(), by=user.username)
    rt.audit(user, f"alarm.{action}", alarm_id)
    rt.monitor.publish_schedules()
    return summary(rt, changed or alarm)


@router.get("/alarms/{alarm_id}/history")
def alarm_history(
    alarm_id: str,
    rt: RuntimeDep,
    user: CurrentUser,
    window: str = Query(default="24h", max_length=10),
) -> dict[str, Any]:
    """One alarm's page: its occurrences, its journal and its signal over ``window``."""

    alarm = alarm_or_404(rt, alarm_id, user)
    span = window_of(window)
    end = rt.clock()
    start = end - span
    chart: dict[str, Any] = {"t": [], "v": []}
    problem = ""
    signal = (alarm.get("state") or {}).get("signal")
    if signal:
        try:
            reader, service = rt.reader(user)
        except LookupError:
            reader, service = rt.user_reader(user), False
        try:
            step = max(1.0, math.ceil(span.total_seconds() / MAX_TRY_POINTS))
            columns, errors = guarded(
                lambda: reader.read([signal], start, end, step), service=service
            )
            series = columns.get(signal)
            if series is not None:
                clean = series.astype(float).replace([np.inf, -np.inf], np.nan).dropna()
                chart = {
                    "t": [moment.isoformat() for moment in clean.index],
                    "v": [float(value) for value in clean.values],
                }
            problem = errors.get(signal, "")
        except HTTPException as exc:
            problem = str(exc.detail)
    events = _events_of(rt, alarm, start.isoformat())
    return {
        "alarm": summary(rt, alarm),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "occurrences": rt.alarms.occurrences(
            start=start.isoformat(), end=end.isoformat(), alarm_id=alarm_id, limit=500
        ),
        "journal": rt.alarms.journal(alarm_id=alarm_id, limit=200),
        "chart": chart,
        "events": events,
        "problem": problem,
    }


def _events_of(rt: Runtime, alarm: dict[str, Any], start: str) -> list[dict[str, Any]]:
    """The events that came in about the alarm's subject since ``start`` of the kinds its rule
    hears (``counted`` when the rule counted them)."""

    kinds = list(alarm.get("hears") or [])
    if not kinds:
        return []
    subject = subject_of(alarm, rt.tree.assets())
    about = engine.about(subject)
    found = []
    for event in rt.incoming.listing(start=start, limit=2000):
        if not kind_matches(kinds, str(event.get("kind") or "")):
            continue
        if subject.kind != "none" and not about(event, "subject"):
            continue
        found.append({**event, "counted": alarm.get("rule_id") in (event.get("rules") or [])})
        if len(found) >= 200:
            break
    return found
