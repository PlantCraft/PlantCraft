"""What the apps of the suite explain about their own objects (API v1 ``/knowledge``).

An app publishes a text for a reference it owns: what a protocol evaluates, what
its inputs and outputs mean and how an assistant should read it
(``algorithm:linkcraft/loop_health``); what a run did and found (``run:linkcraft/42``).
Specialists read these texts as context when a conversation cites the reference,
and search them when someone asks in general terms, so the explanation lives with
the app that knows it and every assistant of the platform can use it.

One row per (app, ref), replaced on every write. A ``transient`` text (a run's
report) is dropped 90 days after its last write; the others stay until the app
removes them (``DELETE``).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from plantcraft.db import Store, list_index

MAX_TEXT = 20000


# Texts by subject: app_knowledge_subjects, kept by triggers (plantcraft.db.list_index).
_SUBJECTS, _FILL_SUBJECTS = list_index(
    "app_knowledge", ("app_id", "ref"), "subjects_json", "app_knowledge_subjects"
)


class KnowledgeStore(Store):
    SCHEMA = (
        """
    CREATE TABLE IF NOT EXISTS app_knowledge (
        app_id TEXT NOT NULL,
        ref TEXT NOT NULL,
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        text TEXT NOT NULL,
        subjects_json TEXT NOT NULL DEFAULT '[]',
        url TEXT,
        transient INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (app_id, ref)
    );

    CREATE INDEX IF NOT EXISTS idx_app_knowledge_ref ON app_knowledge(ref);
    """
        + _SUBJECTS
    )
    # The side table filled once from the texts already kept (2026-10-31).
    MIGRATIONS = (_FILL_SUBJECTS,)

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        return {
            "app": row["app_id"],
            "ref": row["ref"],
            "kind": row["kind"],
            "title": row["title"],
            "text": row["text"],
            "subjects": Store._loads(row["subjects_json"], []),
            "url": row["url"],
            "transient": bool(row["transient"]),
            "updated_at": row["updated_at"],
        }

    def put(self, items: Iterable[dict[str, Any]], *, now: str, cutoff: str) -> int:
        """Write texts (one per app and ref); transient ones older than ``cutoff`` are dropped."""

        count = 0
        with self._lock, self._write() as connection:
            for item in items:
                connection.execute(
                    """
                    INSERT INTO app_knowledge (app_id, ref, kind, title, text, subjects_json,
                        url, transient, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (app_id, ref) DO UPDATE SET
                        kind = excluded.kind, title = excluded.title, text = excluded.text,
                        subjects_json = excluded.subjects_json, url = excluded.url,
                        transient = excluded.transient, updated_at = excluded.updated_at
                    """,
                    (
                        item["app"],
                        item["ref"],
                        item["kind"],
                        item["title"],
                        item["text"][:MAX_TEXT],
                        self._json(item.get("subjects") or []),
                        item.get("url"),
                        int(bool(item.get("transient"))),
                        now,
                    ),
                )
                count += 1
            connection.execute(
                "DELETE FROM app_knowledge WHERE transient = 1 AND updated_at < ?", (cutoff,)
            )
        return count

    def delete(self, app: str, refs: Iterable[str]) -> int:
        refs = list(refs)
        if not refs:
            return 0
        marks = ", ".join("?" for _ in refs)
        with self._lock, self._write() as connection:
            cursor = connection.execute(
                f"DELETE FROM app_knowledge WHERE app_id = ? AND ref IN ({marks})", (app, *refs)
            )
        return cursor.rowcount

    def about(self, ref: str, apps: Iterable[str] | None = None) -> list[dict[str, Any]]:
        """The texts written for ``ref`` itself, or naming it among their subjects."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM app_knowledge
                WHERE ref = ? OR (app_id, ref) IN (
                    SELECT app_id, ref FROM app_knowledge_subjects WHERE subject = ?)
                ORDER BY ref = ? DESC, updated_at DESC
                LIMIT 20
                """,
                (ref, ref, ref),
            ).fetchall()
        allowed = None if apps is None else set(apps)
        return [self._row(row) for row in rows if allowed is None or row["app_id"] in allowed]

    def get(self, ref: str) -> dict[str, Any] | None:
        """The newest text written for ``ref`` itself (any app)."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM app_knowledge WHERE ref = ? ORDER BY updated_at DESC LIMIT 1",
                (ref,),
            ).fetchone()
        return self._row(row) if row else None

    def search(
        self,
        text: str = "",
        *,
        apps: Iterable[str] | None = None,
        kind: str | None = None,
        app: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Texts whose title, ref or body hold every word of ``text``, newest first."""

        clauses: list[str] = []
        values: list[Any] = []
        for word in text.lower().split()[:8]:
            clauses.append("(lower(title) LIKE ? OR lower(ref) LIKE ? OR lower(text) LIKE ?)")
            values.extend([f"%{word}%"] * 3)
        if kind:
            clauses.append("kind = ?")
            values.append(kind)
        if app:
            clauses.append("app_id = ?")
            values.append(app)
        if apps is not None:
            allowed = list(apps)
            if not allowed:
                return []
            clauses.append(f"app_id IN ({', '.join('?' for _ in allowed)})")
            values.extend(allowed)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM app_knowledge{where} ORDER BY transient, updated_at DESC LIMIT ?",
                (*values, max(1, min(limit, 100))),
            ).fetchall()
        return [self._row(row) for row in rows]
