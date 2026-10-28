"""The job folder and the executor of the suite's compute workers (docs/compute.md)."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tarfile
import threading
import time
from pathlib import Path

import pytest

from plantcraft_sdk.compute import folder
from plantcraft_sdk.compute.executor import Executor

HANDLER = "plantcraft_sdk.compute.selftest:answer"


def _tar(members: list[tarfile.TarInfo], data: bytes = b"x") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for member in members:
            if member.isfile():
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
            else:
                archive.addfile(member)
    return buffer.getvalue()


def test_a_job_folder_travels_whole(tmp_path):
    data = folder.pack({"job.json": '{"do": "echo"}', "data/values.bin": b"\x00\x01"})
    assert folder.read(data) == {"data/values.bin": b"\x00\x01", "job.json": b'{"do": "echo"}'}
    written = folder.unpack(data, tmp_path / "job")
    assert sorted(written) == ["data/values.bin", "job.json"]
    assert (tmp_path / "job" / "data" / "values.bin").read_bytes() == b"\x00\x01"


@pytest.mark.parametrize("name", ["../escape.txt", "/etc/passwd", "a/../../b", ""])
def test_names_outside_the_folder_are_refused(name):
    with pytest.raises(folder.ArchiveError):
        folder.pack({name: b"x"})
    member = tarfile.TarInfo(name or "x/")
    member.type = tarfile.REGTYPE
    if name:
        with pytest.raises(folder.ArchiveError):
            folder.read(_tar([member]))


def test_links_and_devices_in_an_archive_are_refused(tmp_path):
    link = tarfile.TarInfo("secret")
    link.type = tarfile.SYMTYPE
    link.linkname = "/run/secrets/key"
    with pytest.raises(folder.ArchiveError, match="not a plain file"):
        folder.unpack(_tar([link]), tmp_path / "job")
    hard = tarfile.TarInfo("hard")
    hard.type = tarfile.LNKTYPE
    hard.linkname = "job.json"
    with pytest.raises(folder.ArchiveError):
        folder.read(_tar([hard]))
    assert not (tmp_path / "job" / "secret").exists()


def test_an_archive_too_big_is_refused():
    with pytest.raises(folder.ArchiveError, match="larger than"):
        folder.read(folder.pack({"big.bin": b"0" * 2048}), max_bytes=1024)
    with pytest.raises(folder.ArchiveError, match="not a tar"):
        folder.read(b"not an archive")


def test_an_answer_never_follows_a_link_out_of_its_folder(tmp_path):
    secret = tmp_path / "credential"
    secret.write_text("pcw_secret")
    job = tmp_path / "job"
    (job / "out").mkdir(parents=True)
    (job / "result.json").write_text('{"status": "done"}')
    (job / "out" / "values.txt").write_text("1 2 3")
    (job / "out" / "stolen").symlink_to(secret)
    (job / "out" / "folder").symlink_to(tmp_path, target_is_directory=True)
    (job / "job.json").write_text("{}")
    files = folder.read(folder.pack_answer(job))
    assert files == {"out/values.txt": b"1 2 3", "result.json": b'{"status": "done"}'}


def _job(jobs: Path, task_id: str, job: dict, *, timeout: float = 30, extra=None) -> None:
    incoming = jobs / f".incoming-{task_id}"
    folder.unpack(folder.pack({"job.json": json.dumps(job), **(extra or {})}), incoming)
    folder.write_json(incoming / folder.TASK, {"id": task_id, "timeout_seconds": timeout})
    incoming.rename(jobs / folder.QUEUE / task_id)


def _answer(jobs: Path, task_id: str, seconds: float = 30) -> dict:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        done = jobs / folder.DONE / task_id
        if (done / folder.RESULT).exists() and not (jobs / folder.WORK / task_id).exists():
            return json.loads((done / folder.RESULT).read_text())
        time.sleep(0.05)
    raise AssertionError(f"no answer for {task_id}")


@pytest.fixture()
def executor(tmp_path):
    jobs = tmp_path / "linkcraft"
    running = Executor(jobs, app="linkcraft", version="0.5.0", handler=HANDLER, workers=2)
    thread = threading.Thread(target=running.serve, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while folder.heartbeat(jobs) is None and time.monotonic() < deadline:
        time.sleep(0.02)
    yield running
    running.stop.set()
    thread.join(15)


def test_the_executor_answers_and_says_who_it_is(executor):
    jobs = executor.jobs
    beat = folder.heartbeat(jobs)
    assert beat["app"] == "linkcraft" and beat["version"] == "0.5.0" and beat["workers"] == 2
    _job(jobs, "t1", {"do": "echo", "text": "hello"})
    _job(jobs, "t2", {"do": "sum"}, extra={"numbers.json": "[1, 2, 3.5]"})
    assert _answer(jobs, "t1")["status"] == "done"
    assert (jobs / folder.DONE / "t1" / "out" / "echo.txt").read_text() == "hello"
    assert _answer(jobs, "t2")["sum"] == 6.5


def test_a_task_that_fails_overruns_or_is_cancelled_stops_alone(executor):
    jobs = executor.jobs
    _job(jobs, "bad", {"do": "fail", "text": "division by zero"})
    _job(jobs, "slow", {"do": "sleep", "seconds": 30}, timeout=1)
    _job(jobs, "stop", {"do": "sleep", "seconds": 30})
    failed = _answer(jobs, "bad")
    assert failed["status"] == "error" and "division by zero" in failed["error"]
    deadline = time.monotonic() + 15
    while not (jobs / folder.WORK / "stop").exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    (jobs / folder.WORK / "stop" / folder.CANCEL).write_text("")
    assert _answer(jobs, "stop")["status"] == "cancelled"
    slow = _answer(jobs, "slow")
    assert slow["status"] == "error" and "longer than its 1 s" in slow["error"]
    # The slots run the next task after stopping those.
    _job(jobs, "after", {"do": "echo", "text": "still here"})
    assert _answer(jobs, "after")["status"] == "done"


def test_a_task_imports_what_subclasses_a_socket_but_opens_none():
    # ssl.SSLSocket subclasses socket.socket: a module importing ssl (httpx) after the child's
    # limits failed to import when the socket was replaced by a function (Analytics' signal
    # quality failed on every worker, 2026-10-26).
    code = (
        "import socket\n"
        "from plantcraft_sdk.compute.executor import _child_limits\n"
        "_child_limits(0, 10**9)\n"
        "class Wrapped(socket.socket):\n"
        "    pass\n"
        "for make in (socket.socket, Wrapped):\n"
        "    try:\n"
        "        make()\n"
        "    except OSError as exc:\n"
        "        assert 'no network' in str(exc)\n"
        "    else:\n"
        "        raise SystemExit('a socket opened')\n"
        "print('ok')\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "ok"


def test_a_task_of_an_executor_that_stopped_goes_back_to_the_queue(tmp_path, monkeypatch):
    """An executor stopped mid-run while its gateway stayed online (the Mac mini, 2026-10-26):
    its tasks are reported failed at once, so PlantCraft gives them to another worker."""

    import time as clock

    from plantcraft_sdk.compute import folder as job_folder
    from plantcraft_sdk.compute.gateway import Gateway, _Task

    gateway = Gateway("https://plantcraft.test", tmp_path, "pcw_x")
    reports: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        gateway,
        "report",
        lambda task_id, status, **kw: reports.append((task_id, status, kw["error"])),
    )
    for name in ("alive", "gone"):
        job_folder.prepare(tmp_path / name)
        (tmp_path / name / job_folder.WORK / f"t-{name}").mkdir()
        gateway.running[f"t-{name}"] = _Task(f"t-{name}", name, clock.monotonic() + 600)
    job_folder.write_json(tmp_path / "alive" / job_folder.HEARTBEAT, {"at": clock.time()})
    job_folder.write_json(tmp_path / "gone" / job_folder.HEARTBEAT, {"at": clock.time() - 120})
    gateway.collect()
    assert reports == [("t-gone", "failed", "the executor of gone stopped")]
    assert (tmp_path / "gone" / job_folder.WORK / "t-gone" / job_folder.CANCEL).exists()


def test_the_lease_waits_briefly_while_tasks_run_here(tmp_path, monkeypatch):
    """An idle Models held the lease's 20 s wait while Analytics' slots freed: one task in four
    ran at a time on a plant of 2050 loops (the cloud bench, 2026-10-27)."""

    import time as clock

    from plantcraft_sdk.compute import gateway as gateway_module
    from plantcraft_sdk.compute.gateway import Gateway, _Task

    gateway = Gateway("https://plantcraft.test", tmp_path, "pcw_x")
    monkeypatch.setattr(gateway, "executors", lambda: [{"app": "modelcraft", "free": 2}])
    waits: list[float] = []

    class Reply:
        status_code = 200

        @staticmethod
        def json():
            return {"state": "active", "tasks": []}

    def post(path, **kwargs):
        waits.append(kwargs["json"]["wait"])
        return Reply()

    monkeypatch.setattr(gateway, "_post", post)
    gateway.take()
    gateway.running["t1"] = _Task("t1", "linkcraft", clock.monotonic() + 600)
    gateway.take()
    assert waits == [gateway_module.LEASE_WAIT_SECONDS, gateway_module.BUSY_WAIT_SECONDS]


def test_a_slot_that_frees_takes_the_next_task_without_a_pause(tmp_path, monkeypatch):
    """With every slot busy the gateway paused half a second before asking again: on short
    tasks (a chunk of signals, under a second) the slots sat idle a third of the time (the
    cloud bench's signal checks, 2026-10-27)."""

    import threading
    import time as clock

    from plantcraft_sdk.compute import gateway as gateway_module
    from plantcraft_sdk.compute.gateway import Gateway, _Task

    monkeypatch.setattr(gateway_module, "IDLE_SECONDS", 5.0)
    gateway = Gateway("https://plantcraft.test", tmp_path, "pcw_x")
    monkeypatch.setattr(gateway, "executors", lambda: [{"app": "linkcraft", "free": 0}])
    monkeypatch.setattr(
        gateway, "_post", lambda path, **kwargs: type("Reply", (), {"status_code": 200})()
    )
    gateway.running["t1"] = _Task("t1", "linkcraft", clock.monotonic() + 600)
    threading.Timer(0.2, gateway.report, args=("t1", "done")).start()
    began = clock.monotonic()
    gateway.take()
    assert clock.monotonic() - began < 2.0


def test_waiting_for_answers_outlives_a_restart_of_plantcraft(monkeypatch):
    """PlantCraft recreated mid-run cut Models' long poll, and the run failed (the Mac mini,
    2026-10-26): the wait goes on while PlantCraft is briefly unreachable."""

    from plantcraft_sdk.client import Unavailable
    from plantcraft_sdk.compute import client as compute_client

    monkeypatch.setattr(compute_client.time, "sleep", lambda seconds: None)

    class Restarting(compute_client.ComputeClient):
        calls = 0

        def __init__(self):
            pass

        def wait(self, ids, seconds=20.0):
            Restarting.calls += 1
            if Restarting.calls <= 2:
                raise Unavailable("PlantCraft could not be reached: connection reset")
            return [{"id": ids[0], "status": "failed", "error": "x"}]

        def answer(self, task):
            return compute_client.Answer(task["id"], task["status"], error=task["error"])

    found = list(Restarting().answers(["t1"], timeout=60))
    assert [item.id for item in found] == ["t1"] and Restarting.calls == 3
    monkeypatch.setattr(compute_client, "OUTAGE_SECONDS", -1.0)
    Restarting.calls = -10
    with pytest.raises(Unavailable):
        list(Restarting().answers(["t1"], timeout=60))
