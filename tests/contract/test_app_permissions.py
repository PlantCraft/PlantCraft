"""An app's own token is held to its [permissions] on every API v1 route (scale review E4,
owner 2026-10-25): a packaged app to its signed manifest, a suite app to what it declares."""
# ruff: noqa: F811 (the fixture "central" of test_api_v1.py, imported to share it)

from __future__ import annotations

from plantcraft.apps import package
from plantcraft_sdk import scopes
from tests.contract.test_api_v1 import _app_key, _rt, central  # noqa: F401


def _service(client, app_id: str = "linkcraft") -> dict[str, str]:
    key = _app_key(client, app_id)["key"]
    grant = client.post("/api/v1/auth/service-token", json={"app": app_id, "key": key})
    assert grant.status_code == 200, grant.text
    return {"Authorization": f"Bearer {grant.json()['token']}"}


def test_every_v1_route_is_named_in_the_permission_table(central):
    routes = {
        (method.upper(), path)
        for path, operations in central.app.openapi()["paths"].items()
        if path.startswith("/api/v1/")
        for method in operations
    }
    named = set(scopes.ROUTE_SCOPES) | set(scopes.PERSON_ONLY)
    assert routes - named == set(), "name each new API v1 route in plantcraft_sdk.scopes"
    assert named - routes == set(), "a route in plantcraft_sdk.scopes no longer exists"


def test_the_package_format_and_the_sdk_list_the_same_permissions():
    assert package.READ_SCOPES == scopes.READ_SCOPES
    assert package.WRITE_SCOPES == scopes.WRITE_SCOPES
    assert package.PERMISSIONS == scopes.PERMISSIONS


def test_an_app_that_declared_its_permissions_is_held_to_them(central):
    headers = _service(central)
    # Before it declares anything (an app before SDK 0.38), nothing changes.
    assert central.get("/api/v1/signals", headers=headers).status_code == 200
    body = {"app": "linkcraft", "version": "9.0.0", "permissions": ["read.assets", "write.audit"]}
    assert central.put("/api/v1/contributions", json=body, headers=headers).status_code == 200
    _rt(central).app_scopes.forget()
    assert central.get("/api/v1/assets", headers=headers).status_code == 200
    refused = central.get("/api/v1/signals", headers=headers)
    assert refused.status_code == 403 and "read.signals" in refused.json()["detail"]
    audit = central.post("/api/v1/audit", json={"action": "x.y"}, headers=headers)
    assert audit.status_code == 201
    assert central.get("/api/v1/installation", headers=headers).status_code == 200
    # A person's own routes are never an app's.
    assert central.get("/api/v1/inbox", headers=headers).status_code == 403


def test_audit_mode_only_logs(central, monkeypatch):
    headers = _service(central)
    body = {"app": "linkcraft", "version": "9.0.0", "permissions": ["write.audit"]}
    central.put("/api/v1/contributions", json=body, headers=headers)
    _rt(central).app_scopes.forget()
    monkeypatch.setenv("PLANTCRAFT_APP_PERMISSIONS", "audit")
    assert central.get("/api/v1/signals", headers=headers).status_code == 200


def test_a_packaged_app_is_held_to_its_manifest_not_to_what_it_says(central):
    rt = _rt(central)
    rt.apps.store.save(
        "acmeflow", name="Acme Flow", version="1.0.0", url="/acme/", origin="package",
        status="running", message="", publisher={}, permissions=["read.assets"], manifest={},
    )  # fmt: skip
    headers = _service(central, "acmeflow")
    body = {"app": "acmeflow", "version": "1.0.0", "permissions": ["read.signals"]}
    central.put("/api/v1/contributions", json=body, headers=headers)
    rt.app_scopes.forget()
    assert central.get("/api/v1/assets", headers=headers).status_code == 200
    assert central.get("/api/v1/signals", headers=headers).status_code == 403


def test_an_external_app_granted_nothing_cannot_grant_itself_more(central, monkeypatch):
    from plantcraft.apps import remote

    rt = _rt(central)
    monkeypatch.setattr(remote, "check_health", lambda url: {"ok": True})
    rt.apps.register_external(
        "acmeext", "Acme External", "https://acme.example/app/", None, "admin", [],
        lambda app_id: ("k1", "unused"), permissions=[],
    )  # fmt: skip
    headers = _service(central, "acmeext")
    body = {"app": "acmeext", "version": "1.0.0", "permissions": ["read.signals"]}
    central.put("/api/v1/contributions", json=body, headers=headers)
    rt.app_scopes.forget()
    assert central.get("/api/v1/signals", headers=headers).status_code == 403


def test_a_persons_token_keeps_the_persons_access(central):
    from tests.contract.test_api_v1 import _as

    headers = _service(central)
    body = {"app": "linkcraft", "version": "9.0.0", "permissions": []}
    central.put("/api/v1/contributions", json=body, headers=headers)
    _rt(central).app_scopes.forget()
    assert central.get("/api/v1/signals", headers=_as(central, "op")).status_code == 200


def test_a_suite_app_is_held_to_what_its_signed_release_pins(central):
    """Security audit 2026-10-26: what a suite app declares when it starts may narrow what the
    bundle's release.json pins, never widen it."""

    rt = _rt(central)
    pins: dict = {}
    rt.app_scopes.pinned = lambda: pins
    headers = _service(central)
    body = {"app": "linkcraft", "version": "9.0.0", "permissions": ["read.assets", "read.signals"]}
    assert central.put("/api/v1/contributions", json=body, headers=headers).status_code == 200
    rt.app_scopes.forget()
    # No release pins it (a development checkout): what it declares.
    assert central.get("/api/v1/signals", headers=headers).status_code == 200
    pins["linkcraft"] = ["read.assets", "write.audit"]
    rt.app_scopes.forget()
    assert central.get("/api/v1/assets", headers=headers).status_code == 200
    assert central.get("/api/v1/signals", headers=headers).status_code == 403
    # What it did not declare stays closed too, though pinned.
    assert central.post("/api/v1/audit", json={"action": "x.y"}, headers=headers).status_code == 403
    # An unreadable status file pins nothing.
    rt.app_scopes.pinned = lambda: 1 / 0
    rt.app_scopes.forget()
    assert central.get("/api/v1/signals", headers=headers).status_code == 200


def test_the_installed_release_pins_the_suite_apps(central):
    import json

    rt = _rt(central)
    status = rt.operations.status_dir
    status.mkdir(parents=True, exist_ok=True)
    release = {"release": {"permissions": {"linkcraft": ["read.assets"]}}}
    (status / "release.json").write_text(json.dumps(release))
    headers = _service(central)
    rt.app_scopes.forget()
    assert central.get("/api/v1/assets", headers=headers).status_code == 200
    assert central.get("/api/v1/signals", headers=headers).status_code == 403
