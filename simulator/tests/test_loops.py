"""The 50-loop portfolio (from PlantCraft's demo simulator) and its OPC UA server."""

from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from asyncua import Client, ua

from simcraft.cli import main
from simcraft.contracts import NAMESPACE_URI
from simcraft.loops import LOOP_DEFINITIONS, initial_state, loop_catalog, simulate_step
from simcraft.loops.storage import SimulatorStateStore

FIRST_LOOP_PV = "CPM.Loops.FIC-1001.PV"


def test_portfolio_has_fifty_loops_with_ten_distinct_behaviours() -> None:
    assert len(LOOP_DEFINITIONS) == 50
    assert len({item.loop_id for item in LOOP_DEFINITIONS}) == 50
    assert len({item.behavior for item in LOOP_DEFINITIONS}) == 10
    assert sum(len(item.signal_names) for item in LOOP_DEFINITIONS) == 205
    assert sum(item.has_secondary for item in LOOP_DEFINITIONS) == 5


def test_simulated_signals_are_deterministic_and_bounded() -> None:
    stamp = datetime(2026, 1, 1, 12, tzinfo=UTC)
    for definition in LOOP_DEFINITIONS:
        first = simulate_step(definition, initial_state(definition), stamp, 30)
        second = simulate_step(definition, initial_state(definition), stamp, 30)
        assert first == second
        assert 0 <= float(first["OP"]) <= 100
        assert first["MODE"] in {"AUTO", "MAN"}
        assert set(first) == set(definition.signal_names)


def test_reference_values_match_the_processcraft_demo_simulator() -> None:
    """Pinned from processcraft/simulator/dynamics.py before the move, so nothing drifted."""

    stamp = datetime(2026, 1, 1, 12, tzinfo=UTC)
    by_id = {item.loop_id: item for item in LOOP_DEFINITIONS}
    state = initial_state(by_id["PIC-1002"])
    for step in range(120):
        values = simulate_step(by_id["PIC-1002"], state, stamp + timedelta(seconds=30 * step), 30)
    assert values == REFERENCE_PIC_1002_AFTER_ONE_HOUR


REFERENCE_PIC_1002_AFTER_ONE_HOUR: dict[str, float | str] = {
    "PV": 51.544385,
    "SP": 52.0,
    "OP": 53.305943,
    "MODE": "AUTO",
}


def test_catalog_lists_every_tag_once(capsys: pytest.CaptureFixture[str]) -> None:
    catalog = loop_catalog()
    tags = [tag for loop in catalog for tag in loop["signals"].values()]
    assert len(catalog) == 50
    assert len(tags) == len(set(tags)) == 205
    assert catalog[0]["signals"]["pv"] == FIRST_LOOP_PV

    assert main(["loops", "catalog"]) == 0
    assert FIRST_LOOP_PV in capsys.readouterr().out


def test_state_store_round_trip(tmp_path: Path) -> None:
    store = SimulatorStateStore(tmp_path / "state.sqlite3")
    stamp = datetime(2026, 1, 1, 12, tzinfo=UTC)
    states = {item.loop_id: initial_state(item) for item in LOOP_DEFINITIONS[:3]}
    simulate_step(LOOP_DEFINITIONS[0], states[LOOP_DEFINITIONS[0].loop_id], stamp, 30)
    store.save(stamp, states)

    loaded_at, loaded = store.load()
    assert loaded_at == stamp
    assert loaded == states
    store.clear()
    assert store.load() == (None, {})


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            pytest.fail(f"loop server exited with code {process.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    pytest.fail("loop server did not open its port in time")


async def _read_history_and_live(endpoint: str) -> tuple[int, datetime, datetime]:
    async with Client(endpoint, timeout=5) as client:
        namespace = await client.get_namespace_index(NAMESPACE_URI)
        node = client.get_node(ua.NodeId(FIRST_LOOP_PV, namespace))
        now = datetime.now(UTC)
        history = await node.read_raw_history(now - timedelta(minutes=10), now)
        first = (await node.read_data_value()).SourceTimestamp
        await asyncio.sleep(1.5)
        second = (await node.read_data_value()).SourceTimestamp
    return len(history), first, second


def test_opcua_history_and_live_values_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    port = _free_port()
    endpoint = f"opc.tcp://127.0.0.1:{port}/plantcraft/"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "simcraft",
            "loops",
            "serve",
            "--endpoint",
            endpoint,
            "--history-db",
            str(tmp_path / "history.sqlite3"),
            "--state-db",
            str(tmp_path / "state.sqlite3"),
            "--history-hours",
            "0.1",
            "--history-sample-seconds",
            "30",
            "--realtime-seconds",
            "0.5",
            "--historian-seconds",
            "0.5",
            "--reset",
            "--log-level",
            "WARNING",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_port(port, process)
        count, first, second = asyncio.run(_read_history_and_live(endpoint))
        assert count >= 10
        assert second > first

        from simcraft.healthcheck import main as healthcheck

        monkeypatch.setenv("SIMCRAFT_HEALTH_ENDPOINT", endpoint)
        assert healthcheck() == 0
        monkeypatch.setenv("SIMCRAFT_NAMESPACE_URI", "urn:processcraft:simulator")
        assert healthcheck() == 1
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
