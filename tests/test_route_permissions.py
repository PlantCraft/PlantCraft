"""Every route's permission, walked from the application itself (gap G10).

A new route is covered without editing this file: with sign-in on, nobody without a session gets
past any interface route, a viewer never writes, an editor never touches admin-only routes, and
the routers that skip the access guard are exactly the ones meant to (sign-in, single sign-on and
API v1).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from plantcraft.api.app import PUBLIC, ROUTERS, create_app

ROOT = Path(__file__).resolve().parents[1]
ADMIN_PASSWORD = "Sup3rSecretAdmin"

# Routes of the guarded routers that answer without a session, each with its reason.
OPEN_WITHOUT_SESSION: dict[tuple[str, str], str] = {
    ("GET", "/healthz"): "the container's health check; answers only that the server is up",
}

# Writes a viewer may make: conversations and marking what they read (``open_to("viewer")``).
VIEWER_WRITES = re.compile(
    r"^/api/(messages|actions/\{[^}]+\}/comments|notifications|session|logout|login)"
)


def _routes(_app) -> list[tuple[str, str, APIRoute]]:
    # Walked from the routers the application mounts (``ROUTERS``), with no prefix of their own.
    found = []
    for module in ROUTERS:
        if module in PUBLIC:
            continue
        for route in module.router.routes:
            if not isinstance(route, APIRoute):
                continue
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                found.append((method, route.path, route))
    return found


def _concrete(path: str) -> str:
    # Any value fills a path parameter: the check under test runs before the lookup.
    return re.sub(r"\{[^}:]+(:path)?\}", "1", path)


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
    for name, level in (("vera", "viewer"), ("eddie", "editor")):
        users.upsert_user(name, name.title(), "Operations")
        users.set_password(name, f"{name}-strong-password")
        users.set_access(name, level, None)
    return application


def _login(app, username: str, password: str) -> TestClient:
    client = TestClient(app)
    reply = client.post("/api/login", json={"username": username, "password": password})
    assert reply.status_code == 200, reply.text
    return client


def test_only_sign_in_and_api_v1_skip_the_access_guard():
    names = {module.__name__.rsplit(".", 1)[-1] for module in PUBLIC}
    # sso: single sign-on with the company's provider, and what the sign-in page offers.
    # mcp: the MCP server checks its own access tokens (docs/assistant-access.md).
    # notebooks_pair: the Notebooks app trades a one-time code for its token (it is the proof).
    # compute_worker: the compute workers prove themselves with their own credential.
    # demo: a public demo's visits, entered before any session (docs/public-demo.md).
    assert names == {
        "session", "demo", "sso", "v1", "v1_links", "v1_llm", "v1_assistant", "v1_people",
        "v1_notebooks", "v1_objects", "v1_desk", "v1_explore", "mcp", "notebooks_pair",
        "v1_compute", "compute_worker", "v1_tools",
    }  # fmt: skip
    assert set(PUBLIC) <= set(ROUTERS)


def test_the_walk_sees_the_interface_routes(app):
    # Guards the tests below from passing on an empty walk.
    walked = {(method, path) for method, path, _route in _routes(app)}
    assert len(walked) > 40
    assert ("POST", "/api/assets") in walked and ("GET", "/api/home") in walked


def test_no_interface_route_answers_without_a_session(app):
    client = TestClient(app)
    leaks = []
    with client:
        for method, path, _route in _routes(app):
            if (method, path) in OPEN_WITHOUT_SESSION:
                continue
            reply = client.request(method, _concrete(path), json={})
            if reply.status_code != 401:
                leaks.append(f"{method} {path} -> {reply.status_code}")
    assert not leaks, "routes answering without a session:\n" + "\n".join(leaks)


def test_a_viewer_never_writes(app):
    with TestClient(app):
        viewer = _login(app, "vera", "vera-strong-password")
        leaks = []
        for method, path, route in _routes(app):
            if method == "GET" or VIEWER_WRITES.match(path):
                continue
            if getattr(route.endpoint, "min_access", None) in {"viewer", "dashboards"}:
                continue
            reply = viewer.request(method, _concrete(path), json={})
            if reply.status_code != 403:
                leaks.append(f"{method} {path} -> {reply.status_code}")
        assert not leaks, "writes a viewer got past:\n" + "\n".join(leaks)


def test_an_editor_never_reaches_admin_routes(app):
    admin_only = [
        ("GET", "/api/users/accounts"),
        ("POST", "/api/users"),
        ("POST", "/api/app-keys"),
        ("POST", "/api/data/sources"),
        ("POST", "/api/assets"),
        ("GET", "/api/specialists"),
        ("POST", "/api/groups"),
        ("GET", "/api/mail"),
        ("PUT", "/api/mail"),
        ("POST", "/api/mail/test"),
        ("GET", "/api/desk/settings"),
        ("PUT", "/api/desk/settings"),
        ("GET", "/api/audit"),
        ("GET", "/api/audit.csv"),
    ]
    with TestClient(app):
        editor = _login(app, "eddie", "eddie-strong-password")
        for method, path in admin_only:
            reply = editor.request(method, path, json={})
            assert reply.status_code == 403, f"{method} {path} -> {reply.status_code}"


@pytest.mark.parametrize(
    ("host", "sign_in", "flag", "starts"),
    [
        ("127.0.0.1", False, False, True),
        ("localhost", False, False, True),
        ("0.0.0.0", False, False, False),
        ("10.0.0.5", False, False, False),
        ("0.0.0.0", False, True, True),
        ("0.0.0.0", True, False, True),
    ],
)
def test_the_server_refuses_a_network_address_without_sign_in(
    tmp_path, monkeypatch, host, sign_in, flag, starts
):
    from plantcraft import cli

    monkeypatch.delenv("PLANTCRAFT_BASIC_AUTH_ENABLED", raising=False)
    if sign_in:
        secret = tmp_path / "admin-password"
        secret.write_text(ADMIN_PASSWORD)
        monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_ENABLED", "true")
        monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_USERNAME", "admin")
        monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE", str(secret))
    refusal = cli._refuse_open_network(host, flag)
    assert (refusal is None) is starts
    if not starts:
        assert "--no-sign-in" in refusal
        assert cli.main(["--host", host]) == 2
