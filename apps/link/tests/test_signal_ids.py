"""Signal ids are opaque, as API v1 names them: ``<source id>:<tag>`` (D2, 2026-10-20).

Loops from PlantCraft assets take the ids of the asset's role map at every sync. A loop defined
here before the rename names bare tags: it is looked up once and stored by the id PlantCraft
answers (``loops/sync.py``, ``rename_signal_ids``). A bare tag still reads until API v1 is
frozen; LinkCraft never builds an id from a tag.
"""

from __future__ import annotations

import sqlite3

from plantcraft_sdk.client import Unavailable

from linkcraft.catalog.presets import PresetStore
from linkcraft.config import LoopConfig, LoopSignals
from linkcraft.db import Database
from linkcraft.loops.store import LoopStore
from linkcraft.loops.sync import rename_signal_ids
from tests.conftest import client_for
from tests.plant import sid


def _old_loop(loop_id: str = "mine", **signals: str) -> LoopConfig:
    signals = signals or {"pv": "FIC-101.PV", "sp": "FIC-101.SP", "op": "FIC-101.OP"}
    return LoopConfig(loop_id=loop_id, name="Mine", signals=LoopSignals(**signals))


def test_loops_from_assets_take_the_ids_of_the_role_map(runtime):
    runtime.sync_loops()
    loop = runtime.loops.get_loop("fic-101")
    assert loop.signals.pv == "fake:FIC-101.PV" and loop.signals.mode == "fake:FIC-101.MODE"


def test_a_loop_defined_with_bare_tags_is_renamed_once(runtime, fake):
    runtime.loops.save_loop(_old_loop(), origin="user")
    result = runtime.sync_loops()
    assert result["signal_ids_renamed"] == 1
    loop = runtime.loops.get_loop("mine")
    assert loop.signals.model_dump() == {
        "pv": sid("FIC-101.PV"),
        "sp": sid("FIC-101.SP"),
        "op": sid("FIC-101.OP"),
        "mode": None,
        "secondary": None,
    }
    with runtime.db.connect() as connection:
        events = connection.execute(
            "SELECT event_type FROM configuration_events WHERE entity_id = 'mine'"
        ).fetchall()
    assert [row["event_type"] for row in events] == ["saved", "signal_ids_renamed"]
    before = fake.requests
    assert rename_signal_ids(runtime.loops, runtime.service_client) == {"checked": 0, "renamed": 0}
    assert fake.requests == before  # checked once: no lookups after
    assert runtime.run_round()["status"] == "ok"
    assert runtime.latest.summaries("cpm", "loop")["mine"]["summary"]["health"] is not None


def test_an_unknown_tag_is_kept_and_a_failed_lookup_is_tried_again(runtime):
    runtime.loops.save_loop(_old_loop("gone", pv="NOPE.PV"), origin="user")
    runtime.loops.save_loop(_old_loop("later"), origin="user")

    class Down:
        def signal(self, signal_id):
            raise Unavailable("PlantCraft could not be reached")

    assert rename_signal_ids(runtime.loops, Down()) == {"checked": 0, "renamed": 0}
    counts = rename_signal_ids(runtime.loops, runtime.service_client)
    assert counts == {"checked": 2, "renamed": 1}
    assert runtime.loops.get_loop("gone").signals.pv == "NOPE.PV"  # PlantCraft's 404 reason
    assert runtime.loops.get_loop("later").signals.pv == sid("FIC-101.PV")


def test_loops_from_assets_are_never_looked_up(runtime, fake):
    runtime.sync_loops()
    assert runtime.loops.unchecked_signal_loops() == []


def test_a_signal_typed_as_a_bare_tag_is_stored_by_its_id(client, runtime):
    created = client.post(
        "/link/api/loops", json={"loop_id": "U-1", "name": "Mine", "signals": {"pv": "FIC-101.PV"}}
    )
    assert created.status_code == 201, created.text
    assert runtime.loops.get_loop("U-1").signals.pv == sid("FIC-101.PV")
    patched = client.patch("/link/api/loops/U-1", json={"signals": {"pv": "LIC-102.PV"}})
    assert patched.status_code == 200, patched.text
    assert runtime.loops.get_loop("U-1").signals.pv == sid("LIC-102.PV")


def test_a_tag_two_sources_have_is_refused_with_both_ids(runtime, fake):
    fake.signals.append({**fake.signals[0], "id": "pi:FIC-101.PV", "source": "pi"})
    with client_for(runtime, fake) as client:
        answer = client.post(
            "/link/api/loops", json={"loop_id": "U-2", "name": "x", "signals": {"pv": "FIC-101.PV"}}
        )
    assert answer.status_code == 422
    assert (
        "fake:FIC-101.PV" in answer.json()["detail"] and "pi:FIC-101.PV" in answer.json()["detail"]
    )


def test_an_installation_from_before_the_rename_gains_the_column(tmp_path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as connection:  # workspace_loops as LinkCraft created it before
        connection.executescript(
            """
            CREATE TABLE workspace_loops (
                loop_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                origin TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO workspace_loops VALUES ('mine', ?, 'user', 'then', 'then')",
            (_old_loop().model_dump_json(),),
        )
    db = Database(path)
    store = LoopStore(db, PresetStore(db))
    LoopStore(db, PresetStore(db))  # a second start changes nothing
    assert [loop.loop_id for loop in store.unchecked_signal_loops()] == ["mine"]
    assert store.get_loop("mine").signals.pv == "FIC-101.PV"  # still reads until renamed


def test_signal_quality_judges_only_the_plants_live_measurements():
    # the suite's health and a CSV imported once are not live plant data: never "stale" alarms
    from linkcraft.data.samples import SignalReader

    class Client:
        def signals(self):
            return [
                {"id": "plantcraft:FIC-1.PV", "source_kind": "opcua", "app": None},
                {"id": "lab:BSW", "source_kind": "csv", "app": None},
                {"id": "system:alarmcraft.cpu_pct", "source_kind": "system", "app": None},
                {"id": "import-1:PILOT.TI", "source_kind": "import", "app": None},
                {"id": "app-linkcraft:x.quality", "source_kind": "derived", "app": "linkcraft"},
            ]

    found = [item["id"] for item in SignalReader(Client()).signals()]
    assert found == ["plantcraft:FIC-1.PV", "lab:BSW"]
