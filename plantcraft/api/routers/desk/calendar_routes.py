"""Desk's calendar: calendars read from elsewhere, a person's own events, and the calendar view
that lays out events, actions, to-dos, alarms and the apps' scheduled runs."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated, Any

from fastapi import HTTPException, Query
from pydantic import BaseModel, Field

from plantcraft.api.deps import CurrentUser, Runtime, UserAccess, action_visibility, open_to
from plantcraft.api.routers.desk.app_items import app_feeds
from plantcraft.api.routers.desk.common import (
    DAY,
    MAX_SPAN_DAYS,
    _bad,
    _my_groups,
    _today,
    followed_assets,
    own_events,
    router,
)
from plantcraft.auth.suite import app_access
from plantcraft.config import plant_today
from plantcraft.desk import (
    FEED_MINUTES,
    CalendarError,
    feed_url,
    parse_ics,
    read_feed,
    repeats,
    todo_due,
)
from plantcraft.i18n import t

# Calendars ------------------------------------------------------------------------------------


class CalendarIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # The text of an .ics file, or a published calendar link.
    ics: str | None = Field(default=None, max_length=2_000_000)
    url: str | None = Field(default=None, max_length=2000)


def _public_calendar(item: dict[str, Any]) -> dict[str, Any]:
    keep = ("calendar_id", "name", "kind", "color", "fetched_at", "error", "count")
    found = {key: item.get(key) for key in keep}
    if "events" in item:
        found["count"] = len(item["events"])
    # A published link carries a secret token in its path: never shown again in full.
    if item.get("url"):
        found["host"] = item["url"].split("/")[2] if "//" in item["url"] else ""
    return found


@router.get("/api/desk/calendars")
def calendars(user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    return {
        "items": [_public_calendar(item) for item in rt.desk.calendars(user)],
        "links": rt.desk.settings()["calendar_links"],
    }


@router.post("/api/desk/calendars", status_code=201)
@open_to("viewer")
def add_calendar(body: CalendarIn, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    if bool(body.ics) == bool(body.url):
        raise HTTPException(
            status_code=422, detail=t("Import an .ics file or give a calendar link.")
        )
    try:
        if body.ics:
            events = parse_ics(body.ics)
            created = rt.desk.add_calendar(
                user, name=body.name, kind="file", url=None, events=events
            )
        else:
            settings = rt.desk.settings()
            if not settings["calendar_links"]:
                raise HTTPException(
                    status_code=403,
                    detail=t(
                        "An administrator has not turned on calendar links. Import an .ics file instead."
                    ),
                )
            link = feed_url(body.url or "")
            events = parse_ics(read_feed(link, settings["hosts"]))
            created = rt.desk.add_calendar(
                user, name=body.name, kind="url", url=link, events=events
            )
    except ValueError as exc:
        raise _bad(exc) from exc
    return _public_calendar(created)


def _refresh(rt: Any, user: str, calendar: dict[str, Any], *, force: bool = False) -> None:
    """A calendar link read again when it is older than 15 minutes (or ``force``)."""

    if calendar.get("kind") != "url" or not calendar.get("url"):
        return
    fetched = calendar.get("fetched_at")
    if not force and fetched:
        try:
            moment = datetime.fromisoformat(fetched)
            if datetime.now(moment.tzinfo) - moment < timedelta(minutes=FEED_MINUTES):
                return
        except ValueError:
            pass
    settings = rt.desk.settings()
    if not settings["calendar_links"]:
        rt.desk.set_events(
            calendar["calendar_id"], None, t("An administrator has turned calendar links off.")
        )
        return
    try:
        rt.desk.set_events(
            calendar["calendar_id"], parse_ics(read_feed(calendar["url"], settings["hosts"]))
        )
    except CalendarError as exc:
        rt.desk.set_events(calendar["calendar_id"], None, str(exc))


@router.post("/api/desk/calendars/{calendar_id}/refresh")
@open_to("viewer")
def refresh_calendar(calendar_id: int, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    calendar = rt.desk.calendar(user, calendar_id)
    if calendar is None:
        raise HTTPException(status_code=404, detail=t("Calendar not found."))
    _refresh(rt, user, calendar, force=True)
    return _public_calendar(rt.desk.calendar(user, calendar_id) or calendar)


@router.delete("/api/desk/calendars/{calendar_id}")
@open_to("viewer")
def delete_calendar(calendar_id: int, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    if not rt.desk.delete_calendar(user, calendar_id):
        raise HTTPException(status_code=404, detail=t("Calendar not found."))
    return {"deleted": calendar_id}


# Own events -----------------------------------------------------------------------------------


class EventIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    start: str = Field(min_length=10, max_length=40)
    end: str | None = Field(default=None, max_length=40)
    all_day: bool = False
    repeat: str = Field(default="", max_length=20)
    until: str | None = Field(default=None, pattern=DAY)
    notes: str = Field(default="", max_length=2000)


class EventChange(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    start: str | None = Field(default=None, min_length=10, max_length=40)
    end: str | None = Field(default=None, max_length=40)
    all_day: bool | None = None
    repeat: str | None = Field(default=None, max_length=20)
    until: str | None = Field(default=None, pattern=DAY)
    notes: str | None = Field(default=None, max_length=2000)


@router.get("/api/desk/events/{event_id}")
def own_event(event_id: int, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    event = rt.desk.event(user, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail=t("Event not found."))
    return {**event, "repeats": repeats()}


@router.post("/api/desk/events", status_code=201)
@open_to("viewer")
def create_event(body: EventIn, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """An event of the person's own: once, or repeated every day, on weekdays, every week or
    every month (until a day, or with no end)."""

    try:
        return rt.desk.create_event(user, **body.model_dump())
    except ValueError as exc:
        raise _bad(exc) from exc


@router.patch("/api/desk/events/{event_id}")
@open_to("viewer")
def change_event(
    event_id: int, body: EventChange, user: CurrentUser, rt: Runtime
) -> dict[str, Any]:
    """Only the fields sent change; ``until: null`` lets a repeat go on with no end. Moving or
    resizing one time of a repeat moves the whole series (the calendar sends the series' new
    start and end)."""

    change = body.model_dump(include=body.model_fields_set)
    for key in ("title", "start", "all_day", "repeat", "notes"):
        if key in change and change[key] is None:
            change.pop(key)
    try:
        event = rt.desk.update_event(user, event_id, **change)
    except ValueError as exc:
        raise _bad(exc) from exc
    if event is None:
        raise HTTPException(status_code=404, detail=t("Event not found."))
    return event


@router.delete("/api/desk/events/{event_id}")
@open_to("viewer")
def delete_event(event_id: int, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    if not rt.desk.delete_event(user, event_id):
        raise HTTPException(status_code=404, detail=t("Event not found."))
    return {"deleted": event_id}


def scheduled_runs(schedules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The apps' next scheduled runs, those in the same hour together as one entry ("6
    scheduled runs") so that a busy hour stays one line."""

    hours: dict[str, list[dict[str, Any]]] = {}
    for schedule in schedules:
        hours.setdefault(schedule["next_run"][:13], []).append(schedule)
    found = []
    for hour, items in hours.items():
        if len(items) == 1:
            schedule = items[0]
            found.append(
                {
                    "id": f"schedule:{schedule['app']}:{schedule['id']}",
                    "title": schedule["name"] or schedule["id"],
                    "start": schedule["next_run"],
                    "all_day": False,
                    "kind": "schedule",
                    "app": schedule["app"],
                    "href": schedule.get("url"),
                    "editable": False,
                    "detail": schedule.get("cadence") or "",
                }
            )
            continue
        items.sort(key=lambda item: (item["next_run"], item["name"] or item["id"]))
        found.append(
            {
                "id": f"runs:{hour}",
                "title": t("{count} scheduled runs", count=len(items)),
                "start": items[0]["next_run"],
                "all_day": False,
                "kind": "schedule",
                "editable": False,
                "detail": ", ".join(item["name"] or item["id"] for item in items[:5]),
                "runs": [
                    {
                        "title": item["name"] or item["id"],
                        "start": item["next_run"],
                        "app": item["app"],
                        "href": item.get("url"),
                        "detail": item.get("cadence") or "",
                    }
                    for item in items
                ],
            }
        )
    return found


def _overlaps(start: str, end: str | None, low: str, high: str) -> bool:
    return start[:10] <= high and (end or start)[:10] >= low


@router.get("/api/desk/calendar")
def calendar(
    user: CurrentUser,
    rt: Runtime,
    access: UserAccess,
    start: Annotated[str, Query(pattern=DAY)],
    end: Annotated[str, Query(pattern=DAY)],
) -> dict[str, Any]:
    """Everything with a date in [start, end]: the person's own events (repeats laid out), their
    actions and their groups' (by due date), their to-dos (repeats laid out on the days ahead),
    alarms on assets they follow, the scheduled runs of the apps they open (those in the same
    hour together), the feeds those apps keep (``feeds``, one chip each) and the calendars they
    added."""

    low, high = _today(start), _today(end)
    if high < low or (high - low).days > MAX_SPAN_DAYS:
        raise HTTPException(status_code=422, detail=t("Ask for a year at most."))
    lo, hi = low.isoformat(), high.isoformat()
    events: list[dict[str, Any]] = []
    seen = action_visibility(rt, user)
    for view in ("mine", "groups"):
        for action in rt.workspace.actions.list(visible=seen, view=view, limit=1000):
            due = action.get("due_at")
            if not due or not lo <= due[:10] <= hi or action["status"] == "cancelled":
                continue
            events.append(
                {
                    "id": f"action:{action['action_id']}",
                    "title": action["title"],
                    "start": due[:10],
                    "all_day": True,
                    "kind": "action",
                    "href": f"/actions/{action['action_id']}",
                    "done": action["status"] == "done",
                    "editable": seen.everything
                    or action.get("owner") == user
                    or action.get("created_by") == user,
                    "detail": action.get("owner_name") or action.get("group_name") or "",
                }
            )
    events = list({item["id"]: item for item in events}.values())
    today_iso = date.fromisoformat(plant_today()).isoformat()
    # To-dos on their day; a repeated one also on the days ahead it falls on.
    for item in rt.desk.todos(user, _my_groups(rt, user), due_to=hi, limit=3000):
        if not item["due"] or (item["done"] and not lo <= item["due"] <= hi):
            continue
        base = {
            "title": item["title"],
            "all_day": True,
            "kind": "todo",
            "href": f"/todo?item={item['todo_id']}",
            "done": item["done"],
            "editable": False,
        }
        if lo <= item["due"] <= hi:
            events.append({**base, "id": f"todo:{item['todo_id']}", "start": item["due"]})
        if item["repeat"] and not item["done"]:
            day = max(low, date.fromisoformat(item["due"]) + timedelta(days=1))
            while day <= high:
                if todo_due(item, day):
                    events.append(
                        {
                            **base,
                            "id": f"todo:{item['todo_id']}:{day.isoformat()}",
                            "start": day.isoformat(),
                        }
                    )
                day += timedelta(days=1)
    for item in followed_assets(rt, user):
        if (
            item["status"] in ("alarm", "warning")
            and item.get("at")
            and lo <= item["at"][:10] <= hi
        ):
            events.append(
                {
                    "id": f"result:{item['ref']}:{item['app']}:{item['kind']}",
                    "title": f"{item['name']}: {item['summary'] or item['status']}",
                    "start": item["at"][:10],
                    "all_day": True,
                    "kind": "alarm",
                    "state": item["status"],
                    "href": item.get("href"),
                    "editable": False,
                }
            )
    events.extend(own_events(rt, user, low, high))
    apps = app_access(access, rt.suite_apps())
    events.extend(
        scheduled_runs(
            [
                schedule
                for schedule in rt.workspace.results.schedules()
                if schedule["app"] in apps
                and schedule.get("enabled")
                and schedule.get("next_run")
                and lo <= schedule["next_run"][:10] <= hi
            ]
        )
    )
    feeds = app_feeds(rt, apps)
    for item in rt.app_items.calendar(
        lo, hi, apps={key.split(":")[0] for key in feeds}, user=user, groups=_my_groups(rt, user)
    ):
        feed = feeds.get(f"{item['app']}:{item['feed']}")
        if feed is None:
            continue
        events.append(
            {
                "id": f"feed:{feed['id']}:{item['id']}",
                "title": item["title"],
                "start": item["start"],
                "end": item["end"],
                "all_day": item["all_day"],
                "kind": "feed",
                "feed": feed["id"],
                "app": item["app"],
                "href": item["url"],
                "ref": item["ref"],
                "editable": False,
                "detail": item["detail"] or feed["title"],
            }
        )
    calendars_out = []
    for item in rt.desk.calendars(user, events=True):
        _refresh(rt, user, item)
    for item in rt.desk.calendars(user, events=True):
        calendars_out.append(_public_calendar(item))
        for event in item["events"]:
            if _overlaps(event["start"], event.get("end"), lo, hi):
                events.append(
                    {
                        **event,
                        "id": f"cal:{item['calendar_id']}:{event['id']}",
                        "kind": "external",
                        "calendar": item["name"],
                        "color": item["color"],
                        "editable": False,
                        "detail": event.get("location") or "",
                    }
                )
    events.sort(key=lambda item: (item["start"], 0 if item.get("all_day") else 1, item["title"]))
    return {
        "start": lo,
        "end": hi,
        "today": today_iso,
        "events": events,
        "calendars": calendars_out,
        "feeds": list(feeds.values()),
        "links": rt.desk.settings()["calendar_links"],
        "repeats": repeats(),
    }
