"""The asset model: types (admins), records, relations and signal roles (editors), the map."""

from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from plantcraft.api.app import create_app
from plantcraft.assets import AssetStore
from plantcraft.db import Database

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "password-123"


@pytest.fixture()
def app(tmp_path, monkeypatch):
    scenario = json.loads((ROOT / "scenarios" / "generic_demo.json").read_text())
    scenario["storage"]["sqlite_path"] = str(tmp_path / "workspace.sqlite3")
    scenario["source"]["path"] = str(ROOT / scenario["source"]["path"])
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario))
    secret = tmp_path / "admin.secret"
    secret.write_text("admin-secret")
    monkeypatch.setenv("PLANTCRAFT_SCENARIO", str(path))
    monkeypatch.setenv("PLANTCRAFT_PREWARM_HISTORY", "false")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_ENABLED", "true")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_USERNAME", "admin")
    monkeypatch.setenv("PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE", str(secret))
    application = create_app()
    with TestClient(application) as client:
        users = client.app.state.runtime.workspace.users
        for username, level in (("eng", "editor"), ("op", "viewer")):
            users.upsert_user(username, username.title(), "")
            users.set_access(username, level, None)
            users.set_password(username, PASSWORD)
        yield application


def _login(app, username: str, password: str = PASSWORD) -> TestClient:
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/api/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return client


@pytest.fixture()
def admin(app):
    return _login(app, "admin", "admin-secret")


@pytest.fixture()
def eng(app):
    return _login(app, "eng")


@pytest.fixture()
def viewer(app):
    return _login(app, "op")


def _rt(client):
    return client.app.state.runtime


PUMP = {
    "name": "Booster",
    "description": "A gas booster.",
    "icon": "box",
    "parent": "equipment",
    "attributes": [
        {"key": "stages", "name": "Stages", "data_type": "number"},
        {"key": "drive", "name": "Drive", "data_type": "choice", "options": ["motor", "turbine"]},
        {"key": "commissioned", "name": "Commissioned", "data_type": "date"},
        {"key": "feeds_unit", "name": "Feeds unit", "data_type": "asset"},
    ],
    "roles": [{"key": "suction_pressure", "name": "Suction pressure", "unit": "bar"}],
    "children": ["instrument"],
}


# Types -------------------------------------------------------------------------------


def test_starter_types_and_the_legacy_kinds(admin):
    body = admin.get("/api/asset-types").json()
    types = {item["id"]: item for item in body["types"]}
    assert [types[key]["name"] for key in ("site", "loop")] == ["Plant", "Control loop"]
    assert types["control_valve"]["path"] == ["equipment", "valve", "control_valve"]
    assert (
        types["loop"]["count"] >= 1 and types["equipment"]["total"] >= types["equipment"]["count"]
    )
    froms = {entry["key"]: entry["from"] for entry in types["control_valve"]["attributes"]}
    assert froms["manufacturer"] == "equipment" and froms["cv"] == "control_valve"
    assert body["data_types"] == ["text", "number", "choice", "date", "asset"]
    assert {item["id"] for item in body["relations"]} == {
        "controls",
        "measures",
        "feeds",
        "downstream_of",
    }
    # The tree's filter chips still list the kinds, now from the types.
    kinds = {item["kind"]: item for item in admin.get("/api/assets").json()["kinds"]}
    assert kinds["loop"]["label"] == "Control loop" and kinds["pump"]["parent"] == "equipment"


def test_admin_creates_edits_and_removes_a_type_and_children_inherit(admin):
    created = admin.post("/api/asset-types", json=PUMP)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["id"] == "booster" and body["path"] == ["equipment", "booster"]
    keys = [entry["key"] for entry in body["attributes"]]
    assert keys[0] == "manufacturer" and "stages" in keys
    child = admin.post(
        "/api/asset-types",
        json={"id": "screw_booster", "name": "Screw booster", "parent": "booster"},
    )
    assert child.status_code == 201
    # A change to the parent reaches the child at once.
    changed = {**PUMP, "attributes": [*PUMP["attributes"], {"key": "rated_power", "name": "Power"}]}
    assert admin.put("/api/asset-types/booster", json=changed).status_code == 200
    resolved = admin.get("/api/asset-types/screw_booster").json()
    assert "rated_power" in [entry["key"] for entry in resolved["attributes"]]
    assert resolved["roles"][0]["key"] == "suction_pressure"
    # Removing: not while a subtype or an asset uses it.
    assert admin.delete("/api/asset-types/booster").status_code == 422
    asset = admin.post("/api/assets", json={"name": "K-101", "kind": "screw_booster"}).json()
    assert admin.delete("/api/asset-types/screw_booster").status_code == 422
    admin.patch(f"/api/assets/{asset['asset_id']}", json={"kind": "equipment"})
    assert admin.delete("/api/asset-types/screw_booster").status_code == 204
    assert admin.delete("/api/asset-types/booster").status_code == 204
    assert admin.delete("/api/asset-types/loop").status_code == 422  # the platform's own
    assert admin.get("/api/asset-types/booster").status_code == 404
    entries = _rt(admin).workspace.audit.list(limit=20)
    assert {"asset_type.create", "asset_type.update", "asset_type.delete"} <= {
        item["action"] for item in entries
    }
    assert all(
        item["username"] == "admin" for item in entries if item["action"].startswith("asset_type")
    )


def test_only_admins_edit_types(eng, viewer):
    for client in (eng, viewer):
        assert client.get("/api/asset-types").status_code == 200
        assert client.post("/api/asset-types", json=PUMP).status_code == 403
        assert client.put("/api/asset-types/pump", json=PUMP).status_code == 403
        assert client.delete("/api/asset-types/pump").status_code == 403


BAD_TYPES = [
    ({"name": ""}, 422),
    ({"name": "x" * 61}, 422),
    ({"name": "Pump"}, 409),  # the name is taken
    ({"id": "pump", "name": "Other pump"}, 409),  # the id is taken
    ({"id": "Bad-Id", "name": "Bad"}, 422),
    ({"id": "signals", "name": "Signals"}, 422),  # a sheet of the plant map
    ({"name": "Bad", "parent": "nope"}, 422),
    ({"name": "Bad", "parent": "x" * 100}, 422),
    ({"name": "Bad", "icon": "<svg>"}, 422),
    ({"name": "Bad", "attributes": [{"key": "Bad Key", "name": "x"}]}, 422),
    ({"name": "Bad", "attributes": [{"key": "description", "name": "x"}]}, 422),
    ({"name": "Bad", "attributes": [{"key": "a", "name": "A"}, {"key": "a", "name": "B"}]}, 422),
    ({"name": "Bad", "attributes": [{"key": "a", "data_type": "colour"}]}, 422),
    ({"name": "Bad", "attributes": [{"key": "a", "data_type": "choice"}]}, 422),
    ({"name": "Bad", "attributes": [{"key": "a", "data_type": "text", "options": ["x"]}]}, 422),
    ({"name": "Bad", "attributes": [{"key": "a", "data_type": "number", "default": "abc"}]}, 422),
    (
        {"name": "Bad", "attributes": [{"key": "a", "data_type": "asset", "default": "FIC-101"}]},
        422,
    ),
    (
        {
            "name": "Bad",
            "attributes": [{"key": "a", "data_type": "choice", "options": ["x"], "default": "y"}],
        },
        422,
    ),
    ({"name": "Bad", "parent": "equipment", "attributes": [{"key": "manufacturer"}]}, 422),
    ({"name": "Bad", "attributes": [{"key": "flow"}], "roles": [{"key": "flow"}]}, 422),
    ({"name": "Bad", "parent": "pump", "attributes": [{"key": "flow"}]}, 422),  # pump's role
    ({"name": "Bad", "roles": [{"key": "pv"}, {"key": "pv"}]}, 422),
    ({"name": "Bad", "children": ["nope"]}, 422),
    ({"name": "Bad", "attributes": [{"key": f"k{i}"} for i in range(101)]}, 422),
    (
        {
            "name": "Bad",
            "attributes": [{"key": "a", "data_type": "choice", "options": ["x" * 121]}],
        },
        422,
    ),
    ({"name": "Bad", "description": "x" * 100_000}, 422),
    ({"name": "Bad", "attributes": "not a list"}, 422),
    ({"name": "Bad", "attributes": [{"key": "a", "default": {"nested": [1, 2]}}]}, 422),
]


@pytest.mark.parametrize(("body", "status"), BAD_TYPES)
def test_bad_type_definitions_are_refused_with_a_reason(admin, body, status):
    response = admin.post("/api/asset-types", json=body)
    assert response.status_code == status, response.text
    assert response.json()["detail"]


def test_inheritance_never_loops(admin):
    assert admin.post("/api/asset-types", json={"id": "a_type", "name": "A"}).status_code == 201
    assert (
        admin.post(
            "/api/asset-types", json={"id": "b_type", "name": "B", "parent": "a_type"}
        ).status_code
        == 201
    )
    assert (
        admin.post(
            "/api/asset-types", json={"id": "c_type", "name": "C", "parent": "b_type"}
        ).status_code
        == 201
    )
    for parent in ("a_type", "b_type", "c_type"):
        response = admin.put("/api/asset-types/a_type", json={"name": "A", "parent": parent})
        assert response.status_code == 422, parent
    # The platform's own types stay at the top.
    response = admin.put(
        "/api/asset-types/loop", json={"name": "Control loop", "parent": "equipment"}
    )
    assert response.status_code == 422
    # A parent's new key may not clash with a key a subtype already has.
    admin.put(
        "/api/asset-types/b_type",
        json={"name": "B", "parent": "a_type", "attributes": [{"key": "size"}]},
    )
    clash = admin.put(
        "/api/asset-types/a_type", json={"name": "A", "attributes": [{"key": "size"}]}
    )
    assert clash.status_code == 422 and "subtype" in clash.json()["detail"]
    assert admin.get("/api/asset-types/c_type").json()["path"] == ["a_type", "b_type", "c_type"]


def test_starter_types_are_placed_once_and_old_kinds_become_types(tmp_path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE asset_kinds (kind TEXT PRIMARY KEY, label TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO asset_kinds VALUES ('compressor-train', 'Compressor train', '2026-01-01')"
        )
    store = AssetStore(Database(path))
    adopted = store.types.resolved("compressor-train")
    assert adopted["name"] == "Compressor train" and adopted["path"] == [
        "equipment",
        "compressor-train",
    ]
    store.save("K-1", name="K-1", kind="compressor-train")
    assert store.get("K-1")["kind_label"] == "Compressor train"
    store.types.delete("pump", in_use=0)
    store.types.delete("compressor-train", in_use=0)
    again = AssetStore(Database(path))
    assert not again.types.exists("pump") and not again.types.exists("compressor-train")
    assert again.types.exists("control_valve")


# Records ---------------------------------------------------------------------------


def test_editors_fill_the_record_and_each_change_is_in_the_history(eng, viewer):
    response = eng.patch(
        "/api/assets/FIC-101/attributes",
        json={"values": {"loop_type": "Flow", "criticality": "high", "action": "reverse"}},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["attributes"] == {"loop_type": "flow", "criticality": "high", "action": "reverse"}
    assert {item["key"] for item in body["changes"]} == {"loop_type", "criticality", "action"}
    again = eng.patch("/api/assets/FIC-101/attributes", json={"values": {"criticality": "high"}})
    assert again.json()["changes"] == []  # nothing changed, nothing recorded
    eng.patch("/api/assets/FIC-101/attributes", json={"values": {"criticality": None}})
    detail = eng.get("/api/assets/FIC-101").json()
    assert "criticality" not in detail["attributes"]
    changes = [event for event in detail["timeline"] if event["kind"] == "asset.attributes_changed"]
    assert len(changes) == 2 and all(event["actor"] == "eng" for event in changes)
    assert "Criticality: high → —" in changes[0]["summary"]
    assert changes[0]["at"]
    audit = [
        item
        for item in _rt(eng).workspace.audit.list(limit=10)
        if item["action"] == "asset.attributes_changed"
    ]
    assert audit and audit[0]["username"] == "eng" and audit[0]["subject"] == "asset:FIC-101"
    assert detail["missing"] == {"attributes": [], "roles": []}  # the demo loop has pv and op
    assert (
        viewer.patch(
            "/api/assets/FIC-101/attributes", json={"values": {"loop_type": "level"}}
        ).status_code
        == 403
    )


BAD_VALUES = [
    {"nope": 1},
    {"loop_type": "viscosity"},
    {"loop_type": 3},
    {"loop_type": "x" * 3000},
    {"criticality": ["high"]},
    {"x" * 50: 1},
]


@pytest.mark.parametrize("values", BAD_VALUES)
def test_wrong_values_are_refused_and_nothing_is_written(eng, values):
    response = eng.patch(
        "/api/assets/FIC-101/attributes", json={"values": {"action": "direct", **values}}
    )
    assert response.status_code == 422, response.text
    assert eng.get("/api/assets/FIC-101").json()["attributes"] == {}


def test_values_by_data_type(admin):
    admin.post("/api/asset-types", json=PUMP)
    asset = admin.post("/api/assets", json={"name": "K-201", "kind": "booster"}).json()
    url = f"/api/assets/{asset['asset_id']}/attributes"
    ok = admin.patch(
        url,
        json={
            "values": {
                "stages": "3",
                "drive": "TURBINE",
                "commissioned": "2024-05-01",
                "feeds_unit": "FIC-101",
            }
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["attributes"]["stages"] == 3 and ok.json()["attributes"]["drive"] == "turbine"
    for values in (
        {"stages": "three"},
        {"stages": True},
        {"stages": "inf"},
        {"commissioned": "yesterday"},
        {"feeds_unit": "NO-SUCH-ASSET"},
        {"feeds_unit": asset["asset_id"]},  # itself
    ):
        assert admin.patch(url, json={"values": values}).status_code == 422, values
    # Required attributes cannot be cleared.
    required = {
        **PUMP,
        "attributes": [{**PUMP["attributes"][0], "required": True}, *PUMP["attributes"][1:]],
    }
    admin.put("/api/asset-types/booster", json=required)
    assert admin.patch(url, json={"values": {"stages": None}}).status_code == 422
    assert admin.patch("/api/assets/no-such/attributes", json={"values": {}}).status_code == 404


def test_the_tree_filters_by_type_with_each_record(admin):
    admin.post("/api/assets", json={"name": "FV-2001", "kind": "control_valve"})
    admin.post("/api/assets", json={"name": "LV-2002", "kind": "valve"})
    admin.patch("/api/assets/fv-2001/attributes", json={"values": {"characteristic": "linear"}})
    valves = admin.get("/api/assets", params={"type": "valve"}).json()["items"]
    assert {item["asset_id"] for item in valves} == {"fv-2001", "lv-2002"}
    by_id = {item["asset_id"]: item for item in valves}
    assert by_id["fv-2001"]["attributes"] == {"characteristic": "linear"}


# Relations and roles ---------------------------------------------------------------------


def test_relations_both_ways_and_in_both_histories(eng, admin):
    admin.post("/api/assets", json={"name": "FV-101", "kind": "control_valve"})
    added = eng.post("/api/assets/FIC-101/relations", json={"type": "controls", "to": "fv-101"})
    assert added.status_code == 201, added.text
    assert added.json()["outgoing"][0]["asset"]["asset_id"] == "fv-101"
    assert (
        eng.post(
            "/api/assets/FIC-101/relations", json={"type": "controls", "to": "fv-101"}
        ).status_code
        == 201
    )
    valve = eng.get("/api/assets/fv-101").json()
    assert valve["relations"]["incoming"][0]["label"] == "Controlled by"
    assert valve["relations"]["incoming"][0]["asset"]["asset_id"] == "FIC-101"
    assert any(event["kind"] == "asset.relation_added" for event in valve["timeline"])
    for body, status in (
        ({"type": "owns", "to": "fv-101"}, 422),
        ({"type": "controls", "to": "FIC-101"}, 422),
        ({"type": "controls", "to": "nope"}, 404),
        ({"type": "controls", "to": "x" * 500}, 422),
    ):
        assert eng.post("/api/assets/FIC-101/relations", json=body).status_code == status, body
    removed = eng.delete(
        "/api/assets/FIC-101/relations", params={"type": "controls", "to": "fv-101"}
    )
    assert removed.status_code == 204
    assert eng.get("/api/assets/FIC-101").json()["relations"] == {"outgoing": [], "incoming": []}
    # Removing the asset removes its relations.
    eng.post("/api/assets/FIC-101/relations", json={"type": "controls", "to": "fv-101"})
    admin.delete("/api/assets/fv-101")
    assert _rt(admin).workspace.assets.relations() == []


def test_binding_a_signal_fills_a_role(eng):
    store = _rt(eng).workspace.assets
    root = _rt(eng).platform.root_asset_id
    store.save("FIC-900", name="FIC-900", kind="loop", parent_id=root)
    assert eng.get("/api/assets/FIC-900").json()["missing"]["roles"] == ["pv", "op"]
    bound = eng.post("/api/assets/FIC-900/signals", json={"signal_id": "pv", "role": "pv"})
    assert bound.status_code == 201, bound.text
    eng.post("/api/assets/FIC-900/signals", json={"signal_id": "neighbor_pv", "role": "pv"})
    signals = eng.get("/api/assets/FIC-900").json()["signals"]
    assert [(item["signal_id"], item["role"]) for item in signals] == [("neighbor_pv", "pv")]
    assert (
        eng.post(
            "/api/assets/FIC-900/signals", json={"signal_id": "op", "role": "flow"}
        ).status_code
        == 422
    )
    assert (
        eng.post(
            "/api/assets/FIC-900/signals", json={"signal_id": "x" * 400, "role": "op"}
        ).status_code
        == 422
    )
    assert (
        eng.delete("/api/assets/FIC-900/signals", params={"signal_id": "neighbor_pv"}).status_code
        == 204
    )
    # Scenario bindings are the scenario's.
    assert eng.delete("/api/assets/FIC-101/signals", params={"signal_id": "pv"}).status_code == 422


def test_a_role_binds_the_api_v1_signal_id_or_a_tag(eng):
    """The picker lists API v1 ids (scenario:pv); the binding keeps the tag and its source."""

    rt = _rt(eng)
    rt.workspace.assets.save(
        "FIC-901", name="FIC-901", kind="loop", parent_id=rt.platform.root_asset_id
    )
    bound = eng.post("/api/assets/FIC-901/signals", json={"signal_id": "scenario:pv", "role": "pv"})
    assert bound.status_code == 201, bound.text
    eng.post("/api/assets/FIC-901/signals", json={"signal_id": "op", "role": "op"})
    signals = {item["role"]: item for item in eng.get("/api/assets/FIC-901").json()["signals"]}
    assert (signals["pv"]["signal_id"], signals["pv"]["source_id"]) == ("pv", "scenario")
    assert (signals["op"]["signal_id"], signals["op"]["source_id"]) == ("op", "scenario")
    token = eng.post("/api/v1/auth/token").json()["token"]
    loop = eng.get("/api/v1/assets/FIC-901", headers={"Authorization": f"Bearer {token}"}).json()
    assert loop["signals"] == {"pv": "scenario:pv", "op": "scenario:op"}
    # The internal value route reads a v1 id as its tag.
    by_id = eng.get("/api/signals/scenario:pv/value").json()
    assert (
        by_id["tag"] == "pv" and by_id["value"] == eng.get("/api/signals/pv/value").json()["value"]
    )
    removed = eng.delete("/api/assets/FIC-901/signals", params={"signal_id": "scenario:pv"})
    assert removed.status_code == 204
    assert [item["role"] for item in eng.get("/api/assets/FIC-901").json()["signals"]] == ["op"]


def test_old_databases_gain_the_binding_source_column(tmp_path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE assets (asset_id TEXT PRIMARY KEY, parent_id TEXT, kind TEXT NOT NULL, "
            "name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', origin TEXT NOT NULL "
            "DEFAULT 'manual', position INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, "
            "updated_at TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE asset_signals (asset_id TEXT NOT NULL, signal_id TEXT NOT NULL, "
            "role TEXT NOT NULL DEFAULT '', name TEXT NOT NULL DEFAULT '', unit TEXT NOT NULL "
            "DEFAULT '', origin TEXT NOT NULL DEFAULT 'manual', PRIMARY KEY (asset_id, signal_id, origin))"
        )
        connection.execute(
            "INSERT INTO assets VALUES ('L-1', NULL, 'loop', 'L-1', '', 'manual', 0, 'x', 'x')"
        )
        connection.execute(
            "INSERT INTO asset_signals VALUES ('L-1', 'FIC 1\\PV', 'pv', '', '', 'manual')"
        )
    store = AssetStore(Database(path))
    assert store.binding_sources() == {"FIC 1\\PV": ""}
    assert store.set_binding_sources({"FIC 1\\PV": "pi"}) == 1
    assert store.set_binding_sources({"FIC 1\\PV": "pi"}) == 0
    assert AssetStore(Database(path)).signals("L-1")[0]["source_id"] == "pi"


# The plant map ---------------------------------------------------------------------------


def _send(client, route: str, payload, name: str = "map.json") -> dict:
    content = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    response = client.post(route, params={"filename": name}, content=content)
    assert response.status_code == 200, response.text
    return response.json()


def test_the_template_imports_with_one_sheet_per_type_and_relations(admin):
    template = admin.get("/api/map/template.json").json()
    assert {"unit", "pump", "control_valve", "instrument", "relations"} <= set(template)
    assert "site" not in template and "loop" not in template
    report = _send(admin, "/api/map/apply", template)
    assert report["applied"], report["issues"]
    store = _rt(admin).workspace.assets
    assert store.get("B-201A")["kind"] == "pump" and store.get("FV-2001")["kind"] == "control_valve"
    assert store.attributes("B-201A")["rated_flow"] == 120
    assert {item["role"]: item["signal_id"] for item in store.signals("B-201A")} == {
        "flow": "UT.B201A.Flow"
    }
    assert store.attributes("FIC-2001")["loop_type"] == "flow"
    assert {(item["from_id"], item["relation"], item["to_id"]) for item in store.relations()} == {
        ("FIC-2001", "controls", "FV-2001"),
        ("FT-2001", "measures", "B-201A"),
    }
    history = admin.get("/api/assets/B-201A").json()["timeline"]
    assert any(
        event["kind"] == "asset.attributes_changed" and event["actor"] == "admin"
        for event in history
    )
    again = _send(admin, "/api/map/preview", template)
    assert again["changes"] == [], again["changes"]


def test_export_has_a_sheet_per_type_and_reimports_without_changes(admin):
    _send(admin, "/api/map/apply", admin.get("/api/map/template.json").json())
    admin.patch("/api/assets/FIC-101/attributes", json={"values": {"criticality": "medium"}})
    exported = admin.get("/api/map/export.json").json()
    assert exported["assets"] == []
    assert [row["asset_id"] for row in exported["pump"]] == ["B-201A"]
    assert exported["pump"][0]["flow"] == "UT.B201A.Flow" and exported["pump"][0]["power"] == 75
    loops = {row["loop_id"]: row for row in exported["loops"]}
    assert loops["FIC-101"]["criticality"] == "medium"
    assert len(exported["relations"]) == 2
    assert _send(admin, "/api/map/preview", exported)["changes"] == []
    workbook = admin.get("/api/map/export.xlsx").content
    sheets = pd.read_excel(io.BytesIO(workbook), sheet_name=None)
    assert {"pump", "control_valve", "instrument", "relations", "loops"} <= set(sheets)
    assert {"rated_flow", "flow", "discharge_pressure"} <= set(sheets["pump"].columns)
    report = _send(admin, "/api/map/preview", workbook, name="map.xlsx")
    assert report["can_apply"] and report["changes"] == [], report["changes"]
    # Pruning with only the pump sheet removes no other type's assets.
    pruned = admin.post(
        "/api/map/preview",
        params={"filename": "map.json", "prune": "true"},
        content=json.dumps({"pump": exported["pump"]}).encode(),
    ).json()
    assert all(
        item["section"] == "pump" or item["action"] != "remove" for item in pruned["changes"]
    )


def test_map_rows_outside_the_types_are_reported_per_line(admin):
    payload = {
        "pump": [
            {"asset_id": "P-1", "name": "P-1", "power": "lots"},
            {"asset_id": "P-2", "name": "P-2", "pump_type": "screw"},
            {"asset_id": "P-3", "name": "P-3", "colour": "red"},
            {"asset_id": "P 4", "name": "P-4"},
        ],
        "valve": [{"asset_id": "P-3", "name": "Twice"}],
        "relations": [
            {"from_id": "P-3", "type": "owns", "to_id": "FIC-101"},
            {"from_id": "P-3", "type": "measures", "to_id": "NOPE"},
            {"from_id": "P-3", "type": "feeds", "to_id": "P-3"},
            {"from_id": "P-3", "type": "Downstream of", "to_id": "FIC-101"},
        ],
    }
    report = _send(admin, "/api/map/preview", payload)
    found = {(item["sheet"], item["line"], item["level"]) for item in report["issues"]}
    assert ("pump", 1, "error") in found and ("pump", 2, "error") in found
    assert ("pump", None, "warning") in found  # colour is not an attribute
    assert ("pump", 4, "error") in found
    assert ("valve", 1, "error") in found  # P-3 is the pump sheet's
    assert {("relations", line, "error") for line in (1, 2, 3)} <= found
    assert ("relations", 4, "error") not in found


def test_scenario_loops_take_their_record_from_the_map(admin):
    payload = {
        "loops": [
            {
                "loop_id": "FIC-101",
                "name": "Feed flow",
                "pv": "pv",
                "loop_type": "flow",
                "controller": "SLC",
            }
        ]
    }
    report = _send(admin, "/api/map/apply", payload)
    assert report["applied"]
    store = _rt(admin).workspace.assets
    assert store.attributes("FIC-101") == {"loop_type": "flow", "controller": "SLC"}
    assert store.get("FIC-101")["origin"] == "scenario"


def test_scenario_metadata_fills_the_record_without_overwriting_it(admin):
    runtime = _rt(admin)
    store = runtime.workspace.assets
    loop = runtime.scenario.loops[0]
    loop.metadata.update(loop_type="Level", criticality="high", action="sideways", other=1)
    store.set_attributes(loop.loop_id, {"criticality": "low"}, actor="eng")
    runtime.sync_assets()
    # The type is filled, a person's criticality stays, a value the type refuses is skipped.
    assert store.attributes(loop.loop_id) == {"loop_type": "level", "criticality": "low"}
    detail = admin.get(f"/api/assets/{loop.loop_id}").json()
    filled = [
        event
        for event in detail["timeline"]
        if event["kind"] == "asset.attributes_changed" and event["actor"] == "scenario"
    ]
    assert len(filled) == 1
    store.set_attributes(loop.loop_id, {"loop_type": "flow"}, actor="eng")
    runtime.sync_assets()
    assert store.attributes(loop.loop_id)["loop_type"] == "flow"


def test_a_hand_made_asset_keeps_its_tag_as_given(admin):
    created = admin.post(
        "/api/assets", json={"asset_id": " LV-2004 ", "name": "Drum level", "kind": "loop"}
    )
    assert created.status_code == 201, created.text
    assert created.json()["asset_id"] == "LV-2004"
    assert admin.get("/api/assets/LV-2004").status_code == 200
    again = admin.post("/api/assets", json={"asset_id": "LV-2004", "name": "Other"})
    assert again.status_code == 409
    for bad in ["LV 2004", "x" * 129]:
        response = admin.post("/api/assets", json={"asset_id": bad, "name": "Bad"})
        assert response.status_code == 422, bad
