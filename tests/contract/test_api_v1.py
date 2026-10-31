"""API v1 contract (docs/api-v1.md): every endpoint, its exact shape, auth failures, read-only.

Apps run the same shape checks against ``plantcraft_sdk.testing.FakePlantCraft``;
``test_the_fake_serves_the_same_shapes`` keeps the fake and PlantCraft together.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from plantcraft.api.app import create_app
from plantcraft.api.identity import issue_user_token
from plantcraft_sdk import jwt
from plantcraft_sdk.auth import AuthError, TokenVerifier
from plantcraft_sdk.client import PlantCraftClient
from plantcraft_sdk.contract import MAX_BATCH_SIGNALS, BatchBuilder
from plantcraft_sdk.testing import FakePlantCraft

ROOT = Path(__file__).resolve().parents[2]
ADMIN, PASSWORD = "root", "root-password-123"

KEY_FIELDS = {"kid", "kty", "crv", "x"}
GRANT_FIELDS = {"token", "expires_at"}
ME_FIELDS = {"username", "name", "level", "apps", "notebooks_url"}
APP_FIELDS = {"id", "name", "url", "access", "version"}
ASSET_FIELDS = {
    "id",
    "name",
    "kind",
    "type_path",
    "parent_id",
    "attributes",
    "signals",
    "relations",
}
ASSET_TYPE_FIELDS = {
    "id",
    "name",
    "description",
    "icon",
    "parent",
    "path",
    "attributes",
    "roles",
    "children",
}
TYPE_ATTRIBUTE_FIELDS = {"key", "name", "data_type", "unit", "required", "default", "options"}
TYPE_ROLE_FIELDS = {"key", "name", "unit", "required"}
SIGNAL_FIELDS = {
    "id",
    "name",
    "source",
    "unit",
    "description",
    "low",
    "high",
    "kind",
    "source_kind",
}
SERIES_FIELDS = {"signal", "kind", "t", "v"}
BATCH_FIELDS = {"series", "errors"}
BATCH_ERROR_FIELDS = {"signal", "status", "detail"}
VALUE_FIELDS = {"signal", "agg", "window", "value", "at"}
LOOP_SIGNAL = "scenario:pv"  # <source id>:<tag> (D2 of docs/app-standard.md)
ISO_UTC = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?\+00:00$")
ISO_OFFSET = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?[+-]\d\d:\d\d$")


def _scenario(tmp_path, monkeypatch) -> None:
    scenario = json.loads((ROOT / "scenarios" / "generic_demo.json").read_text())
    scenario["storage"]["sqlite_path"] = str(tmp_path / "workspace.sqlite3")
    scenario["source"]["path"] = str(ROOT / scenario["source"]["path"])
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario))
    monkeypatch.setenv("PLANTCRAFT_SCENARIO", str(path))
    monkeypatch.setenv("PLANTCRAFT_PREWARM_HISTORY", "false")
    monkeypatch.setenv("PLANTCRAFT_PREWARM_HISTORY", "false")
    monkeypatch.setenv("PLANTCRAFT_APPS", "linkcraft=/link/@0.1.0,dashcraft=/dash/")
    monkeypatch.delenv("PLANTCRAFT_TOKEN_KEY_FILE", raising=False)


@pytest.fixture()
def central(tmp_path, monkeypatch):
    """PlantCraft with sign-in on and a few people with different access."""

    _scenario(tmp_path, monkeypatch)
    secret = tmp_path / "admin.secret"
    secret.write_text(PASSWORD)
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_ENABLED", "true")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_USERNAME", ADMIN)
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE", str(secret))
    with TestClient(create_app()) as client:
        users = client.app.state.runtime.workspace.users
        for username, level, apps in (
            ("eng", "editor", None),
            ("op", "viewer", ["cpm"]),  # the module id still grants the app it grew into
            ("nobody", "viewer", []),
            ("wall", "dashboards", None),
        ):
            users.upsert_user(username, username.title(), "")
            users.set_access(username, level, apps)
            users.set_password(username, "password-123")
        yield client


@pytest.fixture()
def local(tmp_path, monkeypatch):
    """PlantCraft in local single-user mode (sign-in off)."""

    _scenario(tmp_path, monkeypatch)
    monkeypatch.delenv("PLANTCRAFT_BASIC_AUTH_ENABLED", raising=False)
    with TestClient(create_app()) as client:
        yield client


def _rt(client):
    return client.app.state.runtime


def _token(client, username: str) -> str:
    return issue_user_token(_rt(client), username)["token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _as(client, username: str) -> dict[str, str]:
    return _auth(_token(client, username))


def _claims(client, token: str) -> dict:
    return jwt.decode(token, client.get("/api/v1/auth/keys").json(), "processcraft")


# Identity ---------------------------------------------------------------------------


def test_keys_are_public_ed25519_jwks(central):
    response = central.get("/api/v1/auth/keys")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"keys"} and body["keys"]
    for key in body["keys"]:
        assert set(key) == KEY_FIELDS and key["kty"] == "OKP" and key["crv"] == "Ed25519"


def test_the_key_pair_is_kept_beside_the_database_readable_by_its_owner_only(central, tmp_path):
    key_file = tmp_path / "tokens.key"
    assert key_file.is_file() and key_file.stat().st_mode & 0o777 == 0o600


def test_sign_in_sets_the_token_cookie_and_the_token_has_every_claim(central):
    response = central.post("/api/login", json={"username": "op", "password": "password-123"})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("processcraft_token=")
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    token = central.cookies.get("processcraft_token")
    header = jwt.unverified_header(token)
    assert header["alg"] == "EdDSA" and header["kid"]
    claims = _claims(central, token)
    assert claims["iss"] == "processcraft" and claims["aud"] == "processcraft"
    assert claims["sub"] == "op" and claims["name"] == "Op" and claims["level"] == "viewer"
    assert claims["apps"] == {"linkcraft": "viewer"}
    # Only a person limited to part of the plant carries its roots (docs/asset-scope.md).
    assert "assets" not in claims
    assert claims["exp"] - claims["iat"] == 15 * 60
    # The cookie alone is enough to call API v1.
    assert central.get("/api/v1/me").json()["username"] == "op"
    central.post("/api/logout")
    assert central.cookies.get("processcraft_token") is None


def test_browser_token_renewal_needs_the_session(central):
    assert central.post("/api/v1/auth/token").status_code == 401
    central.post("/api/login", json={"username": "eng", "password": "password-123"})
    response = central.post("/api/v1/auth/token")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == GRANT_FIELDS and ISO_OFFSET.match(body["expires_at"])
    assert _claims(central, body["token"])["sub"] == "eng"
    assert central.cookies.get("processcraft_token") == body["token"]


def test_local_mode_issues_tokens_for_the_session_user(local):
    """With sign-in off the token names whoever the session is, so audit rows match."""

    users = _rt(local).workspace.users
    users.upsert_user("ana", "Ana Lima", "")
    users.upsert_user("bruno", "Bruno Reis", "")
    users.set_access("bruno", "viewer", None)
    session = local.get("/api/session").json()
    claims = _claims(local, local.cookies.get("processcraft_token"))
    assert claims["sub"] == session["username"] and claims["level"] == "admin"
    assert claims["apps"] == {"linkcraft": "editor", "dashcraft": "editor"}
    assert local.post("/api/session/switch", json={"username": "ana"}).status_code == 200
    token = local.cookies.get("processcraft_token")
    claims = _claims(local, token)
    assert claims["sub"] == "ana" and claims["name"] == "Ana Lima"
    assert local.post("/api/v1/auth/token").status_code == 200
    assert local.get("/api/v1/me", headers=_auth(token)).json()["username"] == "ana"
    local.post("/api/v1/audit", json={"action": "loop.edit", "app": "linkcraft"})
    entry = _rt(local).workspace.audit.list(limit=1)[0]
    assert entry["username"] == "ana" and entry["app_id"] == "linkcraft"
    # A switch to a viewer gives the apps a viewer's token.
    local.post("/api/session/switch", json={"username": "bruno"})
    claims = _claims(local, local.cookies.get("processcraft_token"))
    assert claims["sub"] == "bruno" and claims["apps"] == {
        "linkcraft": "viewer",
        "dashcraft": "viewer",
    }


def _app_key(client, app_id: str = "linkcraft") -> dict:
    client.post("/api/login", json={"username": ADMIN, "password": PASSWORD})
    response = client.post("/api/app-keys", json={"app_id": app_id, "label": "CI"})
    assert response.status_code == 201, response.text
    client.cookies.clear()
    return response.json()


def test_service_tokens_come_from_an_app_key_and_stop_when_it_is_revoked(central):
    created = _app_key(central)
    assert created["key"].startswith("pck_") and created["active"]
    stored = json.dumps(_rt(central).workspace.app_keys.list())
    assert created["key"].split(".", 1)[1] not in stored  # only the hash is kept
    response = central.post(
        "/api/v1/auth/service-token", json={"app": "linkcraft", "key": created["key"]}
    )
    assert response.status_code == 200
    grant = response.json()
    assert set(grant) == GRANT_FIELDS
    claims = _claims(central, grant["token"])
    assert claims["sub"] == "app:linkcraft" and claims["level"] == "viewer"
    assert claims["apps"] == {"linkcraft": "viewer"}
    assert claims["exp"] - claims["iat"] == 60 * 60
    assert central.get("/api/v1/me", headers=_auth(grant["token"])).status_code == 200
    for body in (
        {"app": "linkcraft", "key": created["key"] + "x"},
        {"app": "dashcraft", "key": created["key"]},
        {"app": "linkcraft", "key": "nonsense"},
    ):
        assert central.post("/api/v1/auth/service-token", json=body).status_code == 401
    central.post("/api/login", json={"username": ADMIN, "password": PASSWORD})
    assert central.delete(f"/api/app-keys/{created['key_id']}").json()["active"] is False
    central.cookies.clear()
    assert central.get("/api/v1/me", headers=_auth(grant["token"])).status_code == 401
    body = {"app": "linkcraft", "key": created["key"]}
    assert central.post("/api/v1/auth/service-token", json=body).status_code == 401


def test_the_revocation_list_ends_tokens_in_every_app_that_verifies_offline(central):
    """Disabled, a new password or new access: apps refuse the old tokens within seconds."""

    users = _rt(central).workspace.users
    verifier = TokenVerifier("http://testserver", "linkcraft", http_client=central)
    old = _token(central, "eng")
    assert verifier.user(old).username == "eng"
    listed = central.get("/api/v1/auth/revoked").json()  # public, like the keys
    assert set(listed) == {"users", "keys", "sessions"}
    assert all(set(item) == {"sub_sha256", "not_before"} for item in listed["users"])
    assert "eng" not in json.dumps(listed)  # people appear only as a digest

    # The same level and apps again change nothing (the admin's level is set at every start).
    stamp = users.tokens_valid_after("eng")
    users.set_access("eng", "editor", None)
    assert users.tokens_valid_after("eng") == stamp
    for change in (
        lambda: users.set_access("eng", "viewer", None),
        lambda: users.set_password("eng", "password-456"),
        lambda: users.deactivate("eng"),
    ):
        old = _token(central, "eng")
        assert central.get("/api/v1/me", headers=_auth(old)).status_code == 200
        change()
        # PlantCraft refuses it at once; the apps on their next read of the list.
        assert central.get("/api/v1/me", headers=_auth(old)).status_code == 401
        verifier._revoked_at = -float("inf")
        with pytest.raises(AuthError) as error:
            verifier.user(old)
        assert error.value.status_code == 401
    users.activate("eng")
    fresh = _token(central, "eng")  # signing in again, even in the same second, works
    assert central.get("/api/v1/me", headers=_auth(fresh)).status_code == 200
    verifier._revoked_at = -float("inf")
    assert verifier.user(fresh).username == "eng"

    # A revoked app key ends its service tokens in the apps too.
    created = _app_key(central)
    grant = central.post(
        "/api/v1/auth/service-token", json={"app": "linkcraft", "key": created["key"]}
    ).json()
    assert verifier.user(grant["token"]).is_service
    central.post("/api/login", json={"username": ADMIN, "password": PASSWORD})
    central.delete(f"/api/app-keys/{created['key_id']}")
    central.cookies.clear()
    keys = central.get("/api/v1/auth/revoked").json()["keys"]
    assert [item["key_id"] for item in keys] == [created["key_id"]]
    verifier._revoked_at = -float("inf")
    with pytest.raises(AuthError):
        verifier.user(grant["token"])


def test_app_keys_are_for_admins_only(central):
    central.post("/api/login", json={"username": "eng", "password": "password-123"})
    assert central.get("/api/app-keys").status_code == 403
    assert central.post("/api/app-keys", json={"app_id": "linkcraft"}).status_code == 403


def test_me_comes_from_the_token(central):
    body = central.get("/api/v1/me", headers=_as(central, "eng")).json()
    assert set(body) == ME_FIELDS
    assert body == {
        "username": "eng",
        "name": "Eng",
        "level": "editor",
        "apps": {"linkcraft": "editor", "dashcraft": "editor"},
        "notebooks_url": None,  # Notebooks are off until an admin turns them on
    }


def test_apps_are_the_installed_ones_the_caller_may_open(central):
    apps = central.get("/api/v1/apps", headers=_as(central, "eng")).json()
    assert [set(item) for item in apps] == [APP_FIELDS, APP_FIELDS]
    assert apps[0] == {
        "id": "linkcraft",
        "name": "PlantCraft Analytics",
        "url": "/link/",
        "access": "editor",
        "version": "0.1.0",
    }
    assert apps[1]["version"] is None
    viewer = central.get("/api/v1/apps", headers=_as(central, "op")).json()
    assert [(item["id"], item["access"]) for item in viewer] == [("linkcraft", "viewer")]
    assert central.get("/api/v1/apps", headers=_as(central, "nobody")).json() == []
    assert central.get("/api/v1/apps", headers=_as(central, "wall")).json() == []


def test_apps_installed_from_processcraft_follow_the_configured_ones(central):
    """Installed (and external) apps join ``PLANTCRAFT_APPS`` in the suite's order (former ids
    as the app they became, unknown apps last); pending installs do not."""

    store = _rt(central).apps.store
    store.save("histcraft", name="HistCraft", version="1.0.0", url="/hist/", origin="package",
               status="running")  # fmt: skip
    store.save("wiki", name="Wiki", version=None, url="https://wiki.plant.example/",
               origin="external", status="external")  # fmt: skip
    store.save("pending", name="Pending", version="0.1.0", url="/pending/", origin="package",
               status="installing")  # fmt: skip
    apps = central.get("/api/v1/apps", headers=_as(central, "eng")).json()
    assert [item["id"] for item in apps] == ["histcraft", "linkcraft", "dashcraft", "wiki"]
    assert all(set(item) == APP_FIELDS for item in apps)
    assert apps[0] == {
        "id": "histcraft", "name": "HistCraft", "url": "/hist/", "access": "editor",
        "version": "1.0.0",
    }  # fmt: skip
    viewer = central.get("/api/v1/apps", headers=_as(central, "op")).json()
    assert [item["id"] for item in viewer] == ["linkcraft"], "access per app still applies"


def test_an_app_refuses_a_user_without_access_to_it(central):
    """The SDK verifier, reading the real PlantCraft's keys, checks ``apps[<app id>]``."""

    verifier = TokenVerifier("http://testserver", "linkcraft", http_client=central)
    assert verifier.user(_token(central, "op")).access == "viewer"
    with pytest.raises(AuthError) as error:
        verifier.user(_token(central, "nobody"))
    assert error.value.status_code == 403
    with pytest.raises(AuthError):
        TokenVerifier("http://testserver", "alarmcraft", http_client=central).user(
            _token(central, "eng")
        )


# Plant data -------------------------------------------------------------------------


def test_assets_tree_with_signals_by_role(central):
    headers = _as(central, "op")
    assets = central.get("/api/v1/assets", headers=headers).json()
    assert assets and all(set(item) == ASSET_FIELDS for item in assets)
    assert all(isinstance(item["attributes"], dict) for item in assets)
    loop = next(item for item in assets if item["kind"] == "loop")
    assert loop["signals"]["pv"] == "scenario:pv" and loop["signals"]["sp"] == "scenario:sp"
    loops = central.get("/api/v1/assets", params={"kind": "loop"}, headers=headers).json()
    assert loops == [loop]
    children = central.get(
        "/api/v1/assets", params={"parent_id": loop["parent_id"]}, headers=headers
    ).json()
    assert loop in children and all(item["parent_id"] == loop["parent_id"] for item in children)
    one = central.get(f"/api/v1/assets/{quote(loop['id'], safe='')}", headers=headers)
    assert one.json() == loop
    assert central.get("/api/v1/assets/no-such-asset", headers=headers).status_code == 404


def test_assets_carry_their_type_path_record_and_relations(central):
    """Added 2026-10-20: ``type_path``, attribute values, ``relations`` and the ``type`` filter."""

    store = _rt(central).workspace.assets
    loop = next(item for item in store.list() if item["kind"] == "loop")
    store.save("FV-2001", name="FV-2001", kind="control_valve", parent_id=loop["parent_id"])
    store.save("LV-2002", name="LV-2002", kind="valve", parent_id=loop["parent_id"])
    store.set_attributes(loop["asset_id"], {"loop_type": "flow", "criticality": "high"}, actor="t")
    store.set_attributes("FV-2001", {"characteristic": "linear", "manufacturer": "X"}, actor="t")
    store.relate(loop["asset_id"], "controls", "FV-2001")
    headers = _as(central, "op")
    assets = {item["id"]: item for item in central.get("/api/v1/assets", headers=headers).json()}
    assert all(set(item) == ASSET_FIELDS for item in assets.values())
    found = assets[loop["asset_id"]]
    assert found["type_path"] == ["loop"]
    assert (
        found["attributes"]["loop_type"] == "flow" and found["attributes"]["criticality"] == "high"
    )
    assert {"description", "kind_label", "origin"} <= set(found["attributes"])
    assert found["attributes"]["kind_label"] == "Control loop"
    assert found["relations"] == [{"type": "controls", "to": "FV-2001"}]
    valve = assets["FV-2001"]
    assert valve["kind"] == "control_valve"
    assert valve["type_path"] == ["equipment", "valve", "control_valve"]
    assert valve["attributes"]["manufacturer"] == "X" and valve["relations"] == []
    # ``type`` takes the type and its subtypes; ``kind`` stays an exact match.
    valves = central.get("/api/v1/assets", params={"type": "valve"}, headers=headers).json()
    assert {item["id"] for item in valves} == {"FV-2001", "LV-2002"}
    exact = central.get("/api/v1/assets", params={"kind": "valve"}, headers=headers).json()
    assert [item["id"] for item in exact] == ["LV-2002"]
    equipment = central.get("/api/v1/assets", params={"type": "equipment"}, headers=headers).json()
    assert {"FV-2001", "LV-2002"} <= {item["id"] for item in equipment}
    assert central.get("/api/v1/assets", params={"type": "nope"}, headers=headers).json() == []


def test_asset_types_with_inheritance_resolved(central):
    headers = _as(central, "op")
    response = central.get("/api/v1/asset-types", headers=headers)
    assert response.status_code == 200
    types = {item["id"]: item for item in response.json()}
    assert {"site", "unit", "area", "equipment", "loop", "pump", "valve", "control_valve"} <= set(
        types
    )
    assert {"instrument"} <= set(types)
    for item in types.values():
        assert set(item) == ASSET_TYPE_FIELDS
        assert item["path"][-1] == item["id"]
        assert all(set(entry) == TYPE_ATTRIBUTE_FIELDS for entry in item["attributes"])
        assert all(set(entry) == TYPE_ROLE_FIELDS for entry in item["roles"])
        assert all(
            entry["data_type"] in {"text", "number", "choice", "date", "asset"}
            for entry in item["attributes"]
        )
    assert types["site"]["name"] == "Plant" and types["loop"]["name"] == "Control loop"
    loop = types["loop"]
    attributes = {entry["key"]: entry for entry in loop["attributes"]}
    assert attributes["loop_type"]["options"] == [
        "flow",
        "level",
        "pressure",
        "temperature",
        "composition",
    ]
    assert attributes["criticality"]["options"] == ["low", "medium", "high"]
    assert attributes["action"]["options"] == ["direct", "reverse"]
    assert attributes["controller"]["options"] == ["DCS", "SLC"]
    roles = {entry["key"]: entry for entry in loop["roles"]}
    assert {"pv", "sp", "op", "mode", "secondary"} <= set(roles)
    assert roles["pv"]["required"] and roles["op"]["required"] and not roles["sp"]["required"]
    valve = types["control_valve"]
    assert valve["parent"] == "valve" and valve["path"] == ["equipment", "valve", "control_valve"]
    keys = [entry["key"] for entry in valve["attributes"]]
    # Inherited first (equipment, then valve), then its own.
    assert keys.index("manufacturer") < keys.index("diameter") < keys.index("characteristic")
    assert [entry["key"] for entry in valve["roles"]] == ["position", "command"]
    assert "pump" in types["equipment"]["children"]  # subtypes of an allowed type are allowed


def test_signals_with_source_units_and_limits(central):
    headers = _as(central, "op")
    signals = central.get("/api/v1/signals", headers=headers).json()
    ids = {f"scenario:{tag}" for tag in ("pv", "sp", "op", "mode")}
    assert ids <= {item["id"] for item in signals}
    assert all(set(item) == SIGNAL_FIELDS for item in signals)
    assert all(item["source"] == "scenario" for item in signals)
    assert all(item["id"] == f"{item['source']}:{item['name']}" for item in signals)
    kinds = {item["id"]: item["kind"] for item in signals}
    assert kinds["scenario:mode"] == "text"
    assert kinds["scenario:pv"] == kinds["scenario:sp"] == "number"
    found = central.get("/api/v1/signals", params={"q": "neighbor"}, headers=headers).json()
    assert [item["id"] for item in found] == ["scenario:neighbor_pv"]
    one = central.get("/api/v1/signals/scenario:pv", headers=headers).json()
    assert set(one) == SIGNAL_FIELDS and one["id"] == "scenario:pv"
    assert central.get("/api/v1/signals/nope", headers=headers).status_code == 404
    assert central.get("/api/v1/signals/other:pv", headers=headers).status_code == 404


def test_a_bare_tag_one_source_has_still_reads_until_v1_is_frozen(central):
    """Deprecated: the ids before D2 were bare tags; one source's tag names its signal."""

    headers = _as(central, "op")
    one = central.get("/api/v1/signals/pv", headers=headers).json()
    assert one["id"] == "scenario:pv"
    window = {"start": "2026-01-01T11:00:00Z", "end": "2026-01-01T11:10:00Z"}
    bare = central.get("/api/v1/signals/pv/series", params=window, headers=headers).json()
    named = central.get("/api/v1/signals/scenario:pv/series", params=window, headers=headers)
    assert bare["signal"] == "pv" and bare["v"] == named.json()["v"]
    value = central.get("/api/v1/signals/pv/value", headers=headers).json()
    assert value["signal"] == "pv" and isinstance(value["value"], float)


def test_signal_ids_with_slashes_are_url_encoded(central):
    rt = _rt(central)
    root = rt.platform.root_asset_id
    rt.workspace.assets.bind_signals(root, [{"signal_id": "Area/FIC-9.PV", "role": "pv"}])
    headers = _as(central, "op")
    signal_id = "scenario:Area/FIC-9.PV"
    path = quote(signal_id, safe="")
    assert central.get(f"/api/v1/signals/{path}", headers=headers).json()["id"] == signal_id
    series = central.get(f"/api/v1/signals/{path}/series", headers=headers).json()
    assert series == {"signal": signal_id, "kind": "number", "t": [], "v": []}
    # ":" needs no encoding in the path.
    raw = central.get("/api/v1/signals/scenario:Area%2FFIC-9.PV", headers=headers)
    assert raw.json()["id"] == signal_id


def test_pi_tags_with_spaces_and_backslashes_are_signal_ids(central):
    rt = _rt(central)
    tag = "Unit 2\\FIC 101.PV"
    rt.workspace.assets.bind_signals(rt.platform.root_asset_id, [{"signal_id": tag, "role": ""}])
    headers = _as(central, "op")
    one = central.get(f"/api/v1/signals/{quote(f'scenario:{tag}', safe='')}", headers=headers)
    assert one.status_code == 200 and one.json()["id"] == f"scenario:{tag}"


def test_series_recorded_and_on_a_regular_step(central):
    headers = _as(central, "op")
    # The demo file covers 08:00-09:59:50 local time (-03:00), every 10 s.
    window = {"start": "2026-01-01T11:00:00Z", "end": "2026-01-01T11:10:00+00:00"}
    recorded = central.get(f"/api/v1/signals/{LOOP_SIGNAL}/series", params=window, headers=headers)
    assert recorded.status_code == 200
    body = recorded.json()
    assert set(body) == SERIES_FIELDS and body["signal"] == LOOP_SIGNAL and body["kind"] == "number"
    assert len(body["t"]) == len(body["v"]) == 61
    assert body["t"][0] == "2026-01-01T11:00:00+00:00" and all(ISO_UTC.match(x) for x in body["t"])
    assert all(isinstance(value, float) for value in body["v"])
    stepped = central.get(
        f"/api/v1/signals/{LOOP_SIGNAL}/series", params={**window, "step": 60}, headers=headers
    ).json()
    assert len(stepped["t"]) == 10 and stepped["t"][1] == "2026-01-01T11:01:00+00:00"
    # Before the file starts: a regular grid of nulls, not an error.
    early = {"start": "2026-01-01T10:00:00Z", "end": "2026-01-01T10:05:00Z", "step": 60}
    empty = central.get(f"/api/v1/signals/{LOOP_SIGNAL}/series", params=early, headers=headers)
    assert empty.json()["v"] == [None] * 5
    # Text signals (controller modes) give their labels.
    mode = central.get("/api/v1/signals/scenario:mode/series", params=window, headers=headers)
    mode = mode.json()
    assert mode["kind"] == "text" and len(mode["v"]) == 61 and set(mode["v"]) <= {"auto", "manual"}
    assert all(isinstance(label, str) for label in mode["v"])
    stepped_mode = central.get(
        "/api/v1/signals/scenario:mode/series", params={**window, "step": 60}, headers=headers
    ).json()
    assert len(stepped_mode["v"]) == 10 and all(isinstance(x, str) for x in stepped_mode["v"])
    default = central.get(f"/api/v1/signals/{LOOP_SIGNAL}/series", headers=headers)
    assert default.status_code == 200 and len(default.json()["t"]) == 720


@pytest.mark.parametrize(
    "params",
    [
        {"start": "2026-01-01T12:00:00Z", "end": "2026-01-01T11:00:00Z"},
        {"start": "yesterday", "end": "2026-01-01T11:00:00Z"},
        {"start": "2025-01-01T00:00:00Z", "end": "2026-01-01T11:00:00Z", "step": 1},
        {"start": "2020-01-01T00:00:00Z", "end": "2026-01-01T11:00:00Z"},
        {"step": -5},
        {"step": 0},
    ],
)
def test_series_requests_outside_the_contract_are_422(central, params):
    response = central.get(
        f"/api/v1/signals/{LOOP_SIGNAL}/series", params=params, headers=_as(central, "op")
    )
    assert response.status_code == 422 and response.json()["detail"]


@pytest.mark.parametrize("agg", ["last", "mean", "min", "max", "std"])
def test_value_aggregates_over_a_window(central, agg):
    response = central.get(
        f"/api/v1/signals/{LOOP_SIGNAL}/value",
        params={"agg": agg, "window": "1h"},
        headers=_as(central, "op"),
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == VALUE_FIELDS
    assert body["signal"] == LOOP_SIGNAL and body["agg"] == agg and body["window"] == "1h"
    assert isinstance(body["value"], float)
    # The file's last sample is "now" for recorded data.
    assert body["at"] == "2026-01-01T12:59:50+00:00"


def test_the_value_of_a_text_signal_is_its_last_label(central):
    headers = _as(central, "op")
    body = central.get("/api/v1/signals/scenario:mode/value", headers=headers).json()
    assert isinstance(body["value"], str) and body["at"] == "2026-01-01T12:59:50+00:00"
    mean = central.get(
        "/api/v1/signals/scenario:mode/value", params={"agg": "mean"}, headers=headers
    )
    assert mean.status_code == 422


# Batch read ---------------------------------------------------------------------------


def test_batch_series_shape_order_and_per_signal_errors(central):
    headers = _as(central, "op")
    window = {"start": "2026-01-01T11:00:00Z", "end": "2026-01-01T11:10:00+00:00"}
    response = central.post(
        "/api/v1/series",
        json={
            "signals": ["scenario:sp", "nope", "scenario:mode", "pv", "scenario:sp"],
            **window,
        },
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == BATCH_FIELDS
    # Each series is named as asked: "pv" is the deprecated bare tag of scenario:pv.
    assert [item["signal"] for item in body["series"]] == ["scenario:sp", "scenario:mode", "pv"]
    assert all(set(item) == SERIES_FIELDS for item in body["series"])
    assert [item["kind"] for item in body["series"]] == ["number", "text", "number"]
    assert body["errors"] == [{"signal": "nope", "status": 404, "detail": "Signal not found."}]
    # Each series is what the one-signal route answers.
    for item in body["series"]:
        alone = central.get(
            f"/api/v1/signals/{item['signal']}/series", params=window, headers=headers
        ).json()
        assert item == alone
    stepped = central.post(
        "/api/v1/series", json={"signals": ["pv", "mode"], **window, "step": 60}, headers=headers
    ).json()
    assert [len(item["t"]) for item in stepped["series"]] == [10, 10]


def test_batch_series_reads_the_source_once(central):
    rt = _rt(central)
    spy = SpySource(rt.platform.sources.primary)
    rt.platform.sources.primary = spy
    central.post(
        "/api/v1/series",
        json={"signals": ["pv", "sp", "op", "mode"], "start": "2026-01-01T11:00:00Z"},
        headers=_as(central, "op"),
    )
    assert spy.used.count("read_range") == 1


def test_a_full_batch_postpones_the_rest_with_413(central, monkeypatch):
    from plantcraft.platform.datalayer import local

    monkeypatch.setattr(local, "BatchBuilder", lambda: BatchBuilder(100))
    window = {"start": "2026-01-01T11:00:00Z", "end": "2026-01-01T11:10:00Z"}
    body = central.post(
        "/api/v1/series", json={"signals": ["pv", "sp", "op"], **window}, headers=_as(central, "op")
    ).json()
    assert [item["signal"] for item in body["series"]] == ["pv"]  # the first always fits
    assert [(item["signal"], item["status"]) for item in body["errors"]] == [
        ("sp", 413),
        ("op", 413),
    ]
    assert all(set(item) == BATCH_ERROR_FIELDS for item in body["errors"])


def test_the_client_reads_a_full_batch_in_several_requests(central, monkeypatch):
    from plantcraft.platform.datalayer import local

    monkeypatch.setattr(local, "BatchBuilder", lambda: BatchBuilder(100))
    client = PlantCraftClient("http://testserver", _token(central, "op"), http_client=central)
    batch = client.series_many(["pv", "sp", "op"], "2026-01-01T11:00:00Z", "2026-01-01T11:10:00Z")
    assert [item["signal"] for item in batch["series"]] == ["pv", "sp", "op"]
    assert batch["errors"] == []


@pytest.mark.parametrize(
    "body",
    [
        {"signals": []},
        {"signals": ["pv"] * (MAX_BATCH_SIGNALS + 1)},
        {"signals": [""]},
        {"signals": ["x" * 301]},
        {"signals": "pv"},
        {"signals": ["pv"], "start": "yesterday"},
        {"signals": ["pv"], "step": 0},
        {
            "signals": ["pv"],
            "start": "2025-01-01T00:00:00Z",
            "end": "2026-01-01T11:00:00Z",
            "step": 1,
        },
        {"signals": ["pv"], "start": "2026-01-01T12:00:00Z", "end": "2026-01-01T11:00:00Z"},
    ],
)
def test_batch_requests_outside_the_contract_are_422(central, body):
    response = central.post("/api/v1/series", json=body, headers=_as(central, "op"))
    assert response.status_code == 422 and response.json()["detail"]


def test_a_failed_source_fails_each_signal_not_the_request(central):
    rt = _rt(central)
    inner = rt.platform.sources.primary

    class Down:
        failed_tags: list = []

        def read_range(self, *_args, **_kwargs):
            raise RuntimeError("historian unreachable")

        def __getattr__(self, name):
            return getattr(inner, name)

    rt.platform.sources.primary = Down()
    response = central.post(
        "/api/v1/series", json={"signals": ["pv", "nope"]}, headers=_as(central, "op")
    )
    assert response.status_code == 200
    errors = {item["signal"]: item for item in response.json()["errors"]}
    assert errors["pv"]["status"] == 502 and "historian unreachable" in errors["pv"]["detail"]
    assert errors["nope"]["status"] == 404


@pytest.mark.parametrize(
    "params", [{"agg": "median"}, {"window": "-1d"}, {"window": "1y"}, {"window": "400d"}]
)
def test_value_requests_outside_the_contract_are_422(central, params):
    response = central.get(
        f"/api/v1/signals/{LOOP_SIGNAL}/value", params=params, headers=_as(central, "op")
    )
    assert response.status_code == 422


def test_audit_records_the_user_from_the_token(central):
    response = central.post(
        "/api/v1/audit",
        json={"action": "protocol.edit", "subject": "loop:FIC-101", "detail": {"gain": 2}},
        headers=_as(central, "eng"),
    )
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id"} and isinstance(body["id"], int)
    entry = _rt(central).workspace.audit.list(limit=1)[0]
    assert entry["username"] == "eng" and entry["action"] == "protocol.edit"
    assert entry["detail"] == {"gain": 2}
    grant = central.post(
        "/api/v1/auth/service-token", json={"app": "linkcraft", "key": _app_key(central)["key"]}
    ).json()
    central.post("/api/v1/audit", json={"action": "round.run"}, headers=_auth(grant["token"]))
    entry = _rt(central).workspace.audit.list(limit=1)[0]
    assert entry["username"] == "app:linkcraft" and entry["app_id"] == "linkcraft"
    bad = central.post("/api/v1/audit", json={"subject": "x"}, headers=_as(central, "eng"))
    assert bad.status_code == 422


# Auth failures ------------------------------------------------------------------------

PROTECTED = [
    ("GET", "/api/v1/me"),
    ("GET", "/api/v1/apps"),
    ("GET", "/api/v1/installation"),
    ("GET", "/api/v1/actions"),
    ("GET", "/api/v1/assets"),
    ("GET", "/api/v1/assets/x"),
    ("GET", "/api/v1/asset-types"),
    ("GET", "/api/v1/explore"),
    ("GET", "/api/v1/signals"),
    ("GET", "/api/v1/signals/pv"),
    ("GET", "/api/v1/signals/pv/series"),
    ("GET", "/api/v1/signals/pv/value"),
    ("POST", "/api/v1/series"),
    ("POST", "/api/v1/audit"),
]
BODIES = {"/api/v1/series": {"signals": ["pv"]}, "/api/v1/audit": {"action": "x"}}


def _forged_tokens(client) -> dict[str, str]:
    rt = _rt(client)
    now = int(time.time())
    claims = {
        "iss": "processcraft",
        "sub": "eng",
        "name": "Eng",
        "level": "editor",
        "apps": {"linkcraft": "editor"},
        "aud": "processcraft",
        "iat": now,
        "exp": now + 600,
    }
    other = jwt.generate_private_key()
    valid = _token(client, "eng")
    head, body, signature = valid.split(".")
    tampered_body = jwt.b64url_encode(json.dumps({**claims, "sub": ADMIN}).encode())
    return {
        "expired": jwt.encode(
            {**claims, "iat": now - 4000, "exp": now - 3600}, rt.tokens._private, rt.tokens.kid
        ),
        "wrong audience": jwt.encode(
            {**claims, "aud": "linkcraft"}, rt.tokens._private, rt.tokens.kid
        ),
        "wrong issuer": jwt.encode(
            {**claims, "iss": "elsewhere"}, rt.tokens._private, rt.tokens.kid
        ),
        "wrong kid": jwt.encode(claims, other, "not-a-processcraft-key"),
        "foreign key, real kid": jwt.encode(claims, other, rt.tokens.kid),
        "tampered": f"{head}.{tampered_body}.{signature}",
        "garbage": "not.a.token",
    }


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_protected_routes_refuse_missing_and_bad_tokens(central, method, path):
    body = {"json": BODIES[path]} if method == "POST" else {}
    missing = central.request(method, path, **body)
    assert missing.status_code == 401 and missing.json()["detail"]
    assert missing.headers["www-authenticate"] == "Bearer"
    for name, token in _forged_tokens(central).items():
        response = central.request(method, path, headers=_auth(token), **body)
        assert response.status_code == 401, (name, response.text)
        central.cookies.set("processcraft_token", token)
        cookie = central.request(method, path, **body)
        central.cookies.clear()
        assert cookie.status_code == 401, name


def test_a_deactivated_person_is_refused_at_once(central):
    headers = _as(central, "eng")
    _rt(central).workspace.users.deactivate("eng")
    assert central.get("/api/v1/me", headers=headers).status_code == 401


def test_dashboards_only_people_do_not_read_plant_data(central):
    headers = _as(central, "wall")
    assert central.get("/api/v1/me", headers=headers).status_code == 200
    for path in (
        "/api/v1/assets",
        "/api/v1/asset-types",
        "/api/v1/signals",
        "/api/v1/signals/pv/series",
    ):
        assert central.get(path, headers=headers).status_code == 403
    batch = central.post("/api/v1/series", json={"signals": ["pv"]}, headers=headers)
    assert batch.status_code == 403


def test_rotated_keys_stay_listed_so_issued_tokens_keep_working(central, tmp_path):
    old = _token(central, "eng")
    rt = _rt(central)
    old_kid = rt.tokens.kid
    new_kid = rt.tokens.rotate()
    assert new_kid != old_kid
    kids = [key["kid"] for key in central.get("/api/v1/auth/keys").json()["keys"]]
    assert kids[0] == new_kid and old_kid in kids
    assert central.get("/api/v1/me", headers=_auth(old)).status_code == 200
    assert jwt.unverified_header(_token(central, "eng"))["kid"] == new_kid
    assert (tmp_path / "tokens.retired.json").stat().st_mode & 0o777 == 0o600


# Read only and complete --------------------------------------------------------------

# What a v1 route may touch on a data source: reads and their bookkeeping.
READ_ONLY = {
    "read_range",
    "read_window",
    "last_time",
    "list_signals",
    "test_connection",
    "failed_tags",
    "last_read_from_cache",
    "config",
}


class SpySource:
    """Wraps the data source and records every attribute used on it."""

    def __init__(self, inner):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "used", [])

    def __getattr__(self, name):
        self.used.append(name)
        return getattr(self._inner, name)

    def __setattr__(self, name, value):
        self.used.append(f"set {name}")
        setattr(self._inner, name, value)


def _v1_routes(app) -> list[tuple[str, str]]:
    return sorted(
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api/v1/")
        for method in operations
    )


def test_no_v1_route_writes_to_a_data_source(central):
    rt = _rt(central)
    spy = SpySource(rt.platform.sources.primary)
    rt.platform.sources.primary = spy
    rt.data._signals = None  # browse again, through the spy
    headers = _as(central, "eng")
    grant = central.post(
        "/api/v1/auth/service-token", json={"app": "linkcraft", "key": _app_key(central)["key"]}
    )
    central.post("/api/login", json={"username": "eng", "password": "password-123"})
    calls = {
        ("GET", "/api/v1/auth/keys"): {},
        ("GET", "/api/v1/auth/revoked"): {},
        ("POST", "/api/v1/auth/token"): {},
        ("POST", "/api/v1/auth/service-token"): {"json": {"app": "x", "key": "y"}},
        ("GET", "/api/v1/me"): {},
        ("GET", "/api/v1/apps"): {},
        ("GET", "/api/v1/installation"): {},
        ("GET", "/api/v1/inbox"): {},
        ("GET", "/api/v1/actions"): {},
        ("GET", "/api/v1/assets"): {},
        ("GET", "/api/v1/assets/{asset_id}"): {"path": "/api/v1/assets/x"},
        ("GET", "/api/v1/explore"): {},
        # Result assets live in the asset tree, never in a source (test_api_v1_results.py).
        ("PUT", "/api/v1/assets/results"): {"json": {"assets": []}},
        ("POST", "/api/v1/assets/results/remove"): {"json": {"ids": ["linkcraft.x"]}},
        ("GET", "/api/v1/asset-types"): {},
        ("GET", "/api/v1/signals"): {},
        ("GET", "/api/v1/signals/{signal_id}"): {"path": "/api/v1/signals/pv"},
        ("GET", "/api/v1/signals/{signal_id}/series"): {"path": "/api/v1/signals/pv/series"},
        ("GET", "/api/v1/signals/{signal_id}/value"): {"path": "/api/v1/signals/pv/value"},
        ("GET", "/api/v1/signals/{signal_id}/runs"): {"path": "/api/v1/signals/pv/runs"},
        ("POST", "/api/v1/series"): {"json": {"signals": ["pv", "mode", "nope"]}},
        # Derived series go to the data layer's own table, never to a plant source.
        ("PUT", "/api/v1/series"): {
            "json": [{"signal": "app-linkcraft:x", "t": ["2026-01-01T00:00:00Z"], "v": [1]}]
        },
        ("POST", "/api/v1/series/retire"): {"json": {"signals": ["app-linkcraft:x"]}},
        ("PUT", "/api/v1/series/runs"): {
            "json": [
                {"signal": "app-linkcraft:r", "run_at": "2026-01-01T00:00:00Z", "t": [], "v": []}
            ]
        },
        ("POST", "/api/v1/audit"): {"json": {"action": "x"}},
        # Results, events, runs and schedules (tests/contract/test_api_v1_links.py).
        ("PUT", "/api/v1/results"): {
            "json": [{"app": "linkcraft", "subject": "signal:pv", "kind": "k", "status": "ok"}]
        },
        ("GET", "/api/v1/results"): {"path": "/api/v1/results?subject=signal:pv"},
        ("GET", "/api/v1/results/history"): {"path": "/api/v1/results/history?subject=signal:pv"},
        ("POST", "/api/v1/events"): {
            "json": {"app": "linkcraft", "kind": "linkcraft.x.done", "subject": "signal:pv"}
        },
        ("PUT", "/api/v1/events/catalog"): {
            "json": {"app": "linkcraft", "events": [{"name": "x.done", "title": "X done"}]}
        },
        ("GET", "/api/v1/events/catalog"): {},
        ("PUT", "/api/v1/contributions"): {
            "json": {"app": "linkcraft", "contributes": {"queue": True}}
        },
        ("GET", "/api/v1/contributions"): {},
        ("GET", "/api/v1/contributions/settings"): {},
        # What an app puts in Desk (tests/contract/test_api_v1_desk.py).
        ("PUT", "/api/v1/calendar/{feed}"): {
            "path": "/api/v1/calendar/reviews?app=linkcraft",
            "json": [{"id": "1", "title": "x", "start": "2026-11-03", "all_day": True}],
        },
        ("POST", "/api/v1/todos"): {
            "path": "/api/v1/todos?app=linkcraft",
            "json": {"key": "k", "kind": "review", "title": "x", "for": "user:eng"},
        },
        ("GET", "/api/v1/todos"): {"path": "/api/v1/todos?app=linkcraft"},
        ("POST", "/api/v1/todos/close"): {
            "path": "/api/v1/todos/close?app=linkcraft",
            "json": {"keys": ["k"]},
        },
        ("GET", "/api/v1/events"): {},
        ("PUT", "/api/v1/runs"): {
            "json": [{"app": "linkcraft", "id": "r", "status": "done", "trigger": "api"}]
        },
        ("GET", "/api/v1/runs"): {},
        ("PUT", "/api/v1/schedules"): {"path": "/api/v1/schedules?app=linkcraft", "json": []},
        ("GET", "/api/v1/schedules"): {},
        # What the apps explain and the assistant beside their objects (tests/test_assistant.py).
        ("PUT", "/api/v1/knowledge"): {
            "json": [{"app": "linkcraft", "ref": "protocol:linkcraft/p", "title": "P", "text": "x"}]
        },
        ("POST", "/api/v1/knowledge/delete"): {"json": {"app": "linkcraft", "refs": ["x:y"]}},
        ("GET", "/api/v1/knowledge"): {},
        ("GET", "/api/v1/assistant"): {"path": "/api/v1/assistant?ref=asset:x"},
        # People, groups and notifications (tests/test_groups_and_notifications.py).
        ("GET", "/api/v1/people"): {},
        # The Notebooks kit's folders (tests/test_notebook_kits.py).
        ("GET", "/api/v1/notebooks"): {},
        ("GET", "/api/v1/notebooks/file"): {"path": "/api/v1/notebooks/file?path=Examples/x"},
        # The apps' objects, forwarded to the app (tests/test_app_objects.py).
        ("GET", "/api/v1/objects"): {},
        ("GET", "/api/v1/apps/{app}/objects/{kind}"): {
            "path": "/api/v1/apps/linkcraft/objects/block"
        },
        ("GET", "/api/v1/apps/{app}/objects/{kind}/{object_id}"): {
            "path": "/api/v1/apps/linkcraft/objects/block/x"
        },
        ("GET", "/api/v1/apps/{app}/notebooks/runtime"): {
            "path": "/api/v1/apps/linkcraft/notebooks/runtime"
        },
        ("POST", "/api/v1/apps/{app}/objects/{kind}/run"): {
            "path": "/api/v1/apps/modelcraft/objects/model/run",
            "json": {"id": "x"},
        },
        # The tools the apps add to the assistant, forwarded to the app (tests/test_app_tools.py).
        ("GET", "/api/v1/tools"): {},
        ("POST", "/api/v1/apps/{app}/tools/{tool_id}"): {
            "path": "/api/v1/apps/doccraft/tools/search_documents",
            "json": {"query": "x"},
        },
        ("GET", "/api/v1/groups"): {},
        ("GET", "/api/v1/notifications"): {},
        ("POST", "/api/v1/notifications"): {"json": {"recipients": ["user:eng"], "title": "x"}},
        ("POST", "/api/v1/notifications/resolve"): {"json": {"key": "alarm:1:1"}},
        ("GET", "/api/v1/queue"): {},
        ("POST", "/api/v1/assistant/conversations"): {
            "json": {"specialist": "nobody", "ref": "asset:x", "text": "hi"}
        },
        ("GET", "/api/v1/assistant/conversations/{conversation_id}"): {
            "path": "/api/v1/assistant/conversations/1"
        },
        ("POST", "/api/v1/assistant/conversations/{conversation_id}/messages"): {
            "path": "/api/v1/assistant/conversations/1/messages",
            "json": {"text": "hi"},
        },
    }
    # Tasks for the compute workers (tests/contract/test_api_v1_compute.py): an app's token only.
    calls.update(
        {
            ("POST", "/api/v1/compute/tasks"): {},
            ("GET", "/api/v1/compute/tasks/{task_id}"): {"path": "/api/v1/compute/tasks/x"},
            ("POST", "/api/v1/compute/wait"): {"json": {"ids": ["x"], "seconds": 0}},
            ("GET", "/api/v1/compute/tasks/{task_id}/output"): {
                "path": "/api/v1/compute/tasks/x/output"
            },
            ("POST", "/api/v1/compute/tasks/{task_id}/cancel"): {
                "path": "/api/v1/compute/tasks/x/cancel"
            },
            ("DELETE", "/api/v1/compute/tasks/{task_id}"): {"path": "/api/v1/compute/tasks/x"},
            ("POST", "/api/v1/compute/runs/{run_id}/cancel"): {
                "path": "/api/v1/compute/runs/x/cancel"
            },
            ("GET", "/api/v1/compute/capacity"): {},
        }
    )
    # An app's call to a language model (tests/contract/test_api_v1_llm.py).
    calls[("POST", "/api/v1/llm/{use}")] = {
        "path": "/api/v1/llm/x",
        "json": {"messages": [{"role": "user", "content": "hi"}]},
    }
    routes = set(_v1_routes(central.app))
    assert routes == set(calls), "every v1 route is exercised here"
    for (method, path), options in calls.items():
        target = options.get("path", path)
        response = central.request(method, target, headers=headers, json=options.get("json"))
        assert response.status_code < 500, (method, path, response.text)
    assert grant.status_code == 200
    assert {"read_range", "list_signals"} <= set(spy.used), "the spy saw the reads"
    assert set(spy.used) <= READ_ONLY, sorted(set(spy.used) - READ_ONLY)
    # Only identity, the audit log, what apps publish (results, events and their catalog, runs, schedules,
    # knowledge, result assets, what an app adds and puts in Desk) and a person's assistant conversations accept writes; the batch read is a
    # POST that reads.
    posts = {path for method, path in routes if method != "GET"}
    assert posts == {
        "/api/v1/auth/token",
        "/api/v1/auth/service-token",
        "/api/v1/series",
        "/api/v1/series/retire",
        "/api/v1/series/runs",
        "/api/v1/audit",
        "/api/v1/assets/results",
        "/api/v1/assets/results/remove",
        "/api/v1/contributions",
        "/api/v1/llm/{use}",
        "/api/v1/calendar/{feed}",
        "/api/v1/todos",
        "/api/v1/todos/close",
        "/api/v1/results",
        "/api/v1/events",
        "/api/v1/events/catalog",
        "/api/v1/runs",
        "/api/v1/schedules",
        "/api/v1/knowledge",
        "/api/v1/knowledge/delete",
        "/api/v1/notifications",
        "/api/v1/notifications/resolve",
        "/api/v1/assistant/conversations",
        "/api/v1/assistant/conversations/{conversation_id}/messages",
        # A notebook asks an app to run an object in its own queue (the app's switch, D4).
        "/api/v1/apps/{app}/objects/{kind}/run",
        # The assistant's tools an app adds are read-only, forwarded to the app (app_tools.py).
        "/api/v1/apps/{app}/tools/{tool_id}",
        # Tasks the apps hand to the compute workers: never a data source (docs/compute.md).
        "/api/v1/compute/tasks",
        "/api/v1/compute/tasks/{task_id}",
        "/api/v1/compute/wait",
        "/api/v1/compute/tasks/{task_id}/cancel",
        "/api/v1/compute/runs/{run_id}/cancel",
    }


def test_the_contract_document_lists_exactly_the_routes_served(central):
    text = (ROOT / "docs" / "api-v1.md").read_text(encoding="utf-8")

    def shape(path: str) -> str:
        return re.sub(r"\{[^}]+\}", "{}", re.sub(r"\?.*$", "", path))

    documented = {
        (method, shape(path))
        for method, path in re.findall(r"^\| `(GET|POST|PUT|DELETE) (/api/v1/[^` ]+)", text, re.M)
    }
    served = {(method, shape(path)) for method, path in _v1_routes(central.app)}
    assert documented == served


def test_the_fake_serves_the_same_shapes(central):
    """Apps test against FakePlantCraft: its answers must look like PlantCraft's."""

    fake = FakePlantCraft(now=datetime(2026, 1, 1, 13, tzinfo=timezone.utc))
    real = PlantCraftClient("http://testserver", _token(central, "eng"), http_client=central)
    faked = fake.client("engineer")
    window = ("2026-01-01T11:00:00Z", "2026-01-01T11:10:00Z")

    def shapes(client, signal_id):
        asset = client.assets()[0]
        return {
            "keys": [set(key) for key in client.keys()],
            "me": set(client.me()),
            "apps": {frozenset(item) for item in client.apps()},
            "assets": set(asset),
            "asset": set(client.asset(asset["id"])),
            "asset types": set(client.asset_types()[0]),
            "type attribute": set(
                next(item for item in client.asset_types() if item["attributes"])["attributes"][0]
            ),
            "type role": set(
                next(item for item in client.asset_types() if item["roles"])["roles"][0]
            ),
            "loop path": next(item for item in client.assets(type="loop"))["type_path"],
            "signals": set(client.signals()[0]),
            "signal": set(client.signal(signal_id)),
            "series": set(client.series(signal_id, *window)),
            "stepped": set(client.series(signal_id, *window, step=60)),
            "batch": set(client.series_many([signal_id, "nope"], *window)),
            "batch series": set(client.series_many([signal_id], *window)["series"][0]),
            "batch error": set(client.series_many(["nope"], *window)["errors"][0]),
            "value": set(client.value(signal_id, "mean", "1h")),
            "audit": set(client.audit("check", "shape")),
        }

    assert shapes(real, LOOP_SIGNAL) == shapes(faked, "FIC-101.PV")
    # A text signal looks alike too (the demo's mode labels; labels given to the fake).
    labels = pd.Series(
        ["AUTO", "MAN"], index=pd.to_datetime(["2026-01-01T11:01:00Z", "2026-01-01T11:02:00Z"])
    )
    texted = FakePlantCraft(series={"FIC-101.MODE": labels}).client("engineer")
    real_mode, fake_mode = real.series("mode", *window), texted.series("FIC-101.MODE", *window)
    assert set(real_mode) == set(fake_mode) and real_mode["kind"] == fake_mode["kind"] == "text"
    assert isinstance(real_mode["v"][0], str) and fake_mode["v"] == ["AUTO", "MAN"]


def test_a_setpoint_recorded_on_change_holds_to_the_end_like_the_fake(tmp_path, monkeypatch):
    """A setpoint written only on change keeps its last value on a grid (no hold limit),
    while a PV's outage stays a gap after ten steps, in PlantCraft and in the fake alike."""

    _scenario(tmp_path, monkeypatch)
    stamps = pd.date_range("2026-01-01 08:00:00", "2026-01-01 09:59:50", freq="10s")
    frame = pd.DataFrame(
        {
            "pv": [51.0] * len(stamps),
            "sp": [50.0 if i < 30 else None for i in range(len(stamps))],  # 5 min, then quiet
            "op": [40.0] * len(stamps),
            "mode": ["auto"] * len(stamps),
        },
        index=pd.Index(stamps, name="timestamp"),
    )
    frame.loc["2026-01-01 09:00:00":"2026-01-01 09:29:50", "pv"] = None  # a PV outage
    csv = tmp_path / "quiet-sp.csv"
    frame.to_csv(csv)
    scenario_path = Path(str(tmp_path / "scenario.json"))
    scenario = json.loads(scenario_path.read_text())
    scenario["source"]["path"] = str(csv)
    scenario_path.write_text(json.dumps(scenario))
    window = ("2026-01-01T11:00:00Z", "2026-01-01T13:00:00Z")
    utc = stamps.tz_localize("America/Sao_Paulo").tz_convert("UTC")
    given = {
        f"fake:FIC-101.{tag.upper()}": pd.Series(frame[tag].to_numpy(), index=utc).dropna()
        for tag in ("pv", "sp")
    }
    faked = FakePlantCraft(series=given).client("engineer")
    with TestClient(create_app()) as client:
        real = PlantCraftClient(
            "http://testserver", issue_user_token(_rt(client), ADMIN)["token"], http_client=client
        )
        sp = real.series("scenario:sp", *window, step=60)["v"]
        pv = real.series("scenario:pv", *window, step=60)["v"]
        batch = real.series_many(["scenario:sp", "scenario:pv"], *window, step=60)["series"]
    assert sp == [50.0] * 120  # before: null from 11:15 on, ten 30 s spacings after 11:05
    assert pv[:70] == [51.0] * 70 and pv[70:90] == [None] * 20 and None not in pv[90:]
    assert [item["v"] for item in batch] == [sp, pv]
    assert faked.series("fake:FIC-101.SP", *window, step=60)["v"] == sp
    assert faked.series("fake:FIC-101.PV", *window, step=60)["v"] == pv


def test_lists_come_in_pages_and_an_unchanged_list_is_a_304(central):
    """Scale review E2 (2026-10-25): signals and assets in pages by id, with an ETag."""

    headers = _as(central, "op")
    whole = central.get("/api/v1/signals", headers=headers)
    ids = [item["id"] for item in whole.json()]
    pages, cursor = [], None
    while True:
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        page = central.get("/api/v1/signals", params=params, headers=headers)
        assert page.status_code == 200 and len(page.json()) <= 2
        assert page.headers["X-Total-Count"] == str(len(ids))
        pages.extend(item["id"] for item in page.json())
        cursor = page.headers.get("X-Next-Cursor")
        if not cursor:
            break
    assert pages == sorted(ids)
    again = central.get(
        "/api/v1/signals", headers={**headers, "If-None-Match": whole.headers["ETag"]}
    )
    assert again.status_code == 304 and not again.content
    assert central.get("/api/v1/signals", params={"limit": 0}, headers=headers).status_code == 422
    assets = central.get("/api/v1/assets", headers=headers)
    first = central.get("/api/v1/assets", params={"limit": 1}, headers=headers)
    assert first.json() == sorted(assets.json(), key=lambda item: item["id"])[:1]
    unchanged = {**headers, "If-None-Match": assets.headers["ETag"]}
    assert central.get("/api/v1/assets", headers=unchanged).status_code == 304
