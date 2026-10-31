"""Uptime by app, and maintenance windows that silence the watch (docs/operations.md, section 4).

**Uptime** is read from the watch's own incidents: a ``service:<name>`` incident is the time that
service was down, not starting, unhealthy or restarting. Over a window (24 h, 7 days, 30 days) a
service's uptime is the share of the watched time it had no such incident open, where the watched
time starts when the watch first ran and leaves out the **planned** time of maintenance windows
(the industry's convention: a planned stop is not an outage). Load incidents are not downtime.

A **maintenance window** is an administrator's plan: from when to when, for every app or a few,
and why. While one is in force the watch keeps quiet about the apps it covers (no incident opens,
nobody is told), as it already does during its own backups and updates. Windows are kept, so the
uptime can leave them out later; one can be ended early.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from plantcraft.i18n import t
from plantcraft_sdk.utc import parse_instant

WINDOWS = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}
MAX_WINDOW_HOURS = 72
SERVICE = "service:"

SCHEMA = """
CREATE TABLE IF NOT EXISTS watch_maintenance (
    window_id INTEGER PRIMARY KEY AUTOINCREMENT,
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    -- JSON list of service names; NULL: every app.
    services TEXT,
    reason TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    ended_by TEXT,
    ended_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_watch_maintenance_end ON watch_maintenance(ends_at);
"""


def check_window(starts: datetime, ends: datetime, reason: str, now: datetime) -> str:
    """The reason, cleaned; ``ValueError`` when the window makes no sense."""

    cleaned = (reason or "").strip()[:300]
    if not cleaned:
        raise ValueError(t("Say what the maintenance is for."))
    if ends <= starts:
        raise ValueError(t("The window ends after it starts."))
    if ends <= now:
        raise ValueError(t("The window has already ended."))
    if ends - starts > timedelta(hours=MAX_WINDOW_HOURS):
        raise ValueError(t("A window lasts up to {count} hours.", count=MAX_WINDOW_HOURS))
    return cleaned


def covers(window: dict[str, Any], key: str) -> bool:
    """Whether a maintenance window silences the check ``key`` (an app's check: ``service:``,
    ``load:``, ``queue:``... followed by the service's name)."""

    services = window.get("services")
    if services is None:
        return True
    return key.split(":", 1)[-1] in services


def _overlap(start: datetime, end: datetime, first: datetime, last: datetime) -> float:
    begin, stop = max(start, first), min(end, last)
    return max(0.0, (stop - begin).total_seconds())


def _union(spans: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _minus(
    spans: list[tuple[datetime, datetime]], holes: list[tuple[datetime, datetime]]
) -> list[tuple[datetime, datetime]]:
    """``spans`` without the parts inside ``holes`` (both sorted and merged)."""

    found: list[tuple[datetime, datetime]] = []
    for start, end in spans:
        cursor = start
        for hole_start, hole_end in holes:
            if hole_end <= cursor or hole_start >= end:
                continue
            if hole_start > cursor:
                found.append((cursor, hole_start))
            cursor = max(cursor, hole_end)
        if cursor < end:
            found.append((cursor, end))
    return found


def uptime(
    services: list[str],
    incidents: list[dict[str, Any]],
    windows: list[dict[str, Any]],
    *,
    now: datetime,
    first_seen: datetime | None,
) -> list[dict[str, Any]]:
    """Each service's uptime (percent, two decimals) over ``WINDOWS``, its downtime and outages,
    from ``service:`` incidents, leaving out planned maintenance. None where nothing was watched."""

    names = sorted(
        set(services)
        | {
            item["check_key"][len(SERVICE) :]
            for item in incidents
            if item["check_key"].startswith(SERVICE)
        }
    )
    found = []
    for name in names:
        key = f"{SERVICE}{name}"
        down = _union(
            [
                (parse_instant(item["opened_at"]), parse_instant(item["closed_at"]) or now)
                for item in incidents
                if item["check_key"] == key and parse_instant(item["opened_at"])
            ]
        )
        planned = _union(
            [
                (
                    parse_instant(item["starts_at"]),
                    parse_instant(item["ended_at"] or item["ends_at"]),
                )
                for item in windows
                if covers(item, key)
            ]
        )
        outages = _minus(down, planned)
        row: dict[str, Any] = {"service": name, "uptime": {}, "down_seconds": {}, "outages": {}}
        for label, length in WINDOWS.items():
            first = max(now - length, first_seen) if first_seen else now - length
            watched = (now - first).total_seconds() - sum(
                _overlap(start, end, first, now) for start, end in planned
            )
            lost = sum(_overlap(start, end, first, now) for start, end in outages)
            row["down_seconds"][label] = round(lost)
            row["outages"][label] = sum(1 for start, end in outages if end > first)
            row["uptime"][label] = (
                round(100 * max(0.0, watched - lost) / watched, 2) if watched > 0 else None
            )
        found.append(row)
    return found
