"""Which PlantCraft versions an app runs on, and closed apps' licences (docs/app-package.md §7-8).

The manifest's new keys ([requires] platform, [tested], [app] source and languages, [license]),
the range rules, the install refusing an app outside its range or without its licence, the
licences page, and the app reading its own licence through API v1.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization

from plantcraft.apps import package as pkg
from plantcraft_sdk import licensing
from tests import app_packages as ap
from tests.test_apps_api import app_row, audit, install, sign_in, upload, world  # noqa: F401

# The manifest ---------------------------------------------------------------------------------


def _valid(**sections):
    return pkg.validate_manifest({**ap.template(**sections), "format": 1}, with_files=False)


def test_new_keys_default_for_an_app_that_names_none():
    manifest = _valid()
    assert manifest["app"]["source"] == "open" and manifest["app"]["languages"] == ["en"]
    assert "tested" not in manifest and "license" not in manifest
    view = pkg.flat({**manifest, "files": {}})
    assert view["tested"] == {"platform": []} and view["license_terms"]["required"] is False


def test_new_keys_are_checked():
    manifest = _valid(
        app={"source": "closed", "languages": ["en", "pt-BR", "es"], "license": "Proprietary"},
        requires={"platform": ">=0.6,<0.8", "processcraft_api": ">=1.0"},
        tested={"platform": ["0.7.0", "0.6.0", "0.6.0"]},
        license={"required": True, "grace_days": 30},
    )
    assert manifest["app"]["languages"] == ["en", "pt-BR", "es"]
    assert manifest["tested"] == {"platform": ["0.6.0", "0.7.0"]}
    assert manifest["license"] == {"required": True, "grace_days": 30}


@pytest.mark.parametrize(
    "sections, reason",
    [
        ({"app": {"source": "secret"}}, "source"),
        ({"app": {"languages": ["pt-BR"]}}, '"en"'),
        ({"app": {"languages": ["en", "portuguese"]}}, "language tags"),
        ({"app": {"languages": ["en", "en"]}}, "twice"),
        ({"requires": {"platform": ">=zero"}}, "platform"),
        ({"tested": {"platform": ["latest"]}}, "tested"),
        ({"license": {"required": "yes"}}, "required"),
        ({"license": {"grace_days": 365}}, "grace_days"),
        ({"license": {"seats": 3}}, "unknown"),
    ],
)
def test_bad_new_keys_are_refused(sections, reason):
    with pytest.raises(pkg.PackageError, match=reason):
        _valid(**sections)


# Ranges ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "version, spec, inside",
    [
        ("0.6.0", ">=0.6,<0.8", True),
        ("0.7.9", ">=0.6,<0.8", True),
        ("0.8.0", ">=0.6,<0.8", False),
        ("0.5.1", ">=0.6,<0.8", False),
        ("0.7.0-rc.1", ">=0.7", True),
        ("0.6.3", "==0.6.*", True),
        ("0.7.0", "==0.6.*", False),
        ("0.6.3", "~=0.6.1", True),
        ("0.7.0", "~=0.6.1", False),
        ("0.9.0", "~=0.6", True),
        ("1.0.0", "~=0.6", False),
        ("0.6.0", "0.6.0", True),
        ("0.6.1", "!=0.6.1", False),
        ("0.10.0", ">0.9", True),
    ],
)
def test_ranges(version, spec, inside):
    assert pkg.satisfies(version, spec) is inside


def test_sdk_and_platform_read_ranges_alike():
    from plantcraft_sdk import compat

    for version in ("0.5.9", "0.6.0", "0.6.12", "0.7.0-rc.2", "0.8.0", "1.0.0"):
        for spec in (">=0.6,<0.8", "==0.6.*", "~=0.6.1", "~=0.6", "<1"):
            assert pkg.satisfies(version, spec) is compat.satisfies(version, spec), (version, spec)


def test_compatibility_refuses_outside_and_warns_when_untested():
    manifest = _valid(
        requires={"platform": ">=0.6,<0.7", "processcraft_api": ">=1.0,<2"},
        tested={"platform": ["0.6.0"]},
    )
    assert pkg.compatibility(manifest, "0.6.0") | {"problems": []} == {
        "platform": "0.6.0",
        "range": ">=0.6,<0.7",
        "api_range": ">=1.0,<2",
        "tested_on": ["0.6.0"],
        "ok": True,
        "tested": True,
        "problems": [],
    }
    later = pkg.compatibility(manifest, "0.6.2")
    assert later["ok"] and not later["tested"]
    outside = pkg.compatibility(manifest, "0.7.0")
    assert not outside["ok"] and "0.7.0" in outside["problems"][0]
    api = pkg.compatibility(manifest, "0.6.0", api_version="2.0")
    assert not api["ok"]
    # A development checkout (no version) checks nothing.
    assert pkg.compatibility(manifest, "")["ok"]


def test_tested_comes_from_passing_reports_of_this_version(tmp_path):
    folder = tmp_path / "compat"
    folder.mkdir()
    rows = [
        ("0.6.0", "hello", "0.1.0", True),
        ("0.7.0", "hello", "0.1.0", True),
        ("0.7.1", "hello", "0.1.0", False),
        ("0.5.0", "hello", "0.0.9", True),
        ("0.6.1", "other", "0.1.0", True),
    ]
    for platform, app, version, passed in rows:
        report = {"platform": platform, "app": app, "app_version": version, "passed": passed}
        (folder / f"{platform}.json").write_text(json.dumps(report))
    (folder / "junk.json").write_text("{")
    assert pkg.tested_from_reports(folder, "hello", "0.1.0") == ["0.6.0", "0.7.0"]


# Licences -------------------------------------------------------------------------------------


def _key(world):
    return serialization.load_pem_private_key(world.key.read_bytes(), password=None)


def _license(world, installation: str, *, app: str = "hello", days: int = 365, **extra) -> bytes:
    today = datetime.now(UTC).date()
    body = {
        "id": "lic-1",
        "app": app,
        "publisher": "testpub",
        "customer": "Refinery North",
        "installation": installation,
        "issued": (today - timedelta(days=400)).isoformat(),
        "expires": (today + timedelta(days=days)).isoformat(),
        "limits": {"sheets": 200},
        "features": ["dexpi"],
        **extra,
    }
    return licensing.issue(_key(world), body)


def _closed(world, folder: str = "b", **sections):
    return ap.build(
        world.tmp / folder,
        world.key,
        app={"source": "closed", "license": "Proprietary"},
        license={"required": True, "grace_days": 7},
        **sections,
    )


def test_a_closed_app_installs_only_with_its_licence(world):
    client = sign_in(world.client())
    preview = upload(client, _closed(world)).json()
    assert preview["license"]["status"] == "missing" and preview["installable"] is False
    assert any("licence" in warning for warning in preview["warnings"])
    refused = client.post(f"/api/apps/packages/{preview['upload_id']}/install")
    assert refused.status_code == 409 and "licence" in refused.json()["detail"]

    installation = client.get("/api/apps/licenses").json()["installation"]
    assert installation
    added = client.post("/api/apps/licenses", content=_license(world, installation))
    assert added.status_code == 201, added.text
    assert added.json()["status"] == "valid" and added.json()["limits"] == {"sheets": 200}
    assert audit(client, "app.license.add")[0]["subject"] == "app:hello"

    row = install(world, client, _closed(world, "c"))
    assert row["status"] == "running" and row["source"] == "closed"
    assert row["license_required"] is True
    listed = client.get("/api/apps/licenses").json()["licenses"]
    assert [(item["app"], item["status"]) for item in listed] == [("hello", "valid")]


def test_a_licence_for_another_installation_or_forged_is_refused(world):
    client = sign_in(world.client())
    other = client.post("/api/apps/licenses", content=_license(world, "another-installation-1"))
    assert other.status_code == 422 and "another installation" in other.json()["detail"]
    good = json.loads(_license(world, "*"))
    good["license"]["limits"]["sheets"] = 100000
    forged = client.post("/api/apps/licenses", content=json.dumps(good).encode())
    assert forged.status_code == 422 and "signature" in forged.json()["detail"]
    assert audit(client, "app.license.rejected")
    stranger, _trusted = ap.publisher(world.tmp / "stranger", "strangerpub")
    body = json.loads(_license(world, "*"))["license"] | {"publisher": "strangerpub"}
    unknown = licensing.issue(
        serialization.load_pem_private_key(stranger.read_bytes(), password=None), body
    )
    refused = client.post("/api/apps/licenses", content=unknown)
    assert refused.status_code == 422 and "unknown publisher" in refused.json()["detail"]
    assert client.delete("/api/apps/licenses/hello").status_code == 404


def test_only_admins_handle_licences(world):
    client = sign_in(world.client(), "eng", "password-123")
    assert client.post("/api/apps/licenses", content=b"{}").status_code == 403


def test_an_app_outside_its_range_is_refused_and_an_untested_one_warns(world, monkeypatch):
    monkeypatch.setenv("PLANTCRAFT_PLATFORM_VERSION", "0.7.0")
    client = sign_in(world.client())
    package = ap.build(
        world.tmp / "b",
        world.key,
        requires={"platform": ">=0.6,<0.7", "processcraft_api": ">=1.0"},
        tested={"platform": ["0.6.0"]},
    )
    preview = upload(client, package).json()
    assert preview["compatibility"]["ok"] is False and preview["installable"] is False
    refused = client.post(f"/api/apps/packages/{preview['upload_id']}/install")
    assert refused.status_code == 409 and "0.7.0" in refused.json()["detail"]

    package = ap.build(
        world.tmp / "c",
        world.key,
        requires={"platform": ">=0.6,<0.8", "processcraft_api": ">=1.0"},
        tested={"platform": ["0.6.0"]},
    )
    preview = upload(client, package).json()
    assert preview["installable"] is True and preview["compatibility"]["tested"] is False
    assert any("not tested it on PlantCraft 0.7.0" in item for item in preview["warnings"])
    row = install(world, client, package)
    assert row["installed_on"] == "0.7.0" and row["requires_platform"] == ">=0.6,<0.8"
    report = client.get("/api/apps/upgrade-check", params={"to": "0.8.0"}).json()
    assert report["blocked"] == ["hello"]
    assert client.get("/api/apps/upgrade-check", params={"to": "0.7.5"}).json()["blocked"] == []


def test_the_app_reads_its_own_licence_and_checks_it_itself(world):
    client = sign_in(world.client())
    installation = client.get("/api/apps/licenses").json()["installation"]
    client.post("/api/apps/licenses", content=_license(world, installation))
    runtime = client.app.state.runtime
    served = runtime.apps.license_file("hello")
    public = licensing.load_public_key((world.trusted / "testpub.pub").read_bytes())
    state = licensing.state(
        json.dumps(served).encode(), public, app_id="hello", installation=installation
    )
    assert state.usable and state.limit("sheets") == 200 and state.has("dexpi")
    meta = client.get("/api/v1/installation").json()
    assert meta["api"] == "1.0" and "read.assets" in meta["scopes"] and "version" in meta
    # A person is not an app: the route answers apps only.
    assert client.get("/api/v1/apps/self/license").status_code == 403


def test_licence_states():
    key = licensing.new_key()
    public = key.public_key()
    today = datetime(2027, 1, 10, tzinfo=UTC)
    body = {
        "id": "x",
        "app": "hello",
        "publisher": "Acme Tools",
        "customer": "Plant",
        "installation": "inst-12345678",
        "issued": "2026-01-01",
        "expires": "2027-01-05",
    }
    data = licensing.issue(key, body)

    def state(**kwargs):
        args = {"app_id": "hello", "installation": "inst-12345678", "grace_days": 7, "now": today}
        return licensing.state(data, public, **(args | kwargs))

    assert state().status == "grace" and state().usable and state().days_left == -5
    assert state(grace_days=3).status == "expired" and not state(grace_days=3).usable
    assert state(now=datetime(2027, 1, 1, tzinfo=UTC)).status == "valid"
    assert state(app_id="other").status == "invalid"
    assert state(installation="inst-87654321").status == "invalid"
    assert licensing.state(None, public, app_id="hello", installation=None).status == "missing"
    with pytest.raises(licensing.LicenseError):
        licensing.validate(body | {"expires": "2025-01-01"})
