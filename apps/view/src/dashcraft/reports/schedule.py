"""When a report is made: the next send after an instant, in the installation's time zone.

Times are kept in UTC and laid out on the plant's wall clock (``PLANTCRAFT_TIMEZONE``), so a
report every day at 06:00 stays at 06:00 across a change of summer time. A wall-clock time that
does not exist that day (the hour skipped in spring) is taken at the same offset as the hour
before, as ``zoneinfo`` does.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dashcraft.i18n import t
from dashcraft.reports.model import WEEKDAYS, Schedule

WEEKDAY_NAMES = {
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
    "sun": "Sunday",
}


def zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _clock(schedule: Schedule) -> time:
    hours, minutes = schedule.at.split(":")
    return time(int(hours), int(minutes))


def _days_from(schedule: Schedule, first: date) -> Iterator[date]:
    """The days the schedule makes a report, from ``first`` on."""

    day = first
    while True:
        if schedule.every == "day":
            yield day
        elif schedule.every == "week" and WEEKDAYS[day.weekday()] == schedule.weekday:
            yield day
        elif schedule.every == "month" and day.day == schedule.day:
            yield day
        day += timedelta(days=1)


def next_run(schedule: Schedule, after: datetime, zone_name: str | None) -> datetime | None:
    """The first send strictly after ``after`` (UTC), or None when the schedule is off."""

    if not schedule.on:
        return None
    where = zone(zone_name)
    local = after.astimezone(where)
    for day in _days_from(schedule, local.date()):
        at = datetime.combine(day, _clock(schedule), tzinfo=where).astimezone(UTC)
        if at > after:
            return at
    return None  # pragma: no cover - the generator never ends


def runs_between(
    schedule: Schedule, start: datetime, end: datetime, zone_name: str | None, limit: int = 100
) -> list[datetime]:
    """Every send in ``(start, end]`` (UTC), at most ``limit``."""

    found: list[datetime] = []
    at = next_run(schedule, start, zone_name)
    while at is not None and at <= end and len(found) < limit:
        found.append(at)
        at = next_run(schedule, at, zone_name)
    return found


def cadence(schedule: Schedule) -> str:
    """In people's words: "Every day at 06:00", "Every Monday at 07:00", "Off"."""

    if schedule.every == "day":
        return t("Every day at {at}", at=schedule.at)
    if schedule.every == "week":
        return t(
            "Every {weekday} at {at}", weekday=t(WEEKDAY_NAMES[schedule.weekday]), at=schedule.at
        )
    if schedule.every == "month":
        return t("Every month on day {day} at {at}", day=schedule.day, at=schedule.at)
    return t("Not scheduled")
