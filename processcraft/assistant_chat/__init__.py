"""The assistant's chats in Desk (owner, 2026-10-23): each person's own conversations with a
language model, apart from Messages, which stay between people.

A person keeps many chats, each on its own subject: a text to translate or correct, a question
about the plant ("plot FIC-101 yesterday", "which loops are worst?"). The model reads the plant
only through read-only tools that call API v1 with a token issued for that person, so it sees
exactly what the person sees (``engine.py``). Nothing here writes anything but the chat itself.

Tables (this module owns them): ``assistant_chats`` and ``assistant_chat_messages``. An answer
keeps the steps the model took (each tool call, as the person can read it), the charts it drew
(the values come from the plant's history, never from the model) and the references it read.

A chat opened from the assistant's side panel in a page (owner, 2026-10-23: "Ask the assistant"
beside a result, an alarm, an asset) carries that place's ``context`` for the model and is not
kept (``kept = 0``): it is not listed in Desk and is deleted a day later, unless the person
continues it in Desk (``keep``).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from processcraft.db import Migration, Store, add_columns, utc_text
from processcraft.i18n import t

MAX_TITLE = 120
MAX_TEXT = 8000
MAX_CHATS = 500
# The context of a chat started from a page (assistant_works.render: about 12,000 characters).
MAX_CONTEXT = 14000
MAX_WORK = 120
MAX_PLACE = 200
MAX_FOLDER = 60
MAX_SHARES = 50
# Who a chat is shared with: everyone in the workspace, one person, or one group.
SHARE_GRANT = re.compile(r"^(everyone|user:[a-z][a-z0-9_.\-]{1,39}|group:[A-Za-z0-9_.\-]{1,80})$")
# How long a chat of the side panel that was not continued in Desk is kept.
UNKEPT_HOURS = 24
ROLES = ("user", "assistant")
STATES = ("working", "done", "failed")


def chat_title(text: str) -> str:
    """A new chat's title: its first question, on one line, cut at a word."""

    line = " ".join(str(text).split())
    if len(line) <= 60:
        return line or t("New chat")
    cut = line[:60].rsplit(" ", 1)[0]
    return f"{cut or line[:60]}…"


class ChatStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS assistant_chats (
        chat_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        title TEXT NOT NULL,
        profile TEXT NOT NULL DEFAULT '',
        ref TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_assistant_chats_user ON assistant_chats(username, updated_at);

    CREATE TABLE IF NOT EXISTS assistant_chat_messages (
        message_id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        text TEXT NOT NULL DEFAULT '',
        state TEXT NOT NULL DEFAULT 'done',
        steps_json TEXT NOT NULL DEFAULT '[]',
        charts_json TEXT NOT NULL DEFAULT '[]',
        refs_json TEXT NOT NULL DEFAULT '[]',
        meta_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_assistant_chat_messages ON assistant_chat_messages(chat_id, message_id);
    """
    # The side panel's chats (2026-10-23): the place's context, and kept in Desk or not.
    MIGRATIONS = (
        Migration(
            "columns-before-0.5",
            add_columns(
                "assistant_chats",
                {
                    "context": "TEXT NOT NULL DEFAULT ''",
                    "place": "TEXT NOT NULL DEFAULT ''",
                    "kept": "INTEGER NOT NULL DEFAULT 1",
                },
            ),
        ),
        # The work the person picked on the page (assistant_works, 2026-10-25).
        Migration("work", add_columns("assistant_chats", {"work": "TEXT NOT NULL DEFAULT ''"})),
        # The history as people keep it (owner, 2026-10-26): a group of the person's own, archived
        # or not, and the people, groups or everyone it is shared with (read-only).
        Migration(
            "history",
            add_columns(
                "assistant_chats",
                {
                    "folder": "TEXT NOT NULL DEFAULT ''",
                    "archived": "INTEGER NOT NULL DEFAULT 0",
                    "shared_json": "TEXT NOT NULL DEFAULT '[]'",
                },
            ),
        ),
    )

    def __init__(self, db: Any):
        super().__init__(db)
        # After a restart no answer is still being written (the page says it was interrupted).
        with self._lock, self._write() as connection:
            connection.execute(
                "UPDATE assistant_chat_messages SET state = 'failed', text = CASE WHEN text = '' "
                "THEN 'The answer was interrupted: PlantCraft restarted. Try again.' "
                "ELSE text END WHERE state = 'working'"
            )

    # Chats

    _LISTED = (
        "SELECT c.*, (SELECT COUNT(*) FROM assistant_chat_messages m WHERE m.chat_id = c.chat_id) "
        "AS messages, (SELECT COUNT(*) FROM assistant_chat_messages m WHERE m.chat_id = c.chat_id "
        "AND m.state = 'working') AS working FROM assistant_chats c "
    )

    def chats(self, username: str, limit: int = MAX_CHATS) -> list[dict[str, Any]]:
        """The person's chats kept in Desk, archived ones too (each says it), newest first."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                self._LISTED + "WHERE c.username = ? AND c.kept = 1 "
                "ORDER BY c.updated_at DESC, c.chat_id DESC LIMIT ?",
                (username, limit),
            ).fetchall()
        return [self._chat(row) for row in rows]

    def shared_with(
        self, username: str, grants: set[str], limit: int = 200
    ) -> list[dict[str, Any]]:
        """Other people's chats shared with ``username`` (``grants``: ``everyone``,
        ``user:<name>`` and ``group:<id>`` of each of their groups), newest first."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                self._LISTED + "WHERE c.username != ? AND c.kept = 1 AND c.shared_json != '[]' "
                "ORDER BY c.updated_at DESC, c.chat_id DESC",
                (username,),
            ).fetchall()
        found = [self._chat(row) for row in rows]
        return [item for item in found if grants & set(item["shared"])][:limit]

    @staticmethod
    def _chat(row: Any) -> dict[str, Any]:
        item = dict(row)
        if "working" in item:
            item["working"] = bool(item["working"])
        item["kept"] = bool(item.get("kept", 1))
        item["archived"] = bool(item.get("archived", 0))
        item["folder"] = item.get("folder") or ""
        try:
            item["shared"] = [str(grant) for grant in json.loads(item.pop("shared_json", "[]"))]
        except (TypeError, ValueError):
            item["shared"] = []
        return item

    def exists(self, chat_id: int) -> bool:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM assistant_chats WHERE chat_id = ? AND kept = 1", (chat_id,)
            ).fetchone()
        return row is not None

    def readable(self, chat_id: int, username: str, grants: set[str]) -> dict[str, Any] | None:
        """The chat for its owner (a side panel's chat not kept too), or a kept chat for someone
        it is shared with (``grants`` as above)."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM assistant_chats WHERE chat_id = ?", (chat_id,)
            ).fetchone()
        if row is None:
            return None
        found = self._chat(row)
        if found["username"] == username:
            return found
        return found if found["kept"] and grants & set(found["shared"]) else None

    def chat(self, chat_id: int, username: str) -> dict[str, Any] | None:
        """The chat, only for the person who owns it."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM assistant_chats WHERE chat_id = ? AND username = ?",
                (chat_id, username),
            ).fetchone()
        return self._chat(row) if row else None

    def create(
        self,
        username: str,
        title: str,
        *,
        profile: str = "",
        ref: str = "",
        context: str = "",
        place: str = "",
        kept: bool = True,
        work: str = "",
    ) -> dict[str, Any]:
        now = self._now()
        self.forget_unkept()
        with self._lock, self._write() as connection:
            (count,) = connection.execute(
                "SELECT COUNT(*) FROM assistant_chats WHERE username = ? AND kept = 1", (username,)
            ).fetchone()
            if count >= MAX_CHATS:
                raise ValueError(
                    t("You have {count} chats, the most kept. Delete some first.", count=MAX_CHATS)
                )
            cursor = connection.execute(
                "INSERT INTO assistant_chats (username, title, profile, ref, context, place, kept, "
                "work, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    username,
                    title.strip()[:MAX_TITLE] or t("New chat"),
                    profile,
                    ref,
                    context.strip()[:MAX_CONTEXT],
                    " ".join(place.split())[:MAX_PLACE],
                    1 if kept else 0,
                    work[:MAX_WORK],
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM assistant_chats WHERE chat_id = ?", (cursor.lastrowid,)
            ).fetchone()
        return self._chat(row)

    def keep(self, chat_id: int, username: str) -> dict[str, Any] | None:
        """A side panel's chat continued in Desk: listed there from now on."""

        with self._lock, self._write() as connection:
            connection.execute(
                "UPDATE assistant_chats SET kept = 1 WHERE chat_id = ? AND username = ?",
                (chat_id, username),
            )
        return self.chat(chat_id, username)

    def forget_unkept(self, hours: int = UNKEPT_HOURS) -> int:
        """Delete the side panel's chats nobody continued in Desk, ``hours`` after their last
        message."""

        cutoff = utc_text(datetime.now(timezone.utc) - timedelta(hours=hours))
        with self._lock, self._write() as connection:
            ids = [
                row[0]
                for row in connection.execute(
                    "SELECT chat_id FROM assistant_chats WHERE kept = 0 AND updated_at < ?",
                    (cutoff,),
                )
            ]
            for chat_id in ids:
                connection.execute(
                    "DELETE FROM assistant_chat_messages WHERE chat_id = ?", (chat_id,)
                )
                connection.execute("DELETE FROM assistant_chats WHERE chat_id = ?", (chat_id,))
        return len(ids)

    def rename(self, chat_id: int, username: str, title: str) -> dict[str, Any] | None:
        return self.change(chat_id, username, title=title)

    def change(
        self,
        chat_id: int,
        username: str,
        *,
        title: str | None = None,
        folder: str | None = None,
        archived: bool | None = None,
    ) -> dict[str, Any] | None:
        """Rename the chat, put it in one of the person's groups ("" takes it out), archive it
        or bring it back; what is None stays."""

        changes: dict[str, Any] = {}
        if title is not None:
            clean = " ".join(title.split())[:MAX_TITLE]
            if not clean:
                raise ValueError(t("Give the chat a title."))
            changes["title"] = clean
        if folder is not None:
            changes["folder"] = " ".join(folder.split())[:MAX_FOLDER]
        if archived is not None:
            changes["archived"] = 1 if archived else 0
        if changes:
            with self._lock, self._write() as connection:
                connection.execute(
                    f"UPDATE assistant_chats SET {', '.join(f'{key} = ?' for key in changes)} "
                    "WHERE chat_id = ? AND username = ?",
                    (*changes.values(), chat_id, username),
                )
        return self.chat(chat_id, username)

    def share(self, chat_id: int, username: str, grants: list[str]) -> dict[str, Any] | None:
        """Who may read the chat besides its owner: ``everyone``, ``user:<name>``,
        ``group:<id>`` (an empty list stops sharing it)."""

        clean: list[str] = []
        for grant in grants:
            grant = str(grant).strip()
            if not SHARE_GRANT.match(grant):
                raise ValueError(
                    t("Share with everyone, a person or a group: {grant}", grant=grant)
                )
            if grant not in clean:
                clean.append(grant)
        if len(clean) > MAX_SHARES:
            raise ValueError(t("Share with {count} people or groups at most.", count=MAX_SHARES))
        with self._lock, self._write() as connection:
            connection.execute(
                "UPDATE assistant_chats SET shared_json = ? WHERE chat_id = ? AND username = ?",
                (json.dumps(clean), chat_id, username),
            )
        return self.chat(chat_id, username)

    def copy(self, chat: dict[str, Any], username: str) -> dict[str, Any]:
        """A chat someone shared, as the reader's own to continue: its title, object, context
        and messages, written by the assistant again under the reader's name."""

        made = self.create(
            username,
            t("{title} (copy)", title=chat["title"])[:MAX_TITLE],
            profile=chat.get("profile") or "",
            ref=chat.get("ref") or "",
            context=chat.get("context") or "",
            place=chat.get("place") or "",
            work=chat.get("work") or "",
        )
        now = self._now()
        with self._lock, self._write() as connection:
            connection.execute(
                "INSERT INTO assistant_chat_messages (chat_id, role, text, state, steps_json, "
                "charts_json, refs_json, meta_json, created_at, updated_at) SELECT ?, role, text, "
                "state, steps_json, charts_json, refs_json, meta_json, created_at, ? FROM "
                "assistant_chat_messages WHERE chat_id = ? AND state != 'working' ORDER BY message_id",
                (made["chat_id"], now, chat["chat_id"]),
            )
        return self.chat(made["chat_id"], username) or made

    def delete(self, chat_id: int, username: str) -> bool:
        with self._lock, self._write() as connection:
            cursor = connection.execute(
                "DELETE FROM assistant_chats WHERE chat_id = ? AND username = ?",
                (chat_id, username),
            )
            if cursor.rowcount:
                connection.execute(
                    "DELETE FROM assistant_chat_messages WHERE chat_id = ?", (chat_id,)
                )
        return bool(cursor.rowcount)

    # Messages

    def remove_message(self, message_id: int) -> None:
        """A failed answer asked again (``ChatEngine.retry``)."""

        with self._lock, self._write() as connection:
            connection.execute(
                "DELETE FROM assistant_chat_messages WHERE message_id = ?", (message_id,)
            )

    @staticmethod
    def _message(row: Any) -> dict[str, Any]:
        return Store._row_with_json(
            row,
            {
                "steps": ("steps_json", []),
                "charts": ("charts_json", []),
                "refs": ("refs_json", []),
                "meta": ("meta_json", {}),
            },
        )

    def messages(self, chat_id: int, *, after: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM assistant_chat_messages WHERE chat_id = ? AND message_id > ? "
                "ORDER BY message_id LIMIT ?",
                (chat_id, after, limit),
            ).fetchall()
        return [self._message(row) for row in rows]

    def message(self, message_id: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM assistant_chat_messages WHERE message_id = ?", (message_id,)
            ).fetchone()
        return self._message(row) if row else None

    def add(
        self, chat_id: int, role: str, text: str, *, state: str = "done", meta: dict | None = None
    ) -> dict[str, Any]:
        if role not in ROLES or state not in STATES:
            raise ValueError(f"role {role} or state {state}")
        now = self._now()
        with self._lock, self._write() as connection:
            cursor = connection.execute(
                "INSERT INTO assistant_chat_messages (chat_id, role, text, state, meta_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (chat_id, role, text[: MAX_TEXT * 4], state, self._json(meta or {}), now, now),
            )
            connection.execute(
                "UPDATE assistant_chats SET updated_at = ? WHERE chat_id = ?", (now, chat_id)
            )
            row = connection.execute(
                "SELECT * FROM assistant_chat_messages WHERE message_id = ?", (cursor.lastrowid,)
            ).fetchone()
        return self._message(row)

    def update(
        self,
        message_id: int,
        *,
        text: str | None = None,
        state: str | None = None,
        steps: list[dict[str, Any]] | None = None,
        charts: list[dict[str, Any]] | None = None,
        refs: list[str] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        sets, values = ["updated_at = ?"], [self._now()]
        for column, value in (
            ("text", text),
            ("state", state),
            ("steps_json", None if steps is None else self._json(steps)),
            ("charts_json", None if charts is None else self._json(charts)),
            ("refs_json", None if refs is None else self._json(refs)),
            ("meta_json", None if meta is None else self._json(meta)),
        ):
            if value is not None:
                sets.append(f"{column} = ?")
                values.append(value)
        with self._lock, self._write() as connection:
            connection.execute(
                f"UPDATE assistant_chat_messages SET {', '.join(sets)} WHERE message_id = ?",
                (*values, message_id),
            )

    def working(self, username: str) -> int:
        """How many answers are being written for ``username`` now."""

        with self._lock, self._connect() as connection:
            (count,) = connection.execute(
                "SELECT COUNT(*) FROM assistant_chat_messages m JOIN assistant_chats c "
                "ON c.chat_id = m.chat_id WHERE c.username = ? AND m.state = 'working'",
                (username,),
            ).fetchone()
        return int(count)

    def answers_since(self, username: str, since: str) -> int:
        """Answers written for ``username`` since ``since`` (the daily limit)."""

        with self._lock, self._connect() as connection:
            (count,) = connection.execute(
                "SELECT COUNT(*) FROM assistant_chat_messages m JOIN assistant_chats c "
                "ON c.chat_id = m.chat_id WHERE c.username = ? AND m.role = 'assistant' "
                "AND m.created_at >= ?",
                (username, since),
            ).fetchone()
        return int(count)
