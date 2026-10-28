"""Schedules run each slot once, never replay missed slots and keep local time across DST."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from linkcraft.db import Database
from linkcraft.engine.jobs import JobStore

ZONE = "America/Sao_Paulo"


def _jobs(tmp_path) -> JobStore:
    return JobStore(Database(tmp_path / "jobs.sqlite3"))


def _set_next(jobs: JobStore, schedule_id: str, stamp: datetime) -> None:
    with jobs._connect() as connection:
        connection.execute(
            "UPDATE analysis_schedules SET next_run_at = ? WHERE schedule_id = ?",
            (stamp.isoformat(timespec="seconds"), schedule_id),
        )


def _is_due(jobs: JobStore, schedule_id: str, now: datetime | None = None) -> bool:
    return any(item["schedule_id"] == schedule_id for item in jobs.due_schedules(now))


def test_missed_slots_after_downtime_collapse_into_one_occurrence(tmp_path):
    jobs = _jobs(tmp_path)
    schedule_id = jobs.create_schedule(
        name="i",
        loop_id="*",
        cadence="interval",
        timezone=ZONE,
        lookback_minutes=60,
        profile_id=None,
        method_config={},
        selector={"mode": "all"},
        interval_minutes=10,
    )
    now = datetime.now(ZoneInfo(ZONE)).replace(microsecond=0)
    _set_next(jobs, schedule_id, now - timedelta(days=1, minutes=3))
    occurrences = 0
    while _is_due(jobs, schedule_id):
        jobs.materialize_occurrence(schedule_id, ["L1", "L2"])
        occurrences += 1
        assert occurrences < 3
    assert occurrences == 1
    following = datetime.fromisoformat(jobs.get_schedule(schedule_id)["next_run_at"])
    assert now < following <= now + timedelta(minutes=10)
    # Still on the original grid: 3 minutes off the 10-minute slots.
    assert (following - (now - timedelta(days=1, minutes=3))) % timedelta(minutes=10) == timedelta(
        0
    )


def test_a_resumed_schedule_runs_from_now_without_catching_up(tmp_path):
    jobs = _jobs(tmp_path)
    schedule_id = jobs.create_schedule(
        name="d",
        loop_id="L1",
        cadence="daily",
        timezone=ZONE,
        time_local="08:00",
        lookback_minutes=60,
        profile_id=None,
        method_config={},
    )
    jobs.set_schedule_enabled(schedule_id, False)
    _set_next(jobs, schedule_id, datetime.now(ZoneInfo(ZONE)) - timedelta(days=30))
    jobs.set_schedule_enabled(schedule_id, True)
    assert not _is_due(jobs, schedule_id)


def test_a_once_schedule_runs_once_even_if_re_enabled(tmp_path):
    jobs = _jobs(tmp_path)
    moment = (datetime.now(UTC) - timedelta(minutes=1)).isoformat(timespec="seconds")
    schedule_id = jobs.create_schedule(
        name="o",
        loop_id="L1",
        cadence="once",
        timezone=ZONE,
        lookback_minutes=60,
        profile_id=None,
        method_config={},
        scheduled_for=moment,
    )
    assert len(jobs.materialize_occurrence(schedule_id)) == 1
    jobs.set_schedule_enabled(schedule_id, True)
    assert not _is_due(jobs, schedule_id)
    assert jobs.materialize_occurrence(schedule_id) == []


def test_a_slot_whose_jobs_already_exist_still_advances(tmp_path):
    jobs = _jobs(tmp_path)
    moment = (datetime.now(UTC) - timedelta(minutes=1)).isoformat(timespec="seconds")
    schedule_id = jobs.create_schedule(
        name="o",
        loop_id="L1",
        cadence="once",
        timezone=ZONE,
        lookback_minutes=60,
        profile_id=None,
        method_config={},
        scheduled_for=moment,
    )
    slot = jobs.get_schedule(schedule_id)["next_run_at"]
    jobs.materialize_occurrence(schedule_id)
    # Force the schedule back onto the slot it already ran (an older bug left it there).
    with jobs._connect() as connection:
        connection.execute(
            "UPDATE analysis_schedules SET enabled = 1, next_run_at = ? WHERE schedule_id = ?",
            (slot, schedule_id),
        )
    assert jobs.materialize_occurrence(schedule_id) == []
    assert not _is_due(jobs, schedule_id)


def test_daily_slots_keep_their_local_time_across_daylight_saving(tmp_path):
    jobs = _jobs(tmp_path)
    zone = ZoneInfo("America/New_York")
    schedule_id = jobs.create_schedule(
        name="d",
        loop_id="L1",
        cadence="daily",
        timezone="America/New_York",
        time_local="08:00",
        lookback_minutes=60,
        profile_id=None,
        method_config={},
    )
    first = datetime(2026, 10, 30, 8, 0, tzinfo=zone)
    _set_next(jobs, schedule_id, first)
    local_times = []
    for day in range(4):
        slot = datetime.fromisoformat(jobs.get_schedule(schedule_id)["next_run_at"]).astimezone(
            zone
        )
        local_times.append(slot.strftime("%m-%d %H:%M"))
        jobs.materialize_occurrence(schedule_id, now=first + timedelta(days=day, minutes=1))
    assert local_times == ["10-30 08:00", "10-31 08:00", "11-01 08:00", "11-02 08:00"]


def test_hourly_slots_step_one_real_hour_across_daylight_saving(tmp_path):
    jobs = _jobs(tmp_path)
    schedule_id = jobs.create_schedule(
        name="h",
        loop_id="L1",
        cadence="hourly",
        timezone="America/New_York",
        time_local="00:30",
        lookback_minutes=60,
        profile_id=None,
        method_config={},
    )
    first = datetime(2026, 11, 1, 0, 30, tzinfo=ZoneInfo("America/New_York"))
    _set_next(jobs, schedule_id, first)
    slots = []
    for hour in range(3):
        slots.append(datetime.fromisoformat(jobs.get_schedule(schedule_id)["next_run_at"]))
        jobs.materialize_occurrence(schedule_id, now=first + timedelta(hours=hour, minutes=1))
    assert [b - a for a, b in zip(slots, slots[1:])] == [timedelta(hours=1)] * 2
