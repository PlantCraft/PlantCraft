"""Alarms' widgets: declared in ``app.toml`` (``[[contributes.widgets]]``), drawn on Alarms'
Overview and on Desk's Today alike (PlantCraft ``docs/widgets.md``). Links are paths on this
host, under Alarms' prefix."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from plantcraft_sdk import widgets as w

from alarmcraft.alarms.model import PRIORITIES
from alarmcraft.api.deps import CurrentUser, RuntimeDep
from alarmcraft.api.routers.operate import alarm_performance, summary_of
from alarmcraft.i18n import t
from alarmcraft.meta import FILES

router = APIRouter(prefix="/api/widgets", tags=["widgets"])

# The ISA-18.2 load over a day: 6 alarms per hour is acceptable, 12 manageable (engine/performance.py).
DAY_ACCEPTABLE, DAY_MANAGEABLE = 6 * 24, 12 * 24
# Unacknowledged or high priority reads as an alarm on the Overview; the rest as a warning.
URGENT = {"critical", "high"}
# Each priority's colour: the suite's tones for critical, high and medium; low as quiet.
PRIORITY_STATE = {"critical": "critical", "high": "high", "medium": "medium", "low": "unknown"}
# Which figures of the Performance page fit the card, in this order: the ISA-18.2 indicators
# first (rate, flood, chattering, stale), then what a larger card has room for.
FIGURES = ("per_hour", "flood", "chattering", "stale", "top10", "peak", "per_10min")


@router.get("")
def widgets(_user: CurrentUser) -> dict[str, Any]:
    return w.catalog(FILES.manifest(), t)


def _state(row: dict[str, Any]) -> str | None:
    if row["status"] in ("unacked", "rtn_unacked") or row.get("priority") in URGENT:
        return "alarm" if row["status"] != "shelved" else "warning"
    return "warning" if row["status"] == "acked" else None


@router.get("/{widget_id}")
def widget(widget_id: str, rt: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    root = rt.settings.root_path
    if widget_id in {"rate", "performance", "bad-actors"}:
        return _performance(rt, user, root, widget_id)
    if widget_id not in {"active", "summary", "raised", "priorities"}:
        raise HTTPException(404, t("Widget not found."))
    data = summary_of(rt, user, dashboards=True)
    counts = data["counts"]
    if widget_id == "active":
        waiting = counts["unacked"] + counts["rtn_unacked"]
        return w.number(
            counts["active"],
            label=t("{n} to acknowledge", n=waiting) if waiting else t("All acknowledged"),
            state="alarm" if waiting else "warning" if counts["active"] else "ok",
            href=f"{root}/alarms",
        )
    if widget_id == "raised":
        return w.number(
            counts["last_24h"],
            label=t("Target: {n} or fewer (6 per hour)", n=DAY_ACCEPTABLE),
            state="ok"
            if counts["last_24h"] <= DAY_ACCEPTABLE
            else "warning"
            if counts["last_24h"] <= DAY_MANAGEABLE
            else "alarm",
            href=f"{root}/performance",
        )
    if widget_id == "priorities":
        rows = [
            row for row in data["alarms"] if row["status"] in ("unacked", "acked", "rtn_unacked")
        ]
        return w.split(
            [
                w.part(
                    t(label),
                    sum(1 for row in rows if row.get("priority") == key),
                    PRIORITY_STATE[key],
                    f"{root}/alarms",
                )
                for key, label in PRIORITIES.items()
            ],
            label=t("alarms that need action"),
            href=f"{root}/alarms",
            empty=t("No alarm needs action."),
        )
    return w.items(
        [
            w.item(
                row.get("name") or row["alarm_id"],
                detail=f"{t(row['priority_label'])} · {row['condition']}".strip(" ·"),
                state=_state(row),
                href=f"{root}/alarms/{quote(row['alarm_id'], safe='')}",
            )
            for row in data["alarms"][:8]
        ],
        href=f"{root}/alarms",
        empty=t("No alarm needs action."),
    )


def _performance(rt: Any, user: Any, root: str, widget_id: str) -> dict[str, Any]:
    if widget_id == "bad-actors":
        found = alarm_performance(rt, user, "7d")
        return w.bars(
            [
                w.bar(
                    row["name"],
                    row["count"],
                    detail=t("{share} % of the load", share=f"{row['share']:g}")
                    + (f" · {t('Chattering')}" if row["chattering"] else ""),
                    state=PRIORITY_STATE.get(row.get("priority") or "medium", "unknown"),
                    href=f"{root}/alarms/{quote(row['alarm_id'], safe='')}",
                )
                for row in found["top"]
            ],
            href=f"{root}/performance",
            empty=t("No alarm raised in the last 7 days."),
        )
    found = alarm_performance(rt, user, "24h")
    figures = {row["id"]: row for row in found["figures"]}
    if widget_id == "performance":
        # Each indicator in its own colour against its target, the ones out of target first
        # (a small card shows four), and the line above names them.
        shown = sorted(
            (figures[key] for key in FIGURES if key in figures),
            key=lambda row: {"alarm": 0, "warning": 1}.get(row["status"], 2),
        )
        out = [row for row in shown if row["status"] != "ok"]
        worst = (
            "alarm" if any(row["status"] == "alarm" for row in out) else "warning" if out else "ok"
        )
        return w.facts(
            t("Last 24 hours"),
            [
                w.fact(
                    t(row["label"]),
                    f"{row['value']:g}{row.get('unit') or ''}",
                    row["status"],
                    detail=t(row["help"]) + " " + t("Target: {target}", target=row["target"]),
                )
                for row in shown
            ],
            status=t("Out of target: {figures}", figures=", ".join(t(row["label"]) for row in out))
            if out
            else t("Within the ISA-18.2 targets"),
            state=worst,
            href=f"{root}/performance",
        )
    # Raised per hour, stacked by priority (the highest at the bottom, in the colours of the
    # split by priority); the dashed line is the philosophy's target for one operator.
    target = rt.philosophy.get().per_person_hour
    total = found["total"]
    buckets = [
        (
            datetime.fromisoformat(hour["at"]).timestamp() * 1000,
            [hour["counts"].get(key, 0) for key in PRIORITIES],
        )
        for hour in found["hourly"]
    ]
    return w.columns(
        buckets if total else [],
        stacks=[w.stack(t(label), PRIORITY_STATE[key]) for key, label in PRIORITIES.items()],
        step="hour",
        value=total,
        label=t("raised in 24 h"),
        state=figures["per_hour"]["status"] if "per_hour" in figures else None,
        target=target,
        target_label=t("Target {n} an hour", n=f"{target:g}"),
        href=f"{root}/performance",
        empty=t("No alarm raised in the last 24 hours."),
    )
