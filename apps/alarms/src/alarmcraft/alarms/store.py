"""Alarms, their state, every occurrence and the alarm journal.

| Table | Holds |
|---|---|
| ``alarms`` | the alarm's configuration (``AlarmDraft``, written from its rule), the monitor's evaluation state, and the operator's part: acknowledged, shelved until |
| ``occurrences`` | one row per time an alarm was raised: start, end, acknowledgement, peak, alarm or notice (kept 400 days) |
| ``journal`` | every raise, clear, acknowledgement, shelve and change, in order (kept 400 days) |

The monitor owns ``state_json``; people own ``acked`` and the shelve columns. Each side writes
only its own columns, so an acknowledgement made while a cycle runs is never lost.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from plantcraft_sdk.server.store import Migration, Store, add_columns

from alarmcraft.alarms.records import (
    ALARM_ID,
    KEEP_DAYS,
    Conflict,
    slug,
)


class AlarmStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS alarms (
        alarm_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        config_json TEXT NOT NULL,
        state_json TEXT NOT NULL DEFAULT '{}',
        acked INTEGER NOT NULL DEFAULT 1,
        acked_at TEXT,
        acked_by TEXT,
        shelved_until TEXT,
        shelved_by TEXT,
        shelve_reason TEXT,
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS occurrences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        alarm_id TEXT NOT NULL,
        name TEXT NOT NULL,
        priority TEXT NOT NULL,
        kind TEXT NOT NULL,
        alarm_limit REAL,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        acked_at TEXT,
        acked_by TEXT,
        start_value REAL,
        peak REAL
    );
    CREATE INDEX IF NOT EXISTS occurrences_started ON occurrences (started_at);
    CREATE INDEX IF NOT EXISTS occurrences_alarm ON occurrences (alarm_id, started_at);
    CREATE TABLE IF NOT EXISTS journal (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        at TEXT NOT NULL,
        alarm_id TEXT NOT NULL,
        name TEXT NOT NULL,
        priority TEXT NOT NULL DEFAULT '',
        action TEXT NOT NULL,
        by TEXT NOT NULL DEFAULT '',
        value REAL,
        detail TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS journal_at ON journal (at);
    CREATE INDEX IF NOT EXISTS journal_alarm ON journal (alarm_id, at);
    """

    # Changes to tables already shipped (PlantCraft docs/upgrades: never renamed or removed).
    # Occurrences from before rules (alarmcraft 0.3.0 and older) were all alarms.
    MIGRATIONS = (
        Migration(
            "columns-before-0.5",
            add_columns(
                "occurrences",
                {"creates": "TEXT NOT NULL DEFAULT 'alarm'", "rule_id": "TEXT NOT NULL DEFAULT ''"},
            ),
        ),
    )

    def _row(self, row: Any) -> dict[str, Any]:
        item = self._row_with_json(
            row, {"config": ("config_json", {}), "state": ("state_json", {})}
        )
        item["acked"] = bool(item.get("acked"))
        return {**item.pop("config"), **item}

    # Alarms ----------------------------------------------------------------------------

    def list(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM alarms ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [self._row(row) for row in rows]

    def get(self, alarm_id: str) -> dict[str, Any] | None:
        if not ALARM_ID.match(alarm_id or ""):
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM alarms WHERE alarm_id = ?", (alarm_id,)
            ).fetchone()
        return self._row(row) if row else None

    def create(self, config: dict[str, Any], *, by: str) -> dict[str, Any]:
        now = self._now()
        with self._lock, self._connect() as connection:
            base = slug(config["name"])
            alarm_id, number = base, 2
            while connection.execute(
                "SELECT 1 FROM alarms WHERE alarm_id = ?", (alarm_id,)
            ).fetchone():
                alarm_id, number = f"{base}-{number}", number + 1
            connection.execute(
                "INSERT INTO alarms (alarm_id, name, config_json, created_at, created_by,"
                " updated_at, updated_by) VALUES (?,?,?,?,?,?,?)",
                (alarm_id, config["name"], self._json(config), now, by, now, by),
            )
        return self.get(alarm_id) or {}

    def put(self, alarm_id: str, config: dict[str, Any], *, by: str) -> dict[str, Any]:
        """A rule's alarm with its own id (``rules.alarm_id_for``); kept when it exists."""

        now = self._now()
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO alarms (alarm_id, name, config_json, created_at, created_by,"
                " updated_at, updated_by) VALUES (?,?,?,?,?,?,?)",
                (alarm_id, config["name"], self._json(config), now, by, now, by),
            )
        return self.get(alarm_id) or {}

    def of_rule(self, rule_id: str) -> list[dict[str, Any]]:
        return [alarm for alarm in self.list() if alarm.get("rule_id") == rule_id]

    def update(
        self,
        alarm_id: str,
        config: dict[str, Any],
        *,
        by: str,
        base_updated_at: str | None = None,
        reset_state: bool = False,
    ) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT updated_at FROM alarms WHERE alarm_id = ?", (alarm_id,)
            ).fetchone()
            if row is None:
                return None
            if base_updated_at and base_updated_at != row["updated_at"]:
                raise Conflict(alarm_id)
            connection.execute(
                "UPDATE alarms SET name = ?, config_json = ?, updated_at = ?, updated_by = ?"
                + (", state_json = '{}', acked = 1" if reset_state else "")
                + " WHERE alarm_id = ?",
                (config["name"], self._json(config), self._now(), by, alarm_id),
            )
        return self.get(alarm_id)

    def delete(self, alarm_id: str) -> bool:
        with self._lock, self._connect() as connection:
            gone = connection.execute("DELETE FROM alarms WHERE alarm_id = ?", (alarm_id,)).rowcount
        return bool(gone)

    def set_state(self, alarm_id: str, state: dict[str, Any], *, raised: bool = False) -> None:
        """The monitor's write: its evaluation state; a new raise also needs a new acknowledgement."""

        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE alarms SET state_json = ?"
                + (", acked = 0, acked_at = NULL, acked_by = NULL" if raised else "")
                + " WHERE alarm_id = ?",
                (self._json(state), alarm_id),
            )

    def acknowledge(self, alarm_id: str, *, by: str, at: str) -> bool:
        """Acknowledge the alarm and its open or last occurrence. False when nothing to acknowledge."""

        with self._lock, self._connect() as connection:
            changed = connection.execute(
                "UPDATE alarms SET acked = 1, acked_at = ?, acked_by = ? WHERE alarm_id = ?"
                " AND acked = 0",
                (at, by, alarm_id),
            ).rowcount
            if changed:
                connection.execute(
                    "UPDATE occurrences SET acked_at = ?, acked_by = ? WHERE id = (SELECT id FROM"
                    " occurrences WHERE alarm_id = ? AND acked_at IS NULL ORDER BY started_at DESC"
                    " LIMIT 1)",
                    (at, by, alarm_id),
                )
        return bool(changed)

    def shelve(self, alarm_id: str, *, until: str | None, by: str, reason: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE alarms SET shelved_until = ?, shelved_by = ?, shelve_reason = ?"
                " WHERE alarm_id = ?",
                (until, by if until else None, reason if until else None, alarm_id),
            )

    # Occurrences -----------------------------------------------------------------------

    def open_occurrence(self, alarm: dict[str, Any], at: str, value: float | None) -> int:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO occurrences (alarm_id, name, priority, kind, alarm_limit, started_at,"
                " start_value, peak, creates, rule_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    alarm["alarm_id"],
                    alarm["name"],
                    alarm.get("priority") or "medium",
                    alarm.get("kind") or "high",
                    alarm.get("limit"),
                    at,
                    value,
                    value,
                    alarm.get("creates") or "alarm",
                    alarm.get("rule_id") or "",
                ),
            )
            return int(cursor.lastrowid or 0)

    def close_occurrence(self, occurrence_id: int, at: str, peak: float | None) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE occurrences SET ended_at = ?, peak = COALESCE(?, peak) WHERE id = ?",
                (at, peak, occurrence_id),
            )

    def acknowledge_occurrence(self, occurrence_id: int, *, by: str, at: str) -> None:
        """Acknowledge one past occurrence (history replay); the alarm's own state is untouched."""

        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE occurrences SET acked_at = ?, acked_by = ? WHERE id = ?",
                (at, by, occurrence_id),
            )

    def set_peak(self, occurrence_id: int, peak: float | None) -> None:
        if peak is None:
            return
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE occurrences SET peak = ? WHERE id = ?", (peak, occurrence_id)
            )

    def occurrences(
        self,
        *,
        start: str | None = None,
        end: str | None = None,
        alarm_id: str | None = None,
        limit: int = 20000,
        creates: str | None = None,
    ) -> list[dict[str, Any]]:
        """Occurrences that overlap [start, end], newest first (only alarms, or only notices,
        with ``creates``)."""

        clauses, values = [], []
        if creates:
            clauses.append("creates = ?")
            values.append(creates)
        if start:
            clauses.append("(ended_at IS NULL OR ended_at >= ?)")
            values.append(start)
        if end:
            clauses.append("started_at <= ?")
            values.append(end)
        if alarm_id:
            clauses.append("alarm_id = ?")
            values.append(alarm_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM occurrences{where} ORDER BY started_at DESC, id DESC LIMIT ?",
                (*values, max(1, min(limit, 100000))),
            ).fetchall()
        found = []
        for row in rows:
            item = dict(row)
            item["limit"] = item.pop("alarm_limit")
            found.append(item)
        return found

    # Journal ---------------------------------------------------------------------------

    def log(
        self,
        alarm: dict[str, Any],
        action: str,
        *,
        at: str,
        by: str = "",
        value: float | None = None,
        detail: str = "",
    ) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat()
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO journal (at, alarm_id, name, priority, action, by, value, detail)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (
                    at,
                    alarm.get("alarm_id") or "",
                    alarm.get("name") or "",
                    alarm.get("priority") or "",
                    action,
                    by,
                    value,
                    detail[:500],
                ),
            )
            if action == "raised":
                connection.execute("DELETE FROM journal WHERE at < ?", (cutoff,))
                connection.execute(
                    "DELETE FROM occurrences WHERE ended_at IS NOT NULL AND ended_at < ?", (cutoff,)
                )

    def journal(
        self,
        *,
        alarm_id: str | None = None,
        start: str | None = None,
        end: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        clauses, values = [], []
        if alarm_id:
            clauses.append("alarm_id = ?")
            values.append(alarm_id)
        if start:
            clauses.append("at >= ?")
            values.append(start)
        if end:
            clauses.append("at <= ?")
            values.append(end)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM journal{where} ORDER BY at DESC, id DESC LIMIT ?",
                (*values, max(1, min(limit, 5000))),
            ).fetchall()
        return [dict(row) for row in rows]
