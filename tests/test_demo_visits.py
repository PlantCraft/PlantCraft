"""Visits of a public demo: a few places, a line to wait in, visits that end unused, idle visitors
give way."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from plantcraft.api.app import create_app
from plantcraft.auth.demo_visits import LINE_GONE_SECONDS, DemoVisits, Visit, Waiting
from plantcraft.db import Database

ROOT = Path(__file__).resolve().parents[1]
EDGE = {"X-PlantCraft-Edge": "1"}


def _enter(store: DemoVisits, address: str, ticket: str | None = None, now: float = 0.0):
    return store.enter(seats=2, minutes=15, idle_minutes=3, address=address, ticket=ticket, now=now)


@pytest.fixture()
def store(tmp_path):
    return DemoVisits(Database(tmp_path / "visits.sqlite3"))


def test_places_then_a_line_in_order(store):
    first, second = _enter(store, "a"), _enter(store, "b")
    assert isinstance(first, Visit) and isinstance(second, Visit)
    third = _enter(store, "c", now=10)
    fourth = _enter(store, "d", now=11)
    assert isinstance(third, Waiting) and third.position == 1
    assert isinstance(fourth, Waiting) and fourth.position == 2
    # About when a place frees: unused, the first visits end at 3 minutes.
    assert 160 <= third.wait_seconds <= 180
    store.leave(first.visit)
    # The second in line does not jump the first.
    assert isinstance(_enter(store, "d", fourth.ticket, now=20), Waiting)
    entered = _enter(store, "c", third.ticket, now=21)
    assert isinstance(entered, Visit)
    assert store.get(entered.visit, now=62) is not None


def test_a_visit_has_a_clock_and_ends_sooner_when_unused(store):
    visit = _enter(store, "a")
    # Unused, it ends 3 minutes after it started.
    assert visit.seconds_left(now=120) == 60
    assert visit.clock_left(15, now=120) == 780
    # Used at 150: it ends 3 minutes later.
    seen = store.seen(visit.visit, active=True, minutes=15, idle_minutes=3, now=150)
    assert seen.seconds_left(now=150) == 180
    # A sign of life without use does not move the end.
    seen = store.seen(visit.visit, active=False, minutes=15, idle_minutes=3, now=300)
    assert seen.seconds_left(now=300) == 30
    assert store.get(visit.visit, now=330) is None


def test_use_never_moves_a_visit_past_its_clock(store):
    visit = _enter(store, "a")
    for now in range(60, 900, 60):
        store.seen(visit.visit, active=True, minutes=15, idle_minutes=3, now=now)
    # Used all along, it still ends 15 minutes after it started.
    assert store.get(visit.visit, now=899) is not None
    assert store.get(visit.visit, now=900) is None


def test_an_idle_visitor_leaves_even_alone(store):
    idle, busy = _enter(store, "a"), _enter(store, "b")
    store.seen(busy.visit, active=True, minutes=15, idle_minutes=3, now=150)
    assert store.get(idle.visit, now=179) is not None
    # Unused three minutes: the visit ends, with nobody waiting.
    assert store.get(idle.visit, now=181) is None
    assert store.get(busy.visit, now=181) is not None


def test_a_browser_that_stopped_asking_leaves_the_line(store):
    _enter(store, "a"), _enter(store, "b")
    gone = _enter(store, "c", now=10)
    late = _enter(store, "d", now=11)
    assert late.position == 2
    again = _enter(store, "d", late.ticket, now=11 + LINE_GONE_SECONDS)
    assert again.position == 1 and again.ticket == late.ticket
    assert gone.ticket != late.ticket


def test_one_address_is_not_capped(store):
    # Behind the demo's proxy and tunnel every visitor can seem to come from one address.
    assert all(isinstance(_enter(store, "proxy", now=index), Visit) for index in range(2))
    assert isinstance(_enter(store, "proxy", now=3), Waiting)
    assert store.counts(now=3) == {"taken": 2, "waiting": 1}


@pytest.fixture()
def demo_app(tmp_path, monkeypatch):
    scenario = json.loads((ROOT / "scenarios" / "generic_demo.json").read_text())
    scenario["storage"]["sqlite_path"] = str(tmp_path / "workspace.sqlite3")
    scenario["source"]["path"] = str(ROOT / scenario["source"]["path"])
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario))
    secret = tmp_path / "secret"
    secret.write_text("admin-secret")
    for key, value in {
        "PLANTCRAFT_SCENARIO": str(path),
        "PLANTCRAFT_PREWARM_HISTORY": "false",
        "PLANTCRAFT_BASIC_AUTH_ENABLED": "true",
        "PLANTCRAFT_BASIC_AUTH_USERNAME": "admin",
        "PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE": str(secret),
        "PLANTCRAFT_PUBLIC_DEMO": "true",
        "PLANTCRAFT_PUBLIC_DEMO_PASSWORD": "plantcraft-demo",
        "PLANTCRAFT_PUBLIC_DEMO_SEATS": "1",
        "PLANTCRAFT_PUBLIC_DEMO_STATS_KEY": "stats-key",
    }.items():
        monkeypatch.setenv(key, value)
    app = create_app()
    with TestClient(app) as admin:
        assert admin.post(
            "/api/login", json={"username": "admin", "password": "admin-secret"}
        ).is_success
        created = admin.post(
            "/api/users",
            json={
                "username": "demo",
                "display_name": "Demo visitor",
                "role": "Visitor",
                "password": "plantcraft-demo",
                "access_level": "viewer",
            },
        )
        assert created.status_code == 201, created.text
        yield app


def test_enter_the_demo_then_wait_in_line(demo_app):
    visitor = TestClient(demo_app, headers=EDGE)
    entered = visitor.post("/api/demo/enter", json={}).json()
    assert entered["entered"] is True and entered["username"] == "demo"
    assert 0 < entered["demo_visit"]["seconds_left"] <= 5 * 60
    assert 29 * 60 < entered["demo_visit"]["clock_seconds"] <= 30 * 60
    assert entered["public_demo"] == {"seats": 1, "minutes": 30, "updating": False}
    # The apps' token: short, with the demo claim the SDK reads.
    token = visitor.post("/api/v1/auth/token").json()
    claims = demo_app.state.runtime.tokens.verify(token["token"])
    assert claims["demo"]["visit"] and claims["demo"]["queries"] == 4
    assert claims["exp"] - claims["iat"] <= 120
    # Still read-only.
    assert visitor.post("/api/actions", json={"title": "x"}).status_code == 403
    assert visitor.post("/api/demo/heartbeat", json={"active": True}).status_code == 200

    other = TestClient(demo_app, headers=EDGE)
    waiting = other.post("/api/demo/enter", json={}).json()
    assert waiting["entered"] is False and waiting["position"] == 1 and waiting["ticket"]
    assert other.get("/api/session").json()["authenticated"] is False

    # Leaving gives the place to the next one.
    assert visitor.post("/api/logout").status_code == 200
    assert visitor.post("/api/demo/heartbeat", json={"active": True}).status_code == 401
    entered = other.post("/api/demo/enter", json={"ticket": waiting["ticket"]}).json()
    assert entered["entered"] is True


def test_the_visitor_account_never_signs_in_with_its_password_from_outside(demo_app):
    outside = TestClient(demo_app, headers=EDGE)
    answer = outside.post("/api/login", json={"username": "demo", "password": "plantcraft-demo"})
    assert answer.status_code == 403
    # Inside the network (the demo seed) the password still works.
    inside = TestClient(demo_app)
    assert inside.post(
        "/api/login", json={"username": "demo", "password": "plantcraft-demo"}
    ).is_success
    # A session from inside is not a visit from outside.
    cookies = dict(inside.cookies)
    replay = TestClient(demo_app, headers=EDGE, cookies=cookies)
    assert replay.get("/api/session").json()["authenticated"] is False


def test_a_visit_that_ended_signs_the_browser_out(demo_app):
    visitor = TestClient(demo_app, headers=EDGE)
    assert visitor.post("/api/demo/enter", json={}).json()["entered"] is True
    store = demo_app.state.runtime.workspace.demo_visits
    with store._write() as connection:
        connection.execute("UPDATE demo_visits SET ends = 0")
    assert visitor.get("/api/session").json()["authenticated"] is False
    assert visitor.post("/api/v1/auth/token").status_code == 401


def test_no_demo_routes_outside_a_public_demo(tmp_path, monkeypatch):
    scenario = json.loads((ROOT / "scenarios" / "generic_demo.json").read_text())
    scenario["storage"]["sqlite_path"] = str(tmp_path / "workspace.sqlite3")
    scenario["source"]["path"] = str(ROOT / scenario["source"]["path"])
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario))
    monkeypatch.setenv("PLANTCRAFT_SCENARIO", str(path))
    monkeypatch.setenv("PLANTCRAFT_PREWARM_HISTORY", "false")
    monkeypatch.delenv("PLANTCRAFT_PUBLIC_DEMO", raising=False)
    with TestClient(create_app()) as client:
        assert client.post("/api/demo/enter", json={}).status_code == 404


def test_the_guides_links_are_replaced_whole_and_stay_on_this_site(store):
    store.set_guide_links({"Plant overview": "/dash/dashboards/7", "Old": "/x"})
    store.set_guide_links(
        {"Plant overview": "/dash/dashboards/8", "Elsewhere": "https://evil", "Twice": "//evil"}
    )
    assert store.guide_links() == {"Plant overview": "/dash/dashboards/8"}


def test_the_guide_a_visitor_picked_is_in_the_audit_log_and_the_links_are_read(demo_app):
    visitor = TestClient(demo_app, headers=EDGE)
    assert visitor.get("/api/demo/guides").status_code == 401
    assert visitor.post("/api/demo/enter", json={"guide": "Not a guide"}).status_code == 422
    entered = visitor.post("/api/demo/enter", json={"guide": "operator"}).json()
    assert entered["entered"] is True
    workspace = demo_app.state.runtime.workspace
    rows = workspace.audit.list(limit=20)
    signed = [row for row in rows if row["action"] == "session.sign_in"]
    assert signed and signed[0]["detail"]["guide"] == "operator"
    assert visitor.get("/api/demo/guides").json() == {"links": {}}
    workspace.demo_visits.set_guide_links({"DOC-MH-001": "/doc/documents/3"})
    assert visitor.get("/api/demo/guides").json() == {"links": {"DOC-MH-001": "/doc/documents/3"}}


def test_an_ipv6_visitor_counts_by_its_block_not_its_device():
    # One home gets a /64 and every device there its own address: they share their places.
    from plantcraft.api.routers.demo import place_of

    assert place_of("2804:14c:1:2::a") == place_of("2804:14c:1:2:ffff::b") == "2804:14c:1:2::/64"
    assert place_of("2804:14c:1:3::a") != place_of("2804:14c:1:2::a")
    assert place_of("::ffff:203.0.113.7") == "203.0.113.7" == place_of("203.0.113.7")
    assert place_of("testclient") == "testclient"


def test_each_visit_is_logged_without_its_address(store):
    first = _enter(store, "198.51.100.4", now=0)
    _enter(store, "b", now=0)
    waiting = _enter(store, "c", now=10)
    store.seen(first.visit, active=True, minutes=15, idle_minutes=3, now=20)
    # A sign of life without use does not lengthen the visit in the log.
    store.seen(first.visit, active=False, minutes=15, idle_minutes=3, now=25)
    store.leave(first.visit)
    second = _enter(store, "c", waiting.ticket, now=30)
    assert isinstance(second, Visit)
    store.opened(second.visit, ["/link/loops/FIC-1003", "/link/runs/8f3a9b2c11", "x", "/"], now=40)
    store.opened(second.visit, ["/", "/view/"], now=70)
    store.opened("not-a-visit", ["/view/"])
    history = store.history(0, now=500)
    assert history[0] == {"started": 0, "seconds": 20, "waited": 0}
    assert history[-1] == {"started": 30, "seconds": 0, "waited": 20}
    assert {p["page"] for p in store.pages(0)} == {
        "/link/loops/FIC-1003",
        "/link/runs/:id",
        "/",
        "/view",
    }
    journey = store.journeys(0, now=500)[0]
    assert journey["pages"] == [
        ["/link/loops/FIC-1003", 10],
        ["/link/runs/:id", 10],
        ["/", 10],
        ["/view", 40],
    ]
    assert second.visit not in json.dumps(store.journeys(0, now=500))
    with store._connect() as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(demo_visit_log)")]
    assert "address" not in columns


def test_the_demo_stats_need_their_key(demo_app):
    visitor = TestClient(demo_app, headers=EDGE)
    assert visitor.post("/api/demo/enter", json={}).json()["entered"] is True
    beat = visitor.post("/api/demo/heartbeat", json={"active": True, "pages": ["/link/"]})
    assert beat.status_code == 200
    outside = TestClient(demo_app, headers=EDGE)
    assert outside.get("/api/demo/stats").status_code == 404
    wrong = {"Authorization": "Bearer nope"}
    assert outside.get("/api/demo/stats", headers=wrong).status_code == 404
    stats = outside.get("/api/demo/stats", headers={"Authorization": "Bearer stats-key"})
    assert stats.status_code == 200, stats.text
    body = stats.json()
    assert body["now"] == {"taken": 1, "waiting": 0, "seats": 1, "updating": False}
    assert len(body["visits"]) == 1 and body["pages"] == [{"page": "/link", "visits": 1}]
    assert body["journeys"][0]["pages"][0][0] == "/link"
    assert "address" not in json.dumps(body)


def test_an_update_notice_is_forgotten_once_long_past(store):
    assert store.update_at(now=0) is None
    store.announce_update(120)
    assert store.update_at(now=0) == 120
    # Due long ago and never cleared (an update that failed half way): forgotten.
    assert store.update_at(now=120 + 31 * 60) is None
    store.announce_update(500)
    store.clear_update()
    assert store.update_at(now=0) is None


def test_an_announced_update_warns_visits_then_ends_them(demo_app):
    visits = demo_app.state.runtime.workspace.demo_visits
    visitor = TestClient(demo_app, headers=EDGE)
    assert visitor.post("/api/demo/enter", json={}).json()["entered"] is True
    assert visitor.post("/api/demo/heartbeat", json={}).json()["update_seconds"] is None
    visits.announce_update(time.time() + 120)
    beat = visitor.post("/api/demo/heartbeat", json={"active": True}).json()
    assert 100 < beat["update_seconds"] <= 120
    # No new visit starts meanwhile, and the sign-in page says why.
    other = TestClient(demo_app, headers=EDGE)
    refused = other.post("/api/demo/enter", json={})
    assert refused.status_code == 503 and "updated" in refused.json()["detail"]
    assert other.get("/api/session").json()["public_demo"]["updating"] is True
    stats = other.get("/api/demo/stats", headers={"Authorization": "Bearer stats-key"})
    assert stats.json()["now"]["updating"] is True
    # The update is here: the visit ends.
    visits.announce_update(time.time() - 1)
    ended = visitor.post("/api/demo/heartbeat", json={})
    assert ended.status_code == 401 and "updated" in ended.json()["detail"]
    assert visits.counts()["taken"] == 0
    # Cleared after the update: visits start again.
    visits.clear_update()
    assert other.post("/api/demo/enter", json={}).json()["entered"] is True
