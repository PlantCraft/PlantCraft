"""Follow-up actions: what someone has to do about an asset, a signal or a finding.

An action has a title, an owner (a person) and a group (the team it is assigned to), a
priority, a due date, a status, the references it is about (``asset:FIC-101``,
``run:linkcraft/...``) and a checklist (items with their own owner and due date). Every change
is kept in its history with who made it. Apps never write actions: they
link to PlantCraft's form (``/actions?new=1&ref=...``, docs/collaboration.md).

A **request** (``kind = "request"``) is an action someone asks of the people who keep the suite
running: IT or an integrator's team (docs/operations.md, section 4). It has a ``category``, its
queue is its group, and ``first_response_at`` is when someone other than who asked first answered
(a comment, a status, a change). Time spent on it is logged in hours (``add_hours``), for the
month's report by company. Anyone who signs in may ask (``POST /api/requests``).

Who sees an action (as in Jira's assignee and team): its owner, the person
who created it, the members of its group, and the leaders above them in the group tree
(``GroupStore.scope``); an administrator sees every action. ``Visibility`` carries that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from plantcraft.config import plant_today
from plantcraft.db import Migration, Store, add_columns
from plantcraft.i18n import t
from plantcraft.refs import parse_ref

from .sla import Targets, check_targets, request_sla

# English constants; read them through ``t()``.
# A checklist entry of the history is stored as "<verb>:<item>" and read in the reader's language.
CHECKLIST_VERBS = {
    "added": "Checklist, added: {item}",
    "checked": "Checklist, done: {item}",
    "unchecked": "Checklist, not done: {item}",
    "changed": "Checklist, changed: {item}",
    "removed": "Checklist, removed: {item}",
}
STATUSES = {
    "open": "Open",
    "in_progress": "In progress",
    "blocked": "Blocked",
    "done": "Done",
    # The id stays "cancelled" (API v1, apps); people read "Archived".
    "cancelled": "Archived",
}
OPEN_STATUSES = ("open", "in_progress", "blocked")
PRIORITIES = {"low": "Low", "medium": "Medium", "high": "High", "critical": "Critical"}
KINDS = {"action": "Action", "request": "Request"}
REQUEST_CATEGORIES = {
    "error": "Something is not working",
    "slow": "Slow or overloaded",
    "access": "Access or account",
    "data": "Data or a signal",
    "change": "A change or an improvement",
    "other": "Other",
}
MAX_HOURS = 24.0
MAX_NOTE = 300
MAX_REFS = 12
MAX_TITLE = 200
MAX_TEXT = 4000
MAX_ITEMS = 100
MAX_ITEM_TEXT = 300


# The quick filters of the Actions page (Jira's "Assigned to me", "My team"...).
VIEWS = ("visible", "mine", "groups", "created")


@dataclass(frozen=True)
class Visibility:
    """What one person sees: ``everything`` (an administrator), or actions owned by one of
    ``people``, assigned to one of ``groups`` or created by ``username``."""

    username: str
    everything: bool = False
    people: frozenset[str] = field(default_factory=frozenset)
    groups: frozenset[str] = field(default_factory=frozenset)
    # Actions about assets out of the person's asset scope only (docs/asset-scope.md): hidden
    # unless the person owns or created them.
    out_of_scope: frozenset[int] = field(default_factory=frozenset)
    # Every request too (the Operations role answers them, whatever their queue).
    requests: bool = False

    def sees(self, action: dict[str, Any]) -> bool:
        mine = action.get("created_by") == self.username or action.get("owner") == self.username
        if mine:
            return True
        if action.get("action_id") in self.out_of_scope:
            return False
        return (
            self.everything
            or action.get("owner") in self.people
            or action.get("group_id") in self.groups
            or (self.requests and action.get("kind") == "request")
        )

    def clause(self) -> tuple[str, list[Any]]:
        if self.everything and not self.out_of_scope:
            return "1 = 1", []
        if self.everything:
            hidden = sorted(self.out_of_scope)
            return (
                f"(action.action_id NOT IN ({','.join('?' for _ in hidden)})"
                " OR action.owner = ? OR action.created_by = ?)",
                [*hidden, self.username, self.username],
            )
        people = sorted(self.people | {self.username})
        groups = sorted(self.groups)
        parts = [f"action.owner IN ({','.join('?' for _ in people)})", "action.created_by = ?"]
        values: list[Any] = [*people, self.username]
        if groups:
            parts.append(f"action.group_id IN ({','.join('?' for _ in groups)})")
            values.extend(groups)
        if self.requests:
            parts.append("action.kind = 'request'")
        clause = "(" + " OR ".join(parts) + ")"
        if self.out_of_scope:
            hidden = sorted(self.out_of_scope)
            clause = (
                f"({clause} AND (action.action_id NOT IN ({','.join('?' for _ in hidden)})"
                " OR action.owner = ? OR action.created_by = ?))"
            )
            values.extend([*hidden, self.username, self.username])
        return clause, values


def choices(table: dict[str, str]) -> list[dict[str, str]]:
    return [{"id": key, "label": t(label)} for key, label in table.items()]


def _due(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError as exc:
        raise ValueError(t("The due date must be a date (YYYY-MM-DD).")) from exc


def _category(kind: str, category: str | None) -> str | None:
    """A request's category (``other`` when none is given); an action has none."""

    if kind not in KINDS:
        raise ValueError(t("An action is an action or a request."))
    if kind != "request":
        return None
    if category in (None, ""):
        return "other"
    if category not in REQUEST_CATEGORIES:
        raise ValueError(t("Unknown request category."))
    return category


def _refs(values: list[str] | None) -> list[str]:
    found: list[str] = []
    for value in values or []:
        ref = str(parse_ref(value))
        if ref not in found:
            found.append(ref)
    if len(found) > MAX_REFS:
        raise ValueError(t("An action points at {count} items at most.", count=MAX_REFS))
    return found


def _history_text(kind: str, text: str) -> str:
    if kind == "hours":
        return t("Time logged: {text}", text=text)
    if kind == "status" and text in STATUSES:
        return t(STATUSES[text])
    if kind == "checklist":
        verb, _, item = text.partition(":")
        if verb in CHECKLIST_VERBS:
            return t(CHECKLIST_VERBS[verb], item=item)
    return text


class ActionStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS follow_up_actions (
        action_id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'open',
        priority TEXT NOT NULL DEFAULT 'medium',
        owner TEXT,
        due_at TEXT,
        refs_json TEXT NOT NULL DEFAULT '[]',
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        completed_at TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_follow_up_actions_status
    ON follow_up_actions(status, due_at);

    CREATE TABLE IF NOT EXISTS follow_up_action_refs (
        action_id INTEGER NOT NULL REFERENCES follow_up_actions(action_id) ON DELETE CASCADE,
        ref TEXT NOT NULL,
        PRIMARY KEY (ref, action_id)
    );

    CREATE TABLE IF NOT EXISTS follow_up_action_history (
        entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
        action_id INTEGER NOT NULL REFERENCES follow_up_actions(action_id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        text TEXT NOT NULL,
        actor TEXT NOT NULL,
        created_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_follow_up_action_history
    ON follow_up_action_history(action_id, entry_id);

    CREATE TABLE IF NOT EXISTS follow_up_action_items (
        item_id INTEGER PRIMARY KEY AUTOINCREMENT,
        action_id INTEGER NOT NULL REFERENCES follow_up_actions(action_id) ON DELETE CASCADE,
        text TEXT NOT NULL,
        done INTEGER NOT NULL DEFAULT 0,
        owner TEXT,
        due_at TEXT,
        position INTEGER NOT NULL DEFAULT 0,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        done_by TEXT,
        done_at TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_follow_up_action_items
    ON follow_up_action_items(action_id, position);

    CREATE TABLE IF NOT EXISTS follow_up_action_hours (
        entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
        action_id INTEGER NOT NULL REFERENCES follow_up_actions(action_id) ON DELETE CASCADE,
        username TEXT NOT NULL,
        day TEXT NOT NULL,
        minutes INTEGER NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        billable INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_follow_up_action_hours ON follow_up_action_hours(day);

    -- Requests' service targets by priority (plantcraft.actions.sla); none stored: the defaults.
    CREATE TABLE IF NOT EXISTS follow_up_request_targets (
        priority TEXT PRIMARY KEY,
        response_minutes INTEGER NOT NULL,
        resolution_minutes INTEGER NOT NULL,
        updated_by TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    -- A month's hours approved for a company ('' for the plant's own people): closed to changes.
    CREATE TABLE IF NOT EXISTS follow_up_hours_months (
        month TEXT NOT NULL,
        company TEXT NOT NULL DEFAULT '',
        hours REAL NOT NULL,
        approved_by TEXT NOT NULL,
        approved_at TEXT NOT NULL,
        PRIMARY KEY (month, company)
    );
    """

    MIGRATIONS = (
        Migration(
            "columns-before-0.5",
            add_columns(
                "follow_up_actions",
                {
                    # The group the action is assigned to; NULL: none.
                    "group_id": "TEXT",
                },
            ),
        ),
        # Requests (Operations): the kind, the category and the first answer's time.
        Migration(
            "requests",
            add_columns(
                "follow_up_actions",
                {
                    "kind": "TEXT NOT NULL DEFAULT 'action'",
                    "category": "TEXT",
                    "first_response_at": "TEXT",
                },
            ),
        ),
    )

    def __init__(self, db: Any):
        super().__init__(db)

    @staticmethod
    def _check(title: str, priority: str, status: str = "open") -> str:
        cleaned = (title or "").strip()
        if not cleaned:
            raise ValueError(t("The action title is required."))
        if len(cleaned) > MAX_TITLE:
            raise ValueError(t("The title is longer than {count} characters.", count=MAX_TITLE))
        if priority not in PRIORITIES:
            raise ValueError(t("Invalid action priority."))
        if status not in STATUSES:
            raise ValueError(t("Invalid action status."))
        return cleaned

    def create(
        self,
        *,
        title: str,
        actor: str,
        description: str = "",
        priority: str = "medium",
        owner: str | None = None,
        group_id: str | None = None,
        due_at: str | None = None,
        refs: list[str] | None = None,
        kind: str = "action",
        category: str | None = None,
    ) -> dict[str, Any]:
        cleaned = self._check(title, priority)
        found = _refs(refs)
        due = _due(due_at)
        category = _category(kind, category)
        now = self._now()
        with self._lock, self._write() as connection:
            cursor = connection.execute(
                """
                INSERT INTO follow_up_actions
                (title, description, priority, owner, group_id, due_at, refs_json, created_by,
                 created_at, updated_at, kind, category)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cleaned,
                    (description or "").strip()[:MAX_TEXT],
                    priority,
                    owner or None,
                    group_id or None,
                    due,
                    self._json(found),
                    actor,
                    now,
                    now,
                    kind,
                    category,
                ),
            )
            action_id = int(cursor.lastrowid)
            self._write_refs(connection, action_id, found)
            self._log(connection, action_id, "created", "", actor, now)
        return self.get(action_id) or {}

    def update(
        self,
        action_id: int,
        *,
        actor: str,
        title: str,
        description: str = "",
        priority: str = "medium",
        status: str = "open",
        owner: str | None = None,
        group_id: str | None = None,
        due_at: str | None = None,
        refs: list[str] | None = None,
        category: str | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        """Save every field; returns the action and its previous status when it changed.
        ``category`` None keeps a request's category."""

        current = self.get(action_id)
        if current is None:
            raise KeyError(action_id)
        cleaned = self._check(title, priority, status)
        category = _category(current["kind"], category or current["category"])
        found = _refs(refs)
        due = _due(due_at)
        description = (description or "").strip()[:MAX_TEXT]
        fields = {
            "title": cleaned,
            "description": description,
            "priority": priority,
            "owner": owner or None,
            "group_id": group_id or None,
            "due_at": due,
            "refs": found,
            "category": category,
        }
        changed = [name for name, value in fields.items() if current[name] != value]
        now = self._now()
        completed = current["completed_at"]
        if status != current["status"]:
            completed = now if status in {"done", "cancelled"} else None
        with self._lock, self._write() as connection:
            connection.execute(
                """
                UPDATE follow_up_actions SET title = ?, description = ?, priority = ?, owner = ?,
                    group_id = ?, due_at = ?, refs_json = ?, status = ?, updated_at = ?,
                    completed_at = ?, category = ?
                WHERE action_id = ?
                """,
                (
                    cleaned,
                    description,
                    priority,
                    owner or None,
                    group_id or None,
                    due,
                    self._json(found),
                    status,
                    now,
                    completed,
                    category,
                    action_id,
                ),
            )
            self._write_refs(connection, action_id, found)
            if changed:
                self._log(connection, action_id, "changed", ", ".join(changed), actor, now)
            if status != current["status"]:
                self._log(connection, action_id, "status", status, actor, now)
        previous = current["status"] if status != current["status"] else None
        return self.get(action_id) or {}, previous

    def comment(self, action_id: int, actor: str, text: str) -> None:
        cleaned = (text or "").strip()
        if not cleaned:
            raise ValueError(t("The comment cannot be empty."))
        if len(cleaned) > MAX_TEXT:
            raise ValueError(t("The comment is longer than {count} characters.", count=MAX_TEXT))
        if self.get(action_id) is None:
            raise KeyError(action_id)
        now = self._now()
        with self._lock, self._write() as connection:
            self._log(connection, action_id, "comment", cleaned, actor, now)
            connection.execute(
                "UPDATE follow_up_actions SET updated_at = ? WHERE action_id = ?", (now, action_id)
            )

    @staticmethod
    def _write_refs(connection: Any, action_id: int, refs: list[str]) -> None:
        connection.execute("DELETE FROM follow_up_action_refs WHERE action_id = ?", (action_id,))
        connection.executemany(
            "INSERT OR IGNORE INTO follow_up_action_refs (action_id, ref) VALUES (?, ?)",
            [(action_id, ref) for ref in refs],
        )

    @staticmethod
    def _log(connection: Any, action_id: int, kind: str, text: str, actor: str, now: str) -> None:
        connection.execute(
            "INSERT INTO follow_up_action_history (action_id, kind, text, actor, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (action_id, kind, text, actor, now),
        )
        if kind != "created":
            # A request's first answer: anything done on it by someone other than who asked.
            connection.execute(
                "UPDATE follow_up_actions SET first_response_at = ? WHERE action_id = ? "
                "AND kind = 'request' AND first_response_at IS NULL AND created_by <> ?",
                (now, action_id, actor),
            )

    # Hours ------------------------------------------------------------------

    def add_hours(
        self,
        action_id: int,
        *,
        actor: str,
        hours: float,
        day: str | None = None,
        note: str = "",
        billable: bool = True,
    ) -> dict[str, Any]:
        """Time ``actor`` spent on the action (a request, mostly), in hours on a day."""

        if self.get(action_id) is None:
            raise KeyError(action_id)
        try:
            value = float(hours)
        except (TypeError, ValueError) as exc:
            raise ValueError(t("Hours must be a number.")) from exc
        minutes = round(value * 60)
        if not 0 < minutes <= MAX_HOURS * 60:
            raise ValueError(t("Log between 1 minute and {count} hours.", count=int(MAX_HOURS)))
        when = _due(day) or plant_today()
        if when > plant_today():
            raise ValueError(t("Hours are logged on a day that has started."))
        cleaned = (note or "").strip()[:MAX_NOTE]
        now = self._now()
        with self._lock, self._write() as connection:
            cursor = connection.execute(
                """
                INSERT INTO follow_up_action_hours
                (action_id, username, day, minutes, note, billable, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (action_id, actor, when, minutes, cleaned, int(bool(billable)), now),
            )
            entry_id = int(cursor.lastrowid)
            self._log(connection, action_id, "hours", f"{minutes / 60:g} h {when}", actor, now)
            self._touch(connection, action_id, now)
        return next(item for item in self.hours(action_id) if item["entry_id"] == entry_id)

    def hours(self, action_id: int) -> list[dict[str, Any]]:
        """The time logged on an action, newest day first."""

        return self._hours("entry.action_id = ?", [action_id])

    def delete_hours(self, action_id: int, entry_id: int) -> dict[str, Any]:
        """Removes one entry (the route checks it is the person's own, or an admin's call)."""

        found = [item for item in self.hours(action_id) if item["entry_id"] == entry_id]
        if not found:
            raise KeyError(entry_id)
        with self._lock, self._write() as connection:
            connection.execute("DELETE FROM follow_up_action_hours WHERE entry_id = ?", (entry_id,))
        return found[0]

    def hours_between(self, first: str, last: str) -> list[dict[str, Any]]:
        """Every entry from ``first`` to ``last`` (days, both included), for the month's report."""

        return self._hours("entry.day >= ? AND entry.day <= ?", [first, last])

    def _hours(self, where: str, values: list[Any]) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT entry.*, person.display_name, action.title, action.kind,
                       action.group_id, action.category
                FROM follow_up_action_hours AS entry
                JOIN follow_up_actions AS action ON action.action_id = entry.action_id
                LEFT JOIN workspace_users AS person ON person.username = entry.username
                WHERE {where}
                ORDER BY entry.day DESC, entry.entry_id DESC
                """,
                values,
            ).fetchall()
        return [
            {
                "entry_id": int(row["entry_id"]),
                "action_id": int(row["action_id"]),
                "title": row["title"],
                "kind": row["kind"],
                "group_id": row["group_id"],
                "category": row["category"],
                "username": row["username"],
                "display_name": row["display_name"] or row["username"],
                "day": row["day"],
                "hours": round(int(row["minutes"]) / 60, 2),
                "note": row["note"],
                "billable": bool(row["billable"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    # The checklist ----------------------------------------------------------

    @staticmethod
    def _item_text(text: str) -> str:
        cleaned = (text or "").strip()
        if not cleaned:
            raise ValueError(t("Write the item."))
        if len(cleaned) > MAX_ITEM_TEXT:
            raise ValueError(t("An item is longer than {count} characters.", count=MAX_ITEM_TEXT))
        return cleaned

    def items(self, action_id: int) -> list[dict[str, Any]]:
        """The action's checklist, in order, with the names of the people on it."""

        today = plant_today()
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT item.*, owner.display_name AS owner_name, doer.display_name AS done_by_name
                FROM follow_up_action_items AS item
                LEFT JOIN workspace_users AS owner ON owner.username = item.owner
                LEFT JOIN workspace_users AS doer ON doer.username = item.done_by
                WHERE item.action_id = ? ORDER BY item.position, item.item_id
                """,
                (action_id,),
            ).fetchall()
        found = []
        for row in rows:
            item = dict(row)
            item["done"] = bool(item["done"])
            item["owner_name"] = item["owner_name"] or item["owner"]
            item["done_by_name"] = item["done_by_name"] or item["done_by"]
            item["overdue"] = bool(item["due_at"] and not item["done"] and item["due_at"] < today)
            found.append(item)
        return found

    def add_item(
        self,
        action_id: int,
        *,
        actor: str,
        text: str,
        owner: str | None = None,
        due_at: str | None = None,
    ) -> dict[str, Any]:
        if self.get(action_id) is None:
            raise KeyError(action_id)
        cleaned = self._item_text(text)
        due = _due(due_at)
        now = self._now()
        with self._lock, self._write() as connection:
            count, last = connection.execute(
                "SELECT COUNT(*), COALESCE(MAX(position), 0) FROM follow_up_action_items "
                "WHERE action_id = ?",
                (action_id,),
            ).fetchone()
            if count >= MAX_ITEMS:
                raise ValueError(t("A checklist holds {count} items at most.", count=MAX_ITEMS))
            cursor = connection.execute(
                """
                INSERT INTO follow_up_action_items
                (action_id, text, owner, due_at, position, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (action_id, cleaned, owner or None, due, int(last) + 1, actor, now),
            )
            item_id = int(cursor.lastrowid)
            self._log(connection, action_id, "checklist", f"added:{cleaned}", actor, now)
            self._touch(connection, action_id, now)
        return self._item(action_id, item_id)

    def update_item(
        self, action_id: int, item_id: int, *, actor: str, changes: dict[str, Any]
    ) -> dict[str, Any]:
        """Change an item: ``text``, ``owner``, ``due_at`` or ``done`` (only those given)."""

        current = self._item(action_id, item_id)
        fields: dict[str, Any] = {}
        if "text" in changes:
            fields["text"] = self._item_text(changes["text"])
        if "owner" in changes:
            fields["owner"] = changes["owner"] or None
        if "due_at" in changes:
            fields["due_at"] = _due(changes["due_at"])
        now = self._now()
        if "done" in changes and bool(changes["done"]) != current["done"]:
            done = bool(changes["done"])
            fields.update(
                done=int(done), done_by=actor if done else None, done_at=now if done else None
            )
        fields = {key: value for key, value in fields.items() if current.get(key) != value}
        if not fields:
            return current
        with self._lock, self._write() as connection:
            connection.execute(
                f"UPDATE follow_up_action_items SET {', '.join(f'{key} = ?' for key in fields)} "
                "WHERE item_id = ? AND action_id = ?",
                (*fields.values(), item_id, action_id),
            )
            text = fields.get("text", current["text"])
            verb = ("checked" if fields["done"] else "unchecked") if "done" in fields else "changed"
            self._log(connection, action_id, "checklist", f"{verb}:{text}", actor, now)
            self._touch(connection, action_id, now)
        return self._item(action_id, item_id)

    def delete_item(self, action_id: int, item_id: int, *, actor: str) -> None:
        current = self._item(action_id, item_id)
        now = self._now()
        with self._lock, self._write() as connection:
            connection.execute(
                "DELETE FROM follow_up_action_items WHERE item_id = ? AND action_id = ?",
                (item_id, action_id),
            )
            self._log(connection, action_id, "checklist", f"removed:{current['text']}", actor, now)
            self._touch(connection, action_id, now)

    def _item(self, action_id: int, item_id: int) -> dict[str, Any]:
        found = next((item for item in self.items(action_id) if item["item_id"] == item_id), None)
        if found is None:
            raise KeyError(item_id)
        return found

    @staticmethod
    def _touch(connection: Any, action_id: int, now: str) -> None:
        connection.execute(
            "UPDATE follow_up_actions SET updated_at = ? WHERE action_id = ?", (now, action_id)
        )

    # Reading ----------------------------------------------------------------

    def get(self, action_id: int) -> dict[str, Any] | None:
        rows = self._select("action.action_id = ?", [action_id], 1)
        return rows[0] if rows else None

    def headline(self, action_id: int) -> dict[str, Any] | None:
        """Only the title and status of an action: what a link to it (``#action:42``) shows,
        without the joins and counts of ``get`` (1.8 ms each, a timeline of 100 actions paid
        180 ms; 2026-10-27)."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT title, status FROM follow_up_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
        return dict(row) if row else None

    def list(
        self,
        *,
        statuses: list[str] | None = None,
        owner: str | None = None,
        ref: str | None = None,
        query: str | None = None,
        limit: int = 500,
        visible: Visibility | None = None,
        view: str = "visible",
        group_ids: list[str] | None = None,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        """Actions by the filters given (``kind``: only actions or only requests). ``visible`` keeps those the person sees; ``view`` narrows
        to theirs (``mine``), their groups' (``groups``) or the ones they created
        (``created``)."""

        clauses: list[str] = []
        values: list[Any] = []
        if visible is not None:
            clause, more = visible.clause()
            clauses.append(clause)
            values.extend(more)
            if view == "mine":
                clauses.append("action.owner = ?")
                values.append(visible.username)
            elif view == "created":
                clauses.append("action.created_by = ?")
                values.append(visible.username)
            elif view == "groups":
                groups = sorted(visible.groups) or [""]
                clauses.append(f"action.group_id IN ({','.join('?' for _ in groups)})")
                values.extend(groups)
        if kind:
            clauses.append("action.kind = ?")
            values.append(kind)
        if group_ids:
            clauses.append(f"action.group_id IN ({','.join('?' for _ in group_ids)})")
            values.extend(group_ids)
        if statuses:
            clauses.append(f"action.status IN ({','.join('?' for _ in statuses)})")
            values.extend(statuses)
        if owner:
            clauses.append("action.owner = ?")
            values.append(owner)
        if ref:
            clauses.append(
                "action.action_id IN (SELECT action_id FROM follow_up_action_refs WHERE ref = ?)"
            )
            values.append(ref)
        if query:
            clauses.append("(LOWER(action.title) LIKE ? OR LOWER(action.description) LIKE ?)")
            pattern = f"%{query.strip().lower()}%"
            values.extend([pattern, pattern])
        return self._select(" AND ".join(clauses) or "1 = 1", values, limit)

    def open_count(self, owner: str) -> int:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) FROM follow_up_actions WHERE owner = ? AND status IN "
                f"({','.join('?' for _ in OPEN_STATUSES)})",
                (owner, *OPEN_STATUSES),
            ).fetchone()
        return int(row[0])

    def counts(self, visible: Visibility | None = None) -> dict[str, int]:
        """Actions by status, plus ``overdue``: open ones past their due date (the home page),
        of those ``visible`` keeps."""

        open_list = ",".join("?" for _ in OPEN_STATUSES)
        where, values = visible.clause() if visible is not None else ("1 = 1", [])
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT status, COUNT(*) AS n FROM follow_up_actions AS action WHERE {where} "
                "GROUP BY status",
                values,
            ).fetchall()
            overdue = connection.execute(
                f"SELECT COUNT(*) FROM follow_up_actions AS action WHERE {where} AND "
                f"status IN ({open_list}) AND due_at IS NOT NULL AND due_at < ?",
                (*values, *OPEN_STATUSES, plant_today()),
            ).fetchone()
        found = {status: 0 for status in STATUSES}
        found.update({row["status"]: int(row["n"]) for row in rows})
        found["overdue"] = int(overdue[0])
        return found

    def history(self, action_id: int) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT entry.*, person.display_name AS actor_name
                FROM follow_up_action_history AS entry
                LEFT JOIN workspace_users AS person ON person.username = entry.actor
                WHERE entry.action_id = ? ORDER BY entry.entry_id
                """,
                (action_id,),
            ).fetchall()
        return [
            {
                "kind": row["kind"],
                "text": _history_text(row["kind"], row["text"]),
                "actor": row["actor"],
                "actor_name": row["actor_name"] or row["actor"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def plant_refs(self) -> dict[int, list[str]]:
        """Action id -> the assets and signals it names (``asset:``, ``signal:`` refs)."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT action_id, ref FROM follow_up_action_refs
                WHERE ref LIKE 'asset:%' OR ref LIKE 'signal:%'
                """
            ).fetchall()
        found: dict[int, list[str]] = {}
        for row in rows:
            found.setdefault(int(row["action_id"]), []).append(row["ref"])
        return found

    def visible_ids(self, visible: Visibility) -> set[int]:
        """The ids of every action ``visible`` lets its person see (one query, ids only)."""

        clause, values = visible.clause()
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT action.action_id FROM follow_up_actions AS action WHERE {clause}",
                values,
            ).fetchall()
        return {int(row[0]) for row in rows}

    def _select(self, where: str, values: list[Any], limit: int) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT action.*, owner.display_name AS owner_name,
                       creator.display_name AS created_by_name, grp.name AS group_name,
                       COALESCE((SELECT MAX(entry.created_at) FROM follow_up_action_history AS entry
                                 WHERE entry.action_id = action.action_id AND entry.kind = 'status'),
                                action.created_at) AS status_since,
                       (SELECT COUNT(*) FROM follow_up_action_items AS item
                        WHERE item.action_id = action.action_id) AS checklist_total,
                       (SELECT COUNT(*) FROM follow_up_action_items AS item
                        WHERE item.action_id = action.action_id AND item.done = 1) AS checklist_done,
                       (SELECT COALESCE(SUM(entry.minutes), 0) FROM follow_up_action_hours AS entry
                        WHERE entry.action_id = action.action_id) AS minutes_logged
                FROM follow_up_actions AS action
                LEFT JOIN workspace_users AS owner ON owner.username = action.owner
                LEFT JOIN workspace_users AS creator ON creator.username = action.created_by
                LEFT JOIN user_groups AS grp ON grp.group_id = action.group_id
                WHERE {where}
                ORDER BY CASE action.status WHEN 'blocked' THEN 0 WHEN 'in_progress' THEN 1
                    WHEN 'open' THEN 2 ELSE 3 END,
                    CASE action.priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                    WHEN 'medium' THEN 2 ELSE 3 END,
                    COALESCE(action.due_at, '9999'), action.action_id DESC
                LIMIT ?
                """,
                [*values, limit],
            ).fetchall()
        today = plant_today()
        items = []
        for row in rows:
            item = self._row_with_json(row, {"refs": ("refs_json", [])})
            item["status_label"] = t(STATUSES.get(item["status"], item["status"]))
            item["priority_label"] = t(PRIORITIES.get(item["priority"], item["priority"]))
            item["owner_name"] = item["owner_name"] or item["owner"]
            item["checklist"] = {
                "total": int(item.pop("checklist_total") or 0),
                "done": int(item.pop("checklist_done") or 0),
            }
            item["created_by_name"] = item["created_by_name"] or item["created_by"]
            item["hours_logged"] = round(int(item.pop("minutes_logged") or 0) / 60, 2)
            item["kind_label"] = t(KINDS.get(item["kind"], item["kind"]))
            item["category_label"] = (
                t(REQUEST_CATEGORIES.get(item["category"], item["category"]))
                if item["category"]
                else None
            )
            item["overdue"] = bool(
                item["due_at"] and item["due_at"] < today and item["status"] in OPEN_STATUSES
            )
            items.append(item)
        requests = [item for item in items if item["kind"] == "request"]
        if requests:
            targets = self.targets()
            statuses = self._statuses([int(item["action_id"]) for item in requests])
            for item in requests:
                item["sla"] = request_sla(item, statuses.get(int(item["action_id"]), []), targets)
        return items

    def _statuses(self, action_ids: list[int]) -> dict[int, list[tuple[str, str]]]:
        """Every status change of these actions, oldest first: {id: [(time, status), ...]}."""

        found: dict[int, list[tuple[str, str]]] = {}
        for start in range(0, len(action_ids), 500):
            chunk = action_ids[start : start + 500]
            with self._lock, self._connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT action_id, text, created_at FROM follow_up_action_history
                    WHERE kind = 'status' AND action_id IN ({",".join("?" for _ in chunk)})
                    ORDER BY created_at, entry_id
                    """,
                    chunk,
                ).fetchall()
            for row in rows:
                found.setdefault(int(row["action_id"]), []).append((row["created_at"], row["text"]))
        return found

    # Service targets and the month's approval -------------------------------

    def targets(self) -> Targets:
        """The requests' targets by priority: the stored ones over the defaults."""

        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM follow_up_request_targets").fetchall()
        minutes = dict(Targets.defaults().minutes)
        for row in rows:
            if row["priority"] in minutes:
                minutes[row["priority"]] = (
                    int(row["response_minutes"]),
                    int(row["resolution_minutes"]),
                )
        return Targets(minutes)

    def set_targets(self, payload: dict[str, Any], *, actor: str) -> Targets:
        """Replaces every priority's targets (``check_targets``); ``ValueError`` if invalid."""

        targets = check_targets(payload)
        now = self._now()
        with self._lock, self._write() as connection:
            connection.executemany(
                """
                INSERT INTO follow_up_request_targets
                (priority, response_minutes, resolution_minutes, updated_by, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(priority) DO UPDATE SET response_minutes = excluded.response_minutes,
                    resolution_minutes = excluded.resolution_minutes,
                    updated_by = excluded.updated_by, updated_at = excluded.updated_at
                """,
                [
                    (key, first, second, actor, now)
                    for key, (first, second) in targets.minutes.items()
                ],
            )
        return targets

    def approvals(self, month: str) -> dict[str, dict[str, Any]]:
        """The month's approved hours by company ('' for the plant): who, when, how many."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT approval.*, person.display_name FROM follow_up_hours_months AS approval
                LEFT JOIN workspace_users AS person ON person.username = approval.approved_by
                WHERE approval.month = ?
                """,
                (month,),
            ).fetchall()
        return {
            row["company"]: {
                "month": row["month"],
                "company": row["company"] or None,
                "hours": float(row["hours"]),
                "approved_by": row["approved_by"],
                "approved_by_name": row["display_name"] or row["approved_by"],
                "approved_at": row["approved_at"],
            }
            for row in rows
        }

    def approve_month(
        self, month: str, company: str | None, *, hours: float, actor: str
    ) -> dict[str, Any]:
        """Closes the month's hours of ``company`` (None: the plant's own); ``ValueError`` when
        already approved or the month has not ended."""

        if month >= plant_today()[:7]:
            raise ValueError(t("A month is approved once it has ended."))
        key = company or ""
        if key in self.approvals(month):
            raise ValueError(t("These hours are already approved."))
        with self._lock, self._write() as connection:
            connection.execute(
                """
                INSERT INTO follow_up_hours_months (month, company, hours, approved_by, approved_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (month, key, round(float(hours), 2), actor, self._now()),
            )
        return self.approvals(month)[key]

    def reopen_month(self, month: str, company: str | None) -> dict[str, Any]:
        """Opens an approved month again; ``KeyError`` when it was not approved."""

        key = company or ""
        found = self.approvals(month).get(key)
        if found is None:
            raise KeyError(month)
        with self._lock, self._write() as connection:
            connection.execute(
                "DELETE FROM follow_up_hours_months WHERE month = ? AND company = ?", (month, key)
            )
        return found

    def month_approved(self, day: str, company: str | None) -> bool:
        """Whether the hours of ``day``'s month are approved for ``company``."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM follow_up_hours_months WHERE month = ? AND company = ?",
                (day[:7], company or ""),
            ).fetchone()
        return row is not None
