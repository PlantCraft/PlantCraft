"""Trackings (M3): a model run against the plant on a schedule, its error kept as a signal and
an optional alarm when it drifts past a limit."""

from __future__ import annotations

import time
from datetime import timedelta

import pytest

from modelcraft.runs.tracking import error_signal, errors, summary
from tests.conftest import TLC, client_for, example
from tests.plant import NOW


def _signal(client) -> str:
    return next(s["id"] for s in client.get("/api/signals", params={"q": "FIC"}).json())


def _settled(runtime, tracking_id: str, seconds: float = 10) -> dict:
    deadline = time.monotonic() + seconds
    while True:
        found = runtime.trackings.get(tracking_id)
        if found["last"].get("status") in ("done", "failed") or time.monotonic() > deadline:
            return found
        time.sleep(0.02)


def test_the_error_is_the_model_minus_the_plant_at_the_plants_times():
    times, values = errors([0, 10, 20], [0.0, 10.0, 20.0], [5, 15, 25, -1], [4.0, 16.0, 0.0, 0.0])
    assert times == [5.0, 15.0] and values == pytest.approx([1.0, -1.0])
    assert summary(values) == {"mae": 1.0, "bias": 0.0, "max": 1.0, "last": -1.0, "n": 2}
    assert summary([])["mae"] is None
    assert error_signal("abc", "tank.level") == "app-modelcraft:tracking-abc.tank.level.error"
    assert error_signal("abc", "x[1]") == "app-modelcraft:tracking-abc.x_1_.error"


def test_a_tracking_runs_when_due_and_writes_its_error_as_a_signal(client, runtime, fake):
    project = example(client)
    signal = _signal(client)
    body = {
        "project_id": project["id"],
        "model": TLC,
        "name": "Tank 1",
        "inputs": {"qin": signal},
        "compare": {"tank.level": signal},
        "window_minutes": 60,
        "every_minutes": 15,
        "step_seconds": 60,
    }
    created = client.post("/api/trackings", json=body)
    assert created.status_code == 201, created.text
    tracking = created.json()
    assert tracking["signals"] == {"tank.level": error_signal(tracking["id"], "tank.level")}
    # Due at once (here at the test plant's clock); the next one 15 min later.
    runtime.trackings.update(tracking["id"], next_at=NOW.isoformat())
    assert runtime.tracker.tick(NOW) == 1
    assert runtime.tracker.tick(NOW + timedelta(minutes=5)) == 0
    done = _settled(runtime, tracking["id"])
    assert done["last"]["status"] == "done", done["last"]
    metrics = done["last"]["metrics"]["tank.level"]
    assert metrics["n"] > 30 and metrics["mae"] is not None
    run = runtime.runs.get(done["last"]["run_id"])
    assert run["options"]["tracking"] == tracking["id"] and run["label"] == "Tracking: Tank 1"
    assert run["options"]["plant"]["end"].startswith(NOW.strftime("%Y-%m-%dT%H:%M"))
    written = fake.derived.get(tracking["signals"]["tank.level"]) or {}
    assert len(written) == metrics["n"]
    assert done["last"]["written"] == 1  # series written
    assert runtime.tracker.tick(NOW + timedelta(minutes=15)) == 1
    # Everyone reads it; a viewer cannot change or run it.
    with client_for(runtime, fake, "operator") as viewer:
        assert viewer.get(f"/api/trackings/{tracking['id']}").status_code == 200
        assert viewer.post(f"/api/trackings/{tracking['id']}/run").status_code == 403
        assert viewer.delete(f"/api/trackings/{tracking['id']}").status_code == 403


def test_a_limit_opens_the_mismatch_and_closes_it_when_back(client, runtime, fake):
    project = example(client)
    signal = _signal(client)
    body = {
        "project_id": project["id"],
        "model": TLC,
        "name": "Tank 2",
        "inputs": {"qin": signal},
        "compare": {"tank.level": signal},
        "step_seconds": 60,
        "limits": {"tank.level": 1e-9},
    }
    tracking = client.post("/api/trackings", json=body).json()
    runtime.tracker.run_now(tracking, NOW)
    done = _settled(runtime, tracking["id"])
    assert done["open"] == ["tank.level"]
    mismatch = [e for e in fake.links.events if e["kind"] == "modelcraft.tracking.mismatch"]
    assert [(e["phase"], e["key"]) for e in mismatch] == [
        ("start", f"tracking:{tracking['id']}:tank.level")
    ]
    # A generous limit: back with the plant, the condition ends.
    updated = client.put(
        f"/api/trackings/{tracking['id']}", json={**body, "limits": {"tank.level": 1e12}}
    )
    assert updated.status_code == 200, updated.text
    runtime.tracker.run_now(runtime.trackings.get(tracking["id"]), NOW + timedelta(minutes=15))
    deadline = time.monotonic() + 10
    while runtime.trackings.get(tracking["id"])["open"] and time.monotonic() < deadline:
        time.sleep(0.02)
    assert runtime.trackings.get(tracking["id"])["open"] == []
    mismatch = [e for e in fake.links.events if e["kind"] == "modelcraft.tracking.mismatch"]
    assert [e["phase"] for e in mismatch] == ["start", "end"]


def test_a_limit_must_name_a_compared_variable_and_a_period_must_be_sane(client):
    project = example(client)
    signal = _signal(client)
    body = {
        "project_id": project["id"],
        "model": TLC,
        "name": "x",
        "compare": {"tank.level": signal},
    }
    assert client.post("/api/trackings", json={**body, "limits": {"other": 1}}).status_code == 422
    assert client.post("/api/trackings", json={**body, "every_minutes": 1}).status_code == 422
    assert client.post("/api/trackings", json={**body, "compare": {}}).status_code == 422
    assert client.post("/api/trackings", json={**body, "project_id": "nope"}).status_code == 404


def test_a_tracking_that_cannot_read_the_plant_says_why(client, runtime):
    project = example(client)
    body = {"project_id": project["id"], "model": TLC, "name": "Lost",
            "compare": {"tank.level": "nope:missing"}}  # fmt: skip
    tracking = client.post("/api/trackings", json=body).json()
    answer = client.post(f"/api/trackings/{tracking['id']}/run").json()
    assert answer["last"]["status"] == "failed" and answer["last"]["detail"]
