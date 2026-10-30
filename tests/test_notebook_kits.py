"""Notebooks kits: Python and JupyterLab for a person's own computer (docs/en/notebooks.md).

The download is a second switch; the zip goes out with this server's address (and its local CA)
added and never a token; the kit's token lasts 90 days; API v1 lists the examples and the
person's notebooks for the kit, which copies them without overwriting what the person edited.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from plantcraft.notebooks import kits
from tests.test_notebooks import _routed, _turn_on, dist  # noqa: F401
from tests.test_route_permissions import ADMIN_PASSWORD, _login, app  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "notebooks" / "python"))
import plantcraft_notebook as pc  # noqa: E402
from plantcraft_notebook import kit  # noqa: E402

KIT = {
    "PlantCraft Notebooks/python/bin/python3": b"\x7fELF" + b"x" * 5000,
    "PlantCraft Notebooks/Open notebooks.sh": b"#!/bin/sh\n",
    "PlantCraft Notebooks/kit.json": b'{"kit": "linux-x64", "version": "0.1.0-old"}',
}


@pytest.fixture(autouse=True)
def app_folder(tmp_path, monkeypatch):
    """The Notebooks app's own folder and the person's Documents, never this machine's."""

    folder = tmp_path / "app-folder"
    monkeypatch.setenv("PLANTCRAFT_APP_FOLDER", str(folder))
    monkeypatch.setenv("PLANTCRAFT_NOTEBOOK_FOLDER", str(tmp_path / "documents"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("PLANTCRAFT_ASSUME_YES", "1")
    return folder


@pytest.fixture()
def shelf(tmp_path, monkeypatch):
    """A kits folder as the bundle leaves it: one zip and kits.json."""

    folder = tmp_path / "kits"
    folder.mkdir()
    with zipfile.ZipFile(folder / "plantcraft-notebooks-linux-x64.zip", "w") as archive:
        for name, data in KIT.items():
            archive.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
    listing = {
        "version": "0.1.0-abc",
        "kits": [
            {
                "id": "linux-x64",
                "system": "Linux",
                "arch": "x64",
                "file": "plantcraft-notebooks-linux-x64.zip",
                "bytes": 1,
            },
            # Listed, but its zip is not there: not offered.
            {"id": "windows-x64", "system": "Windows", "arch": "x64", "file": "missing.zip"},
        ],
    }
    (folder / "kits.json").write_text(json.dumps(listing))
    monkeypatch.setenv("PLANTCRAFT_NOTEBOOK_KITS", str(folder))
    ca = tmp_path / "local-ca-root.crt"
    ca.write_text("-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n")
    monkeypatch.setenv("PLANTCRAFT_LOCAL_CA", str(ca))
    return folder


def test_files_added_to_a_zip_keep_every_entry_before_them(shelf):
    path = shelf / "plantcraft-notebooks-linux-x64.zip"
    length, body = kits.personalized(path, {"plantcraft.json": b'{"url": "https://plant"}'})
    data = b"".join(body)
    assert len(data) == length
    # The kit's bytes go out as they are; only the directory at the end is new.
    original = path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(original)) as before:
        start = before.start_dir
    assert data[:start] == original[:start]
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.testzip() is None
        assert archive.read("PlantCraft Notebooks/plantcraft.json") == b'{"url": "https://plant"}'
        for name, content in KIT.items():
            assert archive.read(name) == content


def test_the_kit_comes_with_notebooks_until_an_administrator_takes_it_away(app, dist, shelf):  # noqa: F811
    """One switch: Notebooks on offers the kit the installation has."""

    with TestClient(app):
        admin = _turn_on(app)
        vera = _login(app, "vera", "vera-strong-password")
        offered = vera.get("/api/notebooks").json()["kits"]
        # As long as the administrator lets a token last (30 days by default).
        assert offered["enabled"] is True and offered["token_days"] == 30
        assert [item["id"] for item in offered["kits"]] == ["linux-x64"]
        url = offered["kits"][0]["url"]
        assert vera.put("/api/notebooks/settings", json={"kit_enabled": False}).status_code == 403
        assert admin.put("/api/notebooks/settings", json={"kit_enabled": False}).status_code == 200
        assert vera.get(url).status_code == 404
        assert vera.get("/api/notebooks").json()["kits"]["enabled"] is False
        assert admin.put("/api/notebooks/settings", json={"kit_enabled": True}).status_code == 200
        # Turning the kits off and on keeps Notebooks on.
        assert vera.get("/api/notebooks").json()["enabled"] is True
        answer = vera.get(url, headers={"x-forwarded-proto": "https", "host": "plant.example"})
        assert answer.status_code == 200
        assert answer.headers["content-type"] == "application/zip"
        assert int(answer.headers["content-length"]) == len(answer.content)
        with zipfile.ZipFile(io.BytesIO(answer.content)) as archive:
            names = archive.namelist()
            settings = json.loads(archive.read("PlantCraft Notebooks/plantcraft.json"))
            ca = archive.read("PlantCraft Notebooks/plantcraft-ca.pem")
        assert settings == {
            "url": "https://plant.example",
            "server_kit_version": "0.1.0-abc",
            "ca": "plantcraft-ca.pem",
        }
        assert b"BEGIN CERTIFICATE" in ca
        # Never a token in the zip.
        assert not any("token" in name for name in names)
        assert vera.get("/api/notebooks/kits/windows-x64.zip").status_code == 404
        assert vera.get("/api/notebooks/kits/..%2Fkits.zip").status_code == 404
        rows = admin.get("/api/audit", params={"action": "notebooks.kit_download"}).json()["rows"]
    assert rows[0]["subject"] == "kit:linux-x64"


def test_without_kits_the_page_offers_the_package_only(app, dist, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("PLANTCRAFT_NOTEBOOK_KITS", str(tmp_path / "none"))
    with TestClient(app):
        _turn_on(app)
        vera = _login(app, "vera", "vera-strong-password")
        assert vera.get("/api/notebooks").json()["kits"] is None


def test_a_kit_token_lasts_the_admins_limit_and_says_when_it_ends(app, dist, shelf):  # noqa: F811
    with TestClient(app):
        vera = _login(app, "vera", "vera-strong-password")
        assert vera.post("/api/notebooks/token").status_code == 409
        _turn_on(app)
        created = vera.post("/api/notebooks/token")
        assert created.status_code == 201, created.text
        token = created.json()["token"]
        expires = datetime.fromisoformat(created.json()["expires_at"].replace("Z", "+00:00"))
        left = expires - datetime.now(timezone.utc)
        # Never past the administrator's limit for tokens (30 days by default; audit 2026-10-26).
        assert timedelta(days=29) < left <= timedelta(days=30)
        access = app.state.runtime.workspace.assistant_access
        access.save_settings(enabled=access.enabled(), max_days=365, actor="admin")
        assert vera.get("/api/notebooks").json()["kits"]["token_days"] == 90
        longer = vera.post("/api/notebooks/token").json()
        left = datetime.fromisoformat(longer["expires_at"].replace("Z", "+00:00")) - datetime.now(
            timezone.utc
        )
        assert timedelta(days=89) < left <= timedelta(days=90)
        reader = TestClient(app)
        listing = reader.get("/api/v1/notebooks", headers={"Authorization": f"Bearer {token}"})
        assert listing.json()["token_expires_at"] == created.json()["expires_at"]
        assert kit.expiry_notice(listing.json()) == ""
        soon = (datetime.now(timezone.utc) + timedelta(days=3, hours=1)).isoformat()
        assert "expires in 3 days" in kit.expiry_notice({"token_expires_at": soon})
        # A session has no end of its own.
        assert vera.get("/api/v1/notebooks").json()["token_expires_at"] is None


def test_the_kit_copies_the_notebooks_and_keeps_what_the_person_edited(
    app,  # noqa: F811
    dist,  # noqa: F811
    shelf,
    tmp_path,
    monkeypatch,
):
    with TestClient(app):
        _turn_on(app)
        vera = _login(app, "vera", "vera-strong-password")
        signal = vera.get("/api/v1/signals").json()[0]["id"]
        made = vera.post("/api/notebooks", json={"kind": "series", "signals": [signal]}).json()
        token = vera.post("/api/notebooks/token").json()["token"]
        home = tmp_path / "kit"
        home.mkdir()
        (home / "kit.json").write_text(json.dumps({"kit": "linux-x64", "version": "0.1.0-old"}))
        (home / "plantcraft.json").write_text(json.dumps({"url": "http://testserver"}))
        monkeypatch.setenv("PLANTCRAFT_KIT", str(home))
        monkeypatch.setattr(kit, "_vault", lambda: None)
        assert kit.save_token("http://testserver", token) == "file"
        if os.name == "posix":
            assert (home / kit.TOKEN_FILE).stat().st_mode & 0o077 == 0
        assert kit.stored_token("http://testserver") == token
        monkeypatch.setattr(pc.Client, "_computer", _routed(TestClient(app)))
        work = tmp_path / "work"
        done = kit.sync(work)
        assert done["examples"] >= 4 and done["added"] == 1
        # The examples land in one folder per app; an example no longer listed goes away.
        assert (work / "Examples" / "PlantCraft" / "First steps.ipynb").exists()
        stale = work / "Examples" / "Read a signal and plot it.ipynb"
        stale.write_text("{}")
        # The server has newer kits (0.1.0-abc) than this one.
        assert done["newer_kit"] is True
        mine = work / "My notebooks" / made["name"]
        assert json.loads(mine.read_text())["cells"]
        mine.write_text('{"edited": true}')
        again = kit.sync(work)
        assert again["added"] == 0 and again["kept"] == 1
        assert mine.read_text() == '{"edited": true}'
        assert not stale.exists()
        # A token for apps' use cannot list a person's notebooks; nor can anyone while it is off.
        reader = TestClient(app)
        listing = reader.get("/api/v1/notebooks", headers={"Authorization": f"Bearer {token}"})
        assert listing.status_code == 200 and listing.json()["kit_version"] == "0.1.0-abc"
        outside = reader.get(
            "/api/v1/notebooks/file",
            params={"path": "My notebooks/../x"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert outside.status_code == 404


def test_kits_built_by_a_deploy_are_read_from_the_data_folder(tmp_path, monkeypatch):
    from plantcraft.ops import snapshot

    monkeypatch.delenv("PLANTCRAFT_NOTEBOOK_KITS", raising=False)
    bundled, built = tmp_path / "bundled", tmp_path / "built"
    bundled.mkdir()
    monkeypatch.setattr(kits, "KITS_DIR", str(bundled))
    monkeypatch.setattr(kits, "BUILT_DIR", str(built))
    # No kits.json from the bundle: the ones ci/macmini/notebook-kits put in PlantCraft's data.
    assert kits.kits_dir() == built
    (bundled / "kits.json").write_text("{}")
    assert kits.kits_dir() == bundled
    # Built again after a restore, never kept in a backup.
    assert "data/processcraft/notebook-kits" in snapshot.SKIPPED_FOLDERS


def test_a_certificate_this_computer_does_not_trust_is_one_line_not_a_traceback(monkeypatch):
    import ssl
    import urllib.error
    import urllib.request

    def refused(*args, **kwargs):
        reason = ssl.SSLCertVerificationError("certificate verify failed")
        reason.verify_message = "unable to get local issuer certificate"
        raise urllib.error.URLError(reason)

    monkeypatch.setattr(urllib.request, "urlopen", refused)
    client = pc.connect("https://plant.example", token="pcat_x", ca=None)
    with pytest.raises(pc.PlantCraftError, match="does not trust .*local issuer.*Download the kit"):
        client.get("/api/v1/me")

    def unreachable(*args, **kwargs):
        raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))

    monkeypatch.setattr(urllib.request, "urlopen", unreachable)
    with pytest.raises(pc.PlantCraftError, match="could not reach https://plant.example"):
        client.get("/api/v1/me")


def test_links_name_a_server_and_a_notebook_and_nothing_else():
    action, values = kit.parse_link(
        "plantcraft-notebooks://open?server=https%3A%2F%2Fplant.local%2F&notebook=..%2F..%2Fx.ipynb"
    )
    assert action == "open"
    assert values == {"server": "https://plant.local", "notebook": "x.ipynb"}
    code = "a" * 32
    assert kit.parse_link(f"plantcraft-notebooks://connect?server=http://h:8443&code={code}")[
        1
    ] == {
        "server": "http://h:8443",
        "code": code,
        "ca": "",
    }
    for bad in (
        "https://plant.local",
        "plantcraft-notebooks://run?server=https://plant.local",
        "plantcraft-notebooks://open?server=file:///etc",
        "plantcraft-notebooks://open?server=https://me:pw@plant.local",
        "plantcraft-notebooks://open?server=https://plant.local&notebook=x.py",
        "plantcraft-notebooks://connect?server=https://plant.local&code=short",
        f"plantcraft-notebooks://connect?server=https://plant.local&code={code}&ca=zz",
    ):
        with pytest.raises(kit.LinkError):
            kit.parse_link(bad)


def test_connect_this_computer_trades_a_one_time_code_for_the_token(
    app,  # noqa: F811
    dist,  # noqa: F811
    shelf,
    monkeypatch,
):
    """No token is copied: the page's link carries a code that works once,
    for two minutes, and the app on the computer keeps the token in the vault."""

    with TestClient(app):
        admin = _turn_on(app)
        vera = _login(app, "vera", "vera-strong-password")
        answer = vera.post("/api/notebooks/pair", headers={"host": "plant.example"})
        assert answer.status_code == 201, answer.text
        link = answer.json()["link"]
        action, values = kit.parse_link(link)
        assert action == "connect" and values["server"] == "http://plant.example"
        # The local CA comes with its SHA-256, which the app checks before it trusts it.
        assert values["ca"] == hashlib.sha256(kits.local_ca()).hexdigest()
        assert TestClient(app).get("/api/notebooks/pair/ca").content == kits.local_ca()
        public = TestClient(app)

        def redeem(url, code, ca):
            given = public.post("/api/notebooks/pair/redeem", json={"code": code, "computer": "pc"})
            assert given.status_code == 200, given.text
            return given.json()

        monkeypatch.setattr(kit, "_redeem", redeem)
        monkeypatch.setattr(kit, "_fetch_ca", lambda url, fingerprint: "")
        monkeypatch.setattr(kit, "_vault", lambda: None)
        assert kit.connect_link(values) is True
        assert kit.stored_token("http://plant.example").startswith("pcat_")
        assert kit.default_server()["url"] == "http://plant.example"
        assert kit.default_server()["name"]
        # Once only.
        again = public.post("/api/notebooks/pair/redeem", json={"code": values["code"]})
        assert again.status_code == 404
        assert public.post("/api/notebooks/pair/redeem", json={"code": "x" * 32}).status_code == 404
        # The token is the person's, read-only, 90 days, and in the audit log.
        tokens = vera.get("/api/assistant-access/mine").json()
        rows = tokens if isinstance(tokens, list) else tokens.get("tokens", [])
        assert any("Notebooks on pc" in item["label"] for item in rows)
        # Without the kit offered, no code.
        assert admin.put("/api/notebooks/settings", json={"kit_enabled": False}).status_code == 200
        assert vera.post("/api/notebooks/pair").status_code == 409
        code = kit.parse_link(link)[1]["code"]
        assert public.post("/api/notebooks/pair/redeem", json={"code": code}).status_code == 404


def test_a_connection_code_connects_the_app_with_one_paste(
    app,  # noqa: F811
    dist,  # noqa: F811
    shelf,
    monkeypatch,
):
    """No link from the page: the person copies one line, the app opened
    unconnected asks for it, checks the CA by its SHA-256 and keeps the token in the vault."""

    with TestClient(app):
        _turn_on(app)
        vera = _login(app, "vera", "vera-strong-password")
        given = vera.post("/api/notebooks/token", headers={"host": "plant.example"}).json()
        found = kit.parse_code(given["code"])
        assert found == {
            "url": "http://plant.example",
            "token": given["token"],
            "ca": hashlib.sha256(kits.local_ca()).hexdigest(),
        }
        # Pasted with line breaks or spaces around it, it is the same code.
        assert kit.parse_code("  " + given["code"][:20] + "\n" + given["code"][20:]) == found
        fetched = []
        monkeypatch.setattr(kit, "_fetch_ca", lambda url, sha: fetched.append(sha) or "ca.pem")
        reader = TestClient(app)

        def check(url, token, ca):
            headers = {"Authorization": f"Bearer {token}"}
            me = reader.get("/api/v1/me", headers=headers)
            assert me.status_code == 200, me.text
            return me.json(), reader.get("/api/v1/notebooks", headers=headers).json()

        monkeypatch.setattr(kit, "_check", check)
        monkeypatch.setattr(kit, "_vault", lambda: None)
        said = kit.connect_with(given["code"])
        assert "http://plant.example" in said and "read-only" in said
        assert fetched == [found["ca"]]
        assert kit.stored_token("http://plant.example") == given["token"]
        assert kit.default_server()["url"] == "http://plant.example"
        assert kit.default_server()["ca"] == "ca.pem"
        with pytest.raises(kit.LinkError):
            kit.parse_code("pcnb1:not-json")
        with pytest.raises(kit.LinkError):
            kit.connect_with("pcnb1:" + "eyJ1cmwiOiJodHRwczovL3gifQ")  # no token in it
        # Asked in a window when the app opens unconnected; cancelling leaves it unconnected.
        monkeypatch.setattr(kit, "ask_code", lambda: "")
        assert kit.connect_interactive() is False


def test_a_code_ends_after_two_minutes(tmp_path, monkeypatch):
    from plantcraft.db import Database
    from plantcraft.notebooks import NotebookStore

    store = NotebookStore(Database(tmp_path / "pc.db"))
    code, _expires = store.pairing_code("vera")
    with store._write() as connection:
        connection.execute("UPDATE notebook_pairings SET expires_at = '2020-01-01T00:00:00+00:00'")
    assert store.redeem(code) is None
    fresh, _expires = store.pairing_code("vera")
    assert store.redeem(fresh) == "vera"
    assert store.redeem(fresh) is None


@pytest.mark.skipif(sys.platform != "linux", reason="the Linux desktop files")
def test_installing_registers_the_link_and_copies_the_examples(tmp_path, monkeypatch):
    home = tmp_path / "kit"
    (home / "examples").mkdir(parents=True)
    (home / "examples" / "Read a signal and plot it.ipynb").write_text('{"cells": []}')
    monkeypatch.setenv("PLANTCRAFT_KIT", str(home))
    kit.install()
    handler = (
        tmp_path / "share" / "applications" / "plantcraft-notebooks-link.desktop"
    ).read_text()
    assert "MimeType=x-scheme-handler/plantcraft-notebooks;" in handler
    assert "-m plantcraft_notebook.kit link %u" in handler
    assert (tmp_path / "documents" / "Examples" / "Read a signal and plot it.ipynb").is_file()
    assert (tmp_path / "documents" / "My notebooks").is_dir()
    kit.uninstall()
    assert not (tmp_path / "share" / "applications" / "plantcraft-notebooks-link.desktop").exists()


def test_the_strip_says_where_the_notebooks_run():
    css = kit.strip_css({"url": "https://plant", "name": "Vera"}, "2027-01-24T10:00:00+00:00")
    assert "On your computer" in css and "as Vera" in css and "2027-01-24" in css


def test_the_windows_setup_and_the_mac_app_go_out_as_they_were_built(
    app,  # noqa: F811
    dist,  # noqa: F811
    shelf,
):
    (shelf / "plantcraft-notebooks-windows-x64-setup.exe").write_bytes(b"MZ" + b"x" * 100)
    (shelf / "missing.zip").write_bytes(b"PK")
    listing = json.loads((shelf / "kits.json").read_text())
    listing["kits"][1]["file"] = "missing.zip"
    listing["kits"][1]["installer"] = {
        "file": "plantcraft-notebooks-windows-x64-setup.exe",
        "bytes": 102,
    }
    listing["kits"][0]["installer"] = {"file": "not-there.zip"}
    (shelf / "kits.json").write_text(json.dumps(listing))
    with TestClient(app):
        _turn_on(app)
        vera = _login(app, "vera", "vera-strong-password")
        offered = {item["id"]: item for item in vera.get("/api/notebooks").json()["kits"]["kits"]}
        assert offered["linux-x64"]["installer"] is None
        setup = offered["windows-x64"]["installer"]
        assert setup["file"].endswith("-setup.exe")
        answer = vera.get(setup["url"])
        assert answer.status_code == 200 and answer.content.startswith(b"MZ")
        assert vera.get("/api/notebooks/kits/linux-x64/installer").status_code == 404
