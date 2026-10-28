"""The Apps page API (/api/apps): upload, catalog, external apps, and the installer's answers.

PlantCraft and the real installer code share folders as in Docker; Docker itself is
``tests/fake_docker.py``. The catalog is a local HTTP server: no test reaches the internet.
"""

from __future__ import annotations

import functools
import http.server
import json
import shutil
import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from processcraft.api.app import create_app
from processcraft.apps import installer as inst
from processcraft.apps import package as pkg
from tests import app_packages as ap

ROOT = Path(__file__).resolve().parents[1]
FAKE = Path(__file__).with_name("fake_docker.py")
ADMIN, PASSWORD = "root", "root-password-123"


class Site:
    """A local web server for the catalog and for external apps' health checks."""

    def __init__(self, folder: Path):
        handler = functools.partial(_Quiet, directory=str(folder))
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


@pytest.fixture()
def world(tmp_path, monkeypatch):
    key, trusted = ap.publisher(tmp_path)
    scenario = json.loads((ROOT / "scenarios" / "generic_demo.json").read_text())
    scenario["storage"]["sqlite_path"] = str(tmp_path / "db" / "workspace.sqlite3")
    scenario["source"]["path"] = str(ROOT / scenario["source"]["path"])
    (tmp_path / "scenario.json").write_text(json.dumps(scenario))
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    (install_dir / "compose.yaml").write_text("services: {}\n")
    requests = tmp_path / "requests"
    secret = tmp_path / "admin.secret"
    secret.write_text(PASSWORD)
    binary = tmp_path / "bin" / "docker"
    binary.parent.mkdir()
    binary.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
    binary.chmod(0o755)
    settings = {
        "PLANTCRAFT_SCENARIO": str(tmp_path / "scenario.json"),
        "PLANTCRAFT_PREWARM_HISTORY": "false",
        "PLANTCRAFT_BASIC_AUTH_ENABLED": "true",
        "PLANTCRAFT_BASIC_AUTH_USERNAME": ADMIN,
        "PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE": str(secret),
        "PLANTCRAFT_APPS": "cpmcraft=/cpm/@0.1.0",
        "PLANTCRAFT_TRUSTED_PUBLISHERS": str(trusted),
        "PLANTCRAFT_APP_REQUESTS": str(requests),
        "PLANTCRAFT_INSTALLER_STATE": str(install_dir / "data" / "installer"),
        "FAKE_DOCKER_DIR": str(tmp_path / "docker"),
    }
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    for name in (
        "PLANTCRAFT_APP_CATALOG_URL",
        "PLANTCRAFT_APP_INSTALL",
        "PLANTCRAFT_APP_MAX_MB",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("PLANTCRAFT_TOKEN_KEY_FILE", raising=False)

    class World:
        def client(self) -> TestClient:
            client = TestClient(create_app(), raise_server_exceptions=False)
            client.__enter__()
            users = client.app.state.runtime.workspace.users
            for username, level in (("eng", "editor"), ("op", "viewer")):
                users.upsert_user(username, username.title(), "")
                users.set_access(username, level, None)
                users.set_password(username, "password-123")
            self.clients.append(client)
            return client

        def installer(self) -> inst.Installer:
            return inst.Installer(
                install_dir,
                requests_dir=requests,
                trusted_dir=trusted,
                helper_image="processcraft-installer:test",
                docker=inst.Docker(str(binary)),
                project="pc-test",
            )

    world = World()
    world.tmp, world.key, world.trusted, world.requests = tmp_path, key, trusted, requests
    world.install_dir, world.clients = install_dir, []
    yield world
    for client in world.clients:
        client.__exit__(None, None, None)


def sign_in(client: TestClient, username: str = ADMIN, password: str = PASSWORD) -> TestClient:
    response = client.post("/api/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return client


def upload(client: TestClient, package: Path):
    return client.post(
        "/api/apps/packages",
        content=package.read_bytes(),
        headers={"Content-Type": "application/octet-stream"},
    )


def audit(client: TestClient, action: str) -> list[dict]:
    rows = client.app.state.runtime.workspace.audit.list(limit=200)
    return [row for row in rows if row["action"] == action]


def app_row(client: TestClient, app_id: str) -> dict | None:
    apps = client.get("/api/apps").json()["apps"]
    return next((item for item in apps if item["id"] == app_id), None)


def install(world, client, package: Path) -> dict:
    preview = upload(client, package)
    assert preview.status_code == 201, preview.text
    confirmed = client.post(f"/api/apps/packages/{preview.json()['upload_id']}/install")
    assert confirmed.status_code == 202, confirmed.text
    world.installer().process_pending()
    return app_row(client, preview.json()["app"]["id"])


# Access ---------------------------------------------------------------------------------------


def test_only_admins_reach_the_apps_page(world):
    client = world.client()
    assert client.get("/api/apps").status_code == 401
    for username in ("eng", "op"):
        sign_in(client, username, "password-123")
        assert client.get("/api/apps").status_code == 403
        assert client.post("/api/apps/packages", content=b"x").status_code == 403
        assert (
            client.post(
                "/api/apps/external", json={"id": "xone", "name": "X", "url": "/xone/"}
            ).status_code
            == 403
        )
        assert client.post("/api/apps/hello/uninstall").status_code == 403
        client.post("/api/logout")


def test_overview_says_what_is_on_and_lists_configured_apps(world):
    client = sign_in(world.client())
    data = client.get("/api/apps").json()
    assert data["install_enabled"] is True
    assert data["catalog"] == {"enabled": False, "configured": False, "switch": False, "url": None}
    assert data["installer"]["online"] is False
    assert data["trusted_publishers"] == ["testpub"]
    assert [(a["id"], a["origin"]) for a in data["apps"]] == [("cpmcraft", "configured")]
    # What an app adds shows once it told PlantCraft (it sends it when it starts).
    assert data["apps"][0]["adds"] is None
    from plantcraft_sdk.contributes import ContributionsIn

    client.app.state.runtime.contributions.put(
        "cpmcraft",
        ContributionsIn.model_validate(
            {"contributes": {"widgets": [{"id": "w", "title": "W"}], "queue": True, "x": []}}
        ),
    )
    [row] = client.get("/api/apps").json()["apps"]
    assert row["adds"] == {"widgets": 1, "queue": 1} and row["adds_unknown"] == ["x"]
    catalog = client.get("/api/apps/catalog").json()
    assert catalog["enabled"] is False and "PLANTCRAFT_APP_CATALOG_URL" in catalog["how"]


# Install from a file ----------------------------------------------------------------------------


def test_upload_shows_what_the_package_holds_before_anything_runs(world):
    client = sign_in(world.client())
    package = ap.build(world.tmp / "b", world.key)
    response = upload(client, package)
    assert response.status_code == 201, response.text
    preview = response.json()
    app = preview["app"]
    assert (app["id"], app["version"], app["prefix"]) == ("hello", "0.1.0", "/hello/")
    assert app["publisher"]["id"] == "testpub" and app["publisher"]["key_id"]
    assert [p["id"] for p in app["permissions"]] == ["read.assets", "read.signals"]
    assert app["summary"] == "A test app." and app["description"].startswith("A test app")
    assert app["plant_write"] is False and app["outbound"] == []
    assert all(p["label"] for p in app["permissions"])
    assert preview["sbom"]["packages"] == 2 and preview["sbom"]["components"][0]["name"] == "python"
    assert preview["replaces"] is None and preview["origin"] == "package"
    sbom = client.get(f"/api/apps/packages/{preview['upload_id']}/sbom")
    assert sbom.status_code == 200 and sbom.json()["spdxVersion"] == "SPDX-2.3"
    assert not list(world.requests.glob("*.json")), (
        "nothing reaches the installer before confirming"
    )
    assert audit(client, "app.package.verified")[0]["subject"] == "app:hello"
    assert client.delete(f"/api/apps/packages/{preview['upload_id']}").json() == {"ok": True}
    assert client.get(f"/api/apps/packages/{preview['upload_id']}").status_code == 404


@pytest.mark.parametrize("body", [b"", b"not a package", b"{}", b"\x1f\x8b junk"])
def test_junk_uploads_are_refused_and_audited(world, body):
    client = sign_in(world.client())
    response = client.post("/api/apps/packages", content=body)
    assert response.status_code == 422 and "refused" in response.json()["detail"]
    assert audit(client, "app.package.rejected")
    assert list((world.requests / "uploads").glob("*")) == []


def test_a_tampered_or_unknown_package_is_refused(world):
    client = sign_in(world.client())
    good = ap.build(world.tmp / "b", world.key)
    members = ap.members_of(good)
    members["manifest.json"] = members["manifest.json"].replace(b"/hello/", b"/hallo/")
    tampered = ap.raw(world.tmp / "t.pcapp", list(members.items()))
    assert "signature" in upload(client, tampered).json()["detail"]
    other, _ = ap.publisher(world.tmp / "o", "stranger")
    foreign = ap.build(world.tmp / "f", other, app={"publisher": "stranger"})
    assert "unknown publisher" in upload(client, foreign).json()["detail"]


def test_an_upload_larger_than_allowed_is_refused(world, monkeypatch):
    monkeypatch.setenv("PLANTCRAFT_APP_MAX_MB", "0")
    client = sign_in(world.client())
    response = upload(client, ap.build(world.tmp / "b", world.key))
    assert response.status_code in {413, 422} and "larger than" in response.json()["detail"]
    big = client.post(
        "/api/apps/packages",
        content=b"x" * (128 * 1024),
        headers={"Content-Length": str(128 * 1024)},
    )
    assert big.status_code == 413


def test_confirm_installs_through_the_installer_and_the_launcher_lists_it(world):
    client = sign_in(world.client())
    package = ap.build(world.tmp / "b", world.key)
    preview = upload(client, package).json()
    confirmed = client.post(f"/api/apps/packages/{preview['upload_id']}/install").json()
    assert confirmed["status"] == "installing"
    request = json.loads((world.requests / f"{confirmed['request_id']}.json").read_text())
    assert request["action"] == "install" and request["requested_by"] == ADMIN
    assert (world.requests / f"{confirmed['request_id']}.pcapp").is_file()
    assert "hello" not in [a["id"] for a in client.get("/api/v1/apps").json()]
    world.installer().process_pending()
    row = app_row(client, "hello")
    assert row["status"] == "running" and row["version"] == "0.1.0" and row["origin"] == "package"
    assert row["publisher"]["id"] == "testpub" and row["has_sbom"]
    assert not list(world.requests.glob(f"{confirmed['request_id']}.*")), "request files cleaned"
    launcher = {a["id"]: a for a in client.get("/api/home").json()["apps"]}
    assert launcher["hello"]["url"] == "/hello/" and launcher["hello"]["access"] == "editor"
    # A token lists the apps that existed when it was issued; the browser renews it.
    assert client.post("/api/v1/auth/token").status_code == 200
    v1 = {a["id"]: a for a in client.get("/api/v1/apps").json()}
    assert set(v1) == {"cpmcraft", "hello"} and v1["hello"]["version"] == "0.1.0"
    assert client.get("/api/apps/hello/sbom").json()["name"] == "hello"
    done = audit(client, "app.install")
    assert done and done[0]["detail"]["result"] == "done" and done[0]["username"] == ADMIN
    assert audit(client, "app.install.request")[0]["detail"]["sha256"] == preview["app"]["sha256"]


def test_upgrade_rollback_and_uninstall_through_the_page(world):
    client = sign_in(world.client())
    install(world, client, ap.build(world.tmp / "v1", world.key, version="0.1.0"))
    second = upload(client, ap.build(world.tmp / "v2", world.key, version="0.2.0")).json()
    assert second["replaces"] == "0.1.0" and second["warnings"]
    client.post(f"/api/apps/packages/{second['upload_id']}/install")
    assert app_row(client, "hello")["status"] == "updating"
    assert client.post("/api/apps/hello/uninstall").status_code == 409, "one request at a time"
    world.installer().process_pending()
    row = app_row(client, "hello")
    assert (row["version"], row["previous_version"]) == ("0.2.0", "0.1.0")
    assert client.post("/api/apps/hello/rollback").status_code == 202
    world.installer().process_pending()
    row = app_row(client, "hello")
    assert (row["version"], row["previous_version"], row["status"]) == ("0.1.0", "0.2.0", "running")
    assert client.post("/api/apps/hello/uninstall").status_code == 202
    world.installer().process_pending()
    assert app_row(client, "hello") is None
    assert "hello" not in [a["id"] for a in client.get("/api/v1/apps").json()]
    for action in (
        "app.rollback",
        "app.uninstall",
        "app.rollback.request",
        "app.uninstall.request",
    ):
        assert audit(client, action), action


def test_a_failed_install_is_shown_with_the_reason(world, monkeypatch):
    client = sign_in(world.client())
    monkeypatch.setenv("FAKE_DOCKER_FAIL", "up:app-hello")
    row = install(world, client, ap.build(world.tmp / "b", world.key))
    assert row["status"] == "failed" and "did not start" in row["message"]
    assert "hello" not in [a["id"] for a in client.get("/api/home").json()["apps"]]
    assert audit(client, "app.install")[0]["detail"]["result"] == "failed"


def test_an_app_key_is_issued_once_and_never_shown(world):
    client = sign_in(world.client())
    row = install(world, client, ap.build(world.tmp / "b", world.key))
    assert row["status"] == "running" and row["needs_key"] is False
    keys = [k for k in client.get("/api/app-keys").json()["keys"] if k["app_id"] == "hello"]
    assert len(keys) == 1 and keys[0]["active"]
    secret = (
        world.install_dir / "data" / "installer" / "secrets" / "hello" / "app-key"
    ).read_text()
    assert secret.startswith("pck_")
    assert secret.strip() not in json.dumps(client.get("/api/apps").json())
    install(world, client, ap.build(world.tmp / "v2", world.key, version="0.2.0"))
    keys = [k for k in client.get("/api/app-keys").json()["keys"] if k["app_id"] == "hello"]
    assert len(keys) == 1, "an upgrade keeps the app's key"
    client.post("/api/apps/hello/uninstall")
    world.installer().process_pending()
    app_row(client, "hello")
    keys = [k for k in client.get("/api/app-keys").json()["keys"] if k["app_id"] == "hello"]
    assert not keys[0]["active"], "an uninstalled app's key is revoked"


@pytest.mark.parametrize(
    ("fields", "detail"),
    [
        (
            {"app_id": "cpmcraft", "runtime": {"prefix": "/cpm/", "port": 8070, "uid": 10002,
                                               "image": "cpmcraft"}},
            "PLANTCRAFT_APPS",
        ),
        ({"app_id": "other", "runtime": {"prefix": "/cpm/"}}, "cpmcraft in the suite table"),
        ({"app_id": "other", "runtime": {"uid": 10007}}, "datacraft in the suite table"),
    ],
)  # fmt: skip
def test_ids_and_prefixes_already_taken_are_refused(world, fields, detail):
    client = sign_in(world.client())
    if "suite table" in detail:
        # build_package refuses it as well: a hostile publisher signs one by hand.
        with pytest.raises(pkg.PackageError, match="suite table"):
            ap.build(world.tmp / "x", world.key, **fields)
        good = ap.build(world.tmp / "b", world.key, app_id=fields["app_id"])
        package = ap.resign(
            good,
            world.key,
            world.tmp / "r.pcapp",
            lambda m: m["runtime"].update(fields["runtime"]),
        )
    else:
        package = ap.build(world.tmp / "b", world.key, **fields)
    response = upload(client, package)
    assert response.status_code in {409, 422} and detail in response.json()["detail"]
    assert list((world.requests / "uploads").glob("*")) == []


def test_a_prefix_of_an_external_app_is_taken(world):
    client = sign_in(world.client())
    assert (
        client.post(
            "/api/apps/external", json={"id": "legacy", "name": "Legacy", "url": "/hello/"}
        ).status_code
        == 201
    )
    response = upload(client, ap.build(world.tmp / "b", world.key))
    assert response.status_code == 409 and "legacy" in response.json()["detail"]
    clash = upload(
        client,
        ap.build(world.tmp / "c", world.key, app_id="legacy", runtime={"prefix": "/legacy/"}),
    )
    assert clash.status_code == 409 and "external" in clash.json()["detail"]


def test_installs_can_be_switched_off(world, monkeypatch):
    monkeypatch.setenv("PLANTCRAFT_APP_INSTALL", "off")
    client = sign_in(world.client())
    assert client.get("/api/apps").json()["install_enabled"] is False
    response = upload(client, ap.build(world.tmp / "b", world.key))
    assert response.status_code == 409 and "switched off" in response.json()["detail"]
    assert (
        client.post(
            "/api/apps/external", json={"id": "wiki", "name": "Wiki", "url": "/wiki/"}
        ).status_code
        == 201
    )


# The command line --------------------------------------------------------------------------------


def test_the_launcher_says_which_asset_types_each_app_shows(world):
    """The asset page links <prefix>assets/<id> of the apps that cover the asset's type."""

    client = sign_in(world.client())
    install(world, client, ap.build(world.tmp / "b", world.key, requires={"asset_types": ["loop"]}))
    install(world, client, ap.build(world.tmp / "c", world.key, app_id="other"))
    launcher = {a["id"]: a for a in client.get("/api/home").json()["apps"]}
    assert launcher["hello"]["asset_types"] == ["loop"]
    assert launcher["other"]["asset_types"] == [], "a manifest without asset_types shows none"
    assert launcher["cpmcraft"]["asset_types"] is None, "PLANTCRAFT_APPS: manifest unknown"
    # The installer's record carries them too (apps added from the command line).
    package = ap.build(
        world.tmp / "d", world.key, app_id="third", requires={"asset_types": ["valve"]}
    )
    world.installer().handle(
        {"request_id": "e" * 32, "action": "install", "app_id": None, "requested_by": "cli:x"},
        package,
    )
    assert app_row(client, "third")["status"] == "running"  # the Apps page reads the installer
    launcher = {a["id"]: a for a in client.get("/api/home").json()["apps"]}
    assert launcher["third"]["asset_types"] == ["valve"]


def test_apps_added_and_removed_from_the_command_line_show_up(world):
    client = sign_in(world.client())
    package = ap.build(world.tmp / "b", world.key)
    installer = world.installer()
    result = installer.handle(
        {
            "request_id": "c" * 32,
            "action": "install",
            "app_id": None,
            "requested_by": "cli:operator",
        },
        package,
    )
    assert result["state"] == "done"
    row = app_row(client, "hello")
    assert row["status"] == "running" and row["installed_by"] == "cli:operator"
    assert client.get("/api/apps/hello/sbom").status_code == 200
    assert audit(client, "app.install")[0]["username"] == "cli:operator"
    installer.handle(
        {"request_id": "d" * 32, "action": "uninstall", "app_id": "hello", "requested_by": "cli:x"}
    )
    assert app_row(client, "hello") is None


# External apps -----------------------------------------------------------------------------------


def test_register_an_external_app_with_its_health(world):
    client = sign_in(world.client())
    site_dir = world.tmp / "site"
    site_dir.mkdir()
    (site_dir / "index.html").write_text("ok")
    site = Site(site_dir)
    try:
        response = client.post(
            "/api/apps/external",
            json={"id": "historian", "name": "Historian", "url": site.url, "version": "2.1.0"},
        )
        assert response.status_code == 201, response.text
        app = response.json()
        assert app["origin"] == "external" and app["status"] == "external"
        assert app["health"]["ok"] is True and app["health"]["status"] == 200
        assert "did not verify" in app["warning"] and app["app_key"].startswith("pck_")
        keys = [k for k in client.get("/api/app-keys").json()["keys"] if k["app_id"] == "historian"]
        assert len(keys) == 1 and keys[0]["active"], "an external app gets an app key"
        assert app["app_key"] not in json.dumps(client.get("/api/apps").json())
        client.post("/api/v1/auth/token")
        listed = {a["id"]: a for a in client.get("/api/v1/apps").json()}
        assert listed["historian"]["url"] == site.url and listed["historian"]["version"] == "2.1.0"
    finally:
        site.close()
    check = client.post("/api/apps/historian/check").json()
    assert check["health"]["ok"] is False
    assert client.post("/api/apps/historian/rollback").status_code == 409
    assert client.post("/api/apps/historian/uninstall").status_code == 202
    assert "historian" not in [a["id"] for a in client.get("/api/v1/apps").json()]
    keys = [k for k in client.get("/api/app-keys").json()["keys"] if k["app_id"] == "historian"]
    assert not keys[0]["active"], "removing it revokes its key"
    assert audit(client, "app.external.register") and audit(client, "app.external.remove")


@pytest.mark.parametrize(
    "payload",
    [
        {"id": "xone", "name": "X", "url": "javascript:alert(1)"},
        {"id": "xone", "name": "X", "url": "ftp://files.example/"},
        {"id": "xone", "name": "X", "url": "http://user:secret@host.example/"},
        {"id": "xone", "name": "X", "url": "/api/"},
        {"id": "xone", "name": "X", "url": "/a b/"},
        {"id": "xone", "name": "X", "url": "/cpm/"},
        {"id": "processcraft", "name": "X", "url": "/pc/"},
        {"id": "cpmcraft", "name": "X", "url": "/other/"},
        {"id": "Bad Id", "name": "X", "url": "/xone/"},
        {"id": "xone", "name": "\u0000", "url": "/xone/"},
        {"id": "xone", "name": "X", "url": "/xone/", "version": "latest"},
    ],
)
def test_external_registration_checks_its_input(world, payload):
    client = sign_in(world.client())
    response = client.post("/api/apps/external", json=payload)
    assert response.status_code in {409, 422}, response.text
    assert app_row(client, payload["id"]) is None or payload["id"] == "cpmcraft"


# Catalog -----------------------------------------------------------------------------------------


@pytest.fixture()
def catalog(world, monkeypatch):
    folder = world.tmp / "catalog"
    package = ap.build(world.tmp / "b", world.key, compress=True)
    folder.mkdir()
    shutil.copy(package, folder / package.name)
    pkg.build_index([folder / package.name], world.key, "testpub", folder)
    site = Site(folder)
    monkeypatch.setenv("PLANTCRAFT_APP_CATALOG_URL", site.url)
    yield folder
    site.close()


def catalog_on(client: TestClient) -> TestClient:
    response = client.put("/api/apps/catalog", json={"enabled": True})
    assert response.status_code == 200 and response.json()["enabled"] is True, response.text
    return client


def test_the_catalog_is_off_until_an_admin_turns_it_on(world, catalog):
    client = sign_in(world.client())
    listed = client.get("/api/apps/catalog").json()
    assert listed == {"enabled": False, "configured": True, "apps": [], "how": listed["how"]}
    assert client.post("/api/apps/catalog/hello/download").status_code == 409
    catalog_on(client)
    assert audit(client, "app.catalog.switch")[0]["detail"] == {"enabled": True}
    assert client.get("/api/apps/catalog").json()["enabled"] is True
    off = client.put("/api/apps/catalog", json={"enabled": False}).json()
    assert off["enabled"] is False and off["switch"] is False
    for username in ("eng", "op"):
        other = sign_in(world.client(), username, "password-123")
        assert other.put("/api/apps/catalog", json={"enabled": True}).status_code == 403


def test_the_catalog_cannot_be_turned_on_without_an_address(world):
    client = sign_in(world.client())
    response = client.put("/api/apps/catalog", json={"enabled": True})
    assert response.status_code == 409 and "PLANTCRAFT_APP_CATALOG_URL" in response.json()["detail"]
    assert client.put("/api/apps/catalog", json={"enabled": "yes please"}).status_code == 422


def test_the_catalog_lists_downloads_and_installs(world, catalog):
    client = catalog_on(sign_in(world.client()))
    listed = client.get("/api/apps/catalog").json()
    assert listed["enabled"] is True
    assert [(a["id"], a["version"], a["installed_version"]) for a in listed["apps"]] == [
        ("hello", "0.1.0", None)
    ]
    preview = client.post("/api/apps/catalog/hello/download")
    assert preview.status_code == 201, preview.text
    assert preview.json()["origin"] == "catalog"
    client.post(f"/api/apps/packages/{preview.json()['upload_id']}/install")
    world.installer().process_pending()
    row = app_row(client, "hello")
    assert row["origin"] == "catalog" and row["status"] == "running"
    assert audit(client, "app.catalog.download")
    assert client.post("/api/apps/catalog/nothing/download").status_code == 404


def test_a_catalog_that_does_not_verify_is_refused(world, catalog):
    client = catalog_on(sign_in(world.client()))
    index = catalog / "index.json"
    index.write_bytes(index.read_bytes().replace(b"A test app.", b"A test app!"))
    response = client.get("/api/apps/catalog")
    assert response.status_code == 502 and "signature" in response.json()["detail"]


def test_a_catalog_package_that_differs_from_the_index_is_refused(world, catalog):
    client = catalog_on(sign_in(world.client()))
    (package,) = catalog.glob("*.pcapp")
    data = bytearray(package.read_bytes())
    data[-1] ^= 1
    package.write_bytes(bytes(data))
    response = client.post("/api/apps/catalog/hello/download")
    assert response.status_code == 502 and "SHA-256" in response.json()["detail"]
    package.write_bytes(bytes(data) + b"\0")
    response = client.post("/api/apps/catalog/hello/download")
    assert response.status_code == 502 and "larger than the catalog" in response.json()["detail"]
    assert list((world.requests / "uploads").glob("*")) == []


def test_an_unreachable_catalog_is_a_clear_error(world, monkeypatch):
    monkeypatch.setenv("PLANTCRAFT_APP_CATALOG_URL", "http://127.0.0.1:9/catalog/")
    client = catalog_on(sign_in(world.client()))
    response = client.get("/api/apps/catalog")
    assert response.status_code == 502 and "cannot reach" in response.json()["detail"]


# Junk ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("ident", ["x" * 300, "..%2F..%2Fetc", "%00", "ç☃", "-1"])
def test_junk_identifiers_answer_4xx(world, ident):
    client = sign_in(world.client())
    for method, path in (
        ("GET", f"/api/apps/packages/{ident}"),
        ("POST", f"/api/apps/packages/{ident}/install"),
        ("DELETE", f"/api/apps/packages/{ident}"),
        ("POST", f"/api/apps/{ident}/uninstall"),
        ("POST", f"/api/apps/{ident}/rollback"),
        ("POST", f"/api/apps/{ident}/key"),
        ("POST", f"/api/apps/{ident}/check"),
        ("GET", f"/api/apps/{ident}/sbom"),
    ):
        response = client.request(method, path)
        assert 400 <= response.status_code < 500, (method, path, response.status_code)


def test_the_installer_outcome_files_are_read_defensively(world):
    client = sign_in(world.client())
    status = world.install_dir / "data" / "installer" / "status"
    (status / "requests").mkdir(parents=True)
    (status / "installed.json").write_text("{not json")
    (status / "heartbeat.json").write_text('{"at": "yesterday"}')
    assert client.get("/api/apps").status_code == 200
    (status / "installed.json").write_text(
        json.dumps({"apps": [{"app_id": "../x"}, {"app_id": "ok", "prefix": "/api/../"}, "junk"]})
    )
    data = client.get("/api/apps").json()
    assert [a["id"] for a in data["apps"]] == ["cpmcraft"]
