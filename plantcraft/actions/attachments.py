"""Images attached to an action: the chart of the result it was opened from (docs/collaboration.md).

An app opening PlantCraft's action form can hand it a picture of what it showed (Analytics hands
the loop's chart, LACUNAS A19); the form attaches it to the new action. Only PNG, JPEG and WebP
images, up to ``MAX_BYTES`` each and ``MAX_PER_ACTION`` per action, are kept: they are shown
inline on the action, so nothing that a browser would run (SVG, HTML) is accepted. The bytes live
in the platform's database with the action.
"""

from __future__ import annotations

from typing import Any

from plantcraft.db import Store
from plantcraft.i18n import t

MAX_BYTES = 2 * 1024 * 1024
MAX_PER_ACTION = 10
# The type a picture's first bytes prove (its declared type is not trusted).
SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)


def sniff(data: bytes) -> str | None:
    """The image type of ``data`` from its first bytes, or None when it is not one we keep."""

    for magic, kind in SIGNATURES:
        if data.startswith(magic):
            return kind
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


class AttachmentStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS follow_up_action_files (
        file_id INTEGER PRIMARY KEY AUTOINCREMENT,
        action_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        content_type TEXT NOT NULL,
        size INTEGER NOT NULL,
        data BLOB NOT NULL,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_follow_up_action_files ON follow_up_action_files(action_id);
    """

    def add(self, action_id: int, name: str, data: bytes, actor: str) -> dict[str, Any]:
        kind = sniff(data)
        if kind is None:
            raise ValueError(t("Only PNG, JPEG and WebP images can be attached."))
        if len(data) > MAX_BYTES:
            raise ValueError(t("An image is at most {size} MB.", size=MAX_BYTES // (1024 * 1024)))
        cleaned = " ".join((name or "").split())[:120] or "image"
        with self._lock, self._connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM follow_up_action_files WHERE action_id = ?", (action_id,)
            ).fetchone()[0]
            if count >= MAX_PER_ACTION:
                raise ValueError(t("An action keeps at most {count} images.", count=MAX_PER_ACTION))
            cursor = connection.execute(
                """
                INSERT INTO follow_up_action_files
                (action_id, name, content_type, size, data, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (action_id, cleaned, kind, len(data), data, actor, self._now()),
            )
            file_id = int(cursor.lastrowid or 0)
        return self.meta(action_id)[-1] if file_id else {}

    def meta(self, action_id: int) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT file_id, name, content_type, size, created_by, created_at
                FROM follow_up_action_files WHERE action_id = ? ORDER BY file_id
                """,
                (action_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def read(self, action_id: int, file_id: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT file_id, name, content_type, data FROM follow_up_action_files
                WHERE action_id = ? AND file_id = ?
                """,
                (action_id, file_id),
            ).fetchone()
        return dict(row) if row else None
