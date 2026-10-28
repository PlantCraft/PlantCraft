"""Who may change the platform, sessions that end with the password, and inputs refused with 422."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from processcraft.api.app import create_app
from processcraft.auth import throttle
from processcraft.auth.users import check_password, needs_rehash

ROOT = Path(__file__).resolve().parents[1]
ADMIN_PASSWORD = "Sup3rSecretAdmin"


@pytest.fixture()
def app(tmp_path, monkeypatch):
    scenario = json.loads((ROOT / "scenarios" / "generic_demo.json").read_text())
    scenario["storage"]["sqlite_path"] = str(tmp_path / "workspace.sqlite3")
    scenario["source"]["path"] = str(ROOT / scenario["source"]["path"])
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario))
    secret = tmp_path / "admin-password"
    secret.write_text(ADMIN_PASSWORD)
    monkeypatch.setenv("PLANTCRAFT_SCENARIO", str(path))
    monkeypatch.setenv("PLANTCRAFT_PREWARM_HISTORY", "false")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_ENABLED", "true")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_USERNAME", "admin")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE", str(secret))
    application = create_app()
    users = application.state.runtime.workspace.users
    users.upsert_user("joao.op", "João", "Operação")
    users.set_password("joao.op", "senha-do-joao")
    return application


def _login(app, username: str, password: str) -> TestClient:
    client = TestClient(app)
    assert (
        client.post("/api/login", json={"username": username, "password": password}).status_code
        == 200
    )
    return client


def test_members_cannot_change_platform_settings(app):
    with TestClient(app):
        member = _login(app, "joao.op", "senha-do-joao")
        assert member.get("/api/session").json()["is_admin"] is False
        source = {"name": "x", "type": "csv", "settings": {"path": "/tmp/x.csv"}}
        assert member.post("/api/data/sources", json=source).status_code == 403
        assert member.post("/api/app-keys", json={"app_id": "cpmcraft"}).status_code == 403
        assert member.get("/api/users/accounts").status_code == 403
        assert (
            member.post("/api/assets", json={"name": "Unit 9", "kind": "unit"}).status_code == 403
        )
        assert (
            member.post("/api/users", json={"username": "eve", "display_name": "Eve"}).status_code
            == 403
        )
        # Reading the plant stays open to everyone signed in.
        assert member.get("/api/assets").status_code == 200
        assert member.get("/api/home").status_code == 200

        admin = _login(app, "admin", ADMIN_PASSWORD)
        assert admin.get("/api/session").json()["is_admin"] is True
        assert admin.get("/api/users/accounts").status_code == 200
        assert admin.post("/api/assets", json={"name": "Unit 9", "kind": "unit"}).status_code == 201


def test_a_new_password_ends_old_sessions(app):
    with TestClient(app):
        member = _login(app, "joao.op", "senha-do-joao")
        assert member.get("/api/home").status_code == 200
        app.state.runtime.workspace.users.set_password("joao.op", "outra-senha-forte")
        assert member.get("/api/home").status_code == 401


def test_the_product_hashes_with_argon2_cffis_default_profile():
    # The tests swap in a cheap hasher (conftest.py); the product keeps RFC 9106's low-memory one.
    from argon2 import PasswordHasher

    from processcraft.auth.users import PRODUCT_HASHER

    default = PasswordHasher()
    assert PRODUCT_HASHER.memory_cost == default.memory_cost >= 65536
    assert PRODUCT_HASHER.time_cost == default.time_cost >= 3
    assert PRODUCT_HASHER.type == default.type


def test_passwords_are_argon2id_and_old_pbkdf2_hashes_move_over_at_sign_in(app):
    users = app.state.runtime.workspace.users
    stored = users._password_hash("joao.op")
    assert stored.startswith("$argon2id$") and "senha-do-joao" not in stored
    assert check_password("senha-do-joao", stored) and not check_password("errada", stored)

    # A hash from before Argon2: same salt and rounds as the old code wrote.
    salt = "00" * 16
    digest = hashlib.pbkdf2_hmac("sha256", b"senha-antiga", salt.encode("ascii"), 240_000)
    old = f"pbkdf2_sha256$240000${salt}${digest.hex()}"
    with users._write() as connection:
        connection.execute(
            "UPDATE workspace_users SET password_hash = ? WHERE username = 'joao.op'", (old,)
        )
    assert needs_rehash(old)
    # A check inside a session never rehashes (it would end that session).
    assert users.verify_password("joao.op", "senha-antiga")
    assert users._password_hash("joao.op") == old
    with TestClient(app):
        _login(app, "joao.op", "senha-antiga")
    moved = users._password_hash("joao.op")
    assert moved.startswith("$argon2id$") and not needs_rehash(moved)
    assert users.verify_password("joao.op", "senha-antiga")
    assert not users.verify_password("joao.op", "senha-errada")


def test_session_key_does_not_come_from_the_password(app, tmp_path):
    secret = (tmp_path / "session.secret").read_text().strip()
    assert len(secret) == 64 and ADMIN_PASSWORD not in secret


def test_repeated_wrong_passwords_are_throttled(app):
    with TestClient(app) as client:
        for _ in range(throttle.LIMIT):
            assert (
                client.post(
                    "/api/login", json={"username": "joao.op", "password": "errada"}
                ).status_code
                == 401
            )
        answer = client.post(
            "/api/login", json={"username": "joao.op", "password": "senha-do-joao"}
        )
        assert answer.status_code == 429


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        ("post", "/api/data/sources", {"name": "s", "type": "modbus", "settings": {}}),
        ("post", "/api/data/sources", {"name": "s", "type": "opcua", "settings": {}}),
        ("post", "/api/assets", {"name": "x", "kind": "spaceship"}),
        ("post", "/api/users", {"username": "x", "display_name": "X", "access_level": "god"}),
        ("post", "/api/users", {"username": "xy", "display_name": "X", "applications": ["nope"]}),
        ("post", "/api/app-keys", {"app_id": "Not An Id!"}),
        ("post", "/api/users/ana.lima/password", {"password": "short"}),
    ],
)
def test_bad_inputs_are_refused_not_crashes(app, method, url, body):
    with TestClient(app):
        admin = _login(app, "admin", ADMIN_PASSWORD)
        answer = getattr(admin, method)(url, json=body)
        assert answer.status_code == 422, answer.text
        # The home page keeps answering after a refused change.
        assert admin.get("/api/home").status_code == 200


@pytest.mark.parametrize("name", ["app:histcraft", "app:processcraft", "ops/ana", "a\\b"])
def test_no_person_takes_an_app_s_service_identity(app, name):
    # Apps trust a token whose subject is ``app:<id>`` as that app's service (offline): a person
    # may never be named like one, nor get a user token with such a subject.
    from processcraft.api.identity import issue_user_token

    with TestClient(app):
        admin = _login(app, "admin", ADMIN_PASSWORD)
        person = {"username": name, "display_name": "X", "password": "a-long-password"}
        assert admin.post("/api/users", json=person).status_code == 422
    with pytest.raises(ValueError):
        app.state.runtime.workspace.users.upsert_user(name, "X", "")
    assert issue_user_token(app.state.runtime, "app:histcraft") is None


def test_failed_sign_ins_are_counted_in_the_database(tmp_path):
    # Every server process sees the same count, and old rows go away as new ones arrive.
    from processcraft.db import Database

    db = Database(tmp_path / "w.sqlite3")
    first, second = throttle.LoginThrottle(db), throttle.LoginThrottle(db)
    for _ in range(throttle.LIMIT):
        first.record(["user:ana"], now=1000.0)
    assert second.blocked(["user:ana"], now=1001.0)
    assert not second.blocked(["user:ana"], now=1000.0 + throttle.WINDOW_SECONDS + 1)
    second.record(["user:bob"], now=1000.0 + throttle.WINDOW_SECONDS + 1)
    with db.connect() as connection:
        keys = {row[0] for row in connection.execute("SELECT key FROM login_failures")}
    assert keys == {"user:bob"}
