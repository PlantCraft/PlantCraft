"""History replay: past rounds and schedule occurrences computed over the archive, once."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from linkcraft.config import AnalysisConfig
from linkcraft.loops.replay import past_slots
from tests.conftest import client_for, make_runtime
from tests.plant import NOW, SAMPLE_SECONDS


def _runtime(tmp_path, fake):
    rt = make_runtime(
        tmp_path, fake, analysis=AnalysisConfig(window_minutes=120, resample_seconds=SAMPLE_SECONDS)
    )
    rt.run_round()
    return rt


def _schedule(rt) -> str:
    return rt.jobs.create_schedule(
        name="Hourly stiction check",
        loop_id="fic-105",
        cadence="hourly",
        timezone="America/Sao_Paulo",
        lookback_minutes=60,
        profile_id=None,
        method_config=rt.loops.effective_method_config(rt.loops.get_loop("fic-105")),
    )


def test_past_slots_follow_each_cadence():
    start = datetime(2026, 10, 1, 0, 30, tzinfo=UTC)
    end = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
    hourly = past_slots({"cadence": "hourly"}, start, end)
    assert hourly[0] == datetime(2026, 10, 1, 1, 0, tzinfo=UTC) and hourly[-1] == end
    every = past_slots({"cadence": "interval", "interval_minutes": 30}, start, end)
    assert len(every) == 2 * len(hourly) - 1
    daily = past_slots(
        {"cadence": "daily", "time_local": "07:00", "timezone": "America/Sao_Paulo"}, start, end
    )
    assert [slot.hour for slot in daily] == [10, 10, 10]  # 07:00 in Sao Paulo is 10:00 UTC
    assert past_slots({"cadence": "once"}, start, end) == []


def test_replay_fills_health_history_and_past_runs_once(tmp_path, fake):
    rt = _runtime(tmp_path, fake)
    try:
        schedule_id = _schedule(rt)
        live = rt.latest.get("cpm", "loop", "fic-105")
        before = len(rt.latest.history("cpm", "loop", "fic-105", days=3650))

        state = rt.replay.replay(hours=6, step_minutes=60)

        # Rounds every hour from two hours in (the window) to an hour before the newest data.
        assert state["rounds"] == 3
        history = rt.latest.history("cpm", "loop", "fic-105", days=3650)
        assert len(history) == before + 3
        assert rt.latest.get("cpm", "loop", "fic-105")["source_end"] == live["source_end"]
        replayed = [run for (app, _), run in fake.links.runs.items() if "replay" in run["id"]]
        assert len(replayed) == 3
        assert all(run["status"] == "done" for run in replayed)
        health = sorted(fake.derived["app-linkcraft:fic-105.flow_loop.health"])
        assert len([stamp for stamp in health if stamp < live["source_end"].replace(" ", "T")]) >= 3

        jobs = rt.jobs.list_jobs(loop_id="fic-105", limit=100)
        past = [job for job in jobs if job.get("schedule_id") == schedule_id]
        assert len(past) == state["runs"] == 5  # 08:00 .. 12:00 UTC, an hour of lookback each
        assert all(job["status"] == "completed" for job in past)
        newest = max(past, key=lambda job: job["requested_at"])
        assert datetime.fromisoformat(newest["requested_at"]) == NOW
        assert datetime.fromisoformat(newest["completed_at"]) == NOW + timedelta(seconds=20)
        assert newest["source_end"] <= str(NOW.replace(tzinfo=None))

        again = rt.replay.replay(hours=6, step_minutes=60)
        assert again["rounds"] == 0 and again["runs"] == 0 and again["skipped"] == 3 + 5
        assert len(rt.latest.history("cpm", "loop", "fic-105", days=3650)) == before + 3
        assert (
            len(
                [
                    j
                    for j in rt.jobs.list_jobs(loop_id="fic-105", limit=100)
                    if j.get("schedule_id") == schedule_id
                ]
            )
            == 5
        )
    finally:
        rt.shutdown()


def test_replay_is_for_admins_and_runs_in_the_background(tmp_path, fake):
    rt = _runtime(tmp_path, fake)
    try:
        with client_for(rt, fake, "engineer") as engineer:
            assert engineer.post("/link/api/history/replay", json={"hours": 6}).status_code == 403
        with client_for(rt, fake, "admin") as admin:
            answer = admin.post("/link/api/history/replay", json={"hours": 6, "step_minutes": 60})
            assert answer.status_code == 202 and answer.json()["started"] is True
            for _ in range(200):
                state = admin.get("/link/api/history/replay").json()
                if not state["running"]:
                    break
                time.sleep(0.05)
            assert state["rounds"] == 3 and "error" not in state
    finally:
        rt.shutdown()
