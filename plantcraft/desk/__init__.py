"""Desk: each person's day, the suite's first page (owner, 2026-10-23).

Desk is an app of the suite served by the platform itself (docs/desk.md). What every app shares
stays where it is: actions, conversations, groups, results and events. Desk keeps only what is
its own:

- each person's **to-dos**, in lists of their own or of a group (a group's list is shared by its
  people): a date, a repeat (every day, on weekdays or on some days of the week), steps inside,
  and "My day" for what they pick for today; the day's checklists and routines of before became
  to-dos (round 7, 2026-10-24);
- the assets each person **follows** (their alarms and results come to their Desk);
- each person's **notes** (rich text with checklists and ``#`` mentions), private until they
  share one with people or groups, and maybe tied to a calendar event (a meeting's note);
- each person's own **events** on the calendar, once or repeated (every day, on weekdays, every
  week or every month), laid out in the plant's time zone;
- **calendars** read from elsewhere (Outlook, Google, any .ics), read only: a file imported or,
  when an administrator allows it, a published calendar link read again every 15 minutes;
- what a person did with an inbox entry or a suggestion (**triage**: done, or snoozed until a day);
- the **suggestions** of the day: plain rules, each with its reason, never an order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

from plantcraft.config import plant_clock, plant_timezone, plant_today
from plantcraft.db import Store, utc_text
from plantcraft.i18n import t

# English constants; read them through ``t()``.
TODO_REPEATS = {
    "": "Does not repeat",
    "daily": "Every day",
    "weekdays": "Monday to Friday",
    "days": "On some days of the week",
}
MAX_TITLE = 200
MAX_TODOS = 3000
MAX_LISTS = 30
MAX_STEPS = 30
MAX_NOTES_EACH = 2000
MAX_NOTE_BYTES = 200_000
MAX_SHARES = 50
MAX_CALENDARS = 10
MAX_ICS_BYTES = 2_000_000
MAX_EVENTS = 3000
MAX_FOLLOWS = 200
FEED_MINUTES = 15
# The window a calendar is read for: the past quarter and the coming year.
WINDOW_BEFORE = timedelta(days=92)
WINDOW_AFTER = timedelta(days=400)
COLORS = ("#6a3d9a", "#0a64b2", "#00726b", "#9c4419", "#80591a", "#4a5a6e")
TRIAGE_STATES = ("done", "snoozed", "read", "unread")
# What a person marks on a notification, a conversation or an assistant chat (owner, 2026-10-28):
# a favorite, or unread again until they open it. A public demo visit also keeps what it read
# (``read``, ``conversation:<id>@<message id>``): the account's own read marks are every visitor's.
MARKS = ("star", "unread", "read")
# A public demo visit's marks (``<account>#visit:<id>``) go a day later.
VISIT_OWNER = "#visit:"
# A suggestion about an action untouched this long.
STALE_DAYS = 14


def todo_repeats() -> list[dict[str, str]]:
    return [{"id": key, "label": t(label)} for key, label in TODO_REPEATS.items()]


def todo_due(todo: dict[str, Any], day: date) -> bool:
    """Whether a repeated to-do falls on ``day`` (any day, for one that does not repeat)."""

    repeat = todo.get("repeat") or ""
    if repeat == "daily":
        return True
    if repeat == "weekdays":
        return day.weekday() < 5
    if repeat == "days":
        return day.weekday() in set(todo.get("days") or [])
    return True


def next_due(todo: dict[str, Any], after: date) -> date | None:
    """The first day after ``after`` a repeated to-do falls on (None when it does not repeat)."""

    if not todo.get("repeat"):
        return None
    day = after + timedelta(days=1)
    for _ in range(8):
        if todo_due(todo, day):
            return day
        day += timedelta(days=1)
    return None


def _clean_title(text: str) -> str:
    title = " ".join(str(text or "").split())
    if not title:
        raise ValueError(t("Write what is to be done."))
    if len(title) > MAX_TITLE:
        raise ValueError(t("Keep it under {count} characters.", count=MAX_TITLE))
    return title


def _day(value: str | date | None) -> str:
    if value is None or value == "":
        return date.fromisoformat(plant_today()).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError as exc:
        raise ValueError(t("The day must be a date (YYYY-MM-DD).")) from exc


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


# Suggestions ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Suggestion:
    key: str
    title: str
    reason: str
    state: str
    href: str
    action: str

    def as_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "title": self.title,
            "reason": self.reason,
            "state": self.state,
            "href": self.href,
            "action": self.action,
        }


def suggest(
    *,
    username: str,
    today: date,
    actions: list[dict[str, Any]],
    followed: list[dict[str, Any]],
    conversations: list[dict[str, Any]],
    triage: dict[str, dict[str, Any]],
    now: datetime | None = None,
    limit: int = 8,
) -> list[dict[str, str]]:
    """The day's suggestions, worst first, each with its reason (owner, 2026-10-23: suggestions,
    not orders). ``actions`` are the open ones the person owns; ``followed`` the current results
    about assets they follow (with ``open_actions``); ``conversations`` theirs."""

    moment = now or datetime.now(timezone.utc)
    found: list[Suggestion] = []
    for action in actions:
        if action.get("owner") != username or not action.get("due_at"):
            continue
        due = date.fromisoformat(action["due_at"][:10])
        href = f"/actions/{action['action_id']}"
        if due < today:
            days = (today - due).days
            found.append(
                Suggestion(
                    f"overdue:{action['action_id']}",
                    action["title"],
                    t("Past its due date by {count} days.", count=days)
                    if days > 1
                    else t("Past its due date since yesterday."),
                    "alarm",
                    href,
                    t("Open"),
                )
            )
        elif due == today:
            found.append(
                Suggestion(
                    f"due:{action['action_id']}:{today.isoformat()}",
                    action["title"],
                    t("Due today."),
                    "warning",
                    href,
                    t("Open"),
                )
            )
    for result in followed:
        if result.get("status") not in ("alarm", "warning") or result.get("open_actions"):
            continue
        ref = result["subject"]
        name = result.get("name") or ref.split(":", 1)[-1]
        title = t(
            "{name}: {summary}", name=name, summary=result.get("summary") or t("needs a look")
        )
        found.append(
            Suggestion(
                f"followed:{ref}:{result.get('app')}:{result.get('kind')}:{result.get('at', '')[:10]}",
                title,
                t("An asset you follow, with no open action."),
                result["status"],
                f"/actions?new=1&ref={ref}&title={title[:120]}",
                t("Create an action"),
            )
        )
    for conversation in conversations:
        last = conversation.get("last_message") or {}
        if (
            not conversation.get("unread")
            or last.get("author") == username
            or not last.get("created_at")
        ):
            continue
        try:
            sent = datetime.fromisoformat(str(last["created_at"]))
        except ValueError:
            continue
        sent = sent if sent.tzinfo else sent.astimezone()
        if moment - sent < timedelta(hours=4):
            continue
        name = (
            conversation.get("display_title")
            or conversation.get("title")
            or last.get("author_name")
            or ""
        )
        found.append(
            Suggestion(
                f"reply:{conversation['conversation_id']}:{last.get('message_id')}",
                t("Answer {name}", name=name),
                t(
                    "A message waiting since {when}.",
                    when=plant_clock(sent, "%d/%m %H:%M"),
                ),
                "warning",
                f"/messages/{conversation['conversation_id']}",
                t("Open"),
            )
        )
    for action in actions:
        if action.get("owner") != username or not action.get("updated_at"):
            continue
        try:
            changed = datetime.fromisoformat(str(action["updated_at"]))
        except ValueError:
            continue
        changed = changed if changed.tzinfo else changed.astimezone()
        days = (moment - changed).days
        if days >= STALE_DAYS and not (
            action.get("due_at") and action["due_at"][:10] <= today.isoformat()
        ):
            found.append(
                Suggestion(
                    f"stale:{action['action_id']}:{action['updated_at'][:10]}",
                    action["title"],
                    t("No change for {count} days: still on it?", count=days),
                    "unknown",
                    f"/actions/{action['action_id']}",
                    t("Open"),
                )
            )
    rank = {"alarm": 0, "warning": 1, "unknown": 2, "ok": 3}
    kept = [item for item in found if not _hidden(triage.get(item.key), today)]
    kept.sort(key=lambda item: rank.get(item.state, 3))
    return [item.as_dict() for item in kept[:limit]]


def _hidden(entry: dict[str, Any] | None, today: date) -> bool:
    if not entry:
        return False
    if entry["state"] == "done":
        return True
    return bool(entry.get("until")) and str(entry["until"]) > today.isoformat()


def hidden(entry: dict[str, Any] | None, today: date | None = None) -> bool:
    """A triaged entry is out of sight: done, or snoozed until a later day."""

    return _hidden(entry, today or date.fromisoformat(plant_today()))


def _forget_visits(connection: Any, table: str) -> None:
    """A public demo visit's marks last a day: the next visitor starts from the demo as seeded."""

    connection.execute(
        f"DELETE FROM {table} WHERE instr(username, ?) > 0 AND updated_at < ?",
        (VISIT_OWNER, utc_text(datetime.now(timezone.utc) - timedelta(days=1))),
    )


# Store ----------------------------------------------------------------------------------------


class DeskStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS desk_checklist (
        item_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        day TEXT NOT NULL,
        title TEXT NOT NULL,
        done INTEGER NOT NULL DEFAULT 0,
        done_at TEXT,
        routine_id INTEGER,
        position INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_desk_checklist_day ON desk_checklist(username, day);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_desk_checklist_routine
        ON desk_checklist(username, day, routine_id, title) WHERE routine_id IS NOT NULL;

    CREATE TABLE IF NOT EXISTS desk_routines (
        routine_id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        items_json TEXT NOT NULL DEFAULT '[]',
        cadence TEXT NOT NULL DEFAULT 'daily',
        days_json TEXT NOT NULL DEFAULT '[]',
        owner TEXT,
        group_id TEXT,
        active INTEGER NOT NULL DEFAULT 1,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS desk_todo_lists (
        list_id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner TEXT,
        group_id TEXT,
        name TEXT NOT NULL,
        color TEXT NOT NULL,
        position INTEGER NOT NULL DEFAULT 0,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS desk_todos (
        todo_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        group_id TEXT,
        list_id INTEGER,
        title TEXT NOT NULL,
        notes TEXT NOT NULL DEFAULT '',
        due TEXT,
        repeat TEXT NOT NULL DEFAULT '',
        days_json TEXT NOT NULL DEFAULT '[]',
        steps_json TEXT NOT NULL DEFAULT '[]',
        my_day TEXT,
        done INTEGER NOT NULL DEFAULT 0,
        done_at TEXT,
        done_by TEXT,
        action_id INTEGER,
        position INTEGER NOT NULL DEFAULT 0,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_desk_todos_user ON desk_todos(username, done);
    CREATE INDEX IF NOT EXISTS idx_desk_todos_group ON desk_todos(group_id, done);

    CREATE TABLE IF NOT EXISTS desk_notes (
        note_id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        body_json TEXT NOT NULL DEFAULT '{}',
        body_text TEXT NOT NULL DEFAULT '',
        shared_json TEXT NOT NULL DEFAULT '[]',
        event_ref TEXT,
        pinned INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_desk_notes_owner ON desk_notes(owner, updated_at);

    CREATE TABLE IF NOT EXISTS desk_follows (
        username TEXT NOT NULL,
        ref TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (username, ref)
    );

    CREATE TABLE IF NOT EXISTS desk_calendars (
        calendar_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        url TEXT,
        color TEXT NOT NULL,
        events_json TEXT NOT NULL DEFAULT '[]',
        fetched_at TEXT,
        error TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS desk_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        title TEXT NOT NULL,
        start TEXT NOT NULL,
        end TEXT NOT NULL,
        all_day INTEGER NOT NULL DEFAULT 0,
        repeat TEXT NOT NULL DEFAULT '',
        until TEXT,
        notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_desk_events_user ON desk_events(username, start);

    CREATE TABLE IF NOT EXISTS desk_triage (
        username TEXT NOT NULL,
        key TEXT NOT NULL,
        state TEXT NOT NULL,
        until TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (username, key)
    );

    CREATE TABLE IF NOT EXISTS desk_marks (
        username TEXT NOT NULL,
        key TEXT NOT NULL,
        mark TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (username, key, mark)
    );

    CREATE TABLE IF NOT EXISTS desk_settings (
        key TEXT PRIMARY KEY,
        value_json TEXT NOT NULL,
        updated_by TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """

    def __init__(self, db: Any) -> None:
        super().__init__(db)
        self.migrate_routines()

    # To-do --------------------------------------------------------------------------------------

    def migrate_routines(self) -> int:
        """The day checklists and routines of before round 7 become to-dos, once, with nothing
        lost: a routine becomes a list of its own (a group's routine, a list of the group) whose
        items repeat as it did; a checklist item becomes a to-do on its day (done or not). The
        items a routine had put on past days, not done, go: the repeated to-do stands for them.
        Returns how many to-dos were made."""

        with self._lock, self._write() as connection:
            routines = connection.execute(
                "SELECT * FROM desk_routines ORDER BY routine_id"
            ).fetchall()
            checks = connection.execute("SELECT * FROM desk_checklist ORDER BY item_id").fetchall()
            if not routines and not checks:
                return 0
            now, today = self._now(), date.fromisoformat(plant_today()).isoformat()
            made = 0
            for index, routine in enumerate(routines):
                cursor = connection.execute(
                    "INSERT INTO desk_todo_lists (owner, group_id, name, color, position, created_by, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        routine["owner"],
                        routine["group_id"],
                        routine["title"],
                        COLORS[index % len(COLORS)],
                        index,
                        routine["created_by"],
                        now,
                    ),
                )
                repeat = {"daily": "daily", "weekdays": "weekdays", "weekly": "days"}.get(
                    routine["cadence"], "daily"
                )
                for position, title in enumerate(self._loads(routine["items_json"], [])):
                    connection.execute(
                        "INSERT INTO desk_todos (username, group_id, list_id, title, due, repeat, days_json, position, "
                        "created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            routine["owner"],
                            routine["group_id"],
                            cursor.lastrowid,
                            str(title)[:MAX_TITLE],
                            today if routine["active"] else None,
                            repeat,
                            routine["days_json"] if repeat == "days" else "[]",
                            position,
                            routine["created_by"],
                            now,
                            now,
                        ),
                    )
                    made += 1
            for check in checks:
                if check["routine_id"] is not None and not check["done"] and check["day"] <= today:
                    continue
                connection.execute(
                    "INSERT INTO desk_todos (username, title, due, done, done_at, done_by, position, created_by, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        check["username"],
                        check["title"],
                        check["day"],
                        check["done"],
                        check["done_at"],
                        check["username"] if check["done"] else None,
                        check["position"],
                        check["username"],
                        check["created_at"],
                        now,
                    ),
                )
                made += 1
            connection.execute("DELETE FROM desk_checklist")
            connection.execute("DELETE FROM desk_routines")
        return made

    # Lists

    def _list(self, row: Any) -> dict[str, Any]:
        return dict(row)

    def todo_lists(self, username: str, groups: list[str]) -> list[dict[str, Any]]:
        """The person's lists, then their groups' (shared with everyone in the group)."""

        marks = ",".join("?" for _ in groups) or "''"
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM desk_todo_lists WHERE owner = ? OR group_id IN ({marks}) "
                "ORDER BY group_id IS NOT NULL, position, list_id",
                (username, *groups),
            ).fetchall()
        return [self._list(row) for row in rows]

    def todo_list(self, list_id: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM desk_todo_lists WHERE list_id = ?", (list_id,)
            ).fetchone()
        return self._list(row) if row else None

    def create_list(
        self, *, name: str, owner: str | None, group_id: str | None, color: str | None, actor: str
    ) -> dict[str, Any]:
        if bool(owner) == bool(group_id):
            raise ValueError(t("A list belongs to a person or to a group."))
        label = _clean_title(name)
        with self._lock, self._write() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM desk_todo_lists WHERE owner IS ? AND group_id IS ?",
                (owner, group_id),
            ).fetchone()[0]
            if count >= MAX_LISTS:
                raise ValueError(t("You keep {count} lists at most.", count=MAX_LISTS))
            cursor = connection.execute(
                "INSERT INTO desk_todo_lists (owner, group_id, name, color, position, created_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    owner,
                    group_id,
                    label,
                    color if color in COLORS else COLORS[count % len(COLORS)],
                    count,
                    actor,
                    self._now(),
                ),
            )
        return self.todo_list(int(cursor.lastrowid)) or {}

    def update_list(
        self, list_id: int, *, name: str | None = None, color: str | None = None
    ) -> dict[str, Any] | None:
        current = self.todo_list(list_id)
        if current is None:
            return None
        label = _clean_title(name) if name is not None else current["name"]
        tint = color if color in COLORS else current["color"]
        with self._lock, self._write() as connection:
            connection.execute(
                "UPDATE desk_todo_lists SET name = ?, color = ? WHERE list_id = ?",
                (label, tint, list_id),
            )
        return self.todo_list(list_id)

    def delete_list(self, list_id: int) -> bool:
        """A list goes with its to-dos."""

        with self._lock, self._write() as connection:
            connection.execute("DELETE FROM desk_todos WHERE list_id = ?", (list_id,))
            cursor = connection.execute("DELETE FROM desk_todo_lists WHERE list_id = ?", (list_id,))
        return cursor.rowcount > 0

    # To-dos

    def _todo(self, row: Any) -> dict[str, Any]:
        item = self._row_with_json(row, {"days": ("days_json", []), "steps": ("steps_json", [])})
        item["done"] = bool(item["done"])
        return item

    def todos(
        self,
        username: str,
        groups: list[str],
        *,
        done: bool | None = None,
        due_from: str | None = None,
        due_to: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """The person's to-dos and their groups' lists' to-dos."""

        marks = ",".join("?" for _ in groups) or "''"
        clauses = [f"((group_id IS NULL AND username = ?) OR group_id IN ({marks}))"]
        values: list[Any] = [username, *groups]
        if done is not None:
            clauses.append("done = ?")
            values.append(int(done))
        if due_from is not None:
            clauses.append("due >= ?")
            values.append(due_from)
        if due_to is not None:
            clauses.append("(due <= ? OR (repeat != '' AND due IS NOT NULL))")
            values.append(due_to)
        order = "done_at DESC" if done else "position, todo_id"
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM desk_todos WHERE {' AND '.join(clauses)} ORDER BY {order} LIMIT ?",
                (*values, limit),
            ).fetchall()
        return [self._todo(row) for row in rows]

    def todo(self, todo_id: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM desk_todos WHERE todo_id = ?", (todo_id,)
            ).fetchone()
        return self._todo(row) if row else None

    @staticmethod
    def _steps(steps: list[Any]) -> list[dict[str, Any]]:
        found = []
        for step in steps[: MAX_STEPS + 1]:
            text = " ".join(str((step or {}).get("text") or "").split())[:MAX_TITLE]
            if text:
                found.append({"text": text, "done": bool(step.get("done"))})
        if len(found) > MAX_STEPS:
            raise ValueError(t("A to-do has {count} steps at most.", count=MAX_STEPS))
        return found

    @staticmethod
    def _repeat(repeat: str, days: list[int]) -> tuple[str, list[int]]:
        if repeat not in TODO_REPEATS:
            raise ValueError(t("Repeat every day, on weekdays or on some days of the week."))
        weekdays = sorted({int(day) for day in days if 0 <= int(day) <= 6})
        if repeat == "days" and not weekdays:
            raise ValueError(t("Choose at least one day of the week."))
        return repeat, weekdays if repeat == "days" else []

    def create_todo(
        self,
        *,
        title: str,
        username: str | None,
        group_id: str | None,
        list_id: int | None,
        actor: str,
        due: str | None = None,
        repeat: str = "",
        days: list[int] | None = None,
        my_day: bool = False,
        notes: str = "",
        steps: list[Any] | None = None,
    ) -> dict[str, Any]:
        how, weekdays = self._repeat(repeat, days or [])
        when = _day(due) if due else None
        if how and not when:
            when = date.fromisoformat(plant_today()).isoformat()
        now = self._now()
        with self._lock, self._write() as connection:
            count, first = connection.execute(
                "SELECT COUNT(*), COALESCE(MIN(position), 0) FROM desk_todos WHERE username IS ? AND group_id IS ?",
                (username, group_id),
            ).fetchone()
            if count >= MAX_TODOS:
                raise ValueError(t("You keep {count} to-dos at most.", count=MAX_TODOS))
            cursor = connection.execute(
                "INSERT INTO desk_todos (username, group_id, list_id, title, notes, due, repeat, days_json, steps_json, "
                "my_day, position, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    username,
                    group_id,
                    list_id,
                    _clean_title(title),
                    str(notes or "").strip()[:MAX_NOTES],
                    when,
                    how,
                    self._json(weekdays),
                    self._json(self._steps(steps or [])),
                    date.fromisoformat(plant_today()).isoformat() if my_day else None,
                    int(first) - 1,
                    actor,
                    now,
                    now,
                ),
            )
        return self.todo(int(cursor.lastrowid)) or {}

    def update_todo(self, todo_id: int, change: dict[str, Any]) -> dict[str, Any] | None:
        """Change the fields given. ``my_day`` true puts it on today's list, false takes it off;
        ``list_id`` (with its owner or group, checked by the caller) moves it to another list."""

        current = self.todo(todo_id)
        if current is None:
            return None
        sets: dict[str, Any] = {}
        if "title" in change:
            sets["title"] = _clean_title(change["title"])
        if "notes" in change:
            text = str(change["notes"] or "").strip()
            if len(text) > MAX_NOTES:
                raise ValueError(t("Keep the notes under {count} characters.", count=MAX_NOTES))
            sets["notes"] = text
        if "due" in change:
            sets["due"] = _day(change["due"]) if change["due"] else None
        if "repeat" in change or "days" in change:
            how, weekdays = self._repeat(
                change.get("repeat", current["repeat"]) or "",
                change.get("days", current["days"]) or [],
            )
            sets["repeat"], sets["days_json"] = how, self._json(weekdays)
            if how and not sets.get("due", current["due"]):
                sets["due"] = date.fromisoformat(plant_today()).isoformat()
        if "steps" in change:
            sets["steps_json"] = self._json(self._steps(change["steps"] or []))
        if "my_day" in change:
            sets["my_day"] = (
                date.fromisoformat(plant_today()).isoformat() if change["my_day"] else None
            )
        if "list_id" in change:
            sets["list_id"] = change["list_id"]
            sets["username"] = change.get("username")
            sets["group_id"] = change.get("group_id")
        if "position" in change:
            sets["position"] = int(change["position"])
        if not sets:
            return current
        sets["updated_at"] = self._now()
        with self._lock, self._write() as connection:
            connection.execute(
                f"UPDATE desk_todos SET {', '.join(f'{key} = ?' for key in sets)} WHERE todo_id = ?",
                (*sets.values(), todo_id),
            )
        return self.todo(todo_id)

    def complete_todo(self, todo_id: int, done: bool, actor: str) -> dict[str, Any] | None:
        """Done, or back. A repeated to-do done stays open on its next day (its steps unchecked)
        and leaves a done copy behind, so that the Done list keeps what was done and when."""

        current = self.todo(todo_id)
        if current is None:
            return None
        now = self._now()
        today = date.fromisoformat(plant_today())
        with self._lock, self._write() as connection:
            if done and current["repeat"] and not current["done"]:
                connection.execute(
                    "INSERT INTO desk_todos (username, group_id, list_id, title, notes, due, steps_json, done, done_at, "
                    "done_by, position, created_by, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)",
                    (
                        current["username"],
                        current["group_id"],
                        current["list_id"],
                        current["title"],
                        current["notes"],
                        current["due"],
                        self._json(current["steps"]),
                        now,
                        actor,
                        current["position"],
                        current["created_by"],
                        now,
                        now,
                    ),
                )
                base = max(date.fromisoformat(current["due"]), today) if current["due"] else today
                following = next_due(current, base)
                steps = [{**step, "done": False} for step in current["steps"]]
                connection.execute(
                    "UPDATE desk_todos SET due = ?, steps_json = ?, my_day = NULL, updated_at = ? WHERE todo_id = ?",
                    (following.isoformat() if following else None, self._json(steps), now, todo_id),
                )
            else:
                connection.execute(
                    "UPDATE desk_todos SET done = ?, done_at = ?, done_by = ?, updated_at = ? WHERE todo_id = ?",
                    (int(done), now if done else None, actor if done else None, now, todo_id),
                )
        return self.todo(todo_id)

    def link_action(self, todo_id: int, action_id: int, actor: str) -> dict[str, Any] | None:
        """A to-do turned into an action: done, with the action it became."""

        now = self._now()
        with self._lock, self._write() as connection:
            connection.execute(
                "UPDATE desk_todos SET action_id = ?, done = 1, done_at = ?, done_by = ?, updated_at = ? "
                "WHERE todo_id = ?",
                (action_id, now, actor, now, todo_id),
            )
        return self.todo(todo_id)

    def delete_todo(self, todo_id: int) -> bool:
        with self._lock, self._write() as connection:
            cursor = connection.execute("DELETE FROM desk_todos WHERE todo_id = ?", (todo_id,))
        return cursor.rowcount > 0

    # Notes ------------------------------------------------------------------------------------

    def _note(self, row: Any, *, body: bool = True) -> dict[str, Any]:
        item = self._row_with_json(row, {"body": ("body_json", {}), "shared": ("shared_json", [])})
        item["pinned"] = bool(item["pinned"])
        if not body:
            item.pop("body")
        return item

    @staticmethod
    def note_visible(note: dict[str, Any], username: str, groups: list[str]) -> bool:
        """A note is its owner's; shared, it is also of the people and groups it names."""

        shared = set(note.get("shared") or [])
        return (
            note["owner"] == username
            or f"user:{username}" in shared
            or any(f"group:{group}" in shared for group in groups)
        )

    def notes(
        self, username: str, groups: list[str], *, q: str = "", event_ref: str | None = None
    ) -> list[dict[str, Any]]:
        """The person's notes and those shared with them, pinned first, newest first; ``q``
        looks in titles and text."""

        like = [f'%"user:{username}"%'] + [f'%"group:{group}"%' for group in groups]
        clauses = " OR ".join("shared_json LIKE ?" for _ in like)
        where = f"(owner = ? OR {clauses})"
        values: list[Any] = [username, *like]
        if q.strip():
            where += " AND (title LIKE ? OR body_text LIKE ?)"
            values += [f"%{q.strip()}%", f"%{q.strip()}%"]
        if event_ref:
            where += " AND event_ref = ?"
            values.append(event_ref)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM desk_notes WHERE {where} ORDER BY pinned DESC, updated_at DESC LIMIT 500",
                values,
            ).fetchall()
        found = [self._note(row, body=False) for row in rows]
        return [item for item in found if self.note_visible(item, username, groups)]

    def exists(self, kind: str, item_id: int) -> bool:
        """Whether a note, a to-do or an event with that id is there (for ``#`` mentions)."""

        table = {"note": "desk_notes", "todo": "desk_todos", "event": "desk_events"}[kind]
        with self._lock, self._connect() as connection:
            row = connection.execute(
                f"SELECT 1 FROM {table} WHERE {kind}_id = ?", (item_id,)
            ).fetchone()
        return row is not None

    def note(self, note_id: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM desk_notes WHERE note_id = ?", (note_id,)
            ).fetchone()
        return self._note(row) if row else None

    @staticmethod
    def _shares(shared: list[str]) -> list[str]:
        found = []
        for item in shared:
            text = str(item).strip()
            kind, _, name = text.partition(":")
            if kind not in ("user", "group") or not name:
                raise ValueError(t("Share a note with people or groups."))
            found.append(text)
        if len(found) > MAX_SHARES:
            raise ValueError(
                t("Share a note with {count} people or groups at most.", count=MAX_SHARES)
            )
        return list(dict.fromkeys(found))

    def _note_body(self, body: Any, text: str) -> tuple[str, str]:
        raw = self._json(body if isinstance(body, dict) else {})
        if len(raw.encode()) > MAX_NOTE_BYTES:
            raise ValueError(t("A note is {count} KB at most.", count=MAX_NOTE_BYTES // 1000))
        return raw, " ".join(str(text or "").split())[:20_000]

    def create_note(
        self,
        owner: str,
        *,
        title: str = "",
        body: Any = None,
        text: str = "",
        shared: list[str] | None = None,
        event_ref: str | None = None,
    ) -> dict[str, Any]:
        raw, plain = self._note_body(body, text)
        now = self._now()
        with self._lock, self._write() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM desk_notes WHERE owner = ?", (owner,)
            ).fetchone()[0]
            if count >= MAX_NOTES_EACH:
                raise ValueError(t("You keep {count} notes at most.", count=MAX_NOTES_EACH))
            cursor = connection.execute(
                "INSERT INTO desk_notes (owner, title, body_json, body_text, shared_json, event_ref, created_at, updated_at, updated_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    owner,
                    " ".join(str(title or "").split())[:MAX_TITLE],
                    raw,
                    plain,
                    self._json(self._shares(shared or [])),
                    (event_ref or None) and str(event_ref)[:200],
                    now,
                    now,
                    owner,
                ),
            )
        return self.note(int(cursor.lastrowid)) or {}

    def update_note(
        self, note_id: int, change: dict[str, Any], actor: str
    ) -> dict[str, Any] | None:
        """The fields given; ``body`` comes with ``text`` (what search reads)."""

        sets: dict[str, Any] = {}
        if "title" in change:
            sets["title"] = " ".join(str(change["title"] or "").split())[:MAX_TITLE]
        if "body" in change:
            sets["body_json"], sets["body_text"] = self._note_body(
                change["body"], change.get("text", "")
            )
        if "shared" in change:
            sets["shared_json"] = self._json(self._shares(change["shared"] or []))
        if "pinned" in change:
            sets["pinned"] = int(bool(change["pinned"]))
        if "event_ref" in change:
            sets["event_ref"] = (change["event_ref"] or None) and str(change["event_ref"])[:200]
        if sets:
            sets["updated_at"], sets["updated_by"] = self._now(), actor
            with self._lock, self._write() as connection:
                connection.execute(
                    f"UPDATE desk_notes SET {', '.join(f'{key} = ?' for key in sets)} WHERE note_id = ?",
                    (*sets.values(), note_id),
                )
        return self.note(note_id)

    def delete_note(self, note_id: int) -> bool:
        with self._lock, self._write() as connection:
            cursor = connection.execute("DELETE FROM desk_notes WHERE note_id = ?", (note_id,))
        return cursor.rowcount > 0

    # Follows ----------------------------------------------------------------------------------

    def follows(self, username: str) -> list[str]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT ref FROM desk_follows WHERE username = ? ORDER BY created_at, ref",
                (username,),
            ).fetchall()
        return [row["ref"] for row in rows]

    def follow(self, username: str, ref: str) -> None:
        with self._lock, self._write() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM desk_follows WHERE username = ?", (username,)
            ).fetchone()[0]
            if count >= MAX_FOLLOWS:
                raise ValueError(t("You follow {count} assets at most.", count=MAX_FOLLOWS))
            connection.execute(
                "INSERT OR IGNORE INTO desk_follows (username, ref, created_at) VALUES (?, ?, ?)",
                (username, ref, self._now()),
            )

    def unfollow(self, username: str, ref: str) -> None:
        with self._lock, self._write() as connection:
            connection.execute(
                "DELETE FROM desk_follows WHERE username = ? AND ref = ?", (username, ref)
            )

    # Calendars --------------------------------------------------------------------------------

    def _calendar(self, row: Any, *, events: bool = False) -> dict[str, Any]:
        item = dict(row)
        raw = item.pop("events_json")
        if events:
            item["events"] = self._loads(raw, [])
        else:
            item["count"] = len(self._loads(raw, []))
        return item

    def calendars(self, username: str, *, events: bool = False) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM desk_calendars WHERE username = ? ORDER BY calendar_id", (username,)
            ).fetchall()
        return [self._calendar(row, events=events) for row in rows]

    def calendar(self, username: str, calendar_id: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM desk_calendars WHERE calendar_id = ? AND username = ?",
                (calendar_id, username),
            ).fetchone()
        return self._calendar(row, events=True) if row else None

    def add_calendar(
        self,
        username: str,
        *,
        name: str,
        kind: str,
        url: str | None,
        events: list[dict[str, Any]],
        error: str = "",
    ) -> dict[str, Any]:
        label = _clean_title(name)
        with self._lock, self._write() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM desk_calendars WHERE username = ?", (username,)
            ).fetchone()[0]
            if count >= MAX_CALENDARS:
                raise ValueError(t("You can add {count} calendars at most.", count=MAX_CALENDARS))
            now = self._now()
            cursor = connection.execute(
                "INSERT INTO desk_calendars (username, name, kind, url, color, events_json, fetched_at, error, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    username,
                    label,
                    kind,
                    url,
                    COLORS[count % len(COLORS)],
                    self._json(events),
                    now,
                    error,
                    now,
                ),
            )
        return self.calendar(username, int(cursor.lastrowid)) or {}

    def set_events(
        self, calendar_id: int, events: list[dict[str, Any]] | None, error: str = ""
    ) -> None:
        """A calendar read again: its events (kept as they were when ``events`` is None) and why
        the last reading failed (empty when it did not)."""

        with self._lock, self._write() as connection:
            if events is None:
                connection.execute(
                    "UPDATE desk_calendars SET fetched_at = ?, error = ? WHERE calendar_id = ?",
                    (self._now(), error, calendar_id),
                )
            else:
                connection.execute(
                    "UPDATE desk_calendars SET events_json = ?, fetched_at = ?, error = ? WHERE calendar_id = ?",
                    (self._json(events), self._now(), error, calendar_id),
                )

    def delete_calendar(self, username: str, calendar_id: int) -> bool:
        with self._lock, self._write() as connection:
            cursor = connection.execute(
                "DELETE FROM desk_calendars WHERE calendar_id = ? AND username = ?",
                (calendar_id, username),
            )
        return cursor.rowcount > 0

    # Own events -------------------------------------------------------------------------------

    @staticmethod
    def _event(row: Any) -> dict[str, Any]:
        item = dict(row)
        item["all_day"] = bool(item["all_day"])
        return item

    def events(self, username: str, low: date, high: date) -> list[dict[str, Any]]:
        """The person's events that may happen in [low, high]: those that start before its end
        and, repeated, have not stopped before its start."""

        before = (high + timedelta(days=2)).isoformat()
        after = (low - timedelta(days=MAX_EVENT_DAYS + 2)).isoformat()
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM desk_events WHERE username = ? AND start < ? "
                "AND (end >= ? OR (repeat != '' AND (until IS NULL OR until >= ?))) "
                "ORDER BY start, event_id",
                (username, before, after, low.isoformat()),
            ).fetchall()
        return [self._event(row) for row in rows]

    def event(self, username: str, event_id: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM desk_events WHERE event_id = ? AND username = ?",
                (event_id, username),
            ).fetchone()
        return self._event(row) if row else None

    @staticmethod
    def _event_fields(
        *,
        title: str,
        start: str,
        end: str | None,
        all_day: bool,
        repeat: str,
        until: str | None,
        notes: str,
    ) -> dict[str, Any]:
        if repeat not in REPEATS:
            raise ValueError(t("Repeat every day, on weekdays, every week or every month."))
        first, last = event_times(start, end, all_day)
        stop = _day(until) if repeat and until else None
        if stop and stop < first[:10]:
            raise ValueError(t("The repeat ends after the first day."))
        text = str(notes or "").strip()
        if len(text) > MAX_NOTES:
            raise ValueError(t("Keep the notes under {count} characters.", count=MAX_NOTES))
        return {
            "title": _clean_title(title),
            "start": first,
            "end": last,
            "all_day": int(bool(all_day)),
            "repeat": repeat,
            "until": stop,
            "notes": text,
        }

    def create_event(
        self,
        username: str,
        *,
        title: str,
        start: str,
        end: str | None = None,
        all_day: bool = False,
        repeat: str = "",
        until: str | None = None,
        notes: str = "",
    ) -> dict[str, Any]:
        fields = self._event_fields(
            title=title,
            start=start,
            end=end,
            all_day=all_day,
            repeat=repeat,
            until=until,
            notes=notes,
        )
        with self._lock, self._write() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM desk_events WHERE username = ?", (username,)
            ).fetchone()[0]
            if count >= MAX_OWN_EVENTS:
                raise ValueError(t("You keep {count} events at most.", count=MAX_OWN_EVENTS))
            now = self._now()
            cursor = connection.execute(
                "INSERT INTO desk_events (username, title, start, end, all_day, repeat, until, notes, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    username,
                    fields["title"],
                    fields["start"],
                    fields["end"],
                    fields["all_day"],
                    fields["repeat"],
                    fields["until"],
                    fields["notes"],
                    now,
                    now,
                ),
            )
        return self.event(username, int(cursor.lastrowid)) or {}

    def update_event(self, username: str, event_id: int, **change: Any) -> dict[str, Any] | None:
        """Change the fields given (``until`` None ends a repeat's end day); a moved or resized
        repeat moves the whole series."""

        current = self.event(username, event_id)
        if current is None:
            return None
        keys = ("title", "start", "end", "all_day", "repeat", "until", "notes")
        merged = {key: current[key] for key in keys}
        merged.update({key: value for key, value in change.items() if key in keys})
        if "all_day" in change and bool(change["all_day"]) != current["all_day"]:
            # All day on or off: the start keeps its day, the end goes unless one was given.
            merged["end"] = change.get("end")
            if change["all_day"] and "start" not in change:
                local = datetime.fromisoformat(current["start"].replace("Z", "+00:00"))
                merged["start"] = local.astimezone(plant_timezone()).date().isoformat()
            elif not change["all_day"] and "start" not in change:
                merged["start"] = f"{current['start'][:10]}T09:00"
        fields = self._event_fields(**merged)
        with self._lock, self._write() as connection:
            connection.execute(
                "UPDATE desk_events SET title = ?, start = ?, end = ?, all_day = ?, repeat = ?, until = ?, "
                "notes = ?, updated_at = ? WHERE event_id = ? AND username = ?",
                (
                    fields["title"],
                    fields["start"],
                    fields["end"],
                    fields["all_day"],
                    fields["repeat"],
                    fields["until"],
                    fields["notes"],
                    self._now(),
                    event_id,
                    username,
                ),
            )
        return self.event(username, event_id)

    def delete_event(self, username: str, event_id: int) -> bool:
        with self._lock, self._write() as connection:
            cursor = connection.execute(
                "DELETE FROM desk_events WHERE event_id = ? AND username = ?", (event_id, username)
            )
        return cursor.rowcount > 0

    # Triage -----------------------------------------------------------------------------------

    def triage(self, username: str) -> dict[str, dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT key, state, until FROM desk_triage WHERE username = ?", (username,)
            ).fetchall()
        return {row["key"]: {"state": row["state"], "until": row["until"]} for row in rows}

    def set_triage(
        self, username: str, key: str, state: str | None, until: str | None = None
    ) -> None:
        with self._lock, self._write() as connection:
            if state is None:
                connection.execute(
                    "DELETE FROM desk_triage WHERE username = ? AND key = ?", (username, key)
                )
                return
            if state not in TRIAGE_STATES:
                raise ValueError(t("Mark it read, done or snooze it."))
            connection.execute(
                "INSERT INTO desk_triage (username, key, state, until, updated_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(username, key) DO UPDATE SET state = excluded.state, until = excluded.until, "
                "updated_at = excluded.updated_at",
                (
                    username,
                    key[:300],
                    state,
                    _day(until) if state == "snoozed" else None,
                    self._now(),
                ),
            )
            # Old entries go: a month is more than any inbox or suggestion lives.
            connection.execute(
                "DELETE FROM desk_triage WHERE username = ? AND updated_at < ?",
                (
                    username,
                    utc_text(datetime.now(timezone.utc) - timedelta(days=45)),
                ),
            )
            _forget_visits(connection, "desk_triage")

    # Marks ------------------------------------------------------------------------------------

    def marks(self, username: str, mark: str) -> set[str]:
        """The keys ``username`` marked with ``mark`` (``star`` or ``unread``)."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT key FROM desk_marks WHERE username = ? AND mark = ?", (username, mark)
            ).fetchall()
        return {row["key"] for row in rows}

    def set_mark(self, username: str, key: str, mark: str, on: bool) -> None:
        if mark not in MARKS:
            raise ValueError(t("Mark it as a favorite or as unread."))
        with self._lock, self._write() as connection:
            if on:
                connection.execute(
                    "INSERT INTO desk_marks (username, key, mark, updated_at) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(username, key, mark) DO UPDATE SET updated_at = excluded.updated_at",
                    (username, key[:300], mark, self._now()),
                )
            else:
                connection.execute(
                    "DELETE FROM desk_marks WHERE username = ? AND key = ? AND mark = ?",
                    (username, key[:300], mark),
                )
            _forget_visits(connection, "desk_marks")

    # Settings ---------------------------------------------------------------------------------

    def settings(self) -> dict[str, Any]:
        """Calendar links are off until an administrator turns them on and names the hosts
        (the platform may run with no internet, docs/security-guide.md)."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM desk_settings WHERE key = 'calendar_links'"
            ).fetchone()
        value = self._loads(row["value_json"] if row else None, {})
        hosts = [str(host) for host in value.get("hosts", []) if str(host).strip()][:20]
        return {
            "calendar_links": bool(value.get("enabled")) and bool(hosts),
            "enabled": bool(value.get("enabled")),
            "hosts": hosts,
        }

    def save_settings(self, *, enabled: bool, hosts: list[str], actor: str) -> dict[str, Any]:
        names: list[str] = []
        for host in hosts[:20]:
            name = str(host).strip().lower().lstrip("*.").rstrip(".")
            if not name:
                continue
            if "/" in name or ":" in name or " " in name or "." not in name:
                raise ValueError(
                    t(
                        "{host} is not a host name (outlook.office365.com, calendar.google.com).",
                        host=host,
                    )
                )
            names.append(name)
        with self._lock, self._write() as connection:
            connection.execute(
                "INSERT INTO desk_settings (key, value_json, updated_by, updated_at) VALUES ('calendar_links', ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_by = excluded.updated_by, "
                "updated_at = excluded.updated_at",
                (
                    self._json({"enabled": bool(enabled), "hosts": list(dict.fromkeys(names))}),
                    actor,
                    self._now(),
                ),
            )
        return self.settings()

    def team_page(self) -> bool:
        """Desk's Team page is hidden until an administrator shows it (owner, 2026-10-25: its use
        is not clear yet; nothing it reads is lost meanwhile)."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM desk_settings WHERE key = 'team_page'"
            ).fetchone()
        return bool(self._loads(row["value_json"] if row else None, {}).get("enabled"))

    def save_team_page(self, enabled: bool, *, actor: str) -> bool:
        with self._lock, self._write() as connection:
            connection.execute(
                "INSERT INTO desk_settings (key, value_json, updated_by, updated_at) VALUES ('team_page', ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_by = excluded.updated_by, "
                "updated_at = excluded.updated_at",
                (self._json({"enabled": bool(enabled)}), actor, self._now()),
            )
        return self.team_page()


# Mentions ---------------------------------------------------------------------------------------

DESK_REFS = {
    "note": ("Note {id}", "/notes?note={id}"),
    "todo": ("To-do {id}", "/todo?view=all&item={id}"),
    "event": ("Event {id}", "/calendar"),
}


def register_refs(refs: Any, store: DeskStore) -> None:
    """``#note:4``, ``#todo:12`` and ``#event:7`` in messages, actions and notes. What they are
    is private to their owner, so the link says only its kind and number to whoever reads it;
    opening it shows the item to whoever may see it (the picker shows the person their titles)."""

    for kind, (title, href) in DESK_REFS.items():

        def resolve(item_id: str, kind: str = kind, title: str = title, href: str = href):
            if not item_id.isdigit() or not store.exists(kind, int(item_id)):
                return None
            return {"title": t(title, id=item_id), "href": href.format(id=item_id), "status": None}

        refs.register(kind, resolve, owner="platform")
