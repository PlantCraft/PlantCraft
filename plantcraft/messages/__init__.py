"""Conversations between two or more participants, their messages and who read what.

A participant is any workspace user: a person or a specialist (a robot).
Each message may carry references (``kind:id``) to platform objects, so a
conversation can point at a loop, a signal, an action or an execution.
Reading is tracked per participant by the last message id they saw.

A group of people (``plantcraft/groups``) has its own conversation: its
participants follow the group, so whoever joins the group finds it in Messages and whoever
leaves stops receiving it (``sync``, run before anyone reads their conversations).
"""

from __future__ import annotations

import json
from typing import Any

from plantcraft.db import Database, Migration, Store, add_columns
from plantcraft.i18n import t
from plantcraft.refs import find_refs, parse_ref

MAX_TEXT = 4000
MAX_MEMBERS = 100


def _upto(read_upto: dict[int, int] | None) -> str:
    return json.dumps({str(key): int(value) for key, value in (read_upto or {}).items()})


class ConversationStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS conversations (
        conversation_id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL DEFAULT '',
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS conversation_members (
        conversation_id INTEGER NOT NULL,
        username TEXT NOT NULL,
        joined_at TEXT NOT NULL,
        last_read_id INTEGER NOT NULL DEFAULT 0,
        -- A specialist preparing a reply ("thinking…"); cleared when it posts.
        busy_since TEXT,
        PRIMARY KEY(conversation_id, username),
        FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS conversation_messages (
        message_id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id INTEGER NOT NULL,
        author TEXT NOT NULL,
        text TEXT NOT NULL,
        refs_json TEXT NOT NULL DEFAULT '[]',
        meta_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_conversation_members_user
    ON conversation_members(username, conversation_id);

    CREATE INDEX IF NOT EXISTS idx_conversation_messages
    ON conversation_messages(conversation_id, message_id);

    -- The notifications apps sent (notices_for, Desk's feed): only those rows, by conversation
    -- and time. Without it the feed read every message of the person's conversations, a year of
    -- them on each load (storage test 2026-10-31, 620k messages: 9.7 ms -> 0.27 ms a feed).
    CREATE INDEX IF NOT EXISTS idx_conversation_notices
    ON conversation_messages(conversation_id, created_at)
    WHERE json_extract(meta_json, '$.kind') = 'notification';
    """

    MIGRATIONS = (
        Migration(
            "columns-before-0.5",
            add_columns(
                "conversations",
                {
                    # The group whose conversation this is; NULL: an ordinary conversation.
                    "group_id": "TEXT",
                },
            ),
        ),
    )

    def __init__(self, db: Database, users: Any):
        """``users`` is the workspace's ``UserStore`` (who may take part)."""

        super().__init__(db)
        self.users = users
        # The workspace's GroupStore, set once it exists: group conversations follow it.
        self.groups: Any = None

    # A group's conversation ------------------------------------------------

    def for_group(self, group_id: str, name: str, members: list[str]) -> dict[str, Any]:
        """The group's conversation, created the first time, its participants the group's."""

        with self._lock, self._write() as connection:
            row = connection.execute(
                "SELECT conversation_id FROM conversations WHERE group_id = ? "
                "ORDER BY conversation_id LIMIT 1",
                (group_id,),
            ).fetchone()
            now = self._now()
            if row is None:
                cursor = connection.execute(
                    "INSERT INTO conversations (title, created_by, created_at, updated_at, group_id) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (name[:120], "system", now, now, group_id),
                )
                conversation_id = int(cursor.lastrowid)
            else:
                conversation_id = int(row["conversation_id"])
                connection.execute(
                    "UPDATE conversations SET title = ? WHERE conversation_id = ?",
                    (name[:120], conversation_id),
                )
        self._follow(conversation_id, members)
        return self.get(conversation_id) or {}

    def _follow(self, conversation_id: int, members: list[str]) -> None:
        """The participants become ``members``: newcomers start with the history read."""

        names = list(dict.fromkeys(members))
        now = self._now()
        with self._lock, self._write() as connection:
            last = connection.execute(
                "SELECT COALESCE(MAX(message_id), 0) FROM conversation_messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
            marks = ",".join("?" for _ in names) or "''"
            connection.execute(
                f"DELETE FROM conversation_members WHERE conversation_id = ? AND username NOT IN ({marks})",
                [conversation_id, *names],
            )
            connection.executemany(
                "INSERT OR IGNORE INTO conversation_members (conversation_id, username, joined_at, last_read_id) VALUES (?, ?, ?, ?)",
                [(conversation_id, name, now, last) for name in names],
            )

    def group_changed(self, group_id: str, members: list[str] | None) -> None:
        """A group's members changed (``members``) or it was deleted (``None``): its
        conversation follows, or stays as an ordinary conversation of the people in it."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT conversation_id FROM conversations WHERE group_id = ?", (group_id,)
            ).fetchone()
        if row is None:
            return
        if members is None:
            with self._lock, self._write() as connection:
                connection.execute(
                    "UPDATE conversations SET group_id = NULL WHERE conversation_id = ?",
                    (row["conversation_id"],),
                )
            return
        self._follow(int(row["conversation_id"]), members)

    def sync(self, username: str) -> None:
        """``username`` takes part in the conversations of their groups, and only those."""

        if self.groups is None:
            return
        mine = {item["group_id"] for item in self.groups.of(username)}
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT conversation.conversation_id, conversation.group_id,
                       EXISTS (SELECT 1 FROM conversation_members AS member
                               WHERE member.conversation_id = conversation.conversation_id
                                 AND member.username = ?) AS joined
                FROM conversations AS conversation WHERE conversation.group_id IS NOT NULL
                """,
                (username,),
            ).fetchall()
        joining = [
            row["conversation_id"] for row in rows if row["group_id"] in mine and not row["joined"]
        ]
        leaving = [
            row["conversation_id"] for row in rows if row["group_id"] not in mine and row["joined"]
        ]
        if not joining and not leaving:
            return
        now = self._now()
        with self._lock, self._write() as connection:
            for conversation_id in joining:
                last = connection.execute(
                    "SELECT COALESCE(MAX(message_id), 0) FROM conversation_messages WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()[0]
                connection.execute(
                    "INSERT OR IGNORE INTO conversation_members (conversation_id, username, joined_at, last_read_id) VALUES (?, ?, ?, ?)",
                    (conversation_id, username, now, last),
                )
            connection.executemany(
                "DELETE FROM conversation_members WHERE conversation_id = ? AND username = ?",
                [(conversation_id, username) for conversation_id in leaving],
            )

    # Conversations ------------------------------------------------------

    def start(self, creator: str, members: list[str], *, title: str = "") -> dict[str, Any]:
        """Open a conversation; two participants without a title reuse their existing one."""

        names = list(dict.fromkeys([creator, *[name.strip().lower() for name in members if name]]))
        if len(names) < 2:
            raise ValueError(t("Choose at least one person or specialist to talk to."))
        if len(names) > MAX_MEMBERS:
            raise ValueError(
                t("A conversation has at most {count} participants.", count=MAX_MEMBERS)
            )
        for name in names:
            user = self.users.get_user(name)
            if not user or not user.get("active"):
                raise ValueError(t("@{username} is not an active platform user.", username=name))
        title = title.strip()[:120]
        if len(names) == 2 and not title:
            existing = self._direct_between(*names)
            if existing is not None:
                return self.get(existing) or {}
        now = self._now()
        with self._lock, self._write() as connection:
            cursor = connection.execute(
                "INSERT INTO conversations (title, created_by, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (title, creator, now, now),
            )
            conversation_id = int(cursor.lastrowid)
            connection.executemany(
                "INSERT INTO conversation_members (conversation_id, username, joined_at) VALUES (?, ?, ?)",
                [(conversation_id, name, now) for name in names],
            )
        return self.get(conversation_id) or {}

    def _direct_between(self, first: str, second: str) -> int | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT conversation.conversation_id FROM conversations AS conversation
                WHERE conversation.title = ''
                  AND (SELECT COUNT(*) FROM conversation_members AS m
                       WHERE m.conversation_id = conversation.conversation_id) = 2
                  AND EXISTS (SELECT 1 FROM conversation_members AS m
                              WHERE m.conversation_id = conversation.conversation_id AND m.username = ?)
                  AND EXISTS (SELECT 1 FROM conversation_members AS m
                              WHERE m.conversation_id = conversation.conversation_id AND m.username = ?)
                ORDER BY conversation.conversation_id LIMIT 1
                """,
                (first, second),
            ).fetchone()
        return int(row["conversation_id"]) if row else None

    def add_members(self, conversation_id: int, members: list[str]) -> dict[str, Any]:
        current = set(self.member_names(conversation_id))
        new = [
            name.strip().lower() for name in members if name and name.strip().lower() not in current
        ]
        if len(current) + len(new) > MAX_MEMBERS:
            raise ValueError(
                t("A conversation has at most {count} participants.", count=MAX_MEMBERS)
            )
        for name in new:
            user = self.users.get_user(name)
            if not user or not user.get("active"):
                raise ValueError(t("@{username} is not an active platform user.", username=name))
        now = self._now()
        with self._lock, self._write() as connection:
            # Newcomers start with the history already read.
            last = connection.execute(
                "SELECT COALESCE(MAX(message_id), 0) FROM conversation_messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
            connection.executemany(
                "INSERT OR IGNORE INTO conversation_members (conversation_id, username, joined_at, last_read_id) VALUES (?, ?, ?, ?)",
                [(conversation_id, name, now, last) for name in new],
            )
        return self.get(conversation_id) or {}

    def is_member(self, conversation_id: int, username: str) -> bool:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM conversation_members WHERE conversation_id = ? AND username = ?",
                (conversation_id, username),
            ).fetchone()
        return row is not None

    def member_names(self, conversation_id: int) -> list[str]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT username FROM conversation_members WHERE conversation_id = ? ORDER BY joined_at, username",
                (conversation_id,),
            ).fetchall()
        return [row["username"] for row in rows]

    def get(
        self,
        conversation_id: int,
        *,
        viewer: str | None = None,
        read_upto: dict[int, int] | None = None,
    ) -> dict[str, Any] | None:
        items = self._conversations(
            "conversation.conversation_id = ?", [conversation_id], viewer, read_upto=read_upto
        )
        return items[0] if items else None

    def list_for(
        self, username: str, *, limit: int = 200, read_upto: dict[int, int] | None = None
    ) -> list[dict[str, Any]]:
        """The user's conversations, most recent activity first. ``read_upto``: what a public
        demo visit read on top of the account's own marks (conversation id: message id)."""

        self.sync(username)
        return self._conversations(
            "conversation.conversation_id IN (SELECT conversation_id FROM conversation_members WHERE username = ?)",
            [username],
            username,
            limit=limit,
            read_upto=read_upto,
        )

    def about(self, username: str, ref: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """The user's conversations where a message cites ``ref``, most recent first."""

        return self._conversations(
            """conversation.conversation_id IN (
                SELECT member.conversation_id FROM conversation_members AS member
                WHERE member.username = ?)
              AND EXISTS (
                SELECT 1 FROM conversation_messages AS cited, json_each(cited.refs_json) AS item
                WHERE cited.conversation_id = conversation.conversation_id AND item.value = ?)""",
            [username, ref],
            username,
            limit=limit,
        )

    def _conversations(
        self,
        where: str,
        parameters: list[Any],
        viewer: str | None,
        *,
        limit: int = 200,
        read_upto: dict[int, int] | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT conversation.*,
                       last.message_id AS last_message_id, last.author AS last_author,
                       last.text AS last_text, last.created_at AS last_at,
                       last_user.display_name AS last_author_name
                FROM conversations AS conversation
                LEFT JOIN conversation_messages AS last ON last.message_id = (
                    SELECT MAX(message_id) FROM conversation_messages
                    WHERE conversation_id = conversation.conversation_id)
                LEFT JOIN workspace_users AS last_user ON last_user.username = last.author
                WHERE {where}
                ORDER BY COALESCE(last.created_at, conversation.updated_at) DESC, conversation.conversation_id DESC
                LIMIT ?
                """,
                [*parameters, limit],
            ).fetchall()
            ids = [row["conversation_id"] for row in rows]
            members: dict[int, list[dict[str, Any]]] = {}
            unread: dict[int, int] = {}
            if ids:
                marks = ",".join("?" for _ in ids)
                for member in connection.execute(
                    f"""
                    SELECT member.conversation_id, member.username, member.last_read_id, member.busy_since,
                           person.display_name, person.role, person.kind, person.active
                    FROM conversation_members AS member
                    LEFT JOIN workspace_users AS person ON person.username = member.username
                    WHERE member.conversation_id IN ({marks})
                    ORDER BY member.joined_at, member.username
                    """,
                    ids,
                ):
                    members.setdefault(member["conversation_id"], []).append(
                        {
                            "username": member["username"],
                            "display_name": member["display_name"] or member["username"],
                            "role": member["role"] or "",
                            "kind": member["kind"] or "person",
                            "active": bool(member["active"]),
                            "last_read_id": member["last_read_id"],
                            "busy": bool(member["busy_since"]),
                        }
                    )
                if viewer:
                    for row in connection.execute(
                        f"""
                        SELECT message.conversation_id, COUNT(*) AS total
                        FROM conversation_messages AS message
                        JOIN conversation_members AS member
                          ON member.conversation_id = message.conversation_id AND member.username = ?
                        LEFT JOIN json_each(?) AS upto
                          ON upto.key = CAST(message.conversation_id AS TEXT)
                        WHERE message.conversation_id IN ({marks})
                          AND message.message_id > MAX(member.last_read_id, COALESCE(upto.value, 0))
                          AND message.author != ?
                        GROUP BY message.conversation_id
                        """,
                        [viewer, _upto(read_upto), *ids, viewer],
                    ):
                        unread[row["conversation_id"]] = int(row["total"])
        result = []
        for row in rows:
            item = dict(row)
            cid = item["conversation_id"]
            item["members"] = members.get(cid, [])
            item["unread"] = unread.get(cid, 0)
            item["is_group"] = (
                len(item["members"]) > 2 or bool(item["title"]) or bool(item.get("group_id"))
            )
            item["last_message"] = (
                {
                    "message_id": item.pop("last_message_id"),
                    "author": item.pop("last_author"),
                    "author_name": item.pop("last_author_name"),
                    "text": item.pop("last_text"),
                    "created_at": item.pop("last_at"),
                }
                if item.get("last_message_id")
                else None
            )
            for key in (
                "last_message_id",
                "last_author",
                "last_author_name",
                "last_text",
                "last_at",
            ):
                item.pop(key, None)
            result.append(item)
        return result

    # Messages -----------------------------------------------------------

    def post(
        self,
        conversation_id: int,
        author: str,
        text: str,
        *,
        refs: list[str] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cleaned = (text or "").strip()
        if not cleaned:
            raise ValueError(t("The message cannot be empty."))
        if len(cleaned) > MAX_TEXT:
            raise ValueError(t("The message is longer than {count} characters.", count=MAX_TEXT))
        if not self.is_member(conversation_id, author):
            raise PermissionError(t("You are not part of this conversation."))
        found: list[str] = []
        for ref in [*(refs or []), *find_refs(cleaned)]:
            try:
                value = str(parse_ref(ref))
            except ValueError:
                continue
            if value not in found:
                found.append(value)
        now = self._now()
        with self._lock, self._write() as connection:
            cursor = connection.execute(
                """
                INSERT INTO conversation_messages (conversation_id, author, text, refs_json, meta_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    author,
                    cleaned,
                    self._json(found[:12]),
                    self._json(meta or {}),
                    now,
                ),
            )
            message_id = int(cursor.lastrowid)
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                (now, conversation_id),
            )
            # Writing a message means everything before it was seen.
            connection.execute(
                "UPDATE conversation_members SET last_read_id = ? WHERE conversation_id = ? AND username = ?",
                (message_id, conversation_id, author),
            )
        return self.message(message_id) or {}

    def message(self, message_id: int) -> dict[str, Any] | None:
        rows = self._messages("message.message_id = ?", [message_id], 1)
        return rows[0] if rows else None

    def messages(
        self, conversation_id: int, *, after: int = 0, before: int | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Messages oldest first: the newest ``limit`` ones, or those after a known id."""

        where = "message.conversation_id = ? AND message.message_id > ?"
        parameters: list[Any] = [conversation_id, after]
        if before is not None:
            where += " AND message.message_id < ?"
            parameters.append(before)
        return self._messages(where, parameters, limit)

    def _messages(self, where: str, parameters: list[Any], limit: int) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT message.*, author.display_name AS author_name, author.kind AS author_kind
                FROM conversation_messages AS message
                LEFT JOIN workspace_users AS author ON author.username = message.author
                WHERE {where}
                ORDER BY message.message_id DESC LIMIT ?
                """,
                [*parameters, limit],
            ).fetchall()[::-1]
        return [
            self._row_with_json(row, {"refs": ("refs_json", []), "meta": ("meta_json", {})})
            for row in rows
        ]

    # Reading ------------------------------------------------------------

    def mark_read(self, conversation_id: int, username: str, message_id: int | None = None) -> None:
        with self._lock, self._write() as connection:
            if message_id is None:
                message_id = connection.execute(
                    "SELECT COALESCE(MAX(message_id), 0) FROM conversation_messages WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()[0]
            connection.execute(
                """
                UPDATE conversation_members SET last_read_id = MAX(last_read_id, ?)
                WHERE conversation_id = ? AND username = ?
                """,
                (message_id, conversation_id, username),
            )

    def set_read(self, conversation_id: int, username: str, message_id: int) -> None:
        """Read up to ``message_id`` exactly, earlier too (the demo seed leaves a few unread)."""

        with self._lock, self._write() as connection:
            connection.execute(
                "UPDATE conversation_members SET last_read_id = ? WHERE conversation_id = ? AND username = ?",
                (message_id, conversation_id, username),
            )

    def unread_total(
        self,
        username: str,
        *,
        chats_only: bool = False,
        read_upto: dict[int, int] | None = None,
    ) -> int:
        """Messages the user has not read; ``chats_only`` leaves out what apps' robots post
        (notifications, which Messages lists apart and counts with their own read marks);
        ``read_upto`` as in ``list_for``."""

        self.sync(username)
        robots = (
            " AND COALESCE((SELECT kind FROM workspace_users WHERE username = message.author), '') != 'system'"
            if chats_only
            else ""
        )
        with self._lock, self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT COUNT(*) FROM conversation_messages AS message
                JOIN conversation_members AS member
                  ON member.conversation_id = message.conversation_id AND member.username = ?
                LEFT JOIN json_each(?) AS upto ON upto.key = CAST(message.conversation_id AS TEXT)
                WHERE message.message_id > MAX(member.last_read_id, COALESCE(upto.value, 0))
                  AND message.author != ?{robots}
                """,
                (username, _upto(read_upto), username),
            ).fetchone()
        return int(row[0])

    def notices_for(self, username: str, *, since: str, limit: int = 500) -> list[dict[str, Any]]:
        """The notifications apps sent the user (``meta.kind`` "notification") since a time, newest
        first, each with ``read``: whether the user had read it in the conversation."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT message.*, author.display_name AS author_name, author.kind AS author_kind,
                       message.message_id <= member.last_read_id AS was_read
                FROM conversation_messages AS message
                JOIN conversation_members AS member
                  ON member.conversation_id = message.conversation_id AND member.username = ?
                LEFT JOIN workspace_users AS author ON author.username = message.author
                WHERE message.created_at >= ? AND message.author != ?
                  AND json_extract(message.meta_json, '$.kind') = 'notification'
                ORDER BY message.message_id DESC LIMIT ?
                """,
                (username, since, username, limit),
            ).fetchall()
        found = []
        for row in rows:
            item = self._row_with_json(row, {"refs": ("refs_json", []), "meta": ("meta_json", {})})
            item["read"] = bool(item.pop("was_read"))
            found.append(item)
        return found

    # Specialists replying -------------------------------------------------

    def set_busy(self, conversation_id: int, username: str, busy: bool) -> None:
        with self._lock, self._write() as connection:
            connection.execute(
                "UPDATE conversation_members SET busy_since = ? WHERE conversation_id = ? AND username = ?",
                (self._now() if busy else None, conversation_id, username),
            )

    def clear_busy(self) -> int:
        """After a restart nobody is still typing."""

        with self._lock, self._write() as connection:
            cursor = connection.execute(
                "UPDATE conversation_members SET busy_since = NULL WHERE busy_since IS NOT NULL"
            )
        return cursor.rowcount
