"""Operations › Requests and Partners: a request anyone may open, its first answer and the hours
logged on it, companies with an end to their access, and the month's hours by company."""
# ruff: noqa: F811 (the fixture "world" of tests/test_apps_api.py, imported to share it)

from __future__ import annotations

from datetime import date, timedelta

from plantcraft.config import plant_today
from tests.test_apps_api import audit, sign_in, world  # noqa: F401

PASSWORD = "password-123"


def _company(admin, **changes):
    payload = {
        "name": "Acme Automation",
        "group_id": "acme",
        "kind": "company",
        "coordinator": "eng",
        "members": ["eng"],
        "sponsor": None,
        "access_until": None,
        **changes,
    }
    answer = admin.post("/api/groups", json=payload)
    assert answer.status_code == 201, answer.text
    return answer.json()


def test_a_viewer_asks_for_help_and_the_first_answer_is_timed(world):
    admin = sign_in(world.client())
    op = sign_in(world.client(), "op", PASSWORD)
    answer = op.post(
        "/api/requests",
        json={
            "title": "Trend of FIC-101 does not load",
            "category": "error",
            "description": "Since 9 h",
        },
    )
    assert answer.status_code == 201, answer.text
    request = answer.json()
    assert request["kind"] == "request" and request["category"] == "error"
    assert request["category_label"] == "Something is not working"
    assert request["first_response_at"] is None
    # Who answers is told: with no queue, the administrators, in Messages from "Operations".
    told = admin.get("/api/notifications").json()
    assert any("Trend of FIC-101 does not load" in str(item) for item in told.get("items", told))
    # Who asked commenting is not an answer; someone else's comment is.
    op.post(f"/api/actions/{request['action_id']}/comments", json={"text": "Still failing"})
    assert admin.get(f"/api/actions/{request['action_id']}").json()["first_response_at"] is None
    admin.post(f"/api/actions/{request['action_id']}/comments", json={"text": "Looking at it"})
    assert admin.get(f"/api/actions/{request['action_id']}").json()["first_response_at"]
    # Only requests in the list asked for them; an action never gets a category.
    admin.post("/api/actions", json={"title": "Calibrate FT-7"})
    listed = admin.get("/api/actions", params={"kind": "request"}).json()
    assert [item["title"] for item in listed["items"]] == ["Trend of FIC-101 does not load"]
    assert {item["id"] for item in listed["categories"]} >= {"error", "slow", "access"}
    plain = admin.get("/api/actions", params={"kind": "action"}).json()["items"]
    assert [item["category"] for item in plain] == [None]
    bad = op.post("/api/requests", json={"title": "x", "category": "coffee"})
    assert bad.status_code == 422


def test_hours_are_logged_by_whoever_sees_it_and_removed_by_their_author(world):
    admin = sign_in(world.client())
    op = sign_in(world.client(), "op", PASSWORD)
    action_id = op.post("/api/requests", json={"title": "Reset my password"}).json()["action_id"]
    logged = op.post(f"/api/actions/{action_id}/hours", json={"hours": 1.5, "note": "call"})
    assert logged.status_code == 201, logged.text
    body = logged.json()
    assert body["hours_logged"] == 1.5 and body["hours"][0]["note"] == "call"
    assert any(entry["kind"] == "hours" for entry in body["history"])
    tomorrow = (date.fromisoformat(plant_today()) + timedelta(days=1)).isoformat()
    assert (
        op.post(f"/api/actions/{action_id}/hours", json={"hours": 1, "day": tomorrow}).status_code
        == 422
    )
    assert op.post(f"/api/actions/{action_id}/hours", json={"hours": 30}).status_code == 422
    entry = admin.post(f"/api/actions/{action_id}/hours", json={"hours": 2}).json()["hours"][0]
    # The viewer cannot remove the admin's entry; the admin can remove anyone's.
    assert op.delete(f"/api/actions/{action_id}/hours/{entry['entry_id']}").status_code == 403
    own = body["hours"][0]["entry_id"]
    assert admin.delete(f"/api/actions/{action_id}/hours/{own}").status_code == 200
    assert admin.get(f"/api/actions/{action_id}").json()["hours_logged"] == 2.0
    assert audit(admin, "action.hours.deleted")


def test_a_company_lists_its_people_requests_and_hours(world):
    admin = sign_in(world.client())
    until = (date.fromisoformat(plant_today()) + timedelta(days=10)).isoformat()
    company = _company(admin, sponsor="op", access_until=until)
    assert company["kind"] == "company" and company["sponsor"] == "op"
    team = admin.post(
        "/api/groups",
        json={"name": "Acme field team", "kind": "team", "parent_id": "acme", "members": ["eng"]},
    )
    assert team.status_code == 201, team.text
    eng = sign_in(world.client(), "eng", PASSWORD)
    request_id = eng.post(
        "/api/requests", json={"title": "Commission OPC UA source", "group_id": "acme"}
    ).json()["action_id"]
    eng.post(f"/api/actions/{request_id}/hours", json={"hours": 3, "billable": True})
    eng.post(f"/api/actions/{request_id}/hours", json={"hours": 1, "billable": False})
    partners = admin.get("/api/operations/partners").json()
    [acme] = partners["companies"]
    assert acme["state"] == "ending"  # ends in 10 days
    assert acme["sponsor_name"] and acme["open_requests"] == 1
    assert acme["hours"] == 4.0 and acme["billable_hours"] == 3.0
    assert [team["name"] for team in acme["teams"]] == ["Acme field team"]
    assert acme["people"][0]["username"] == "eng" and acme["people"][0]["coordinator"]
    report = admin.get("/api/operations/hours", params={"company": "acme"}).json()
    assert report["hours"] == 4.0 and {e["company_name"] for e in report["entries"]} == {
        "Acme Automation"
    }
    assert admin.get("/api/operations/hours", params={"company": "plant"}).json()["entries"] == []
    assert admin.get("/api/operations/hours", params={"month": "2026-13"}).status_code == 422
    assert audit(admin, "operations.hours.read")
    # The sponsor is someone of the plant: a member of the company cannot be it.
    bad = admin.put(
        "/api/groups/acme",
        json={"name": "Acme Automation", "kind": "company", "members": ["eng"], "sponsor": "eng"},
    )
    assert bad.status_code == 422


def test_nobody_of_a_company_signs_in_after_its_access_ends(world):
    admin = sign_in(world.client())
    eng = sign_in(world.client(), "eng", PASSWORD)
    assert eng.get("/api/session").status_code == 200
    yesterday = (date.fromisoformat(plant_today()) - timedelta(days=1)).isoformat()
    _company(admin, members=[], coordinator=None)
    admin.post(
        "/api/groups",
        json={"name": "Acme field team", "kind": "team", "parent_id": "acme", "members": ["eng"]},
    )
    admin.put(
        "/api/groups/acme",
        json={"name": "Acme Automation", "kind": "company", "access_until": yesterday},
    )
    # The open session ends, and signing in again is refused with the reason.
    assert eng.get("/api/actions").status_code == 401
    refused = world.client().post("/api/login", json={"username": "eng", "password": PASSWORD})
    assert refused.status_code == 403 and yesterday in refused.json()["detail"]
    # Extended by the admin: in again.
    admin.put(
        "/api/groups/acme",
        json={"name": "Acme Automation", "kind": "company", "access_until": None},
    )
    assert sign_in(world.client(), "eng", PASSWORD).get("/api/actions").status_code == 200


def test_another_kind_of_group_keeps_no_company_fields(world):
    admin = sign_in(world.client())
    team = admin.post(
        "/api/groups",
        json={"name": "Shift A", "kind": "team", "access_until": "2020-01-01", "sponsor": "op"},
    ).json()
    assert team["access_until"] is None and team["sponsor"] is None
