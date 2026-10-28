"""What the suite can report, and the installation's alarm philosophy.

The **catalog** is every event each app declares (PlantCraft's ``GET /api/v1/events/catalog``):
the rule editor picks from it, and each event can start a rule from the rule its app suggests.
The **conditions** are what the apps opened and did not close yet (a service down). The
**philosophy** holds the targets Alarms measures and uses to hold back what reaches people
(``alarms.philosophy``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from alarmcraft.alarms.philosophy import PhilosophyDraft
from alarmcraft.api.deps import CurrentUser, EditorUser, RuntimeDep
from alarmcraft.api.runtime import Runtime
from alarmcraft.i18n import t
from alarmcraft.monitor.suggest import counting_rules, suggested_rule

router = APIRouter(prefix="/api", tags=["catalog"])


@router.get("/catalog")
def event_catalog(rt: RuntimeDep, _user: CurrentUser) -> dict[str, Any]:
    """Every event the apps declare, by app, with the rules that already count each one."""

    apps, error = rt.event_catalog()
    rules = rt.rules.list()
    for app in apps:
        for event in app["events"]:
            event["rules"] = counting_rules(rules, event["kind"])
    return {"apps": apps, "error": error, "service_key": rt.has_service_key}


@router.get("/rules/from-catalog")
def rule_from_catalog(
    rt: RuntimeDep, _user: EditorUser, kind: str = Query(min_length=3, max_length=200)
) -> dict[str, Any]:
    """A new rule filled in from a declared event and the rule its app suggests."""

    apps, error = rt.event_catalog()
    for app in apps:
        for event in app["events"]:
            if event["kind"] == kind:
                return suggested_rule(event)
    raise HTTPException(404, error or t("No app declares the event {kind}.", kind=kind))


@router.get("/conditions")
def open_conditions(rt: RuntimeDep, _user: CurrentUser) -> list[dict[str, Any]]:
    """The conditions open now: started by an app and not ended yet."""

    return rt.incoming.open_conditions()


@router.get("/philosophy")
def get_philosophy(rt: RuntimeDep, _user: CurrentUser) -> dict[str, Any]:
    return {**rt.philosophy.record(), "next_summary": _next(rt)}


@router.put("/philosophy")
def put_philosophy(body: PhilosophyDraft, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    saved = rt.philosophy.put(body, by=user.username)
    rt.audit(user, "philosophy.changed", "philosophy", body.model_dump(mode="json"))
    return {**saved, "next_summary": _next(rt)}


def _next(rt: Runtime) -> str:
    return rt.philosophy.get().next_digest(rt.clock()).isoformat()
