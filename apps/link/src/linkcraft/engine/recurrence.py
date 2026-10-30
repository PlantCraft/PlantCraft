"""A schedule's calendar: when it runs, as a person says it.

Every N minutes or hours (on some weekdays, between two times), every N days at one or more times,
every N weeks on chosen weekdays, every N months on a day of the month or on "the first Monday",
with an optional first and last day. It follows the model of iCalendar's RRULE (RFC 5545) and of
Elipse's Scheduling library, kept as plain fields a form fills in. Times are wall-clock times in
the schedule's time zone, so 06:00 stays 06:00 across daylight saving changes.
"""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from linkcraft.engine.zones import zone_of
from linkcraft.i18n import t

Clock = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
FREQUENCIES = ("minutes", "hours", "days", "weeks", "months")
# How far ahead a rule is searched: a rule that matches nothing in two years matches nothing.
HORIZON_DAYS = 800
# Monday, so "every 2 weeks" and "every 3 days" count from a fixed day when no start is given.
ANCHOR = date(2024, 1, 1)
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
ORDINALS = {1: "first", 2: "second", 3: "third", 4: "fourth", -1: "last"}


class MonthWeekday(BaseModel):
    """The n-th weekday of the month: ``{"n": 1, "weekday": 0}`` is the first Monday."""

    n: Literal[1, 2, 3, 4, -1]
    weekday: int = Field(ge=0, le=6)


class Recurrence(BaseModel):
    """When a schedule runs. ``weekdays`` are 0 (Monday) to 6."""

    freq: Literal["minutes", "hours", "days", "weeks", "months"]
    every: int = Field(default=1, ge=1, le=1000)
    # Days, weeks and months: the times of day it runs.
    times: list[str] = Field(default_factory=lambda: ["08:00"], max_length=48)
    # Minutes, hours and days: only on these weekdays (empty: every day); weeks: the days it runs.
    weekdays: list[int] = Field(default_factory=list, max_length=7)
    # Minutes and hours: only between these two times of day (both included).
    between: tuple[str, str] | None = None
    # Months: a day of the month (-1 the last), or the n-th weekday.
    month_day: int | None = Field(default=None, ge=-1, le=31)
    month_weekday: MonthWeekday | None = None
    # The first and the last day it runs (in the schedule's time zone), both optional.
    start: date | None = None
    end: date | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Recurrence:
        for clock in [*self.times, *(self.between or ())]:
            _clock(clock)
        if any(day < 0 or day > 6 for day in self.weekdays):
            raise ValueError(t("A weekday is 0 (Monday) to 6 (Sunday)."))
        if self.freq in {"days", "weeks", "months"} and not self.times:
            raise ValueError(t("Choose at least one time of day."))
        if self.freq == "weeks" and not self.weekdays:
            raise ValueError(t("Choose the days of the week it runs."))
        if self.freq == "months" and (self.month_day is None) == (self.month_weekday is None):
            raise ValueError(t("Choose a day of the month, or a weekday of the month."))
        if self.month_day == 0:
            raise ValueError(t("A day of the month is 1 to 31, or the last."))
        if self.between and _clock(self.between[0]) > _clock(self.between[1]):
            raise ValueError(t("The start of the time span comes after its end."))
        if self.start and self.end and self.end < self.start:
            raise ValueError(t("The last day comes before the first."))
        if self.freq == "minutes" and self.every > 24 * 60:
            raise ValueError(t("Every N minutes runs at least once a day: use days instead."))
        if self.freq == "hours" and self.every > 24:
            raise ValueError(t("Every N hours runs at least once a day: use days instead."))
        return self


def _clock(text: str) -> time:
    try:
        hour, minute = (int(part) for part in text.split(":"))
        return time(hour, minute)
    except (TypeError, ValueError) as exc:
        raise ValueError(t("A time of day is HH:MM, such as 06:00.")) from exc


def _runs_on(rule: Recurrence, day: date) -> bool:
    """Whether the rule runs at all on this local day."""

    if rule.start and day < rule.start:
        return False
    if rule.end and day > rule.end:
        return False
    anchor = rule.start or ANCHOR
    if rule.freq in {"minutes", "hours"}:
        return not rule.weekdays or day.weekday() in rule.weekdays
    if rule.freq == "days":
        if rule.weekdays and day.weekday() not in rule.weekdays:
            return False
        return (day - anchor).days % rule.every == 0
    if rule.freq == "weeks":
        monday = anchor - timedelta(days=anchor.weekday())
        return day.weekday() in rule.weekdays and ((day - monday).days // 7) % rule.every == 0
    months = (day.year * 12 + day.month) - (anchor.year * 12 + anchor.month)
    if months % rule.every:
        return False
    last = calendar.monthrange(day.year, day.month)[1]
    if rule.month_day is not None:
        wanted = last if rule.month_day == -1 else min(rule.month_day, last)
        return day.day == wanted
    found = rule.month_weekday
    assert found is not None  # the validator asks for one of the two
    if day.weekday() != found.weekday:
        return False
    if found.n == -1:
        return day.day + 7 > last
    return (day.day - 1) // 7 + 1 == found.n


def _slots(rule: Recurrence, day: date) -> list[time]:
    """The times of day the rule runs on a day it runs."""

    if rule.freq in {"minutes", "hours"}:
        step = rule.every * (60 if rule.freq == "hours" else 1)
        first = _clock(rule.between[0]) if rule.between else time(0, 0)
        last = _clock(rule.between[1]) if rule.between else time(23, 59)
        start = first.hour * 60 + first.minute
        stop = last.hour * 60 + last.minute
        # The clock's own steps from midnight (every 15 minutes: :00, :15, :30, :45).
        minute = -(-start // step) * step
        found = []
        while minute <= stop:
            found.append(time(minute // 60, minute % 60))
            minute += step
        return found
    return sorted({_clock(item) for item in rule.times})


def next_after(rule: Recurrence, timezone: str, after: datetime) -> datetime | None:
    """The first time the rule runs strictly after ``after`` (UTC), or None when it never does."""

    zone = zone_of(timezone)
    local = after.astimezone(zone)
    day = local.date()
    for _ in range(HORIZON_DAYS):
        if rule.end and day > rule.end:
            return None
        if _runs_on(rule, day):
            for slot in _slots(rule, day):
                moment = datetime.combine(day, slot, tzinfo=zone).astimezone(UTC)
                if moment > after:
                    return moment
        day += timedelta(days=1)
    return None


def _days(weekdays: list[int]) -> str:
    chosen = sorted(set(weekdays))
    if chosen == [0, 1, 2, 3, 4]:
        return t("Mon to Fri")
    if chosen == [5, 6]:
        return t("Sat and Sun")
    return ", ".join(t(WEEKDAYS[day]) for day in chosen)


def _times(items: list[str]) -> str:
    chosen = sorted(set(items))
    if len(chosen) == 1:
        return chosen[0]
    return t("{times} and {last}", times=", ".join(chosen[:-1]), last=chosen[-1])


def describe(rule: Recurrence) -> str:
    """The rule in one line, as the schedule's page and its form say it."""

    count = rule.every
    if rule.freq == "minutes":
        text = t("Every minute") if count == 1 else t("Every {n} minutes", n=count)
    elif rule.freq == "hours":
        text = t("Every hour") if count == 1 else t("Every {n} hours", n=count)
    elif rule.freq == "days":
        text = t("Every day") if count == 1 else t("Every {n} days", n=count)
    elif rule.freq == "weeks":
        text = t("Every week") if count == 1 else t("Every {n} weeks", n=count)
    else:
        text = t("Every month") if count == 1 else t("Every {n} months", n=count)
    if rule.freq == "weeks":
        text += t(" on {days}", days=_days(rule.weekdays))
    elif rule.weekdays and len(set(rule.weekdays)) < 7:
        text += f", {_days(rule.weekdays)}"
    if rule.freq == "months":
        if rule.month_day == -1:
            text += t(" on the last day")
        elif rule.month_day is not None:
            text += t(" on day {day}", day=rule.month_day)
        elif rule.month_weekday is not None:
            text += t(
                " on the {nth} {weekday}",
                nth=t(ORDINALS[rule.month_weekday.n]),
                weekday=t(WEEKDAYS[rule.month_weekday.weekday]),
            )
    if rule.freq in {"minutes", "hours"}:
        if rule.between:
            text += t(", {start} to {end}", start=rule.between[0], end=rule.between[1])
    else:
        text += t(" at {times}", times=_times(rule.times))
    if rule.start:
        text += t(", from {day}", day=rule.start.isoformat())
    if rule.end:
        text += t(", until {day}", day=rule.end.isoformat())
    return text


__all__ = ["FREQUENCIES", "MonthWeekday", "Recurrence", "describe", "next_after"]
