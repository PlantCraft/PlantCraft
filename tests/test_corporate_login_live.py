"""Corporate sign-in against a real directory and provider: OpenLDAP (over LDAPS and StartTLS)
and Keycloak, started by ``dev/corporate-login`` (its README). Skipped unless
``PLANTCRAFT_LIVE_DIRECTORY=1``; nothing here reaches beyond this machine."""

from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from fastapi.testclient import TestClient

from processcraft.api.app import create_app
from processcraft.directory import oidc
from processcraft.directory.settings import LDAP_PRESETS

pytestmark = pytest.mark.skipif(
    os.environ.get("PLANTCRAFT_LIVE_DIRECTORY") != "1",
    reason="needs dev/corporate-login running (PLANTCRAFT_LIVE_DIRECTORY=1)",
)

ROOT = Path(__file__).resolve().parents[1]
CA = ROOT / "dev" / "corporate-login" / "certs" / "ca.crt"
ADMIN_PASSWORD = "Sup3rSecretAdmin"
RULES = [
    {"match": "pc-engineers", "level": "editor", "groups": ["engineering"]},
    {"match": "pc-operators", "level": "viewer", "apps": ["histcraft"]},
    {"match": "pc-admins", "level": "admin"},
]


def _ldap(**changes):
    return {
        **LDAP_PRESETS["openldap"],
        "preset": "openldap",
        "enabled": True,
        "url": "ldaps://ldap.plant.test:1636",
        "security": "ldaps",
        "ca_certificate": CA.read_text(),
        "bind_dn": "uid=reader,ou=people,dc=plant,dc=test",
        "base_dn": "dc=plant,dc=test",
        **changes,
    }


def _oidc(**changes):
    return {
        "enabled": True,
        "label": "Test Company",
        "issuer": "https://sso.plant.test:8443/realms/plant",
        "client_id": "processcraft",
        "public_url": "http://testserver",
        "ca_certificate": CA.read_text(),
        **changes,
    }


@pytest.fixture()
def app(tmp_path, monkeypatch):
    oidc._cache.clear()
    scenario = json.loads((ROOT / "scenarios" / "generic_demo.json").read_text())
    scenario["storage"]["sqlite_path"] = str(tmp_path / "workspace.sqlite3")
    scenario["source"]["path"] = str(ROOT / scenario["source"]["path"])
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario))
    secret = tmp_path / "admin-password"
    secret.write_text(ADMIN_PASSWORD)
    for name, value in {
        "PLANTCRAFT_SCENARIO": str(path),
        "PLANTCRAFT_PREWARM_HISTORY": "false",
        "PLANTCRAFT_DEMO_USERS": "false",
        "PLANTCRAFT_APPS": "histcraft=http://histcraft:8100",
        "PLANTCRAFT_BASIC_AUTH_ENABLED": "true",
        "PLANTCRAFT_BASIC_AUTH_USERNAME": "admin",
        "PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE": str(secret),
    }.items():
        monkeypatch.setenv(name, value)
    application = create_app()
    application.state.runtime.workspace.groups.create("Engineering", group_id="engineering")
    return application


def _admin(app) -> TestClient:
    client = TestClient(app)
    assert (
        client.post(
            "/api/login", json={"username": "admin", "password": ADMIN_PASSWORD}
        ).status_code
        == 200
    )
    return client


def _save(admin: TestClient, **settings) -> None:
    reply = admin.put(
        "/api/directory",
        json={
            "settings": {"ldap": _ldap(), "oidc": _oidc(), "rules": RULES, **settings},
            "ldap_bind_password": "reader-service-pass",
            "oidc_client_secret": "processcraft-test-secret",
        },
    )
    assert reply.status_code == 200, reply.text


@pytest.mark.parametrize(
    "ldap",
    [
        {"url": "ldaps://ldap.plant.test:1636", "security": "ldaps"},
        {"url": "ldap://ldap.plant.test:1389", "security": "starttls"},
    ],
)
def test_ldap_sign_in_over_tls(app, ldap):
    admin = _admin(app)
    _save(admin, ldap=_ldap(**ldap))
    test = admin.post(
        "/api/directory/ldap/test",
        json={
            "settings": {"ldap": _ldap(**ldap), "rules": RULES},
            "username": "ana.lima",
            "password": "ana-directory-pass",
        },
    ).json()
    assert test["ok"] and test["access"]["level"] == "admin", test
    client = TestClient(app)
    reply = client.post(
        "/api/login", json={"username": "ana.lima", "password": "ana-directory-pass"}
    )
    assert reply.status_code == 200, reply.text
    user = app.state.runtime.workspace.users.get_user("ana.lima")
    assert user["auth_source"] == "ldap" and user["access_level"] == "admin"
    assert (
        user["profile"]["job_title"] == "Process engineer" and user["profile"]["unit"] == "Unit 100"
    )
    assert app.state.runtime.workspace.groups.members("engineering") == ["ana.lima"]
    bad = TestClient(app).post("/api/login", json={"username": "ana.lima", "password": "wrong"})
    assert bad.status_code == 401
    outsider = TestClient(app).post(
        "/api/login", json={"username": "outsider", "password": "outsider-directory-pass"}
    )
    assert outsider.status_code == 403


def test_ldap_refuses_a_server_whose_certificate_is_not_trusted(app):
    admin = _admin(app)
    test = admin.post(
        "/api/directory/ldap/test", json={"settings": {"ldap": _ldap(ca_certificate="")}}
    ).json()
    assert not test["ok"] and "certificate" in test["steps"][0]["detail"]


def _keycloak_sign_in(location: str, username: str, password: str) -> tuple[str, str]:
    """The person types their name and password on Keycloak's page: the callback's query."""

    browser = requests.Session()
    page = browser.get(location, verify=str(CA), timeout=10)
    action = html.unescape(re.search(r'action="([^"]+)"', page.text).group(1))
    reply = browser.post(
        action,
        data={"username": username, "password": password, "credentialId": ""},
        allow_redirects=False,
        verify=str(CA),
        timeout=10,
    )
    query = parse_qs(urlsplit(reply.headers["Location"]).query)
    return query["code"][0], query["state"][0]


def test_single_sign_on_with_keycloak(app):
    admin = _admin(app)
    _save(admin)
    assert admin.post("/api/directory/oidc/test", json={"settings": {"oidc": _oidc()}}).json()["ok"]
    client = TestClient(app)
    start = client.get("/api/sso/oidc/start?next=/assets", follow_redirects=False)
    code, state = _keycloak_sign_in(start.headers["location"], "marina.costa", "marina-sso-pass")
    reply = client.get(f"/api/sso/oidc/callback?code={code}&state={state}", follow_redirects=False)
    assert reply.headers["location"] == "/assets", client.get("/api/sso/methods").json()
    session = client.get("/api/session").json()
    assert session["username"] == "marina.costa" and session["access"]["level"] == "editor"
    user = app.state.runtime.workspace.users.get_user("marina.costa")
    assert user["auth_source"] == "oidc" and user["profile"]["email"] == "marina.costa@plant.test"
    # The same code a second time: refused by Keycloak and by the session.
    again = client.get(f"/api/sso/oidc/callback?code={code}&state={state}", follow_redirects=False)
    assert again.headers["location"] == "/login?sso=failed"

    outsider = TestClient(app)
    start = outsider.get("/api/sso/oidc/start", follow_redirects=False)
    code, state = _keycloak_sign_in(start.headers["location"], "outsider", "outsider-sso-pass")
    reply = outsider.get(
        f"/api/sso/oidc/callback?code={code}&state={state}", follow_redirects=False
    )
    assert reply.headers["location"] == "/login?sso=failed"
    assert "not in any group" in outsider.get("/api/sso/methods").json()["error"]
