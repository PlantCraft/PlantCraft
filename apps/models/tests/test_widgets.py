"""Models' widgets for the PlantCraft Overview (contract v1)."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from plantcraft_sdk import apptest
from plantcraft_sdk.asset_scope import forget

from modelcraft.api.routers.widgets import day_starts
from tests.conftest import TLC, client_for, example, wait_for
from tests.plant import NOW
from tests.test_optimize import OPTIMIZATION, wait_optimization
from tests.test_studies import SWEEP, wait_study


def test_the_latest_runs_widget_links_each_run(client):
    listed = client.get("/api/widgets").json()
    assert [item["id"] for item in listed["widgets"] if item["default"]] == ["run-status"]
    assert client.get("/api/widgets/runs").json()["items"] == []
    project = example(client)
    run = client.post(
        f"/api/projects/{project['id']}/fmu", json={"model": TLC, "version": "2.0", "type": "cs"}
    ).json()
    wait_for(client, run["id"])
    data = client.get("/api/widgets/runs").json()
    assert data["kind"] == "list" and data["href"].endswith("/executions")
    item = data["items"][0]
    assert item["state"] == "ok" and item["href"].endswith(f"/runs/{run['id']}")
    assert item["detail"].startswith("FMU export")
    assert apptest.widget_problems(client, "") == []
    done = next(
        p for p in client.get("/api/widgets/run-status").json()["parts"] if p["state"] == "ok"
    )
    assert done["value"] == 1
    one = client.get("/api/widgets/model", params={"item": f"{project['id']}/{TLC}"}).json()
    assert one["kind"] == "facts" and one["state"] == "ok"
    assert client.get("/api/widgets/nope").status_code == 404


def test_the_models_widget_links_each_model(client):
    project = example(client)
    data = client.get("/api/widgets/models").json()
    assert data["kind"] == "list" and data["href"].endswith("/models")
    item = next(row for row in data["items"] if row["label"] == "TankLevelControl")
    assert item["href"].endswith(f"/models/{project['id']}/{TLC}") and item["detail"] == "Example"
    assert item["value"].endswith("blocks")
    # a model written as code has no diagram: it says so instead of "0 blocks"
    code = [row for row in data["items"] if row["label"] in {"Furnaces", "LoopProcess"}]
    assert code and all(row["value"] == "Code" for row in code)
    # The earlier name, kept for Overviews arranged before.
    assert client.get("/api/widgets/projects").json()["items"] == data["items"]


def test_the_activity_counts_each_days_simulations_by_status(client):
    data = client.get("/api/widgets/activity").json()
    assert data["kind"] == "columns" and data["step"] == "day" and data["value"] == 0
    assert len(data["buckets"]) == 14 and data["empty"].startswith("No simulation")
    assert [stack["state"] for stack in data["stacks"]] == ["ok", "alarm", "warning", "unknown"]
    project = example(client)
    run = client.post(f"/api/projects/{project['id']}/simulate", json={"model": TLC}).json()
    wait_for(client, run["id"])
    # An FMU export is not a simulation.
    fmu = client.post(
        f"/api/projects/{project['id']}/fmu", json={"model": TLC, "version": "2.0", "type": "cs"}
    ).json()
    wait_for(client, fmu["id"])
    data = client.get("/api/widgets/activity").json()
    assert data["value"] == 1 and data["label"] == "simulations in 14 days"
    assert data["buckets"][-1][1] == [1, 0, 0, 0] and data["href"].endswith("/executions")
    starts = [bucket[0] for bucket in data["buckets"]]
    assert starts == sorted(starts)


def test_days_start_at_midnight_on_the_installations_clock():
    zone = ZoneInfo("America/Sao_Paulo")
    starts = day_starts(datetime(2026, 10, 27, 2, 0, tzinfo=UTC), zone, 3)
    # 02:00 UTC is still the 26th in São Paulo (UTC-3).
    assert [start.isoformat() for start in starts] == [
        "2026-10-24T00:00:00-03:00",
        "2026-10-25T00:00:00-03:00",
        "2026-10-26T00:00:00-03:00",
    ]


def test_the_latest_study_says_what_a_sweep_gave(client):
    empty = client.get("/api/widgets/latest-study").json()
    assert empty["kind"] == "facts" and "title" not in empty and empty["empty"]
    project = example(client)
    # A quick simulation is not a study here.
    quick = client.post(f"/api/projects/{project['id']}/simulate", json={"model": TLC}).json()
    wait_for(client, quick["id"])
    assert "title" not in client.get("/api/widgets/latest-study").json()
    study = client.post(f"/api/projects/{project['id']}/studies", json=SWEEP).json()
    wait_study(client, study["id"])
    data = client.get("/api/widgets/latest-study").json()
    assert data["title"] == "Controller gain" and data["state"] == "ok"
    assert data["status"] == "Done" and data["detail"].startswith("TankLevelControl")
    assert data["href"].endswith(f"/studies/{study['id']}")
    facts = {fact["label"]: fact["value"] for fact in data["facts"]}
    assert facts["Cases done"] == "8 of 8" and facts["Failed"] == 0
    assert facts["Varied"] == "controller.k, controller.Ti"
    assert apptest.widget_problems(client, "") == []


def test_the_latest_study_gives_an_optimizations_best_values(client, runtime):
    runtime.workbench.poll_seconds = 0.01
    project = example(client)
    created = client.post(f"/api/projects/{project['id']}/studies", json=OPTIMIZATION).json()
    wait_optimization(client, created["id"])
    data = client.get("/api/widgets/latest-study").json()
    assert data["title"] == OPTIMIZATION["name"] and data["state"] == "ok"
    assert data["status"] == "Best found"
    facts = {fact["label"]: fact["value"] for fact in data["facts"]}
    assert facts["Final value of tank.level"] == pytest.approx(2.25, abs=1e-3)
    assert facts["controller.k"] == pytest.approx(6.0, abs=0.01)
    assert facts["Simulations"] >= 1


def test_simulations_on_plant_data_count_only_for_who_sees_them(client, runtime, fake):
    project = example(client)
    signal = next(s["id"] for s in client.get("/api/signals", params={"q": "FIC"}).json())
    body = {
        "model": TLC,
        "plant": {
            "start": NOW.replace(hour=6).isoformat(),
            "end": NOW.replace(hour=7).isoformat(),
            "step": 60,
            "inputs": {"qin": signal},
        },
    }
    run = client.post(f"/api/projects/{project['id']}/simulate", json=body).json()
    wait_for(client, run["id"])
    own = signal.split(".")[2]
    other = next(
        item["id"] for item in fake.assets if item.get("kind") == "loop" and item["id"] != own
    )
    forget()
    try:
        stranger = client_for(runtime, fake, None)
        stranger.headers["Authorization"] = f"Bearer {fake.token('engineer', assets=[other])}"
        with stranger:
            assert stranger.get("/api/widgets/activity").json()["value"] == 0
        assert client.get("/api/widgets/activity").json()["value"] == 1
    finally:
        forget()
