"""Alarm performance over a period, against the installation's alarm philosophy (its defaults are
the public ISA-18.2 and EEMUA 191 targets below; ``alarms.philosophy``).

Figures are for one operator position (every alarm of this installation). Shelved and
out-of-service alarms raise no occurrence, so they never count.

| Figure | Target (acceptable / manageable) |
|---|---|
| Average alarms per hour | ≤ 6 / ≤ 12 |
| Average alarms per 10 minutes | ≤ 1 / ≤ 2 |
| Share of 10-minute periods in flood (more than 10 alarms) | < 1 % |
| Peak alarms in 10 minutes | ≤ 10 |
| Share of the load from the 10 most frequent alarms | ≤ 5 % (10 % still manageable) |
| Chattering alarms (3 or more raises within a minute) | none |
| Stale alarms (active for more than 24 hours) | fewer than 5 |
| Priority distribution (high and critical / medium / low) | about 5 % / 15 % / 80 % |
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

FLOOD_ALARMS = 10
SLOT = timedelta(minutes=10)
HOUR = timedelta(hours=1)
CHATTER_COUNT = 3
CHATTER_SECONDS = 60.0
STALE_HOURS = 24.0
PRIORITY_TARGETS = {"high": 5.0, "medium": 15.0, "low": 80.0}


def _time(text: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text)) if text else None
    except ValueError:
        return None


def _status(value: float, acceptable: float, manageable: float) -> str:
    if value <= acceptable:
        return "ok"
    return "warning" if value <= manageable else "alarm"


def performance(
    occurrences: list[dict[str, Any]],
    start: datetime,
    end: datetime,
    *,
    names: dict[str, str] | None = None,
    targets: Any = None,
) -> dict[str, Any]:
    """Every figure of the Performance page for the occurrences raised in [start, end];
    ``targets``: the philosophy (``PhilosophyDraft``), else the public defaults."""

    names = names or {}
    per_person = float(getattr(targets, "per_person_hour", 6))
    flood_alarms = int(getattr(targets, "flood_alarms", FLOOD_ALARMS))
    chatter_count = int(getattr(targets, "chatter_minute", CHATTER_COUNT))
    stale_hours = float(getattr(targets, "stale_hours", STALE_HOURS))
    priority_targets = targets.targets() if targets is not None else PRIORITY_TARGETS
    hours = max((end - start).total_seconds() / 3600.0, 1e-9)
    raised = []
    for item in occurrences:
        moment = _time(item.get("started_at"))
        if moment is not None and start <= moment <= end:
            raised.append((moment, item))
    raised.sort(key=lambda pair: pair[0])
    total = len(raised)

    slots = max(1, math.ceil((end - start) / SLOT))
    per_slot = [0] * slots
    for moment, _ in raised:
        index = min(slots - 1, int((moment - start) / SLOT))
        per_slot[index] += 1
    flood_slots = sum(1 for count in per_slot if count > flood_alarms)

    # Raised per whole hour (the first and the last may be partial), by priority: the
    # Overview's columns against the per-hour target.
    first_hour = start.replace(minute=0, second=0, microsecond=0)
    hour_count = max(1, math.ceil((end - first_hour) / HOUR))
    hourly: list[Counter[str]] = [Counter() for _ in range(hour_count)]
    for moment, item in raised:
        hourly[min(hour_count - 1, int((moment - first_hour) / HOUR))][
            item.get("priority") or "medium"
        ] += 1

    counts = Counter(item["alarm_id"] for _, item in raised)
    # Each alarm's priority when it last went off (the bad actors' colour).
    last_priority = {item["alarm_id"]: item.get("priority") or "medium" for _, item in raised}
    top = counts.most_common(10)
    top_share = 100.0 * sum(count for _, count in top) / total if total else 0.0

    by_alarm: dict[str, list[datetime]] = defaultdict(list)
    for moment, item in raised:
        by_alarm[item["alarm_id"]].append(moment)
    chattering = []
    for alarm_id, moments in by_alarm.items():
        for index in range(len(moments) - chatter_count + 1):
            window = (moments[index + chatter_count - 1] - moments[index]).total_seconds()
            if window <= CHATTER_SECONDS:
                chattering.append(alarm_id)
                break

    stale = []
    for item in occurrences:
        began = _time(item.get("started_at"))
        ended = _time(item.get("ended_at")) or end
        if (
            began is not None
            and (ended - began).total_seconds() >= stale_hours * 3600
            and ended >= start
        ):
            stale.append(item["alarm_id"])
    stale = sorted(set(stale))

    priorities = Counter(
        "high" if item.get("priority") in ("critical", "high") else item.get("priority") or "medium"
        for _, item in raised
    )
    distribution = {
        key: round(100.0 * priorities.get(key, 0) / total, 1) if total else 0.0
        for key in priority_targets
    }

    ack_seconds = [
        (acked - moment).total_seconds()
        for moment, item in raised
        for acked in [_time(item.get("acked_at"))]
        if acked is not None and acked >= moment
    ]

    per_hour = total / hours
    per_ten = total / max(hours * 6.0, 1e-9)
    flood_share = 100.0 * flood_slots / slots
    peak = max(per_slot) if per_slot else 0
    figures = [
        {
            "id": "per_hour",
            "label": "Average alarms per hour",
            "help": "How many alarms an operator received each hour, on average. ISA-18.2 takes about 6 an hour as what one person can handle.",
            "value": round(per_hour, 2),
            "target": f"≤ {per_person:g} (≤ {2 * per_person:g} manageable)",
            "status": _status(per_hour, per_person, 2 * per_person),
        },
        {
            "id": "per_10min",
            "label": "Average alarms per 10 minutes",
            "help": "The same load counted in 10-minute periods, the time an operator has to react to each one.",
            "value": round(per_ten, 2),
            "target": f"≤ {per_person / 6:g} (≤ {per_person / 3:g} manageable)",
            "status": _status(per_ten, per_person / 6, per_person / 3),
        },
        {
            "id": "flood",
            "label": "Time in flood",
            "help": "The share of 10-minute periods with more alarms than an operator can answer (an alarm flood): too many to read, the important ones get lost.",
            "value": round(flood_share, 1),
            "unit": "%",
            "target": f"< 1 % of 10-minute periods with more than {flood_alarms} alarms",
            "status": _status(flood_share, 1, 5),
        },
        {
            "id": "peak",
            "label": "Peak alarms in 10 minutes",
            "help": "The most alarms raised in any one 10-minute period: the worst moment of the period.",
            "value": peak,
            "target": f"≤ {flood_alarms}",
            "status": _status(peak, flood_alarms, 2 * flood_alarms),
        },
        {
            "id": "top10",
            "label": "Load from the 10 most frequent alarms",
            "help": "The share of all alarms that come from the 10 raised most often. A high share means a few bad actors make most of the noise: fix those first.",
            "value": round(top_share, 1),
            "unit": "%",
            "target": "≤ 5 % (≤ 10 % manageable) on a large alarm system",
            "status": "ok" if total < 50 else _status(top_share, 5, 10),
        },
        {
            "id": "chattering",
            "label": "Chattering alarms",
            "help": "Alarms that raise and clear again and again within a minute, usually a limit too close to normal operation or a missing deadband.",
            "value": len(chattering),
            "target": f"none ({chatter_count} or more raises within a minute)",
            "status": "ok" if not chattering else "alarm",
        },
        {
            "id": "stale",
            "label": "Stale alarms",
            "help": "Alarms active for a long time without being solved. An alarm that stays on stops being read.",
            "value": len(stale),
            "target": f"fewer than 5 active for more than {stale_hours:g} hours",
            "status": _status(len(stale), 4, 9),
        },
    ]
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "total": total,
        "figures": figures,
        "per_slot": [
            {"at": (start + SLOT * index).isoformat(), "count": count}
            for index, count in enumerate(per_slot)
        ],
        "hourly": [
            {"at": (first_hour + HOUR * index).isoformat(), "counts": dict(counted)}
            for index, counted in enumerate(hourly)
        ],
        "top": [
            {
                "alarm_id": alarm_id,
                "name": names.get(alarm_id, alarm_id),
                "count": count,
                "priority": last_priority.get(alarm_id, "medium"),
                "share": round(100.0 * count / total, 1) if total else 0.0,
                "chattering": alarm_id in chattering,
            }
            for alarm_id, count in top
        ],
        "chattering": [{"alarm_id": a, "name": names.get(a, a)} for a in sorted(chattering)],
        "stale": [{"alarm_id": a, "name": names.get(a, a)} for a in stale],
        "priorities": [
            {"priority": key, "share": distribution[key], "target": target}
            for key, target in priority_targets.items()
        ],
        "mean_ack_seconds": round(sum(ack_seconds) / len(ack_seconds), 1) if ack_seconds else None,
        "unacked": sum(1 for _, item in raised if not item.get("acked_at")),
    }
