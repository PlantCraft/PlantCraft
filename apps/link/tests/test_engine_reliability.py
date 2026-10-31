"""The engine survives crashed and hung tasks, failed reads, downtime and restarts."""

from __future__ import annotations

import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from linkcraft.db import Database
from linkcraft.engine.compute import ComputePool, task_timeout
from linkcraft.engine.jobs import JobStore
from linkcraft.engine.service import Engine
from tests.plant import sid


def test_a_task_that_kills_its_worker_fails_alone_and_the_pool_recovers():
    pool = ComputePool(1)
    try:
        assert pool.call(abs, -1) == 1
        # os._exit stands in for a segfault or an out-of-memory kill in a method.
        future = pool.submit(os._exit, 7)
        with pytest.raises(BrokenProcessPool):
            future.result(timeout=60)  # used to deadlock in the pool's own thread
        assert not pool.disabled
        assert pool.call(abs, -2) == 2
    finally:
        pool.shutdown()


def test_tasks_queued_behind_a_crashing_one_still_run():
    pool = ComputePool(2)
    try:
        before = [pool.submit(abs, -n) for n in range(20)]
        poison = pool.submit(os._exit, 7)
        after = [pool.submit(abs, -n) for n in range(20)]
        assert [future.result(timeout=60) for future in before + after] == list(range(20)) * 2
        with pytest.raises(BrokenProcessPool):
            poison.result(timeout=60)
    finally:
        pool.shutdown()


def test_a_hung_task_is_reported_as_timed_out_and_the_pool_is_replaced():
    pool = ComputePool(1)
    try:
        hung = pool.submit(time.sleep, 600)
        started = time.monotonic()
        outcomes = list(pool.as_completed([hung], timeout=1))
        assert time.monotonic() - started < 30
        assert [type(error) for _, error in outcomes] == [TimeoutError]
        assert pool.call(abs, -3) == 3
    finally:
        pool.shutdown()


def test_a_task_that_takes_too_much_memory_fails_alone(monkeypatch):
    monkeypatch.setenv("LINKCRAFT_TASK_MEMORY_MB", "300")
    pool = ComputePool(1)
    try:
        with pytest.raises(MemoryError):
            pool.call(bytearray, 2 * 1024**3)
        assert pool.call(len, bytearray(10 * 1024**2)) == 10 * 1024**2
    finally:
        pool.shutdown()


def test_task_timeout_is_configurable(monkeypatch):
    monkeypatch.delenv("LINKCRAFT_TASK_TIMEOUT_SECONDS", raising=False)
    assert task_timeout() == 300
    monkeypatch.setenv("LINKCRAFT_TASK_TIMEOUT_SECONDS", "12.5")
    assert task_timeout() == 12.5
    monkeypatch.setenv("LINKCRAFT_TASK_TIMEOUT_SECONDS", "0")
    assert task_timeout() is None


def test_a_hung_loop_gets_a_failed_result_instead_of_stalling_the_round(runtime):
    monitor = runtime.monitor

    class HangingPool(ComputePool):
        def as_completed(self, futures, timeout=None):
            yield from (
                (future, TimeoutError("analysis took longer than 1 s")) for future in futures
            )

    runtime.sync_loops()
    monitor.compute = HangingPool(0)
    snapshot = monitor.run_once()
    assert snapshot["status"] == "ok"
    reason = snapshot["loops"]["fic-101"]["summary"]["operating_state_reason"]
    assert "TimeoutError" in reason


def test_a_failed_batch_read_keeps_the_last_results_of_its_loops(runtime, monkeypatch):
    from linkcraft.loops import monitor as monitor_module

    monkeypatch.setattr(monitor_module, "READ_BATCH", 1)
    runtime.sync_loops()
    monitor = runtime.monitor
    first = monitor.run_once()
    assert set(first["loops"]) == {"fic-101", "lic-102", "pic-103", "tic-104", "fic-105"}
    before = monitor.latest.get("cpm", "loop", "lic-102")

    plant = monitor.plant
    original = plant.read_range

    def failing(start, end, sample_seconds, *, tags, text_signals=()):
        if sid("LIC-102.PV") in tags:
            raise ConnectionError("PlantCraft unreachable")
        return original(start, end, sample_seconds, tags=tags, text_signals=text_signals)

    monkeypatch.setattr(plant, "read_range", failing)
    second = monitor.run_once()
    assert second["status"] == "ok"
    # The unread loop is not analysed as "no data": it keeps its last result.
    assert "lic-102" not in second["loops"]
    assert second["unread_loops"] == 1
    assert monitor.latest.get("cpm", "loop", "lic-102") == before


def test_a_round_keeps_only_a_few_loops_out_at_once(runtime, monkeypatch):
    """A plant of thousands of loops never holds every loop's data at once (an Analytics of
    2050 loops passed 4 GB and was killed, round after round)."""

    from linkcraft.loops import monitor as monitor_module

    monkeypatch.setattr(monitor_module, "READ_BATCH", 1)
    monkeypatch.setattr(monitor_module, "OPEN_LOOPS", 2)
    runner = ThreadPoolExecutor(8)
    out: list[Future] = []
    most = []

    class SlowPool(ComputePool):
        def submit(self, function, argument):
            most.append(sum(not future.done() for future in out) + 1)
            future = runner.submit(lambda: (time.sleep(0.05), function(argument))[1])
            out.append(future)
            return future

    runtime.sync_loops()
    runtime.monitor.compute = SlowPool(0)
    snapshot = runtime.monitor.run_once()
    runner.shutdown()
    assert snapshot["status"] == "ok"
    assert len(snapshot["loops"]) == 5
    assert max(most) <= 2


def test_jobs_left_running_by_a_stopped_engine_cancel_their_compute_tasks(tmp_path):
    jobs = JobStore(Database(tmp_path / "jobs.sqlite3"))
    job = jobs.create_job(loop_id="L1", name="x", kind="manual")
    jobs.claim_next("test")
    cancelled = []
    engine = SimpleNamespace(
        started=False,
        jobs=jobs,
        rt=SimpleNamespace(cancel_compute=cancelled.append),
        dispatcher=SimpleNamespace(start=lambda: None),
        sampler=SimpleNamespace(start=lambda: None),
    )
    Engine.start(engine, scheduler=False)
    assert cancelled == [job]
    assert jobs.claim_next("test")["job_id"] == job


def test_a_round_with_processcraft_down_reports_an_error(runtime, monkeypatch):
    runtime.sync_loops()

    def down(*_args, **_kwargs):
        raise ConnectionError("PlantCraft unreachable")

    monkeypatch.setattr(runtime.monitor.plant, "read_range", down)
    assert runtime.monitor.run_once()["status"] == "error"


def test_the_tick_prunes_the_health_history_at_most_hourly():
    from linkcraft.api.runtime import Runtime

    calls: list[float] = []
    latest = SimpleNamespace(
        prune_history=lambda days: calls.append(days) or 0,
        thin_history=lambda full_days: calls.append(("full", full_days)) or 0,
    )
    quality = SimpleNamespace(
        prune=lambda days: calls.append(days) or 0,
        thin_history=lambda full_days: calls.append(("full", full_days)) or 0,
    )
    jobs = SimpleNamespace(
        prune_jobs=lambda days: calls.append(days) or 0,
        prune_detail=lambda keep: calls.append(keep) or 0,
        thin_summaries=lambda: calls.append("thin") or 0,
    )
    runtime = SimpleNamespace(
        latest=latest,
        quality_results=quality,
        jobs=jobs,
        _last_prune=-1e9,
        _summaries_thin=False,
        _last_stall_check=-1e9,
        events=SimpleNamespace(check_stalled=lambda: calls.append("stalled") or 0),
        migrate_asset_schedules=lambda: 0,
        add_model_examples=lambda: None,
        retire_old_series=lambda: None,
    )
    Runtime.tick(runtime)
    Runtime.tick(runtime)
    # Old summaries thinned until none is left, then the stalled schedules every 5 minutes.
    assert calls == ["thin", 90, 90, ("full", 14), ("full", 14), 90, 50, "stalled"]


def test_old_finished_runs_are_pruned_but_each_subject_keeps_its_newest(tmp_path):
    from linkcraft.db import recorded_at

    jobs = JobStore(Database(tmp_path / "jobs.sqlite3"))
    old = datetime.now().astimezone() - timedelta(days=120)
    with recorded_at(old):
        gone = jobs.create_job(loop_id="L1", name="x", kind="scheduled")
        newest_of_l2 = jobs.create_job(loop_id="L2", name="x", kind="scheduled")
        waiting = jobs.create_job(loop_id="L1", name="x", kind="scheduled")
    jobs.fail_job(gone, "boom")
    jobs.fail_job(newest_of_l2, "boom")
    recent = jobs.create_job(loop_id="L1", name="x", kind="scheduled")
    jobs.fail_job(recent, "boom")
    assert jobs.prune_jobs(days=90) == 1
    assert jobs.get_job(gone) is None
    assert jobs.get_job(newest_of_l2) and jobs.get_job(waiting) and jobs.get_job(recent)


def test_prune_history_drops_old_points(tmp_path):
    from linkcraft.engine.latest import LatestStore

    latest = LatestStore(Database(tmp_path / "latest.sqlite3"))
    old = (datetime.now(UTC) - timedelta(days=200)).isoformat(timespec="seconds")
    recent = datetime.now(UTC).isoformat(timespec="seconds")
    for stamp in (old, recent):
        latest.save_many(
            "cpm",
            "loop",
            [
                {
                    "subject_id": "L1",
                    "status": "normal",
                    "health": 90,
                    "summary": {},
                    "results": [],
                    "source_start": stamp,
                    "source_end": stamp,
                }
            ],
        )
    assert latest.prune_history(days=90) == 1
    assert [point["source_end"] for point in latest.history("cpm", "loop", "L1", days=400)] == [
        recent
    ]


def test_prune_history_keeps_a_recorded_source(tmp_path):
    # A recorded source from last year: its newest point, not today's clock, sets the cutoff.
    from linkcraft.engine.latest import LatestStore

    latest = LatestStore(Database(tmp_path / "latest.sqlite3"))
    for stamp in ("2025-01-01 00:00:00", "2025-01-02 12:00:00"):
        latest.save_many(
            "cpm",
            "loop",
            [
                {
                    "subject_id": "L1",
                    "status": "normal",
                    "health": 90,
                    "summary": {},
                    "results": [],
                    "source_start": stamp,
                    "source_end": stamp,
                }
            ],
        )
    assert latest.prune_history(days=90) == 0
    assert latest.prune_history(days=1) == 1


def test_a_round_gives_its_freed_memory_back_and_a_loop_waits_for_the_minute(monkeypatch):
    from linkcraft.engine import service

    released = []
    monkeypatch.setattr(service, "release", lambda: released.append(True) or True)
    events = SimpleNamespace(after=lambda job_id: None)

    def engine(outcome):
        def run(job):
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        return SimpleNamespace(_execute=run, rt=SimpleNamespace(events=events))

    assert Engine.execute(engine("done"), {"job_id": "a", "work": "round"}) == "done"
    assert len(released) == 1
    with pytest.raises(RuntimeError):
        Engine.execute(engine(RuntimeError("read failed")), {"job_id": "b", "work": "replay"})
    assert len(released) == 2  # a failed round freed its data too
    Engine.execute(engine("done"), {"job_id": "c", "work": "loop"})
    assert len(released) == 2  # one loop: the engine's Releaser, every minute
