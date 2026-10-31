"""Service targets of requests (Operations › Requests, docs/operations.md section 4).

Each priority has two targets, in calendar hours (a plant runs day and night):

- **first answer**: from the request to the first thing someone other than who asked did on it
  (``first_response_at``);
- **resolution**: from the request to Done, without the time it spent Blocked. A request is
  Blocked while it waits for the person who asked or a third party (a supplier, a shutdown), and
  that time is not the queue's.

A queue may have **service hours** (``ServiceHours``: the days of the week and the hours of the
day its people work, on the plant's clock); its requests' clocks then run only inside them. A
request without a queue follows the default calendar, and with none the clock runs day and night.

An archived request has no targets. The targets apply when they are read, so a change of target
moves the clock of the open requests too (the closed ones keep their verdict as computed then).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any

from plantcraft.db import utc_text
from plantcraft.i18n import t

# (first answer, resolution) in hours, by priority: common service-desk values.
DEFAULT_TARGETS: dict[str, tuple[float, float]] = {
    "critical": (1, 8),
    "high": (4, 24),
    "medium": (8, 72),
    "low": (24, 168),
}
MAX_TARGET_HOURS = 24 * 90
# Shown "at risk" from this share of the target on.
AT_RISK = 0.75
PAUSED = "blocked"
CLOSED = ("done", "cancelled")


@dataclass(frozen=True)
class Targets:
    """Minutes per priority: {"high": (240, 1440), ...}."""

    minutes: dict[str, tuple[int, int]]

    @classmethod
    def defaults(cls) -> Targets:
        return cls({key: (round(a * 60), round(b * 60)) for key, (a, b) in DEFAULT_TARGETS.items()})

    def as_dict(self) -> dict[str, Any]:
        return {
            priority: {"response_hours": first / 60, "resolution_hours": second / 60}
            for priority, (first, second) in self.minutes.items()
        }


def check_targets(payload: dict[str, Any]) -> Targets:
    """``{"high": {"response_hours": 4, "resolution_hours": 24}, ...}``; every priority given.
    ``ValueError`` when a target is missing, not positive, too long, or the resolution comes
    before the first answer."""

    found: dict[str, tuple[int, int]] = {}
    for priority in DEFAULT_TARGETS:
        item = payload.get(priority)
        if not isinstance(item, dict):
            raise ValueError(t("Give both targets of every priority."))
        try:
            first = float(item.get("response_hours"))
            second = float(item.get("resolution_hours"))
        except (TypeError, ValueError) as exc:
            raise ValueError(t("A target is a number of hours.")) from exc
        if not (0 < first <= MAX_TARGET_HOURS and 0 < second <= MAX_TARGET_HOURS):
            raise ValueError(
                t("A target is between a minute and {count} days.", count=MAX_TARGET_HOURS // 24)
            )
        if second < first:
            raise ValueError(t("The resolution target cannot be before the first answer's."))
        found[priority] = (max(1, round(first * 60)), max(1, round(second * 60)))
    return Targets(found)


def _when(text: str | None) -> datetime | None:
    if not text:
        return None
    moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _minutes(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds() / 60)


DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@dataclass(frozen=True)
class ServiceHours:
    """When a queue works: ``days`` (0 Monday .. 6 Sunday) from ``start`` to ``end`` (minutes
    after midnight on the plant's clock, ``end`` after ``start``). Holidays are not modelled."""

    days: frozenset[int]
    start: int
    end: int

    @classmethod
    def check(cls, payload: dict[str, Any]) -> ServiceHours:
        """``{"days": ["mon", ...], "start": "08:00", "end": "17:00"}``; ``ValueError`` if bad."""

        days = payload.get("days")
        if not isinstance(days, list) or not days or any(day not in DAY_NAMES for day in days):
            raise ValueError(t("Choose the days of the week the queue works."))
        start, end = str(payload.get("start") or ""), str(payload.get("end") or "")
        if not HHMM.match(start) or not HHMM.match(end):
            raise ValueError(t("Hours are written as 08:00."))
        first = int(start[:2]) * 60 + int(start[3:])
        last = int(end[:2]) * 60 + int(end[3:])
        if last <= first:
            raise ValueError(t("The end of the day comes after its start."))
        return cls(frozenset(DAY_NAMES.index(day) for day in days), first, last)

    def as_dict(self) -> dict[str, Any]:
        return {
            "days": [DAY_NAMES[day] for day in sorted(self.days)],
            "start": f"{self.start // 60:02d}:{self.start % 60:02d}",
            "end": f"{self.end // 60:02d}:{self.end % 60:02d}",
        }

    def _windows(self, first: datetime, last: datetime, zone: Any):
        """The working spans (UTC) of every local day from ``first`` to ``last``."""

        day = first.astimezone(zone).date() - timedelta(days=1)
        stop = last.astimezone(zone).date() + timedelta(days=1)
        while day <= stop:
            if day.weekday() in self.days:
                midnight = datetime.combine(day, time(), zone)
                yield (
                    (midnight + timedelta(minutes=self.start)).astimezone(UTC),
                    (midnight + timedelta(minutes=self.end)).astimezone(UTC),
                )
            day += timedelta(days=1)

    def minutes(self, start: datetime, end: datetime, zone: Any) -> float:
        """Working minutes from ``start`` to ``end``."""

        if end <= start:
            return 0.0
        total = 0.0
        for open_at, close_at in self._windows(start, end, zone):
            total += (
                _minutes(max(start, open_at), min(end, close_at))
                if open_at < end and close_at > start
                else 0.0
            )
        return total

    def add(self, start: datetime, minutes: float, zone: Any) -> datetime:
        """The moment ``minutes`` working minutes after ``start``."""

        left = max(0.0, minutes)
        cursor = start
        for _ in range(60):  # weeks: a target is at most 90 days of working time
            horizon = cursor + timedelta(days=7)
            for open_at, close_at in self._windows(cursor, horizon, zone):
                if close_at <= cursor:
                    continue
                begin = max(cursor, open_at)
                room = _minutes(begin, close_at)
                if room >= left:
                    return begin + timedelta(minutes=left)
                left -= room
                cursor = close_at
            cursor = max(cursor, horizon)
        return cursor


class _Clock:
    """Minutes between two moments: on the calendar's working hours, or all of them."""

    def __init__(self, hours: ServiceHours | None, zone: Any):
        self.hours, self.zone = hours, zone

    def minutes(self, start: datetime, end: datetime) -> float:
        return self.hours.minutes(start, end, self.zone) if self.hours else _minutes(start, end)

    def add(self, start: datetime, minutes: float) -> datetime:
        if self.hours:
            return self.hours.add(start, minutes, self.zone)
        return start + timedelta(minutes=max(0.0, minutes))


def _verdict(used: float, target: int, *, finished: bool) -> str:
    if used > target:
        return "breached"
    if finished:
        return "met"
    return "at_risk" if used >= target * AT_RISK else "running"


def paused_minutes(
    created_at: str, statuses: list[tuple[str, str]], end: datetime, clock: _Clock | None = None
) -> tuple[float, bool]:
    """The minutes spent Blocked from ``created_at`` to ``end``, and whether it is Blocked at
    ``end``. ``statuses``: (time, status) of every status change, oldest first."""

    count = (clock or _Clock(None, UTC)).minutes
    paused = 0.0
    since: datetime | None = None
    for when, status in statuses:
        moment = _when(when)
        if moment is None or moment > end:
            break
        if status == PAUSED and since is None:
            since = moment
        elif status != PAUSED and since is not None:
            paused += count(since, moment)
            since = None
    if since is not None:
        paused += count(since, end)
    return paused, since is not None


def request_sla(
    request: dict[str, Any],
    statuses: list[tuple[str, str]],
    targets: Targets,
    now: datetime | None = None,
    hours: ServiceHours | None = None,
    zone: Any = UTC,
) -> dict[str, Any] | None:
    """Where a request stands against its targets; None for an archived one or an action.

    ``{"response": {target_minutes, used_minutes, state, due_at}, "resolution": {..., paused}}``
    with ``state`` one of running, at_risk, met, breached; ``due_at`` while it runs (the
    resolution's moves on while Blocked). With ``hours`` (the queue's service hours, in
    ``zone``) the clocks run only inside them."""

    if request.get("kind") != "request" or request.get("status") == "cancelled":
        return None
    now = now or _when(utc_text()) or datetime.now(UTC)
    created = _when(request["created_at"])
    if created is None:
        return None
    first_target, resolution_target = targets.minutes.get(
        request.get("priority") or "medium", targets.minutes["medium"]
    )
    clock = _Clock(hours, zone)
    answered = _when(request.get("first_response_at"))
    used = clock.minutes(created, answered or now)
    response = {
        "target_minutes": first_target,
        "used_minutes": round(used),
        "state": _verdict(used, first_target, finished=answered is not None),
        "due_at": None,
    }
    if answered is None:
        response["due_at"] = _iso(clock.add(created, first_target).timestamp())
    finished = request.get("status") == "done"
    end = (_when(request.get("completed_at")) if finished else None) or now
    paused, blocked = paused_minutes(request["created_at"], statuses, end, clock)
    spent = max(0.0, clock.minutes(created, end) - paused)
    resolution = {
        "target_minutes": resolution_target,
        "used_minutes": round(spent),
        "paused_minutes": round(paused),
        "paused": blocked and not finished,
        "state": _verdict(spent, resolution_target, finished=finished),
        "due_at": None,
    }
    if not finished and not blocked:
        resolution["due_at"] = _iso(clock.add(now, resolution_target - spent).timestamp())
    return {
        "response": response,
        "resolution": resolution,
        "service_hours": hours.as_dict() if hours else None,
    }


def _iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
