"""Public demo mode (PLANTCRAFT_PUBLIC_DEMO): visitors read, only an administrator writes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from plantcraft.api.app import create_app
from plantcraft.auth.public_demo import RateLimiter, public_demo
from plantcraft.specialists.profiles import models_allowed, models_allowed_for

ROOT = Path(__file__).resolve().parents[1]
VISITOR_PASSWORD = "plantcraft-demo"


@pytest.fixture()
def suite(tmp_path, monkeypatch):
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
        "PLANTCRAFT_PUBLIC_DEMO_PASSWORD": VISITOR_PASSWORD,
    }.items():
        monkeypatch.setenv(key, value)
    app = create_app()
    with TestClient(app) as admin:
        assert admin.post(
            "/api/login", json={"username": "admin", "password": "admin-secret"}
        ).is_success
        for username, level in (("demo", "viewer"), ("ana", "editor")):
            created = admin.post(
                "/api/users",
                json={
                    "username": username,
                    "display_name": username.title(),
                    "role": "Demo",
                    "password": VISITOR_PASSWORD,
                    "access_level": level,
                },
            )
            assert created.status_code == 201, created.text
        yield app, admin


def _signed(app, username):
    client = TestClient(app)
    answer = client.post("/api/login", json={"username": username, "password": VISITOR_PASSWORD})
    assert answer.status_code == 200, answer.text
    return client


def test_the_sign_in_page_offers_the_demo_never_its_password(suite):
    app, _admin = suite
    answer = TestClient(app).get("/api/session").json()
    assert answer["authenticated"] is False
    assert answer["public_demo"] == {"seats": 10, "minutes": 30}


def test_visitors_cannot_write_even_in_conversations(suite):
    app, _admin = suite
    for username in ("demo",):
        client = _signed(app, username)
        assert client.get("/api/home").json()["public_demo"] is True
        started = client.post(
            "/api/messages/conversations",
            json={"members": ["admin"], "title": "Hello", "text": "spam"},
        )
        assert started.status_code == 403
        assert "public demo" in started.json()["detail"]
        assert client.post("/api/actions", json={"title": "x"}).status_code == 403
        assert (
            client.post("/api/users/demo/password", json={"password": "x" * 12}).status_code == 403
        )


def test_visitors_mark_what_they_read_and_sign_out(suite):
    app, admin = suite
    started = admin.post(
        "/api/messages/conversations",
        json={"members": ["demo"], "title": "Welcome", "text": "Hello, visitor."},
    ).json()
    visitor = _signed(app, "demo")
    conversation = started["conversation"]["conversation_id"]
    read = visitor.post(f"/api/messages/conversations/{conversation}/read")
    assert read.status_code in (200, 204), read.text
    assert visitor.post("/api/logout").status_code in (200, 204)


def test_editors_and_the_administrator_still_write(suite):
    app, admin = suite
    editor = _signed(app, "ana")
    answer = editor.post(
        "/api/messages/conversations",
        json={"members": ["demo"], "title": "From the cast", "text": "Hello."},
    )
    assert answer.status_code in (200, 201), answer.text
    answer = admin.post(
        "/api/messages/conversations",
        json={"members": ["demo"], "title": "Welcome", "text": "Hello, visitor."},
    )
    assert answer.status_code in (200, 201), answer.text


def test_language_models_are_only_for_the_people_an_administrator_created(suite, monkeypatch):
    """Owner, 2026-10-25: the demo keeps the assistant for real accounts; visitors never reach
    a model, and neither do the apps' uses (a visitor's click could set them off)."""

    app, admin = suite
    monkeypatch.setenv("PLANTCRAFT_LLM", "on")
    assert public_demo() is not None and models_allowed() is True
    assert models_allowed_for("admin") and models_allowed_for("editor")
    assert not models_allowed_for("viewer") and not models_allowed_for(None)
    visitor = _signed(app, "demo").get("/api/assistant").json()
    assert visitor["allowed"] is False and visitor["available"] is False
    assert admin.get("/api/assistant").json()["allowed"] is True
    started = _signed(app, "demo").post("/api/assistant/chats", json={"text": "hi"})
    assert started.status_code == 403
    monkeypatch.setenv("PLANTCRAFT_LLM", "off")
    assert not models_allowed_for("admin")


def test_each_address_gets_a_limited_number_of_requests_per_minute():
    limiter = RateLimiter(3)
    assert [limiter.allow("1.2.3.4", now=0.0) for _ in range(4)] == [True, True, True, False]
    assert limiter.allow("5.6.7.8", now=1.0) is True
    assert limiter.allow("1.2.3.4", now=61.0) is True


def test_the_rate_limit_answers_429(tmp_path, monkeypatch):
    scenario = json.loads((ROOT / "scenarios" / "generic_demo.json").read_text())
    scenario["storage"]["sqlite_path"] = str(tmp_path / "workspace.sqlite3")
    scenario["source"]["path"] = str(ROOT / scenario["source"]["path"])
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario))
    monkeypatch.setenv("PLANTCRAFT_SCENARIO", str(path))
    monkeypatch.setenv("PLANTCRAFT_PREWARM_HISTORY", "false")
    monkeypatch.setenv("PLANTCRAFT_PUBLIC_DEMO", "true")
    monkeypatch.setenv("PLANTCRAFT_PUBLIC_DEMO_RATE", "5")
    with TestClient(create_app()) as client:
        edge = {"X-PlantCraft-Edge": "1"}
        codes = [client.get("/api/session", headers=edge).status_code for _ in range(7)]
        assert codes[:5] == [200] * 5
        assert codes[5:] == [429, 429]
        assert client.get("/healthz", headers=edge).status_code == 200
        # The suite's apps call inside the network, without the proxy's mark: never limited.
        assert client.get("/api/session").status_code == 200


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("PLANTCRAFT_PUBLIC_DEMO", raising=False)
    assert public_demo() is None


def test_visitors_write_no_audit_entries_through_api_v1(suite):
    app, admin = suite
    entry = {"action": "loop.created", "subject": "loop:x", "app": "linkcraft"}
    visitor = _signed(app, "demo")
    token = visitor.post("/api/v1/auth/token").json()["token"]
    refused = visitor.post(
        "/api/v1/audit", json=entry, headers={"Authorization": f"Bearer {token}"}
    )
    assert refused.status_code == 403
    editor = _signed(app, "ana")
    token = editor.post("/api/v1/auth/token").json()["token"]
    recorded = editor.post(
        "/api/v1/audit", json=entry, headers={"Authorization": f"Bearer {token}"}
    )
    assert recorded.status_code == 201, recorded.text


def test_the_visitor_sees_the_teams_actions(suite):
    """The demo shows the team's follow-up: an action of a group the visitor is not in."""

    app, admin = suite
    group = admin.post("/api/groups", json={"name": "Instrumentation"}).json()
    made = admin.post(
        "/api/actions", json={"title": "Inspect the valve", "group_id": group["group_id"]}
    ).json()
    titles = [item["title"] for item in _signed(app, "demo").get("/api/actions").json()["items"]]
    assert "Inspect the valve" in titles
    assert _signed(app, "ana").get(f"/api/actions/{made['action_id']}").status_code == 404


def test_the_visitor_reads_the_administration_and_changes_nothing(suite):
    """Owner, 2026-10-28: a visitor sees People, Apps and Backups to know the platform."""

    app, _admin = suite
    visitor = _signed(app, "demo")
    assert visitor.get("/api/session").json()["access"]["admin_view"] is True
    assert visitor.get("/api/users/accounts").status_code == 200
    assert visitor.get("/api/apps").status_code == 200
    assert visitor.get("/api/operations").status_code == 200
    assert visitor.post("/api/operations/backup").status_code == 403
    assert visitor.get("/api/app-keys").status_code == 403
    editor = _signed(app, "ana")
    assert editor.get("/api/session").json()["access"]["admin_view"] is False
    assert editor.get("/api/users/accounts").status_code == 403
