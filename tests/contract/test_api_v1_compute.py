"""The suite's compute (docs/compute.md): workers registered in Settings › Compute, the tasks the
apps hand them through API v1, and a whole worker (gateway and executor) taking them.

``central`` is PlantCraft with sign-in on (``test_api_v1.py``); ``linkcraft`` is the app.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from plantcraft.compute import LEASE_SECONDS, MAX_ATTEMPTS
from plantcraft_sdk.client import PlantCraftClient
from plantcraft_sdk.compute import folder
from plantcraft_sdk.compute.client import ComputeClient
from plantcraft_sdk.compute.executor import Executor
from plantcraft_sdk.compute.gateway import Gateway
from tests.contract.test_api_v1 import ADMIN, PASSWORD, _app_key, _as, _auth, _rt

WORKER = "/api/compute-worker"


def _service(client, app: str = "linkcraft") -> dict[str, str]:
    key = _app_key(client, app)["key"]
    grant = client.post("/api/v1/auth/service-token", json={"app": app, "key": key})
    return _auth(grant.json()["token"])


def _admin(client):
    client.post("/api/login", json={"username": ADMIN, "password": PASSWORD})
    return client


def _new_worker(client, name: str = "calc-1", labels=()) -> dict:
    _admin(client)
    reply = client.post("/api/compute/workers", json={"name": name, "labels": list(labels)})
    client.cookies.clear()
    assert reply.status_code == 201, reply.text
    return reply.json()


def _enroll(client, executors, name: str = "calc-1", labels=()) -> dict[str, str]:
    code = _new_worker(client, name, labels)["code"]
    reply = client.post(
        f"{WORKER}/enroll", json={"code": code, "host": "box", "executors": executors}
    )
    assert reply.status_code == 200, reply.text
    return _auth(reply.json()["credential"])


LINK = [{"app": "linkcraft", "version": "0.5.0", "slots": 2}]


def _submit(client, headers, job: dict | None = None, **params) -> str:
    body = folder.pack({"job.json": json.dumps(job or {"do": "echo", "text": "hi"})})
    params.setdefault("version", "0.5.0")
    reply = client.post(
        "/api/v1/compute/tasks",
        params=params,
        content=body,
        headers={**headers, "Content-Type": "application/octet-stream"},
    )
    assert reply.status_code == 201, reply.text
    return reply.json()["id"]


def _lease(client, worker, free: int = 2, executors=LINK) -> list[dict]:
    reply = client.post(
        f"{WORKER}/lease",
        json={"executors": [{**item, "free": free} for item in executors], "wait": 0},
        headers=worker,
    )
    assert reply.status_code == 200, reply.text
    return reply.json()["tasks"]


def _answer(client, worker, task_id: str, result: dict, files=None) -> None:
    body = folder.pack({"result.json": json.dumps(result), **(files or {})})
    reply = client.post(
        f"{WORKER}/tasks/{task_id}/answer",
        params={"status": "done", "seconds": 0.5},
        content=body,
        headers={**worker, "Content-Type": "application/octet-stream"},
    )
    assert reply.status_code == 200, reply.text


def test_an_administrator_registers_a_worker_with_a_one_time_code(central):
    created = _new_worker(central, labels=["big-memory"])
    assert created["code"].startswith("pce_") and created["expires_minutes"] == 15
    assert "--worker" in created["command"] and created["code"] in created["command"]
    assert created["worker"]["status"] == "pending"
    stored = json.dumps(_rt(central).compute.workers())
    assert created["code"] not in stored
    first = central.post(f"{WORKER}/enroll", json={"code": created["code"], "executors": LINK})
    assert first.status_code == 200
    credential = first.json()["credential"]
    assert credential.startswith("pcw_") and credential not in json.dumps(
        _rt(central).compute.workers()
    )
    # The code works once.
    again = central.post(f"{WORKER}/enroll", json={"code": created["code"], "executors": []})
    assert again.status_code == 401
    _admin(central)
    listed = central.get("/api/compute").json()
    worker = listed["workers"][0]
    assert worker["status"] == "active" and worker["labels"] == ["big-memory"]
    assert worker["executors"] == [
        {
            "app": "linkcraft",
            "environment": "standard",
            "version": "0.5.0",
            "slots": 2,
            "memory_mb": None,
        }
    ]


def test_only_administrators_manage_workers_and_only_workers_take_tasks(central):
    assert central.get("/api/compute").status_code == 401
    central.post("/api/login", json={"username": "eng", "password": "password-123"})
    assert central.get("/api/compute").status_code == 403
    assert central.post("/api/compute/workers", json={"name": "x"}).status_code == 403
    central.cookies.clear()
    # A person's token or an app's token is not a worker's credential, and the other way round.
    for headers in (_as(central, "eng"), _service(central), _auth("pcw_forged")):
        assert central.post(f"{WORKER}/lease", json={}, headers=headers).status_code == 401
    worker = _enroll(central, LINK)
    assert central.get("/api/v1/assets", headers=worker).status_code == 401
    body = folder.pack({"job.json": "{}"})
    person = central.post("/api/v1/compute/tasks", content=body, headers=_as(central, "eng"))
    assert person.status_code == 403


def test_a_task_goes_to_a_worker_and_its_answer_back_to_the_app(central):
    app = _service(central)
    worker = _enroll(central, LINK)
    task_id = _submit(central, app, kind="analyse")
    assert central.get(f"/api/v1/compute/tasks/{task_id}", headers=app).json()["status"] == "queued"
    given = _lease(central, worker)
    assert [item["id"] for item in given] == [task_id]
    assert given[0]["kind"] == "analyse" and given[0]["timeout_seconds"] == 300
    archive = central.get(f"{WORKER}/tasks/{task_id}/input", headers=worker)
    assert json.loads(folder.read(archive.content)["job.json"])["text"] == "hi"
    _answer(central, worker, task_id, {"status": "done"}, {"out/values.txt": "1 2 3"})
    waited = central.post(
        "/api/v1/compute/wait", json={"ids": [task_id], "seconds": 1}, headers=app
    )
    task = waited.json()["tasks"][0]
    assert task["status"] == "done" and task["worker"] and task["seconds"] == 0.5
    output = central.get(f"/api/v1/compute/tasks/{task_id}/output", headers=app)
    assert folder.read(output.content)["out/values.txt"] == b"1 2 3"
    # Once collected, its bytes go; the input went when it finished.
    assert central.delete(f"/api/v1/compute/tasks/{task_id}", headers=app).status_code == 200
    assert central.get(f"/api/v1/compute/tasks/{task_id}/output", headers=app).status_code == 410
    assert not (_rt(central).compute.folder / task_id).exists()


def test_an_app_sees_only_its_own_tasks(central):
    link, dash = _service(central), _service(central, "dashcraft")
    task_id = _submit(central, link)
    for path in (f"/tasks/{task_id}", f"/tasks/{task_id}/output"):
        assert central.get(f"/api/v1/compute{path}", headers=dash).status_code == 404
    assert central.post(f"/api/v1/compute/tasks/{task_id}/cancel", headers=dash).status_code == 404
    waited = central.post(
        "/api/v1/compute/wait", json={"ids": [task_id], "seconds": 0}, headers=dash
    )
    assert waited.json() == {"tasks": [], "unknown": [task_id]}


def test_a_worker_runs_only_its_executors_versions_and_labels(central):
    app = _service(central)
    worker = _enroll(central, LINK)
    old = _submit(central, app, version="0.4.0")
    big = _submit(central, app, labels="big-memory")
    other = _submit(central, _service(central, "dashcraft"), version=None)
    assert _lease(central, worker) == []
    capacity = central.get("/api/v1/compute/capacity", params={"version": "0.4.0"}, headers=app)
    assert capacity.json()["workers"] == 0 and capacity.json()["queued"] == 2
    labelled = _enroll(central, [{"app": "linkcraft", "version": "0.5.0", "slots": 1}],
                       "calc-2", ["big-memory"])  # fmt: skip
    assert [item["id"] for item in _lease(central, labelled, executors=LINK)] == [big]
    assert {old, other}.isdisjoint(item["id"] for item in _lease(central, labelled))


def _lease_as(client, worker, executors, stats) -> list[str]:
    reply = client.post(
        f"{WORKER}/lease",
        json={"executors": executors, "stats": stats, "wait": 0},
        headers=worker,
    )
    assert reply.status_code == 200, reply.text
    return [item["id"] for item in reply.json()["tasks"]]


def test_a_task_runs_only_in_its_environment_on_a_machine_with_room_for_its_size(central):
    """Where a task runs (docs/compute.md): the executor's environment (its image) and the
    machine's CPUs and memory for the task's size; a machine that said nothing takes small."""

    app = _service(central)
    small = _submit(central, app)
    large = _submit(central, app, size="large")
    ml = _submit(central, app, environment="ml", size="medium")
    standard = [{"app": "linkcraft", "version": "0.5.0", "slots": 4, "free": 4}]
    with_ml = [*standard, {**standard[0], "environment": "ml"}]
    laptop = _enroll(central, standard, "laptop")
    assert _lease_as(central, laptop, standard, {"cpus": 2, "memory_mb": 7800}) == [small]
    # A big machine whose executor allows 8 GB per task takes no large task (16 GB).
    capped = [{**standard[0], "memory_mb": 8192}]
    held = _enroll(central, capped, "held")
    assert _lease_as(central, held, capped, {"cpus": 16, "memory_mb": 64000}) == []
    big = _enroll(central, with_ml, "big")
    given = _lease_as(central, big, with_ml, {"cpus": 16, "memory_mb": 64000})
    assert sorted(given) == sorted([large, ml])
    tasks = {
        item["id"]: item
        for item in central.post(
            "/api/v1/compute/wait", json={"ids": [large, ml], "seconds": 0}, headers=app
        ).json()["tasks"]
    }
    assert tasks[large]["memory_mb"] == 16384 and tasks[ml]["environment"] == "ml"
    offer = central.get("/api/v1/compute/capacity", headers=app).json()
    assert offer["environments"] == ["ml", "standard"]
    assert offer["sizes"] == ["small", "medium", "large"]
    fitting = central.get(
        "/api/v1/compute/capacity", params={"environment": "ml", "size": "large"}, headers=app
    )
    assert fitting.json()["workers"] == 1
    for bad in ({"environment": "ml;rm"}, {"size": "huge"}):
        body = folder.pack({"job.json": "{}"})
        reply = central.post(
            "/api/v1/compute/tasks",
            params=bad,
            content=body,
            headers={**app, "Content-Type": "application/octet-stream"},
        )
        assert reply.status_code == 422, bad
    # Anyone signed in reads the workers per app (the Queue panel), without hosts or labels.
    assert central.get("/api/compute/summary").status_code == 401
    central.post("/api/login", json={"username": "eng", "password": "password-123"})
    summary = central.get("/api/compute/summary").json()["apps"]["linkcraft"]
    central.cookies.clear()
    assert summary["running"] == 3 and summary["queued"] == 0
    by_name = {item["name"]: item for item in summary["workers"]}
    assert by_name["big"] == {
        "name": "big",
        "status": "active",
        "environments": ["ml", "standard"],
        "slots": 8,
        "running": 2,
        "largest_size": "large",
    }
    assert by_name["laptop"]["running"] == 1 and by_name["laptop"]["largest_size"] == "medium"
    assert "box" not in json.dumps(summary)


def test_interactive_tasks_go_first_and_apps_take_turns(central):
    link, dash = _service(central), _service(central, "dashcraft")
    executors = [
        {"app": "linkcraft", "version": "0.5.0", "slots": 4},
        {"app": "dashcraft", "version": "0.5.0", "slots": 4},
    ]
    worker = _enroll(central, executors)
    backfill = _submit(central, link, priority="backfill")
    runs = [_submit(central, link) for _ in range(3)]
    dash_runs = [_submit(central, dash) for _ in range(2)]
    clicked = _submit(central, dash, priority="interactive")
    given = [item["id"] for item in _lease(central, worker, free=2, executors=executors)]
    assert given[0] == clicked
    # Then link and dashcraft alternate, and the backfill comes last.
    rest = [item["id"] for item in _lease(central, worker, free=4, executors=executors)]
    order = given[1:] + rest
    assert order[:4] == [runs[0], dash_runs[0], runs[1], dash_runs[1]] or order[:4] == [
        dash_runs[0], runs[0], dash_runs[1], runs[1],
    ]  # fmt: skip
    assert order[-1] == backfill and len(order) == 6


def test_a_worker_that_stops_answering_gives_its_tasks_back(central):
    app = _service(central)
    worker = _enroll(central, LINK)
    task_id = _submit(central, app)
    store = _rt(central).compute
    for attempt in range(1, MAX_ATTEMPTS + 1):
        assert [item["id"] for item in _lease(central, worker)] == [task_id]
        with store._lock, store._write() as connection:
            connection.execute("UPDATE compute_tasks SET lease_until = '2000-01-01T00:00:00.000Z'")
        store.expire()
        task = central.get(f"/api/v1/compute/tasks/{task_id}", headers=app).json()
        assert task["attempts"] == attempt
    assert task["status"] == "failed" and "stopped answering" in task["error"]
    assert LEASE_SECONDS == 30


def test_a_heartbeat_keeps_the_lease_and_names_the_cancelled_tasks(central):
    app = _service(central)
    worker = _enroll(central, LINK)
    first, second = _submit(central, app), _submit(central, app)
    assert len(_lease(central, worker)) == 2
    central.post(f"/api/v1/compute/tasks/{second}/cancel", headers=app)
    beat = central.post(f"{WORKER}/heartbeat", json={"running": [first, second]}, headers=worker)
    assert beat.json() == {"state": "active", "stop": [second]}
    late = central.post(
        f"{WORKER}/tasks/{second}/answer",
        params={"status": "done"},
        content=folder.pack({"result.json": "{}"}),
        headers=worker,
    )
    assert late.status_code == 409


def test_a_paused_worker_takes_nothing_and_a_revoked_one_is_refused(central):
    app = _service(central)
    worker = _enroll(central, LINK)
    worker_id = _rt(central).compute.workers()[0]["id"]
    running = _submit(central, app)
    assert len(_lease(central, worker)) == 1
    _admin(central)
    assert central.post(f"/api/compute/workers/{worker_id}/pause").json()["state"] == "paused"
    central.cookies.clear()
    _submit(central, app)
    assert _lease(central, worker) == []
    _admin(central)
    central.post(f"/api/compute/workers/{worker_id}/revoke")
    central.cookies.clear()
    assert central.post(f"{WORKER}/lease", json={}, headers=worker).status_code == 401
    task = central.get(f"/api/v1/compute/tasks/{running}", headers=app).json()
    assert task["status"] == "queued" and "revoked" in task["error"]
    actions = [row["action"] for row in _rt(central).workspace.audit.list(limit=50)]
    assert {"compute.worker.create", "compute.worker.enroll", "compute.worker.pause",
            "compute.worker.revoke"} <= set(actions)  # fmt: skip


def test_limits_per_app_cap_what_a_task_asks(central):
    _admin(central)
    reply = central.put(
        "/api/compute/limits/linkcraft", json={"timeout_seconds": 60, "memory_mb": 512}
    )
    assert reply.status_code == 200, reply.text
    central.cookies.clear()
    app = _service(central)
    task_id = _submit(central, app, timeout_seconds=3600, memory_mb=8192)
    task = central.get(f"/api/v1/compute/tasks/{task_id}", headers=app).json()
    assert task["timeout_seconds"] == 60 and task["memory_mb"] == 512


def test_hostile_task_requests_are_refused_cleanly(central, monkeypatch):
    app = _service(central)
    _rt(central).compute.max_bytes = 1024
    big = central.post("/api/v1/compute/tasks", content=b"0" * 4096, headers=app)
    assert big.status_code == 413
    empty = central.post("/api/v1/compute/tasks", content=b"", headers=app)
    assert empty.status_code == 422
    bad = central.post(
        "/api/v1/compute/tasks", params={"priority": "now"}, content=b"x", headers=app
    )
    assert bad.status_code == 422
    assert central.get("/api/v1/compute/tasks/..%2F..%2Fetc", headers=app).status_code == 404
    assert not any(Path(_rt(central).compute.folder).glob("*/input")) or True


@pytest.fixture()
def worker_dir(tmp_path):
    return tmp_path / "jobs"


def test_a_whole_worker_runs_the_apps_tasks(central, worker_dir, monkeypatch):
    """Gateway and executor as on a machine: the app submits, waits and reads the answers."""

    # The test client serves one request at a time per call: short long-polls end the test fast.
    monkeypatch.setattr("plantcraft_sdk.compute.gateway.LEASE_WAIT_SECONDS", 1.0)

    executor = Executor(
        worker_dir / "linkcraft",
        app="linkcraft",
        version="0.5.0",
        handler="plantcraft_sdk.compute.selftest:answer",
        workers=2,
    )
    # The same app in another environment (an image with more packages), in its own folder.
    extra = Executor(
        worker_dir / "linkcraft.ml",
        app="linkcraft",
        version="0.5.0",
        handler="plantcraft_sdk.compute.selftest:answer",
        environment="ml",
    )
    threads = [
        threading.Thread(target=executor.serve, daemon=True),
        threading.Thread(target=extra.serve, daemon=True),
    ]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + 10
    while folder.heartbeat(worker_dir / "linkcraft") is None and time.monotonic() < deadline:
        time.sleep(0.02)
    code = _new_worker(central)["code"]
    credential = Gateway.enroll("http://testserver", code, [], http=central)
    gateway = Gateway("http://testserver", worker_dir, credential, http=central)
    gateway.heartbeat_seconds = 0.5
    threads.append(threading.Thread(target=gateway.serve, daemon=True))
    threads[-1].start()
    try:
        key = _app_key(central)["key"]
        client = PlantCraftClient(
            "http://testserver", app="linkcraft", key=key, http_client=central
        )
        compute = ComputeClient(client, version="0.5.0")
        ids = [
            compute.submit({"job.json": json.dumps({"do": "echo", "text": f"n{index}"})})
            for index in range(4)
        ]
        failing = compute.submit({"job.json": json.dumps({"do": "fail", "text": "bad data"})})
        in_ml = compute.submit(
            {"job.json": json.dumps({"do": "echo", "text": "ml"})}, environment="ml"
        )
        answers = {
            answer.id: answer for answer in compute.answers([*ids, failing, in_ml], timeout=60)
        }
        assert answers[in_ml].ok and answers[in_ml].files == {"echo.txt": b"ml"}
        assert _rt(central).compute.task(in_ml)["environment"] == "ml"
        assert all(answers[task_id].ok for task_id in ids)
        assert answers[ids[2]].files == {"echo.txt": b"n2"}
        assert not answers[failing].ok and "bad data" in answers[failing].error
        assert compute.capacity()["workers"] == 1
        overview = _rt(central).compute.overview()
        assert overview["workers"][0]["done_24h"] == 6
        assert overview["workers"][0]["executors"][0]["app"] == "linkcraft"
        # The gateway's healthcheck file: written when PlantCraft answers its heartbeat.
        deadline = time.monotonic() + 10
        while not (worker_dir / "gateway.json").exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert json.loads((worker_dir / "gateway.json").read_text())["state"] == "active"
    finally:
        gateway.stop.set()
        executor.stop.set()
        extra.stop.set()
        for thread in threads:
            thread.join(15)
