"""The calendar: a person's own events and how they repeat, and calendars read from elsewhere
(an .ics file, or a published calendar link an administrator allows)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

from plantcraft.config import plant_timezone, plant_today
from plantcraft.db import utc_text
from plantcraft.desk.common import (
    MAX_EVENTS,
    MAX_ICS_BYTES,
    MAX_TITLE,
    WINDOW_AFTER,
    WINDOW_BEFORE,
    _day,
)
from plantcraft.i18n import t

# Own events ------------------------------------------------------------------------------------

# English constants; read them through ``t()``.
REPEATS = {
    "": "Does not repeat",
    "daily": "Every day",
    "weekdays": "Monday to Friday",
    "weekly": "Every week",
    "monthly": "Every month",
}
MAX_OWN_EVENTS = 2000
MAX_NOTES = 2000
# An event lasts three months at most (a holiday, a turnaround); a repeat is one of its days.
MAX_EVENT_DAYS = 92


def repeats() -> list[dict[str, str]]:
    return [{"id": key, "label": t(label)} for key, label in REPEATS.items()]


def _instant(value: str) -> datetime:
    """A time from the browser: with its offset, or (without one) in the plant's time zone."""

    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(t("The time must be a date and time (2026-10-24T09:00).")) from exc
    return moment if moment.tzinfo else moment.replace(tzinfo=plant_timezone())


def event_times(start: str, end: str | None, all_day: bool) -> tuple[str, str]:
    """An event's start and end as stored: days (the end not included, as in iCalendar) for an
    all-day event, UTC instants for the rest. Raises ``ValueError`` with a reason."""

    if all_day:
        first = date.fromisoformat(_day(start))
        last = date.fromisoformat(_day(end)) if end else first + timedelta(days=1)
        if last <= first:
            last = first + timedelta(days=1)
        if (last - first).days > MAX_EVENT_DAYS:
            raise ValueError(t("An event lasts {count} days at most.", count=MAX_EVENT_DAYS))
        return first.isoformat(), last.isoformat()
    begin = _instant(start)
    finish = _instant(end) if end else begin + timedelta(hours=1)
    if finish <= begin:
        raise ValueError(t("The end comes after the start."))
    if finish - begin > timedelta(days=MAX_EVENT_DAYS):
        raise ValueError(t("An event lasts {count} days at most.", count=MAX_EVENT_DAYS))
    return utc_text(begin), utc_text(finish)


def _repeats_on(repeat: str, first: date, day: date) -> bool:
    # The first day is always one of them, as in iCalendar (a weekday repeat made on a Saturday).
    if day <= first:
        return day == first
    if repeat == "daily":
        return True
    if repeat == "weekdays":
        return day.weekday() < 5
    if repeat == "weekly":
        return day.weekday() == first.weekday()
    if repeat == "monthly":
        return day.day == first.day
    return day == first


def occurrences(event: dict[str, Any], low: date, high: date) -> list[tuple[str, str]]:
    """The (start, end) of each time ``event`` happens on a plant day in [low, high], its
    repeats laid out in the plant's time zone (a 09:00 meeting stays at 09:00 across a change
    of summer time)."""

    zone = plant_timezone()
    repeat = event.get("repeat") or ""
    until = date.fromisoformat(event["until"]) if event.get("until") else None
    if event["all_day"]:
        first = date.fromisoformat(event["start"][:10])
        length = date.fromisoformat(event["end"][:10]) - first
        local: datetime | None = None
    else:
        local = datetime.fromisoformat(event["start"].replace("Z", "+00:00")).astimezone(zone)
        first = local.date()
        length = datetime.fromisoformat(event["end"].replace("Z", "+00:00")) - local
    found: list[tuple[str, str]] = []
    day = max(first, low - timedelta(days=length.days + 1))
    while day <= high and (until is None or day <= until):
        if _repeats_on(repeat, first, day):
            if local is None:
                begin_day, end_day = day, day + length
                if begin_day <= high and end_day > low:
                    found.append((begin_day.isoformat(), end_day.isoformat()))
            else:
                begin = datetime.combine(day, local.time(), zone)
                finish = begin + length
                last = (finish - timedelta(microseconds=1)).astimezone(zone).date()
                if begin.date() <= high and last >= low:
                    found.append((utc_text(begin), utc_text(finish)))
        if not repeat:
            break
        day += timedelta(days=1)
    return found


# Calendars ------------------------------------------------------------------------------------


class CalendarError(ValueError):
    """A calendar that could not be read; the message says why, for the person."""


def feed_url(url: str) -> str:
    """A published calendar link as it is read: ``webcal://`` is HTTPS."""

    text = str(url or "").strip()
    if text.lower().startswith("webcal://"):
        text = "https://" + text[len("webcal://") :]
    parts = urlsplit(text)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise CalendarError(t("A calendar link starts with https:// or webcal://."))
    if parts.username or parts.password:
        raise CalendarError(t("A calendar link must not carry a user name or password."))
    return text


def host_allowed(url: str, hosts: list[str]) -> bool:
    """``url``'s host is one of ``hosts`` or under one of them (``outlook.office365.com``)."""

    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    for allowed in hosts:
        name = allowed.strip().lower().lstrip("*.").rstrip(".")
        if name and (host == name or host.endswith(f".{name}")):
            return True
    return False


def _moment(value: Any) -> tuple[str, bool, datetime]:
    """An iCalendar date or date-time as (ISO text, all day, sortable UTC moment)."""

    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.astimezone()
        return moment.isoformat(timespec="minutes"), False, moment.astimezone(timezone.utc)
    if isinstance(value, date):
        return value.isoformat(), True, datetime.combine(value, time(), tzinfo=timezone.utc)
    raise CalendarError(t("The calendar has an event without a start."))


def parse_ics(text: str, *, today: date | None = None) -> list[dict[str, Any]]:
    """The events of an iCalendar file in the window Desk reads (recurring events expanded),
    in order. Raises :class:`CalendarError` with a reason for a file that is not a calendar."""

    from dateutil.rrule import rruleset, rrulestr
    from icalendar import Calendar

    if len(text.encode("utf-8")) > MAX_ICS_BYTES:
        raise CalendarError(t("The calendar is larger than 2 MB."))
    try:
        calendar = Calendar.from_ical(text)
    except (ValueError, IndexError, KeyError) as exc:
        raise CalendarError(t("This is not an iCalendar (.ics) file.")) from exc
    day = today or date.fromisoformat(plant_today())
    low = datetime.combine(day - WINDOW_BEFORE, time(), tzinfo=timezone.utc)
    high = datetime.combine(day + WINDOW_AFTER, time(), tzinfo=timezone.utc)
    found: list[tuple[datetime, dict[str, Any]]] = []
    for event in calendar.walk("VEVENT"):
        if str(event.get("STATUS", "")).upper() == "CANCELLED" or event.get("DTSTART") is None:
            continue
        start = event.decoded("DTSTART")
        if event.get("DTEND") is not None:
            end = event.decoded("DTEND")
        elif event.get("DURATION") is not None:
            end = start + event.decoded("DURATION")
        else:
            end = start + (timedelta(days=1) if not isinstance(start, datetime) else timedelta())
        length = end - start
        title = " ".join(str(event.get("SUMMARY", "")).split())[:MAX_TITLE] or t("(no title)")
        location = " ".join(str(event.get("LOCATION", "")).split())[:MAX_TITLE]
        uid = str(event.get("UID", ""))[:200]
        starts = [start]
        if event.get("RRULE") is not None:
            rules = rruleset()
            anchor = start if isinstance(start, datetime) else datetime.combine(start, time())
            rule_text = event["RRULE"].to_ical().decode()
            # UNTIL in UTC against a floating start (an all-day series) would not compare.
            if anchor.tzinfo is None:
                rule_text = (
                    rule_text.replace("Z;", ";").rstrip("Z") if "UNTIL" in rule_text else rule_text
                )
            try:
                rules.rrule(rrulestr(rule_text, dtstart=anchor))
            except (ValueError, TypeError):
                rules = None
            if rules is not None:
                exdates = event.get("EXDATE")
                for group in exdates if isinstance(exdates, list) else [exdates] if exdates else []:
                    for item in group.dts:
                        moment = (
                            item.dt
                            if isinstance(item.dt, datetime)
                            else datetime.combine(item.dt, time())
                        )
                        if (moment.tzinfo is None) != (anchor.tzinfo is None):
                            moment = moment.replace(tzinfo=anchor.tzinfo)
                        rules.exdate(moment)
                bounds = (
                    (low, high)
                    if anchor.tzinfo
                    else (low.replace(tzinfo=None), high.replace(tzinfo=None))
                )
                expanded = rules.between(*bounds, inc=True)
                starts = [
                    item if isinstance(start, datetime) else item.date()
                    for item in expanded[:MAX_EVENTS]
                ]
        for index, begin in enumerate(starts):
            first, all_day, key = _moment(begin)
            if not low <= key <= high:
                continue
            last, _, _ = _moment(begin + length)
            found.append(
                (
                    key,
                    {
                        "id": f"{uid}#{index}" if uid else f"event-{len(found)}",
                        "title": title,
                        "start": first,
                        "end": last,
                        "all_day": all_day,
                        "location": location,
                    },
                )
            )
            if len(found) >= MAX_EVENTS:
                break
        if len(found) >= MAX_EVENTS:
            break
    found.sort(key=lambda pair: pair[0])
    return [item for _, item in found]


def read_feed(url: str, hosts: list[str], *, fetch: Any = None) -> str:
    """The text of a published calendar link, when an administrator allowed its host."""

    link = feed_url(url)
    if not host_allowed(link, hosts):
        raise CalendarError(
            t(
                "An administrator has not allowed calendars from {host}.",
                host=urlsplit(link).hostname or "",
            )
        )
    if fetch is not None:
        return fetch(link)
    import requests

    try:
        with requests.get(
            link,
            timeout=10,
            stream=True,
            allow_redirects=False,
            headers={"Accept": "text/calendar"},
        ) as response:
            if response.status_code != 200:
                raise CalendarError(
                    t("The calendar link answered {status}.", status=response.status_code)
                )
            body = b""
            for chunk in response.iter_content(65536):
                body += chunk
                if len(body) > MAX_ICS_BYTES:
                    raise CalendarError(t("The calendar is larger than 2 MB."))
    except requests.RequestException as exc:
        raise CalendarError(t("The calendar link could not be read.")) from exc
    return body.decode("utf-8", errors="replace")
