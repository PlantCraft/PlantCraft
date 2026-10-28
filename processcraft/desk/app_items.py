"""What the apps put in Desk: dated items in calendar feeds and to-dos (``docs/desk.md``).

An app declares its feeds in ``[[contributes.calendar]]`` and its to-do kinds in
``[[contributes.todo]]`` (``docs/app-standard.md``, section 4b), then sends the items through
API v1. Desk is the owner of the format: who an item is for (``audience``), its dates, and the
limits that keep one app from flooding anyone's day.

- A **feed** is replaced whole on each ``PUT /api/v1/calendar/<feed>``: at most
  ``MAX_FEED_ITEMS`` items, each for ``user:<name>``, ``group:<id>`` or ``everyone``.
- A **to-do** is upserted by its ``key`` (``POST /api/v1/todos``): the same key changes it,
  never makes a second one. It is for a person or a group; the person ticks it in Desk, or the
  app closes it itself (``POST /api/v1/todos/close``). At most ``MAX_OPEN_TODOS`` open per app
  and per person or group.

A to-do is work the app asks for ("review schedule X"); a problem is an event, never a to-do.
"""

from __future__ import annotations

from typing import Any

from plantcraft_sdk.desk import MAX_FEED_ITEMS, MAX_OPEN_TODOS
from processcraft.db import Store


class AppItemError(ValueError):
    """A request Desk refuses; ``status`` is the HTTP status that says why."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def audience_matches(audience: str, user: str, groups: list[str]) -> bool:
    """Whether an item for ``audience`` reaches ``user`` (a member of ``groups``)."""

    if audience == "everyone":
        return True
    kind, _, target = audience.partition(":")
    return (kind == "user" and target == user) or (kind == "group" and target in groups)


class AppItemStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS desk_app_calendar (
        app TEXT NOT NULL,
        feed TEXT NOT NULL,
        item_id TEXT NOT NULL,
        title TEXT NOT NULL,
        start TEXT NOT NULL,
        end_at TEXT,
        all_day INTEGER NOT NULL DEFAULT 0,
        audience TEXT NOT NULL,
        ref TEXT,
        url TEXT,
        detail TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (app, feed, item_id)
    );
    CREATE INDEX IF NOT EXISTS desk_app_calendar_start ON desk_app_calendar (start);
    CREATE TABLE IF NOT EXISTS desk_app_feeds (
        app TEXT NOT NULL,
        feed TEXT NOT NULL,
        items INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (app, feed)
    );
    CREATE TABLE IF NOT EXISTS desk_app_todos (
        app TEXT NOT NULL,
        key TEXT NOT NULL,
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        assignee TEXT NOT NULL,
        due TEXT,
        ref TEXT,
        url TEXT,
        detail TEXT NOT NULL DEFAULT '',
        done_at TEXT,
        done_by TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (app, key)
    );
    CREATE INDEX IF NOT EXISTS desk_app_todos_assignee ON desk_app_todos (assignee, done_at);
    """

    # Calendar feeds ---------------------------------------------------------------------------

    def put_feed(self, app: str, feed: str, items: list[dict[str, Any]]) -> int:
        """The feed's items, replaced whole; answers how many it holds now."""

        if len(items) > MAX_FEED_ITEMS:
            raise AppItemError(413, f"A feed holds {MAX_FEED_ITEMS} items at most.")
        ids = [item["id"] for item in items]
        if len(set(ids)) != len(ids):
            raise AppItemError(422, "Each item of a feed needs its own id.")
        with self._lock, self._write() as connection:
            connection.execute(
                "DELETE FROM desk_app_calendar WHERE app = ? AND feed = ?", (app, feed)
            )
            connection.executemany(
                """
                INSERT INTO desk_app_calendar
                    (app, feed, item_id, title, start, end_at, all_day, audience, ref, url, detail)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        app,
                        feed,
                        item["id"],
                        item["title"],
                        item["start"],
                        item.get("end"),
                        1 if item.get("all_day") else 0,
                        item["audience"],
                        item.get("ref"),
                        item.get("url"),
                        item.get("detail") or "",
                    )
                    for item in items
                ],
            )
            connection.execute(
                """
                INSERT INTO desk_app_feeds (app, feed, items, updated_at) VALUES (?, ?, ?, ?)
                ON CONFLICT(app, feed) DO UPDATE SET items = excluded.items,
                    updated_at = excluded.updated_at
                """,
                (app, feed, len(items), self._now()),
            )
        return len(items)

    def feeds(self, app: str | None = None) -> list[dict[str, Any]]:
        """The feeds apps have sent: app, feed, how many items, when."""

        query, args = "SELECT * FROM desk_app_feeds", ()
        if app is not None:
            query, args = query + " WHERE app = ?", (app,)
        with self._lock, self._connect() as connection:
            rows = connection.execute(query + " ORDER BY app, feed", args).fetchall()
        return [dict(row) for row in rows]

    def calendar(
        self, low: str, high: str, *, apps: set[str], user: str, groups: list[str]
    ) -> list[dict[str, Any]]:
        """The items of ``apps`` that reach ``user`` and overlap the days [low, high]."""

        if not apps:
            return []
        marks = ",".join("?" for _ in apps)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM desk_app_calendar
                WHERE app IN ({marks}) AND substr(start, 1, 10) <= ?
                    AND substr(COALESCE(end_at, start), 1, 10) >= ?
                ORDER BY start, title
                """,
                (*sorted(apps), high, low),
            ).fetchall()
        return [
            {
                "app": row["app"],
                "feed": row["feed"],
                "id": row["item_id"],
                "title": row["title"],
                "start": row["start"],
                "end": row["end_at"],
                "all_day": bool(row["all_day"]),
                "ref": row["ref"],
                "url": row["url"],
                "detail": row["detail"],
            }
            for row in rows
            if audience_matches(row["audience"], user, groups)
        ]

    # To-dos -----------------------------------------------------------------------------------

    def put_todo(self, app: str, item: dict[str, Any]) -> dict[str, Any]:
        """The to-do with ``item["key"]``, made or changed; a done one stays done."""

        now = self._now()
        with self._lock, self._write() as connection:
            known = connection.execute(
                "SELECT done_at FROM desk_app_todos WHERE app = ? AND key = ?", (app, item["key"])
            ).fetchone()
            if known is None:
                open_ = connection.execute(
                    """
                    SELECT COUNT(*) FROM desk_app_todos
                    WHERE app = ? AND assignee = ? AND done_at IS NULL
                    """,
                    (app, item["for"]),
                ).fetchone()[0]
                if open_ >= MAX_OPEN_TODOS:
                    raise AppItemError(
                        429,
                        f"{item['for']} already has {MAX_OPEN_TODOS} open to-dos from this app.",
                    )
            connection.execute(
                """
                INSERT INTO desk_app_todos (app, key, kind, title, assignee, due, ref, url,
                    detail, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(app, key) DO UPDATE SET kind = excluded.kind,
                    title = excluded.title, assignee = excluded.assignee, due = excluded.due,
                    ref = excluded.ref, url = excluded.url, detail = excluded.detail,
                    updated_at = excluded.updated_at
                """,
                (
                    app,
                    item["key"],
                    item["kind"],
                    item["title"],
                    item["for"],
                    item.get("due"),
                    item.get("ref"),
                    item.get("url"),
                    item.get("detail") or "",
                    now,
                    now,
                ),
            )
        return self.todo(app, item["key"]) or {}

    def todo(self, app: str, key: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM desk_app_todos WHERE app = ? AND key = ?", (app, key)
            ).fetchone()
        return None if row is None else self._todo(row)

    def app_todos(self, app: str, state: str = "all", limit: int = 500) -> list[dict[str, Any]]:
        """``app``'s own to-dos (``open``, ``done`` or ``all``), newest change first."""

        where = {"open": " AND done_at IS NULL", "done": " AND done_at IS NOT NULL"}.get(state, "")
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM desk_app_todos WHERE app = ?{where} "
                "ORDER BY updated_at DESC LIMIT ?",
                (app, limit),
            ).fetchall()
        return [self._todo(row) for row in rows]

    def todos_for(
        self, user: str, groups: list[str], *, apps: set[str], done: bool = False, limit: int = 500
    ) -> list[dict[str, Any]]:
        """The apps' to-dos for ``user`` or one of ``groups``, of ``apps`` they may open."""

        if not apps:
            return []
        assignees = [f"user:{user}", *(f"group:{group}" for group in groups)]
        marks_a = ",".join("?" for _ in assignees)
        marks_p = ",".join("?" for _ in apps)
        state = "done_at IS NOT NULL" if done else "done_at IS NULL"
        order = "done_at DESC" if done else "COALESCE(due, '9999'), created_at"
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM desk_app_todos
                WHERE assignee IN ({marks_a}) AND app IN ({marks_p}) AND {state}
                ORDER BY {order} LIMIT ?
                """,
                (*assignees, *sorted(apps), limit),
            ).fetchall()
        return [self._todo(row) for row in rows]

    def complete(self, app: str, key: str, done: bool, actor: str) -> dict[str, Any] | None:
        """Ticked (or unticked) in Desk by ``actor``."""

        with self._lock, self._write() as connection:
            changed = connection.execute(
                """
                UPDATE desk_app_todos SET done_at = ?, done_by = ?, updated_at = ?
                WHERE app = ? AND key = ?
                """,
                (self._now() if done else None, actor if done else None, self._now(), app, key),
            ).rowcount
        return self.todo(app, key) if changed else None

    def remove_todo(self, app: str, key: str) -> bool:
        """The app closed its to-do: gone from everyone's Desk."""

        with self._lock, self._write() as connection:
            return bool(
                connection.execute(
                    "DELETE FROM desk_app_todos WHERE app = ? AND key = ?", (app, key)
                ).rowcount
            )

    def _todo(self, row: Any) -> dict[str, Any]:
        return {
            "app": row["app"],
            "key": row["key"],
            "kind": row["kind"],
            "title": row["title"],
            "for": row["assignee"],
            "due": row["due"],
            "ref": row["ref"],
            "url": row["url"],
            "detail": row["detail"],
            "done": row["done_at"] is not None,
            "done_at": row["done_at"],
            "done_by": row["done_by"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


__all__ = [
    "AppItemError",
    "AppItemStore",
    "audience_matches",
]
