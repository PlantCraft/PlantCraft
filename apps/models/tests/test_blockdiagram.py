"""Models drawn as block diagrams: the blocks' interfaces, the diagram read from the Modelica
text and written back to it, the simulation settings, and the API around them."""

from __future__ import annotations

import pytest

from modelcraft.api.runtime import BLOCK_EXAMPLES, example_files
from modelcraft.modelica import blockdiagram
from modelcraft.modelica.edit import EditError
from modelcraft.modelica.interface import library_blocks, names
from tests.conftest import TLC, TLC_FILE, example, wait_for


@pytest.fixture(scope="module")
def blocks() -> dict:
    found = {}
    for package in BLOCK_EXAMPLES:
        files = example_files(package, "blocks")
        for spec in library_blocks(files, library=package, library_name=package):
            found[spec["block_id"]] = spec
    return found


def node(name, block, x=0, y=0, label="", **parameters):
    return {"id": name, "block": block, "parameters": parameters, "label": label, "x": x, "y": y}


def wire(source, target):
    (a, a_port), (b, b_port) = source.split("."), target.split(".")
    return {"source": a, "source_port": a_port, "target": b, "target_port": b_port}


def test_every_block_shows_its_signals_and_parameters(blocks):
    assert len(blocks) == 28
    pid = blocks["PlantCraftControl.PID"]
    assert pid["name"] == "PID" and pid["group"] == "PlantCraftControl"
    assert [p["port"] for p in pid["inputs"]] == ["sp", "pv"]
    assert [p["port"] for p in pid["outputs"]] == ["op"]
    assert all(p["type"] == "real" and p["types"] == ["real"] for p in pid["inputs"])
    parameters = {p["name"]: p for p in pid["parameters"]}
    assert parameters["k"]["default"] == 1 and parameters["k"]["schema"] == {"type": "number"}
    assert parameters["Ti"]["unit"] == "s" and parameters["Ti"]["schema"]["minimum"] == 1e-6
    assert parameters["reverse"]["schema"] == {"type": "boolean"}
    assert "pid" not in parameters  # protected parts stay inside the block
    tank = blocks["PlantCraftEquipment.Tank"]
    assert {p["port"]: p["unit"] for p in tank["outputs"]} == {"level": "m", "qOut": "m3/s"}
    table = {p["name"]: p for p in blocks["PlantCraftSources.TimeTable"]["parameters"]}
    assert table["table"]["schema"]["type"] == "array"
    assert blocks["PlantCraftSinks.Scope"]["outputs"] == []
    assert names("Step", "Step: a value that jumps") == ("Step", "A value that jumps")
    assert names("ControlValve", "Valve with a flow")[0] == "Control valve"


def test_a_diagram_is_written_as_modelica_and_read_back(blocks):
    text = blockdiagram.new_model("Loop", "A loop")
    diagram = {
        "version": 1,
        "nodes": [
            node("setpoint", "PlantCraftSources.Step", 0, 0, "Setpoint", height=2, startTime=10),
            node("controller", "PlantCraftControl.PID", 240, 0, k=1.5),
            node("process", "PlantCraftContinuous.FirstOrder", 480, 0, T=20),
            node("scope", "PlantCraftSinks.Scope", 720, 0),
        ],
        "edges": [
            wire("setpoint.y", "controller.sp"),
            wire("process.y", "controller.pv"),  # a feedback loop
            wire("controller.op", "process.u"),
            wire("process.y", "scope.u"),
        ],
    }
    text = blockdiagram.write(text, "Loop", diagram, blocks)
    assert 'PlantCraftSources.Step setpoint(height=2, startTime=10) "Setpoint"' in text
    assert "connect(process.y, controller.pv)" in text
    read = blockdiagram.read(text, "Loop", blocks)
    assert read["editable"] and not read["problems"]
    assert read["diagram"]["nodes"][1] == node("controller", "PlantCraftControl.PID", 240, 0, k=1.5)
    assert sorted(map(str, read["diagram"]["edges"])) == sorted(map(str, diagram["edges"]))
    # A change rewrites only what changed: here a parameter back to its default, a move,
    # a label, a removed block and its wires.
    changed = read["diagram"]
    changed["nodes"][1]["parameters"] = {"k": 1, "Ti": 30}
    changed["nodes"][2]["x"] = 600
    changed["nodes"][2]["label"] = "Process lag"
    changed["nodes"] = changed["nodes"][:3]
    changed["edges"] = [e for e in changed["edges"] if e["target"] != "scope"]
    again = blockdiagram.write(text, "Loop", changed, blocks)
    assert "PlantCraftControl.PID controller(Ti=30)" in again
    assert '"Process lag"' in again and "scope" not in again
    assert blockdiagram.read(again, "Loop", blocks)["diagram"]["nodes"][2]["x"] == 600


def test_the_diagram_refuses_what_the_text_cannot_hold(blocks):
    text = blockdiagram.new_model("Loop", "")
    step = node("step", "PlantCraftSources.Step")
    gain = node("gain", "PlantCraftMath.Gain", 200)
    for bad in (
        {"nodes": [node("Step", "PlantCraftSources.Step")]},  # upper-case first letter
        {"nodes": [node("time", "PlantCraftSources.Step")]},  # a Modelica word
        {"nodes": [step, {**step}]},
        {"nodes": [node("x", "Nope.Block")]},
        {"nodes": [step, gain], "edges": [wire("gain.u", "step.y")]},
        {
            "nodes": [step, gain, {**step, "id": "s2"}],
            "edges": [wire("step.y", "gain.u"), wire("s2.y", "gain.u")],
        },
    ):
        with pytest.raises(EditError):
            blockdiagram.write(text, "Loop", {"version": 1, "edges": [], **bad}, blocks)
    hand_written = "model Hand\n  Real x;\nequation\n  der(x) = -x;\nend Hand;\n"
    read = blockdiagram.read(hand_written, "Hand", blocks)
    assert not read["editable"] and len(read["problems"]) == 2
    with pytest.raises(EditError, match="edit it in the code"):
        blockdiagram.write(hand_written, "Hand", {"nodes": [], "edges": []}, blocks)


def test_simulation_settings_live_in_the_class_annotation():
    text = blockdiagram.new_model("Loop", "")
    assert blockdiagram.read(text, "Loop", {})["settings"] == blockdiagram.DEFAULT_SETTINGS
    values = {"start": 0, "stop": 600, "interval": 0.5, "tolerance": 1e-5, "solver": "rungekutta"}
    text = blockdiagram.set_settings(text, "Loop", values)
    assert "experiment(StartTime=0, StopTime=600, Interval=0.5, Tolerance=1e-05)" in text
    assert '__OpenModelica_simulationFlags(s="rungekutta")' in text
    assert text.count("experiment(") == 1
    assert blockdiagram.read(text, "Loop", {})["settings"] == {
        "start": 0.0,
        "stop": 600.0,
        "interval": 0.5,
        "tolerance": 1e-5,
        "solver": "rungekutta",
    }
    assert blockdiagram.run_options(values) == {
        "start": 0.0,
        "stop": 600.0,
        "intervals": 1200,
        "tolerance": 1e-5,
        "method": "rungekutta",
    }
    for bad in (
        {**values, "stop": 0},
        {**values, "interval": 0},
        {**values, "interval": 1e-4},  # more than 200 000 steps
        {**values, "tolerance": 1},
        {**values, "solver": "magic"},
    ):
        with pytest.raises(EditError):
            blockdiagram.check_settings(bad)


def test_the_examples_are_diagrams(blocks):
    files = example_files("PlantCraftExamples", "models")
    for path, text in files.items():
        if path.endswith(".mo") and not path.endswith("package.mo"):
            cls = "PlantCraftExamples." + path.rpartition("/")[2].removesuffix(".mo")
            read = blockdiagram.read(text, cls, blocks)
            assert read["editable"], (cls, read["problems"])
            assert read["diagram"]["nodes"] and read["diagram"]["edges"]


# The API ---------------------------------------------------------------------------------


def test_catalog_and_models(client):
    catalog = client.get("/api/catalog").json()
    assert len(catalog["blocks"]) == 28
    assert [item["name"] for item in catalog["libraries"]] == [
        "Sources",
        "Math",
        "Continuous",
        "Control",
        "Process equipment",
        "Sinks",
    ]
    assert sum(item["count"] for item in catalog["libraries"]) == 28
    pid = client.get("/api/catalog/PlantCraftControl.PID").json()
    assert pid["code"].startswith("within PlantCraftControl;") and pid["example"]
    assert pid["group"] == "Control" and pid["library_name"] == "Control"
    assert client.get("/api/catalog/Nope.Block").status_code == 404
    models = client.get("/api/models").json()
    tlc = next(m for m in models if m["model"] == TLC)
    assert tlc["example"] and tlc["diagram"] and tlc["blocks"] == 8
    assert tlc["settings"]["stop"] == 3600 and tlc["file"] == TLC_FILE
    assert models[0]["example"]
    twin = [m for m in models if m["project"] == "Analytics models"]
    assert twin and not any(m["diagram"] for m in twin)  # written as code
    # A model written as code is the one block of its diagram: its ports and parameters.
    code = client.get(f"/api/models/{twin[0]['project_id']}/{twin[0]['model']}").json()
    block = code["code_block"]
    assert block["block_id"] == f"modelica:{twin[0]['model']}" and block["name"] == code["name"]
    assert block["parameters"] or block["inputs"] or block["outputs"]
    assert client.get(f"/api/models/{tlc['project_id']}/{TLC}").json()["code_block"] is None
    # A block's Used by: the models that place it.
    used = client.get("/api/catalog/PlantCraftControl.PID/used-by").json()
    assert any(m["model"] == TLC and m["count"] >= 1 and m["example"] for m in used)
    assert client.get("/api/catalog/Nope.Block/used-by").status_code == 404


def test_create_draw_run_duplicate_and_delete_a_model(client):
    created = client.post(
        "/api/models", json={"name": "Level loop", "description": "Mine", "group": "Tests"}
    )
    assert created.status_code == 201
    model = created.json()
    assert model["model"] == "LevelLoop" and model["group"] == "Tests" and model["editable"]
    url = f"/api/models/{model['project_id']}/LevelLoop"
    diagram = {
        "version": 1,
        "nodes": [
            node("source", "PlantCraftSources.Ramp", 0, 0, height=1, duration=10),
            node("lag", "PlantCraftContinuous.FirstOrder", 240, 0, T=5),
            node("scope", "PlantCraftSinks.Scope", 480, 0),
        ],
        "edges": [wire("source.y", "lag.u"), wire("lag.y", "scope.u")],
    }
    settings = {"start": 0, "stop": 60, "interval": 0.1, "tolerance": 1e-6, "solver": "euler"}
    saved = client.put(
        url,
        json={"diagram": diagram, "settings": settings, "base_updated_at": model["updated_at"]},
    )
    assert saved.status_code == 200, saved.text
    assert (
        saved.json()["settings"]["solver"] == "euler" and len(saved.json()["diagram"]["nodes"]) == 3
    )
    stale = client.put(url, json={"diagram": diagram, "base_updated_at": model["updated_at"]})
    assert stale.status_code == 409
    bad = client.put(url, json={"diagram": {"nodes": [node("x", "Nope.Block")], "edges": []}})
    assert bad.status_code == 422
    run = client.post(f"{url}/run", json={"label": "First"})
    assert run.status_code == 201
    options = run.json()["options"]
    assert options["method"] == "euler" and options["intervals"] == 600 and options["stop"] == 60
    assert wait_for(client, run.json()["id"])["status"] == "done"
    copy = client.post(f"{url}/duplicate", json={"name": "Level loop 2"}).json()
    assert copy["model"] == "LevelLoop2" and copy["settings"]["solver"] == "euler"
    assert len(copy["diagram"]["nodes"]) == 3 and copy["group"] == "Tests"
    renamed = client.patch(url, json={"group": "Other"}).json()
    assert renamed["group"] == "Other"
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404
    assert client.get(f"/api/runs/{run.json()['id']}").status_code == 200  # the run stays


def test_examples_are_run_and_duplicated_but_never_changed(client):
    project = example(client)
    url = f"/api/models/{project['id']}/{TLC}"
    current = client.get(url).json()
    assert current["example"] and current["editable"]
    refused = client.put(
        url, json={"diagram": current["diagram"], "base_updated_at": current["updated_at"]}
    )
    assert refused.status_code == 403
    assert client.delete(url).status_code == 403
    run = client.post(f"{url}/run", json={}).json()
    assert run["options"]["intervals"] == 3600 and run["options"]["method"] == "dassl"
    copy = client.post(f"{url}/duplicate", json={"name": "My tank"})
    assert copy.status_code == 201 and not copy.json()["example"]


def test_viewers_read_models_but_do_not_change_them(runtime, fake):
    from tests.conftest import client_for

    with client_for(runtime, fake, "operator") as viewer:
        assert viewer.get("/api/models").status_code == 200
        assert viewer.post("/api/models", json={"name": "No"}).status_code == 403


def test_a_model_is_imported_from_a_modelica_file(client):
    """Round 9: New model, Import a file: the file as it is, opened on its first model."""

    text = (
        'model Heater "Room heater"\n'
        '  parameter Real k = 2 "Gain";\n'
        "  Real x(start = 0);\n"
        "equation\n"
        "  der(x) = -x + k;\n"
        "end Heater;\n"
    )
    made = client.post("/api/models/import", json={"file_name": "Heater.mo", "text": text})
    assert made.status_code == 201, made.text
    found = made.json()
    assert found["model"] == "Heater" and found["name"] == "Room heater"
    assert client.get(f"/api/models/{found['project_id']}/Heater").status_code == 200
    empty = client.post(
        "/api/models/import", json={"file_name": "Pkg.mo", "text": "package Pkg\nend Pkg;\n"}
    )
    assert empty.status_code == 422
    assert (
        client.post("/api/models/import", json={"file_name": "../x.mo", "text": text}).status_code
        == 422
    )
