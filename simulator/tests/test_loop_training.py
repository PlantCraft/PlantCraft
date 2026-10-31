"""Training on the loop portfolio: scheduled faults with a separate answer key (S1), named
snapshots, freeze and speed (S2), all driven from the state file, never over OPC UA."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from asyncua import Client, ua

from simcraft.cli import main
from simcraft.contracts import NAMESPACE_URI
from simcraft.loops import LOOP_DEFINITIONS, initial_state, simulate_step
from simcraft.loops.faults import (
    FaultScheduleError,
    active_faults,
    answer_key,
    answer_key_markdown,
    parse_schedule,
)
from simcraft.loops.server import LoopPortfolioServer
from simcraft.loops.storage import SimulatorStateStore
from tests.test_loops import _free_port, _wait_for_port

LOOPS = {item.loop_id for item in LOOP_DEFINITIONS}
FIC = next(item for item in LOOP_DEFINITIONS if item.loop_id == "FIC-1001")
T0 = datetime(2026, 11, 2, 13, tzinfo=UTC)


def schedule(*faults: dict) -> list:
    return parse_schedule({"faults": list(faults)}, LOOPS)


def fault(kind: str, minutes: float | None = 30, **fields) -> dict:
    return {"loop": "FIC-1001", "fault": kind, "start": "2026-11-02T13:10:00Z",
            "duration_minutes": minutes, **fields}  # fmt: skip


def run(faults, steps: int = 120, every: float = 10.0) -> list[dict]:
    """FIC-1001 over ``steps`` steps from T0 with ``faults``; each step's values and state."""

    state = initial_state(FIC)
    found = []
    for number in range(steps):
        moment = T0 + timedelta(seconds=every * number)
        values = simulate_step(FIC, state, moment, every, active_faults(faults, "FIC-1001", moment))
        found.append({**values, "valve": state.valve_position, "status": state.pv_status,
                      "at": moment})  # fmt: skip
    return found


def during(rows: list[dict], start: int = 61, stop: int = 120) -> list[dict]:
    return rows[start:stop]  # 13:10:10 to 13:20, inside the fault


def test_a_schedule_is_checked_entry_by_entry():
    found = schedule(fault("valve_stuck", id="A"), fault("load_step", magnitude=-5, id="B"))
    assert [item.fault_id for item in found] == ["A", "B"]
    assert found[0].end == T0 + timedelta(minutes=40)
    bad = [
        ({"faults": [fault("nope")]}, "is not one of"),
        ({"faults": [fault("valve_stuck", loop="X-1")]}, "no loop"),
        ({"faults": [fault("load_step")]}, "needs a magnitude"),
        ({"faults": [fault("valve_stuck", start="13:10")]}, "not a time"),
        ({"faults": [fault("valve_stuck", start="2026-11-02T13:10:00")]}, "needs its zone"),
        ({"faults": [fault("valve_stuck", duration_minutes=0)]}, "duration_minutes"),
        ({"faults": [fault("valve_stuck", id="A"), fault("sensor_frozen", id="A")]}, "twice"),
        ({"faults": [fault("valve_stuck", None), fault("valve_stuck", 5)]}, "overlaps"),
        ({"faults": [{**fault("manual"), "secret": 1}]}, "unknown field"),
        ({"items": []}, "a schedule is"),
    ]
    for payload, words in bad:
        with pytest.raises(FaultScheduleError, match=words):
            parse_schedule(payload, LOOPS)


def test_each_fault_shows_in_the_tags_as_its_textbook_symptom():
    clean = run([])
    stuck = run(schedule(fault("valve_stuck")))
    assert stuck[:60] == clean[:60]  # nothing before its start: deterministic
    assert len({round(row["valve"], 9) for row in during(stuck)}) == 1
    assert max(abs(row["OP"] - stuck[60]["OP"]) for row in during(stuck)) > 0.05  # OP moves

    frozen = run(schedule(fault("sensor_frozen")))
    assert len({row["PV"] for row in during(frozen)}) == 1

    biased = run(schedule(fault("sensor_bias", magnitude=4.0)))
    assert biased[61]["PV"] - clean[61]["PV"] == pytest.approx(4.0, abs=0.5)

    step = run(schedule(fault("load_step", magnitude=-8.0)))
    assert min(row["PV"] for row in during(step)) < min(row["PV"] for row in during(clean)) - 2

    manual = run(schedule(fault("manual")))
    assert {row["MODE"] for row in during(manual)} == {"MAN"}
    assert len({row["OP"] for row in during(manual)}) == 1

    bad = run(schedule(fault("bad_quality")))
    assert {row["status"] for row in during(bad)} == {"Bad"} and bad[59]["status"] == "Good"
    # After its end (13:40), the loop is itself again: the valve follows the output.
    after = run(schedule(fault("valve_stuck", 5)), steps=200)
    assert after[199]["valve"] == pytest.approx(after[199]["OP"])


def test_the_answer_key_is_apart_and_says_what_to_look_for(tmp_path: Path):
    faults = schedule(fault("valve_stuck", id="F1", note="Before the shift change"))
    key = answer_key(faults, {"F1": {"at": "2026-11-02T13:10:00+00:00", "pv": 55.1}})
    [item] = key["faults"]
    assert item["fired"]["pv"] == 55.1 and "OP keeps moving" in item["symptoms"]
    text = answer_key_markdown(key)
    assert "| F1 | FIC-1001 | valve_stuck | 2026-11-02T13:10:00Z | 2026-11-02T13:40:00Z" in text
    path = tmp_path / "faults.json"
    path.write_text(json.dumps({"faults": [fault("valve_stuck", id="F1")]}))
    assert main(["loops", "faults", "check", str(path)]) == 0
    state = str(tmp_path / "state.sqlite3")
    assert main(["loops", "faults", "key", str(path), "--state-db", state]) == 0
    path.write_text(json.dumps({"faults": [fault("nope")]}))
    assert main(["loops", "faults", "check", str(path)]) == 2


def test_snapshots_freeze_and_speed_are_kept_in_the_state_file(tmp_path: Path):
    db = str(tmp_path / "state.sqlite3")
    store = SimulatorStateStore(db)
    assert main(["loops", "snapshot", "save", "start", "--state-db", db]) == 2  # nothing yet
    states = {item.loop_id: initial_state(item) for item in LOOP_DEFINITIONS}
    store.save(T0, states)
    assert main(["loops", "snapshot", "save", "Start of shift", "--state-db", db]) == 0
    assert [item["name"] for item in store.snapshots()] == ["Start of shift"]
    assert main(["loops", "snapshot", "restore", "nope", "--state-db", db]) == 2
    assert main(["loops", "snapshot", "restore", "Start of shift", "--state-db", db]) == 0
    assert store.controls()["restore"] == "Start of shift"
    assert main(["loops", "freeze", "--state-db", db]) == 0 and store.controls()["frozen"]
    assert main(["loops", "speed", "50", "--state-db", db]) == 2
    assert main(["loops", "speed", "4", "--state-db", db]) == 0
    assert main(["loops", "resume", "--state-db", db]) == 0
    assert store.controls() | {"changed_at": ""} == {"frozen": False, "speed": 4.0,
        "offset_seconds": 0.0, "restore": "Start of shift", "changed_at": ""}  # fmt: skip
    assert main(["loops", "status", "--state-db", db]) == 0
    assert store.take_restore() == "Start of shift" and store.take_restore() is None
    assert main(["loops", "snapshot", "delete", "Start of shift", "--state-db", db]) == 0
    assert main(["loops", "snapshot", "delete", "Start of shift", "--state-db", db]) == 2
    with pytest.raises(ValueError):
        store.save_snapshot("../etc")


def test_the_server_follows_the_controls(tmp_path: Path):
    server = LoopPortfolioServer(state_db=tmp_path / "state.sqlite3")
    server.state_store = store = SimulatorStateStore(server.state_db)
    server.states = {item.loop_id: initial_state(item) for item in LOOP_DEFINITIONS}
    store.save(T0, server.states)
    store.save_snapshot("start")
    server.states["FIC-1001"].true_pv = 99.0
    store.set_controls(restore="start", speed=4)
    frozen, seconds = server._apply_controls(1.0)
    assert not frozen and seconds == 4.0 and server.offset_seconds == 3.0
    assert server.states["FIC-1001"].true_pv == FIC.base_pv  # the snapshot is back
    store.set_controls(frozen=True)
    frozen, seconds = server._apply_controls(2.0)
    assert frozen and server.offset_seconds == 1.0  # the model's clock stopped with it
    assert store.controls()["offset_seconds"] == 1.0  # kept for a restart


async def _read_pv(endpoint: str) -> ua.DataValue:
    async with Client(endpoint, timeout=5) as client:
        namespace = await client.get_namespace_index(NAMESPACE_URI)
        node = client.get_node(ua.NodeId("CPM.Loops.FIC-1001.PV", namespace))
        await asyncio.sleep(1.0)
        return await node.read_data_value(raise_on_bad_status=False)


def test_a_scheduled_fault_reaches_the_client_and_its_answer_key(tmp_path: Path):
    now = datetime.now(UTC).replace(microsecond=0)
    path = tmp_path / "faults.json"
    path.write_text(json.dumps({"faults": [{
        "id": "F1", "loop": "FIC-1001", "fault": "bad_quality",
        "start": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        "duration_minutes": 60}]}))  # fmt: skip
    port = _free_port()
    endpoint = f"opc.tcp://127.0.0.1:{port}/plantcraft/"
    state = tmp_path / "state.sqlite3"
    process = subprocess.Popen(
        [sys.executable, "-m", "simcraft", "loops", "serve", "--endpoint", endpoint,
         "--history-db", str(tmp_path / "history.sqlite3"), "--state-db", str(state),
         "--history-hours", "0.1", "--realtime-seconds", "0.5", "--reset",
         "--faults", str(path), "--log-level", "WARNING"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    try:
        _wait_for_port(port, process)
        found = asyncio.run(_read_pv(endpoint))
        assert found.StatusCode_.value == ua.StatusCodes.BadSensorFailure
        fired = SimulatorStateStore(state).fired()
        assert set(fired) == {"F1"} and "pv" in fired["F1"]
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
