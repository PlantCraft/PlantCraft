"""Where a rule applies: its subjects on the asset tree and in the suite's executions. Pure
functions over plain dicts (the asset tree as ``{id: asset}``, the executions as API v1
``GET /schedules`` lists them, with their ``subjects``), shared by the monitor and the editor's
Test, so what a person tests is what the plant will see.

A branch (``under``) covers the asset itself and every asset below it; a type covers every
asset whose type (or a type above it) is named; an execution covers the assets it runs on. A
rule over a role covers, under its branches and types, only the assets that have the role (a
pump has no PV). A rule ``anywhere`` has no subjects of its own: the events name them.
"""

from __future__ import annotations

from typing import Any

from alarmcraft.alarms.blocks import VALUE_BLOCK, nodes
from alarmcraft.alarms.rules import RuleDraft
from alarmcraft.engine.run import Subject

# A rule covers at most this many subjects (the rest are left out and the rule says so).
MAX_SUBJECTS = 5000


def descendants(assets: dict[str, dict], roots: list[str]) -> list[str]:
    """The roots and every asset below them, roots first, each once."""

    children: dict[str, list[str]] = {}
    for asset_id, asset in assets.items():
        parent = asset.get("parent_id")
        if parent:
            children.setdefault(str(parent), []).append(asset_id)
    found: list[str] = []
    seen: set[str] = set()
    queue = [root for root in roots if root in assets]
    while queue and len(found) < 20000:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        found.append(current)
        queue.extend(sorted(children.get(current, [])))
    return found


def chain(assets: dict[str, dict], asset_id: str | None) -> list[str]:
    """The asset ids from ``asset_id`` up to the root."""

    found: list[str] = []
    current = asset_id
    while current and current in assets and current not in found and len(found) < 50:
        found.append(current)
        current = assets[current].get("parent_id")
    return found


def _name(assets: dict[str, dict], asset_id: str) -> str:
    return str((assets.get(asset_id) or {}).get("name") or asset_id)


def _roles(rule: RuleDraft) -> set[str]:
    return {
        str((node.get("parameters") or {}).get("role") or "")
        for node in nodes(rule.diagram, VALUE_BLOCK)
    } - {""}


def execution_assets(schedules: list[dict[str, Any]], executions: list[str]) -> list[str]:
    """The assets the named executions (``<app>:<id>``) run on, in order."""

    found: list[str] = []
    wanted = set(executions)
    for schedule in schedules:
        if f"{schedule.get('app')}:{schedule.get('id')}" not in wanted:
            continue
        for ref in schedule.get("subjects") or []:
            kind, _, value = str(ref).partition(":")
            if kind == "asset" and value and value not in found:
                found.append(value)
    return found


def asset_subject(assets: dict[str, dict], asset_id: str, *, single: bool) -> Subject:
    return Subject(
        asset_id,
        "asset",
        asset_id,
        assets.get(asset_id),
        None if single else _name(assets, asset_id),
    )


def subjects(
    rule: RuleDraft, assets: dict[str, dict], schedules: list[dict[str, Any]] | None = None
) -> list[Subject]:
    """The subjects of a rule (an asset named but unknown to PlantCraft stays, so its alarm can
    say why). A rule ``anywhere`` answers none: the events name its subjects."""

    where = rule.where
    if where.anywhere:
        return []
    if where.empty:
        return [Subject("", "none")]
    if where.per == "execution":
        found = []
        names = {f"{item.get('app')}:{item.get('id')}": item for item in schedules or []}
        for execution in where.executions:
            app, _, schedule = execution.partition(":")
            label = str((names.get(execution) or {}).get("name") or schedule)
            found.append(Subject(f"execution:{execution}", "execution", schedule, None, label, app))
        return found
    roles = _roles(rule)
    chosen = list(where.assets)
    broad = descendants(assets, where.under)
    if where.types:
        wanted = set(where.types)
        broad += [
            asset_id
            for asset_id, asset in assets.items()
            if asset.get("kind") in wanted or wanted & set(asset.get("type_path") or [])
        ]
    broad += execution_assets(schedules or [], where.executions)
    for asset_id in broad:
        if asset_id in chosen or asset_id not in assets:
            continue
        signals = assets[asset_id].get("signals") or {}
        if all(role in signals for role in roles):
            chosen.append(asset_id)
    single = rule.single
    return [asset_subject(assets, asset_id, single=single) for asset_id in chosen[:MAX_SUBJECTS]]


def event_assets(event: dict[str, Any], assets: dict[str, dict]) -> list[str]:
    """The assets an event names: its subject, its refs, or the asset that holds its signal."""

    named: list[str] = []
    holders: dict[str, str] = {}
    for ref in [event.get("subject"), *(event.get("refs") or [])]:
        kind, _, value = str(ref or "").partition(":")
        if kind == "asset" and value:
            named.append(value)
        elif kind == "signal" and value:
            if not holders:
                holders = {
                    str(signal): asset_id
                    for asset_id, asset in assets.items()
                    for signal in (asset.get("signals") or {}).values()
                }
            if value in holders:
                named.append(holders[value])
    return list(dict.fromkeys(named))
