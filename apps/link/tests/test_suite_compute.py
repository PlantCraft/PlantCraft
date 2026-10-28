"""Analytics on the suite's compute workers (LINKCRAFT_COMPUTE=suite; PlantCraft docs/compute.md).

``FakeCompute`` stands in for PlantCraft's queue and a worker: each task's folder is answered by
the executor's handler (``linkcraft.api.compute.answer``) in a thread, as the worker would in its own
container. A round on it gives what the round in this process gives.
"""

from __future__ import annotations

import itertools
import json
import math
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from plantcraft_sdk.blocks import NoData, Result
from plantcraft_sdk.compute.client import Answer

from linkcraft.api import compute as worker
from linkcraft.api.compute import RemoteCodePool, site_blocks
from linkcraft.blocks import sandbox
from linkcraft.engine import suite_compute
from linkcraft.engine.suite_compute import SuitePool, priority
from linkcraft.engine.wire import WireError, decode, encode
from tests.conftest import make_runtime


class FakeCompute:
    def __init__(self, folder: Path, workers: int = 2):
        self.folder = folder
        self.pool = ThreadPoolExecutor(workers)
        self.ids = itertools.count(1)
        self.futures: dict[str, object] = {}
        self.sent: list[dict] = []
        self.cancelled: list[str] = []
        self.lock = threading.Lock()

    def submit(self, files, **options):
        task_id = f"t{next(self.ids)}"
        job_dir = self.folder / task_id
        job_dir.mkdir()
        for name, content in files.items():
            (job_dir / name).write_text(content, encoding="utf-8")
        with self.lock:
            self.sent.append(
                {"id": task_id, **options, "items": len(json.loads(files["job.json"])["items"])}
            )
            self.futures[task_id] = self.pool.submit(worker.answer, job_dir)
        return task_id

    def _task(self, task_id):
        future = self.futures[task_id]
        if not future.done():
            return {"id": task_id, "status": "running"}
        error = future.exception()
        if error is not None:
            return {"id": task_id, "status": "failed", "error": str(error)}
        return {"id": task_id, "status": "done"}

    def wait(self, ids, seconds=20.0):
        with self.lock:
            futures = [self.futures[task_id] for task_id in ids if task_id in self.futures]
        wait(futures, timeout=seconds, return_when=FIRST_COMPLETED)
        return [self._task(task_id) for task_id in ids if task_id in self.futures]

    def answer(self, task):
        task_id = task["id"]
        if task["status"] != "done":
            return Answer(task_id, task["status"], error=task.get("error", ""), task=task)
        out = self.folder / task_id / "out"
        files = {path.name: path.read_bytes() for path in out.iterdir()}
        return Answer(task_id, "done", {"status": "done"}, files, "", task)

    def cancel(self, task_id):
        self.cancelled.append(task_id)
        return {"id": task_id, "status": "cancelled"}


@pytest.fixture
def fake_compute(tmp_path):
    folder = tmp_path / "compute"
    folder.mkdir()
    found = FakeCompute(folder)
    yield found
    found.pool.shutdown(wait=True)


def _round_trip(value):
    return decode(json.loads(json.dumps(encode(value))))


def test_frames_series_and_results_cross_unchanged():
    index = pd.date_range("2026-10-26", periods=5, freq="5s", tz="UTC", name="time")
    frame = pd.DataFrame(
        {
            "pv": [1.0, np.nan, 3.0, 4.0, 5.0],
            "count": [1, 2, 3, 4, 5],
            "mode": ["AUTO", "MAN", None, "AUTO", "CAS"],
            "when": pd.date_range("2026-10-26", periods=5, tz="America/Sao_Paulo"),
            "on": [True, False, True, True, False],
        },
        index=index,
    )
    frame.attrs["failed_tags"] = [("a", "b")]
    value = {
        "raw": frame,
        "pv": frame["pv"],
        "result": Result("good", 90.0, "fine", detail={"limit": math.inf}),
        "none": NoData("no data"),
        "$odd": 1,
        3: (1, 2),
        "array": np.arange(6).reshape(2, 3),
        "nan": math.nan,
        "nullable": pd.array([True, None], dtype="boolean"),
    }
    back = _round_trip(value)
    pd.testing.assert_frame_equal(back["raw"], frame, check_freq=False)
    pd.testing.assert_series_equal(back["pv"], frame["pv"], check_freq=False)
    assert back["raw"].attrs == {"failed_tags": [("a", "b")]}
    assert back["result"] == value["result"] and back["none"] == value["none"]
    assert back["$odd"] == 1 and back[3] == (1, 2) and math.isnan(back["nan"])
    assert (back["array"] == value["array"]).all()
    assert back["nullable"].tolist() == [True, pd.NA]


def test_numbers_cross_as_their_bytes():
    """A float series went value by value (``Series.array`` is an extension array): 15 ms and
    250 KB a signal of a day at 10 s, two minutes of the app's time for a plant's checks."""

    series = pd.Series(
        np.linspace(0, 1, 8640), index=pd.date_range("2026-10-26", periods=8640, freq="10s")
    )
    sent = encode(series)["$series"]
    # The values and the time index (naive, as the engine reads it) both as bytes.
    assert "b64" in sent["values"] and "list" not in sent["values"]
    assert "b64" in sent["index"]["values"]
    pd.testing.assert_series_equal(_round_trip(series), series, check_freq=False)


def test_only_plain_data_crosses():
    with pytest.raises(WireError):
        encode(object())
    with pytest.raises(WireError):
        encode(lambda: None)


def test_only_named_functions_run_on_a_worker(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    (job / "job.json").write_text(json.dumps({"call": "os:system", "items": ["true"]}))
    with pytest.raises(ValueError, match="does not run"):
        worker.answer(job)
    pool = SuitePool(FakeCompute(tmp_path))
    try:
        with pytest.raises(ValueError, match="does not run"):
            pool.submit(print, "x").result(timeout=5)
    finally:
        pool.shutdown()


def test_a_round_on_the_workers_matches_the_round_here(tmp_path, fake, fake_compute):
    here = make_runtime(tmp_path / "here", fake)
    remote = make_runtime(tmp_path / "remote", fake)
    pool = SuitePool(fake_compute, extras=site_blocks)
    remote.monitor.compute = pool
    try:
        expected = here.run_round()
        got = remote.run_round()
        assert got["status"] == expected["status"] == "ok", got
        assert fake_compute.sent, "the analyses went to the compute workers"
        # The loops travel together (D6): fewer tasks than loops.
        loops = len(here.loops.list_loops())
        assert len(fake_compute.sent) < loops
        assert {item["kind"] for item in fake_compute.sent} == {"loop"}

        def scores(runtime):
            found = runtime.latest.summaries("cpm", "loop")
            return {
                loop_id: {
                    key: summary.get(key) for key in ("status", "health", "priority", "summary")
                }
                for loop_id, summary in found.items()
            }

        assert scores(remote) and scores(remote) == scores(here)
    finally:
        pool.shutdown()
        here.shutdown()
        remote.shutdown()


def test_block_code_runs_on_a_worker_with_its_errors(fake_compute):
    pool = SuitePool(fake_compute)
    code = RemoteCodePool(pool, timeout=30)
    good = sandbox.Call(
        key="k1",
        code="def run(inputs, params, ctx):\n    return {'y': inputs['x'] * params['k']}\n",
        inputs={"x": pd.Series([1.0, 2.0])},
        params={"k": 3},
    )
    bad = sandbox.Call(key="k2", code="import os\n", inputs={}, params={})
    try:
        with priority("interactive"):
            given, state = code.run(good)
        pd.testing.assert_series_equal(given["y"], pd.Series([3.0, 6.0]))
        assert state == {}
        assert fake_compute.sent[-1]["priority"] == "interactive"
        assert fake_compute.sent[-1]["kind"] == "code"
        with pytest.raises(sandbox.BlockCodeError):
            code.run(bad)
    finally:
        pool.shutdown()


def test_a_task_that_fails_fails_each_of_its_items(fake_compute, monkeypatch):
    pool = SuitePool(fake_compute)

    def broken(job_dir):
        raise RuntimeError("the worker stopped")

    monkeypatch.setattr(worker, "answer", broken)
    try:
        future = pool.submit(
            worker.run_block_code, {"key": "k", "code": "", "inputs": {}, "params": {}}
        )
        with pytest.raises(suite_compute.ComputeTaskError, match="the worker stopped"):
            future.result(timeout=10)
    finally:
        pool.shutdown()


def test_each_placement_travels_in_its_own_tasks(fake_compute):
    """An algorithm's environment and size go with its tasks; calls of different placements
    never share a task."""

    pool = SuitePool(fake_compute, linger=0.2)
    code = "def run(inputs, params, ctx):\n    return {'y': 1}\n"
    call = {"key": "k", "code": code, "inputs": {}, "params": {}}
    try:
        futures = [pool.submit(worker.run_block_code, dict(call)) for _ in range(2)]
        with suite_compute.placement({"environment": "ml", "size": "large"}):
            futures += [pool.submit(worker.run_block_code, dict(call)) for _ in range(3)]
        for future in futures:
            future.result(timeout=10)
    finally:
        pool.shutdown()
    where = sorted(
        (item.get("environment"), item.get("size"), item["items"]) for item in fake_compute.sent
    )
    assert where == [("ml", "large", 3), ("standard", "small", 2)]


def test_a_batch_too_large_for_one_task_goes_as_several(fake_compute):
    """1000 loops of a long window made tasks over the 64 MB a worker takes (the Mac mini,
    2026-10-26): a batch over the limit is halved until each part fits."""

    pool = SuitePool(fake_compute, linger=0.2, max_task_bytes=3000)
    code = "def run(inputs, params, ctx):\n    return {'y': len(params['pad'])}\n"
    try:
        futures = [
            pool.submit(
                worker.run_block_code,
                {"key": "k", "code": code, "inputs": {}, "params": {"pad": "x" * 500}},
            )
            for _ in range(8)
        ]
        for future in futures:
            future.result(timeout=10)
        huge = pool.submit(
            worker.run_block_code,
            {"key": "k", "code": code, "inputs": {}, "params": {"pad": "x" * 5000}},
        )
        with pytest.raises(suite_compute.ComputeTaskError, match="larger than a compute task"):
            huge.result(timeout=10)
    finally:
        pool.shutdown()
    assert len(fake_compute.sent) > 1
    assert sum(item["items"] for item in fake_compute.sent) == 8


def test_signal_quality_on_the_workers_matches_the_check_here(tmp_path, sq_fake, fake_compute):
    from tests.conftest import make_signal_runtime

    here = make_signal_runtime(tmp_path / "here", sq_fake)
    remote = make_signal_runtime(tmp_path / "remote", sq_fake)
    pool = SuitePool(fake_compute, processes=2)
    remote.quality_engine.compute = pool
    try:
        assert here.run_signal_quality("manual")["status"] == "ok"
        assert remote.run_signal_quality("manual")["status"] == "ok"
        assert {item["kind"] for item in fake_compute.sent} == {"signals"}
        # One chunk per task, as many chunks as slots: every slot judges a part of each batch
        # (two tasks of 150 and 50 signals left the cloud bench's other slots idle, 2026-10-27).
        assert {item["items"] for item in fake_compute.sent} == {1}
        assert 8 <= remote.signal_store.count() <= 200  # one batch, cut for two slots
        assert len(fake_compute.sent) == 2

        def verdicts(runtime):
            return {
                signal_id: (row.get("status"), row.get("quality"), row.get("apt"))
                for signal_id, row in runtime.quality_results.latest_many().items()
            }

        assert verdicts(remote) and verdicts(remote) == verdicts(here)
    finally:
        pool.shutdown()
        here.shutdown()
        remote.shutdown()


def test_a_task_carries_the_site_block_versions_its_diagram_uses(tmp_path, monkeypatch):
    from linkcraft.blocks import site

    monkeypatch.delenv(site.FOLDER_VARIABLE, raising=False)  # put back after the test
    here = tmp_path / "here"
    site.set_folder(here)
    block_id = "custom.drift.v3"
    assert site.path_of(block_id) is not None
    site.path_of(block_id).write_text('{"name": "Drift"}', encoding="utf-8")
    diagram = {"nodes": [{"id": "n1", "block": block_id}, {"id": "n2", "block": "core.mean"}]}
    extras = site_blocks([{"diagram": diagram}, {"diagram": None}, "plain"])
    assert extras == {"blocks": {block_id: '{"name": "Drift"}'}}
    assert site_blocks([{"diagram": {"nodes": [{"block": "core.mean"}]}}]) == {}
    # The worker keeps them in its own folder, by their pinned id only.
    there = tmp_path / "there"
    site.set_folder(there)
    worker._keep_blocks({**extras["blocks"], "../../escape": "x", "/etc/passwd": "x"})
    assert (there / f"{block_id}.json").read_text(encoding="utf-8") == '{"name": "Drift"}'
    assert sorted(path.name for path in there.rglob("*") if path.is_file()) == [f"{block_id}.json"]
