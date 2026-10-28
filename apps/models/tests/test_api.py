"""The API end to end against the fake PlantCraft and the fake runner: projects and files,
check, diagram and its edits, simulations, plots, FMUs, plant inputs, roles and the policy."""

from __future__ import annotations

import zipfile
from io import BytesIO

from modelcraft.api.runtime import example_files
from modelcraft.projects.models import SYSTEM
from tests.conftest import (
    TLC,
    TLC_FILE,
    client_for,
    editable_example,
    example,
    make_runtime,
    wait_for,
)
from tests.plant import NOW, START


def test_examples_are_seeded_once_with_their_classes(client, runtime):
    projects = client.get("/api/projects").json()
    names = [p["name"] for p in projects]
    assert "Examples" in names and "Analytics models" in names
    runtime.seed_examples()
    assert len(client.get("/api/projects").json()) == len(projects)
    project = client.get(f"/api/projects/{example(client)['id']}").json()
    classes = {c["name"]: c for c in project["classes"]}
    assert classes[TLC]["simulable"] and classes[TLC]["experiment"]["StopTime"] == 3600
    assert classes["PlantCraftExamples"]["restriction"] == "package"
    assert not classes["PlantCraftExamples"]["simulable"]
    assert any(f["path"] == TLC_FILE for f in project["files"])


def test_examples_are_read_only_and_follow_the_version_installed(client, runtime):
    project = example(client)
    path = f"/api/projects/{project['id']}/files/{TLC_FILE}"
    current = client.get(path).json()
    refused = client.put(
        path, json={"content": current["content"] + "\n", "base_updated_at": current["updated_at"]}
    )
    assert refused.status_code == 403 and "duplicate" in refused.json()["detail"]
    assert client.delete(f"/api/projects/{project['id']}").status_code == 403
    libraries = client.get("/api/blocks").json()
    assert (
        client.patch(f"/api/blocks/{libraries[0]['id']}", json={"name": "Mine"}).status_code == 422
    )
    # An install of an earlier version: a changed example and a retired one.
    runtime.projects.replace_files(project["id"], {TLC_FILE: "model Old end Old;"})
    old = runtime.projects.create(
        "Process examples",
        by=SYSTEM,
        files={"ProcessExamples/package.mo": "package ProcessExamples end ProcessExamples;"},
        example=True,
    )
    runtime.seed_examples()
    assert runtime.projects.get(old["id"]) is None
    assert runtime.projects.files(project["id"]) == example_files("PlantCraftExamples", "models")
    copy = editable_example(client)
    assert not copy["example"] and len(copy["files"]) == project["files"]


def test_an_upgraded_install_keeps_its_renamed_examples_project_and_its_runs(client, runtime):
    # 0.3 shipped the examples as ProcessExamples; the project (and what ran in it) stays.
    project = example(client)
    runtime.projects.delete(project["id"], by=SYSTEM)
    old = runtime.projects.create(
        "Process examples",
        by=SYSTEM,
        files={"ProcessExamples/package.mo": "package ProcessExamples end ProcessExamples;"},
        example=True,
    )
    runtime.seed_examples()
    kept = runtime.projects.get(old["id"])
    assert kept is not None and kept["name"] == "Examples"
    assert runtime.projects.files(old["id"]) == example_files("PlantCraftExamples", "models")
    assert [p["id"] for p in client.get("/api/projects").json() if p["name"] == "Examples"] == [
        old["id"]
    ]


def test_create_edit_and_version_a_file(client):
    project = client.post("/api/projects", json={"name": "Reactor study"}).json()
    assert [f["path"] for f in project["files"]] == ["ReactorStudy.mo"]
    path = f"/api/projects/{project['id']}/files/ReactorStudy.mo"
    current = client.get(path).json()
    saved = client.put(
        path, json={"content": current["content"] + "\n", "base_updated_at": current["updated_at"]}
    )
    assert saved.status_code == 200
    stale = client.put(
        path, json={"content": "model X end X;", "base_updated_at": current["updated_at"]}
    )
    assert stale.status_code == 409 and "changed" in stale.json()["detail"]
    revisions = client.get(f"{path}/revisions").json()
    assert len(revisions) == 1
    old = client.get(f"/api/projects/{project['id']}/revisions/{revisions[0]['id']}").json()
    assert old["content"] == current["content"]
    renamed = client.post(f"{path}/rename", json={"path": "Reactor/Study.mo"})
    assert renamed.status_code == 200 and renamed.json()["path"] == "Reactor/Study.mo"
    assert (
        client.post(f"/api/projects/{project['id']}/files", json={"path": "../x.mo"}).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/projects/{project['id']}/files",
            json={"path": "Extra.mo", "content": "model Extra end Extra;"},
        ).status_code
        == 201
    )
    assert client.delete(f"/api/projects/{project['id']}/files/Extra.mo").status_code == 204


def test_import_and_export_keep_the_library_layout(client):
    project = client.post("/api/projects", json={"name": "Imported", "template": "blank"}).json()
    files = {"Lib/package.mo": "package Lib end Lib;", "Lib/A.mo": "within Lib; model A end A;"}
    assert client.post(f"/api/projects/{project['id']}/import", json={"files": files}).json()[
        "saved"
    ]
    assert (
        client.post(f"/api/projects/{project['id']}/import", json={"files": files}).status_code
        == 409
    )
    exported = client.get(f"/api/projects/{project['id']}/export")
    with zipfile.ZipFile(BytesIO(exported.content)) as archive:
        assert sorted(archive.namelist()) == ["Lib/A.mo", "Lib/package.mo"]


def test_check_reports_success_and_errors_on_the_project_file(client):
    project = editable_example(client)
    ok = client.post(f"/api/projects/{project['id']}/check", json={"model": TLC}).json()
    assert ok["ok"] and "12 equation" in ok["summary"]
    path = f"/api/projects/{project['id']}/files/{TLC_FILE}"
    current = client.get(path).json()
    client.put(
        path,
        json={
            "content": current["content"].replace("equation\n", "equation\n  BROKEN;\n"),
            "base_updated_at": current["updated_at"],
        },
    )
    failed = client.post(f"/api/projects/{project['id']}/check", json={"model": TLC}).json()
    assert not failed["ok"]
    error = failed["messages"][0]
    assert error["level"] == "error" and error["file"] == TLC_FILE and error["line"] > 1
    assert "/jobs" not in str(failed)
    unknown = client.post(f"/api/projects/{project['id']}/check", json={"model": "Nope.Model"})
    assert unknown.status_code == 422


def test_the_policy_refuses_system_commands_before_anything_runs(client, runtime):
    project = client.post("/api/projects", json={"name": "Sneaky", "template": "blank"}).json()
    text = 'model Sneaky\nalgorithm\n  Modelica.Utilities.System.command("curl x");\nend Sneaky;\n'
    client.post(f"/api/projects/{project['id']}/files", json={"path": "Sneaky.mo", "content": text})
    jobs = len(runtime.executor.jobs)
    check = client.post(f"/api/projects/{project['id']}/check", json={"model": "Sneaky"}).json()
    assert not check["ok"] and check["messages"][0]["line"] == 3
    simulate = client.post(
        f"/api/projects/{project['id']}/simulate", json={"model": "Sneaky", "stop": 1}
    )
    assert simulate.status_code == 422
    assert len(runtime.executor.jobs) == jobs


def test_diagram_and_its_edits_change_the_text(client):
    project = editable_example(client)
    diagram = client.get(f"/api/projects/{project['id']}/diagram", params={"model": TLC}).json()
    names = {c["name"]: c for c in diagram["components"]}
    assert {"tank", "setpoint", "controller", "pump", "outlet"} <= set(names)
    assert {c["name"] for c in names["controller"]["connectors"]} >= {"u_s", "u_m", "y"}
    assert any(p["name"] == "k" for p in names["controller"]["parameters"])
    assert {(c["from"], c["to"]) for c in diagram["connections"]} >= {
        ("setpoint.y", "controller.u_s")
    }
    file = TLC_FILE
    base = client.get(f"/api/projects/{project['id']}/files/{file}").json()
    edit = {"model": TLC, "file": file, "base_updated_at": base["updated_at"]}
    added = client.post(
        f"/api/projects/{project['id']}/edit",
        json={
            **edit,
            "op": "add",
            "type": "Modelica.Blocks.Math.Gain",
            "extent": [[-10, 40], [10, 60]],
        },
    )
    assert (
        added.status_code == 200
        and "Modelica.Blocks.Math.Gain gain annotation" in added.json()["content"]
    )
    stale = client.post(
        f"/api/projects/{project['id']}/edit", json={**edit, "op": "delete", "name": "gain"}
    )
    assert stale.status_code == 409
    edit["base_updated_at"] = added.json()["updated_at"]
    moved = client.post(
        f"/api/projects/{project['id']}/edit",
        json={**edit, "op": "modifiers", "name": "controller", "values": {"k": "8", "Ti": None}},
    )
    text = moved.json()["content"]
    assert "k=8" in text and "Ti =" not in text and "Ti=" not in text
    edit["base_updated_at"] = moved.json()["updated_at"]
    wired = client.post(
        f"/api/projects/{project['id']}/edit",
        json={
            **edit,
            "op": "connect",
            "left": "gain.y",
            "right": "pump.u",
            "points": [[10, 50], [20, 50]],
        },
    )
    assert "connect(gain.y, pump.u)" in wired.json()["content"]
    edit["base_updated_at"] = wired.json()["updated_at"]
    removed = client.post(
        f"/api/projects/{project['id']}/edit", json={**edit, "op": "delete", "name": "gain"}
    )
    assert (
        "Gain gain" not in removed.json()["content"] and "gain.y" not in removed.json()["content"]
    )
    bad = client.post(
        f"/api/projects/{project['id']}/edit",
        json={**edit, "base_updated_at": None, "op": "delete", "name": "nothing"},
    )
    assert bad.status_code == 422


def test_simulate_plot_and_download(client):
    project = example(client)
    run = client.post(
        f"/api/projects/{project['id']}/simulate",
        json={
            "model": TLC,
            "stop": 900,
            "intervals": 900,
            "overrides": {"controller.k": 3},
            "label": "k = 3",
        },
    )
    assert run.status_code == 201
    done = wait_for(client, run.json()["id"])
    assert done["status"] == "done", done
    assert done["result"]["rows"] > 10 and done["label"] == "k = 3"
    variables = {v["name"]: v for v in client.get(f"/api/runs/{done['id']}/variables").json()}
    assert variables["tank.level"]["unit"] == "m" and variables["tank.level"]["kind"] == "state"
    assert variables["tank.A"]["kind"] == "parameter"
    series = client.post(
        f"/api/runs/{done['id']}/series", json={"names": ["tank.level", "nope"], "max_points": 50}
    ).json()
    assert series["missing"] == ["nope"] and len(series["series"][0]["time"]) <= 60
    assert 1.4 < series["series"][0]["values"][-1] < 1.6
    csv_text = client.get(f"/api/runs/{done['id']}/results.csv").text
    assert csv_text.startswith('"time"')
    assert client.get(f"/api/runs/{done['id']}/fmu").status_code == 404
    listed = client.get("/api/runs", params={"project": project["id"]}).json()
    assert listed[0]["id"] == done["id"]
    assert client.get(f"/api/runs/{done['id']}/files").json()[TLC_FILE]


def test_a_failed_simulation_says_why(client):
    project = client.post("/api/projects", json={"name": "Broken"}).json()
    path = f"/api/projects/{project['id']}/files/Broken.mo"
    current = client.get(path).json()
    client.put(
        path,
        json={
            "content": current["content"].replace("1 - x", "BROKEN - x"),
            "base_updated_at": current["updated_at"],
        },
    )
    run = client.post(
        f"/api/projects/{project['id']}/simulate", json={"model": "Broken", "stop": 10}
    ).json()
    done = wait_for(client, run["id"])
    assert done["status"] == "failed" and "BROKEN" in done["summary"]
    assert client.post(f"/api/runs/{done['id']}/series", json={"names": ["x"]}).status_code == 409


def test_fmu_export_is_described_and_downloadable(client):
    project = example(client)
    run = client.post(
        f"/api/projects/{project['id']}/fmu", json={"model": TLC, "version": "2.0", "type": "cs"}
    ).json()
    done = wait_for(client, run["id"])
    assert done["status"] == "done"
    result = done["result"]
    assert (
        result["fmi_version"] == "2.0"
        and result["inputs"] == ["u"]
        and result["platforms"] == ["linux64"]
    )
    assert len(result["sha256"]) == 64
    download = client.get(f"/api/runs/{done['id']}/fmu")
    assert download.status_code == 200 and download.content[:2] == b"PK"


def test_plant_signals_feed_the_inputs_and_the_comparison(client, runtime, fake):
    project = example(client)
    signal = next(s["id"] for s in client.get("/api/signals", params={"q": "FIC"}).json())
    body = {
        "model": TLC,
        "plant": {
            "start": (NOW.replace(hour=6)).isoformat(),
            "end": (NOW.replace(hour=7)).isoformat(),
            "step": 60,
            "inputs": {"qin": signal},
            "compare": {"tank.level": signal},
        },
    }
    run = client.post(f"/api/projects/{project['id']}/simulate", json=body)
    assert run.status_code == 201, run.text
    done = wait_for(client, run.json()["id"])
    assert done["options"]["stop"] == 3600 and done["options"]["plant"]["inputs"] == {"qin": signal}
    inputs = runtime.executor.extras[-1]["inputs.csv"].decode().splitlines()
    assert inputs[0] == "time,qin" and len(inputs) > 50 and inputs[-1].startswith("3600.0,")
    assert runtime.executor.jobs[-1]["options"]["inputs_file"] == "inputs.csv"
    series = client.post(f"/api/runs/{done['id']}/series", json={"names": ["tank.level"]}).json()
    assert series["compare"][0]["signal"] == signal and len(series["compare"][0]["values"]) > 50
    page = client.get("/api/asset-runs", params={"asset": signal.split(".")[2]}).json()
    assert [r["id"] for r in page["runs"]] == [done["id"]]
    assert START < NOW


def test_viewers_read_but_never_run_or_change(runtime, fake):
    with client_for(runtime, fake, "operator") as viewer:
        project = example(viewer)
        assert viewer.get(f"/api/projects/{project['id']}").status_code == 200
        assert (
            viewer.post(f"/api/projects/{project['id']}/check", json={"model": TLC}).status_code
            == 403
        )
        assert (
            viewer.post(f"/api/projects/{project['id']}/simulate", json={"model": TLC}).status_code
            == 403
        )
        assert (
            viewer.get(f"/api/projects/{project['id']}/diagram", params={"model": TLC}).status_code
            == 403
        )
        assert viewer.post("/api/projects", json={"name": "x"}).status_code == 403
        assert viewer.delete(f"/api/projects/{project['id']}").status_code == 403
    with client_for(runtime, fake, "outsider") as outsider:
        assert outsider.get("/api/projects").status_code == 403
    with client_for(runtime, fake, None) as anonymous:
        assert anonymous.get("/api/projects").status_code == 401


def test_without_a_runner_every_job_says_so(tmp_path, fake):
    runtime = make_runtime(tmp_path, fake)
    runtime.executor.available = False
    try:
        with client_for(runtime, fake) as client:
            project = example(client)
            state = client.get("/api/runner").json()
            assert state["available"] is False and state["reason"]
            check = client.post(f"/api/projects/{project['id']}/check", json={"model": TLC})
            assert check.status_code == 503 and "runner" in check.json()["detail"]
            assert (
                client.post(
                    f"/api/projects/{project['id']}/simulate", json={"model": TLC, "stop": 1}
                ).status_code
                == 503
            )
            assert client.get("/api/projects").status_code == 200
    finally:
        runtime.shutdown()


def test_library_browser_search_and_class_page(client):
    root = client.get("/api/library").json()["classes"]
    assert [c["name"] for c in root] == ["Modelica"]
    blocks = client.get("/api/library", params={"parent": "Modelica.Blocks"}).json()["classes"]
    assert {"Modelica.Blocks.Continuous", "Modelica.Blocks.Sources"} <= {c["name"] for c in blocks}
    found = client.get("/api/library", params={"q": "limpid"}).json()["classes"]
    assert found[0]["name"] == "Modelica.Blocks.Continuous.LimPID"
    page = client.get(
        "/api/library/class", params={"name": "Modelica.Blocks.Continuous.LimPID"}
    ).json()
    assert page["restriction"] == "block" and page["source"].startswith("block LimPID")
    assert client.get("/api/library/class", params={"name": "Modelica.Nope"}).status_code == 404
    assert (
        "Modelica.Blocks.Continuous.LimPID"
        in client.get("/api/library/names", params={"prefix": "Modelica.Blocks.C"}).json()
    )


def test_runs_are_reported_on_processcraft_executions(client, fake):
    project = example(client)
    run = client.post(
        f"/api/projects/{project['id']}/simulate", json={"model": TLC, "stop": 900}
    ).json()
    wait_for(client, run["id"])
    reported = fake.client(fake.token("admin")).runs(app="modelcraft")
    assert any(
        item["id"] == run["id"]
        and item["status"] == "done"
        and item["url"] == f"/model/runs/{run['id']}"
        for item in reported
    )


def test_a_run_tells_the_suite_queue_who_started_it_and_how_to_cancel_it():
    """docs/quick-access.md (PlantCraft): queued and running runs offer Cancel; every run says
    who started it, so PlantCraft tells them when it ends."""

    from modelcraft.suite import executions

    sent: list[dict] = []

    class Client:
        def put_runs(self, runs):
            sent.extend(runs)

    run = {"id": "r1", "kind": "simulate", "model": "Lib.Tank", "status": "queued"}
    run |= {"created_at": "2026-10-26T12:00:00Z", "created_by": "ana"}
    executions.put_run(Client(), run, "/model")
    executions.put_run(Client(), {**run, "status": "done"}, "/model")
    assert sent[0]["status"] == "queued" and sent[0]["by"] == "ana"
    assert sent[0]["cancel"] == "/model/api/runs/r1/cancel"
    assert sent[1]["status"] == "done" and "cancel" not in sent[1]


def test_where_a_run_goes_is_checked(client):
    project = example(client)
    bad = client.post(
        f"/api/projects/{project['id']}/simulate",
        json={"model": TLC, "compute": {"environment": "standard", "size": "huge"}},
    )
    assert bad.status_code == 422
    odd = client.post(
        f"/api/projects/{project['id']}/simulate",
        json={"model": TLC, "compute": {"environment": "ML Stack!", "size": "small"}},
    )
    assert odd.status_code == 422
    offer = client.get("/api/compute/offer").json()
    assert offer["suite"] is False and offer["environments"] == []
