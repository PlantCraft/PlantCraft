"""When a report is made: the next send after an instant, in the installation's time zone.

Times are kept in UTC and laid out on the plant's wall clock (``PLANTCRAFT_TIMEZONE``), so a
report every day at 06:00 stays at 06:00 across a change of summer time. A wall-clock time that
does not exist that day (the hour skipped in spring) is taken at the same offset as the hour
before, as ``zoneinfo`` does.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dashcraft.i18n import t
from dashcraft.reports.model import WEEKDAYS, EventTrigger, Schedule

WEEKDAY_NAMES = {
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
    "sun": "Sunday",
}


# Every other week counts weeks from a fixed Monday, so the same weeks are on in every installation
# and across a change of year (ISO week numbers would skip at a 53-week year).
FORTNIGHT_ANCHOR = date(2024, 1, 1)


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
        elif (
            schedule.every == "fortnight"
            and WEEKDAYS[day.weekday()] == schedule.weekday
            and (day - FORTNIGHT_ANCHOR).days // 7 % 2 == 0
        ):
            yield day
        elif schedule.every == "month" and day.day == schedule.day:
            yield day
        elif schedule.every == "quarter" and day.month in (1, 4, 7, 10) and day.day == schedule.day:
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


def closed_period(
    schedule: Schedule, now: datetime, zone_name: str | None
) -> tuple[datetime, datetime] | None:
    """The last whole calendar period of the cadence before ``now`` (UTC), on the plant's wall
    clock: yesterday, last Monday to Sunday, the two weeks before this Monday, last month or last
    quarter. None when the report reads its own period (``closed`` off, or not scheduled)."""

    if not schedule.closed or not schedule.on:
        return None
    where = zone(zone_name)
    today = now.astimezone(where).date()
    if schedule.every == "day":
        end = today
        start = end - timedelta(days=1)
    elif schedule.every in ("week", "fortnight"):
        end = today - timedelta(days=today.weekday())
        start = end - timedelta(days=7 if schedule.every == "week" else 14)
    elif schedule.every == "month":
        end = today.replace(day=1)
        start = (end - timedelta(days=1)).replace(day=1)
    else:  # quarter
        end = date(today.year, (today.month - 1) // 3 * 3 + 1, 1)
        before = end - timedelta(days=1)
        start = date(before.year, (before.month - 1) // 3 * 3 + 1, 1)

    def instant(day: date) -> datetime:
        return datetime.combine(day, time(0), tzinfo=where).astimezone(UTC)

    return instant(start), instant(end)


MAX_EVENT_DAYS = 31
# Reports one tick makes for one report's events (a burst after a long stop waits a tick).
MAX_EVENT_RUNS = 5


def _at(event: dict[str, Any]) -> datetime | None:
    try:
        at = datetime.fromisoformat(str(event.get("at") or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def _payload_start(event: dict[str, Any]) -> datetime | None:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    for key in ("start", "started_at"):
        if payload.get(key):
            found = _at({"at": payload[key]})
            if found is not None:
                return found
    return None


def event_periods(
    trigger: EventTrigger,
    ends: list[dict[str, Any]],
    starts: list[dict[str, Any]],
    since: datetime,
    fallback_seconds: int,
    limit: int = MAX_EVENT_RUNS,
) -> list[tuple[datetime, datetime, dict[str, Any]]]:
    """The periods new end events close, oldest first: ``(start, end, end event)`` for each
    event of ``trigger.end_kind`` after ``since`` (about ``trigger.subject`` when set). The start
    is the newest start event about the same subject before the end (and after the end before
    it), else the end event's payload ``start``, else ``fallback_seconds`` before the end; never
    more than ``MAX_EVENT_DAYS`` before it."""

    def wanted(event: dict[str, Any]) -> bool:
        return not trigger.subject or str(event.get("subject") or "") == trigger.subject

    timed_ends = sorted(
        ((at, e) for e in ends if wanted(e) and (at := _at(e)) is not None),
        key=lambda pair: pair[0],
    )
    timed_starts = [(at, s) for s in starts if wanted(s) and (at := _at(s)) is not None]
    previous_end: dict[str, datetime] = {}
    found: list[tuple[datetime, datetime, dict[str, Any]]] = []
    for end, event in timed_ends:
        subject = str(event.get("subject") or "")
        floor = previous_end.get(subject)
        previous_end[subject] = end
        # Run stamps keep milliseconds: an end within one of the last look is the one made.
        if end < since + timedelta(milliseconds=1):
            continue
        candidates = [
            at
            for at, s in timed_starts
            if str(s.get("subject") or "") == subject
            and at < end
            and (floor is None or at >= floor)
        ]
        start = max(candidates) if candidates else _payload_start(event)
        if start is None or start >= end:
            start = end - timedelta(seconds=fallback_seconds)
        start = max(start, end - timedelta(days=MAX_EVENT_DAYS))
        found.append((start, end, event))
        if len(found) >= limit:
            break
    return found


def cadence(schedule: Schedule) -> str:
    """In people's words: "Every day at 06:00", "Every Monday at 07:00", "Off"."""

    timed = _timed(schedule)
    if schedule.on_event is None:
        return timed
    when = t("When {kind} happens", kind=schedule.on_event.end_kind)
    return when if not schedule.on else t("{timed}; and {when}", timed=timed, when=when.lower())


def _timed(schedule: Schedule) -> str:
    if schedule.every == "day":
        return t("Every day at {at}", at=schedule.at)
    if schedule.every == "week":
        return t(
            "Every {weekday} at {at}", weekday=t(WEEKDAY_NAMES[schedule.weekday]), at=schedule.at
        )
    if schedule.every == "fortnight":
        return t(
            "Every other {weekday} at {at}",
            weekday=t(WEEKDAY_NAMES[schedule.weekday]),
            at=schedule.at,
        )
    if schedule.every == "month":
        return t("Every month on day {day} at {at}", day=schedule.day, at=schedule.at)
    if schedule.every == "quarter":
        return t("Every quarter on day {day} at {at}", day=schedule.day, at=schedule.at)
    return t("Not scheduled")
