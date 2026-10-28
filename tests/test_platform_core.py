"""The PlantCraft core: assets, loops in the tree, events and references."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from processcraft.api.app import create_app
from processcraft.assets import AssetStore
from processcraft.db import Database
from processcraft.events import EventStore
from processcraft.refs import RefResolvers, find_refs, parse_ref

ROOT = Path(__file__).resolve().parents[1]


def _scenario(tmp_path: Path) -> Path:
    scenario = json.loads((ROOT / "scenarios" / "generic_demo.json").read_text())
    scenario["storage"]["sqlite_path"] = str(tmp_path / "workspace.sqlite3")
    scenario["source"]["path"] = str(ROOT / scenario["source"]["path"])
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario))
    return path


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANTCRAFT_SCENARIO", str(_scenario(tmp_path)))
    monkeypatch.setenv("PLANTCRAFT_PREWARM_HISTORY", "false")
    monkeypatch.delenv("PLANTCRAFT_BASIC_AUTH_ENABLED", raising=False)
    with TestClient(create_app()) as test_client:
        yield test_client


# Assets -----------------------------------------------------------------------


def test_asset_sync_keeps_hand_made_assets_and_moves(tmp_path):
    store = AssetStore(Database(tmp_path / "a.sqlite3"))
    store.save("plant", name="Planta", kind="site", origin="platform")
    store.sync(
        "scenario",
        [
            {"asset_id": "feed", "name": "Alimentação", "kind": "area", "parent_id": "plant"},
            {
                "asset_id": "FIC-1",
                "name": "Vazão",
                "kind": "loop",
                "parent_id": "feed",
                "signals": [{"signal_id": "FT1", "role": "pv", "name": "PV", "unit": "m3/h"}],
            },
        ],
    )
    store.save("pump", name="Bomba", kind="equipment", parent_id="plant")
    # A person puts the loop under an equipment: the next sync must not undo it.
    store.move("FIC-1", "pump")
    store.sync(
        "scenario",
        [{"asset_id": "feed", "name": "Alimentação", "kind": "area", "parent_id": "plant"}],
    )
    assert store.get("FIC-1")["parent_id"] == "pump"
    assert store.signal_roles("loop") == {"FT1": [{"asset_id": "FIC-1", "role": "pv"}]}
    assert [item["asset_id"] for item in store.path("FIC-1")] == ["plant", "pump", "FIC-1"]
    with pytest.raises(ValueError):
        store.move("plant", "FIC-1")
    # Removing an asset lifts its children to its parent.
    store.delete("pump")
    assert store.get("FIC-1")["parent_id"] == "plant"


def test_a_stale_synced_asset_goes_away(tmp_path):
    store = AssetStore(Database(tmp_path / "a.sqlite3"))
    store.sync("scenario", [{"asset_id": "tank", "name": "Tanque", "kind": "equipment"}])
    store.sync("scenario", [])
    assert store.get("tank") is None


def test_a_database_from_the_monolith_hands_its_loops_to_the_scenario(tmp_path):
    from processcraft.platform.loops import LEGACY_ORIGIN, SCENARIO_ORIGIN

    store = AssetStore(Database(tmp_path / "a.sqlite3"))
    store.save("old-area", name="Old area", kind="area", origin=LEGACY_ORIGIN)
    store.save("FIC-1", name="Flow", kind="loop", parent_id="old-area", origin=LEGACY_ORIGIN)
    store.set_signals("FIC-1", [{"signal_id": "FT1", "role": "pv"}], origin=LEGACY_ORIGIN)
    assert store.adopt(LEGACY_ORIGIN, SCENARIO_ORIGIN) == 2
    store.sync(
        SCENARIO_ORIGIN,
        [
            {"asset_id": "area", "name": "Area", "kind": "area"},
            {
                "asset_id": "FIC-1",
                "name": "Flow",
                "kind": "loop",
                "parent_id": "area",
                "signals": [{"signal_id": "FT1", "role": "pv"}],
            },
        ],
    )
    # The old area is gone, the loop moved under the scenario's area and kept one pv link.
    assert store.get("old-area") is None
    assert store.get("FIC-1")["parent_id"] == "area"
    assert store.signal_roles("loop") == {"FT1": [{"asset_id": "FIC-1", "role": "pv"}]}


# Events and references --------------------------------------------------------


def test_events_build_timelines_backlinks_and_reach_subscribers(tmp_path):
    events = EventStore(Database(tmp_path / "e.sqlite3"))
    seen = []
    events.subscribe(seen.append, prefix="action.")
    events.publish(
        "action.created",
        "action:1",
        source="work",
        summary="Ação criada",
        refs=["asset:FIC-1", "bad ref"],
    )
    events.publish("message.posted", "conversation:7", source="collab", refs=["asset:FIC-1"])
    timeline = events.timeline("asset:FIC-1")
    assert [item["kind"] for item in timeline] == ["message.posted", "action.created"]
    assert timeline[1]["refs"] == ["action:1", "asset:FIC-1"]
    assert events.backlinks("asset:FIC-1") == ["conversation:7", "action:1"]
    assert [item["kind"] for item in seen] == ["action.created"]


def test_events_older_than_the_retention_are_dropped_with_their_refs(tmp_path, monkeypatch):
    from datetime import datetime, timedelta

    from processcraft.db import recorded_at

    events = EventStore(Database(tmp_path / "e.sqlite3"))
    with recorded_at(datetime.now().astimezone() - timedelta(days=800)):
        events.publish("action.created", "action:old", source="work", refs=["asset:FIC-1"])
    events.publish("action.created", "action:new", source="work", refs=["asset:FIC-1"])
    assert events.backlinks("asset:FIC-1") == ["action:new"]  # pruned on publish (730 days)
    monkeypatch.setenv("PLANTCRAFT_EVENT_RETENTION_DAYS", "0")
    with recorded_at(datetime.now().astimezone() - timedelta(days=900)):
        events.publish("action.created", "action:kept", source="work")
    assert events.prune() == 0  # 0 keeps every event
    assert events.prune(1) == 1


def test_refs_take_every_id_the_suite_writes():
    """One rule with plantcraft_sdk.refs: PI tags keep spaces and backslashes, no encoding."""

    tag = "signal:pi:Unit 2\\FIC 101.PV"
    assert str(parse_ref(tag)) == tag and parse_ref(tag).id == "pi:Unit 2\\FIC 101.PV"
    assert parse_ref("run:cpmcraft/2026-10-19-0600").id == "cpmcraft/2026-10-19-0600"
    for bad in ("asset:", "asset: padded", "asset:a\nb", "asset:" + "x" * 301, "Asset:x"):
        with pytest.raises(ValueError):
            parse_ref(bad)
    events = EventStore(Database(Path(tempfile.mkdtemp()) / "e.sqlite3"))
    events.publish("cpmcraft.x.done", tag, source="cpmcraft", refs=["signal:pi:a/b c"])
    assert [item["refs"] for item in events.timeline("signal:pi:a/b c")] == [
        [tag, "signal:pi:a/b c"]
    ]


def test_a_bare_tag_two_sources_have_names_no_signal():
    from processcraft.platform.signals import AmbiguousSignal, SignalCatalog

    catalog = SignalCatalog()
    for source in ("pi", "opc"):
        catalog.add({"id": f"{source}:FIC-1.PV", "source": source}, "FIC-1.PV")
    catalog.add({"id": "pi:LIC-2.PV", "source": "pi"}, "LIC-2.PV")
    assert catalog.find("pi:FIC-1.PV") == "pi:FIC-1.PV"
    assert catalog.find("LIC-2.PV") == "pi:LIC-2.PV"
    assert catalog.find("nope") is None
    with pytest.raises(AmbiguousSignal) as caught:
        catalog.find("FIC-1.PV")
    assert caught.value.ids == ["opc:FIC-1.PV", "pi:FIC-1.PV"]
    found, reason = catalog.lookup("FIC-1.PV")
    assert found is None and "opc:FIC-1.PV" in reason and "pi:FIC-1.PV" in reason


def test_mentions_and_resolvers():
    text = "Veja #[FIC-1](loop:FIC-1) e #asset:feed, e de novo #loop:FIC-1."
    assert find_refs(text) == ["loop:FIC-1", "asset:feed"]
    with pytest.raises(ValueError):
        parse_ref("sem-tipo")
    refs = RefResolvers()
    refs.register(
        "asset",
        lambda item: {"title": item.upper(), "href": f"/assets/{item}"} if item == "feed" else None,
    )
    assert refs.resolve("asset:feed")["title"] == "FEED"
    assert refs.resolve("asset:none") | {"exists": False} == refs.resolve("asset:none")
    gone = refs.resolve("twin:feed")
    assert gone["available"] is False and "is not active in this installation" in gone["reason"]
    # An app's declared kind, written as the assistant writes any app's object.
    refs.declared = lambda kind: (
        {"app": "dashcraft", "title": "Dashboard", "url": "/dash/dashboards/{id}"}
        if kind == "dashboard"
        else None
    )
    board = refs.resolve("dashboard:dashcraft/d-1")
    assert board["ref"] == "dashboard:d-1" and board["href"] == "/dash/dashboards/d-1"
    assert refs.resolve("dashboard:d-1")["href"] == "/dash/dashboards/d-1"


# The platform API ---------------------------------------------------------------


def test_assets_api_links_loops_and_signals(client):
    tree = client.get("/api/assets").json()
    by_id = {item["asset_id"]: item for item in tree["items"]}
    root = tree["root_id"]
    assert by_id[root]["kind"] == "site"
    loop = by_id["FIC-101"]
    assert loop["kind"] == "loop" and by_id[loop["parent_id"]]["kind"] == "area"
    detail = client.get("/api/assets/FIC-101").json()
    assert [item["asset_id"] for item in detail["path"]][0] == root
    assert {item["role"] for item in detail["signals"]} >= {"pv", "sp", "op"}
    assert set(detail) == {
        "asset",
        "type",
        "type_path",
        "attributes",
        "missing",
        "relations",
        "path",
        "children",
        "signals",
        "timeline",
    }
    assert detail["type"]["name"] == "Control loop" and detail["type_path"] == ["loop"]
    area = loop["parent_id"]
    assert {
        item["signal_id"]
        for item in client.get(f"/api/assets/{area}/signals", params={"deep": True}).json()
    } >= {"pv"}
    value = client.get("/api/signals/pv/value", params={"agg": "mean", "window": "24h"}).json()
    assert value["value"] is not None and value["samples"] > 0 and value["assets"] == ["FIC-101"]
    series = client.get("/api/signals/pv/series", params={"window": "1h", "points": 50}).json()
    assert 0 < len(series["series"]) <= 51
    assert client.get("/api/signals/pv/value", params={"window": "90d"}).status_code == 422


def test_hand_made_assets_and_references(client):
    created = client.post("/api/assets", json={"name": "Bomba P-101", "kind": "equipment"})
    assert created.status_code == 201
    pump = created.json()["asset_id"]
    area = client.get("/api/assets/FIC-101").json()["asset"]["parent_id"]
    assert client.delete(f"/api/assets/{area}").status_code == 422  # the scenario file's
    assert (
        client.patch("/api/assets/FIC-101", json={"move": True, "parent_id": pump}).json()[
            "parent_id"
        ]
        == pump
    )
    refs = client.get(
        "/api/refs", params={"ref": ["asset:FIC-101", "user:ana.lima", f"asset:{pump}", "twin:x"]}
    ).json()
    assert refs["asset:FIC-101"]["href"] == "/assets/FIC-101"
    assert refs["user:ana.lima"]["title"] == "Ana Lima"
    assert refs[f"asset:{pump}"]["title"] == "Bomba P-101"
    assert refs["twin:x"]["available"] is False


def test_asset_kinds_can_be_added_and_contents_roll_up(client):
    kinds = {item["kind"]: item for item in client.get("/api/assets").json()["kinds"]}
    assert kinds["loop"]["builtin"] is True and kinds["loop"]["count"] >= 1
    added = client.post("/api/asset-kinds", json={"label": "Controlador"})
    assert added.status_code == 201
    kind = added.json()["kind"]
    assert client.post("/api/asset-kinds", json={"label": "controlador"}).status_code == 409
    created = client.post("/api/assets", json={"name": "DCS-01", "kind": kind}).json()
    assert created["kind_label"] == "Controlador"
    assert client.post("/api/assets", json={"name": "X", "kind": "nope"}).status_code == 422
    assert client.delete(f"/api/asset-kinds/{kind}").status_code == 422  # still in use
    root = client.get("/api/assets").json()["root_id"]
    contents = client.get(f"/api/assets/{root}/contents").json()
    assert contents["kinds"]["loop"] >= 1 and contents["kinds"][kind] == 1
    loops = client.get(f"/api/assets/{root}/contents", params={"kind": "loop"}).json()["items"]
    fic = next(item for item in loops if item["asset_id"] == "FIC-101")
    assert fic["signals"] >= 3 and fic["where"]
    assert (
        client.patch(f"/api/assets/{created['asset_id']}", json={"kind": "equipment"}).json()[
            "kind"
        ]
        == "equipment"
    )
    assert client.delete(f"/api/asset-kinds/{kind}").status_code == 204
