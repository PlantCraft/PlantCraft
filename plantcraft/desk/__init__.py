"""Desk: each person's day, the suite's first page.

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

This package puts ``DeskStore`` together and registers Desk's ``#`` mentions. The rest lives
by subject: ``desk.common`` (limits and shared checks), ``desk.todos`` (repeats of to-dos),
``desk.calendar`` (own events, .ics files and published calendars), ``desk.suggestions``, and
the store's methods in ``desk.todo_store``, ``desk.note_store``, ``desk.calendar_store`` and
``desk.triage_store``. The names other modules import from here stay importable from here.
"""

from __future__ import annotations

from typing import Any

from plantcraft.db import Store
from plantcraft.desk.calendar import (
    MAX_EVENT_DAYS,
    MAX_NOTES,
    MAX_OWN_EVENTS,
    REPEATS,
    CalendarError,
    _instant,
    _moment,
    _repeats_on,
    event_times,
    feed_url,
    host_allowed,
    occurrences,
    parse_ics,
    read_feed,
    repeats,
)
from plantcraft.desk.calendar_store import CalendarStore
from plantcraft.desk.common import (
    COLORS,
    FEED_MINUTES,
    MARKS,
    MAX_CALENDARS,
    MAX_EVENTS,
    MAX_FOLLOWS,
    MAX_ICS_BYTES,
    MAX_LISTS,
    MAX_NOTE_BYTES,
    MAX_NOTES_EACH,
    MAX_SHARES,
    MAX_STEPS,
    MAX_TITLE,
    MAX_TODOS,
    STALE_DAYS,
    TRIAGE_STATES,
    WINDOW_AFTER,
    WINDOW_BEFORE,
    _clean_title,
    _day,
    _forget_visits,
)
from plantcraft.desk.note_store import NoteStore
from plantcraft.desk.suggestions import Suggestion, _hidden, hidden, suggest
from plantcraft.desk.todo_store import TodoStore
from plantcraft.desk.todos import TODO_REPEATS, next_due, todo_due, todo_repeats
from plantcraft.desk.triage_store import TriageStore
from plantcraft.i18n import t

# The names other modules import from here, from before the split.
__all__ = [
    "COLORS",
    "CalendarError",
    "FEED_MINUTES",
    "MARKS",
    "MAX_CALENDARS",
    "MAX_EVENTS",
    "MAX_EVENT_DAYS",
    "MAX_FOLLOWS",
    "MAX_ICS_BYTES",
    "MAX_LISTS",
    "MAX_NOTES",
    "MAX_NOTES_EACH",
    "MAX_NOTE_BYTES",
    "MAX_OWN_EVENTS",
    "MAX_SHARES",
    "MAX_STEPS",
    "MAX_TITLE",
    "MAX_TODOS",
    "REPEATS",
    "STALE_DAYS",
    "Suggestion",
    "TODO_REPEATS",
    "TRIAGE_STATES",
    "WINDOW_AFTER",
    "WINDOW_BEFORE",
    "_clean_title",
    "_day",
    "_forget_visits",
    "_hidden",
    "_instant",
    "_moment",
    "_repeats_on",
    "event_times",
    "feed_url",
    "hidden",
    "host_allowed",
    "next_due",
    "occurrences",
    "parse_ics",
    "read_feed",
    "repeats",
    "suggest",
    "todo_due",
    "todo_repeats",
]


# Store ----------------------------------------------------------------------------------------


class DeskStore(TodoStore, NoteStore, CalendarStore, TriageStore, Store):
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

    def exists(self, kind: str, item_id: int) -> bool:
        """Whether a note, a to-do or an event with that id is there (for ``#`` mentions)."""

        table = {"note": "desk_notes", "todo": "desk_todos", "event": "desk_events"}[kind]
        with self._lock, self._connect() as connection:
            row = connection.execute(
                f"SELECT 1 FROM {table} WHERE {kind}_id = ?", (item_id,)
            ).fetchone()
        return row is not None


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
