"""Corporate sign-in (docs/corporate-login.md): LDAP or Active Directory and OIDC, the group
rules, the account created on the first sign-in, and the admin's way in that never depends on
the directory. Against an in-memory directory and provider (``tests/directory_fakes.py``)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from fastapi.testclient import TestClient

from processcraft.api.app import create_app
from processcraft.directory import jose, map_access, oidc
from processcraft.directory.mapping import local_username
from processcraft.directory.settings import DirectorySettings, check_settings
from tests.directory_fakes import (
    CLIENT_SECRET,
    SERVICE_PASSWORD,
    FakeDirectory,
    FakeProvider,
    b64,
    ldap_settings,
    oidc_settings,
)

ROOT = Path(__file__).resolve().parents[1]
ADMIN_PASSWORD = "Sup3rSecretAdmin"

RULES = [
    {"match": "pc-engineers", "level": "editor", "apps": None, "groups": ["engineering"]},
    {
        "match": "pc-operators",
        "level": "viewer",
        "apps": ["histcraft"],
        "app_roles": {"histcraft": "viewer"},
        "groups": ["operations"],
    },
    {"match": "pc-admins", "level": "admin"},
]


# Settings and rules -----------------------------------------------------------------------


def test_everything_is_off_by_default():
    settings = DirectorySettings()
    assert not settings.ldap.enabled and not settings.oidc.enabled
    assert settings.unmatched == "deny" and settings.local_passwords
    assert not settings.method_enabled("ldap") and not settings.method_enabled("oidc")


@pytest.mark.parametrize(
    ("ldap", "message"),
    [
        ({"security": "none"}, "never travel in clear"),
        ({"url": "ldap://dc1.company.local", "security": "ldaps"}, "ldaps://"),
        ({"url": "ldaps://dc1.company.local", "security": "starttls"}, "ldap://"),
        ({"url": "http://dc1"}, "ldaps://host"),
        ({"user_filter": "(uid=fixed)"}, "{username}"),
        ({"user_filter": "uid={username}"}, "filter in parentheses"),
        ({"base_dn": ""}, "search base"),
        ({"ca_certificate": "not a certificate"}, "BEGIN CERTIFICATE"),
        ({"email_attribute": "mail; drop"}, "attribute name"),
    ],
)
def test_ldap_settings_are_refused_when_unsafe_or_incomplete(ldap, message):
    with pytest.raises(ValueError, match=message.replace("{", r"\{").replace("}", r"\}")):
        check_settings({"ldap": ldap_settings(**ldap)})


@pytest.mark.parametrize(
    ("oidc", "message"),
    [
        ({"issuer": "http://sso.company.local/realms/plant"}, "https://"),
        ({"issuer": "https://sso.company.local/?x=1"}, "https://"),
        ({"scopes": "profile email"}, "openid"),
        ({"public_url": ""}, "PlantCraft's address"),
        ({"username_claim": "name with spaces"}, "claim name"),
    ],
)
def test_oidc_settings_are_refused_when_unsafe_or_incomplete(oidc, message):
    with pytest.raises(ValueError, match=message):
        check_settings({"oidc": oidc_settings(**oidc)})


def test_rules_name_known_apps_and_groups_only():
    with pytest.raises(ValueError, match="Unknown app"):
        check_settings({"rules": [{"match": "x", "apps": ["nope"]}]}, app_ids={"histcraft"})
    with pytest.raises(ValueError, match="Group not found"):
        check_settings({"rules": [{"match": "x", "groups": ["nope"]}]}, group_ids={"operations"})
    with pytest.raises(ValueError, match="viewer or editor"):
        check_settings({"rules": [{"match": "x", "app_roles": {"histcraft": "owner"}}]})
    with pytest.raises(ValueError, match="refused or get"):
        check_settings({"unmatched": "admin"})


def test_rules_give_the_highest_level_and_every_app_of_the_matched_groups():
    settings = check_settings({"rules": RULES})
    engineer = map_access(settings, ("cn=pc-engineers,ou=groups,dc=plant,dc=test",))
    assert engineer.level == "editor" and engineer.apps is None
    assert engineer.groups == ("engineering",)
    operator = map_access(settings, ("/pc-operators",))  # Keycloak's full group path
    assert operator.level == "viewer" and operator.apps == ("histcraft",)
    assert operator.app_roles == {"histcraft": "viewer"}
    both = map_access(settings, ("CN=PC-Operators,OU=Groups,DC=plant", "pc-admins"))
    assert both.level == "admin" and both.apps is None  # the admins rule names no apps: all
    assert map_access(settings, ("someone-else",)) is None
    assert map_access(check_settings({"unmatched": "viewer"}), ()).level == "viewer"


def test_a_rule_with_a_dn_matches_only_that_dn():
    settings = check_settings(
        {"rules": [{"match": "CN=Ops,OU=Plant A,DC=corp", "level": "editor"}]}
    )
    assert map_access(settings, ("cn=ops,ou=plant a,dc=corp",)).level == "editor"
    assert map_access(settings, ("cn=ops,ou=plant b,dc=corp",)) is None


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("ana.lima", "ana.lima"),
        ("CORP\\Ana.Lima", "ana.lima"),
        ("ana.lima@plant.test", "ana.lima"),
        ("Ana Lima", "ana.lima"),
    ],
)
def test_directory_names_become_usernames(typed, expected):
    assert local_username(typed) == expected


# ID token signatures -----------------------------------------------------------------------


def _jwk_ec(key: ec.EllipticCurvePrivateKey) -> dict:
    numbers = key.public_key().public_numbers()
    return {
        "kty": "EC",
        "crv": "P-256",
        "kid": "ec",
        "x": b64(numbers.x.to_bytes(32, "big")),
        "y": b64(numbers.y.to_bytes(32, "big")),
    }


def _signed(header: dict, claims: dict, sign) -> str:
    data = f"{b64(json.dumps(header).encode())}.{b64(json.dumps(claims).encode())}"
    return f"{data}.{b64(sign(data.encode()))}"


def test_signatures_are_checked_for_rsa_ec_and_eddsa():
    provider = FakeProvider()
    keys = provider.get("https://sso.plant.test/realms/plant/certs").json()["keys"]
    assert jose.verify(provider.id_token({"sub": "a"}), keys) == {"sub": "a"}

    ec_key = ec.generate_private_key(ec.SECP256R1())

    def ec_sign(data: bytes) -> bytes:
        r, s = decode_dss_signature(ec_key.sign(data, ec.ECDSA(hashes.SHA256())))
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")

    assert (
        jose.verify(
            _signed({"alg": "ES256", "kid": "ec"}, {"sub": "b"}, ec_sign), [_jwk_ec(ec_key)]
        )["sub"]
        == "b"
    )

    ed_key = ed25519.Ed25519PrivateKey.generate()
    raw = ed_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    token = _signed({"alg": "EdDSA", "kid": "ed"}, {"sub": "c"}, ed_key.sign)
    assert (
        jose.verify(token, [{"kty": "OKP", "crv": "Ed25519", "kid": "ed", "x": b64(raw)}])["sub"]
        == "c"
    )


def test_unsigned_hmac_tampered_and_unknown_key_tokens_are_refused():
    provider = FakeProvider()
    keys = provider.get("https://sso.plant.test/realms/plant/certs").json()["keys"]
    good = provider.id_token({"sub": "a"})
    header, body, signature = good.split(".")
    for token in (
        _signed({"alg": "none", "kid": "key-1"}, {"sub": "a"}, lambda data: b""),
        _signed({"alg": "HS256", "kid": "key-1"}, {"sub": "a"}, lambda data: b"x" * 32),
        f"{header}.{b64(json.dumps({'sub': 'admin'}).encode())}.{signature}",
        FakeProvider().id_token({"sub": "a"}),  # another provider's key, same kid
        "not.a.token",
    ):
        with pytest.raises(jose.InvalidToken):
            jose.verify(token, keys)


# The application ----------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_provider_cache():
    # Each test's provider has its own keys under the same address.
    oidc._cache.clear()
    yield
    oidc._cache.clear()


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
    monkeypatch.setenv("PLANTCRAFT_DEMO_USERS", "false")
    monkeypatch.setenv(
        "PLANTCRAFT_APPS", "histcraft=http://histcraft:8100,linkcraft=http://linkcraft:8140"
    )
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_ENABLED", "true")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_USERNAME", "admin")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE", str(secret))
    application = create_app()
    rt = application.state.runtime
    rt.workspace.groups.create("Engineering", group_id="engineering")
    rt.workspace.groups.create("Operations", group_id="operations")
    directory = FakeDirectory()
    directory.add_person(
        "ana.lima",
        "ana-directory-pass",
        groups=("pc-engineers",),
        cn="Ana Lima",
        mail="ana.lima@plant.test",
        title="Process engineer",
        ou="Process engineering",
    )
    directory.add_person(
        "carlos.menezes", "carlos-directory-pass", groups=("pc-operators",), cn="Carlos Menezes"
    )
    directory.add_person("outsider", "outsider-directory-pass", cn="Someone Else")
    rt.directory.ldap_connect = directory.connect
    provider = FakeProvider()
    rt.directory.oidc_http = provider
    application.state.fake_directory = directory
    application.state.fake_provider = provider
    return application


def _admin(app) -> TestClient:
    client = TestClient(app)
    reply = client.post("/api/login", json={"username": "admin", "password": ADMIN_PASSWORD})
    assert reply.status_code == 200, reply.text
    return client


def _configure(app, **changes) -> TestClient:
    admin = _admin(app)
    settings = {"ldap": ldap_settings(), "oidc": oidc_settings(), "rules": RULES, **changes}
    reply = admin.put(
        "/api/directory",
        json={
            "settings": settings,
            "ldap_bind_password": SERVICE_PASSWORD,
            "oidc_client_secret": CLIENT_SECRET,
        },
    )
    assert reply.status_code == 200, reply.text
    return admin


def _login(app, username: str, password: str):
    client = TestClient(app)
    return client, client.post("/api/login", json={"username": username, "password": password})


def test_the_settings_never_send_the_secrets_back(app, tmp_path):
    admin = _configure(app)
    body = admin.get("/api/directory").json()
    text = json.dumps(body)
    assert SERVICE_PASSWORD not in text and CLIENT_SECRET not in text
    assert body["ldap"]["has_bind_password"] and body["oidc"]["has_client_secret"]
    assert body["oidc"]["redirect_uri"] == "http://testserver/api/sso/oidc/callback"
    secrets_file = tmp_path / "directory-secrets.json"
    assert secrets_file.stat().st_mode & 0o777 == 0o600
    assert SERVICE_PASSWORD not in (tmp_path / "workspace.sqlite3").read_bytes().decode("latin-1")
    audit = app.state.runtime.workspace.audit.list(limit=20, username="admin")
    assert any(row["action"] == "directory.settings" for row in audit)


def test_only_admins_see_or_change_corporate_sign_in(app):
    _configure(app)
    rt = app.state.runtime
    rt.workspace.users.upsert_user("eddie", "Eddie", "Engineering")
    rt.workspace.users.set_password("eddie", "eddie-strong-password")
    rt.workspace.users.set_access("eddie", "editor", None)
    editor, reply = _login(app, "eddie", "eddie-strong-password")
    assert reply.status_code == 200
    assert editor.get("/api/directory").status_code == 403
    assert editor.put("/api/directory", json={"settings": {}}).status_code == 403
    assert editor.post("/api/directory/ldap/test", json={}).status_code == 403


def test_the_sign_in_page_offers_what_is_on(app):
    anonymous = TestClient(app)
    assert anonymous.get("/api/sso/methods").json() == {
        "ldap": False,
        "oidc": False,
        "oidc_label": None,
        "error": None,
    }
    _configure(app)
    methods = anonymous.get("/api/sso/methods").json()
    assert methods["ldap"] and methods["oidc"] and methods["oidc_label"] == "Test Company"


def test_a_directory_person_signs_in_and_gets_an_account_profile_access_and_groups(app):
    _configure(app)
    client, reply = _login(app, "ana.lima", "ana-directory-pass")
    assert reply.status_code == 200, reply.text
    rt = app.state.runtime
    user = rt.workspace.users.get_user("ana.lima")
    assert user["display_name"] == "Ana Lima" and user["auth_source"] == "ldap"
    assert user["access_level"] == "editor" and user["applications"] is None
    assert user["profile"]["email"] == "ana.lima@plant.test"
    assert (
        user["profile"]["job_title"] == "Process engineer" and user["role"] == "Process engineering"
    )
    assert rt.workspace.groups.members("engineering") == ["ana.lima"]
    assert not rt.workspace.users.has_password("ana.lima")
    session = client.get("/api/session").json()
    assert session["authenticated"] and session["access"]["level"] == "editor"
    # The suite's token cookie is set: the apps open for her too.
    assert client.cookies.get("processcraft_token")


def test_each_sign_in_brings_access_and_groups_up_to_date(app):
    _configure(app)
    rt = app.state.runtime
    _login(app, "carlos.menezes", "carlos-directory-pass")
    user = rt.workspace.users.get_user("carlos.menezes")
    assert user["access_level"] == "viewer" and user["applications"] == ["histcraft"]
    assert rt.workspace.groups.members("operations") == ["carlos.menezes"]
    # IT moves Carlos to engineering in the directory.
    directory = app.state.fake_directory
    carlos = "uid=carlos.menezes,ou=people,dc=plant,dc=test"
    it = directory.connect(None, "", "")
    it.bind()
    it.modify("cn=pc-engineers,ou=groups,dc=plant,dc=test", {"member": [("MODIFY_ADD", [carlos])]})
    it.modify(
        "cn=pc-operators,ou=groups,dc=plant,dc=test", {"member": [("MODIFY_DELETE", [carlos])]}
    )
    _client, reply = _login(app, "carlos.menezes", "carlos-directory-pass")
    assert reply.status_code == 200, reply.text
    user = rt.workspace.users.get_user("carlos.menezes")
    assert user["access_level"] == "editor" and user["applications"] is None
    assert rt.workspace.groups.members("operations") == []
    assert rt.workspace.groups.members("engineering") == ["carlos.menezes"]


def test_wrong_passwords_and_people_in_no_mapped_group_are_refused(app):
    _configure(app)
    _client, reply = _login(app, "ana.lima", "wrong-password")
    assert reply.status_code == 401 and reply.json()["detail"] == "Incorrect username or password."
    _client, reply = _login(app, "nobody", "whatever-password")
    assert reply.status_code == 401
    _client, reply = _login(app, "ana.lima", "")
    assert reply.status_code in (401, 422)
    _client, reply = _login(app, "outsider", "outsider-directory-pass")
    assert reply.status_code == 403 and "not in any group" in reply.json()["detail"]
    assert app.state.runtime.workspace.users.get_user("outsider") is None


def test_ldap_filters_cannot_be_injected_through_the_username(app):
    _configure(app)
    for typed in ("*", "ana*", "ana.lima)(uid=*", "*)(|(uid=*"):
        _client, reply = _login(app, typed, "ana-directory-pass")
        assert reply.status_code == 401, typed


def test_the_admin_signs_in_when_the_directory_is_down(app):
    _configure(app)
    app.state.fake_directory.down = True
    _client, reply = _login(app, "admin", ADMIN_PASSWORD)
    assert reply.status_code == 200
    _client, reply = _login(app, "ana.lima", "ana-directory-pass")
    assert reply.status_code == 503 and "did not answer" in reply.json()["detail"]


def test_local_passwords_can_be_turned_off_except_for_the_admin(app):
    rt = app.state.runtime
    rt.workspace.users.upsert_user("eddie", "Eddie", "Engineering")
    rt.workspace.users.set_password("eddie", "eddie-strong-password")
    eddie, reply = _login(app, "eddie", "eddie-strong-password")
    assert reply.status_code == 200
    _configure(app, local_passwords=False)
    assert eddie.get("/api/session").json()["authenticated"] is False
    _client, reply = _login(app, "eddie", "eddie-strong-password")
    assert reply.status_code == 401
    _client, reply = _login(app, "admin", ADMIN_PASSWORD)
    assert reply.status_code == 200


def test_a_local_account_is_never_taken_over_by_a_directory_namesake(app):
    rt = app.state.runtime
    rt.workspace.users.upsert_user("ana.lima", "Ana (local)", "Engineering")
    rt.workspace.users.set_password("ana.lima", "local-strong-password")
    _configure(app)
    _client, reply = _login(app, "ana.lima", "ana-directory-pass")
    assert reply.status_code == 401
    assert rt.workspace.users.identity("ana.lima") == ("local", None)
    _client, reply = _login(app, "ana.lima", "local-strong-password")
    assert reply.status_code == 200


def test_an_account_an_admin_created_without_a_password_is_adopted(app):
    rt = app.state.runtime
    rt.workspace.users.upsert_user("ana.lima", "Ana", "Engineering")
    _configure(app)
    _client, reply = _login(app, "ana.lima", "ana-directory-pass")
    assert reply.status_code == 200
    assert rt.workspace.users.identity("ana.lima") == ("ldap", "uuid-ana.lima")


def test_the_installation_admin_account_is_never_a_directory_person(app):
    directory = app.state.fake_directory
    directory.add_person("admin", "directory-admin-pass", groups=("pc-admins",))
    _configure(app)
    _client, reply = _login(app, "admin", "directory-admin-pass")
    assert reply.status_code == 401
    assert app.state.runtime.workspace.users.identity("admin")[0] == "local"


def test_turned_off_here_stays_off_whatever_the_directory_says(app):
    _configure(app)
    rt = app.state.runtime
    client, _reply = _login(app, "ana.lima", "ana-directory-pass")
    rt.workspace.users.deactivate("ana.lima")
    assert client.get("/api/session").json()["authenticated"] is False
    _client, reply = _login(app, "ana.lima", "ana-directory-pass")
    assert reply.status_code == 403 and "turned off" in reply.json()["detail"]
    assert not rt.workspace.users.get_user("ana.lima")["active"]


def test_directory_sessions_end_after_the_hours_set_and_when_the_method_is_off(app):
    admin = _configure(app, session_hours=2)
    client, _reply = _login(app, "ana.lima", "ana-directory-pass")
    assert client.get("/api/session").json()["authenticated"]
    real = time.time
    try:
        time.time = lambda: real() + 3 * 3600  # type: ignore[assignment]
        assert client.get("/api/session").json()["authenticated"] is False
    finally:
        time.time = real  # type: ignore[assignment]
    client, _reply = _login(app, "ana.lima", "ana-directory-pass")
    assert client.get("/api/session").json()["authenticated"]
    reply = admin.put(
        "/api/directory",
        json={
            "settings": {
                "ldap": ldap_settings(enabled=False),
                "oidc": oidc_settings(),
                "rules": RULES,
            }
        },
    )
    assert reply.status_code == 200
    assert client.get("/api/session").json()["authenticated"] is False


def test_a_directory_person_has_no_password_here(app):
    _configure(app)
    _login(app, "ana.lima", "ana-directory-pass")
    with pytest.raises(ValueError, match="company directory"):
        app.state.runtime.workspace.users.set_password("ana.lima", "a-new-local-password")


def test_the_ldap_test_shows_each_step_and_the_access_it_would_give(app):
    admin = _configure(app)
    settings = {"ldap": ldap_settings(), "rules": RULES}
    reply = admin.post(
        "/api/directory/ldap/test",
        json={"settings": settings, "username": "ana.lima", "password": "ana-directory-pass"},
    )
    body = reply.json()
    assert reply.status_code == 200 and body["ok"], body
    assert [step["ok"] for step in body["steps"]] == [True, True, True, True]
    assert body["person"]["display_name"] == "Ana Lima"
    assert body["access"]["level"] == "editor"
    reply = admin.post(
        "/api/directory/ldap/test", json={"settings": settings, "ldap_bind_password": "wrong"}
    )
    assert reply.json()["ok"] is False and "service account" in reply.json()["steps"][0]["detail"]


# Single sign-on (OIDC) ----------------------------------------------------------------------


def _sso(app, claims: dict, *, client: TestClient | None = None):
    client = client or TestClient(app)
    start = client.get("/api/sso/oidc/start?next=/assets", follow_redirects=False)
    assert start.status_code == 303, start.text
    code, state = app.state.fake_provider.sign_in(start.headers["location"], claims)
    return client, client.get(
        f"/api/sso/oidc/callback?code={code}&state={state}", follow_redirects=False
    )


def test_single_sign_on_creates_the_person_and_opens_the_session(app):
    _configure(app)
    claims = {
        "sub": "kc-1",
        "preferred_username": "marina.costa",
        "name": "Marina Costa",
        "email": "marina.costa@plant.test",
        "groups": ["pc-engineers"],
    }
    client, reply = _sso(app, claims)
    assert reply.status_code == 303 and reply.headers["location"] == "/assets"
    session = client.get("/api/session").json()
    assert session["authenticated"] and session["username"] == "marina.costa"
    user = app.state.runtime.workspace.users.get_user("marina.costa")
    assert user["auth_source"] == "oidc" and user["access_level"] == "editor"
    assert user["profile"]["email"] == "marina.costa@plant.test"


def test_single_sign_on_reads_missing_claims_from_user_info(app):
    _configure(app)
    provider = app.state.fake_provider
    provider.userinfo = {"sub": "kc-2", "groups": ["pc-operators"], "name": "Rafael Souza"}
    client, reply = _sso(app, {"sub": "kc-2", "preferred_username": "rafael.souza"})
    assert reply.headers["location"] == "/assets"
    assert app.state.runtime.workspace.users.get_user("rafael.souza")["access_level"] == "viewer"
    # Another person's details are never taken.
    provider.userinfo = {"sub": "someone-else", "groups": ["pc-admins"]}
    client, reply = _sso(app, {"sub": "kc-3", "preferred_username": "x.person"})
    assert reply.headers["location"].startswith("/login")


@pytest.mark.parametrize(
    "tamper",
    [{"nonce": "replayed"}, {"aud": "another-client"}, {"iss": "https://evil.test"}, {"exp": 1000}],
)
def test_single_sign_on_refuses_tokens_that_fail_a_check(app, tamper):
    _configure(app)
    app.state.fake_provider.tamper = tamper
    client, reply = _sso(
        app, {"sub": "kc-1", "preferred_username": "marina.costa", "groups": ["pc-engineers"]}
    )
    assert reply.status_code == 303 and reply.headers["location"] == "/login?sso=failed"
    assert client.get("/api/session").json()["authenticated"] is False
    error = client.get("/api/sso/methods").json()["error"]
    assert "ID token was not accepted" in error
    # Said once.
    assert client.get("/api/sso/methods").json()["error"] is None


def test_single_sign_on_refuses_a_forged_or_replayed_callback(app):
    _configure(app)
    client = TestClient(app)
    reply = client.get("/api/sso/oidc/callback?code=x&state=forged", follow_redirects=False)
    assert reply.headers["location"] == "/login?sso=failed"
    client, reply = _sso(
        app, {"sub": "kc-1", "preferred_username": "marina.costa", "groups": ["pc-engineers"]}
    )
    location = reply.headers["location"]
    assert location == "/assets"
    # The same code again: the flow is gone from the session.
    attacker = TestClient(app)
    start = attacker.get("/api/sso/oidc/start", follow_redirects=False)
    code, _state = app.state.fake_provider.sign_in(
        start.headers["location"], {"sub": "kc-9", "preferred_username": "x"}
    )
    stolen = client.get(
        f"/api/sso/oidc/callback?code={code}&state=whatever", follow_redirects=False
    )
    assert stolen.headers["location"] == "/login?sso=failed"


def test_single_sign_on_lands_only_on_this_site(app):
    _configure(app)
    client = TestClient(app)
    for target in ("https://evil.test", "//evil.test", "/\\evil.test"):
        start = client.get(f"/api/sso/oidc/start?next={target}", follow_redirects=False)
        code, state = app.state.fake_provider.sign_in(
            start.headers["location"],
            {"sub": "kc-1", "preferred_username": "marina.costa", "groups": ["pc-engineers"]},
        )
        reply = client.get(
            f"/api/sso/oidc/callback?code={code}&state={state}", follow_redirects=False
        )
        assert reply.headers["location"] == "/", target


def test_single_sign_on_is_closed_while_off(app):
    client = TestClient(app)
    reply = client.get("/api/sso/oidc/start", follow_redirects=False)
    assert reply.headers["location"] == "/login?sso=failed"
    assert "not turned on" in client.get("/api/sso/methods").json()["error"]


def test_the_authorization_request_carries_pkce_state_and_nonce(app):
    _configure(app)
    start = TestClient(app).get("/api/sso/oidc/start", follow_redirects=False)
    query = parse_qs(urlsplit(start.headers["location"]).query)
    assert query["code_challenge_method"] == ["S256"] and len(query["code_challenge"][0]) == 43
    assert len(query["state"][0]) >= 32 and len(query["nonce"][0]) >= 32
    assert query["redirect_uri"] == ["http://testserver/api/sso/oidc/callback"]


def test_the_oidc_test_reads_the_provider(app):
    admin = _configure(app)
    reply = admin.post("/api/directory/oidc/test", json={"settings": {"oidc": oidc_settings()}})
    body = reply.json()
    assert body["ok"] and body["redirect_uri"].endswith("/api/sso/oidc/callback"), body


def test_corporate_sign_in_can_be_forbidden_by_the_installation(app, monkeypatch):
    _configure(app)
    monkeypatch.setenv("PLANTCRAFT_CORPORATE_LOGIN", "off")
    _client, reply = _login(app, "ana.lima", "ana-directory-pass")
    assert reply.status_code == 401
    assert TestClient(app).get("/api/sso/methods").json()["oidc"] is False


def test_a_saved_secret_never_goes_to_a_server_it_was_not_typed_for(app):
    # Security audit 2026-10-22: changing the directory's address (or the provider) kept the saved
    # secret, so an admin of PlantCraft could send the company's service password to a server of
    # their own with one test. A new address needs the secret typed again.
    admin = _configure(app)
    rogue = {"ldap": ldap_settings(url="ldaps://rogue.example.test"), "rules": RULES}
    for path in ("/api/directory/ldap/test", "/api/directory"):
        method = admin.post if path.endswith("test") else admin.put
        reply = method(path, json={"settings": rogue})
        assert reply.status_code == 422, (path, reply.text)
        assert "type the password again" in reply.json()["detail"]
    other_account = {"ldap": ldap_settings(bind_dn="cn=other,dc=plant,dc=test"), "rules": RULES}
    assert admin.put("/api/directory", json={"settings": other_account}).status_code == 422
    other_provider = {
        "ldap": ldap_settings(),
        "oidc": oidc_settings(issuer="https://rogue.example.test"),
        "rules": RULES,
    }
    reply = admin.put("/api/directory", json={"settings": other_provider})
    assert reply.status_code == 422, reply.text
    # The same server keeps its secret; a new server with the secret typed again is saved.
    same = {"ldap": ldap_settings(), "oidc": oidc_settings(), "rules": RULES}
    assert admin.put("/api/directory", json={"settings": same}).status_code == 200
    typed = {"settings": rogue, "ldap_bind_password": "typed-again"}
    assert admin.put("/api/directory", json=typed).status_code == 200
