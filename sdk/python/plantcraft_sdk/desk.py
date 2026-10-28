"""What an app puts in Desk: dated items in its calendar feeds and to-dos (API v1).

Desk owns the format (``docs/desk.md``); the app declares its feeds in
``[[contributes.calendar]]`` and its to-do kinds in ``[[contributes.todo]]``
(``plantcraft_sdk.contributes``), then sends:

- ``PUT /api/v1/calendar/<feed>`` with the feed's whole list of :class:`CalendarItemIn`
  (``client.put_calendar``), at most ``MAX_FEED_ITEMS``;
- ``POST /api/v1/todos`` with one :class:`TodoIn` (``client.put_todo``), upserted by ``key``;
  ``POST /api/v1/todos/close`` closes some (``client.close_todos``) and ``GET /api/v1/todos``
  lists the app's own, with who ticked them (``client.todos``).

Who an item is for is its ``audience``: ``user:<username>``, ``group:<id>`` or ``everyone``
(a to-do is never for everyone). A to-do is work the app asks a person for; a problem is an
event (``plantcraft_sdk.events``), never a to-do.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

MAX_FEED_ITEMS = 2000
MAX_OPEN_TODOS = 200

AUDIENCE = r"^(everyone|user:[A-Za-z0-9_.@\-]{1,80}|group:[A-Za-z0-9_.:\-]{1,80})$"
ASSIGNEE = r"^(user:[A-Za-z0-9_.@\-]{1,80}|group:[A-Za-z0-9_.:\-]{1,80})$"
# A day (all-day items) or an instant with its offset, as the rest of API v1.
WHEN = r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2}))?$"
DAY = r"^\d{4}-\d{2}-\d{2}$"

ItemId = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
When = Annotated[str, StringConstraints(pattern=WHEN)]
Ref = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z_]{1,31}:.{1,200}$")]


class _Item(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CalendarItemIn(_Item):
    """One dated item of a feed: an instant, a span, or whole days (``all_day``)."""

    id: ItemId
    title: Title
    start: When
    end: When | None = None
    all_day: bool = False
    audience: Annotated[str, StringConstraints(pattern=AUDIENCE)] = "everyone"
    # What it is about (``#asset:x``, ``#study:3``) and where a click goes in the app.
    ref: Ref | None = None
    url: Annotated[str, StringConstraints(max_length=500)] | None = None
    detail: Annotated[str, StringConstraints(max_length=300)] = ""

    @model_validator(mode="after")
    def _order(self) -> CalendarItemIn:
        if self.all_day and (len(self.start) != 10 or (self.end and len(self.end) != 10)):
            raise ValueError("an all-day item has days, not instants")
        if not self.all_day and len(self.start) == 10:
            raise ValueError("an item at an instant needs its time; set all_day for days")
        if self.end and self.end[:10] < self.start[:10]:
            raise ValueError("end comes before start")
        return self


class TodoIn(_Item):
    """A to-do the app asks of a person or a group; the same ``key`` changes it."""

    key: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    # One of the app's [[contributes.todo]] ids.
    kind: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,40}$")]
    title: Title
    for_: Annotated[str, StringConstraints(pattern=ASSIGNEE)] = Field(alias="for")
    due: Annotated[str, StringConstraints(pattern=DAY)] | None = None
    ref: Ref | None = None
    url: Annotated[str, StringConstraints(max_length=500)] | None = None
    detail: Annotated[str, StringConstraints(max_length=300)] = ""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    def as_body(self) -> dict[str, object]:
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


class FeedIn(BaseModel):
    """A feed's whole list."""

    items: list[CalendarItemIn] = Field(max_length=MAX_FEED_ITEMS)

    @model_validator(mode="after")
    def _ids(self) -> FeedIn:
        ids = [item.id for item in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("each item of a feed needs its own id")
        return self


__all__ = [
    "ASSIGNEE",
    "AUDIENCE",
    "MAX_FEED_ITEMS",
    "MAX_OPEN_TODOS",
    "CalendarItemIn",
    "FeedIn",
    "TodoIn",
]
