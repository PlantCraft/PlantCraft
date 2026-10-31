"""The asset model: starter types, inheritance and the fake's asset routes."""

from __future__ import annotations

from plantcraft_sdk.assets import (
    STARTER_TYPES,
    effective_attributes,
    resolve_types,
    subtypes,
    type_path,
)
from plantcraft_sdk.testing import FakePlantCraft


def test_starter_types_resolve_with_inheritance():
    types = {item["id"]: item for item in resolve_types(STARTER_TYPES)}
    valve = types["control_valve"]
    assert valve["path"] == ["equipment", "valve", "control_valve"]
    keys = [entry["key"] for entry in valve["attributes"]]
    assert keys[:2] == ["manufacturer", "model"] and keys[-1] == "cv"
    assert [entry["key"] for entry in valve["roles"]] == ["position", "command"]
    loop = types["loop"]
    assert {entry["key"] for entry in loop["roles"] if entry["required"]} == {"pv", "op"}
    assert [entry["key"] for entry in loop["attributes"]] == [
        "loop_type",
        "criticality",
        "action",
        "controller",
    ]
    assert set(types["equipment"]["children"]) >= {"equipment", "pump", "valve", "control_valve"}


def test_a_circular_chain_stops_instead_of_looping():
    definitions = {
        "a": {"id": "a", "parent": "b"},
        "b": {"id": "b", "parent": "a"},
    }
    assert type_path(definitions, "a") == ["b", "a"]
    assert subtypes(definitions, "a") == {"a", "b"}
    assert type_path(definitions, "unknown") == ["unknown"]


def test_defaults_fill_missing_values():
    resolved = {
        "attributes": [
            {"key": "criticality", "default": "medium"},
            {"key": "loop_type", "default": None},
        ]
    }
    assert effective_attributes(resolved, {}) == {"criticality": "medium"}
    assert effective_attributes(resolved, {"loop_type": "flow", "gone": 1}) == {
        "criticality": "medium",
        "loop_type": "flow",
    }


def test_the_fake_serves_types_type_paths_and_relations():
    client = FakePlantCraft().client("operator")
    types = {item["id"]: item for item in client.asset_types()}
    assert types["loop"]["name"] == "Control loop"
    loops = client.assets(type="loop")
    assert {item["id"] for item in loops} == {"fic-101", "lic-102"}
    fic = client.asset("fic-101")
    assert fic["type_path"] == ["loop"] and fic["attributes"]["criticality"] == "high"
    assert fic["relations"] == [{"type": "controls", "to": "fv-101"}]
    assert client.asset("fv-101")["type_path"] == ["equipment", "valve", "control_valve"]
    assert {item["id"] for item in client.assets(type="valve")} == {"fv-101"}
    assert client.assets(kind="valve") == []


def test_the_fake_takes_its_own_types():
    custom = [
        {"id": "loop", "name": "Loop", "attributes": [], "roles": [{"key": "pv", "name": "PV"}]},
        {"id": "cascade", "name": "Cascade", "parent": "loop", "roles": [{"key": "pv2"}]},
    ]
    fake = FakePlantCraft(
        asset_types=custom,
        assets=[{"id": "x", "name": "X", "kind": "cascade", "parent_id": None}],
    )
    client = fake.client("operator")
    assert client.assets(type="loop")[0]["type_path"] == ["loop", "cascade"]
    cascade = next(item for item in client.asset_types() if item["id"] == "cascade")
    assert [entry["key"] for entry in cascade["roles"]] == ["pv", "pv2"]


def test_a_multivariable_controller_holds_mvs_and_cvs_with_the_same_roles():
    types = {item["id"]: item for item in resolve_types(STARTER_TYPES)}
    assert types["apc"]["children"] == ["apc_mv", "apc_cv"]
    assert [entry["key"] for entry in types["apc"]["roles"] if entry["required"]] == ["on"]
    roles = ["value", "lo", "hi", "target", "status", "shadow_price"]
    for kind in ("apc_mv", "apc_cv"):
        assert types[kind]["path"] == ["apc_variable", kind]
        assert [entry["key"] for entry in types[kind]["roles"]] == roles
        assert [entry["key"] for entry in types[kind]["attributes"]] == ["limit_band"]
    assert "apc" in types["unit"]["children"] and "apc" in types["area"]["children"]
