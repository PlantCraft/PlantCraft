"""What Link tells the Alarms app (owner decision D6, 2026-10-24; only changes since Alarms
round 11): a subject's state when it changes, a failed run once per run of its schedule and a
schedule that stopped once per schedule, each with its schedule and owner. What each run
computed is series, not events."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from linkcraft.api.events import (
    RUN_FAILED,
    SCHEDULE_STALLED,
    STATUS_CHANGED,
    owner_ref,
)
from tests.test_algorithms import _save, api, rt, suite_fake  # noqa: F401


def _mine(fake, kind):
    return [event for event in fake.links.events if event["kind"] == kind]


def _schedule(api):  # noqa: F811
    _save(api)
    return api.post(
        "/link/api/schedules",
        json={
            "name": "PV and valve",
            "profile_id": "pv_and_valve",
            "selector": {"mode": "list", "ids": ["tic-104", "fic-101"]},
            "cadence": "interval",
            "interval_minutes": 30,
            "lookback_minutes": 360,
        },
    ).json()


def _run(rt, schedule):  # noqa: F811
    jobs = rt.jobs.run_schedule_now(schedule["schedule_id"], ["tic-104", "fic-101"])
    for job_id in jobs:
        rt.monitor.execute_job(job_id)
        rt.events.after(job_id)
    return jobs


def test_a_state_is_said_only_when_it_changes_and_never_each_run(
    api,  # noqa: F811
    rt,  # noqa: F811
    suite_fake,  # noqa: F811
):
    schedule = _schedule(api)
    jobs = _run(rt, schedule)
    changed = _mine(suite_fake, STATUS_CHANGED)
    assert [event["subject"] for event in changed] == ["asset:tic-104"]  # an ok start says nothing
    first = changed[0]["payload"]
    assert (
        first["schedule_id"] == schedule["schedule_id"] and first["schedule_name"] == "PV and valve"
    )
    assert first["algorithm_id"] == "pv_and_valve" and first["algorithm_version"] == 1
    assert first["severity"] == "critical" and first["owner"].startswith("user:")
    assert first["url"].endswith(f"/executions/{schedule['schedule_id']}/tic-104")
    assert any(ref in changed[0]["refs"] for ref in (f"run:linkcraft/{job}" for job in jobs))
    assert first["status"] == "alarm" and first.get("previous_status") is None
    before = len(suite_fake.links.events)
    _run(rt, schedule)
    assert len(_mine(suite_fake, STATUS_CHANGED)) == 1  # the state did not change
    assert len(suite_fake.links.events) == before  # nothing else is repeated at each run
    assert not [e for e in suite_fake.links.events if e["kind"] == "linkcraft.output.status"]


def test_a_failed_run_is_said_once_however_many_subjects_failed(api, rt, suite_fake):  # noqa: F811
    schedule = _schedule(api)
    jobs = rt.jobs.run_schedule_now(schedule["schedule_id"], ["fic-101", "tic-104"])
    for job_id in jobs:
        rt.jobs.fail_job(job_id, "The plant data did not answer.")
    assert [rt.events.after(job_id) for job_id in jobs] == [1, 0]
    (event,) = _mine(suite_fake, RUN_FAILED)
    assert event["subject"] in {"asset:fic-101", "asset:tic-104"}
    assert event["payload"]["schedule_id"] == schedule["schedule_id"]
    assert event["payload"]["run_at"]
    assert "did not answer" in event["summary"]


def test_a_schedule_that_stopped_is_one_condition_said_once_until_it_runs(
    api,  # noqa: F811
    rt,  # noqa: F811
    suite_fake,  # noqa: F811
):
    schedule = _schedule(api)
    later = datetime.now(UTC) + timedelta(hours=2)  # four of its 30-minute periods
    assert rt.events.check_stalled(later) >= 1
    events = [
        event
        for event in _mine(suite_fake, SCHEDULE_STALLED)
        if event["payload"]["schedule_id"] == schedule["schedule_id"]
    ]
    assert len(events) == 1 and events[0]["subject"] == "app:linkcraft"
    assert events[0]["key"] == f"stalled:{schedule['schedule_id']}"
    assert events[0]["phase"] == "start" and events[0]["payload"]["subjects"] == 2
    assert rt.events.check_stalled(later) == 0  # said once
    assert rt.events.check_stalled(datetime.now(UTC)) == 0  # on time again: forgotten
    assert schedule["schedule_id"] not in rt.events.store.stalled()
    ended = _mine(suite_fake, SCHEDULE_STALLED)[-1]
    assert ended["phase"] == "end" and ended["key"] == events[0]["key"]


def test_owners_are_addressed_as_the_alarms_app_reads_them():
    assert owner_ref("engineer") == "user:engineer"
    assert owner_ref("group:operations") == "group:operations"
    assert owner_ref("") == ""


def test_the_monitoring_round_says_each_loop_whose_health_changed(rt, suite_fake):  # noqa: F811
    from linkcraft.api.subjects import ROUND_ID

    job_id = rt.queue_round(ROUND_ID)
    rt.engine.execute(rt.jobs.get_job(job_id))  # the round, then its events
    loops = {row["loop_id"]: row for row in rt.monitor.overview_rows()}
    changed = _mine(suite_fake, STATUS_CHANGED)
    assert changed and all(event["payload"]["schedule_id"] == ROUND_ID for event in changed)
    for event in changed:
        loop_id = event["subject"].removeprefix("asset:")
        assert loops[loop_id]["status"] in {"medium", "high", "critical"}
        assert event["payload"]["algorithm_id"] == rt.loops.get_loop(loop_id).profile_id


def test_a_run_by_hand_is_the_schedules_last_run_but_not_its_calendars(api, rt):  # noqa: F811
    schedule = _schedule(api)
    assert api.get(f"/link/api/schedules/{schedule['schedule_id']}").json()["last_run_at"] is None
    rt.jobs.run_schedule_now(schedule["schedule_id"], ["fic-101"])
    listed = next(
        item
        for item in api.get("/link/api/schedules").json()
        if item["schedule_id"] == schedule["schedule_id"]
    )
    assert listed["last_run_at"] and listed["last_run_by_hand"] is True
    stored = rt.jobs.get_schedule(schedule["schedule_id"])
    assert stored["last_run_at"] is None  # the stall warning still counts from the calendar
