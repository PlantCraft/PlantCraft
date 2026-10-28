import asyncio
import json
import socket
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from asyncua import Client, ua

from simcraft.engine import Observation
from simcraft.server import (
    HEALTH_NODE_ID,
    NAMESPACE_URI,
    OpcUaPlantServer,
    _data_value,
)
from simcraft.storage import BulkHistorySQLite


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_opcua_value_preserves_source_and_server_time_semantics() -> None:
    server_timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    source_timestamp = server_timestamp + timedelta(seconds=7)
    observation = Observation(
        signal_id="SIG-0001",
        node_id="ns=2;s=Plant.ControlLoops.FIC-101.PV",
        timestamp=source_timestamp,
        value=1.0,
        quality="UNCERTAIN",
        engineering_unit="m³/h",
    )
    signal = next(
        item
        for item in OpcUaPlantServer(history_hours=0).catalog.signals
        if item.signal_id == observation.signal_id
    )
    value = _data_value(observation, signal, server_timestamp)

    assert value.SourceTimestamp == source_timestamp.replace(tzinfo=None)
    assert value.ServerTimestamp == server_timestamp.replace(tzinfo=None)


@pytest.mark.parametrize(
    ("quality", "status"),
    [
        ("GOOD", ua.StatusCodes.Good),
        ("UNCERTAIN", ua.StatusCodes.Uncertain),
        ("BAD", ua.StatusCodes.Bad),
        ("BAD_NO_COMMUNICATION", ua.StatusCodes.BadNoCommunication),
    ],
)
def test_all_declared_quality_states_map_to_opcua_status_codes(
    quality: str,
    status: int,
) -> None:
    signal = OpcUaPlantServer(history_hours=0).catalog.signals[0]
    observation = Observation(
        signal_id=signal.signal_id,
        node_id=signal.opcua_node_id,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        value=1.0,
        quality=quality,
        engineering_unit=signal.engineering_unit,
    )

    assert _data_value(observation, signal).StatusCode.value == status


def test_opcua_server_publishes_all_nodes_and_supports_current_reads(tmp_path: Path) -> None:
    async def exercise() -> tuple[int, float, str]:
        port = _free_port()
        endpoint = f"opc.tcp://127.0.0.1:{port}/plantcraft/"
        server = OpcUaPlantServer(
            endpoint=endpoint,
            history_db=tmp_path / "history.sqlite3",
            history_hours=0,
            sample_seconds=5,
            reset=True,
        )
        await server.start()
        try:
            async with Client(endpoint, timeout=3) as client:
                namespace = await client.get_namespace_index(NAMESPACE_URI)
                node = client.get_node(ua.NodeId("Plant.ControlLoops.FIC-101.PV", namespace))
                value = await node.read_value()
                unit_children = await node.get_properties()
                properties = {
                    await item.read_browse_name(): await item.read_value() for item in unit_children
                }
                engineering_unit = next(
                    value for name, value in properties.items() if name.Name == "EngineeringUnit"
                )
                return len(server.nodes), float(value), str(engineering_unit)
        finally:
            await server.stop()

    node_count, value, engineering_unit = asyncio.run(exercise())
    assert node_count == 500
    assert value >= 0
    assert engineering_unit == "m³/h"


def test_realtime_publication_advances_the_health_timestamp(tmp_path: Path) -> None:
    async def exercise() -> tuple[datetime | None, datetime | None]:
        port = _free_port()
        endpoint = f"opc.tcp://127.0.0.1:{port}/plantcraft/"
        server = OpcUaPlantServer(
            endpoint=endpoint,
            history_db=tmp_path / "history.sqlite3",
            history_hours=0,
            sample_seconds=1,
            reset=True,
        )
        await server.start()
        try:
            async with Client(endpoint, timeout=3) as client:
                namespace = await client.get_namespace_index(NAMESPACE_URI)
                node = client.get_node(ua.NodeId(HEALTH_NODE_ID, namespace))
                first = await node.read_data_value()
                second = first
                for _ in range(70):
                    await asyncio.sleep(0.1)
                    second = await node.read_data_value()
                    if second.SourceTimestamp != first.SourceTimestamp:
                        break
                return first.SourceTimestamp, second.SourceTimestamp
        finally:
            await server.stop()

    first, second = asyncio.run(exercise())
    assert first is not None
    assert second is not None
    assert second > first


def test_history_continuation_quality_ranges_and_restart_are_interoperable(
    tmp_path: Path,
) -> None:
    async def exercise() -> tuple[int, int, int]:
        port = _free_port()
        endpoint = f"opc.tcp://127.0.0.1:{port}/plantcraft/"
        database = tmp_path / "history.sqlite3"
        fixed_wall_time = datetime(2026, 9, 6, 12, tzinfo=UTC)
        options = {
            "endpoint": endpoint,
            "history_db": database,
            "history_hours": 600 / 3_600,
            "sample_seconds": 30,
            "scenario_cycle_seconds": 600,
            "max_history_values_per_node": 2,
            "seed": 31,
            "wall_clock": lambda: fixed_wall_time,
        }
        server = OpcUaPlantServer(**options, reset=True)
        await server.start()
        assert server.simulator is not None
        start = server.simulator.start_at
        end = start + timedelta(seconds=600)
        fic_table = server.history._get_table_name(server.nodes["SIG-0001"].nodeid)
        try:
            async with Client(endpoint, timeout=5) as client:
                namespace = await client.get_namespace_index(NAMESPACE_URI)
                regular = client.get_node(ua.NodeId("Plant.ControlLoops.FIC-101.PV", namespace))
                values = await regular.read_raw_history(
                    starttime=start,
                    endtime=end,
                    numvalues=0,
                    return_bounds=False,
                )
                assert len(values) == 20
                assert [item.SourceTimestamp for item in values] == sorted(
                    item.SourceTimestamp for item in values
                )
                reverse = await regular.read_raw_history(
                    starttime=end,
                    endtime=start,
                    numvalues=0,
                    return_bounds=False,
                )
                assert [item.SourceTimestamp for item in reverse] == list(
                    reversed([item.SourceTimestamp for item in values])
                )
                empty = await regular.read_raw_history(
                    starttime=end + timedelta(days=1),
                    endtime=end + timedelta(days=2),
                    numvalues=0,
                    return_bounds=False,
                )
                assert empty == []

                irregular = client.get_node(ua.NodeId("Plant.ControlLoops.AIC-904.PV", namespace))
                irregular_values = await irregular.read_raw_history(
                    starttime=start,
                    endtime=end + timedelta(seconds=10),
                    numvalues=0,
                    return_bounds=False,
                )
                assert any(item.StatusCode.is_uncertain() for item in irregular_values)
                assert any(
                    item.SourceTimestamp != item.ServerTimestamp for item in irregular_values
                )
                assert any(item.StatusCode.is_good() for item in irregular_values)

                bad_quality = client.get_node(ua.NodeId("Plant.ControlLoops.PIC-605.PV", namespace))
                bad_values = await bad_quality.read_raw_history(
                    starttime=start,
                    endtime=end,
                    numvalues=0,
                    return_bounds=False,
                )
                assert any(item.StatusCode.is_bad() for item in bad_values)
                assert bad_values[-1].StatusCode.is_good()

                gap = client.get_node(ua.NodeId("Plant.ControlLoops.LIC-1002.PV", namespace))
                gap_values = await gap.read_raw_history(
                    starttime=start,
                    endtime=end,
                    numvalues=0,
                    return_bounds=False,
                )
                assert 0 < len(gap_values) < len(values)
                assert gap_values[-1].StatusCode.is_good()

                slower = client.get_node(
                    ua.NodeId("Plant.Areas.FEED.Equipment.FH-101.TEMPERATURE", namespace)
                )
                slower_values = await slower.read_raw_history(
                    starttime=start,
                    endtime=end,
                    numvalues=0,
                    return_bounds=False,
                )
                assert len(slower_values) == 10
        finally:
            await server.stop()

        with sqlite3.connect(database) as connection:
            first_count = connection.execute(f'SELECT COUNT(*) FROM "{fic_table}"').fetchone()[0]
            first_distinct = connection.execute(
                f'SELECT COUNT(DISTINCT SourceTimestamp) FROM "{fic_table}"'
            ).fetchone()[0]

        restarted = OpcUaPlantServer(**options, reset=False)
        await restarted.start()
        await restarted.stop()
        with sqlite3.connect(database) as connection:
            second_count = connection.execute(f'SELECT COUNT(*) FROM "{fic_table}"').fetchone()[0]
            second_distinct = connection.execute(
                f'SELECT COUNT(DISTINCT SourceTimestamp) FROM "{fic_table}"'
            ).fetchone()[0]
        mismatch_options = {**options, "sample_seconds": 10}
        mismatched = OpcUaPlantServer(**mismatch_options, reset=False)
        with pytest.raises(ValueError, match="checkpoint mismatch: sample_seconds"):
            await mismatched.start()
        assert mismatched.history is None
        return first_count, second_count, second_distinct - first_distinct

    first_count, second_count, new_distinct = asyncio.run(exercise())
    assert second_count == first_count
    assert new_distinct == 0


def test_restart_advances_across_downtime_without_fabricating_intermediate_history(
    tmp_path: Path,
) -> None:
    async def exercise() -> tuple[datetime, datetime, int]:
        port = _free_port()
        endpoint = f"opc.tcp://127.0.0.1:{port}/plantcraft/"
        database = tmp_path / "history.sqlite3"
        wall_time = [datetime(2026, 9, 4, 12, tzinfo=UTC)]
        options = {
            "endpoint": endpoint,
            "history_db": database,
            "history_hours": 60 / 3_600,
            "sample_seconds": 5,
            "seed": 31,
            "wall_clock": lambda: wall_time[0],
        }
        server = OpcUaPlantServer(**options, reset=True)
        await server.start()
        table = server.history._get_table_name(server.nodes["SIG-0001"].nodeid)
        await server.stop()
        with sqlite3.connect(database) as connection:
            before = datetime.fromisoformat(
                connection.execute(f'SELECT MAX(SourceTimestamp) FROM "{table}"').fetchone()[0]
            )

        wall_time[0] += timedelta(minutes=10)
        restarted = OpcUaPlantServer(**options, reset=False)
        await restarted.start()
        await restarted.stop()
        with sqlite3.connect(database) as connection:
            after_text, count = connection.execute(
                f'SELECT MAX(SourceTimestamp), COUNT(*) FROM "{table}"'
            ).fetchone()
        return before, datetime.fromisoformat(after_text), count

    before, after, count = asyncio.run(exercise())
    assert before == datetime.fromisoformat("2026-09-04T12:00:00")
    assert after == datetime.fromisoformat("2026-09-04T12:10:00")
    assert count == 1


def test_restart_repairs_checkpoint_outside_the_sampling_lattice(
    tmp_path: Path,
) -> None:
    async def exercise() -> tuple[float, bool]:
        port = _free_port()
        endpoint = f"opc.tcp://127.0.0.1:{port}/plantcraft/"
        database = tmp_path / "history.sqlite3"
        wall_time = [datetime(2026, 9, 4, 12, tzinfo=UTC)]
        options = {
            "endpoint": endpoint,
            "history_db": database,
            "history_hours": 60 / 3_600,
            "sample_seconds": 5,
            "seed": 31,
            "wall_clock": lambda: wall_time[0],
        }
        server = OpcUaPlantServer(**options, reset=True)
        await server.start()
        await server.stop()

        with sqlite3.connect(database) as connection:
            payload = json.loads(
                connection.execute(
                    "SELECT Payload FROM SimulatorCheckpoint WHERE Identity = 1"
                ).fetchone()[0]
            )
            payload["elapsed_seconds"] = 61.0
            connection.execute(
                "UPDATE SimulatorCheckpoint SET Payload = ? WHERE Identity = 1",
                (json.dumps(payload, separators=(",", ":"), sort_keys=True),),
            )
            connection.commit()

        restarted = OpcUaPlantServer(**options, reset=False)
        await restarted.start()
        assert restarted.simulator is not None
        repaired_elapsed = restarted.simulator.elapsed_seconds
        next_frame = restarted.simulator.advance(restarted.sample_seconds)
        await restarted.stop()
        return repaired_elapsed, bool(next_frame.observations)

    repaired_elapsed, publishes_on_lattice = asyncio.run(exercise())
    assert repaired_elapsed == 65.0
    assert repaired_elapsed % 5 == 0
    assert publishes_on_lattice


def test_incomplete_historian_requires_explicit_reset(tmp_path: Path) -> None:
    async def exercise() -> None:
        database = tmp_path / "incomplete.sqlite3"
        storage = BulkHistorySQLite(database)
        await storage.init()
        node_id = ua.NodeId("Plant.ControlLoops.FIC-101.PV", 2)
        await storage.new_historized_node(node_id, period=None, count=0)
        stamp = datetime(2026, 1, 1, tzinfo=UTC)
        await storage.save_node_values(
            node_id,
            (
                ua.DataValue(
                    ua.Variant(1.0, ua.VariantType.Double),
                    SourceTimestamp=stamp,
                    ServerTimestamp=stamp,
                ),
            ),
        )
        await storage.stop()

        endpoint = f"opc.tcp://127.0.0.1:{_free_port()}/plantcraft/"
        server = OpcUaPlantServer(
            endpoint=endpoint,
            history_db=database,
            history_hours=0,
            reset=False,
        )
        with pytest.raises(ValueError, match="without a complete simulator checkpoint"):
            await server.start()
        assert server.history is None

    asyncio.run(exercise())
