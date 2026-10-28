"""Persistence of the loop portfolio: its OPC UA historian and the dynamic state of each loop."""

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


HISTORY_RETENTION = timedelta(days=2)
