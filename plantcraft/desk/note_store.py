"""``DeskStore``'s notes and the assets each person follows. Part of ``DeskStore``
(``plantcraft.desk``)."""

from __future__ import annotations

from typing import Any

from plantcraft.desk.common import (
    MAX_FOLLOWS,
    MAX_NOTE_BYTES,
    MAX_NOTES_EACH,
    MAX_SHARES,
    MAX_TITLE,
)
from plantcraft.i18n import t


class NoteStore:
    """``DeskStore``'s notes and follows."""

    # Notes ------------------------------------------------------------------------------------

    def _note(self, row: Any, *, body: bool = True) -> dict[str, Any]:
        item = self._row_with_json(row, {"body": ("body_json", {}), "shared": ("shared_json", [])})
        item["pinned"] = bool(item["pinned"])
        if not body:
            item.pop("body")
        return item

    @staticmethod
    def note_visible(note: dict[str, Any], username: str, groups: list[str]) -> bool:
        """A note is its owner's; shared, it is also of the people and groups it names."""

        shared = set(note.get("shared") or [])
        return (
            note["owner"] == username
            or f"user:{username}" in shared
            or any(f"group:{group}" in shared for group in groups)
        )

    def notes(
        self, username: str, groups: list[str], *, q: str = "", event_ref: str | None = None
    ) -> list[dict[str, Any]]:
        """The person's notes and those shared with them, pinned first, newest first; ``q``
        looks in titles and text."""

        like = [f'%"user:{username}"%'] + [f'%"group:{group}"%' for group in groups]
        clauses = " OR ".join("shared_json LIKE ?" for _ in like)
        where = f"(owner = ? OR {clauses})"
        values: list[Any] = [username, *like]
        if q.strip():
            where += " AND (title LIKE ? OR body_text LIKE ?)"
            values += [f"%{q.strip()}%", f"%{q.strip()}%"]
        if event_ref:
            where += " AND event_ref = ?"
            values.append(event_ref)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM desk_notes WHERE {where} ORDER BY pinned DESC, updated_at DESC LIMIT 500",
                values,
            ).fetchall()
        found = [self._note(row, body=False) for row in rows]
        return [item for item in found if self.note_visible(item, username, groups)]

    def note(self, note_id: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM desk_notes WHERE note_id = ?", (note_id,)
            ).fetchone()
        return self._note(row) if row else None

    @staticmethod
    def _shares(shared: list[str]) -> list[str]:
        found = []
        for item in shared:
            text = str(item).strip()
            kind, _, name = text.partition(":")
            if kind not in ("user", "group") or not name:
                raise ValueError(t("Share a note with people or groups."))
            found.append(text)
        if len(found) > MAX_SHARES:
            raise ValueError(
                t("Share a note with {count} people or groups at most.", count=MAX_SHARES)
            )
        return list(dict.fromkeys(found))

    def _note_body(self, body: Any, text: str) -> tuple[str, str]:
        raw = self._json(body if isinstance(body, dict) else {})
        if len(raw.encode()) > MAX_NOTE_BYTES:
            raise ValueError(t("A note is {count} KB at most.", count=MAX_NOTE_BYTES // 1000))
        return raw, " ".join(str(text or "").split())[:20_000]

    def create_note(
        self,
        owner: str,
        *,
        title: str = "",
        body: Any = None,
        text: str = "",
        shared: list[str] | None = None,
        event_ref: str | None = None,
    ) -> dict[str, Any]:
        raw, plain = self._note_body(body, text)
        now = self._now()
        with self._lock, self._write() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM desk_notes WHERE owner = ?", (owner,)
            ).fetchone()[0]
            if count >= MAX_NOTES_EACH:
                raise ValueError(t("You keep {count} notes at most.", count=MAX_NOTES_EACH))
            cursor = connection.execute(
                "INSERT INTO desk_notes (owner, title, body_json, body_text, shared_json, event_ref, created_at, updated_at, updated_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    owner,
                    " ".join(str(title or "").split())[:MAX_TITLE],
                    raw,
                    plain,
                    self._json(self._shares(shared or [])),
                    (event_ref or None) and str(event_ref)[:200],
                    now,
                    now,
                    owner,
                ),
            )
        return self.note(int(cursor.lastrowid)) or {}

    def update_note(
        self, note_id: int, change: dict[str, Any], actor: str
    ) -> dict[str, Any] | None:
        """The fields given; ``body`` comes with ``text`` (what search reads)."""

        sets: dict[str, Any] = {}
        if "title" in change:
            sets["title"] = " ".join(str(change["title"] or "").split())[:MAX_TITLE]
        if "body" in change:
            sets["body_json"], sets["body_text"] = self._note_body(
                change["body"], change.get("text", "")
            )
        if "shared" in change:
            sets["shared_json"] = self._json(self._shares(change["shared"] or []))
        if "pinned" in change:
            sets["pinned"] = int(bool(change["pinned"]))
        if "event_ref" in change:
            sets["event_ref"] = (change["event_ref"] or None) and str(change["event_ref"])[:200]
        if sets:
            sets["updated_at"], sets["updated_by"] = self._now(), actor
            with self._lock, self._write() as connection:
                connection.execute(
                    f"UPDATE desk_notes SET {', '.join(f'{key} = ?' for key in sets)} WHERE note_id = ?",
                    (*sets.values(), note_id),
                )
        return self.note(note_id)

    def delete_note(self, note_id: int) -> bool:
        with self._lock, self._write() as connection:
            cursor = connection.execute("DELETE FROM desk_notes WHERE note_id = ?", (note_id,))
        return cursor.rowcount > 0

    # Follows ----------------------------------------------------------------------------------

    def follows(self, username: str) -> list[str]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT ref FROM desk_follows WHERE username = ? ORDER BY created_at, ref",
                (username,),
            ).fetchall()
        return [row["ref"] for row in rows]

    def follow(self, username: str, ref: str) -> None:
        with self._lock, self._write() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM desk_follows WHERE username = ?", (username,)
            ).fetchone()[0]
            if count >= MAX_FOLLOWS:
                raise ValueError(t("You follow {count} assets at most.", count=MAX_FOLLOWS))
            connection.execute(
                "INSERT OR IGNORE INTO desk_follows (username, ref, created_at) VALUES (?, ?, ?)",
                (username, ref, self._now()),
            )

    def unfollow(self, username: str, ref: str) -> None:
        with self._lock, self._write() as connection:
            connection.execute(
                "DELETE FROM desk_follows WHERE username = ? AND ref = ?", (username, ref)
            )
