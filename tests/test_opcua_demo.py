"""The OPC UA demo reads the Simulator's 50-loop portfolio (``simcraft loops serve``).

The Simulator is its own product (``simulator/``). The platform's CI does not install it, so the
round trip runs against the test server in ``tests/opcua_plant.py``; when the Simulator is
installed (``pip install -e simulator``), the scenario is also checked against its catalog and read from the real
server.
"""

from __future__ import annotations

import json
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import pytest

from processcraft.config import DataSourceConfig, load_scenario
from processcraft.industrial_data.sources import OpcUaHistoricalSource
from tests.opcua_plant import NAMESPACE_URI, FakePlantCraft, free_port

SCENARIO = "scenarios/opcua_demo.json"
# What a Simulator loop controls, from the first letter of its ISA 5.1 tag. Only the demo
# scenario's own loops are typed this way (in the file); a client's tags are never guessed.
ISA_LOOP_TYPES = {
    "F": "flow",
    "L": "level",
    "P": "pressure",
    "T": "temperature",
    "A": "composition",
}
# The Simulator's engineering unit of the PV, per loop type: its catalog's own metadata.
PV_UNITS = {
    "flow": {"m³/h", "t/h", "Nm³/h"},
    "level": {"%"},
    "pressure": {"bar"},
    "temperature": {"°C"},
    "composition": {"mol%", "ppm", "pH"},
}


def _source(endpoint: str, tags: list[str]) -> OpcUaHistoricalSource:
    return OpcUaHistoricalSource(
        DataSourceConfig(
            type="opcua",
            endpoint_url=endpoint,
            auth_type="anonymous",
            timezone="UTC",
            tags=tags,
        )
    )


def test_opcua_sources_default_to_the_plantcraft_namespace():
    config = DataSourceConfig(type="opcua", endpoint_url="opc.tcp://h:4840/", tags=["a"])
    assert config.namespace_uri == NAMESPACE_URI == "urn:processcraft:plantcraft"


def test_demo_scenario_lists_the_plantcraft_portfolio():
    scenario = load_scenario(SCENARIO)
    assert scenario.source.type == "opcua"
    assert scenario.source.namespace_uri == NAMESPACE_URI
    assert scenario.source.endpoint_url.endswith(":4840/plantcraft/")
    assert len(scenario.loops) == 50
    assert len(scenario.source.tags) == 205
    assert len(set(scenario.source.tags)) == 205
    assert sum(loop.signals.secondary is not None for loop in scenario.loops) == 5
    assert len({loop.area for loop in scenario.loops}) > 1
    for loop in scenario.loops:
        for role, tag in loop.signals.model_dump().items():
            if tag:
                assert tag == f"CPM.Loops.{loop.loop_id}.{role.upper()}", tag
                assert re.fullmatch(r"CPM\.Loops\.[A-Z]{3}-\d{4}\.[A-Z]+", tag)


def test_every_demo_loop_carries_its_loop_type():
    scenario = load_scenario(SCENARIO)
    types = {loop.loop_id: loop.metadata.get("loop_type") for loop in scenario.loops}
    assert all(kind == ISA_LOOP_TYPES[loop_id[0]] for loop_id, kind in types.items()), types
    counts = {kind: list(types.values()).count(kind) for kind in set(types.values())}
    assert counts == {"flow": 13, "level": 13, "pressure": 9, "temperature": 10, "composition": 5}
    listed = next(loop for loop in scenario.loops if loop.loop_id == "FIC-1001")
    assert listed.metadata["impact"], "the ten reference loops keep their own metadata"


def test_the_demo_records_get_their_loop_type(tmp_path, monkeypatch):
    """The sync fills each loop's record (CPMCraft picks a protocol from its loop_type)."""

    from fastapi.testclient import TestClient

    from processcraft.api.app import create_app

    payload = json.loads(open(SCENARIO, encoding="utf-8").read())
    payload["storage"]["sqlite_path"] = str(tmp_path / "workspace.sqlite3")
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("PLANTCRAFT_SCENARIO", str(path))
    monkeypatch.setenv("PLANTCRAFT_PREWARM_HISTORY", "false")
    # Nothing listens there: the loops are placed without reading the plant.
    monkeypatch.setenv(
        "PLANTCRAFT_OPCUA_ENDPOINT", f"opc.tcp://127.0.0.1:{free_port()}/plantcraft/"
    )
    with TestClient(create_app()) as client:
        store = client.app.state.runtime.workspace.assets
        records = {loop["loop_id"]: store.attributes(loop["loop_id"]) for loop in payload["loops"]}
    assert {loop_id: record.get("loop_type") for loop_id, record in records.items()} == {
        loop["loop_id"]: loop["metadata"]["loop_type"] for loop in payload["loops"]
    }


def test_demo_scenario_matches_the_installed_plantcraft():
    loops = pytest.importorskip("simcraft.loops", reason="the Simulator is not installed")
    catalog = loops.loop_catalog()
    scenario = load_scenario(SCENARIO)
    assert [loop.loop_id for loop in scenario.loops] == [item["loop_id"] for item in catalog]
    for loop, item in zip(scenario.loops, catalog, strict=True):
        signals = {role: tag for role, tag in loop.signals.model_dump().items() if tag}
        assert signals == item["signals"], loop.loop_id
        assert (loop.name, loop.area) == (item["name"], item["area"]), loop.loop_id
        assert item["pv_unit"] in PV_UNITS[loop.metadata["loop_type"]], loop.loop_id


def test_opcua_historical_access_round_trip():
    pytest.importorskip("asyncua")
    scenario = load_scenario(SCENARIO)
    with FakePlantCraft(scenario.loops) as plant:
        source = _source(plant.endpoint, scenario.source.tags)
        end = datetime.now(timezone.utc)
        first = source.read_range(end - timedelta(minutes=8), end, 30)
        assert source.failed_tags == []
        assert set(first.columns) == set(scenario.source.tags)
        assert len(first) >= 10
        plant.advance()
        second = source.read_window(10, 30)
        assert second.index.max() > first.index.max()
        assert source.failed_tags == []
        signals = {item.tag: item for item in source.list_signals()}
        assert set(signals) == set(scenario.source.tags)
        assert signals["CPM.Loops.FIC-1001.PV"].asset == "FIC-1001"
        assert signals["CPM.Loops.FIC-1001.MODE"].data_type == "text"


def _wait_for_port(port: int, process: subprocess.Popen, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            pytest.fail(f"The Simulator exited with code {process.returncode}.")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    pytest.fail("The Simulator was not ready in time.")


def test_round_trip_against_plantcraft(tmp_path):
    pytest.importorskip("asyncua")
    pytest.importorskip("simcraft.loops", reason="the Simulator is not installed")
    scenario = load_scenario(SCENARIO)
    port = free_port()
    endpoint = f"opc.tcp://127.0.0.1:{port}/plantcraft/"
    process = subprocess.Popen(
        [sys.executable, "-m", "simcraft", "loops", "serve", "--endpoint", endpoint]
        + ["--history-db", str(tmp_path / "history.sqlite3")]
        + ["--state-db", str(tmp_path / "state.sqlite3")]
        + ["--history-hours", "0.1", "--history-sample-seconds", "30"]
        + ["--realtime-seconds", "0.5", "--historian-seconds", "0.5"]
        + ["--reset", "--log-level", "WARNING"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_port(port, process, 60)
        source = _source(endpoint, scenario.source.tags)
        end = datetime.now(timezone.utc)
        first = source.read_range(end - timedelta(minutes=5), end, 30)
        assert source.failed_tags == []
        assert set(first.columns) == set(scenario.source.tags)
        first_end = first.index.max()
        time.sleep(1.2)
        second = source.read_window(10, 30)
        assert second.index.max() > first_end
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def test_the_demo_starts_an_app_of_your_own_by_its_address():
    import argparse

    import run_opcua_demo

    args = run_opcua_demo._parser().parse_args(["--app", "starter=http://127.0.0.1:9100/starter/"])
    assert args.app == [("starter", "http://127.0.0.1:9100/starter/")]
    for wrong in ("starter", "starter=/starter/", "starter=http://127.0.0.1/starter/"):
        with pytest.raises(argparse.ArgumentTypeError):
            run_opcua_demo._app_entry(wrong)
