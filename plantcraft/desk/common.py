"""Desk's limits and the checks its parts share: titles, days and a public demo visit's marks."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from plantcraft.auth.public_demo import VISIT_OWNER
from plantcraft.config import plant_today
from plantcraft.db import utc_text
from plantcraft.i18n import t

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
# What a person marks on a notification, a conversation or an assistant chat:
# a favorite, or unread again until they open it. A public demo visit also keeps what it read
# (``read``, ``conversation:<id>@<message id>``): the account's own read marks are every visitor's.
MARKS = ("star", "unread", "read")
# A public demo visit's marks (``<account>#visit:<id>``) go a day later.
# A suggestion about an action untouched this long.
STALE_DAYS = 14


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


def _forget_visits(connection: Any, table: str) -> None:
    """A public demo visit's marks last a day: the next visitor starts from the demo as seeded."""

    connection.execute(
        f"DELETE FROM {table} WHERE instr(username, ?) > 0 AND updated_at < ?",
        (VISIT_OWNER, utc_text(datetime.now(timezone.utc) - timedelta(days=1))),
    )
