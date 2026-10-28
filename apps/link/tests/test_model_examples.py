"""The Simulator demo plant's model algorithms (``assets.examples``): PlantCraft Twin's example
twins as algorithms on assets, created with one button and calibrated on the last hours."""

from __future__ import annotations

from linkcraft.assets import examples
from tests.conftest import client_for
from tests.plant import sid
from tests.test_asset_algorithms import unit_fake, unit_runtime


def _source(loop: str, role: str) -> dict[str, str]:
    return {"asset_id": loop.lower(), "role": role}


def test_examples_follow_what_the_plant_has():
    everything = examples.twins(_source, area="u-100-furnaces", loop_asset=str.lower)
    assert [twin["name"] for twin in everything] == [
        "Furnaces",
        "FIC-1001 process",
        "LIC-1010 process",
    ]
    furnaces = everything[0]
    assert furnaces["asset_id"] == "u-100-furnaces"
    assert [item["variable"] for item in furnaces["outputs"]] == [
        "TIC1104_PV",
        "TIC1209_PV",
        "FIC1210_PV",
    ]
    assert [item["variable"] for item in everything[2]["inputs"]] == ["u", "d"]
    # No shared area for the furnace loops, and FIC-1001 missing its OP: only LIC-1010 is left.
    some = examples.twins(
        lambda loop, role: None if (loop, role) == ("FIC-1001", "op") else _source(loop, role),
        area=None,
        loop_asset=str.lower,
    )
    assert [twin["name"] for twin in some] == ["LIC-1010 process"]
    assert examples.algorithm_id("FIC-1001 process") == "example_fic_1001_process"


def _plant_fake():
    fake = unit_fake()
    for signal in fake.signals:  # PlantCraft lists every signal with its description
        signal.setdefault("description", "")
    # The demo plant's FIC-1001 loop, on the fake's valve and measured value.
    fake.assets.append(
        {
            "id": "fic-1001",
            "name": "FIC-1001",
            "kind": "loop",
            "parent_id": "furnace",
            "attributes": {},
            "signals": {"op": sid("TIC-1.OP"), "pv": sid("TIC-1.PV")},
        }
    )
    return fake


def test_the_examples_are_created_once_on_their_assets(tmp_path):
    fake = _plant_fake()
    runtime = unit_runtime(tmp_path, fake)
    try:
        with client_for(runtime, fake, "engineer") as client:
            listed = client.get("/link/api/models/examples").json()
            assert listed == [
                {
                    "algorithm_id": "example_fic_1001_process",
                    "name": "FIC-1001 process",
                    "description": listed[0]["description"],
                    "exists": False,
                }
            ]
            created = client.post("/link/api/models/examples")
            assert created.status_code == 201
            (row,) = created.json()
            assert row["algorithm_id"] == "example_fic_1001_process" and row["schedule_id"]
            assert row["assets"] == ["fic-1001"]
            # Calibrated on the hours up to the plant's newest data (two hours in this fake).
            assert row["calibrated"] and not row["problem"]
            algorithm = client.get("/link/api/algorithms/example_fic_1001_process").json()
            assert algorithm["subject_kind"] == "asset" and algorithm["check"]["valid"]
            assert algorithm["assets"] == ["fic-1001"]
            blocks = {node["block"] for node in algorithm["diagram"]["nodes"]}
            assert "model.fmu_plantcrafttwin_loopprocess" in blocks
            assert client.get("/link/api/models/examples").json()[0]["exists"] is True
            assert client.post("/link/api/models/examples").json() == []
        with client_for(runtime, fake, "viewer") as client:
            assert client.get("/link/api/models/examples").status_code == 403
    finally:
        runtime.shutdown()


def test_the_demo_plant_gets_its_twins_calibrated_and_scheduled_once(tmp_path, monkeypatch):
    fake = _plant_fake()
    runtime = unit_runtime(tmp_path, fake)
    # The demo plant's own example is Furnaces; this fake plant has only FIC-1001's twin.
    monkeypatch.setattr(examples, "DEMO_EXAMPLES", ("FIC-1001 process",))
    try:
        runtime.add_model_examples()
        profile = runtime.presets.get_profile("example_fic_1001_process")
        assert profile is not None and profile["author"] == "PlantCraft"
        assert profile["owner_name"] == "PlantCraft" and profile["tags"] == ["digital twin"]
        assert runtime.presets.marked("model-examples") == "example_fic_1001_process"
        # Its own schedule, an ordinary one: every hour on the asset it was made for.
        (schedule,) = [
            item
            for item in runtime.jobs.list_schedules()
            if item["profile_id"] == "example_fic_1001_process"
        ]
        assert (
            schedule["name"] == "FIC-1001 process: model beside the plant"
            and schedule["kind"] == "protocol"
        )
        assert schedule["subject_kind"] == "asset" and schedule["interval_minutes"] == 60
        assert runtime.schedule_subjects(schedule) == ["fic-1001"]
        # Deleted by a person, it stays deleted.
        runtime.presets.delete_profile("example_fic_1001_process")
        runtime._examples_tried = -1e9
        runtime.add_model_examples()
        assert runtime.presets.get_profile("example_fic_1001_process") is None
    finally:
        runtime.shutdown()


def test_another_plant_is_looked_at_again_later(tmp_path):
    fake = unit_fake()
    for signal in fake.signals:
        signal.setdefault("description", "")
    runtime = unit_runtime(tmp_path, fake)
    try:
        runtime.add_model_examples()
        assert runtime.presets.marked("model-examples") is None
    finally:
        runtime.shutdown()


def test_without_the_plant_there_is_nothing_to_create(tmp_path):
    fake = unit_fake()
    for signal in fake.signals:
        signal.setdefault("description", "")
    runtime = unit_runtime(tmp_path, fake)
    try:
        with client_for(runtime, fake, "engineer") as client:
            assert client.get("/link/api/models/examples").json() == []
            assert client.post("/link/api/models/examples").status_code == 404
    finally:
        runtime.shutdown()
