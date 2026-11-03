"""``DeskStore``'s calendars read from elsewhere and each person's own events. Part of
``DeskStore`` (``plantcraft.desk``)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from plantcraft.config import plant_timezone
from plantcraft.desk.calendar import MAX_EVENT_DAYS, MAX_NOTES, MAX_OWN_EVENTS, REPEATS, event_times
from plantcraft.desk.common import COLORS, MAX_CALENDARS, _clean_title, _day
from plantcraft.i18n import t


class CalendarStore:
    """``DeskStore``'s calendars and events."""

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
