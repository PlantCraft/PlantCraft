"""The queue: priorities, skip when busy, spread, retries, rounds as schedules, the engine's lease
and the queue's answer."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from plantcraft_sdk.server import ops

from linkcraft.db import Database
from linkcraft.engine.dispatcher import Dispatcher, RetryLater
from linkcraft.engine.jobs import PRIORITIES, JobStore
from linkcraft.engine.process import lease_for
from tests.conftest import client_for, make_runtime


def _jobs(tmp_path) -> JobStore:
    return JobStore(Database(tmp_path / "jobs.sqlite3"))


def _interval(jobs: JobStore, **extra) -> str:
    return jobs.create_schedule(
        name="every loop",
        loop_id="*",
        cadence="interval",
        timezone="UTC",
        lookback_minutes=60,
        profile_id=None,
        method_config={},
        selector={"mode": "all"},
        interval_minutes=10,
        **extra,
    )


def test_a_person_s_request_runs_before_the_schedules_and_a_replay_last(tmp_path):
    jobs = _jobs(tmp_path)
    replay = jobs.create_job(loop_id="*", name="r", kind="replay", work="replay")
    scheduled = jobs.create_job(loop_id="L1", name="s", kind="scheduled")
    manual = jobs.create_job(loop_id="L2", name="m", kind="manual")
    order = [jobs.claim_next("test")["job_id"] for _ in range(3)]
    assert order == [manual, scheduled, replay]
    assert jobs.claim_next("test") is None
    assert jobs.get_job(manual)["priority"] == PRIORITIES["manual"]


def test_an_execution_waits_for_its_due_time(tmp_path):
    jobs = _jobs(tmp_path)
    later = (datetime.now(UTC) + timedelta(minutes=5)).isoformat(timespec="seconds")
    jobs.create_job(loop_id="L1", name="x", kind="manual", due_at=later)
    assert jobs.claim_next("test") is None
    assert jobs.next_due_at() == later


def test_an_occurrence_is_skipped_while_the_previous_one_runs(tmp_path):
    jobs = _jobs(tmp_path)
    schedule_id = _interval(jobs)
    (first,) = jobs.materialize_occurrence(schedule_id, ["L1"])
    jobs.claim_next("test")
    assert jobs.get_job(first)["status"] == "running"
    # Due again while L1 still runs: L1 is recorded as skipped, L2 is queued.
    with jobs._connect() as connection:
        connection.execute(
            "UPDATE analysis_schedules SET next_run_at = ? WHERE schedule_id = ?",
            ((datetime.now(UTC) - timedelta(minutes=1)).isoformat(timespec="seconds"), schedule_id),
        )
    created = jobs.materialize_occurrence(schedule_id, ["L1", "L2"])
    assert [jobs.get_job(job_id)["loop_id"] for job_id in created] == ["L2"]
    skipped = jobs.list_jobs(statuses={"skipped"})
    assert [(row["loop_id"], bool(row["error_message"])) for row in skipped] == [("L1", True)]
    assert jobs.get_schedule(schedule_id)["last_summary"] == {"jobs": 1, "skipped": 1}


def test_a_spread_schedule_places_each_subject_at_the_same_offset(tmp_path):
    jobs = _jobs(tmp_path)
    schedule_id = _interval(jobs)
    jobs.update_schedule(schedule_id, name="spread")
    with jobs._connect() as connection:
        connection.execute(
            "UPDATE analysis_schedules SET spread_minutes = 30 WHERE schedule_id = ?",
            (schedule_id,),
        )
    slot = datetime.fromisoformat(jobs.get_schedule(schedule_id)["next_run_at"]).astimezone(UTC)
    created = jobs.materialize_occurrence(schedule_id, [f"L{n}" for n in range(20)])
    offsets = [
        (datetime.fromisoformat(jobs.get_job(job_id)["due_at"]) - slot).total_seconds()
        for job_id in created
    ]
    assert all(0 <= offset <= 1800 for offset in offsets)
    assert len(set(offsets)) > 10


def test_a_data_read_failure_is_tried_again_then_fails_with_the_reason(tmp_path):
    jobs = _jobs(tmp_path)
    job_id = jobs.create_job(loop_id="L1", name="x", kind="manual")
    tries: list[int] = []

    def run(job):
        tries.append(job["attempts"])
        raise RetryLater("PlantCraft timed out")

    dispatcher = Dispatcher(jobs, run, slots=1, max_attempts=2)
    assert dispatcher.run_next()
    job = jobs.get_job(job_id)
    assert job["status"] == "queued" and job["due_at"] > jobs.utc_now()
    assert "timed out" in job["error_message"]
    with jobs._connect() as connection:
        connection.execute("UPDATE analysis_jobs SET due_at = NULL WHERE job_id = ?", (job_id,))
    assert dispatcher.run_next()
    job = jobs.get_job(job_id)
    assert job["status"] == "failed" and tries == [1, 2]


def test_a_schedule_s_retries_wait_count_and_give_up_before_its_next_occurrence(tmp_path):
    """A schedule says how its executions try again (as Elipse EPM): how many
    more tries, how far apart, and to give up when the next occurrence comes first."""

    jobs = _jobs(tmp_path)

    def run(_job):
        raise RetryLater("PlantCraft timed out")

    dispatcher = Dispatcher(jobs, run, slots=1)
    retry = {"enabled": True, "count": 1, "wait_minutes": 5, "abort_on_next": False}
    schedule_id = _interval(jobs, retry=retry)
    assert jobs.get_schedule(schedule_id)["retry"] == retry
    job_id = jobs.create_job(loop_id="L1", name="x", kind="scheduled", schedule_id=schedule_id)
    assert dispatcher.run_next()
    job = jobs.get_job(job_id)
    wait = datetime.fromisoformat(job["due_at"]) - datetime.now(UTC)
    assert job["status"] == "queued" and timedelta(minutes=4) < wait <= timedelta(minutes=5)
    with jobs._connect() as connection:
        connection.execute("UPDATE analysis_jobs SET due_at = NULL WHERE job_id = ?", (job_id,))
    assert dispatcher.run_next()
    assert jobs.get_job(job_id)["status"] == "failed"  # 1 + 1 tries

    # The next occurrence in 2 minutes comes before a try in 5: it gives up at once.
    soon = (datetime.now(UTC) + timedelta(minutes=2)).isoformat(timespec="seconds")
    jobs.update_schedule(schedule_id, retry={**retry, "abort_on_next": True})
    with jobs._connect() as connection:
        connection.execute(
            "UPDATE analysis_schedules SET next_run_at = ? WHERE schedule_id = ?",
            (soon, schedule_id),
        )
    job_id = jobs.create_job(loop_id="L1", name="x", kind="scheduled", schedule_id=schedule_id)
    assert dispatcher.run_next()
    job = jobs.get_job(job_id)
    assert job["status"] == "failed" and "next occurrence comes first" in job["error_message"]

    # Retries off: the first failure is the last.
    jobs.update_schedule(schedule_id, retry={**retry, "enabled": False})
    job_id = jobs.create_job(loop_id="L1", name="x", kind="scheduled", schedule_id=schedule_id)
    assert dispatcher.run_next()
    assert jobs.get_job(job_id)["status"] == "failed"

    # Its record: three executions failed, the first after a second try.
    stats = jobs.schedule_stats(schedule_id)
    assert (stats["executions"], stats["failed"], stats["retried"]) == (3, 3, 1)
    assert stats["last_status"] == "failed" and stats["last_change"] is None
    assert stats["seconds_max"] >= stats["seconds_mean"] >= stats["seconds_min"] >= 0


def test_a_calendar_schedule_previews_saves_and_changes(tmp_path, fake):
    rt = make_runtime(tmp_path, fake)
    try:
        rt.sync_loops()
        body = {
            "name": "Shift reports",
            "cadence": "calendar",
            "recurrence": {"freq": "weeks", "weekdays": [0, 2, 4], "times": ["06:00", "18:00"]},
            "timezone": "America/Sao_Paulo",
            "selector": {"mode": "all"},
            "lookback_minutes": 720,
        }
        with client_for(rt, fake, "engineer") as client:
            preview = client.post("/link/api/schedules/preview", json=body).json()
            assert preview["when"] == "Every week on Mon, Wed, Fri at 06:00 and 18:00"
            local = [
                datetime.fromisoformat(item).astimezone(ZoneInfo("America/Sao_Paulo"))
                for item in preview["next_runs"]
            ]
            assert len(local) == 5
            assert {item.weekday() for item in local} <= {0, 2, 4}
            assert {item.hour for item in local} == {6, 18}
            local = client.post("/link/api/schedules/preview", json={**body, "timezone": "local"})
            assert local.status_code == 200 and len(local.json()["next_runs"]) == 5
            unknown = {**body, "timezone": "Mars/Base"}
            assert client.post("/link/api/schedules/preview", json=unknown).status_code == 422
            missing = client.post("/link/api/schedules", json={**body, "recurrence": None})
            assert missing.status_code == 422
            bad = {**body, "recurrence": {"freq": "weeks", "times": ["06:00"]}}
            assert client.post("/link/api/schedules", json=bad).status_code == 422
            created = client.post("/link/api/schedules", json=body)
            assert created.status_code == 201, created.text
            schedule = created.json()
            assert schedule["when"] == preview["when"]
            assert schedule["retry"] == {
                "enabled": True,
                "count": 2,
                "wait_minutes": 5.0,
                "abort_on_next": True,
            }
            changed = client.patch(
                f"/link/api/schedules/{schedule['schedule_id']}",
                json={
                    "recurrence": {"freq": "minutes", "every": 30, "between": ["08:00", "17:00"]},
                    "retry": {"enabled": False},
                },
            ).json()
            assert changed["when"] == "Every 30 minutes, 08:00 to 17:00"
            assert changed["retry"]["enabled"] is False
            stamp = datetime.fromisoformat(changed["next_run_at"])
            following = stamp.astimezone(ZoneInfo("America/Sao_Paulo"))
            assert following.minute in {0, 30} and 8 <= following.hour <= 17
            # Back to every 15 minutes, then to a calendar on days: the old step goes.
            path = f"/link/api/schedules/{schedule['schedule_id']}"
            plain = client.patch(path, json={"cadence": "interval", "interval_minutes": 15}).json()
            assert plain["interval_minutes"] == 15
            daily = {"freq": "days", "times": ["06:00"]}
            days = client.patch(path, json={"cadence": "calendar", "recurrence": daily}).json()
            assert days["interval_minutes"] is None and days["when"] == "Every day at 06:00"
    finally:
        rt.shutdown()


def test_an_execution_that_raises_fails_alone(tmp_path):
    jobs = _jobs(tmp_path)
    bad = jobs.create_job(loop_id="L1", name="x", kind="manual")
    good = jobs.create_job(loop_id="L2", name="y", kind="scheduled")

    def run(job):
        if job["job_id"] == bad:
            raise ValueError("broken")
        jobs.finish(job["job_id"], "completed")

    assert Dispatcher(jobs, run, slots=1).drain() == 2
    assert (
        jobs.get_job(bad)["status"] == "failed" and "broken" in jobs.get_job(bad)["error_message"]
    )
    assert jobs.get_job(good)["status"] == "completed"


def test_the_monitoring_round_is_a_schedule_that_queues_one_execution(tmp_path, fake):
    rt = make_runtime(tmp_path, fake)
    try:
        rt.sync_loops()
        created = rt.engine.scheduler.run_due_schedules()
        works = sorted(rt.jobs.get_job(job_id)["schedule_id"] for job_id in created)
        assert works == ["round-cpm", "round-signal_quality"]
        assert rt.engine.dispatcher.drain() == 2
        rounds = [rt.jobs.get_job(job_id) for job_id in created]
        assert {job["status"] for job in rounds} == {"completed"}
        loops = next(job for job in rounds if job["schedule_id"] == "round-cpm")
        assert loops["work"] == "round" and loops["progress_done"] == loops["progress_total"] > 0
        # The round's header is kept with its schedule: the pages read it from there.
        header = rt.round_header()
        assert header["status"] == "ok" and rt.status()["round"] == header
        assert rt.status()["running"] is False
        # Not due again until its interval has passed.
        assert rt.engine.scheduler.run_due_schedules() == []
    finally:
        rt.shutdown()


def test_a_round_the_data_did_not_answer_is_tried_again(tmp_path, fake, monkeypatch):
    rt = make_runtime(tmp_path, fake)
    try:
        job_id = rt.queue_round("round-signal_quality", user="ana")
        refused = "PlantCraft answered 502: The Historian could not be reached: Connection refused"
        monkeypatch.setattr(
            rt, "run_scheduled_round", lambda *_args: {"status": "error", "error": refused}
        )
        rt.engine.dispatcher.drain()
        for _ in range(50):  # the engine's own thread may have taken it
            job = rt.jobs.get_job(job_id)
            if job["status"] != "running":
                break
            time.sleep(0.1)
        assert job["status"] == "queued" and job["error_message"] == refused
    finally:
        rt.shutdown()


def test_run_now_queues_a_round_once(tmp_path, fake):
    rt = make_runtime(tmp_path, fake)
    try:
        first = rt.queue_round("round-cpm", user="ana")
        assert first and rt.queue_round("round-cpm", user="ana") is None
        assert rt.jobs.get_job(first)["priority"] == PRIORITIES["manual"]
    finally:
        rt.shutdown()


def test_the_queue_answer_has_the_suite_format(tmp_path, fake):
    rt = make_runtime(tmp_path, fake)
    try:
        later = (datetime.now(UTC) + timedelta(hours=1)).isoformat(timespec="seconds")
        rt.jobs.create_job(loop_id="L1", name="x", kind="manual", due_at=later)
        rt.engine.sampler.sample()
        with client_for(rt, fake, "engineer") as client:
            answer = client.get("/link/api/queue?window=1h").json()
            assert client.get("/link/api/queue?window=2h").status_code == 422
        assert answer["format"] == "plantcraft-queue/1" and answer["window"] == "1h"
        assert answer["now"]["queued"] == 1 and answer["now"]["workers"] > 0
        assert answer["history"] and answer["history"][-1]["queued"] == 1
    finally:
        rt.shutdown()


def test_the_queue_lists_what_a_person_asked_for_with_cancel(tmp_path, fake):
    rt = make_runtime(tmp_path, fake)
    try:
        later = (datetime.now(UTC) + timedelta(hours=1)).isoformat(timespec="seconds")
        asked = rt.jobs.create_job(
            loop_id="L1", name="Ana's run", kind="manual", created_by="ana", due_at=later
        )
        rt.jobs.create_job(loop_id="L2", name="scheduled", kind="schedule", due_at=later)
        with client_for(rt, fake, "engineer") as client:
            answer = client.get("/link/api/queue").json()
        assert answer["url"] == "executions"
        [item] = answer["items"]
        assert item["id"] == asked and item["by"] == "ana" and item["status"] == "queued"
        assert item["url"] == f"/link/runs/{asked}"
        assert item["cancel"] == {
            "label": "Cancel",
            "method": "POST",
            "href": f"/link/api/executions/{asked}/cancel",
        }
        rt.jobs.cancel_job(asked)
        # The answer is kept a few seconds; the app's own Cancel reads it again at once.
        rt.queue_changed()
        with client_for(rt, fake, "engineer") as client:
            [item] = client.get("/link/api/queue").json()["items"]
        assert item["status"] == "cancelled" and "cancel" not in item
    finally:
        rt.shutdown()


def test_the_ops_metrics_carry_the_queue_for_plantcraft_s_watch(tmp_path, fake):
    rt = make_runtime(tmp_path, fake)
    try:
        later = (datetime.now(UTC) + timedelta(hours=1)).isoformat(timespec="seconds")
        rt.jobs.create_job(loop_id="L1", name="x", kind="manual", due_at=later)
        with client_for(rt, fake, "admin") as client:
            queue = client.get("/link/api/ops/metrics").json()["queue"]
        assert queue["queued"] == 1 and queue["workers"] > 0 and "delay_seconds" in queue
    finally:
        rt.shutdown()
    assert "queue" not in ops.metrics("linkcraft", "0")


def test_one_engine_holds_the_database_and_a_second_waits(tmp_path):
    database = tmp_path / "linkcraft.sqlite3"
    lease = lease_for(database)
    assert lease.acquire()
    code = (
        "import sys; from pathlib import Path; from linkcraft.engine.process import lease_for; "
        "sys.exit(0 if lease_for(Path(sys.argv[1])).acquire() else 3)"
    )
    assert subprocess.run([sys.executable, "-c", code, str(database)]).returncode == 3
    lease.release()
    assert subprocess.run([sys.executable, "-c", code, str(database)]).returncode == 0


def test_the_server_starts_its_engine_again_when_it_stops(tmp_path, monkeypatch):
    from linkcraft.engine import process

    monkeypatch.setattr(process, "PARENT_SECONDS", 0.1)
    monkeypatch.setattr(process, "RESTART_SECONDS", (0.1, 0.4))
    child = process.EngineProcess(None, command=[sys.executable, "-c", "pass"])
    child.start()
    try:
        deadline = time.monotonic() + 10
        while child.restarts < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert child.restarts >= 2
    finally:
        child.stop()
    assert child.process is None


def test_a_child_engine_stops_with_its_server(tmp_path):
    from linkcraft.engine.process import run_engine

    started: list[str] = []

    class Quiet:
        def __init__(self, settings):
            self.engine = SimpleNamespace(dispatcher=SimpleNamespace(slots=1))

        def start_engine(self):
            started.append("engine")

        def shutdown(self):
            started.append("shutdown")

    settings = SimpleNamespace(database_path=tmp_path / "linkcraft.sqlite3", engine="process")
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    assert run_engine(settings, Quiet, parent=gone.pid) == 0
    assert started == []  # its server was already gone: it never started
    stop = threading.Event()
    worker = threading.Thread(target=run_engine, args=(settings, Quiet), kwargs={"stop": stop})
    worker.start()
    deadline = time.monotonic() + 10
    while not started and time.monotonic() < deadline:
        time.sleep(0.05)
    # A second engine on the same database waits as a standby while the first one runs.
    assert not lease_for(settings.database_path).acquire()
    stop.set()
    worker.join(timeout=10)
    assert started == ["engine", "shutdown"]
    assert settings.engine == "inline"  # the engine's own runtime runs everything in-process


def test_executions_list_cancel_and_run_again(tmp_path, fake):
    rt = make_runtime(tmp_path, fake)
    try:
        later = (datetime.now(UTC) + timedelta(hours=1)).isoformat(timespec="seconds")
        waiting = rt.jobs.create_job(loop_id="fic-101", name="later", kind="manual", due_at=later)
        with client_for(rt, fake, "engineer") as client:
            listed = client.get("/link/api/executions?status=queued").json()
            assert [row["id"] for row in listed["items"]] == [waiting]
            row = listed["items"][0]
            assert row["can_cancel"] and not row["can_rerun"] and row["work_label"]
            cancelled = client.post(f"/link/api/executions/{waiting}/cancel").json()
            assert cancelled["status"] == "cancelled" and cancelled["can_rerun"]
            assert client.post(f"/link/api/executions/{waiting}/cancel").status_code == 409
            again = client.post(f"/link/api/executions/{waiting}/rerun")
            assert again.status_code == 202
            assert (
                again.json()["id"] != waiting and again.json()["priority"] == PRIORITIES["manual"]
            )
            assert client.get("/link/api/executions?work=round").json()["items"] == []
            assert client.post("/link/api/executions/nope/rerun").status_code == 404
    finally:
        rt.shutdown()


def test_a_schedule_previews_what_it_queues(tmp_path, fake):
    rt = make_runtime(tmp_path, fake)
    try:
        rt.sync_loops()
        loops = len(rt.resolve_selector({"mode": "all"}))
        body = {
            "name": "Night",
            "cadence": "daily",
            "time_local": "00:00",
            "timezone": "America/Sao_Paulo",
            "selector": {"mode": "all"},
            "lookback_minutes": 1440,
            "spread_minutes": 30,
        }
        with client_for(rt, fake, "engineer") as client:
            preview = client.post("/link/api/schedules/preview", json=body).json()
            assert preview["executions"] == loops > 0
            assert len(preview["next_runs"]) == 5
            # Answered in UTC; 00:00 in the schedule's own zone.
            first, second = (datetime.fromisoformat(item) for item in preview["next_runs"][:2])
            assert all(item.endswith("Z") for item in preview["next_runs"])
            local = first.astimezone(ZoneInfo("America/Sao_Paulo"))
            assert second - first == timedelta(days=1) and local.hour == 0
            assert preview["seconds_each"] is None and preview["warning"] == ""
            # The round previews as one execution, whatever the form says about subjects.
            round_preview = client.post(
                "/link/api/schedules/preview?schedule_id=round-cpm",
                json={**body, "cadence": "interval", "interval_minutes": 10},
            ).json()
            assert round_preview["executions"] == 1
    finally:
        rt.shutdown()


def test_the_capacity_warns_when_occurrences_would_overlap(tmp_path, fake):
    rt = make_runtime(tmp_path, fake)
    try:
        job_id = rt.jobs.create_job(loop_id="L1", name="x", kind="manual")
        with rt.jobs._connect() as connection:
            connection.execute(
                "UPDATE analysis_jobs SET status = 'completed', started_at = ?, completed_at = ? "
                "WHERE job_id = ?",
                ("2026-10-23T00:00:00+00:00", "2026-10-23T00:00:30+00:00", job_id),
            )
        workers = rt.engine.live().workers
        fits = rt.capacity(workers * 10, {"cadence": "interval", "interval_minutes": 10})
        assert fits["seconds_each"] == 30 and fits["drain_seconds"] == 300 and not fits["warning"]
        late = rt.capacity(workers * 100, {"cadence": "interval", "interval_minutes": 10})
        assert late["drain_seconds"] == 3000 and "would not empty" in late["warning"]
    finally:
        rt.shutdown()


def test_rounds_and_cycles_keep_what_they_cannot_change(tmp_path, fake):
    rt = make_runtime(tmp_path, fake)
    try:
        with client_for(rt, fake, "admin") as client:
            schedules = {
                row["schedule_id"]: row for row in client.get("/link/api/schedules").json()
            }
            loops, signals = schedules["round-cpm"], schedules["round-signal_quality"]
            assert loops["work"] == "round" and loops["editable"]["delete"] is False
            assert signals["subject_label"] == "Every signal"
            assert signals["algorithm"]["id"] == "signal_quality"
            changed = client.patch(
                "/link/api/schedules/round-cpm", json={"priority": 80, "interval_minutes": 5}
            ).json()
            assert changed["priority"] == 80 and changed["interval_minutes"] == 5
            refused = client.patch(
                "/link/api/schedules/round-cpm", json={"selector": {"mode": "list", "ids": ["x"]}}
            )
            assert refused.status_code == 422
            assert client.delete("/link/api/schedules/round-cpm").status_code == 409
            detail = client.get("/link/api/schedules/round-cpm").json()
            assert detail["subject_count"] == 0 and detail["priority"] == 80
    finally:
        rt.shutdown()


def test_a_schedule_s_past_is_replayed_alone(tmp_path, fake):
    rt = make_runtime(tmp_path, fake)
    try:
        with client_for(rt, fake, "admin") as client:
            answer = client.post("/link/api/schedules/round-cpm/replay", json={"hours": 6})
            assert answer.status_code == 202
            job = rt.jobs.get_job(answer.json()["job_id"])
            assert job["work"] == "replay" and job["payload"]["schedule_id"] == "round-cpm"
            assert job["priority"] == PRIORITIES["replay"]
            rt.wait_for([job["job_id"]], 20)
            with rt.jobs._connect() as connection:  # one replay at a time
                connection.execute(
                    "UPDATE analysis_jobs SET status = 'running' WHERE job_id = ?",
                    (job["job_id"],),
                )
            busy = client.post("/link/api/schedules/round-cpm/replay", json={"hours": 6})
            assert busy.status_code == 409
            refused = client.post("/link/api/schedules/round-signal_quality/replay", json={})
            assert refused.status_code == 409
    finally:
        rt.shutdown()


def test_an_execution_says_how_many_tries_its_schedule_gives():
    from linkcraft.api.routers.executions import execution_row
    from linkcraft.engine.dispatcher import schedule_tries

    retry = {"enabled": True, "count": 2, "wait_minutes": 5.0, "abort_on_next": True}
    assert schedule_tries({"retry": retry}) == 3
    assert schedule_tries({"retry": {**retry, "enabled": False}}) == 1
    assert schedule_tries({"retry": retry, "kind": "round"}) is None
    assert schedule_tries({}) is None
    job = {"job_id": "j1", "loop_id": "FIC-101", "status": "queued", "schedule_id": "s1"}
    row = execution_row({**job, "attempts": 2}, {"s1": "Night"}, {}, {"s1": 3})
    assert (row["attempts"], row["max_attempts"]) == (2, 3)
    assert execution_row({**job, "schedule_id": None}, {}, {})["max_attempts"] is None


def test_latest_finished_keeps_each_subjects_newest_ended_run(tmp_path):
    """The Overview's Monitors and Results read one row per subject straight from SQLite (it
    decoded every run before: 4-12 s on the Mac mini)."""

    jobs = _jobs(tmp_path)
    schedule = _interval(jobs)

    def ended(subject: str, value: float, *, work: str = "asset", fail: bool = False, **extra):
        job_id = jobs.create_job(
            loop_id=subject, name="n", kind="scheduled", work=work, schedule_id=schedule, **extra
        )
        assert jobs.claim_job(job_id)
        if fail:
            jobs.fail_job(job_id, "no data")
        else:
            jobs.complete_job(
                job_id,
                results=[],
                summary={"verdict": {"value": value}},
                config_snapshot={},
                source_start=None,
                source_end=None,
            )
        time.sleep(1.01)  # rows are stamped to the second
        return job_id

    ended("a", 1)
    newest_a = ended("a", 2)
    newest_b = ended("b", 3, fail=True)
    ended("a", 9, work="replay")
    jobs.create_job(loop_id="a", name="n", kind="scheduled", schedule_id=schedule)  # queued
    found = jobs.latest_finished(schedule)
    assert {key: job["job_id"] for key, job in found.items()} == {"a": newest_a, "b": newest_b}
    assert found["a"]["summary"]["verdict"]["value"] == 2
    assert set(jobs.latest_finished(schedule, ["b"])) == {"b"}
    manual = jobs.create_job(loop_id="c", name="n", kind="manual", work="asset")
    assert jobs.claim_job(manual)
    jobs.fail_job(manual, "x")
    assert set(jobs.latest_finished(None)) == {"c"}


def test_latest_finished_reads_an_index_never_the_runs_rows(tmp_path):
    """A run's row is ~7 KB of JSON: reading every one of a monitor's runs, cold, cost the Mac
    mini 2-3 s for the Monitors list (2026-10-27). The newest run's id comes from an index."""

    jobs = _jobs(tmp_path)
    with jobs._connect() as connection:
        for schedule_id, subjects in (("s", None), ("s", ["a", "b"]), (None, None)):
            query, parameters = jobs._latest_query(schedule_id, subjects)
            plan = " ".join(
                str(row[-1])
                for row in connection.execute(f"EXPLAIN QUERY PLAN {query}", parameters)
            )
            assert "COVERING INDEX" in plan, plan


def test_an_engine_that_keeps_dying_makes_the_server_unhealthy(monkeypatch):
    from linkcraft.engine import process

    child = process.EngineProcess(None, command=[sys.executable, "-c", "pass"])
    assert child.crash_loop() is None
    now = time.monotonic()
    child._restarted_at = [now - 30, now - 20]
    assert child.crash_loop(now) is None
    child._restarted_at.append(now - 10)
    assert "LINKCRAFT_MEMORY" in child.crash_loop(now)
    # Restarts older than the window no longer count: it heals by itself.
    assert child.crash_loop(now + process.CRASH_LOOP_SECONDS + 1) is None
