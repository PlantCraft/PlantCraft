"""Incoming: what the apps of the suite report, as Alarms read it from PlantCraft's events.

Every event another app publishes (``/api/v1/events``) is kept here for 30 days with the rules
it counted for. Incoming never notifies anyone: a rule decides what becomes an alarm. Alarms' own
events (``alarmcraft.*``) are not kept: they are what the rules made.

| Table | Holds |
|---|---|
| ``incoming`` | each event: id in PlantCraft, when, app, kind, subject, summary, severity, phase, key, category, payload, refs, the rules it counted for (kept 30 days) |
| ``conditions`` | each condition an app opened (an event with ``phase`` start and a ``key``) and has not closed yet: what inhibits the alarms that depend on it |
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from plantcraft_sdk.server.store import Migration, Store, add_columns

KEEP_DAYS = 30
SEVERITIES = ("info", "ok", "warning", "critical")


def phase_of(event: dict[str, Any]) -> str:
    """``start``, ``end`` or ``instant`` (events from before SDK 0.26 are instant)."""

    phase = str(event.get("phase") or "instant")
    return phase if phase in ("start", "end") else "instant"


def severity_of(event: dict[str, Any]) -> str:
    """The event's severity: its own field (PlantCraft fills it, ``info`` when the app said
    nothing), else ``payload.severity`` as apps wrote it before; "" when none."""

    value = str(event.get("severity") or "").strip().lower()
    if value in SEVERITIES and value != "info":
        return value
    given = str((event.get("payload") or {}).get("severity") or "").strip().lower()
    if given in SEVERITIES:
        return given
    return value if value in SEVERITIES else ""


class IncomingStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS incoming (
        event_id INTEGER PRIMARY KEY,
        at TEXT NOT NULL,
        app TEXT NOT NULL,
        kind TEXT NOT NULL,
        subject TEXT NOT NULL DEFAULT '',
        summary TEXT NOT NULL DEFAULT '',
        severity TEXT NOT NULL DEFAULT '',
        payload_json TEXT NOT NULL DEFAULT '{}',
        refs_json TEXT NOT NULL DEFAULT '[]',
        rules_json TEXT NOT NULL DEFAULT '[]'
    );
    CREATE INDEX IF NOT EXISTS incoming_at ON incoming (at);
    CREATE INDEX IF NOT EXISTS incoming_kind ON incoming (kind, at);
    CREATE TABLE IF NOT EXISTS conditions (
        app TEXT NOT NULL,
        condition_key TEXT NOT NULL,
        kind TEXT NOT NULL,
        subject TEXT NOT NULL DEFAULT '',
        summary TEXT NOT NULL DEFAULT '',
        severity TEXT NOT NULL DEFAULT '',
        opened_at TEXT NOT NULL,
        event_id INTEGER NOT NULL,
        PRIMARY KEY (app, condition_key)
    );
    """
    # Columns added with the event's own fields (alarmcraft 0.5.0, SDK 0.26).
    COLUMNS = {
        "phase": "TEXT NOT NULL DEFAULT 'instant'",
        "event_key": "TEXT NOT NULL DEFAULT ''",
        "category": "TEXT NOT NULL DEFAULT ''",
    }

    MIGRATIONS = (Migration("columns-before-0.5", add_columns("incoming", COLUMNS)),)

    def _item(self, row: Any) -> dict[str, Any]:
        item = self._row_with_json(
            row,
            {
                "payload": ("payload_json", {}),
                "refs": ("refs_json", []),
                "rules": ("rules_json", []),
            },
        )
        item["id"] = item.pop("event_id")
        item["key"] = item.pop("event_key", "") or ""
        return item

    def add(
        self, events: list[dict[str, Any]], rules: dict[int, list[str]], *, now: datetime
    ) -> int:
        """Keep the events read (``rules``: event id → the rules it counted for)."""

        rows = [
            (
                int(event["id"]),
                str(event.get("at") or now.isoformat()),
                str(event.get("app") or ""),
                str(event.get("kind") or ""),
                str(event.get("subject") or ""),
                str(event.get("summary") or "")[:500],
                severity_of(event),
                self._json(event.get("payload") or {}),
                self._json(list(event.get("refs") or [])[:50]),
                self._json(rules.get(int(event["id"]), [])),
                phase_of(event),
                str(event.get("key") or "")[:200],
                str(event.get("category") or "")[:20],
            )
            for event in events
        ]
        cutoff = (now - timedelta(days=KEEP_DAYS)).isoformat()
        with self._lock, self._connect() as connection:
            connection.executemany(
                "INSERT OR IGNORE INTO incoming (event_id, at, app, kind, subject, summary,"
                " severity, payload_json, refs_json, rules_json, phase, event_key, category)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
            connection.execute("DELETE FROM incoming WHERE at < ?", (cutoff,))
            for event in events:
                self._condition(connection, event, now)
        return len(rows)

    @staticmethod
    def _condition(connection: Any, event: dict[str, Any], now: datetime) -> None:
        key, phase = str(event.get("key") or ""), phase_of(event)
        if not key or phase == "instant":
            return
        app = str(event.get("app") or "")
        if phase == "end":
            connection.execute(
                "DELETE FROM conditions WHERE app = ? AND condition_key = ?", (app, key)
            )
            return
        connection.execute(
            "INSERT INTO conditions (app, condition_key, kind, subject, summary, severity,"
            " opened_at, event_id) VALUES (?,?,?,?,?,?,?,?)"
            " ON CONFLICT(app, condition_key) DO UPDATE SET summary = excluded.summary,"
            " severity = excluded.severity",
            (
                app,
                key,
                str(event.get("kind") or ""),
                str(event.get("subject") or ""),
                str(event.get("summary") or "")[:500],
                severity_of(event),
                str(event.get("at") or now.isoformat()),
                int(event["id"]),
            ),
        )

    def open_conditions(self) -> list[dict[str, Any]]:
        """The conditions open now (started, not ended), oldest first."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM conditions ORDER BY opened_at, event_id"
            ).fetchall()
        found = []
        for row in rows:
            item = dict(row)
            item["key"] = item.pop("condition_key")
            found.append(item)
        return found

    def listing(
        self,
        *,
        start: str | None = None,
        app: str | None = None,
        kind: str | None = None,
        severity: str | None = None,
        subject: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Events newest first, filtered."""

        clauses, values = [], []
        for column, value in (
            ("app", app),
            ("kind", kind),
            ("severity", severity),
            ("subject", subject),
        ):
            if value:
                clauses.append(f"{column} = ?")
                values.append(value)
        if start:
            clauses.append("at >= ?")
            values.append(start)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM incoming{where} ORDER BY at DESC, event_id DESC LIMIT ?",
                (*values, max(1, min(limit, 5000))),
            ).fetchall()
        return [self._item(row) for row in rows]

    def get(self, event_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM incoming WHERE event_id = ?", (event_id,)
            ).fetchone()
        return self._item(row) if row else None

    def history(self, app: str, key: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """The events of one condition (an app's key: its starts and ends), newest first."""

        if not key:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM incoming WHERE app = ? AND event_key = ?"
                " ORDER BY at DESC, event_id DESC LIMIT ?",
                (app, key, max(1, min(limit, 200))),
            ).fetchall()
        return [self._item(row) for row in rows]

    def counts(self, start: str) -> list[dict[str, Any]]:
        """How many events of each app and kind arrived since ``start``, most first."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT app, kind, COUNT(*) AS count, MAX(at) AS last,"
                " SUM(CASE WHEN rules_json != '[]' THEN 1 ELSE 0 END) AS counted"
                " FROM incoming WHERE at >= ? GROUP BY app, kind ORDER BY count DESC, kind",
                (start,),
            ).fetchall()
        return [dict(row) for row in rows]

    def since(self, start: str, kinds: list[str] | None = None) -> list[dict[str, Any]]:
        """Events since ``start``, oldest first (a rule's "Try it")."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM incoming WHERE at >= ? ORDER BY at, event_id LIMIT 20000", (start,)
            ).fetchall()
        return [self._item(row) for row in rows]
