"""HTTP routes: Alarms' rules and alarms for notebooks (``[[contributes.objects]]``).

PlantCraft forwards a notebook's ``pc.app("alarms").list("alarm")`` here with the person's
identity (``plantcraft_sdk.server.objects``, format ``plantcraft-objects/1``). A rule is read as
the Rules page shows it; an alarm with its state and its occurrences of the last 30 days, which
is what an alarm performance study (rates, bad actors, chattering, standing alarms) starts from.
Both are read only: rules are written on the Rules page.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import HTTPException
from plantcraft_sdk.app_manifest import parse_manifest
from plantcraft_sdk.server.objects import AppObjects, notebooks_router, object_item

from alarmcraft.api.routers.alarms import rule_names, summary
from alarmcraft.api.routers.rules import rule_or_404, rule_row
from alarmcraft.api.scope import seen, sees_alarm
from alarmcraft.meta import FILES
from alarmcraft.notebook_examples import EXAMPLES

objects = AppObjects()
# An alarm's occurrences in one read: the last 30 days, at most 5000.
HISTORY_DAYS = 30
MAX_OCCURRENCES = 5000


@objects.lister("rule")
def rules(user: Any, rt: Any) -> list[dict[str, Any]]:
    by_rule: dict[str, int] = {}
    for alarm in seen(rt.asset_scope(user), rt.alarms.list()):
        by_rule[alarm.get("rule_id") or ""] = by_rule.get(alarm.get("rule_id") or "", 0) + 1
    return [
        object_item(
            rule["rule_id"],
            rule.get("name") or rule["rule_id"],
            priority=rule.get("priority") or "",
            editor=rule.get("editor") or "",
            enabled=bool(rule.get("enabled", True)),
            alarms=by_rule.get(rule["rule_id"], 0),
            updated_at=rule.get("updated_at"),
        )
        for rule in rt.rules.list()
    ]


@objects.getter("rule")
def rule(user: Any, rt: Any, rule_id: str) -> dict[str, Any] | None:
    try:
        found = rule_or_404(rt, rule_id)
    except HTTPException:
        return None
    alarms = [
        alarm
        for alarm in seen(rt.asset_scope(user), rt.alarms.list())
        if alarm.get("rule_id") == rule_id
    ]
    return {"id": rule_id, **rule_row(rt, found, alarms)}


@objects.lister("alarm")
def alarms(user: Any, rt: Any) -> list[dict[str, Any]]:
    rows = []
    names = rule_names(rt)
    for alarm in seen(rt.asset_scope(user), rt.alarms.list()):
        row = summary(rt, alarm, names)
        rows.append(
            object_item(
                row["alarm_id"],
                row.get("name") or row["alarm_id"],
                rule=row.get("rule_id") or "",
                priority=row.get("priority") or "",
                status=row["status"],
                active=row["active"],
                area=row.get("area_name") or "",
                signal=row.get("signal") or "",
            )
        )
    return rows


@objects.getter("alarm")
def alarm(user: Any, rt: Any, alarm_id: str) -> dict[str, Any] | None:
    found = rt.alarms.get(alarm_id) if len(alarm_id) <= 200 else None
    if found is None or not sees_alarm(rt.asset_scope(user), found):
        return None
    end = rt.clock()
    start = end - timedelta(days=HISTORY_DAYS)
    occurrences = rt.alarms.occurrences(
        start=start.isoformat(), end=end.isoformat(), alarm_id=alarm_id, limit=MAX_OCCURRENCES
    )
    return {
        "id": alarm_id,
        **summary(rt, found),
        "history_start": start.isoformat(),
        "at": end.isoformat(),
        "occurrences": occurrences,
    }


router = objects.router()


def notebooks() -> Any:
    """Alarms' examples (``[contributes.notebooks]`` of its ``app.toml``)."""

    data = FILES.manifest()
    return notebooks_router(EXAMPLES, parse_manifest(data) if data else None)
