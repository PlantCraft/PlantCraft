"""What a schedule records in the Historian: its "Recorded outputs" part (Link round 8, D6).

Each port the algorithm marks to record is one row of the schedule's part, chosen one by one:
record it or not, and for how long. A row becomes points of the schedule's result asset on each
asset, ``app-linkcraft:<asset>.<schedule key>.<output>``:

- a number: one value per execution, kept 400 days by default;
- a verdict (``result``): its score (``/100``) and its status as text, two points, kept forever
  by default (the final index of an algorithm);
- a series: one whole series per execution (a runs point), the last 10 kept by default.

The schedule's choices are stored as ``{output key: {"record": bool, "keep": {...}}}``; ``keep``
is ``{"forever": true}``, ``{"days": N}`` or, for a series, ``{"runs": N}``. The Historian keeps
each point's retention locked to the schedule (``managed_by``), so people change it here only.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from plantcraft_sdk.assets import MAX_RESULT_ASSETS
from plantcraft_sdk.blocks import label_of
from plantcraft_sdk.derived import (
    DEFAULT_KEEP_RUNS,
    MAX_KEEP_RUNS,
    MAX_NAME,
    MAX_RETENTION_DAYS,
    DerivedIn,
    RunIn,
    source_of,
)
from plantcraft_sdk.refs import asset_ref
from pydantic import ValidationError

from linkcraft.assets.run import timing_of
from linkcraft.blocks import compile_algorithm
from linkcraft.blocks.catalog import CATALOG
from linkcraft.blocks.convert import diagram_of
from linkcraft.blocks.run import recorded_keys
from linkcraft.i18n import t

LOGGER = logging.getLogger(__name__)
APP_ID = "linkcraft"
# How a recorded port is kept, by its port type.
SINGLE, VERDICT, SERIES = "number", "verdict", "series"
KIND_OF_PORT = {"number": SINGLE, "result": VERDICT, "series": SERIES}
DEFAULT_DAYS = 400
# The status point of a verdict: ``<output>.status``.
STATUS_SUFFIX = "status"
# Bytes a stored value takes in the Historian, about (3 to 8 today).
BYTES_PER_VALUE = 6
MAX_POINTS_PER_RUN = 20_000


def default_keep(kind: str) -> dict[str, Any]:
    if kind == VERDICT:
        return {"forever": True}
    if kind == SERIES:
        return {"runs": DEFAULT_KEEP_RUNS}
    return {"days": DEFAULT_DAYS}


def checked_keep(kind: str, keep: Any) -> dict[str, Any]:
    """A ``keep`` choice as stored; ``ValueError`` names what is wrong."""

    if not isinstance(keep, dict):
        raise ValueError(t("Choose how long each output is kept."))
    if keep.get("forever"):
        if kind == SERIES:
            raise ValueError(t("A derived signal is kept for a number of runs or days."))
        return {"forever": True}
    if keep.get("runs") is not None:
        if kind != SERIES:
            raise ValueError(t("Only a derived signal is kept by runs."))
        runs = int(keep["runs"])
        if not 1 <= runs <= MAX_KEEP_RUNS:
            raise ValueError(t("Keep 1 to {count} runs.", count=MAX_KEEP_RUNS))
        return {"runs": runs}
    days = int(keep.get("days") or 0)
    if not 1 <= days <= MAX_RETENTION_DAYS:
        raise ValueError(t("Keep 1 to {count} days.", count=MAX_RETENTION_DAYS))
    return {"days": days}


def algorithm_outputs(config: dict[str, Any]) -> list[dict[str, Any]]:
    """The ports an algorithm (its stored ``method_config``) records, one row each:
    ``{key, name, kind, unit, description, values_per_run}``; none for an invalid diagram."""

    try:
        plan = compile_algorithm(diagram_of(config or {}))
    except Exception:  # an algorithm Link cannot read records nothing
        return []
    if not plan.valid:
        return []
    timing = timing_of(config)
    window = max(1, int(timing.window_seconds / max(timing.step_seconds, 1.0)))
    rows = []
    for (node_id, port_id), key in recorded_keys(plan).items():
        node = plan.nodes[node_id]
        port = CATALOG[node["block"]].spec.output(port_id)
        if port is None or port.type not in KIND_OF_PORT:
            continue
        kind = KIND_OF_PORT[port.type]
        name = label_of(node, CATALOG)
        if "." in key:  # a block that records several ports names the port too
            name = f"{name} {t(port.label)}".strip()
        rows.append(
            {
                "key": key,
                "name": name,
                "kind": kind,
                "unit": "/100" if kind == VERDICT else port.unit or "",
                "description": t(port.description or ""),
                "values_per_run": min(window, MAX_POINTS_PER_RUN) if kind == SERIES else 1,
            }
        )
    return rows


def schedule_outputs(
    config: dict[str, Any], chosen: dict[str, Any] | None, *, runs_per_day: float = 0.0
) -> list[dict[str, Any]]:
    """The algorithm's outputs with the schedule's choices (defaults where it made none) and
    what each costs: ``values_per_day`` and ``stored_values`` per asset, ``stored_bytes``."""

    rows = []
    for row in algorithm_outputs(config):
        choice = (chosen or {}).get(row["key"]) or {}
        record = bool(choice.get("record", True))
        try:
            keep = checked_keep(row["kind"], choice.get("keep") or default_keep(row["kind"]))
        except ValueError:
            keep = default_keep(row["kind"])
        rows.append({**row, "record": record, "keep": keep, **cost(row, keep, runs_per_day)})
    return rows


def cost(row: dict[str, Any], keep: dict[str, Any], runs_per_day: float) -> dict[str, Any]:
    """Values written per day and kept at most, per asset (forever: what one year keeps)."""

    points = 2 if row["kind"] == VERDICT else 1
    per_run = int(row.get("values_per_run") or 1) * points
    per_day = per_run * max(runs_per_day, 0.0)
    if keep.get("runs"):
        stored = per_run * int(keep["runs"])
        if runs_per_day <= 0:
            stored = 0
    else:
        days = 365 if keep.get("forever") else int(keep.get("days") or 0)
        stored = per_day * days
    return {
        "values_per_day": round(per_day, 1),
        "stored_values": int(stored),
        "stored_bytes": int(stored * BYTES_PER_VALUE),
        "grows": bool(keep.get("forever")),
    }


def checked_choices(config: dict[str, Any], chosen: Any) -> dict[str, Any]:
    """A schedule's ``outputs`` as stored: only the algorithm's own keys, each checked."""

    if chosen in (None, {}):
        return {}
    if not isinstance(chosen, dict):
        raise ValueError(t("Choose the recorded outputs one by one."))
    kinds = {row["key"]: row["kind"] for row in algorithm_outputs(config)}
    found: dict[str, Any] = {}
    for key, choice in chosen.items():
        if key not in kinds:
            continue  # an output the algorithm no longer records
        if not isinstance(choice, dict):
            raise ValueError(t("Choose the recorded outputs one by one."))
        entry: dict[str, Any] = {"record": bool(choice.get("record", True))}
        if choice.get("keep") is not None:
            entry["keep"] = checked_keep(kinds[key], choice["keep"])
        found[key] = entry
    return found


def retention(keep: dict[str, Any]) -> dict[str, Any]:
    """The Historian fields of a ``keep``: ``retention_days`` (0: forever) for single values,
    ``keep_runs`` and ``keep_days`` for a series."""

    if keep.get("runs"):
        return {"keep_runs": int(keep["runs"]), "keep_days": None}
    if keep.get("forever"):
        return {"retention_days": 0}
    return {"retention_days": int(keep["days"])}


def managed_by(schedule_id: str) -> str:
    """Who sets a point's retention in the Historian: this schedule in Link."""

    return f"link:{schedule_id}"[:100]


def point_keys(row: dict[str, Any]) -> list[tuple[str, str]]:
    """``(point suffix, kind)`` of the points one output row writes."""

    if row["kind"] == VERDICT:
        return [(row["key"], "number"), (f"{row['key']}.{STATUS_SUFFIX}", "text")]
    if row["kind"] == SERIES:
        return [(row["key"], "runs")]
    return [(row["key"], "number")]


def role_of(suffix: str, taken: set[str]) -> str:
    """A point's role in its result asset (``health.status`` → ``health_status``), unique."""

    base = re.sub(r"[^a-z0-9]+", "_", suffix.lower()).strip("_")[:50] or "output"
    if not base[0].isalpha():
        base = f"o_{base}"
    role, number = base, 2
    while role in taken:
        role, number = f"{base}_{number}", number + 1
    taken.add(role)
    return role


def recording(schedule: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any] | None:
    """What one execution of an asset schedule records: ``{schedule_id, key, name, outputs}``
    with the rows it records; None for a run without a schedule (it records nothing new)."""

    if not schedule or schedule.get("subject_kind") != "asset" or not schedule.get("output_key"):
        return None
    rows = schedule_outputs(profile.get("method_config") or {}, schedule.get("outputs"))
    return {
        "schedule_id": schedule["schedule_id"],
        "key": schedule["output_key"],
        "name": schedule.get("name") or schedule["output_key"],
        "outputs": [row for row in rows if row["record"]],
    }


def recorded_points(
    payload: dict[str, Any], schedule: dict[str, Any], at: str
) -> dict[str, list[dict[str, Any]]]:
    """What one execution writes for its schedule (``recording``): ``values`` (``PUT
    /api/v1/series``) and ``runs`` (``PUT /api/v1/series/runs``), under
    ``app-linkcraft:<asset>.<schedule key>.<output>``, named ``<tag> · <schedule> · <output>``,
    kept as the schedule says (``managed_by``). ``at``: when the execution ended."""

    asset_id = str(payload["asset"]["id"])
    tag = str((payload.get("config") or {}).get("name") or asset_id)
    summary = payload.get("summary") or {}
    entries = {
        str(entry.get("key") or f"{entry.get('node_id')}.{entry.get('port')}"): entry
        for entry in summary.get("recorded") or []
        if isinstance(entry, dict)
    }
    base = f"{source_of(APP_ID)}:{asset_id}.{schedule['key']}"
    run_at = str((summary.get("window") or {}).get("end") or at)
    common = {"subject": asset_ref(asset_id), "managed_by": managed_by(schedule["schedule_id"])}
    found: dict[str, list[dict[str, Any]]] = {"values": [], "runs": []}
    for row in schedule.get("outputs") or []:
        entry = entries.get(row["key"])
        if not row.get("record") or entry is None:
            continue
        named = {
            **common,
            "name": f"{tag} · {schedule['name']} · {row['name']}"[:MAX_NAME],
            "unit": row.get("unit") or "",
            "description": row.get("description") or "",
        }
        keep = retention(row["keep"])
        if row["kind"] == SERIES:
            points = entry.get("points") or {}
            if points.get("t"):
                item = {
                    **named,
                    "signal": f"{base}.{row['key']}",
                    "run_at": run_at,
                    "t": list(points["t"]),
                    "v": list(points["v"]),
                    "keep_runs": keep["keep_runs"],
                }
                _add(found["runs"], RunIn, item)
            continue
        value = entry.get("value")
        item = {
            **named,
            **keep,
            "signal": f"{base}.{row['key']}",
            "t": [at],
            "v": [None if value is None else float(value)],
            "kind": "number",
        }
        _add(found["values"], DerivedIn, item)
        if row["kind"] == VERDICT:
            status = {
                **item,
                "signal": f"{base}.{point_keys(row)[1][0]}",
                "name": f"{named['name']} · {t('Status')}"[:MAX_NAME],
                "unit": "",
                "v": [str(entry.get("status") or "unknown")],
                "kind": "text",
            }
            _add(found["values"], DerivedIn, status)
    return found


def _add(found: list[dict[str, Any]], model: Any, item: dict[str, Any]) -> None:
    try:
        model.model_validate(item)
    except ValidationError as exc:
        LOGGER.warning("Not publishing %s: %s", item["signal"], exc.errors()[0]["msg"])
        return
    found.append(item)


def result_assets(
    schedules: list[dict[str, Any]],
    config_of: Callable[[str], dict[str, Any]],
    names: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """One result asset per asset of each schedule that records outputs, under that asset:
    ``linkcraft.<asset>.<schedule key>``, holding the points the schedule writes there.
    ``config_of``: an algorithm's stored configuration; ``names``: the assets' names."""

    items: list[dict[str, Any]] = []
    for schedule in schedules:
        if schedule.get("subject_kind") != "asset" or not schedule.get("output_key"):
            continue
        config = config_of(schedule.get("profile_id") or "")
        rows = [row for row in schedule_outputs(config, schedule.get("outputs")) if row["record"]]
        if not rows:
            continue
        key = schedule["output_key"]
        title = schedule.get("name") or key
        for asset_id in (schedule.get("selector") or {}).get("ids") or []:
            base = f"{source_of(APP_ID)}:{asset_id}.{key}"
            taken: set[str] = set()
            points = []
            for row in rows:
                for suffix, kind in point_keys(row):
                    status = suffix != row["key"]
                    points.append(
                        {
                            "role": role_of(suffix, taken),
                            "signal": f"{base}.{suffix}",
                            "name": f"{row['name']} · {t('Status')}" if status else row["name"],
                            "unit": "" if kind == "text" else row.get("unit") or "",
                        }
                    )
            tag = (names or {}).get(asset_id) or asset_id
            items.append(
                {
                    "id": f"{APP_ID}.{asset_id}.{key}",
                    "parent_id": asset_id,
                    "name": f"{tag} · {title}"[:MAX_NAME],
                    "description": t("What the monitor {name} records on this asset.", name=title),
                    "made_by": f"schedule:{schedule['schedule_id']}",
                    "points": points,
                }
            )
    if len(items) > MAX_RESULT_ASSETS:
        LOGGER.warning("%d result assets; PlantCraft keeps %d.", len(items), MAX_RESULT_ASSETS)
    return items[:MAX_RESULT_ASSETS]


def runs_per_day(schedule: dict[str, Any], upcoming: list[str] | None = None) -> float:
    """How many times a schedule runs a day, about (a calendar from its next occurrences)."""

    cadence = schedule.get("cadence")
    if cadence == "interval":
        minutes = float(schedule.get("interval_minutes") or 0)
        return 1440.0 / minutes if minutes > 0 else 0.0
    if cadence == "hourly":
        return 24.0
    if cadence == "daily":
        return 1.0
    if cadence == "weekly":
        return 1 / 7
    if cadence == "calendar" and upcoming and len(upcoming) > 1:
        from datetime import datetime

        first, last = datetime.fromisoformat(upcoming[0]), datetime.fromisoformat(upcoming[-1])
        days = (last - first).total_seconds() / 86400
        return (len(upcoming) - 1) / days if days > 0 else 0.0
    return 0.0


__all__ = [
    "SERIES",
    "SINGLE",
    "VERDICT",
    "algorithm_outputs",
    "checked_choices",
    "checked_keep",
    "cost",
    "default_keep",
    "managed_by",
    "point_keys",
    "recorded_points",
    "recording",
    "result_assets",
    "retention",
    "role_of",
    "runs_per_day",
    "schedule_outputs",
]
