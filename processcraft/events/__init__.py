"""Platform events: what happened, published by whoever did it.

A module publishes an event (``action.status_changed``, ``finding.opened``,
``twin.status_changed``, ``message.posted``...) with the references it touches.
Other modules subscribe without the publisher knowing they exist: the
collaboration module turns events into notifications, the asset page reads
them as a timeline, and backlinks are simply "events that mention this ref".

An event also says how bad its publisher thinks it is (``severity``: info, ok, warning,
critical), whether it opens or closes a condition (``phase`` start or end, the condition named
by ``key``; ``instant`` otherwise) and what it is about (``category``). Apps declare the events
they write in a catalog (``plantcraft_sdk.events``), kept here in ``event_catalogs`` with the
kinds an app wrote without declaring them; Alarms reads the catalogs to offer them in its rules.

Each event lists its references in ``event_refs`` so a timeline is one indexed query whatever
the size of the history. Events older than ``PLANTCRAFT_EVENT_RETENTION_DAYS`` (two years by
default; ``0`` keeps them all) are dropped, at most once an hour, when new ones arrive.

**Only changes are kept** (Alarms round 11): a ``start`` of a condition already open from the
same app with the same severity, or an ``end`` of one that is not open, is not written again;
``publish_many`` answers the event already there, marked ``repeated``. A ``start`` with another
severity (warning to critical) is a change and is written. Apps publish when something changes,
never to repeat that it is still the same.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable, Collection
from datetime import datetime, timedelta, timezone
from typing import Any

from processcraft.db import Migration, Store, add_columns, utc_text
from processcraft.refs import parse_ref

logger = logging.getLogger(__name__)

RETENTION_ENV = "PLANTCRAFT_EVENT_RETENTION_DAYS"
DEFAULT_RETENTION_DAYS = 730
PRUNE_SECONDS = 3600


def retention_days() -> int:
    """Days of events kept (``0``: all of them)."""

    raw = os.environ.get(RETENTION_ENV, "").strip()
    if not raw:
        return DEFAULT_RETENTION_DAYS
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning(
            "%s=%r is not a number of days; keeping %s", RETENTION_ENV, raw, DEFAULT_RETENTION_DAYS
        )
        return DEFAULT_RETENTION_DAYS


Subscriber = Callable[[dict[str, Any]], None]


class EventStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS platform_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        at TEXT NOT NULL,
        kind TEXT NOT NULL,
        source TEXT NOT NULL,
        subject TEXT NOT NULL,
        actor TEXT NOT NULL DEFAULT '',
        summary TEXT NOT NULL DEFAULT '',
        payload_json TEXT NOT NULL DEFAULT '{}'
    );

    CREATE INDEX IF NOT EXISTS idx_platform_events_kind ON platform_events(kind, event_id);
    CREATE INDEX IF NOT EXISTS idx_platform_events_at ON platform_events(at);

    CREATE TABLE IF NOT EXISTS event_refs (
        event_id INTEGER NOT NULL REFERENCES platform_events(event_id) ON DELETE CASCADE,
        ref TEXT NOT NULL,
        PRIMARY KEY (ref, event_id)
    );

    CREATE TABLE IF NOT EXISTS event_catalogs (
        app TEXT PRIMARY KEY,
        events_json TEXT NOT NULL DEFAULT '[]',
        undeclared_json TEXT NOT NULL DEFAULT '[]',
        updated_at TEXT NOT NULL
    );
    """

    # Event fields added 2026-10-25 (Alarms round 8): stored as written, "" when not given.
    FIELDS = ("severity", "event_key", "phase", "category")

    MIGRATIONS = (
        Migration(
            "columns-before-0.5",
            add_columns("platform_events", dict.fromkeys(FIELDS, "TEXT NOT NULL DEFAULT ''")),
        ),
    )

    def __init__(self, db: Any):
        super().__init__(db)
        with self._lock, self._write() as connection:
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_platform_events_key"
                " ON platform_events(event_key, event_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_platform_events_source_at"
                " ON platform_events(source, at)"
            )
        self._subscribers: list[tuple[str, Subscriber]] = []
        self._subscribers_lock = threading.Lock()
        self._pruned_at = -float("inf")

    # Publishing ------------------------------------------------------------

    def subscribe(self, subscriber: Subscriber, *, prefix: str = "") -> None:
        """Call ``subscriber(event)`` after every event whose kind starts with ``prefix``."""

        with self._subscribers_lock:
            self._subscribers.append((prefix, subscriber))

    def publish(
        self,
        kind: str,
        subject: str,
        *,
        source: str,
        actor: str = "",
        summary: str = "",
        payload: dict[str, Any] | None = None,
        refs: list[str] | tuple[str, ...] = (),
        severity: str = "",
        key: str = "",
        phase: str = "",
        category: str = "",
    ) -> dict[str, Any]:
        """Record an event about ``subject`` (a reference) that also mentions ``refs``."""

        item = {"kind": kind, "subject": subject, "source": source, "actor": actor}
        item.update(summary=summary, payload=payload, refs=refs)
        item.update(severity=severity, key=key, phase=phase, category=category)
        return self.publish_many([item])[0]

    def publish_many(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Record several events in one transaction, in order; answers them as ``get`` does.

        Each item has ``publish``'s arguments as keys. A subject that is not a
        reference raises ``ValueError`` before anything is written.
        """

        rows = []
        for item in items:
            subject = item["subject"]
            parse_ref(subject)
            mentioned = [subject]
            for ref in item.get("refs") or ():
                try:
                    normalized = str(parse_ref(ref))
                except ValueError:
                    continue
                if normalized not in mentioned:
                    mentioned.append(normalized)
            rows.append((item, mentioned))
        events: list[dict[str, Any]] = []
        repeated: dict[int, int] = {}
        with self._lock, self._write() as connection:
            now = self._now()
            # (source, key) -> (phase, severity, event id) of the condition's last event.
            last: dict[tuple[str, str], tuple[str, str, int] | None] = {}
            for place, (item, mentioned) in enumerate(rows):
                payload = self._json(item.get("payload") or {})
                fields = self._fields(item)
                same = self._unchanged(connection, last, item["source"], fields)
                if same is not None:
                    repeated[place] = same
                    events.append({})
                    continue
                cursor = connection.execute(
                    """
                    INSERT INTO platform_events
                        (at, kind, source, subject, actor, summary, payload_json,
                         severity, event_key, phase, category)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now,
                        item["kind"],
                        item["source"],
                        item["subject"],
                        item.get("actor") or "",
                        item.get("summary") or "",
                        payload,
                        fields["severity"],
                        fields["key"],
                        fields["phase"],
                        fields["category"],
                    ),
                )
                event_id = int(cursor.lastrowid)
                connection.executemany(
                    "INSERT OR IGNORE INTO event_refs (event_id, ref) VALUES (?, ?)",
                    [(event_id, ref) for ref in mentioned],
                )
                events.append(
                    {
                        "event_id": event_id,
                        "at": now,
                        "kind": item["kind"],
                        "source": item["source"],
                        "subject": item["subject"],
                        "actor": item.get("actor") or "",
                        "summary": item.get("summary") or "",
                        "payload": self._loads(payload, {}),
                        "refs": mentioned,
                        **fields,
                    }
                )
                if fields["key"] and fields["phase"] in ("start", "end"):
                    last[(item["source"], fields["key"])] = (
                        fields["phase"],
                        fields["severity"],
                        event_id,
                    )
        written = [event for event in events if event]
        for place, event_id in repeated.items():
            found = self.get(event_id) if event_id else None
            events[place] = {**(found or {}), "repeated": True}
        self._prune_now_and_then()
        with self._subscribers_lock:
            subscribers = list(self._subscribers)
        for event in written:
            for prefix, subscriber in subscribers:
                if event["kind"].startswith(prefix):
                    try:
                        subscriber(event)
                    except Exception:  # one listener failing must not undo the event
                        logger.exception("Event subscriber failed for %s", event["kind"])
        return events

    @staticmethod
    def _unchanged(
        connection: Any,
        last: dict[tuple[str, str], tuple[str, str, int] | None],
        source: str,
        fields: dict[str, str],
    ) -> int | None:
        """The id of the event that already says this (0 when none was ever written: an end of
        a condition never opened), or None when this event is a change to write."""

        key, phase = fields["key"], fields["phase"]
        if not key or phase not in ("start", "end"):
            return None
        if (source, key) not in last:
            row = connection.execute(
                "SELECT event_id, phase, severity FROM platform_events"
                " WHERE event_key = ? AND source = ? ORDER BY event_id DESC LIMIT 1",
                (key, source),
            ).fetchone()
            last[(source, key)] = (
                None if row is None else (row["phase"], row["severity"], int(row["event_id"]))
            )
        before = last[(source, key)]
        if phase == "end":
            if before is None:
                return 0
            return before[2] if before[0] == "end" else None
        if before is not None and before[0] == "start" and before[1] == fields["severity"]:
            return before[2]
        return None

    def count_since(self, source: str, start: str) -> int:
        """Events ``source`` wrote at or after ``start`` (an hour's budget)."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM platform_events WHERE source = ? AND at >= ?",
                (source, start),
            ).fetchone()
        return int(row[0])

    @staticmethod
    def _fields(item: dict[str, Any]) -> dict[str, str]:
        """``severity``, ``key``, ``phase``, ``category``: as given, else from ``payload.severity``
        (how events were written before) and ``instant``."""

        severity = str(item.get("severity") or "")
        if not severity:
            given = str((item.get("payload") or {}).get("severity") or "").strip().lower()
            severity = given if given in ("info", "ok", "warning", "critical") else "info"
        return {
            "severity": severity,
            "key": str(item.get("key") or ""),
            "phase": str(item.get("phase") or "instant"),
            "category": str(item.get("category") or ""),
        }

    def _item(self, row: Any) -> dict[str, Any]:
        item = self._row_with_json(row, {"payload": ("payload_json", {})})
        item["key"] = item.pop("event_key", "") or ""
        item["severity"] = item.get("severity") or "info"
        item["phase"] = item.get("phase") or "instant"
        item.setdefault("category", "")
        return item

    # Catalogs ----------------------------------------------------------------

    def put_catalog(self, app: str, events: list[dict[str, Any]]) -> None:
        """The events ``app`` declares, replaced; kinds it wrote undeclared and now declares
        leave the undeclared list."""

        declared = {f"{app}.{spec['name']}" for spec in events}
        with self._lock, self._write() as connection:
            row = connection.execute(
                "SELECT undeclared_json FROM event_catalogs WHERE app = ?", (app,)
            ).fetchone()
            undeclared = [
                kind
                for kind in self._loads(row["undeclared_json"] if row else None, [])
                if kind not in declared
            ]
            connection.execute(
                """
                INSERT INTO event_catalogs (app, events_json, undeclared_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(app) DO UPDATE SET events_json = excluded.events_json,
                    undeclared_json = excluded.undeclared_json, updated_at = excluded.updated_at
                """,
                (app, self._json(events), self._json(undeclared), self._now()),
            )

    def catalogs(self) -> dict[str, dict[str, Any]]:
        """app -> ``{"events", "undeclared", "updated_at"}``."""

        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM event_catalogs ORDER BY app").fetchall()
        return {
            row["app"]: {
                "events": self._loads(row["events_json"], []),
                "undeclared": self._loads(row["undeclared_json"], []),
                "updated_at": row["updated_at"],
            }
            for row in rows
        }

    def catalog(self, app: str) -> list[dict[str, Any]] | None:
        """The events ``app`` declares; None when it never sent a catalog."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT events_json FROM event_catalogs WHERE app = ?", (app,)
            ).fetchone()
        return None if row is None else self._loads(row["events_json"], [])

    def note_undeclared(self, app: str, kind: str) -> bool:
        """Remember that ``app`` wrote ``kind`` without declaring it; True the first time."""

        with self._lock, self._write() as connection:
            row = connection.execute(
                "SELECT undeclared_json FROM event_catalogs WHERE app = ?", (app,)
            ).fetchone()
            if row is None:
                return False
            undeclared = self._loads(row["undeclared_json"], [])
            if kind in undeclared or len(undeclared) >= 100:
                return False
            connection.execute(
                "UPDATE event_catalogs SET undeclared_json = ? WHERE app = ?",
                (self._json([*undeclared, kind]), app),
            )
        return True

    def prune(self, days: int | None = None, *, now: datetime | None = None) -> int:
        """Delete events older than ``days`` (the configured retention); events deleted."""

        days = retention_days() if days is None else days
        if days <= 0:
            return 0
        cutoff = utc_text((now or datetime.now(timezone.utc)) - timedelta(days=days))
        with self._lock, self._write() as connection:
            # event_refs follow (ON DELETE CASCADE).
            return connection.execute(
                "DELETE FROM platform_events WHERE at < ?", (cutoff,)
            ).rowcount

    def _prune_now_and_then(self) -> None:
        if time.monotonic() - self._pruned_at < PRUNE_SECONDS:
            return
        self._pruned_at = time.monotonic()
        try:
            removed = self.prune()
        except Exception:  # retention must never cost an event
            logger.exception("Pruning old events failed")
            return
        if removed:
            logger.info("Dropped %s events older than %s days", removed, retention_days())

    # Reading ---------------------------------------------------------------

    def get(self, event_id: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM platform_events WHERE event_id = ?", (event_id,)
            ).fetchone()
            refs = [
                item["ref"]
                for item in connection.execute(
                    "SELECT ref FROM event_refs WHERE event_id = ? ORDER BY rowid", (event_id,)
                )
            ]
        if row is None:
            return None
        item = self._item(row)
        item["refs"] = refs
        return item

    def timeline(
        self,
        ref: str,
        *,
        before_id: int | None = None,
        limit: int = 50,
        kinds: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Events that mention ``ref`` (as subject or reference), newest first."""

        parse_ref(ref)
        query = """
            SELECT e.* FROM event_refs r JOIN platform_events e ON e.event_id = r.event_id
            WHERE r.ref = ?
        """
        params: list[Any] = [ref]
        if before_id is not None:
            query += " AND e.event_id < ?"
            params.append(before_id)
        if kinds:
            query += f" AND e.kind IN ({','.join('?' for _ in kinds)})"
            params.extend(kinds)
        query += " ORDER BY e.event_id DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        with self._lock, self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
            ids = [row["event_id"] for row in rows]
            refs: dict[int, list[str]] = {}
            if ids:
                for item in connection.execute(
                    f"SELECT event_id, ref FROM event_refs WHERE event_id IN ({','.join('?' for _ in ids)}) ORDER BY rowid",
                    ids,
                ):
                    refs.setdefault(item["event_id"], []).append(item["ref"])
        events = []
        for row in rows:
            item = self._item(row)
            item["refs"] = refs.get(item["event_id"], [])
            events.append(item)
        return events

    def listing(
        self,
        *,
        ref: str | None = None,
        kind: str | None = None,
        after_id: int | None = None,
        limit: int = 100,
        key: str | None = None,
        hidden: Collection[str] = (),
    ) -> list[dict[str, Any]]:
        """Events (about or mentioning ``ref``, of ``kind``, of the condition ``key``, not sent
        by one of the ``hidden`` sources), oldest first.

        With ``after_id``, the first ``limit`` events after it (to page forward);
        without, the latest ``limit`` events.
        """

        clauses, params = [], []
        if hidden:
            clauses.append(f"source NOT IN ({','.join('?' for _ in hidden)})")
            params.extend(sorted(hidden))
        if ref is not None:
            clauses.append("event_id IN (SELECT event_id FROM event_refs WHERE ref = ?)")
            params.append(ref)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if key is not None:
            clauses.append("event_key = ?")
            params.append(key)
        if after_id is not None:
            clauses.append("event_id > ?")
            params.append(after_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        order = "ASC" if after_id is not None else "DESC"
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT event_id FROM platform_events{where} ORDER BY event_id {order} LIMIT ?",
                [*params, max(1, min(limit, 500))],
            ).fetchall()
        ids = sorted(row["event_id"] for row in rows)
        return [event for event in (self.get(event_id) for event_id in ids) if event]

    def since(self, after_id: int, *, limit: int = 500) -> list[dict[str, Any]]:
        """Events after ``after_id``, oldest first (for listeners catching up)."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT event_id FROM platform_events WHERE event_id > ? ORDER BY event_id LIMIT ?",
                (after_id, limit),
            ).fetchall()
        return [event for event in (self.get(row["event_id"]) for row in rows) if event]

    def about(self, ref: str, *, since: str) -> list[dict[str, Any]]:
        """What happened about ``ref`` since ``since``, by kind: ``{"kind", "app", "count",
        "last_at", "open", "severity"}`` (``open``: conditions of that kind started and not
        ended), most recent first."""

        parse_ref(ref)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT e.kind, e.source, e.event_key, e.phase, e.severity, e.at
                FROM event_refs r JOIN platform_events e ON e.event_id = r.event_id
                WHERE r.ref = ? AND e.at >= ? ORDER BY e.event_id
                LIMIT 20000
                """,
                (ref, since),
            ).fetchall()
        kinds: dict[str, dict[str, Any]] = {}
        last: dict[tuple[str, str], tuple[str, str]] = {}
        for row in rows:
            item = kinds.setdefault(
                row["kind"],
                {"kind": row["kind"], "app": row["source"], "count": 0, "last_at": "",
                 "open": 0, "severity": ""},
            )  # fmt: skip
            item["count"] += 1
            item["last_at"] = row["at"]
            item["severity"] = row["severity"] or "info"
            if row["event_key"] and row["phase"] in ("start", "end"):
                last[(row["source"], row["event_key"])] = (row["phase"], row["kind"])
        for phase, kind in last.values():
            if phase == "start":
                kinds[kind]["open"] += 1
        return sorted(kinds.values(), key=lambda item: item["last_at"], reverse=True)

    def signal_refs(self) -> list[str]:
        """Every ``signal:`` reference stored on events (as subject or mention)."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT ref FROM event_refs WHERE ref LIKE 'signal:%'
                UNION SELECT subject FROM platform_events WHERE subject LIKE 'signal:%'
                """
            ).fetchall()
        return sorted(row[0] for row in rows)

    def rename_refs(self, mapping: dict[str, str]) -> dict[str, int]:
        """References renamed (``old -> new``) on events' subjects and mentions; rows changed."""

        counts = {"events": 0, "event_refs": 0}
        with self._lock, self._write() as connection:
            for old, new in mapping.items():
                counts["events"] += connection.execute(
                    "UPDATE platform_events SET subject = ? WHERE subject = ?", (new, old)
                ).rowcount
                counts["event_refs"] += connection.execute(
                    "UPDATE OR IGNORE event_refs SET ref = ? WHERE ref = ?", (new, old)
                ).rowcount
        return counts

    def backlinks(self, ref: str, *, limit: int = 100) -> list[str]:
        """Subjects of the events that mention ``ref`` without being about it, newest first."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT e.subject, MAX(e.event_id) AS last_id
                FROM event_refs r JOIN platform_events e ON e.event_id = r.event_id
                WHERE r.ref = ? AND e.subject != ?
                GROUP BY e.subject ORDER BY last_id DESC LIMIT ?
                """,
                (ref, ref, limit),
            ).fetchall()
        return [row["subject"] for row in rows]


__all__ = ["EventStore", "Subscriber"]
