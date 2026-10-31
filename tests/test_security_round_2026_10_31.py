"""The fixes of the security test of 2026-10-31 (report 05-seguranca.md): sign-out ends the
cookie, a burst of wrong passwords never locks a person out from another address, the people
list shows names only to non-administrators, and the route list is not served."""

from __future__ import annotations

from fastapi.testclient import TestClient

from plantcraft.auth import throttle
from tests.test_security import ADMIN_PASSWORD, _login, app  # noqa: F401  (fixture)


def test_a_cookie_copied_before_sign_out_stops_working(app):  # noqa: F811
    with TestClient(app):
        person = _login(app, "joao.op", "senha-do-joao")
        copied = dict(person.cookies)
        assert person.get("/api/session").json()["authenticated"] is True
        assert person.post("/api/logout").status_code == 200
        thief = TestClient(app, cookies=copied)
        assert thief.get("/api/session").json()["authenticated"] is False
        assert thief.get("/api/users").status_code == 401
        # Signing in again gives a new session that works.
        again = _login(app, "joao.op", "senha-do-joao")
        assert again.get("/api/session").json()["authenticated"] is True


def test_wrong_passwords_from_one_address_do_not_lock_the_person_out_elsewhere(app):  # noqa: F811
    with TestClient(app):
        attacker = TestClient(app, client=("203.0.113.9", 5000))
        for _ in range(throttle.PAIR_FREE + 3):
            attacker.post("/api/login", json={"username": "admin", "password": "wrong"})
        blocked = attacker.post("/api/login", json={"username": "admin", "password": "wrong"})
        assert blocked.status_code == 429
        assert int(blocked.headers["retry-after"]) >= 1
        desk = TestClient(app, client=("198.51.100.4", 5000))
        answer = desk.post("/api/login", json={"username": "admin", "password": ADMIN_PASSWORD})
        assert answer.status_code == 200


def test_the_wait_doubles_and_has_a_ceiling():
    import tempfile
    from pathlib import Path

    from plantcraft.db import Database

    with tempfile.TemporaryDirectory() as folder:
        store = throttle.LoginThrottle(Database(Path(folder) / "w.sqlite3"))
        key = throttle.pair_key("ana", "10.0.0.1")
        for second in range(throttle.PAIR_FREE):
            assert store.wait([key], now=1000.0 + second) == 0
            store.record([key], now=1000.0 + second)
        last = 1000.0 + throttle.PAIR_FREE - 1
        assert store.wait([key], now=last) == throttle.PAIR_FIRST_WAIT
        store.record([key], now=last)
        assert store.wait([key], now=last) == 2 * throttle.PAIR_FIRST_WAIT
        for _ in range(20):
            store.record([key], now=last)
        assert store.wait([key], now=last) == throttle.PAIR_MAX_WAIT


def test_an_address_spraying_many_names_is_stopped():
    import tempfile
    from pathlib import Path

    from plantcraft.db import Database

    with tempfile.TemporaryDirectory() as folder:
        store = throttle.LoginThrottle(Database(Path(folder) / "w.sqlite3"), address_limit=3)
        address = throttle.address_key("10.0.0.2")
        for index in range(3):
            store.record([throttle.pair_key(f"u{index}", "10.0.0.2"), address], now=1000.0)
        assert store.blocked([throttle.pair_key("u9", "10.0.0.2"), address], now=1001.0)
        assert not store.blocked([address], now=1000.0 + store.window + 1)


def test_the_people_list_shows_names_only_to_non_administrators(app):  # noqa: F811
    with TestClient(app):
        users = app.state.runtime.workspace.users
        users.set_profile("joao.op", {"email": "joao@example.com", "phone": "+55 51 9999"})
        member = _login(app, "joao.op", "senha-do-joao")
        listed = member.get("/api/users").json()
        assert listed and all(
            set(row) == {"username", "display_name", "role", "active", "kind"} for row in listed
        )
        assert "joao@example.com" not in member.get("/api/users").text
        admin = _login(app, "admin", ADMIN_PASSWORD)
        assert "joao@example.com" in admin.get("/api/users").text


def test_the_route_list_is_not_served(app):  # noqa: F811
    with TestClient(app) as client:
        answer = client.get("/openapi.json")
        # Not the API description (the page's own HTML, or nothing at all).
        assert '"paths"' not in answer.text


def test_signing_out_ends_the_browser_token_in_the_platform_and_the_apps(app):  # noqa: F811
    from plantcraft_sdk import jwt

    with TestClient(app):
        person = _login(app, "joao.op", "senha-do-joao")
        token = person.post("/api/v1/auth/token").json()["token"]
        sid = jwt.unverified_claims(token)["sid"]
        bearer = {"Authorization": f"Bearer {token}"}
        assert TestClient(app).get("/api/v1/me", headers=bearer).status_code == 200
        assert TestClient(app).get("/api/v1/auth/revoked").json()["sessions"] == []
        assert person.post("/api/logout").status_code == 200
        # The token copied before sign-out: refused by the platform at once ...
        assert TestClient(app).get("/api/v1/me", headers=bearer).status_code == 401
        # ... and listed for the apps, which refuse it within REVOKED_TTL_SECONDS.
        listed = [
            s["sid_sha256"] for s in TestClient(app).get("/api/v1/auth/revoked").json()["sessions"]
        ]
        assert listed == [sid]
        # A new sign-in gets a new session and a token that works.
        again = _login(app, "joao.op", "senha-do-joao")
        fresh = again.post("/api/v1/auth/token").json()["token"]
        assert (
            TestClient(app)
            .get("/api/v1/me", headers={"Authorization": f"Bearer {fresh}"})
            .status_code
            == 200
        )
