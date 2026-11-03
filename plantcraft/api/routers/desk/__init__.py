"""Desk: each person's day (docs/desk.md). Their to-dos and lists, the assets they follow,
their calendar (own events, actions, to-dos, alarms on followed assets, the apps'
scheduled runs and calendars read from elsewhere), the day's suggestions and, for
a group leader, their team.

Everything here is the person's own: a reader (viewer) keeps their own to-dos and calendar
too (``open_to("viewer")``). Actions, conversations and results are read through the stores
that own them, with the person's own sight of them.

Its routes live by subject, on the one ``router`` of ``desk.common``: ``today_routes``,
``todo_routes``, ``note_routes``, ``follow_routes``, ``calendar_routes`` (calendars read from
elsewhere, own events and the calendar view), ``triage_routes``, ``team_routes`` and
``settings_routes``; what several of them read is in ``common``, what the apps put in Desk in
``app_items``. No route module imports another, so importing them below in the order they were
written in registers the routes in that order. The names other modules import from here stay
importable from here.
"""

from __future__ import annotations

# isort: off
# The routes register in the order they were written in when this was one file.
from plantcraft.api.routers.desk import today_routes  # noqa: F401
from plantcraft.api.routers.desk import todo_routes  # noqa: F401
from plantcraft.api.routers.desk import note_routes  # noqa: F401
from plantcraft.api.routers.desk import follow_routes  # noqa: F401
from plantcraft.api.routers.desk import calendar_routes  # noqa: F401
from plantcraft.api.routers.desk import triage_routes  # noqa: F401
from plantcraft.api.routers.desk import team_routes  # noqa: F401
from plantcraft.api.routers.desk import settings_routes  # noqa: F401

# isort: on
from plantcraft.api.routers.desk.app_items import _app_names, app_feeds, app_todos
from plantcraft.api.routers.desk.calendar_routes import (
    CalendarIn,
    EventChange,
    EventIn,
    _overlaps,
    _public_calendar,
    _refresh,
    add_calendar,
    calendar,
    calendars,
    change_event,
    create_event,
    delete_calendar,
    delete_event,
    own_event,
    refresh_calendar,
    scheduled_runs,
)
from plantcraft.api.routers.desk.common import (
    DAY,
    MAX_SPAN_DAYS,
    _bad,
    _my_groups,
    _open_refs,
    _present_note,
    _today,
    _today_todos,
    _with_refs,
    _worst,
    followed_assets,
    note_mentions,
    own_events,
    router,
)
from plantcraft.api.routers.desk.follow_routes import FollowIn, follow, follows, unfollow
from plantcraft.api.routers.desk.note_routes import (
    NoteChange,
    NoteIn,
    _check_shares,
    _note_for,
    change_note,
    create_note,
    delete_note,
    note,
    notes,
)
from plantcraft.api.routers.desk.settings_routes import (
    DeskSettingsIn,
    TeamPageIn,
    desk_settings,
    save_desk_settings,
    save_team_page,
    team_page,
)
from plantcraft.api.routers.desk.team_routes import (
    BOARD_STATUSES,
    HANDOVER_DAYS,
    AssignIn,
    _group_board,
    _led_groups,
    _managed_groups,
    _team_board,
    _team_group,
    _team_overview,
    _team_people,
    assign,
    availability,
    handover,
    handover_ref,
    team,
)
from plantcraft.api.routers.desk.today_routes import today
from plantcraft.api.routers.desk.todo_routes import (
    AppTodoDone,
    ListChange,
    ListIn,
    TodoAction,
    TodoChange,
    TodoIn,
    _leads,
    _list_for,
    _may_set_up,
    _own_list,
    _todo_for,
    change_list,
    change_todo,
    complete_app_todo,
    create_list,
    create_todo,
    delete_list,
    delete_todo,
    todo_to_action,
    todos,
)
from plantcraft.api.routers.desk.triage_routes import TriageIn, triage

# The names other modules import from here, from before the split.
__all__ = [
    "AppTodoDone",
    "AssignIn",
    "BOARD_STATUSES",
    "CalendarIn",
    "DAY",
    "DeskSettingsIn",
    "EventChange",
    "EventIn",
    "FollowIn",
    "HANDOVER_DAYS",
    "ListChange",
    "ListIn",
    "MAX_SPAN_DAYS",
    "NoteChange",
    "NoteIn",
    "TeamPageIn",
    "TodoAction",
    "TodoChange",
    "TodoIn",
    "TriageIn",
    "_app_names",
    "_bad",
    "_check_shares",
    "_group_board",
    "_leads",
    "_led_groups",
    "_list_for",
    "_managed_groups",
    "_may_set_up",
    "_my_groups",
    "_note_for",
    "_open_refs",
    "_overlaps",
    "_own_list",
    "_present_note",
    "_public_calendar",
    "_refresh",
    "_team_board",
    "_team_group",
    "_team_overview",
    "_team_people",
    "_today",
    "_today_todos",
    "_todo_for",
    "_with_refs",
    "_worst",
    "add_calendar",
    "app_feeds",
    "app_todos",
    "assign",
    "availability",
    "calendar",
    "calendars",
    "change_event",
    "change_list",
    "change_note",
    "change_todo",
    "complete_app_todo",
    "create_event",
    "create_list",
    "create_note",
    "create_todo",
    "delete_calendar",
    "delete_event",
    "delete_list",
    "delete_note",
    "delete_todo",
    "desk_settings",
    "follow",
    "followed_assets",
    "follows",
    "handover",
    "handover_ref",
    "note",
    "note_mentions",
    "notes",
    "own_event",
    "own_events",
    "refresh_calendar",
    "router",
    "save_desk_settings",
    "save_team_page",
    "scheduled_runs",
    "team",
    "team_page",
    "today",
    "todo_to_action",
    "todos",
    "triage",
    "unfollow",
]
