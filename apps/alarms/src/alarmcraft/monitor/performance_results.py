"""The alarm performance of each part of the plant, published as a result (``alarm_performance``)
so other apps read it without calling Alarms: View's reports print it (ISA-18.2 section).

One result per asset that heads alarms: the root of the asset tree (the site, every alarm under
it) and each area (the root's children, or an alarm's own ``area``). Its ``detail`` holds the
Performance page's reading (``engine.performance``) over the last 24 hours, 7 days and 30 days:
the figures against the philosophy's targets, the EEMUA 191 level, the floods, the time to
acknowledge by priority, the 20 most frequent and the fleeting alarms. Alarms on no asset are
only on the Performance page. Published once an hour; each result expires after two, so a
stopped Alarms leaves no old figures behind.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from plantcraft_sdk.refs import format_ref

from alarmcraft.engine.performance import performance

KIND = "alarm_performance"
EVERY = timedelta(hours=1)
EXPIRES = timedelta(hours=2)
PERIODS = {"24h": timedelta(days=1), "7d": timedelta(days=7), "30d": timedelta(days=30)}
# PlantCraft keeps a result's detail to 16 KiB of JSON; the lists shrink until it fits.
MAX_DETAIL = 15_000
CAPS = (20, 10, 5, 3)
WORST = ["ok", "unknown", "warning", "alarm"]


def subjects_of(alarm: dict[str, Any], tree: Any) -> list[str]:
    """The assets whose performance counts this alarm: its root and its area."""

    chain, area = tree.area_of(alarm)
    found = [chain[0]] if chain else []
    if area and area.get("id") and str(area["id"]) not in found:
        found.append(str(area["id"]))
    return found


def _short(text: Any, limit: int = 60) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _period(reading: dict[str, Any], cap: int) -> dict[str, Any]:
    return {
        "start": reading["start"],
        "end": reading["end"],
        "total": reading["total"],
        "figures": [
            {k: figure.get(k) for k in ("id", "label", "value", "unit", "target", "status")}
            for figure in reading["figures"]
        ],
        "eemua": {k: v for k, v in reading["eemua"].items() if k != "bands"},
        "floods": reading["floods"][-cap:],
        "flood_count": len(reading["floods"]),
        "flood_minutes": reading["flood_minutes"],
        "acknowledge": reading["acknowledge"],
        "mean_ack_seconds": reading["mean_ack_seconds"],
        "unacked": reading["unacked"],
        "priorities": reading["priorities"],
        "top": [
            {
                "alarm_id": row["alarm_id"],
                "name": _short(row["name"]),
                "count": row["count"],
                "share": row["share"],
                "priority": row["priority"],
                "chattering": row["chattering"],
            }
            for row in reading["top"][:cap]
        ],
        "fleeting": [
            {"alarm_id": row["alarm_id"], "name": _short(row["name"]), "count": row["count"]}
            for row in reading["fleeting"][:cap]
        ],
        "stale": len(reading["stale"]),
        "chattering": len(reading["chattering"]),
    }


def performance_results(
    alarms: list[dict[str, Any]],
    occurrences: list[dict[str, Any]],
    tree: Any,
    *,
    now: datetime,
    targets: Any = None,
    url: str = "",
) -> list[dict[str, Any]]:
    """The ``alarm_performance`` result of each asset that heads alarms. ``occurrences``: the
    alarms' occurrences of the last 30 days (``AlarmStore.occurrences(creates="alarm")``)."""

    names = {alarm["alarm_id"]: alarm.get("name") or alarm["alarm_id"] for alarm in alarms}
    under: dict[str, set[str]] = defaultdict(set)
    for alarm in alarms:
        for subject in subjects_of(alarm, tree):
            under[subject].add(alarm["alarm_id"])
    rows = []
    for asset_id in sorted(under):
        ids = under[asset_id]
        found = [item for item in occurrences if item.get("alarm_id") in ids]
        readings = {
            key: performance(found, now - span, now, names=names, targets=targets)
            for key, span in PERIODS.items()
        }
        detail: dict[str, Any] = {}
        for cap in CAPS:
            detail = {
                "alarms": len(ids),
                "url": url,
                "periods": {key: _period(reading, cap) for key, reading in readings.items()},
            }
            if len(json.dumps(detail, separators=(",", ":"))) <= MAX_DETAIL:
                break
        day = readings["24h"]
        status = max(
            (figure["status"] for figure in day["figures"]),
            key=lambda value: WORST.index(value) if value in WORST else 1,
            default="ok",
        )
        level = day["eemua"]["level"]
        rows.append(
            {
                "subject": format_ref("asset", asset_id),
                "kind": KIND,
                "status": status,
                "score": None,
                "usable": None,
                "value": float(day["total"]),
                "summary": _short(
                    f"{day['total']} alarms in 24 h, EEMUA 191 {level}, "
                    f"{len(day['floods'])} floods",
                    300,
                ),
                "detail": detail,
                "at": now.isoformat(),
                "expires_at": (now + EXPIRES).isoformat(),
            }
        )
    return rows
