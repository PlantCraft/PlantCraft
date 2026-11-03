"""Operating the alarms: the alarm summary, acknowledge, shelve, the journal and performance."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from plantcraft_sdk.auth import User
from pydantic import BaseModel, ConfigDict, Field

from alarmcraft.alarms.model import PRIORITIES
from alarmcraft.alarms.records import config_of, owner_of
from alarmcraft.api.deps import CurrentUser, EditorUser, RuntimeDep, alarm_or_404
from alarmcraft.api.routers.alarms import mark_mine, rule_names, summary, window_of
from alarmcraft.api.runtime import Runtime
from alarmcraft.api.scope import of_seen, seen
from alarmcraft.engine.performance import performance
from alarmcraft.i18n import t

LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["operate"])
MAX_SHELVE_MINUTES = 7 * 24 * 60
# The summary's order: needing action first, then by priority, newest first.
STATUS_ORDER = ["unacked", "rtn_unacked", "acked", "shelved", "out_of_service", "normal"]


class AckBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alarm_ids: list[str] | None = Field(default=None, max_length=5000)


class ShelveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minutes: int = Field(ge=1, le=MAX_SHELVE_MINUTES)
    reason: str = Field(min_length=1, max_length=500)


def shown_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row["status"] not in ("normal", "out_of_service")]


def _order(row: dict[str, Any]) -> tuple[int, int]:
    return (
        STATUS_ORDER.index(row["status"]),
        list(PRIORITIES).index(row.get("priority") or "medium"),
    )


@router.get("/summary")
def alarm_summary(
    rt: RuntimeDep,
    user: CurrentUser,
    rule: str | None = Query(default=None, max_length=63),
) -> dict[str, Any]:
    """The alarm summary (Active): every alarm that is active, unacknowledged or shelved, and
    counts; only one rule's with ``rule``. ``mine`` marks the alarms the person answers for or
    is notified about ("My alarms")."""

    return summary_of(rt, user, rule)


def summary_of(
    rt: Runtime, user: User, rule: str | None = None, *, dashboards: bool = False
) -> dict[str, Any]:
    """The summary; ``dashboards``: only the alarms whose rule shows them on dashboards (the
    widgets)."""

    scope = rt.asset_scope(user)
    every = rt.alarms.list()
    stored = [alarm for alarm in seen(scope, every) if not rule or alarm.get("rule_id") == rule]
    if dashboards:
        stored = [alarm for alarm in stored if config_of(alarm).get("dashboards", True)]
    names = rule_names(rt)
    rows = mark_mine(rt, [summary(rt, alarm, names) for alarm in stored], user.username)
    counts = {status: 0 for status in STATUS_ORDER}
    for row in rows:
        counts[row["status"]] += 1
    shown = shown_rows(rows)
    shown.sort(key=lambda row: row.get("raised_at") or "", reverse=True)
    shown.sort(key=_order)
    now = rt.clock()
    since = (now - timedelta(hours=24)).isoformat()
    day = of_seen(scope, every, rt.alarms.occurrences(start=since, end=now.isoformat()))
    return {
        "counts": {
            **counts,
            "total": len(rows),
            "active": counts["unacked"] + counts["acked"],
            "unknown": sum(1 for row in rows if row.get("known") is False),
            "last_24h": sum(
                1 for item in day if item["started_at"] >= since and item.get("creates") != "notice"
            ),
            "notices_24h": sum(
                1 for item in day if item["started_at"] >= since and item.get("creates") == "notice"
            ),
            "mine": sum(1 for row in shown_rows(rows) if row["mine"]),
        },
        "alarms": shown,
        "out_of_service": [row for row in rows if row["status"] == "out_of_service"],
        "monitor": rt.status()["monitor"],
        "at": now.isoformat(),
    }


def settle_notifications(rt: Runtime) -> None:
    """Settle at once the notifications of what was just acknowledged (their Acknowledge button
    goes); the monitor's next cycle does it otherwise."""

    try:
        rt.notifier.settle(rt.clock())
    except Exception:  # noqa: BLE001 - the acknowledgement stands whatever PlantCraft answers
        LOGGER.exception("Notifications not settled")


@router.post("/alarms/{alarm_id}/ack")
def acknowledge(alarm_id: str, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    alarm = alarm_or_404(rt, alarm_id, user)
    at = rt.clock().isoformat()
    if rt.alarms.acknowledge(alarm_id, by=user.username, at=at):
        rt.alarms.log(alarm, "acknowledged", at=at, by=user.username)
        settle_notifications(rt)
    return summary(rt, rt.alarms.get(alarm_id) or alarm)


@router.post("/ack")
def acknowledge_many(body: AckBody, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    """Acknowledge the alarms named, or every unacknowledged alarm."""

    at = rt.clock().isoformat()
    wanted = set(body.alarm_ids) if body.alarm_ids is not None else None
    done = 0
    for alarm in seen(rt.asset_scope(user), rt.alarms.list()):
        if wanted is not None and alarm["alarm_id"] not in wanted:
            continue
        if not alarm.get("acked", True) and rt.alarms.acknowledge(
            alarm["alarm_id"], by=user.username, at=at
        ):
            rt.alarms.log(alarm, "acknowledged", at=at, by=user.username)
            done += 1
    if done:
        settle_notifications(rt)
    return {"acknowledged": done}


@router.post("/alarms/{alarm_id}/shelve")
def shelve(alarm_id: str, body: ShelveBody, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    """Shelve the alarm for ``minutes``: it raises nothing until then (ISA-18.2 shelving)."""

    alarm = alarm_or_404(rt, alarm_id, user)
    now = rt.clock()
    until = (now + timedelta(minutes=body.minutes)).isoformat()
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(422, t("Say why the alarm is shelved."))
    longest = rt.philosophy.get().shelve_minutes(alarm.get("priority"))
    if body.minutes > longest:
        raise HTTPException(
            422,
            t(
                "A {priority} alarm is shelved for {hours} h at most (the alarm philosophy).",
                priority=alarm.get("priority") or "medium",
                hours=longest // 60,
            ),
        )
    rt.alarms.shelve(alarm_id, until=until, by=user.username, reason=reason)
    rt.alarms.log(
        alarm,
        "shelved",
        at=now.isoformat(),
        by=user.username,
        detail=t("{minutes} min: {reason}", minutes=body.minutes, reason=reason),
    )
    rt.audit(user, "alarm.shelved", alarm_id, {"until": until, "reason": reason})
    return summary(rt, rt.alarms.get(alarm_id) or alarm)


@router.post("/alarms/{alarm_id}/unshelve")
def unshelve(alarm_id: str, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    alarm = alarm_or_404(rt, alarm_id, user)
    rt.alarms.shelve(alarm_id, until=None, by=user.username, reason="")
    state = alarm.get("state") or {}
    if state.get("active") and alarm.get("acked", True):
        # Still active: it is annunciated again and needs an acknowledgement.
        rt.alarms.set_state(alarm_id, state, raised=True)
    rt.alarms.log(alarm, "unshelved", at=rt.clock().isoformat(), by=user.username)
    rt.audit(user, "alarm.unshelved", alarm_id)
    return summary(rt, rt.alarms.get(alarm_id) or alarm)


@router.get("/journal")
def journal(
    rt: RuntimeDep,
    user: CurrentUser,
    window: str = Query(default="24h", max_length=10),
    alarm: str | None = Query(default=None, max_length=63),
    limit: int = Query(default=500, ge=1, le=5000),
) -> list[dict[str, Any]]:
    end = rt.clock()
    start = end - window_of(window)
    rows = rt.alarms.journal(
        alarm_id=alarm, start=start.isoformat(), end=end.isoformat(), limit=limit
    )
    return of_seen(rt.asset_scope(user), rt.alarms.list(), rows)


NO_CONSOLE = "none"


def _console_of(rt: Runtime, philosophy: Any, alarm: dict[str, Any] | None) -> str | None:
    if alarm is None or not philosophy.consoles:
        return None
    found = philosophy.console_of(rt.tree.area_of(alarm)[0])
    return found.id if found else None


def _performance_input(rt: Runtime, user: User, window: str) -> dict[str, Any]:
    """What the performance figures are made of: the alarms the person sees, the occurrences
    raised in the window, each alarm's console."""

    end = rt.clock()
    start = end - window_of(window)
    every = rt.alarms.list()
    scope = rt.asset_scope(user)
    stored = seen(scope, every)
    philosophy = rt.philosophy.get()
    # Notices are messages, not alarms: they stay out of the ISA-18.2 figures.
    found = of_seen(
        scope,
        every,
        rt.alarms.occurrences(
            start=start.isoformat(), end=end.isoformat(), limit=100000, creates="alarm"
        ),
    )
    names = {alarm["alarm_id"]: alarm["name"] for alarm in stored}
    for item in found:
        names.setdefault(item["alarm_id"], item["name"])
    by_id = {alarm["alarm_id"]: alarm for alarm in stored}
    consoles = {alarm_id: _console_of(rt, philosophy, by_id.get(alarm_id)) for alarm_id in names}
    return {
        "start": start,
        "end": end,
        "stored": stored,
        "found": found,
        "names": names,
        "consoles": consoles,
        "philosophy": philosophy,
    }


def _console_or_404(philosophy: Any, console: str) -> Any:
    if console == NO_CONSOLE:
        return None
    found = philosophy.console(console)
    if found is None:
        raise HTTPException(404, t("No such console."))
    return found


@router.get("/performance")
def alarm_performance(
    rt: RuntimeDep,
    user: CurrentUser,
    window: str = Query(default="24h", max_length=10),
    console: Annotated[str | None, Query(max_length=40)] = None,
) -> dict[str, Any]:
    """Alarm performance over the last ``window`` against ISA-18.2 and EEMUA 191 targets (of
    the alarms on the part of the plant the person sees). With ``console``: only the alarms of
    that operator position, against its own target (``none``: the alarms of no console)."""

    made = _performance_input(rt, user, window)
    philosophy = made["philosophy"]
    found, names = made["found"], made["names"]
    targets, chosen = philosophy, None
    if console:
        chosen = _console_or_404(philosophy, console)
        wanted = chosen.id if chosen else None
        found = [item for item in found if made["consoles"].get(item["alarm_id"]) == wanted]
        targets = philosophy.for_console(chosen)
    owners = {alarm["alarm_id"]: owner_of(alarm) for alarm in made["stored"]}
    result = performance(found, made["start"], made["end"], names=names, targets=targets)
    for group in ("top", "chattering", "stale", "fleeting"):
        for item in result.get(group) or []:
            item["owner"] = owners.get(item["alarm_id"])
    shown = None
    if console:
        shown = (
            {"id": chosen.id, "name": chosen.name, "per_hour": targets.per_person_hour}
            if chosen
            else {"id": NO_CONSOLE, "name": t("No console"), "per_hour": targets.per_person_hour}
        )
    return {**result, "window": window, "console": shown}


def _brief(result: dict[str, Any]) -> dict[str, Any]:
    figures = {item["id"]: item for item in result["figures"]}
    return {
        "total": result["total"],
        "per_hour": figures["per_hour"]["value"],
        "per_hour_status": figures["per_hour"]["status"],
        "peak_10min": result["eemua"]["peak_per_10min"],
        "peak_status": figures["peak"]["status"],
        "flood_share": figures["flood"]["value"],
        "eemua": result["eemua"]["level"],
        "mean_ack_seconds": result["mean_ack_seconds"],
    }


@router.get("/performance/consoles")
def console_performance(
    rt: RuntimeDep, user: CurrentUser, window: str = Query(default="24h", max_length=10)
) -> dict[str, Any]:
    """The load of each operator position in the last ``window`` against its own target: the
    alarms an hour, the peak in 10 minutes, the time in flood and the EEMUA 191 level."""

    made = _performance_input(rt, user, window)
    philosophy = made["philosophy"]
    groups: dict[str | None, list[dict[str, Any]]] = {}
    for item in made["found"]:
        groups.setdefault(made["consoles"].get(item["alarm_id"]), []).append(item)
    alarms: dict[str | None, int] = {}
    for alarm in made["stored"]:
        if (alarm.get("creates") or "alarm") != "alarm":
            continue
        key = made["consoles"].get(alarm["alarm_id"])
        alarms[key] = alarms.get(key, 0) + 1
    rows = []
    for console in [*philosophy.consoles, None]:
        key = console.id if console else None
        if console is None and not groups.get(None) and not alarms.get(None):
            continue
        targets = philosophy.for_console(console)
        result = performance(groups.get(key, []), made["start"], made["end"],
                             names=made["names"], targets=targets)  # fmt: skip
        rows.append(
            {
                "id": key or NO_CONSOLE,
                "name": console.name if console else t("No console"),
                "operators": console.operators if console else [],
                "areas": console.areas if console else [],
                "target_per_hour": targets.per_person_hour,
                "alarms": alarms.get(key, 0),
                **_brief(result),
            }
        )
    return {"window": window, "consoles": rows, "defined": len(philosophy.consoles)}


@router.post("/run")
def run_now(rt: RuntimeDep, _user: EditorUser) -> dict[str, Any]:
    """Evaluate every alarm now (the monitor would at its next cycle)."""

    if not rt.has_service_key:
        raise HTTPException(503, t("Alarms needs its app key to read the plant: an admin sets it."))
    return rt.monitor.run_cycle()
