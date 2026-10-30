"""Groups of people, shared by every app of the suite (docs/groups.md).

A group is a name for several people: "Unit 100 operations", "Instrumentation and control".
Apps send notifications to a group, filter by it or make it the owner of their objects, and
never keep a copy: they read it through API v1 (``group:<id>``). A group has a kind (a
department, an area of the plant, an engineering discipline or a team), may point at the asset it
covers, and may have a coordinator, who manages its members without being an administrator.

Groups form a tree (owner, 2026-10-23): each may sit under a parent group ("Operations" >
"U-100 operations" > "Shift A"). The coordinator leads the group, and a leader sees the work of
their group and of every group below it (``scope``: actions use it). A person may be in several
groups.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from typing import Any, TypeVar

from plantcraft.db import Database, Migration, Store, add_columns
from plantcraft.i18n import t

GROUP_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,59}$")
KINDS = ("department", "area", "discipline", "team")
MAX_DEPTH = 8
MAX_MEMBERS = 500
MAX_DESCRIPTION = 500


def kind_labels() -> dict[str, str]:
    return {
        "department": t("Department"),
        "area": t("Area"),
        "discipline": t("Discipline"),
        "team": t("Team"),
    }


def _scope(raw: str | None) -> list[str] | None:
    """A stored asset scope: the root ids, or None (no limit)."""

    try:
        value = json.loads(raw) if raw else None
    except ValueError:
        return None
    return [str(item) for item in value] if isinstance(value, list) else None


_Method = TypeVar("_Method", bound=Callable[..., Any])


def _membership_change(method: _Method) -> _Method:
    """A write to who is in which group: see ``GroupStore._scope_watch``."""

    @wraps(method)
    def watched(self: GroupStore, *args: Any, **kwargs: Any) -> Any:
        with self._scope_watch():
            return method(self, *args, **kwargs)

    return watched  # type: ignore[return-value]


def slug(name: str) -> str:
    """A group id from its name: "Unit 100 operations" -> "unit-100-operations"."""

    text = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return text[:60].rstrip("-") or "group"


class GroupStore(Store):
    """Groups and their members (people by username)."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS user_groups (
        group_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'team',
        description TEXT NOT NULL DEFAULT '',
        asset_id TEXT,
        coordinator TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS user_group_members (
        group_id TEXT NOT NULL,
        username TEXT NOT NULL,
        added_at TEXT NOT NULL,
        PRIMARY KEY (group_id, username),
        FOREIGN KEY (group_id) REFERENCES user_groups(group_id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_user_group_members_user ON user_group_members(username);
    """

    MIGRATIONS = (
        Migration(
            "columns-before-0.5",
            add_columns(
                "user_groups",
                {
                    # NULL: a group at the top of the tree.
                    "parent_id": "TEXT",
                },
            ),
        ),
        # The roots of the asset tree the members see (docs/asset-scope.md); NULL: no limit.
        Migration("asset-scope", add_columns("user_groups", {"asset_scope_json": "TEXT"})),
    )

    def __init__(self, db: Database, users: Any):
        """``users`` is the workspace's ``UserStore`` (who may be a member)."""

        super().__init__(db)
        self.users = users

    # Reading ---------------------------------------------------------------------------

    def list(self) -> list[dict[str, Any]]:
        """Every group by name, with its members (active people first by name)."""

        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM user_groups ORDER BY name COLLATE NOCASE")
            groups = [dict(row) for row in rows]
            members = connection.execute(
                """
                SELECT member.group_id, member.username, person.display_name, person.active
                FROM user_group_members AS member
                LEFT JOIN workspace_users AS person ON person.username = member.username
                ORDER BY person.display_name COLLATE NOCASE, member.username
                """
            ).fetchall()
        by_group: dict[str, list[dict[str, Any]]] = {}
        for row in members:
            by_group.setdefault(row["group_id"], []).append(
                {
                    "username": row["username"],
                    "display_name": row["display_name"] or row["username"],
                    "active": bool(row["active"]),
                }
            )
        labels = kind_labels()
        names = {group["group_id"]: group["name"] for group in groups}
        children: dict[str, list[str]] = {}
        for group in groups:
            if group["parent_id"] in names:
                children.setdefault(group["parent_id"], []).append(group["group_id"])
        for group in groups:
            group["asset_scope"] = _scope(group.pop("asset_scope_json", None))
            group["kind_label"] = labels.get(group["kind"], group["kind"])
            group["members"] = by_group.get(group["group_id"], [])
            if group["parent_id"] not in names:
                group["parent_id"] = None
            group["parent_name"] = names.get(group["parent_id"] or "")
            group["children"] = children.get(group["group_id"], [])
            coordinator = (
                self.users.get_user(group["coordinator"]) if group["coordinator"] else None
            )
            group["coordinator_name"] = (coordinator or {}).get("display_name")
        return groups

    def get(self, group_id: str) -> dict[str, Any] | None:
        return next((group for group in self.list() if group["group_id"] == group_id), None)

    def of(self, username: str) -> list[dict[str, Any]]:
        """The groups ``username`` belongs to (id, name, kind), by name."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT grp.group_id, grp.name, grp.kind, grp.coordinator, grp.parent_id
                FROM user_groups AS grp
                JOIN user_group_members AS member ON member.group_id = grp.group_id
                WHERE member.username = ?
                ORDER BY grp.name COLLATE NOCASE
                """,
                (username,),
            ).fetchall()
        labels = kind_labels()
        return [
            {
                "group_id": row["group_id"],
                "name": row["name"],
                "kind": row["kind"],
                "kind_label": labels.get(row["kind"], row["kind"]),
                "coordinator": row["coordinator"] == username,
                "parent_id": row["parent_id"],
            }
            for row in rows
        ]

    # Asset scope (docs/asset-scope.md) ----------------------------------------------------

    def asset_scopes_of(self, username: str) -> list[list[str]]:
        """The asset scopes of the groups ``username`` is in that have one (a group without a
        scope adds nothing: it never widens what a person sees)."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT grp.asset_scope_json FROM user_groups AS grp
                JOIN user_group_members AS member ON member.group_id = grp.group_id
                WHERE member.username = ? AND grp.asset_scope_json IS NOT NULL
                """,
                (username,),
            ).fetchall()
        return [found for row in rows if (found := _scope(row[0])) is not None]

    def set_asset_scope(self, group_id: str, roots: list[str] | None) -> dict[str, Any]:
        """The assets the group's members see: ``roots`` and everything under them (``None``:
        the group limits nothing). The roots are checked by the caller, which knows the tree."""

        group = self.get(group_id)
        if group is None:
            raise LookupError(group_id)
        cleaned = None if roots is None else sorted(set(roots))
        if cleaned != group["asset_scope"]:
            with self._lock, self._write() as connection:
                connection.execute(
                    "UPDATE user_groups SET asset_scope_json = ?, updated_at = ? WHERE group_id = ?",
                    (None if cleaned is None else json.dumps(cleaned), self._now(), group_id),
                )
            # Members' tokens carry the scope: the ones issued before the change must go.
            for member in group["members"]:
                self.users.revoke_tokens(member["username"])
        return self.get(group_id) or {}

    def _scoped_memberships(self) -> dict[str, set[str]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT member.username, member.group_id FROM user_group_members AS member
                JOIN user_groups AS grp ON grp.group_id = member.group_id
                WHERE grp.asset_scope_json IS NOT NULL
                """
            ).fetchall()
        found: dict[str, set[str]] = {}
        for row in rows:
            found.setdefault(row["username"], set()).add(row["group_id"])
        return found

    @contextmanager
    def _scope_watch(self) -> Iterator[None]:
        """Joining or leaving a group with an asset scope changes what a person sees: their
        tokens, which carry it, end."""

        before = self._scoped_memberships()
        yield
        after = self._scoped_memberships()
        for username in set(before) | set(after):
            if before.get(username, set()) != after.get(username, set()):
                self.users.revoke_tokens(username)

    # The tree ----------------------------------------------------------------------------

    def _parents(self) -> dict[str, str | None]:
        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT group_id, parent_id FROM user_groups").fetchall()
        return {row["group_id"]: row["parent_id"] for row in rows}

    @staticmethod
    def _below(parents: dict[str, str | None], roots: set[str]) -> set[str]:
        """``roots`` and every group under them."""

        found = set(roots) & set(parents)
        frontier = set(found)
        while frontier:
            frontier = {child for child, parent in parents.items() if parent in frontier} - found
            found |= frontier
        return found

    def descendants(self, group_id: str) -> set[str]:
        """The group and every group under it."""

        return self._below(self._parents(), {group_id})

    def ancestors(self, group_id: str) -> list[str]:
        """The groups above, nearest first."""

        parents = self._parents()
        found: list[str] = []
        current = parents.get(group_id)
        while current and current in parents and current not in found and current != group_id:
            found.append(current)
            current = parents.get(current)
        return found

    def scope(self, username: str) -> dict[str, set[str]]:
        """What ``username`` sees of other people's work: ``groups`` (theirs, and every group
        under one they lead) and ``people`` (themselves and everyone in a group they lead or
        below it)."""

        parents = self._parents()
        with self._lock, self._connect() as connection:
            mine = {
                row["group_id"]
                for row in connection.execute(
                    "SELECT group_id FROM user_group_members WHERE username = ?", (username,)
                )
            }
            led = {
                row["group_id"]
                for row in connection.execute(
                    "SELECT group_id FROM user_groups WHERE coordinator = ?", (username,)
                )
            }
            below = self._below(parents, led)
            people = {username}
            if below:
                marks = ",".join("?" for _ in below)
                people |= {
                    row["username"]
                    for row in connection.execute(
                        f"SELECT username FROM user_group_members WHERE group_id IN ({marks})",
                        list(below),
                    )
                }
        return {"groups": mine | below, "people": people, "led": below}

    @_membership_change
    def set_groups_of(self, username: str, group_ids: list[str]) -> list[dict[str, Any]]:
        """The groups a person is in (People › edit): joins the new ones, leaves the others,
        except a group they coordinate (an administrator changes the coordinator first)."""

        wanted = list(dict.fromkeys(group_ids))
        parents = self._parents()
        unknown = [group_id for group_id in wanted if group_id not in parents]
        if unknown:
            raise ValueError(t("Group not found: {group}.", group=unknown[0]))
        if not self.users.is_person(username):
            raise ValueError(t("User not found: {username}.", username=username))
        now = self._now()
        with self._lock, self._write() as connection:
            led = {
                row["group_id"]
                for row in connection.execute(
                    "SELECT group_id FROM user_groups WHERE coordinator = ?", (username,)
                )
            }
            keep = set(wanted) | led
            marks = ",".join("?" for _ in keep) or "''"
            connection.execute(
                f"DELETE FROM user_group_members WHERE username = ? AND group_id NOT IN ({marks})",
                [username, *keep],
            )
            connection.executemany(
                "INSERT OR IGNORE INTO user_group_members (group_id, username, added_at) VALUES (?, ?, ?)",
                [(group_id, username, now) for group_id in keep],
            )
        return self.of(username)

    def memberships(self) -> dict[str, list[str]]:
        """Username -> ids of their groups, for everyone in a group."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT username, group_id FROM user_group_members ORDER BY group_id"
            ).fetchall()
        found: dict[str, list[str]] = {}
        for row in rows:
            found.setdefault(row["username"], []).append(row["group_id"])
        return found

    def members(self, group_id: str, *, active_only: bool = True) -> list[str]:
        """Usernames of the group's people (the active ones by default)."""

        group = self.get(group_id)
        if group is None:
            return []
        return [
            member["username"] for member in group["members"] if member["active"] or not active_only
        ]

    # Writing ---------------------------------------------------------------------------

    def _check_parent(self, group_id: str | None, parent_id: str | None) -> str | None:
        """The parent must exist, not be the group itself or below it, and keep the tree
        shallow enough to read."""

        parent_id = (parent_id or "").strip().lower() or None
        if parent_id is None:
            return None
        parents = self._parents()
        if parent_id not in parents:
            raise ValueError(t("Group not found: {group}.", group=parent_id))
        if group_id and parent_id in self._below(parents, {group_id}):
            raise ValueError(t("A group cannot sit under itself or under a group below it."))
        if len(self.ancestors(parent_id)) + 2 > MAX_DEPTH:
            raise ValueError(t("Groups go {count} levels deep at most.", count=MAX_DEPTH))
        return parent_id

    def _check(
        self,
        name: str,
        kind: str,
        description: str,
        coordinator: str | None,
        members: list[str],
    ) -> tuple[str, str, str, str | None, list[str]]:
        name = (name or "").strip()
        if not name or len(name) > 120:
            raise ValueError(t("A group needs a name of 1 to 120 characters."))
        if kind not in KINDS:
            raise ValueError(t("A group's kind is department, area, discipline or team."))
        description = (description or "").strip()
        if len(description) > MAX_DESCRIPTION:
            raise ValueError(
                t("The description is longer than {count} characters.", count=MAX_DESCRIPTION)
            )
        names = list(dict.fromkeys(item.strip().lower() for item in members if item.strip()))
        if len(names) > MAX_MEMBERS:
            raise ValueError(t("A group has at most {count} members.", count=MAX_MEMBERS))
        coordinator = (coordinator or "").strip().lower() or None
        for username in [*names, *([coordinator] if coordinator else [])]:
            if not self.users.is_person(username):
                raise ValueError(t("User not found: {username}.", username=username))
        if coordinator and coordinator not in names:
            names.append(coordinator)
        return name, kind, description, coordinator, names

    def create(
        self,
        name: str,
        *,
        group_id: str | None = None,
        kind: str = "team",
        description: str = "",
        asset_id: str | None = None,
        coordinator: str | None = None,
        members: list[str] | None = None,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        name, kind, description, coordinator, names = self._check(
            name, kind, description, coordinator, members or []
        )
        group_id = (group_id or "").strip().lower() or slug(name)
        if not GROUP_ID.match(group_id):
            raise ValueError(
                t("A group id is lower-case letters, digits, dot, dash or underscore.")
            )
        if self.get(group_id) is not None:
            raise KeyError(group_id)
        parent = self._check_parent(None, parent_id)
        now = self._now()
        with self._lock, self._write() as connection:
            connection.execute(
                """
                INSERT INTO user_groups
                (group_id, name, kind, description, asset_id, coordinator, parent_id,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    group_id,
                    name,
                    kind,
                    description,
                    (asset_id or "").strip() or None,
                    coordinator,
                    parent,
                    now,
                    now,
                ),
            )
            connection.executemany(
                "INSERT INTO user_group_members (group_id, username, added_at) VALUES (?, ?, ?)",
                [(group_id, username, now) for username in names],
            )
        return self.get(group_id) or {}

    def update(
        self,
        group_id: str,
        *,
        name: str,
        kind: str,
        description: str = "",
        asset_id: str | None = None,
        coordinator: str | None = None,
        members: list[str],
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        if self.get(group_id) is None:
            raise LookupError(group_id)
        name, kind, description, coordinator, names = self._check(
            name, kind, description, coordinator, members
        )
        parent = self._check_parent(group_id, parent_id)
        with self._lock, self._write() as connection:
            connection.execute(
                """
                UPDATE user_groups SET name = ?, kind = ?, description = ?, asset_id = ?,
                    coordinator = ?, parent_id = ?, updated_at = ?
                WHERE group_id = ?
                """,
                (
                    name,
                    kind,
                    description,
                    (asset_id or "").strip() or None,
                    coordinator,
                    parent,
                    self._now(),
                    group_id,
                ),
            )
        self._set_members(group_id, names)
        return self.get(group_id) or {}

    def set_members(self, group_id: str, members: list[str]) -> dict[str, Any]:
        """The members a coordinator chose; the coordinator stays one of them."""

        group = self.get(group_id)
        if group is None:
            raise LookupError(group_id)
        *_, names = self._check(
            group["name"], group["kind"], group["description"], group["coordinator"], members
        )
        self._set_members(group_id, names)
        return self.get(group_id) or {}

    @_membership_change
    def add_member(self, group_id: str, username: str) -> None:
        """One more person in the group (the company directory's sign-in keeps groups in step)."""

        now = self._now()
        with self._lock, self._write() as connection:
            if not connection.execute(
                "SELECT 1 FROM user_groups WHERE group_id = ?", (group_id,)
            ).fetchone():
                return
            connection.execute(
                "INSERT OR IGNORE INTO user_group_members (group_id, username, added_at) VALUES (?, ?, ?)",
                (group_id, username, now),
            )

    @_membership_change
    def remove_member(self, group_id: str, username: str) -> None:
        """The person leaves the group, unless they coordinate it (an admin changes that)."""

        with self._lock, self._write() as connection:
            connection.execute(
                """
                DELETE FROM user_group_members WHERE group_id = ? AND username = ?
                AND username IS NOT (SELECT coordinator FROM user_groups WHERE group_id = ?)
                """,
                (group_id, username, group_id),
            )

    @_membership_change
    def _set_members(self, group_id: str, names: list[str]) -> None:
        now = self._now()
        marks = ",".join("?" for _ in names) or "''"
        with self._lock, self._write() as connection:
            connection.execute(
                f"DELETE FROM user_group_members WHERE group_id = ? AND username NOT IN ({marks})",
                [group_id, *names],
            )
            connection.executemany(
                "INSERT OR IGNORE INTO user_group_members (group_id, username, added_at) VALUES (?, ?, ?)",
                [(group_id, username, now) for username in names],
            )
            connection.execute(
                "UPDATE user_groups SET updated_at = ? WHERE group_id = ?", (now, group_id)
            )

    @_membership_change
    def delete(self, group_id: str) -> bool:
        """The group goes; the groups under it move up to its parent."""

        parent = self._parents().get(group_id)
        with self._lock, self._write() as connection:
            connection.execute(
                "UPDATE user_groups SET parent_id = ? WHERE parent_id = ?", (parent, group_id)
            )
            connection.execute("DELETE FROM user_group_members WHERE group_id = ?", (group_id,))
            cursor = connection.execute("DELETE FROM user_groups WHERE group_id = ?", (group_id,))
        return cursor.rowcount > 0
