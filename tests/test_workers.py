"""Several server processes on one installation (``plantcraft.ops.workers``, PLANTCRAFT_WORKERS)."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from plantcraft.db import Database, Store
from plantcraft.ops.workers import Leader, first_only, startup, worker_count

ROOT = Path(__file__).resolve().parents[1]


def test_worker_count_follows_the_data_layer():
    assert worker_count({}, cpus=12) == 1  # PlantCraft reads its own sources: one process
    assert worker_count({"HISTCRAFT_URL": "http://histcraft:8100/hist"}, cpus=12) == 4
    assert worker_count({"HISTCRAFT_URL": "http://h/hist"}, cpus=1) == 2
    assert worker_count({"HISTCRAFT_URL": "http://h/hist"}, cpus=3) == 3
    assert worker_count({"PLANTCRAFT_WORKERS": "3"}, cpus=12) == 3
    assert worker_count({"PLANTCRAFT_WORKERS": "99"}, cpus=12) == 8
    assert worker_count({"PLANTCRAFT_WORKERS": "0"}, cpus=12) == 1
    assert worker_count({"PLANTCRAFT_WORKERS": "many"}, cpus=12) == 1


def test_one_leader_at_a_time(tmp_path):
    first, second = Leader(tmp_path), Leader(tmp_path)
    assert first.acquire() and first.held
    assert not second.acquire()
    first.release()
    stop = threading.Event()
    assert second.wait(stop) and second.held
    second.release()


def test_a_waiting_leader_stops_when_asked(tmp_path):
    holder = Leader(tmp_path)
    assert holder.acquire()
    stop = threading.Event()
    stop.set()
    assert not Leader(tmp_path).wait(stop)
    holder.release()


def test_first_only_and_startup_take_turns(tmp_path):
    with first_only(tmp_path / "x.lock") as mine:
        assert mine
        with first_only(tmp_path / "x.lock") as other:
            assert not other
    order: list[str] = []
    with startup(tmp_path):
        worker = threading.Thread(target=lambda: _start(tmp_path, order))
        worker.start()
        time.sleep(0.3)
        order.append("first")
    worker.join(5)
    assert order == ["first", "second"]


def _start(folder: Path, order: list[str]) -> None:
    with startup(folder):
        order.append("second")


class Counter(Store):
    SCHEMA = "CREATE TABLE IF NOT EXISTS counter (id INTEGER PRIMARY KEY, n INTEGER NOT NULL);"

    def bump(self) -> None:
        # Read, then write: in a write block, so no other process slips in between.
        with self._lock, self._write() as connection:
            row = connection.execute("SELECT n FROM counter WHERE id = 1").fetchone()
            value = (row[0] if row else 0) + 1
            connection.execute("INSERT OR REPLACE INTO counter VALUES (1, ?)", (value,))


def _bump_many(path: str, times: int) -> None:
    store = Counter(Database(path))
    for _ in range(times):
        store.bump()


def test_write_blocks_of_several_processes_never_lose_an_update(tmp_path):
    import multiprocessing

    path = str(tmp_path / "shared.sqlite3")
    Counter(Database(path))
    context = multiprocessing.get_context("spawn")
    processes = [context.Process(target=_bump_many, args=(path, 50)) for _ in range(4)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(60)
        assert process.exitcode == 0
    with Database(path).connect() as connection:
        assert connection.execute("SELECT n FROM counter").fetchone()[0] == 200


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.mark.slow
def test_three_server_processes_share_sign_in_writes_and_one_leader(tmp_path):
    scenario = json.loads((ROOT / "scenarios" / "generic_demo.json").read_text())
    scenario["storage"]["sqlite_path"] = str(tmp_path / "workspace.sqlite3")
    scenario["source"]["path"] = str(ROOT / scenario["source"]["path"])
    (tmp_path / "scenario.json").write_text(json.dumps(scenario))
    (tmp_path / "admin-password").write_text("workers-admin-secret")
    port = _free_port()
    env = {
        **os.environ,
        "PLANTCRAFT_SCENARIO": str(tmp_path / "scenario.json"),
        "PLANTCRAFT_PREWARM_HISTORY": "false",
        "PLANTCRAFT_BASIC_AUTH_ENABLED": "true",
        "PLANTCRAFT_BASIC_AUTH_USERNAME": "admin",
        "PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE": str(tmp_path / "admin-password"),
        "PLANTCRAFT_WORKERS": "3",
        "PLANTCRAFT_PORT": str(port),
        "PLANTCRAFT_HOST": "127.0.0.1",
    }
    # The log goes to a file: three processes log about 65 KB here, more than a pipe nobody
    # reads holds, and a full pipe blocks every process that logs (a request hangs).
    log = (tmp_path / "server.log").open("w")
    server = subprocess.Popen(
        [sys.executable, "-m", "plantcraft.api.serve"],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=log,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 90
        while time.time() < deadline:
            try:
                if httpx.get(f"{base}/healthz", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.3)
        else:
            raise AssertionError("the server did not start")
        with httpx.Client(base_url=base, timeout=30) as client:
            signed = client.post(
                "/api/login", json={"username": "admin", "password": "workers-admin-secret"}
            )
            assert signed.status_code == 200
            cookies = dict(client.cookies)

        def create(index: int) -> int:
            # Each request may land on any of the three processes: the signed cookie and the
            # database are all they share.
            with httpx.Client(base_url=base, timeout=60, cookies=cookies) as client:
                answer = client.post(
                    "/api/assets",
                    json={"name": f"Pump {index}", "asset_id": f"P-{index}", "kind": "equipment"},
                )
                assert client.get("/api/session").json().get("username") == "admin"
                return answer.status_code

        with ThreadPoolExecutor(16) as pool:
            codes = list(pool.map(create, range(60)))
        assert codes == [201] * 60
        with httpx.Client(base_url=base, timeout=30, cookies=cookies) as client:
            listed = client.get("/api/assets").json()
        text = json.dumps(listed)
        assert all(f'"P-{index}"' in text for index in range(60))
        # One process leads (the watch and the outbox), the others stand by.
        pid = int((tmp_path / "leader.lock").read_text().strip())
        children = subprocess.run(
            ["ps", "-o", "pid=", "--ppid", str(server.pid)], capture_output=True, text=True
        ).stdout.split()
        assert len(children) >= 3 and str(pid) in children
        # One session key and one token key for every process.
        assert len(list(tmp_path.glob("session.secret"))) == 1
    finally:
        server.terminate()
        try:
            server.wait(30)
        except subprocess.TimeoutExpired:
            server.kill()
        log.close()


def test_asset_types_changed_in_another_process_are_seen(tmp_path, monkeypatch):
    from plantcraft.assets import types

    path = tmp_path / "types.sqlite3"
    here, there = types.AssetTypeStore(Database(path)), types.AssetTypeStore(Database(path))
    assert "heat_pump" not in here.definitions()
    there.create({"id": "heat_pump", "name": "Heat pump", "parent": "equipment"}, actor="admin")
    # Within the second the version is not asked again: one request reads the types many times.
    assert "heat_pump" not in here.definitions()
    monkeypatch.setattr(types, "VERSION_CHECK_SECONDS", 0.0)
    assert here.definitions()["heat_pump"]["name"] == "Heat pump"
