"""Loops through PlantCraft's asset catalog: types, attributes, roles and incomplete records."""

from __future__ import annotations

import pytest

from linkcraft.config import LoopConfig, LoopSignals
from linkcraft.loops.sync import (
    is_loop,
    loop_from_asset,
    loops_from_processcraft,
    required_roles_by_type,
)
from tests.conftest import client_for, make_runtime
from tests.plant import RESOLVED_TYPES, make_fake, sid


@pytest.fixture
def catalog(tmp_path):
    fake = make_fake(catalog=True)
    rt = make_runtime(tmp_path, fake)
    yield rt, fake
    rt.shutdown()


def _asset(fake, asset_id):
    return next(item for item in fake.assets if item["id"] == asset_id)


def test_loop_type_and_criticality_come_from_the_asset_record(catalog):
    rt, _fake = catalog
    result = rt.sync_loops()
    assert result["status"] == "ok" and result["added"] == 6

    flow = rt.loops.get_loop("fic-101")
    assert flow.profile_id == "flow_loop"
    assert flow.metadata["criticality"] == "high"
    record = flow.asset_record
    assert record.loop_type == "flow" and record.action == "reverse" and record.controller == "DCS"
    assert record.type_path == ["loop"] and record.roles_source == "asset_types"
    assert record.required_roles == ["pv", "op"]
    assert record.relations == [{"type": "feeds", "to": "pic-103"}]

    pressure = rt.loops.get_loop("pic-103")
    assert pressure.profile_id == "temperature_loop"
    assert pressure.metadata["criticality"] == "low"
    # No loop type: the generic protocol and the default criticality, as before the catalog.
    level = rt.loops.get_loop("lic-102")
    assert level.profile_id == "flow_loop" and level.metadata["criticality"] == "medium"


def test_the_ui_is_told_where_each_setting_comes_from(catalog):
    rt, fake = catalog
    rt.sync_loops()
    with client_for(rt, fake) as client:
        detail = client.get("/link/api/loops/fic-101").json()
        assert detail["settings_source"] == {
            "profile_id": "asset",
            "criticality": "asset",
            "method_parameters": "asset",
        }
        assert detail["record_defaults"] == {"profile_id": "flow_loop", "criticality": "high"}
        generic = client.get("/link/api/loops/lic-102").json()
        assert generic["settings_source"]["profile_id"] == "default"

        changed = client.patch("/link/api/loops/fic-101", json={"profile_id": "surge_level"})
        assert changed.status_code == 200
        detail = client.get("/link/api/loops/fic-101").json()
        assert detail["settings_source"]["profile_id"] == "here"
        assert detail["settings_source"]["criticality"] == "asset"


def test_a_setting_chosen_here_survives_a_sync_and_can_be_reset(catalog):
    rt, fake = catalog
    rt.sync_loops()
    with client_for(rt, fake) as client:
        assert client.patch(
            "/link/api/loops/fic-101", json={"profile_id": "surge_level"}
        ).is_success
        # PlantCraft changes the record: the protocol chosen here stays, criticality follows.
        _asset(fake, "fic-101")["attributes"].update(loop_type="level", criticality="low")
        rt.sync_loops()
        loop = rt.loops.get_loop("fic-101")
        assert loop.profile_id == "surge_level" and loop.set_here == ["profile_id"]
        assert loop.metadata["criticality"] == "low"

        assert client.patch("/link/api/loops/fic-101", json={"criticality": "critical"}).is_success
        _asset(fake, "fic-101")["attributes"]["criticality"] = "high"
        rt.sync_loops()
        assert rt.loops.get_loop("fic-101").metadata["criticality"] == "critical"

        reset = client.patch(
            "/link/api/loops/fic-101", json={"reset": ["profile_id", "criticality"]}
        )
        assert reset.status_code == 200
        loop = rt.loops.get_loop("fic-101")
        assert loop.profile_id == "level_loop" and loop.metadata["criticality"] == "high"
        assert loop.set_here == []
        user_loop = client.post(
            "/link/api/loops",
            json={"loop_id": "U-1", "name": "Mine", "signals": {"pv": sid("FIC-101.PV")}},
        )
        assert user_loop.status_code == 201
        refused = client.patch("/link/api/loops/U-1", json={"reset": ["profile_id"]})
        assert refused.status_code == 409


def test_loop_type_parameters_sit_under_the_algorithm_and_the_loop(catalog):
    rt, _fake = catalog
    rt.sync_loops()
    loop = rt.loops.get_loop("fic-101")
    config = rt.loops.effective_method_config(loop)
    assert config["profile_id"] == "flow_loop"
    assert config["parameters"]["op_travel_reversal"]["max_travel_per_hour"] == 400.0
    # The flow type tunes noise as well (once the flow protocol's own setting).
    assert config["parameters"]["sensor_noise_ratio"]["noise_ratio_threshold"] == 0.25
    tuned = loop.model_copy(
        update={"method_parameters": {"op_travel_reversal": {"max_travel_per_hour": 250.0}}}
    )
    assert (
        rt.loops.effective_method_config(tuned)["parameters"]["op_travel_reversal"][
            "max_travel_per_hour"
        ]
        == 250.0
    )


def test_an_asset_missing_a_required_role_is_an_incomplete_record(catalog):
    rt, fake = catalog
    rt.run_round()
    loop = rt.loops.get_loop("fic-106")
    assert loop.incomplete and loop.asset_record.missing_roles == ["op"]
    assert loop.enabled
    rows = {row["loop_id"]: row for row in rt.monitor.overview_rows()}
    row = rows["fic-106"]
    assert row["status"] == "incomplete" and row["missing_roles"] == ["op"]
    assert "OP" in row["state_reason"] and "PlantCraft" in row["state_reason"]
    assert row["health"] is None
    # Never analysed, and a run on it is refused with the reason.
    assert rt.latest.get("cpm", "loop", "fic-106") is None
    assert "fic-106" not in {item.loop_id for item in rt.loops.list_loops(enabled_only=True)}
    with client_for(rt, fake) as client:
        detail = client.get("/link/api/loops/fic-106").json()
        assert detail["incomplete"] is True and detail["missing_roles"] == ["op"]
        assert detail["summary"]["status"] == "incomplete" and detail["results"] == []
        refused = client.post("/link/api/jobs", json={"loop_id": "fic-106", "name": "try"})
        assert refused.status_code == 409 and "OP" in refused.json()["detail"]
        batch = client.post("/link/api/jobs/batch", json={"loop_ids": ["fic-106"]})
        assert batch.status_code == 409
        assert client.get("/link/api/reports/weekly.pdf").status_code == 200
        assert client.get("/link/api/loops/fic-106/report.pdf").status_code == 200

    # Once the OP is bound in PlantCraft, the next round analyses it.
    _asset(fake, "fic-106")["signals"]["op"] = sid("FIC-101.OP")
    rt.run_round()
    loop = rt.loops.get_loop("fic-106")
    assert not loop.incomplete
    assert rt.latest.get("cpm", "loop", "fic-106") is not None


def test_an_asset_without_a_pv_is_listed_too(catalog):
    rt, fake = catalog
    del _asset(fake, "fic-106")["signals"]["pv"]
    rt.run_round()
    loop = rt.loops.get_loop("fic-106")
    assert loop.signals.pv is None and loop.asset_record.missing_roles == ["pv", "op"]
    row = next(row for row in rt.monitor.overview_rows() if row["loop_id"] == "fic-106")
    assert row["status"] == "incomplete" and row["missing_roles"] == ["pv", "op"]


def test_an_older_processcraft_is_read_by_kind_with_pv_and_op_required(tmp_path):
    runtime = make_runtime(tmp_path, make_fake(older=True))
    try:
        result = runtime.sync_loops()
        assert result["status"] == "ok" and result["added"] == 5
        loop = runtime.loops.get_loop("fic-101")
        assert loop.asset_record.roles_source == "fallback"
        assert loop.asset_record.required_roles == ["pv", "op"]
        assert loop.asset_record.type_path == ["loop"] and loop.profile_id == "flow_loop"
        assert not any(item.incomplete for item in runtime.loops.list_loops())
    finally:
        runtime.shutdown()


def test_the_starter_types_give_a_loop_its_required_roles(runtime):
    """The SDK's fake serves PlantCraft's starter types: Control loop needs PV and OP."""

    runtime.sync_loops()
    record = runtime.loops.get_loop("fic-101").asset_record
    assert record.roles_source == "asset_types" and record.required_roles == ["pv", "op"]


def test_a_derived_loop_type_counts_as_a_loop():
    assert is_loop({"type_path": ["loop", "cascade_loop"], "kind": "cascade_loop"})
    assert is_loop({"kind": "loop"})
    assert not is_loop({"kind": "cascade_loop"})  # no type path: only the loop kind itself
    assert not is_loop({"type_path": ["equipment"], "kind": "loop"})
    by_type = required_roles_by_type(RESOLVED_TYPES)
    loop = loop_from_asset(
        {
            "id": "c1",
            "type_path": ["loop", "cascade_loop"],
            "kind": "cascade_loop",
            "signals": {"pv": "a", "op": "b"},
        },
        {},
        by_type,
    )
    assert loop.asset_record.type_id == "cascade_loop" and not loop.incomplete


def test_rows_synced_before_the_catalog_keep_what_people_chose(runtime):
    old = LoopConfig(
        loop_id="fic-101",
        name="FIC-101",
        signals=LoopSignals(pv=sid("FIC-101.PV"), sp=sid("FIC-101.SP"), op=sid("FIC-101.OP")),
        profile_id="tracking",
        metadata={"criticality": "critical"},
    )
    runtime.loops.save_loop(old, origin="processcraft")
    # The stored row predates the asset record (as an upgraded database has it).
    assert runtime.loops.get_loop("fic-101").asset_record is None
    runtime.sync_loops()
    loop = runtime.loops.get_loop("fic-101")
    assert loop.profile_id == "tracking" and loop.metadata["criticality"] == "critical"
    assert sorted(loop.set_here) == ["criticality", "profile_id"]


HOSTILE_ASSETS = [
    "not an asset",
    None,
    42,
    {"name": "no id", "kind": "loop"},
    {"id": "", "kind": "loop", "signals": {"pv": "x"}},
    {"id": "x" * 500, "kind": "loop", "signals": {"pv": "x"}},
    {"id": 7, "kind": "loop", "signals": {"pv": sid("FIC-101.PV"), "op": sid("FIC-101.OP")}},
    {"id": "h-name", "name": ["list"], "kind": "loop", "signals": {"pv": sid("FIC-101.PV")}},
    {"id": "h-attr", "kind": "loop", "attributes": ["junk"], "signals": ["pv"]},
    {"id": "h-sig", "kind": "loop", "signals": {"pv": 5, "op": None, "bogus": "y"}},
    {"id": "h-path", "kind": "loop", "type_path": 12, "signals": {"pv": sid("FIC-101.PV")}},
    {"id": "h-path2", "kind": "x", "type_path": [None, 3, "loop"], "signals": {"pv": "a"}},
    {"id": "h-path3", "kind": "loop", "type_path": "loop", "signals": {"pv": sid("FIC-101.PV")}},
    {"id": "cyc-a", "name": "A", "kind": "area", "parent_id": "cyc-b"},
    {"id": "cyc-b", "name": "B", "kind": "area", "parent_id": "cyc-a"},
    {
        "id": "h-cycle",
        "name": "Cycle",
        "kind": "loop",
        "parent_id": "cyc-a",
        "signals": {"pv": sid("FIC-101.PV"), "op": sid("FIC-101.OP")},
    },
    {
        "id": "h-self",
        "kind": "loop",
        "parent_id": "h-self",
        "signals": {"pv": sid("FIC-101.PV"), "op": sid("FIC-101.OP")},
    },
    {
        "id": "h-type",
        "kind": "loop",
        "type_path": ["loop"],
        "attributes": {
            "loop_type": "steam",
            "criticality": "extreme",
            "action": {"x": 1},
            "controller": True,
            "description": 3.5,
        },
        "relations": ["junk", {"type": 1}, {"type": "controls", "to": "fic-101"}, None],
        "signals": {"pv": sid("FIC-101.PV"), "op": sid("FIC-101.OP")},
    },
    {
        "id": "h-type2",
        "kind": "loop",
        "attributes": {"loop_type": 3, "criticality": ["high"]},
        "relations": {"type": "feeds"},
        "signals": {"pv": sid("FIC-101.PV"), "op": sid("FIC-101.OP")},
    },
    {"id": "fic-101", "kind": "loop", "signals": {"pv": "dup"}},  # a repeated id
]


@pytest.mark.parametrize(
    "types",
    [
        None,
        "junk",
        {"types": "junk"},
        [None, 1, {"id": None}, {"id": "loop", "roles": "pv"}],
        [{"id": "loop", "roles": {"pv": {"required": True}, "op": "yes"}}],
        [{"id": "loop", "required_roles": ["pv", 3, {"role": "op"}]}],
    ],
)
def test_odd_asset_payloads_never_crash_a_sync_or_a_round(tmp_path, types):
    fake = make_fake(catalog=True)
    fake._route_asset_types = lambda _request: types  # what this PlantCraft answers
    fake.assets = [*fake.assets, *HOSTILE_ASSETS]
    rt = make_runtime(tmp_path, fake)
    try:
        result = rt.sync_loops()
        assert result["status"] == "ok"
        loops = {loop.loop_id: loop for loop in rt.loops.list_loops()}
        assert "7" in loops and "fic-101" in loops and "h-path3" in loops
        assert loops["fic-101"].signals.pv == sid("FIC-101.PV")  # the first record of an id wins
        assert not any(len(loop_id) > 120 for loop_id in loops)
        assert loops["h-cycle"].area == "A" and loops["h-cycle"].unit == "B"
        assert loops["h-self"].area == "No area"
        odd = loops["h-type"]
        assert odd.profile_id == "flow_loop" and odd.metadata["criticality"] == "medium"
        assert odd.asset_record.loop_type == "steam" and odd.asset_record.action is None
        assert odd.asset_record.relations == [{"type": "controls", "to": "fic-101"}]
        assert loops["h-sig"].incomplete
        assert rt.run_round()["status"] == "ok"
        rows = rt.monitor.overview_rows()
        assert {row["loop_id"] for row in rows} >= {"h-type", "h-sig", "fic-106"}
        with client_for(rt, fake) as client:
            for loop_id in ("h-type", "h-sig", "7"):
                assert client.get(f"/link/api/loops/{loop_id}").status_code == 200
    finally:
        rt.shutdown()


def test_a_processcraft_answering_junk_for_the_asset_list_syncs_nothing():
    class Junk:
        def assets(self):
            return {"not": "a list"}

    assert loops_from_processcraft(Junk()) == []


def test_asset_types_are_read_as_processcraft_serves_them():
    """Every type listed with its roles resolved (``{key, name, unit, required}``)."""

    served = make_fake(catalog=True).client("engineer").asset_types()
    assert served == RESOLVED_TYPES
    area = next(item for item in served if item["id"] == "area")
    # Children are type ids (each allowed type and its subtypes), not nested types.
    assert {"equipment", "loop", "cascade_loop"} <= set(area["children"])
    assert all(isinstance(child, str) for item in served for child in item["children"])
    by_type = required_roles_by_type(served)
    assert by_type["loop"] == {"pv", "op"}
    assert by_type["cascade_loop"] == {"pv", "op"}  # a child type: inherited roles resolved
    assert by_type["area"] == set() and by_type["pump"] == set()
    # Nested type objects are read too, without recursion.
    deep: dict = {"id": "t0", "roles": [], "children": []}
    node = deep
    for level in range(1, 3000):  # deeper than Python's recursion limit
        child = {"id": f"t{level}", "roles": [{"key": "pv", "required": True}], "children": []}
        node["children"].append(child)
        node = child
    assert required_roles_by_type([deep])["t2999"] == {"pv"}
    cycle: dict = {"id": "c", "roles": [], "children": []}
    cycle["children"].append(cycle)
    assert required_roles_by_type([cycle]) == {"c": set()}  # bounded, never hangs
