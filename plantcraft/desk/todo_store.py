"""``DeskStore``'s to-dos and their lists, and the routines of before round 7 made to-dos.
Part of ``DeskStore`` (``plantcraft.desk``)."""

from __future__ import annotations

from datetime import date
from typing import Any

from plantcraft.config import plant_today
from plantcraft.desk.calendar import MAX_NOTES
from plantcraft.desk.common import (
    COLORS,
    MAX_LISTS,
    MAX_STEPS,
    MAX_TITLE,
    MAX_TODOS,
    _clean_title,
    _day,
)
from plantcraft.desk.todos import TODO_REPEATS, next_due
from plantcraft.i18n import t


class TodoStore:
    """``DeskStore``'s to-dos and lists."""

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
