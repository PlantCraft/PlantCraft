"""Bounded SQLite historian support for the OPC UA server."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiosqlite
from asyncua import ua
from asyncua.common.sql_injection import validate_table_name
from asyncua.common.utils import Buffer
from asyncua.server.history_sql import HistorySQLite
from asyncua.ua.ua_binary import variant_from_binary, variant_to_binary


class BulkHistorySQLite(HistorySQLite):
    """Asyncua historian with explicit timestamps and transactional bulk inserts."""

    def __init__(
        self,
        path: str | Path,
        max_history_data_response_size: int = 10_000,
        retention_seconds: float | None = None,
    ) -> None:
        super().__init__(str(path), max_history_data_response_size)
        self.retention_seconds = retention_seconds

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self._db_file)
        await self._db.execute(
            "CREATE TABLE IF NOT EXISTS SimulatorCheckpoint ("
            "Identity INTEGER PRIMARY KEY CHECK (Identity = 1), Payload TEXT NOT NULL)"
        )
        await self._db.commit()

    async def new_historized_node(
        self,
        node_id: ua.NodeId,
        period: timedelta | None,
        count: int = 0,
    ) -> None:
        await super().new_historized_node(node_id, period, count)
        table = self._get_table_name(node_id)
        validate_table_name(table)
        index = f"HistorySource_{hashlib.sha256(table.encode()).hexdigest()[:16]}"
        validate_table_name(index)
        await self._db.execute(
            f'CREATE INDEX IF NOT EXISTS "{index}" ON "{table}" ("SourceTimestamp")'
        )
        await self._db.commit()

    async def load_checkpoint(self) -> dict[str, object] | None:
        async with self._db.execute(
            "SELECT Payload FROM SimulatorCheckpoint WHERE Identity = 1"
        ) as cursor:
            row = await cursor.fetchone()
        return None if row is None else json.loads(row[0])

    async def save_checkpoint(self, checkpoint: dict[str, object], *, commit: bool = True) -> None:
        payload = json.dumps(
            checkpoint,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        await self._db.execute(
            "INSERT INTO SimulatorCheckpoint (Identity, Payload) VALUES (1, ?) "
            "ON CONFLICT(Identity) DO UPDATE SET Payload = excluded.Payload",
            (payload,),
        )
        if commit:
            await self._db.commit()

    async def has_historical_values(self) -> bool:
        async with self._db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name != 'SimulatorCheckpoint'"
        ) as cursor:
            rows = await cursor.fetchall()
        for row in rows:
            table = row[0]
            validate_table_name(table)
            async with self._db.execute(f'SELECT 1 FROM "{table}" LIMIT 1') as cursor:
                if await cursor.fetchone() is not None:
                    return True
        return False

    async def save_node_values(
        self,
        node_id: ua.NodeId,
        values: Iterable[ua.DataValue],
        *,
        commit: bool = True,
        enforce_retention: bool = True,
    ) -> None:
        table = self._get_table_name(node_id)
        validate_table_name(table)
        selected_values = tuple(values)
        if any(
            value.SourceTimestamp is None or value.ServerTimestamp is None
            for value in selected_values
        ):
            raise ValueError("historical values require source and server timestamps")
        rows = [
            (
                self._encode(value.ServerTimestamp),
                self._encode(value.SourceTimestamp),
                value.StatusCode.value,
                str(value.Value.Value),
                value.Value.VariantType.name,
                sqlite3.Binary(variant_to_binary(value.Value)),
            )
            for value in selected_values
        ]
        if rows:
            await self._db.executemany(
                f'INSERT INTO "{table}" VALUES (NULL, ?, ?, ?, ?, ?, ?)',
                rows,
            )
            if enforce_retention and self.retention_seconds is not None:
                latest = max(
                    value.SourceTimestamp
                    for value in selected_values
                    if value.SourceTimestamp is not None
                )
                cutoff = latest - timedelta(seconds=self.retention_seconds)
                await self._db.execute(
                    f'DELETE FROM "{table}" WHERE "SourceTimestamp" < ?',
                    (self._encode(cutoff),),
                )
            if commit:
                await self._db.commit()

    async def commit_pending(self) -> None:
        await self._db.commit()

    async def rollback_pending(self) -> None:
        await self._db.rollback()

    async def read_node_history(
        self,
        node_id: ua.NodeId,
        start: datetime | None,
        end: datetime | None,
        nb_values: int,
    ) -> tuple[list[ua.DataValue], datetime | None]:
        table = self._get_table_name(node_id)
        order = "ASC"
        win_epoch = ua.get_win_epoch()
        if start is None or start == win_epoch:
            order = "DESC"
            start = win_epoch
        if end is None or end == win_epoch:
            end = datetime.now(UTC) + timedelta(days=1)
        normalized_start = self._utc_naive(start)
        normalized_end = self._utc_naive(end)
        if normalized_start < normalized_end:
            start_time, end_time = self._encode(start), self._encode(end)
        else:
            order = "DESC"
            start_time, end_time = self._encode(end), self._encode(start)
        requested = nb_values if nb_values else self.max_history_data_response_size + 1
        limit = min(requested, self.max_history_data_response_size + 1)
        validate_table_name(table)
        results: list[ua.DataValue] = []
        async with self._db.execute(
            f'SELECT * FROM "{table}" WHERE "SourceTimestamp" BETWEEN ? AND ? '
            f'ORDER BY "_Id" {order} LIMIT ?',
            (start_time, end_time, limit),
        ) as cursor:
            async for row in cursor:
                results.append(
                    ua.DataValue(
                        variant_from_binary(Buffer(row[6])),
                        ServerTimestamp=self._decode(row[1]),
                        SourceTimestamp=self._decode(row[2]),
                        StatusCode_=ua.StatusCode(row[3]),
                    )
                )
        continuation = (
            results[self.max_history_data_response_size].SourceTimestamp
            if len(results) > self.max_history_data_response_size
            else None
        )
        return results[: self.max_history_data_response_size], continuation

    @staticmethod
    def _utc_naive(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=None)
        return value.astimezone(UTC).replace(tzinfo=None)

    @staticmethod
    def _encode(value: datetime | None) -> str | None:
        if value is None:
            return None
        return BulkHistorySQLite._utc_naive(value).isoformat(" ", timespec="microseconds")

    @staticmethod
    def _decode(value: str | None) -> datetime | None:
        return None if value is None else datetime.fromisoformat(value)
