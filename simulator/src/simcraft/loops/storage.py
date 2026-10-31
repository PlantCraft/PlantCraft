"""Persistence of the loop portfolio: its OPC UA historian and the dynamic state of each loop.

The state file also keeps the instructor's side of a training session, which no OPC UA client
sees:

| Table | Holds |
|---|---|
| ``simulator_state`` | each loop's dynamic state, saved every step |
| ``fault_log`` | when each scheduled fault began and what it held (the answer key's evidence) |
| ``snapshots`` | named copies of every loop's state, to restore a starting point |
| ``controls`` | one row: frozen, speed, the model clock's offset, a snapshot asked to restore |
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from asyncua import ua
from asyncua.common.sql_injection import validate_table_name
from asyncua.server.history_sql import HistorySQLite
from asyncua.ua.ua_binary import variant_to_binary

from .dynamics import LoopState


class LoopHistorySQLite(HistorySQLite):
    """Asyncua SQLite historian with an efficient deterministic backfill API."""

    def __init__(
        self,
        path: str = "history.db",
        max_history_data_response_size: int = 10_000,
        realtime_min_interval_seconds: float = 5.0,
    ) -> None:
        super().__init__(path, max_history_data_response_size)
        self.realtime_min_interval_seconds = max(
            float(realtime_min_interval_seconds),
            0.0,
        )
        self._last_realtime_timestamp: dict[ua.NodeId, datetime] = {}

    async def save_node_value(
        self,
        node_id: ua.NodeId,
        datavalue: ua.DataValue,
    ) -> None:
        """Downsample numeric realtime history without slowing live values."""

        stamp = datavalue.SourceTimestamp or datavalue.ServerTimestamp
        is_numeric = datavalue.Value.VariantType in {
            ua.VariantType.Float,
            ua.VariantType.Double,
        }
        previous = self._last_realtime_timestamp.get(node_id)
        if (
            is_numeric
            and stamp is not None
            and previous is not None
            and (stamp - previous).total_seconds() < self.realtime_min_interval_seconds
        ):
            return
        if stamp is not None:
            self._last_realtime_timestamp[node_id] = stamp
        await super().save_node_value(node_id, datavalue)

    async def save_node_values(
        self,
        node_id: ua.NodeId,
        values: Iterable[ua.DataValue],
        *,
        commit: bool = True,
    ) -> None:
        table = self._get_table_name(node_id)
        validate_table_name(table)
        rows = [
            (
                value.ServerTimestamp,
                value.SourceTimestamp,
                value.StatusCode.value,
                str(value.Value.Value),
                value.Value.VariantType.name,
                sqlite3.Binary(variant_to_binary(value.Value)),
            )
            for value in values
        ]
        if not rows:
            return
        await self._db.executemany(
            f'INSERT INTO "{table}" VALUES (NULL, ?, ?, ?, ?, ?, ?)',
            rows,
        )
        period, count = self._datachanges_period[node_id]
        if period:
            cutoff = (datetime.now(UTC) - period).replace(tzinfo=None)
            await self._db.execute(
                f'DELETE FROM "{table}" WHERE SourceTimestamp < ?',
                (cutoff,),
            )
        if count:
            await self._db.execute(
                f'DELETE FROM "{table}" WHERE "_Id" NOT IN '
                f'(SELECT "_Id" FROM "{table}" ORDER BY "_Id" DESC LIMIT ?)',
                (count,),
            )
        if commit:
            await self._db.commit()

    async def commit_pending(self) -> None:
        """Commit a group of bulk inserts as one historian transaction."""

        await self._db.commit()

    async def count_node_values(self, node_id: ua.NodeId) -> int:
        table = self._get_table_name(node_id)
        validate_table_name(table)
        async with self._db.execute(
            f'SELECT COUNT(*) FROM "{table}"',
        ) as cursor:
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def clear_node_values(self, node_id: ua.NodeId) -> None:
        table = self._get_table_name(node_id)
        validate_table_name(table)
        await self._db.execute(f'DELETE FROM "{table}"')
        await self._db.commit()


class SimulatorStateStore:
    """Persist dynamic states so server restarts continue instead of jumping."""

    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS simulator_state (
                    loop_id TEXT PRIMARY KEY,
                    simulated_at TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    schema_version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fault_log (
                    fault_id TEXT PRIMARY KEY,
                    loop_id TEXT NOT NULL,
                    fired_at TEXT NOT NULL,
                    seen_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS snapshots (
                    name TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    simulated_at TEXT NOT NULL,
                    states_json TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS controls (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    frozen INTEGER NOT NULL DEFAULT 0,
                    speed REAL NOT NULL DEFAULT 1,
                    offset_seconds REAL NOT NULL DEFAULT 0,
                    restore TEXT,
                    changed_at TEXT NOT NULL DEFAULT ''
                );
                INSERT OR IGNORE INTO controls (id) VALUES (1);
                """
            )

    def load(self) -> tuple[datetime | None, dict[str, LoopState]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT loop_id, simulated_at, state_json
                FROM simulator_state
                WHERE schema_version = ?
                """,
                (self.SCHEMA_VERSION,),
            ).fetchall()
        if not rows:
            return None, {}
        timestamps = [datetime.fromisoformat(row["simulated_at"]).astimezone(UTC) for row in rows]
        simulated_at = min(timestamps)
        states = {
            row["loop_id"]: LoopState.from_dict(json.loads(row["state_json"])) for row in rows
        }
        return simulated_at, states

    def save(self, simulated_at: datetime, states: dict[str, LoopState]) -> None:
        stamp = simulated_at.astimezone(UTC).isoformat()
        rows = [
            (
                loop_id,
                stamp,
                json.dumps(state.to_dict(), separators=(",", ":")),
                self.SCHEMA_VERSION,
            )
            for loop_id, state in states.items()
        ]
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO simulator_state
                    (loop_id, simulated_at, state_json, schema_version)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(loop_id) DO UPDATE SET
                    simulated_at = excluded.simulated_at,
                    state_json = excluded.state_json,
                    schema_version = excluded.schema_version
                """,
                rows,
            )

    def clear(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM simulator_state")
            connection.execute("DELETE FROM fault_log")

    # Faults: when each began (the answer key's "fired").

    def record_fault(self, fault_id: str, loop_id: str, at: datetime, seen: dict) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO fault_log (fault_id, loop_id, fired_at, seen_json)"
                " VALUES (?, ?, ?, ?)",
                (fault_id, loop_id, _stamp(at), json.dumps(seen, separators=(",", ":"))),
            )

    def fired(self) -> dict[str, dict]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM fault_log").fetchall()
        return {
            row["fault_id"]: {"at": row["fired_at"], **json.loads(row["seen_json"])} for row in rows
        }

    # Snapshots: a named copy of every loop's state.

    def save_snapshot(self, name: str, note: str = "") -> dict:
        name = snapshot_name(name)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT loop_id, simulated_at, state_json FROM simulator_state"
                " WHERE schema_version = ?",
                (self.SCHEMA_VERSION,),
            ).fetchall()
            if not rows:
                raise LookupError("no state to keep yet: start the simulator first")
            states = {row["loop_id"]: json.loads(row["state_json"]) for row in rows}
            at = min(row["simulated_at"] for row in rows)
            connection.execute(
                "INSERT INTO snapshots (name, created_at, simulated_at, states_json, note)"
                " VALUES (?, ?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET"
                " created_at = excluded.created_at, simulated_at = excluded.simulated_at,"
                " states_json = excluded.states_json, note = excluded.note",
                (name, _stamp(datetime.now(UTC)), at, json.dumps(states), note[:300]),
            )
        return {"name": name, "simulated_at": at, "loops": len(states)}

    def snapshots(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT name, created_at, simulated_at, note FROM snapshots ORDER BY name"
            ).fetchall()
        return [dict(row) for row in rows]

    def snapshot(self, name: str) -> dict[str, LoopState]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT states_json FROM snapshots WHERE name = ?", (name,)
            ).fetchone()
        if row is None:
            raise LookupError(f"no snapshot {name!r}")
        return {
            loop_id: LoopState.from_dict(state)
            for loop_id, state in json.loads(row["states_json"]).items()
        }

    def delete_snapshot(self, name: str) -> bool:
        with self._connect() as connection:
            return connection.execute("DELETE FROM snapshots WHERE name = ?", (name,)).rowcount > 0

    # Controls: freeze, speed, a restore asked for; the server reads them every step.

    def controls(self) -> dict:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM controls WHERE id = 1").fetchone()
        return {
            "frozen": bool(row["frozen"]),
            "speed": float(row["speed"]),
            "offset_seconds": float(row["offset_seconds"]),
            "restore": row["restore"],
            "changed_at": row["changed_at"],
        }

    def set_controls(self, **values) -> dict:
        allowed = {"frozen", "speed", "offset_seconds", "restore"}
        if set(values) - allowed:
            raise ValueError(f"unknown control(s) {sorted(set(values) - allowed)}")
        if "speed" in values and not MIN_SPEED <= float(values["speed"]) <= MAX_SPEED:
            raise ValueError(f"speed from {MIN_SPEED:g} to {MAX_SPEED:g}")
        if values.get("restore") is not None:
            self.snapshot(values["restore"])  # refuses an unknown name now, not at the server
        sets = ", ".join(f"{key} = ?" for key in values)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE controls SET {sets}, changed_at = ? WHERE id = 1",  # noqa: S608
                (*[int(v) if isinstance(v, bool) else v for v in values.values()],
                 _stamp(datetime.now(UTC))),
            )  # fmt: skip
        return self.controls()

    def take_restore(self) -> str | None:
        """The snapshot asked to restore, once (the request is cleared)."""

        with self._connect() as connection:
            row = connection.execute("SELECT restore FROM controls WHERE id = 1").fetchone()
            if row is None or not row["restore"]:
                return None
            connection.execute("UPDATE controls SET restore = NULL WHERE id = 1")
        return str(row["restore"])


MIN_SPEED = 1.0
MAX_SPEED = 20.0


def snapshot_name(name: str) -> str:
    name = (name or "").strip()
    if not name or len(name) > 60 or not all(ch.isalnum() or ch in "-_. " for ch in name):
        raise ValueError("a snapshot name is up to 60 letters, digits, spaces, - _ or .")
    return name


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


HISTORY_RETENTION = timedelta(days=2)
