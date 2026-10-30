"""The part of the plant a person sees (PlantCraft's docs/asset-scope.md): their
token's claim ``assets`` names the roots of the asset tree they see. Alarms shows them only the
alarms on those assets and their signals; any other reads as not found.

An alarm is about its asset (``asset_id``, else its rule's ``subject``), else its signal. An
alarm on an execution of an app, or on nothing of the plant, stays visible.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated, Any

from fastapi import Depends
from plantcraft_sdk.asset_scope import AssetScope
from plantcraft_sdk.server.access import CurrentUser

from alarmcraft.api.deps import RuntimeDep


def asset_scope(user: CurrentUser, rt: RuntimeDep) -> AssetScope:
    return rt.asset_scope(user)


Scope = Annotated[AssetScope, Depends(asset_scope)]


def sees_alarm(scope: AssetScope, alarm: dict[str, Any]) -> bool:
    if scope.everything:
        return True
    asset = str(alarm.get("asset_id") or "")
    if asset:
        return scope.asset(asset)
    subject = str(alarm.get("subject") or "")
    if subject and not subject.startswith("execution:"):
        return scope.asset(subject)
    source = alarm.get("source") if isinstance(alarm.get("source"), dict) else {}
    signal = source.get("signal_id") or (alarm.get("state") or {}).get("signal")
    return scope.signal(str(signal)) if signal else True


def seen(scope: AssetScope, alarms: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [alarm for alarm in alarms if sees_alarm(scope, alarm)]


def of_seen(
    scope: AssetScope, alarms: Iterable[dict[str, Any]], rows: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Rows of alarms (occurrences, journal lines) whose alarm the person sees; a row of an
    alarm deleted since stays out for who sees only part of the plant."""

    rows = list(rows)
    if scope.everything:
        return rows
    ids = {alarm["alarm_id"] for alarm in seen(scope, alarms)}
    return [row for row in rows if row.get("alarm_id") in ids]


__all__ = ["Scope", "of_seen", "sees_alarm", "seen"]
