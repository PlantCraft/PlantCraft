"""A report section on alarm performance (ISA-18.2, EEMUA 191) for one part of the plant.

Alarms publishes, once an hour, the performance of the site and of each area as a result
(``alarmcraft.alarm_performance``: the Performance page's reading over the last 24 hours,
7 days and 30 days). The section reads that result for the asset it names, picks the reading
closest to the report's period, and lays it out as plain tables every file format draws the
same way (the PDF, Word, HTML and Markdown): the figures against their targets, the EEMUA 191
level, the floods, the time to acknowledge by priority, the most frequent alarms and the
fleeting ones. View never calls Alarms: when Alarms is not installed, or has not published yet,
the section says so.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from plantcraft_sdk.client import PlantCraftError, Unauthorized

from dashcraft.dashboards.model import window_seconds
from dashcraft.i18n import t

RESULT = "alarmcraft.alarm_performance"
PERIODS = (("24h", timedelta(days=1)), ("7d", timedelta(days=7)), ("30d", timedelta(days=30)))
PERIOD_WORDS = {"24h": "the last 24 hours", "7d": "the last 7 days", "30d": "the last 30 days"}
LEVEL_WORDS = {
    "robust": "Robust",
    "stable": "Stable",
    "reactive": "Reactive",
    "overloaded": "Overloaded",
}
LEVEL_STATE = {"robust": "ok", "stable": "ok", "reactive": "warning", "overloaded": "alarm"}
PRIORITY_WORDS = {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low"}
PRIORITY_STATE = {"critical": "alarm", "high": "alarm", "medium": "warning", "low": ""}
STATUS_WORDS = {"ok": "Acceptable", "warning": "Manageable", "alarm": "Over target"}


def period_key(period: str) -> str:
    """The reading closest to the report's period: the shortest that covers it, else 30 days."""

    seconds = window_seconds(period)
    for key, span in PERIODS:
        if seconds <= span.total_seconds():
            return key
    return PERIODS[-1][0]


def read(reader: Any, asset_id: str, period: str) -> dict[str, Any]:
    """What the section shows: the asset, the reading for the report's period, or ``problem``."""

    key = period_key(period)
    out: dict[str, Any] = {
        "kind": "alarms",
        "asset_id": asset_id,
        "asset_name": asset_id,
        "period": key,
        "exact": window_seconds(period) == dict(PERIODS)[key].total_seconds(),
        "reading": None,
        "at": None,
        "problem": "",
    }
    try:
        asset = reader.asset(asset_id)
        out["asset_name"] = str(asset.get("name") or asset_id)
    except Unauthorized:
        raise
    except PlantCraftError:
        pass
    found = reader.result(f"asset:{asset_id}", RESULT)
    if found is None:
        out["problem"] = t(
            "Alarms has published no alarm performance for {asset} (not installed, no alarm "
            "under it, or not run for an hour yet).",
            asset=out["asset_name"],
        )
        return out
    periods = (found.get("detail") or {}).get("periods") or {}
    reading = periods.get(key)
    if not isinstance(reading, dict):
        out["problem"] = t("Alarms' result has no reading for {period}.", period=key)
        return out
    out["reading"] = reading
    out["at"] = found.get("at")
    if found.get("stale"):
        out["problem"] = t("Alarms' figures are older than two hours: Alarms may be stopped.")
    return out


def duration(seconds: float | None) -> str:
    if seconds is None:
        return "–"
    if seconds < 90:
        return f"{seconds:.0f} s"
    if seconds < 90 * 60:
        return f"{seconds / 60:.0f} min"
    return f"{seconds / 3600:.1f} h"


def _number(value: Any, unit: str = "") -> str:
    if isinstance(value, float):
        text = f"{value:g}"
    else:
        text = str(value if value is not None else "–")
    return f"{text}{unit}"


def lead(data: dict[str, Any]) -> str:
    """One line: the EEMUA 191 level and the load, for the top of the section."""

    reading = data.get("reading") or {}
    if not reading:
        return ""
    eemua = reading.get("eemua") or {}
    level = str(eemua.get("level") or "")
    floods = int(reading.get("flood_count") or len(reading.get("floods") or []))
    words = t(
        "{asset}, {period}: EEMUA 191 level {level} (average {average} and peak {peak} alarms per "
        "10 minutes). Alarms raised: {total}. Floods: {floods} ({minutes} min).",
        asset=data.get("asset_name") or data.get("asset_id"),
        period=t(PERIOD_WORDS.get(data.get("period") or "", data.get("period") or "")),
        level=t(LEVEL_WORDS.get(level, level)),
        average=_number(eemua.get("average_per_10min")),
        peak=_number(eemua.get("peak_per_10min")),
        total=reading.get("total", 0),
        floods=floods,
        minutes=reading.get("flood_minutes", 0),
    )
    if not data.get("exact"):
        words += " " + t("Alarms publishes 24 hours, 7 days and 30 days; this is the closest.")
    return words


def level_state(data: dict[str, Any]) -> str:
    level = ((data.get("reading") or {}).get("eemua") or {}).get("level") or ""
    return LEVEL_STATE.get(str(level), "")


def tables(data: dict[str, Any], clock: Any) -> list[dict[str, Any]]:
    """The section as plain tables: ``title``, ``head``, ``rows``, ``align``, ``states``,
    ``empty`` (said when there are no rows) and ``note``."""

    reading = data.get("reading") or {}
    if not reading:
        return []
    figures = reading.get("figures") or []
    out = [
        {
            "title": t("Figures against the targets"),
            "head": [t("Figure"), t("Value"), t("Target"), t("Status")],
            "rows": [
                [
                    t(str(f.get("label") or f.get("id"))),
                    _number(f.get("value"), str(f.get("unit") or "")),
                    str(f.get("target") or ""),
                    t(STATUS_WORDS.get(str(f.get("status")), str(f.get("status") or ""))),
                ]
                for f in figures
            ],
            "align": ["left", "right", "left", "left"],
            "states": [s if (s := str(f.get("status") or "")) != "ok" else "" for f in figures],
            "empty": "",
            "note": "",
        }
    ]
    top = reading.get("top") or []
    out.append(
        {
            "title": t("Most frequent alarms"),
            "head": ["#", t("Alarm"), t("Priority"), t("Raised"), t("Share")],
            "rows": [
                [
                    str(index),
                    str(row.get("name") or row.get("alarm_id"))
                    + (f" ({t('chattering')})" if row.get("chattering") else ""),
                    t(PRIORITY_WORDS.get(str(row.get("priority")), str(row.get("priority") or ""))),
                    str(row.get("count", 0)),
                    f"{row.get('share', 0)}%",
                ]
                for index, row in enumerate(top, start=1)
            ],
            "align": ["right", "left", "left", "right", "right"],
            "states": [PRIORITY_STATE.get(str(row.get("priority")), "") for row in top],
            "empty": t("No alarm was raised in the period."),
            "note": "",
        }
    )
    floods = reading.get("floods") or []
    count = int(reading.get("flood_count") or len(floods))
    out.append(
        {
            "title": t("Floods"),
            "head": [t("Start"), t("End"), t("Minutes"), t("Alarms"), t("Peak in 10 min")],
            "rows": [
                [
                    clock.text(flood.get("start"), "%d %b %H:%M"),
                    clock.text(flood.get("end"), "%d %b %H:%M"),
                    str(flood.get("minutes", 0)),
                    str(flood.get("alarms", 0)),
                    str(flood.get("peak", 0)),
                ]
                for flood in floods
            ],
            "align": ["left", "left", "right", "right", "right"],
            "states": ["alarm"] * len(floods),
            "empty": t("No flood in the period."),
            "note": t(
                "A flood starts above the flood limit in 10 minutes and ends below half of it."
            )
            + (
                " " + t("The {n} latest of {total} are listed.", n=len(floods), total=count)
                if count > len(floods)
                else ""
            ),
        }
    )
    ack = reading.get("acknowledge") or []
    out.append(
        {
            "title": t("Time to acknowledge"),
            "head": [t("Priority"), t("Acknowledged"), t("Half within"), t("9 in 10 within")],
            "rows": [
                [
                    t(PRIORITY_WORDS.get(str(row.get("priority")), str(row.get("priority") or ""))),
                    str(row.get("count", 0)),
                    duration(row.get("median_seconds")),
                    duration(row.get("p90_seconds")),
                ]
                for row in ack
            ],
            "align": ["left", "right", "right", "right"],
            "states": [PRIORITY_STATE.get(str(row.get("priority")), "") for row in ack],
            "empty": t("No alarm was acknowledged in the period."),
            "note": t("{n} alarms of the period are not acknowledged yet.", n=reading["unacked"])
            if reading.get("unacked")
            else "",
        }
    )
    fleeting = reading.get("fleeting") or []
    out.append(
        {
            "title": t("Fleeting alarms"),
            "head": [t("Alarm"), t("Times")],
            "rows": [
                [str(row.get("name") or row.get("alarm_id")), str(row.get("count", 0))]
                for row in fleeting
            ],
            "align": ["left", "right"],
            "states": ["warning"] * len(fleeting),
            "empty": t("None: every alarm stayed long enough to be read."),
            "note": t(
                "Back to normal within 10 seconds with nobody acting: a delay or a deadband "
                "removes them."
            ),
        }
    )
    return out
