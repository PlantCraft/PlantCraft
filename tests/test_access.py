"""Access profiles and user administration, over the API."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from plantcraft.api.app import create_app
from plantcraft.auth.access import Access

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "senha-forte-1"


def _scenario(tmp_path, monkeypatch):
    scenario = json.loads((ROOT / "scenarios" / "generic_demo.json").read_text())
    scenario["storage"]["sqlite_path"] = str(tmp_path / "workspace.sqlite3")
    scenario["source"]["path"] = str(ROOT / scenario["source"]["path"])
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario))
    monkeypatch.setenv("PLANTCRAFT_SCENARIO", str(path))
    monkeypatch.setenv("PLANTCRAFT_PREWARM_HISTORY", "false")
    monkeypatch.setenv("PLANTCRAFT_APPS", "linkcraft=/link/,histcraft=/hist/")


@pytest.fixture()
def signed(tmp_path, monkeypatch):
    """Sign-in on, signed in as the environment's administrator."""

    _scenario(tmp_path, monkeypatch)
    secret = tmp_path / "secret"
    secret.write_text("admin-secret")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_ENABLED", "true")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_USERNAME", "admin")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE", str(secret))
    with TestClient(create_app()) as client:
        assert (
            client.post(
                "/api/login", json={"username": "admin", "password": "admin-secret"}
            ).status_code
            == 200
        )
        yield client


@pytest.fixture()
def demo(tmp_path, monkeypatch):
    """Sign-in off: the demonstration, with the user switcher."""

    _scenario(tmp_path, monkeypatch)
    monkeypatch.delenv("PLANTCRAFT_BASIC_AUTH_ENABLED", raising=False)
    with TestClient(create_app()) as client:
        yield client


def _create(client, username, level, applications=None):
    response = client.post(
        "/api/users",
        json={
            "username": username,
            "display_name": username.title(),
            "role": "Operação",
            "password": PASSWORD,
            "access_level": level,
            "applications": applications,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _login(app, username, password=PASSWORD):
    client = TestClient(app)
    assert (
        client.post("/api/login", json={"username": username, "password": password}).status_code
        == 200
    )
    return client


def test_access_levels_rank_and_restrict_applications():
    assert Access("admin").allows("linkcraft")
    assert Access("admin", ("histcraft",)).allows("linkcraft")  # administrators see everything
    viewer = Access("viewer", ("histcraft",))
    assert viewer.allows("histcraft") and not viewer.allows("linkcraft")
    assert not viewer.can_edit and Access("editor").can_edit
    assert Access("dashboards").at_least("dashboards") and not Access("dashboards").at_least(
        "viewer"
    )


def test_viewer_reads_but_cannot_change_anything(signed):
    _create(signed, "leitor", "viewer")
    viewer = _login(signed.app, "leitor")
    session = viewer.get("/api/session").json()
    assert session["access"]["level"] == "viewer" and not session["access"]["can_edit"]
    for path in ("/api/home", "/api/assets", "/api/data/sources", "/api/map/format"):
        assert viewer.get(path).status_code == 200, path
    refused = viewer.post("/api/assets", json={"name": "Unit 8", "kind": "unit"})
    assert refused.status_code == 403
    assert refused.json()["detail"] == "Your access is read-only."
    assert viewer.post("/api/asset-kinds", json={"label": "Compressor"}).status_code == 403
    assert viewer.delete("/api/data/sources/scenario").status_code == 403
    # Even checking a plant map file is engineering work.
    preview = viewer.post(
        "/api/map/preview",
        files={"file": ("map.json", b'{"assets": []}', "application/json")},
    )
    assert preview.status_code == 403


def test_launcher_shows_each_person_only_their_apps(signed):
    _create(signed, "qualidade", "editor", ["histcraft"])
    person = _login(signed.app, "qualidade")
    apps = {item["id"]: item["access"] for item in person.get("/api/home").json()["apps"]}
    assert apps == {"linkcraft": None, "histcraft": "editor"}
    token = person.post("/api/v1/auth/token").json()["token"]
    listed = person.get("/api/v1/apps", headers={"Authorization": f"Bearer {token}"}).json()
    assert [item["id"] for item in listed] == ["histcraft"]
    # Access granted before the apps left PlantCraft still counts.
    _create(signed, "legado", "viewer", ["cpm"])
    legacy = _login(signed.app, "legado")
    apps = {item["id"]: item["access"] for item in legacy.get("/api/home").json()["apps"]}
    assert apps == {"linkcraft": "viewer", "histcraft": None}


def test_dashboards_only_person_opens_no_plant_data(signed):
    _create(signed, "sala.controle", "dashboards")
    screen = _login(signed.app, "sala.controle")
    assert screen.get("/api/users").status_code == 200
    for path in ("/api/home", "/api/assets", "/api/data/sources"):
        response = screen.get(path)
        assert response.status_code == 403, path
        assert response.json()["detail"] == "Your access is limited to dashboards."
    token = screen.post("/api/v1/auth/token").json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert screen.get("/api/v1/apps", headers=headers).json() == []
    assert screen.get("/api/v1/assets", headers=headers).status_code == 403


def test_only_administrators_manage_users(signed):
    _create(signed, "engenheira", "editor")
    editor = _login(signed.app, "engenheira")
    assert editor.get("/api/users/accounts").status_code == 403
    assert editor.post("/api/users", json={"username": "x", "display_name": "X"}).status_code == 403

    accounts = signed.get("/api/users/accounts").json()
    assert {item["id"] for item in accounts["levels"]} == {
        "admin",
        "editor",
        "viewer",
        "dashboards",
    }
    engineer = next(item for item in accounts["users"] if item["username"] == "engenheira")
    assert engineer["access_level"] == "editor" and engineer["has_password"]
    # Old demo people with no level: editors when signed in, admin follows is_admin.
    assert (
        next(item for item in accounts["users"] if item["username"] == "marina.costa")[
            "access_level"
        ]
        == "editor"
    )
    assert (
        next(item for item in accounts["users"] if item["username"] == "admin")["access_level"]
        == "admin"
    )
    assert (
        signed.post(
            "/api/users", json={"username": "engenheira", "display_name": "Outra"}
        ).status_code
        == 409
    )
    assert (
        signed.post(
            "/api/users", json={"username": "fraca", "display_name": "F", "password": "123"}
        ).status_code
        == 422
    )
    assert signed.get("/api/users/accounts").json()["users"][-1]["username"] != "fraca"
    bad_app = {"username": "y", "display_name": "Y", "applications": ["nope"]}
    assert signed.post("/api/users", json=bad_app).status_code == 422

    changed = signed.put(
        "/api/users/engenheira",
        json={
            "display_name": "Eng. Ana",
            "role": "Processo",
            "access_level": "viewer",
            "applications": ["linkcraft"],
        },
    ).json()
    assert (changed["display_name"], changed["access_level"], changed["applications"]) == (
        "Eng. Ana",
        "viewer",
        ["linkcraft"],
    )
    # Takes effect at once.
    assert editor.post("/api/assets", json={"name": "Unit 7", "kind": "unit"}).status_code == 403

    assert (
        signed.post(
            "/api/users/engenheira/password", json={"password": "nova-senha-123"}
        ).status_code
        == 200
    )
    assert editor.get("/api/home").status_code == 401  # the old session ended
    _login(signed.app, "engenheira", "nova-senha-123")

    off = {"display_name": "Eng. Ana", "role": "", "access_level": "viewer", "active": False}
    assert signed.put("/api/users/engenheira", json=off).json()["active"] is False
    assert (
        TestClient(signed.app)
        .post("/api/login", json={"username": "engenheira", "password": "nova-senha-123"})
        .status_code
        == 401
    )
    # The environment's administrator is fixed by the installation.
    assert signed.put("/api/users/admin", json={**off, "active": True}).status_code == 422
    # Nobody by that name.
    assert signed.put("/api/users/ziegler", json=off).status_code == 404


def test_demo_without_sign_in_keeps_everyone_admin_until_a_level_is_set(demo):
    session = demo.get("/api/session").json()
    assert (
        session["username"] == "ana.lima"
        and session["access"]["level"] == "admin"
        and session["can_switch_user"]
    )
    _create(demo, "visitante", "viewer")
    assert demo.post("/api/session/switch", json={"username": "visitante"}).status_code == 200
    assert demo.get("/api/session").json()["access"]["level"] == "viewer"
    assert demo.post("/api/assets", json={"name": "Unit 6", "kind": "unit"}).status_code == 403
    assert demo.get("/api/users/accounts").status_code == 403
    assert demo.post("/api/session/switch", json={"username": "marina.costa"}).status_code == 200
    assert demo.post("/api/assets", json={"name": "Unit 6", "kind": "unit"}).status_code == 201


def test_users_command_sets_the_access_level(tmp_path, monkeypatch, capsys):
    from plantcraft.cli import main
    from plantcraft.platform.workspace import Workspace

    _scenario(tmp_path, monkeypatch)
    assert main(["users", "add", "tv.sala", "--name", "TV da sala", "--access", "dashboards"]) == 0
    assert main(["users", "access", "marina.costa", "viewer", "--apps", "linkcraft"]) == 0
    assert main(["users", "list"]) == 0
    out = capsys.readouterr().out
    assert "Dashboards only" in out
    users = Workspace(tmp_path / "workspace.sqlite3").users
    assert users.access("tv.sala") == Access("dashboards")
    assert users.access("marina.costa") == Access("viewer", ("linkcraft",))
    assert main(["users", "admin", "marina.costa"]) == 0
    assert users.access("marina.costa").is_admin
