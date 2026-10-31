"""Notes on a signal, at one instant or over an interval (2026-10-31, gap H8).

What a person knows that the values do not say: "analyser recalibrated", "pump B on manual
from 14:00 to 15:30". Kept beside the catalog by signal id, with who wrote it and when, and
read with a window like the values. Each note is also told to PlantCraft as an event
(``histcraft.annotation.added``, ``app.toml``) so Events, Alarms and the assistant see it: the
Historian never calls the suite (no app key), so the page that wrote the note posts the event
in the person's name with the body the API answers (``event``).
"""

from __future__ import annotations

from typing import Any

from histcraft.db import Store


class Annotations(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS annotations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal TEXT NOT NULL,
        start_ms INTEGER NOT NULL,
        end_ms INTEGER,
        text TEXT NOT NULL,
        author TEXT NOT NULL DEFAULT '',
        created_ms INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS annotations_signal ON annotations (signal, start_ms);
    """

    def add(
        self, signal: str, start_ms: int, end_ms: int | None, text: str, author: str, now: int
    ) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "INSERT INTO annotations (signal, start_ms, end_ms, text, author, created_ms)"
                " VALUES (?, ?, ?, ?, ?, ?) RETURNING *",
                (signal, start_ms, end_ms, text, author, now),
            ).fetchone()
        return dict(row)

    def get(self, annotation_id: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM annotations WHERE id = ?", (annotation_id,)
            ).fetchone()
        return dict(row) if row else None

    def remove(self, annotation_id: int) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM annotations WHERE id = ?", (annotation_id,))

    def between(
        self, signals: list[str] | None, start_ms: int, end_ms: int, limit: int
    ) -> list[dict[str, Any]]:
        """Notes that touch ``[start_ms, end_ms]`` (an interval that overlaps it counts), of
        ``signals`` (None: every signal), oldest first."""

        where = "start_ms <= ? AND COALESCE(end_ms, start_ms) >= ?"
        args: list[Any] = [end_ms, start_ms]
        if signals is not None:
            if not signals:
                return []
            where += f" AND signal IN ({','.join('?' for _ in signals)})"
            args.extend(signals)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM annotations WHERE {where} ORDER BY start_ms, id LIMIT ?",
                (*args, limit),
            ).fetchall()
        return [dict(row) for row in rows]
