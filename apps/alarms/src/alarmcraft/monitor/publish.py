"""What the monitor sends to PlantCraft, built as plain data (tested apart).

- **Results** (app standard, section 6): ``alarm_state`` per subject (the alarm's asset, else
  its signal): ``alarm`` while a critical or high priority alarm is active, ``warning`` while
  a medium or low one is, ``ok`` otherwise, ``unknown`` when none of its alarms could be judged.
  They expire after 15 minutes, so a stopped Alarms leaves no green light behind. A rule with
  its Dashboards output off sends none.
- **Events** ``alarmcraft.alarm.raised`` and ``alarmcraft.alarm.cleared``, one per transition.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from plantcraft_sdk.refs import format_ref

from alarmcraft import APP_ID
from alarmcraft.alarms.model import PRIORITIES, AlarmDraft
from alarmcraft.i18n import t

RESULT_KIND = "alarm_state"
RESULT_MINUTES = 15
WORST = ["ok", "unknown", "warning", "alarm"]


def _clip(text: str, limit: int = 300) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def subject_of(alarm: AlarmDraft, signal_id: str | None) -> str | None:
    if alarm.subject_asset:
        return format_ref("asset", alarm.subject_asset)
    return format_ref("signal", signal_id) if signal_id else None


def shown(value: float | None, unit: str = "") -> str:
    if value is None:
        return ""
    return f"{value:.4g}" + (f" {unit}" if unit else "")


def reading(alarm: AlarmDraft, value: float | None, unit: str = "") -> str:
    """ "42 /100 (Health < 50 for 5 values in a row)" (a notification's line)."""

    if value is None:
        return alarm.condition()
    return t("{value} ({condition})", value=shown(value, unit), condition=alarm.condition())


def describe(alarm: AlarmDraft, value: float | None, unit: str = "", message: str = "") -> str:
    """ "Valve health · FIC-101: 42 /100 (Health < 50 for 5 values in a row)"."""

    words = message or reading(alarm, value, unit)
    return t("{name}: {reading}", name=alarm.name, reading=words)


def results(entries: list[dict[str, Any]], *, now: datetime, url: str) -> list[dict[str, Any]]:
    """One ``alarm_state`` per subject. ``entries``: ``{alarm, signal, status, value, known}``."""

    expires = (now + timedelta(minutes=RESULT_MINUTES)).isoformat()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        if not entry["alarm"].dashboards:
            continue
        subject = subject_of(entry["alarm"], entry.get("signal"))
        if subject:
            grouped.setdefault(subject, []).append(entry)
    rows = []
    for subject, items in sorted(grouped.items()):
        active = [item for item in items if item["status"] in ("unacked", "acked")]
        judged = [item for item in items if item.get("known")]
        if any(
            item["alarm"].priority in ("critical", "high") and item["alarm"].creates == "alarm"
            for item in active
        ):
            status = "alarm"
        elif active:
            status = "warning"
        elif judged:
            status = "ok"
        else:
            status = "unknown"
        active.sort(key=lambda item: list(PRIORITIES).index(item["alarm"].priority))
        if active:
            summary = t("{count} active: ", count=len(active)) + "; ".join(
                describe(item["alarm"], item.get("value"), item.get("unit") or "")
                for item in active[:3]
            )
        elif status == "ok":
            summary = t("No active alarm ({count} configured).", count=len(items))
        else:
            summary = t("Its alarms could not be judged: no data from PlantCraft.")
        rows.append(
            {
                "subject": subject,
                "kind": RESULT_KIND,
                "status": status,
                "score": None,
                "usable": None,
                "value": float(len(active)),
                "summary": _clip(summary),
                "detail": {
                    "active": [
                        {
                            "alarm": item["alarm_id"],
                            "name": item["alarm"].name,
                            "priority": item["alarm"].priority,
                            "acked": item["status"] == "acked",
                        }
                        for item in active[:20]
                    ],
                    "configured": len(items),
                    "url": url,
                },
                "at": now.isoformat(),
                "expires_at": expires,
            }
        )
    return rows


# A transition -> the event app.toml declares for it ([[publishes.events]]).
ALARM_EVENTS = {"raised": "alarm.raised", "cleared": "alarm.cleared"}
# An alarm's priority -> its event's severity.
EVENT_SEVERITY = {"critical": "critical", "high": "critical", "medium": "warning", "low": "warning"}


def event(
    alarm_id: str,
    alarm: AlarmDraft,
    signal_id: str | None,
    kind: str,
    at: datetime,
    value: Any,
    unit: str = "",
) -> dict[str, Any] | None:
    """``alarmcraft.alarm.raised`` or ``.cleared`` for one transition (None without a subject)."""

    subject = subject_of(alarm, signal_id) or f"app:{APP_ID}"
    refs = [format_ref("signal", signal_id)] if signal_id and alarm.subject_asset else []
    words = describe(alarm, value, unit)
    summary = (
        t("{priority} alarm: {words}", priority=t(PRIORITIES[alarm.priority]), words=words)
        if kind == "raised"
        else t("Cleared: {words}", words=words)
    )
    return {
        "kind": f"{APP_ID}.{ALARM_EVENTS[kind]}",
        "subject": subject,
        "summary": _clip(summary),
        "refs": refs,
        # One alarm is one condition: raised starts it, cleared ends it (app.toml).
        "severity": EVENT_SEVERITY.get(alarm.priority, "warning") if kind == "raised" else "ok",
        "phase": "start" if kind == "raised" else "end",
        "key": f"alarm:{alarm_id}"[:200],
        "payload": {
            "alarm": alarm_id,
            "rule": alarm.rule_id,
            "priority": alarm.priority,
            "condition": alarm.condition()[:300],
            "value": value,
            "at": at.isoformat(),
        },
    }
