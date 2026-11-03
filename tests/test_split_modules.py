"""The large files split into modules by subject (refactor F5) keep every name they had: each
old import path still gives every top-level name of the file before the split, and each class
that was split into parts still has every method it had. The lists were taken from the files as
they were before their split."""

from __future__ import annotations

import importlib

import pytest

SPLIT = {
    "plantcraft.desk": {
        "names": [
            "TODO_REPEATS",
            "MAX_TITLE",
            "MAX_TODOS",
            "MAX_LISTS",
            "MAX_STEPS",
            "MAX_NOTES_EACH",
            "MAX_NOTE_BYTES",
            "MAX_SHARES",
            "MAX_CALENDARS",
            "MAX_ICS_BYTES",
            "MAX_EVENTS",
            "MAX_FOLLOWS",
            "FEED_MINUTES",
            "WINDOW_BEFORE",
            "WINDOW_AFTER",
            "COLORS",
            "TRIAGE_STATES",
            "MARKS",
            "STALE_DAYS",
            "todo_repeats",
            "todo_due",
            "next_due",
            "_clean_title",
            "_day",
            "REPEATS",
            "MAX_OWN_EVENTS",
            "MAX_NOTES",
            "MAX_EVENT_DAYS",
            "repeats",
            "_instant",
            "event_times",
            "_repeats_on",
            "occurrences",
            "CalendarError",
            "feed_url",
            "host_allowed",
            "_moment",
            "parse_ics",
            "read_feed",
            "Suggestion",
            "suggest",
            "_hidden",
            "hidden",
            "_forget_visits",
            "DeskStore",
            "DESK_REFS",
            "register_refs",
        ],
        "classes": {
            "DeskStore": [
                "__init__",
                "migrate_routines",
                "_list",
                "todo_lists",
                "todo_list",
                "create_list",
                "update_list",
                "delete_list",
                "_todo",
                "todos",
                "todo",
                "_steps",
                "_repeat",
                "create_todo",
                "update_todo",
                "complete_todo",
                "link_action",
                "delete_todo",
                "_note",
                "note_visible",
                "notes",
                "exists",
                "note",
                "_shares",
                "_note_body",
                "create_note",
                "update_note",
                "delete_note",
                "follows",
                "follow",
                "unfollow",
                "_calendar",
                "calendars",
                "calendar",
                "add_calendar",
                "set_events",
                "delete_calendar",
                "_event",
                "events",
                "event",
                "_event_fields",
                "create_event",
                "update_event",
                "delete_event",
                "triage",
                "set_triage",
                "marks",
                "set_mark",
                "settings",
                "save_settings",
                "team_page",
                "save_team_page",
            ]
        },
    },
}


@pytest.mark.parametrize("module", sorted(SPLIT))
def test_a_split_module_keeps_its_names(module: str) -> None:
    loaded = importlib.import_module(module)
    names = SPLIT[module]
    assert [name for name in names["names"] if not hasattr(loaded, name)] == []
    for cls, methods in names["classes"].items():
        assert [method for method in methods if not hasattr(getattr(loaded, cls), method)] == []
