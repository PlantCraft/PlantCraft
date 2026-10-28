"""Studies, the queue and the shared blocks, end to end against the fake PlantCraft and the
fake runner: a sweep made of one simulation per combination, built once, its indicators,
comparison, statistics and export; quick simulations; cancelling; a restart; block libraries."""

from __future__ import annotations

import csv
import io
import json
import threading
import time
import zipfile

from modelcraft.runs.studies import combinations, parameter_values
from tests.conftest import TLC, TLC_FILE, client_for, example, make_runtime, wait_for

SWEEP = {
    "model": TLC,
    "name": "Controller gain",
    "start": 0,
    "stop": 900,
    "intervals": 450,
    "sweep": [
        {"name": "controller.k", "mode": "range", "start": 2, "stop": 8, "count": 4},
        {"name": "controller.Ti", "mode": "list", "values": [30, 60]},
    ],
    "indicators": ["tank.level"],
}


def wait_study(client, study_id: str, seconds: float = 10) -> dict:
    deadline = time.monotonic() + seconds
    while True:
        study = client.get(f"/api/studies/{study_id}").json()
        if (study["queued"] == 0 and study["running"] == 0) or time.monotonic() > deadline:
            return study
        time.sleep(0.02)


def test_combinations_cover_every_value():
    assert parameter_values({"name": "k", "mode": "range", "start": 0, "stop": 1, "count": 3}) == [
        0.0,
        0.5,
        1.0,
    ]
    found = combinations(
        [
            {"name": "a", "mode": "list", "values": [1, 2]},
            {"name": "b", "mode": "range", "start": 10, "stop": 20, "count": 2},
        ]
    )
    assert found == [
        {"a": 1, "b": 10.0},
        {"a": 1, "b": 20.0},
        {"a": 2, "b": 10.0},
        {"a": 2, "b": 20.0},
    ]
    assert combinations([]) == [{}]


def test_a_sweep_simulates_every_combination_built_in_batches(client, runtime):
    project = example(client)
    preview = client.post(
        f"/api/projects/{project['id']}/studies/preview",
        json={"model": TLC, "sweep": SWEEP["sweep"]},
    ).json()
    assert preview["count"] == 8 and preview["limit"] == 500
    created = client.post(f"/api/projects/{project['id']}/studies", json=SWEEP)
    assert created.status_code == 201, created.text
    study = wait_study(client, created.json()["id"])
    assert study["kind"] == "sweep" and study["total"] == 8 and study["done"] == 8
    runs = study["runs"]
    assert {(r["variant"]["controller.k"], r["variant"]["controller.Ti"]) for r in runs} == {
        (k, ti) for k in (2.0, 4.0, 6.0, 8.0) for ti in (30, 60)
    }
    assert runs[0]["label"] == "k=2, Ti=30"
    # Built once per batch: one sweep job for the 8 variants (batch of 10).
    sweeps = [job for job in runtime.executor.jobs if job["kind"] == "sweep"]
    assert len(sweeps) == 1 and len(sweeps[0]["variants"]) == 8
    assert all(r["status"] == "done" and "indicators" in r["result"] for r in runs)
    level = {r["variant"]["controller.k"]: r["result"]["indicators"]["tank.level"] for r in runs}
    assert level[8.0]["final"] == 2 * level[4.0]["final"]
    assert level[4.0]["min"] <= level[4.0]["mean"] <= level[4.0]["max"]
    # Every simulation keeps the model's files and its own page.
    one = client.get(f"/api/runs/{runs[0]['id']}").json()
    assert one["study"]["id"] == study["id"] and one["status"] == "done"
    assert TLC_FILE in client.get(f"/api/runs/{one['id']}/files").json()
    listed = client.get("/api/studies", params={"project": project["id"]}).json()
    assert listed[0]["id"] == study["id"] and listed[0]["done"] == 8


def test_compare_statistics_and_export(client):
    project = example(client)
    study = client.post(f"/api/projects/{project['id']}/studies", json=SWEEP).json()
    study = wait_study(client, study["id"])
    ids = [run["id"] for run in study["runs"][:3]]
    series = client.post(
        f"/api/studies/{study['id']}/series", json={"name": "tank.level", "runs": ids}
    ).json()
    assert [item["run_id"] for item in series["series"]] == ids
    band = series["envelope"]
    assert band["runs"] == 3 and len(band["time"]) == len(band["p50"])
    assert all(
        lo <= mid <= hi
        for lo, mid, hi in zip(band["min"], band["p50"], band["max"], strict=True)
        if lo is not None
    )
    stats = client.get(f"/api/studies/{study['id']}/statistics").json()
    final = next(
        row for row in stats if row["variable"] == "tank.level" and row["statistic"] == "final"
    )
    assert final["n"] == 8 and final["min"] <= final["p50"] <= final["max"]
    exported = client.get(f"/api/studies/{study['id']}/export.zip")
    assert exported.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(exported.content))
    names = set(archive.namelist())
    assert {"parameters.csv", "results.csv", "study.ipynb", "study.json", "README.md"} <= names
    assert f"model/{TLC_FILE}" in names
    rows = list(csv.DictReader(io.StringIO(archive.read("parameters.csv").decode())))
    assert len(rows) == 8 and {"controller.k", "controller.Ti", "tank.level:final"} <= set(rows[0])
    results = list(csv.reader(io.StringIO(archive.read("results.csv").decode())))
    assert results[0][:2] == ["run_id", "time"] and len({row[0] for row in results[1:]}) == 8
    notebook = json.loads(archive.read("study.ipynb"))
    assert notebook["nbformat"] == 4 and any(
        "read_csv" in "".join(c["source"]) for c in notebook["cells"]
    )


def test_a_failed_variant_says_why_and_the_others_finish(client):
    project = example(client)
    body = {
        **SWEEP,
        "sweep": [{"name": "fail", "mode": "list", "values": [False, True]}],
    }
    study = client.post(f"/api/projects/{project['id']}/studies", json=body).json()
    study = wait_study(client, study["id"])
    assert study["done"] == 1 and study["failed"] == 1
    failed = next(r for r in study["runs"] if r["status"] == "failed")
    assert "division by zero" in failed["summary"]


def test_a_study_over_the_limit_is_refused(tmp_path, fake):
    runtime = make_runtime(tmp_path, fake, study_max_runs=5)
    try:
        with client_for(runtime, fake) as client:
            project = example(client)
            refused = client.post(f"/api/projects/{project['id']}/studies", json=SWEEP)
            assert refused.status_code == 422 and "limit is 5" in refused.json()["detail"]
            bad = client.post(
                f"/api/projects/{project['id']}/studies",
                json={**SWEEP, "sweep": [{"name": "x", "mode": "range", "start": 0}]},
            )
            assert bad.status_code == 422
    finally:
        runtime.shutdown()


def test_quick_simulations_join_the_models_quick_study(client):
    project = example(client)
    run = client.post(
        f"/api/projects/{project['id']}/simulate", json={"model": TLC, "stop": 900}
    ).json()
    wait_for(client, run["id"])
    again = client.post(
        f"/api/projects/{project['id']}/simulate", json={"model": TLC, "stop": 900}
    ).json()
    wait_for(client, again["id"])
    studies = [s for s in client.get("/api/studies").json() if s["kind"] == "quick"]
    assert len(studies) == 1 and studies[0]["total"] == 2
    assert client.get(f"/api/runs/{run['id']}").json()["study"]["kind"] == "quick"


def test_cancel_a_study_and_follow_the_queue(client, runtime):
    hold = threading.Event()
    runtime.executor.hold = hold
    try:
        _cancel_while_running(client, hold)
    finally:
        hold.set()


def _cancel_while_running(client, hold):
    project = example(client)
    study = client.post(f"/api/projects/{project['id']}/studies", json=SWEEP).json()
    deadline = time.monotonic() + 5
    first = None
    while time.monotonic() < deadline:
        queue = client.get("/api/queue/runs").json()
        first = next((r for r in queue["running_runs"] if r["label"] == "k=2, Ti=30"), None)
        if first is not None and first["progress"]:
            break
        time.sleep(0.02)
    assert queue["running"] == 8 and queue["busy"] == 1
    # The first variant is half way: its results file reaches 450 s of 900 s.
    assert first is not None
    assert first["progress"] == 0.5
    assert client.post(f"/api/studies/{study['id']}/cancel").json()["cancelled"] == 8
    study = wait_study(client, study["id"])
    assert study["cancelled"] == 8 and study["done"] == 0
    assert client.delete(f"/api/studies/{study['id']}").status_code == 204
    assert client.get(f"/api/studies/{study['id']}").status_code == 404


def test_a_quick_simulation_goes_ahead_of_a_sweep(client, runtime):
    hold = threading.Event()
    runtime.executor.hold = hold
    try:
        _quick_first(client, hold)
    finally:
        hold.set()


def _quick_first(client, hold):
    project = example(client)
    first = client.post(f"/api/projects/{project['id']}/studies", json=SWEEP).json()
    second = client.post(f"/api/projects/{project['id']}/studies", json=SWEEP).json()
    quick = client.post(
        f"/api/projects/{project['id']}/simulate", json={"model": TLC, "stop": 900}
    ).json()
    queue = client.get("/api/queue/runs").json()
    waiting = [run["id"] for run in queue["queued_runs"]]
    assert waiting[0] == quick["id"]
    hold.set()
    for study in (first, second):
        assert wait_study(client, study["id"])["done"] == 8
    assert wait_for(client, quick["id"])["status"] == "done"


def test_a_restart_puts_running_simulations_back_in_the_queue(tmp_path, fake):
    runtime = make_runtime(tmp_path, fake)
    with client_for(runtime, fake) as client:
        project = example(client)
        runtime.workbench.queue.shutdown()  # nobody takes the work: it stays queued
        runtime.workbench.queue.wake = lambda: None
        study = client.post(f"/api/projects/{project['id']}/studies", json=SWEEP).json()
        ids = [run["id"] for run in client.get(f"/api/studies/{study['id']}").json()["runs"]]
        runtime.runs.started(ids[:2], "job-lost")
    runtime.shutdown()
    again = make_runtime(tmp_path, fake)
    again.start()
    try:
        with client_for(again, fake) as client:
            assert wait_study(client, study["id"])["done"] == 8
    finally:
        again.shutdown()


def test_block_libraries_are_shared_by_every_project(client, runtime):
    libraries = client.get("/api/blocks").json()
    assert [(lib["group"], lib["name"]) for lib in libraries] == [
        ("Control", "Control"),
        ("Dynamics", "Continuous"),
        ("Equipment", "Process equipment"),
        ("Signals", "Math"),
        ("Signals", "Sinks"),
        ("Signals", "Sources"),
    ]
    equipment = libraries[2]
    assert {block["name"] for block in equipment["blocks"]} >= {
        "PlantCraftEquipment.Tank",
        "PlantCraftEquipment.ControlValve",
        "PlantCraftEquipment.Pump",
    }
    assert all(
        lib["id"] not in {p["id"] for p in client.get("/api/projects").json()} for lib in libraries
    )
    project = client.post("/api/projects", json={"name": "Uses blocks"}).json()
    model = (
        "model UsesBlocks\n  PlantCraftEquipment.Tank tank;\n"
        "  Modelica.Blocks.Sources.Constant q(k = 0.1);\n  Modelica.Blocks.Sources.Constant u(k = 0.5);\n"
        "equation\n  connect(q.y, tank.qIn);\n  connect(u.y, tank.opening);\nend UsesBlocks;\n"
    )
    current = client.get(f"/api/projects/{project['id']}/files/UsesBlocks.mo").json()
    client.put(
        f"/api/projects/{project['id']}/files/UsesBlocks.mo",
        json={"content": model, "base_updated_at": current["updated_at"]},
    )
    checked = client.post(
        f"/api/projects/{project['id']}/check", json={"model": "UsesBlocks"}
    ).json()
    assert checked["ok"]
    sent = runtime.executor.jobs[-1]
    assert sent["kind"] == "check"
    run = client.post(
        f"/api/projects/{project['id']}/simulate", json={"model": "UsesBlocks", "stop": 10}
    ).json()
    files = client.get(f"/api/runs/{run['id']}/files").json()
    assert "PlantCraftEquipment/Tank.mo" in files and "UsesBlocks.mo" in files
    created = client.post("/api/blocks", json={"name": "Utilities", "group": "Equipment"})
    assert created.status_code == 201 and created.json()["packages"] == ["Utilities"]
    assert client.post("/api/blocks", json={"name": "Utilities"}).status_code == 409
    changed = client.patch(f"/api/blocks/{created.json()['id']}", json={"group": "Utilities"})
    assert changed.json()["group"] == "Utilities"


def test_viewers_cannot_start_or_cancel_studies(runtime, fake, client):
    project = example(client)
    with client_for(runtime, fake, "operator") as viewer:
        assert viewer.post(f"/api/projects/{project['id']}/studies", json=SWEEP).status_code == 403
        assert viewer.post("/api/blocks", json={"name": "Mine"}).status_code == 403
        assert viewer.get("/api/blocks").status_code == 200
        assert viewer.get("/api/queue").status_code == 200


def test_settling_indicators_measure_how_a_response_reaches_its_final_value():
    import numpy as np

    from modelcraft.runs.studies import settling

    t = np.linspace(0, 100, 1001)
    response = 1 - np.exp(-t / 10) * np.cos(t / 3)
    found = settling(t, response)
    assert 40 < found["overshoot"] < 41 and 30 < found["settling"] < 32 and found["iae"] > 0
    assert settling(t, -response)["overshoot"] == found["overshoot"]  # falling the same way
    assert settling(t, np.ones_like(t)) == {"overshoot": 0.0, "settling": 0.0, "iae": 0.0}
    assert settling(t[:1], response[:1])["settling"] is None


def test_the_queue_answers_the_suite_panel(client, runtime):
    project = example(client)
    run = client.post(
        f"/api/projects/{project['id']}/simulate", json={"model": TLC, "stop": 10}
    ).json()
    wait_for(client, run["id"])
    runtime.queue_sampler.sample()
    answer = client.get("/api/queue", params={"window": "1h"}).json()
    assert answer["format"] == "plantcraft-queue/1" and answer["window"] == "1h"
    assert answer["now"]["done_hour"] >= 1 and answer["now"]["workers"] >= 1
    assert (
        answer["history"] and client.get("/api/queue", params={"window": "2y"}).status_code == 422
    )


def test_an_example_study_is_ready_after_the_first_start(tmp_path, fake):
    """Round 9 (D13): every install starts with a study already run, queued once by Models."""

    from modelcraft.api.runtime import EXAMPLE_STUDY

    runtime = make_runtime(tmp_path, fake, example_study=True)
    try:
        with client_for(runtime, fake) as client:
            listed = client.get("/api/studies").json()
            [found] = [s for s in listed if s["name"] == EXAMPLE_STUDY["name"]]
            study = wait_study(client, found["id"])
            assert study["model"] == TLC and study["created_by"] == "modelcraft"
            assert study["total"] == 3 and study["done"] == 3
            assert runtime.seed_example_study() is None  # once: a restart does not queue again
    finally:
        runtime.shutdown()


def test_a_study_drives_inputs_and_varies_the_simulation_settings(client, runtime):
    """Round 9 M6-M8: an input as a step whose value is swept, the integrator in a list, each
    simulation its own time; the inputs reach omc as a CSV per simulation, never as overrides."""

    project = example(client)
    body = {
        **SWEEP,
        "name": "Inputs and integrators",
        "sweep": [
            {"name": "u", "mode": "list", "values": [60, 70]},
            {"name": "@method", "mode": "list", "values": ["dassl", "ida"]},
        ],
        "overrides": {"d": 55},
        "inputs": {
            "u": {"shape": "step", "before": 50, "at": 100},
            "d": {"shape": "constant"},
        },
    }
    created = client.post(f"/api/projects/{project['id']}/studies", json=body)
    assert created.status_code == 201, created.text
    spec = created.json()["spec"]
    assert spec["options"]["overrides"] == {}
    assert spec["options"]["inputs"]["d"] == {"shape": "constant", "value": 55.0}
    study = wait_study(client, created.json()["id"])
    assert study["done"] == 4
    assert {run["label"] for run in study["runs"]} >= {"u=60, method=dassl", "u=70, method=ida"}
    index = next(i for i, job in enumerate(runtime.executor.jobs) if job["kind"] == "sweep")
    job, extra = runtime.executor.jobs[index], runtime.executor.extras[index]
    assert all("u" not in variant for variant in job["variants"])
    assert {variant["@method"] for variant in job["variants"]} == {"dassl", "ida"}
    assert "inputs" not in job["options"] and len(job["inputs_files"]) == 4
    rows = [line.split(",") for line in extra["inputs_0.csv"].decode().split()]
    assert rows[0] == ["time", "u", "d"]
    assert [float(row[1]) for row in rows[1:]] == [50, 50, 60, 60]
    assert {float(row[2]) for row in rows[1:]} == {55}
    assert len({run["seconds"] for run in study["runs"]}) == 4


def test_a_study_refuses_inputs_without_a_value_and_odd_settings(client):
    project = example(client)
    url = f"/api/projects/{project['id']}/studies"
    for change in (
        {"inputs": {"u": {"shape": "constant"}}},
        {"inputs": {"u": {"shape": "step", "value": 3}}},
        {"inputs": {"u": {"shape": "ramp", "value": 3, "before": 0, "at": 5, "end": 2}}},
        {"sweep": [{"name": "@method", "mode": "range", "start": 0, "stop": 1, "count": 2}]},
        {"sweep": [{"name": "@method", "mode": "list", "values": ["rm"]}]},
        {"sweep": [{"name": "@tolerance", "mode": "list", "values": [1]}]},
        {"sweep": [{"name": "@stop", "mode": "list", "values": [-5]}]},
        {"sweep": [{"name": "@other", "mode": "list", "values": [1]}]},
    ):
        answer = client.post(url, json={**SWEEP, **change})
        assert answer.status_code == 422, (change, answer.text)


def test_any_variable_is_measured_after_the_study_ran(client):
    """Round 9 M10: the indicators of a variable the study did not name, computed on asking."""

    project = example(client)
    study = client.post(f"/api/projects/{project['id']}/studies", json=SWEEP).json()
    study = wait_study(client, study["id"])
    kept = client.post(f"/api/studies/{study['id']}/indicators", json={"name": "tank.level"})
    assert kept.status_code == 200 and len(kept.json()["runs"]) == 8
    names = [
        item["name"]
        for item in client.get(f"/api/runs/{study['runs'][0]['id']}/variables").json()
        if item["column"] is not None and item["name"] not in ("time", "tank.level")
    ]
    other = client.post(f"/api/studies/{study['id']}/indicators", json={"name": names[0]}).json()
    assert len(other["runs"]) == 8
    assert set(next(iter(other["runs"].values()))) >= {"final", "max", "iae"}
    junk = client.post(f"/api/studies/{study['id']}/indicators", json={"name": "a b"})
    assert junk.status_code == 422
