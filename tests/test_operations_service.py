"""Operations, the second batch: the requests' service targets with the clock stopped while
Blocked, the month's approval that closes the hours, and temporary support access."""
# ruff: noqa: F811 (the fixture "world" of tests/test_apps_api.py, imported to share it)

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from plantcraft.actions.sla import Targets, check_targets, paused_minutes, request_sla
from plantcraft.config import plant_today
from tests.test_apps_api import ADMIN, audit, sign_in, world  # noqa: F401
from tests.test_operations_requests import PASSWORD, _company

T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


def _at(minutes: float) -> str:
    return (T0 + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def _request(**changes):
    return {
        "kind": "request",
        "status": "open",
        "priority": "high",
        "created_at": _at(0),
        "first_response_at": None,
        "completed_at": None,
        **changes,
    }


# The clock ----------------------------------------------------------------------------------


def test_the_first_answer_and_the_resolution_are_measured_against_the_priority():
    targets = Targets.defaults()  # high: 4 h first answer, 24 h resolution
    now = T0 + timedelta(hours=3, minutes=30)
    sla = request_sla(_request(), [], targets, now)
    assert sla["response"]["state"] == "at_risk"  # 210 of 240 minutes
    assert sla["response"]["due_at"] == _at(240)
    late = request_sla(_request(), [], targets, T0 + timedelta(hours=5))
    assert late["response"]["state"] == "breached"
    answered = request_sla(_request(first_response_at=_at(30)), [], targets, now)
    assert answered["response"] == {
        "target_minutes": 240,
        "used_minutes": 30,
        "state": "met",
        "due_at": None,
    }


def test_blocked_stops_the_resolution_clock_and_done_gives_the_verdict():
    targets = Targets.defaults()
    # Open 10 h, Blocked 20 h (waiting for who asked), then 10 h more and Done: 20 h used of 24.
    statuses = [(_at(600), "blocked"), (_at(1800), "in_progress"), (_at(2400), "done")]
    done = _request(status="done", first_response_at=_at(10), completed_at=_at(2400))
    sla = request_sla(done, statuses, targets, T0 + timedelta(days=5))
    assert sla["resolution"]["used_minutes"] == 1200
    assert sla["resolution"]["paused_minutes"] == 1200
    assert sla["resolution"]["state"] == "met"
    # While Blocked the clock stands, and no due time is given.
    waiting = request_sla(
        _request(status="blocked"), statuses[:1], targets, T0 + timedelta(hours=30)
    )
    assert waiting["resolution"]["paused"] is True
    assert waiting["resolution"]["used_minutes"] == 600
    assert waiting["resolution"]["due_at"] is None
    assert paused_minutes(_at(0), statuses[:1], T0 + timedelta(hours=30)) == (1200.0, True)
    # Archived requests and actions have no targets.
    assert request_sla(_request(status="cancelled"), [], targets) is None
    assert request_sla({**_request(), "kind": "action"}, [], targets) is None


def test_targets_are_checked():
    good = {key: {"response_hours": 1, "resolution_hours": 8} for key in Targets.defaults().minutes}
    assert check_targets(good).minutes["low"] == (60, 480)
    with pytest.raises(ValueError):
        check_targets({**good, "high": {"response_hours": 8, "resolution_hours": 2}})
    with pytest.raises(ValueError):
        check_targets({**good, "low": {"response_hours": 0, "resolution_hours": 2}})
    with pytest.raises(ValueError):
        check_targets({"high": good["high"]})


def test_requests_carry_their_targets_and_an_administrator_changes_them(world):
    admin = sign_in(world.client())
    op = sign_in(world.client(), "op", PASSWORD)
    request = op.post("/api/requests", json={"title": "Historian is slow"}).json()
    assert request["sla"]["response"]["target_minutes"] == 8 * 60  # medium
    listed = admin.get("/api/actions", params={"kind": "request"}).json()["items"]
    assert listed[0]["sla"]["resolution"]["state"] == "running"
    shown = op.get("/api/operations/targets").json()
    assert shown["targets"]["medium"] == {"response_hours": 8, "resolution_hours": 72}
    changed = {**shown["targets"], "medium": {"response_hours": 2, "resolution_hours": 12}}
    assert op.put("/api/operations/targets", json={"targets": changed}).status_code == 403
    answer = admin.put("/api/operations/targets", json={"targets": changed})
    assert answer.status_code == 200, answer.text
    again = admin.get(f"/api/actions/{request['action_id']}").json()
    assert again["sla"]["response"]["target_minutes"] == 120
    assert audit(admin, "operations.targets")
    # Blocked: the resolution clock stands.
    blocked = admin.put(
        f"/api/actions/{request['action_id']}",
        json={**{k: again[k] for k in ("title", "description", "priority")}, "status": "blocked"},
    ).json()
    assert blocked["sla"]["resolution"]["paused"] is True


# The month's approval ------------------------------------------------------------------------


def _last_month() -> tuple[str, str]:
    first = date.fromisoformat(plant_today()).replace(day=1)
    day = first - timedelta(days=1)
    return day.strftime("%Y-%m"), day.isoformat()


def test_the_sponsor_approves_a_month_and_its_hours_close(world):
    admin = sign_in(world.client())
    users = admin.app.state.runtime.workspace.users
    users.upsert_user("rui", "Rui Planta", "")
    users.set_access("rui", "viewer", None)
    users.set_password("rui", PASSWORD)
    _company(admin, sponsor="rui")
    eng = sign_in(world.client(), "eng", PASSWORD)
    month, day = _last_month()
    action_id = eng.post("/api/requests", json={"title": "Tune the OPC UA client"}).json()[
        "action_id"
    ]
    entry = eng.post(f"/api/actions/{action_id}/hours", json={"hours": 3, "day": day})
    assert entry.status_code == 201, entry.text
    entry_id = entry.json()["hours"][0]["entry_id"]
    # This month cannot be approved yet; another person cannot approve the company's month.
    this = plant_today()[:7]
    early = admin.post("/api/operations/hours/approve", json={"month": this, "company": "acme"})
    assert early.status_code == 409
    op = sign_in(world.client(), "op", PASSWORD)
    refused = op.post("/api/operations/hours/approve", json={"month": month, "company": "acme"})
    assert refused.status_code == 403
    rui = sign_in(world.client(), "rui", PASSWORD)
    approved = rui.post("/api/operations/hours/approve", json={"month": month, "company": "acme"})
    # (each new client sets the test people's passwords again, which ends eng's session)
    eng = sign_in(world.client(), "eng", PASSWORD)
    assert approved.status_code == 200, approved.text
    assert approved.json()["hours"] == 3 and approved.json()["approved_by"] == "rui"
    assert audit(admin, "operations.hours.approved")
    again = rui.post("/api/operations/hours/approve", json={"month": month, "company": "acme"})
    assert again.status_code == 409
    # Closed: nothing is added or removed in that month; the page marks the entry.
    more = eng.post(f"/api/actions/{action_id}/hours", json={"hours": 1, "day": day})
    assert more.status_code == 409
    gone = eng.delete(f"/api/actions/{action_id}/hours/{entry_id}")
    assert gone.status_code == 409
    assert eng.get(f"/api/actions/{action_id}").json()["hours"][0]["locked"] is True
    partners = admin.get("/api/operations/partners", params={"month": month}).json()
    assert partners["closable"] is True
    assert partners["companies"][0]["approval"]["approved_by_name"] == "Rui Planta"
    # An administrator reopens it; then the entry goes.
    assert (
        rui.post("/api/operations/hours/reopen", json={"month": month, "company": "acme"})
    ).status_code == 403
    reopened = admin.post("/api/operations/hours/reopen", json={"month": month, "company": "acme"})
    assert reopened.status_code == 200
    assert eng.delete(f"/api/actions/{action_id}/hours/{entry_id}").status_code == 200


# Temporary support access --------------------------------------------------------------------


def test_temporary_support_access_opens_operations_until_it_ends(world):
    admin = sign_in(world.client())
    op = sign_in(world.client(), "op", PASSWORD)
    assert op.get("/api/operations/health").status_code == 403
    assert op.get("/api/session").json()["access"]["can_operate"] is False
    refused = op.post(
        "/api/operations/support-access/grants",
        json={"username": "op", "hours": 4, "reason": "Me"},
    )
    assert refused.status_code == 403
    request_id = op.post("/api/requests", json={"title": "Alarms stopped"}).json()["action_id"]
    granted = admin.post(
        "/api/operations/support-access/grants",
        json={"username": "op", "hours": 4, "reason": "Alarms stopped", "action_id": request_id},
    )
    assert granted.status_code == 201, granted.text
    grant = granted.json()
    assert grant["active"] is True
    assert audit(admin, "operations.support_access.granted")
    session = op.get("/api/session").json()["access"]
    assert session["can_operate"] is True and session["support_until"] == grant["ends_at"]
    assert op.get("/api/operations/health").status_code == 200
    # Still not an administrator: backups, load limits and grants stay theirs.
    assert (
        op.post(
            "/api/operations/support-access/grants",
            json={"username": "op", "hours": 4, "reason": "more"},
        ).status_code
        == 403
    )
    listed = admin.get("/api/operations/support-access").json()["grants"]
    assert [item["username"] for item in listed] == ["op"]
    # Too long, an administrator, an unknown person: refused.
    for payload, code in (
        ({"username": "op", "hours": 100, "reason": "x"}, 422),
        ({"username": ADMIN, "hours": 1, "reason": "x"}, 409),
        ({"username": "nobody", "hours": 1, "reason": "x"}, 404),
    ):
        assert admin.post("/api/operations/support-access/grants", json=payload).status_code == code
    ended = admin.delete(f"/api/operations/support-access/grants/{grant['grant_id']}")
    assert ended.status_code == 200 and ended.json()["active"] is False
    assert audit(admin, "operations.support_access.ended")
    assert op.get("/api/operations/health").status_code == 403
    assert (
        admin.delete(f"/api/operations/support-access/grants/{grant['grant_id']}").status_code
        == 409
    )


# Service hours and the sponsor's Partners ---------------------------------------------------


def test_service_hours_stop_the_clock_outside_the_working_day():
    from zoneinfo import ZoneInfo

    from plantcraft.actions.sla import ServiceHours

    zone = ZoneInfo("America/Sao_Paulo")
    week = ServiceHours.check(
        {"days": ["mon", "tue", "wed", "thu", "fri"], "start": "08:00", "end": "17:00"}
    )
    # Asked Friday 16:00 (19:00 UTC); a 2 h first answer target falls on Monday 09:00 (12:00 UTC).
    friday = datetime(2026, 10, 30, 19, 0, tzinfo=UTC)
    monday = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
    assert week.add(friday, 120, zone) == monday
    assert week.minutes(friday, monday, zone) == 120
    targets = Targets({**Targets.defaults().minutes, "high": (120, 9 * 60)})
    asked = _request(created_at="2026-10-30T19:00:00Z")
    saturday = datetime(2026, 10, 31, 15, 0, tzinfo=UTC)
    sla = request_sla(asked, [], targets, saturday, hours=week, zone=zone)
    assert sla["response"]["used_minutes"] == 60  # Friday 16:00-17:00 only
    assert sla["response"]["state"] == "running"
    assert sla["response"]["due_at"] == "2026-11-02T12:00:00Z"
    assert sla["service_hours"]["days"] == ["mon", "tue", "wed", "thu", "fri"]
    for bad in (
        {"days": [], "start": "08:00", "end": "17:00"},
        {"days": ["mon"], "start": "18:00", "end": "17:00"},
        {"days": ["mon"], "start": "8h", "end": "17:00"},
    ):
        with pytest.raises(ValueError):
            ServiceHours.check(bad)


def test_an_administrator_sets_a_queue_s_hours(world):
    admin = sign_in(world.client())
    op = sign_in(world.client(), "op", PASSWORD)
    admin.post("/api/groups", json={"name": "IT", "group_id": "it", "kind": "team"})
    week = {"days": ["mon", "tue", "wed", "thu", "fri"], "start": "08:00", "end": "17:00"}
    assert (
        op.put("/api/operations/service-hours", json={"queue": "it", "hours": week}).status_code
        == 403
    )
    answer = admin.put("/api/operations/service-hours", json={"queue": "it", "hours": week})
    assert answer.status_code == 200, answer.text
    assert answer.json()["service_hours"][0]["queue_name"] == "IT"
    assert audit(admin, "operations.service_hours")
    request = op.post("/api/requests", json={"title": "VPN down", "group_id": "it"}).json()
    assert request["sla"]["service_hours"]["start"] == "08:00"
    other = op.post("/api/requests", json={"title": "Printer"}).json()
    assert other["sla"]["service_hours"] is None
    bad = admin.put(
        "/api/operations/service-hours", json={"queue": "it", "hours": {"days": ["mon"]}}
    )
    assert bad.status_code == 422
    cleared = admin.put("/api/operations/service-hours", json={"queue": "it", "hours": None})
    assert cleared.json()["service_hours"] == []


def test_a_sponsor_reads_and_approves_only_their_companies(world):
    admin = sign_in(world.client())
    users = admin.app.state.runtime.workspace.users
    users.upsert_user("rui", "Rui Planta", "")
    users.set_access("rui", "viewer", None)
    users.set_password("rui", PASSWORD)
    _company(admin, sponsor="rui")
    _company(admin, name="Beta Controls", group_id="beta", coordinator=None, members=[])
    op = sign_in(world.client(), "op", PASSWORD)
    assert op.get("/api/operations/partners").status_code == 403
    rui = sign_in(world.client(), "rui", PASSWORD)
    session = rui.get("/api/session").json()["access"]
    assert session["sponsor_of"] == ["acme"] and session["can_operate"] is False
    shown = rui.get("/api/operations/partners").json()
    assert [item["group_id"] for item in shown["companies"]] == ["acme"]
    assert rui.get("/api/operations/hours").status_code == 200
    # Still not Operations: status and logs stay closed.
    assert rui.get("/api/operations/health").status_code == 403
    month, _day = _last_month()
    refused = rui.post("/api/operations/hours/approve", json={"month": month, "company": "beta"})
    assert refused.status_code == 403
    every = admin.get("/api/operations/partners").json()
    assert {item["group_id"] for item in every["companies"]} == {"acme", "beta"}
