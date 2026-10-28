import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from asyncua import ua

from simcraft.storage import BulkHistorySQLite


def _value(timestamp: datetime, number: float, status: int = ua.StatusCodes.Good) -> ua.DataValue:
    return ua.DataValue(
        ua.Variant(number, ua.VariantType.Double),
        StatusCode_=ua.StatusCode(status),
        SourceTimestamp=timestamp,
        ServerTimestamp=timestamp + timedelta(seconds=1),
    )


def test_history_bounds_order_continuation_and_empty_range(tmp_path: Path) -> None:
    async def exercise() -> None:
        storage = BulkHistorySQLite(tmp_path / "history.sqlite3", max_history_data_response_size=2)
        await storage.init()
        node_id = ua.NodeId("Plant.ControlLoops.FIC-101.PV", 2)
        await storage.new_historized_node(node_id, period=None, count=0)
        start = datetime(2026, 1, 1, tzinfo=UTC)
        values = [_value(start + timedelta(seconds=10 * index), index) for index in range(4)]
        await storage.save_node_values(node_id, values)

        first, continuation = await storage.read_node_history(
            node_id, start, start + timedelta(seconds=30), 0
        )
        assert [item.Value.Value for item in first] == [0.0, 1.0]
        assert continuation == (start + timedelta(seconds=20)).replace(tzinfo=None)
        second, continuation = await storage.read_node_history(
            node_id, continuation, start + timedelta(seconds=30), 0
        )
        assert [item.Value.Value for item in second] == [2.0, 3.0]
        assert continuation is None

        reverse, continuation = await storage.read_node_history(
            node_id, start + timedelta(seconds=30), start, 0
        )
        assert [item.Value.Value for item in reverse] == [3.0, 2.0]
        assert continuation == (start + timedelta(seconds=10)).replace(tzinfo=None)

        empty, continuation = await storage.read_node_history(
            node_id,
            start + timedelta(days=1),
            start + timedelta(days=2),
            0,
        )
        assert empty == []
        assert continuation is None
        await storage.stop()

    asyncio.run(exercise())


def test_history_preserves_status_timestamps_retention_and_checkpoint(tmp_path: Path) -> None:
    async def exercise() -> None:
        storage = BulkHistorySQLite(
            tmp_path / "history.sqlite3",
            max_history_data_response_size=10,
            retention_seconds=20,
        )
        await storage.init()
        node_id = ua.NodeId("Plant.ControlLoops.AIC-904.PV", 2)
        await storage.new_historized_node(node_id, period=None, count=0)
        start = datetime(2026, 1, 1, tzinfo=UTC)
        values = [
            _value(start + timedelta(seconds=10 * index), index, ua.StatusCodes.Uncertain)
            for index in range(4)
        ]
        await storage.save_node_values(node_id, (item for item in values), commit=False)
        checkpoint = {"schema": "test", "elapsed_seconds": 30.0}
        await storage.save_checkpoint(checkpoint, commit=False)
        await storage.commit_pending()

        retained, continuation = await storage.read_node_history(
            node_id, start, start + timedelta(seconds=30), 0
        )
        assert [item.Value.Value for item in retained] == [1.0, 2.0, 3.0]
        assert all(item.StatusCode.is_uncertain() for item in retained)
        assert retained[0].SourceTimestamp == (start + timedelta(seconds=10)).replace(tzinfo=None)
        assert retained[0].ServerTimestamp == (start + timedelta(seconds=11)).replace(tzinfo=None)
        assert continuation is None
        assert await storage.load_checkpoint() == checkpoint
        assert await storage.has_historical_values() is True
        await storage.stop()

    asyncio.run(exercise())


def test_bulk_bootstrap_can_defer_redundant_retention_deletes(tmp_path: Path) -> None:
    async def exercise() -> None:
        storage = BulkHistorySQLite(
            tmp_path / "history.sqlite3",
            max_history_data_response_size=10,
            retention_seconds=20,
        )
        await storage.init()
        node_id = ua.NodeId("Plant.ControlLoops.FIC-101.PV", 2)
        await storage.new_historized_node(node_id, period=None, count=0)
        start = datetime(2026, 1, 1, tzinfo=UTC)
        values = [_value(start + timedelta(seconds=10 * index), index) for index in range(4)]

        await storage.save_node_values(node_id, values, enforce_retention=False)

        retained, continuation = await storage.read_node_history(
            node_id, start, start + timedelta(seconds=30), 0
        )
        assert [item.Value.Value for item in retained] == [0.0, 1.0, 2.0, 3.0]
        assert continuation is None
        await storage.stop()

    asyncio.run(exercise())


def test_historized_nodes_index_source_timestamps_for_bounded_retention(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        storage = BulkHistorySQLite(
            tmp_path / "history.sqlite3",
            retention_seconds=86_400,
        )
        await storage.init()
        node_id = ua.NodeId("Plant.ControlLoops.FIC-101.PV", 2)
        await storage.new_historized_node(node_id, period=None, count=0)
        table = storage._get_table_name(node_id)

        async with storage._db.execute(f'PRAGMA index_list("{table}")') as cursor:
            indexes = await cursor.fetchall()
        assert len(indexes) == 1

        async with storage._db.execute(
            f'EXPLAIN QUERY PLAN DELETE FROM "{table}" WHERE "SourceTimestamp" < ?',
            ("2026-01-01 00:00:00.000000",),
        ) as cursor:
            plan = " ".join(str(value) for row in await cursor.fetchall() for value in row)
        assert "USING" in plan
        assert "SourceTimestamp" in plan
        await storage.stop()

    asyncio.run(exercise())
