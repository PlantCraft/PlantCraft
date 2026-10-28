"""Who an alarm reaches: the policies that match it, the silences that hold it back, and the
people and groups each policy names. Pure functions over plain dicts (the stores' rows), so the
monitor, a rule's Notify and Active's "My alarms" agree.

An alarm's *context* is what policies and silences look at: its id, priority, discipline,
owner and ``areas``, the chain of asset ids from the root of the asset tree down to its area
(or its asset). A policy's area matches when it is anywhere in that chain, so "Unit 100" covers
every area, equipment and loop under it.

A policy with hours matches only inside them (or, ``hours_mode`` "outside", only outside them),
read on the policy's own time zone. Pass ``now=None`` to ask which alarms a policy covers at all
(Active's "My alarms"): the hours are then left out.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from alarmcraft.alarms.model import PRIORITIES
from alarmcraft.alarms.notices import COORDINATOR, DAYS, minutes_of, zone_of

RANK = {priority: index for index, priority in enumerate(PRIORITIES)}


def context(alarm: dict[str, Any], chain: list[str], *, owner: str | None = None) -> dict[str, Any]:
    return {
        "alarm_id": alarm.get("alarm_id"),
        "priority": alarm.get("priority") or "medium",
        "discipline": alarm.get("discipline"),
        "owner": owner if owner is not None else alarm.get("owner"),
        "areas": list(chain),
    }


def _covers(areas: list[str], disciplines: list[str], ctx: dict[str, Any]) -> bool:
    if areas and not set(areas) & set(ctx["areas"]):
        return False
    return not (disciplines and ctx.get("discipline") not in disciplines)


def in_windows(windows: list[dict[str, Any]], local: datetime) -> bool:
    """Whether the wall-clock time ``local`` falls in one of the windows."""

    for window in windows:
        start, end = minutes_of(window["start"]), minutes_of(window["end"])
        span = end - start if end > start else end + 24 * 60 - start
        for back in (0, 1):
            day = local.date() - timedelta(days=back)
            if DAYS[day.weekday()] not in window.get("days", []):
                continue
            # Wall-clock time in the policy's own zone (``local``), so naive on purpose.
            begins = datetime(day.year, day.month, day.day) + timedelta(minutes=start)  # noqa: DTZ001
            if begins <= local.replace(tzinfo=None) < begins + timedelta(minutes=span):
                return True
    return False


def in_hours(policy: dict[str, Any], now: datetime) -> bool:
    """Whether the policy sends at ``now`` (always, inside its hours or outside them)."""

    mode = policy.get("hours_mode") or "always"
    if mode == "always" or not policy.get("hours"):
        return True
    local = now.astimezone(zone_of(policy.get("timezone")))
    inside = in_windows(policy["hours"], local)
    return inside if mode == "inside" else not inside


def matches(policy: dict[str, Any], ctx: dict[str, Any], now: datetime | None = None) -> bool:
    if not policy.get("enabled", True):
        return False
    if now is not None and not in_hours(policy, now):
        return False
    wanted = RANK.get(policy.get("min_priority") or "low", len(RANK))
    if RANK.get(ctx["priority"], len(RANK)) > wanted:
        return False
    return _covers(policy.get("areas") or [], policy.get("disciplines") or [], ctx)


def routes(
    policies: list[dict[str, Any]], ctx: dict[str, Any], now: datetime | None = None
) -> list[dict[str, Any]]:
    """Every policy (a rule's notifications) that matches (at ``now``)."""

    return [policy for policy in policies if matches(policy, ctx, now)]


def silenced_by(
    silences: list[dict[str, Any]], ctx: dict[str, Any], now: datetime
) -> dict[str, Any] | None:
    moment = now.isoformat()
    for silence in silences:
        if not (silence["starts_at"] <= moment < silence["ends_at"]):
            continue
        ids = silence.get("alarm_ids") or []
        if ids and ctx["alarm_id"] not in ids:
            continue
        if _covers(silence.get("areas") or [], silence.get("disciplines") or [], ctx):
            return silence
    return None


def recipients(policy: dict[str, Any], owner: str | None) -> list[str]:
    """The policy's recipients with ``owner`` replaced by the alarm's owner."""

    found: list[str] = []
    for item in policy.get("recipients") or []:
        value = owner if item == "owner" else item
        if value and value not in found:
            found.append(value)
    return found


def escalation_recipients(
    step: dict[str, Any],
    policy: dict[str, Any],
    owner: str | None,
    coordinators: dict[str, str | None],
) -> list[str]:
    """An escalation step's recipients: ``owner`` is the alarm's owner and ``coordinator`` the
    coordinators of the groups the policy names (``coordinators``: group id → username)."""

    found: list[str] = []
    for item in step.get("recipients") or []:
        if item == COORDINATOR:
            names = [
                coordinators.get(ref.partition(":")[2])
                for ref in recipients(policy, owner)
                if ref.startswith("group:")
            ]
            values = [f"user:{name}" for name in names if name]
        else:
            values = [owner if item == "owner" else item]
        for value in values:
            if value and value not in found:
                found.append(value)
    return found


def reaches(refs: list[str], username: str, groups: dict[str, list[str]]) -> bool:
    """Whether ``user:``/``group:`` references include ``username`` (``groups``: id → members)."""

    for ref in refs:
        kind, _, name = ref.partition(":")
        if kind == "user" and name == username:
            return True
        if kind == "group" and username in groups.get(name, []):
            return True
    return False
