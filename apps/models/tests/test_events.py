"""The events Models writes: declared in app.toml, and a failed run reports one."""

from __future__ import annotations

import tomllib
from pathlib import Path

from tests.conftest import client_for, make_runtime, wait_for

MANIFEST = tomllib.loads((Path(__file__).resolve().parents[1] / "app.toml").read_text())


def test_a_failed_run_writes_its_declared_event(tmp_path, fake):
    fake.declare_events(MANIFEST)  # the fake refuses any event app.toml does not declare
    runtime = make_runtime(tmp_path, fake)
    try:
        with client_for(runtime, fake) as client:
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
            assert wait_for(client, run["id"])["status"] == "failed"
    finally:
        runtime.shutdown()
    [event] = [item for item in fake.links.events if item["kind"] == "modelcraft.run.failed"]
    assert event["subject"] == "app:modelcraft" and event["category"] == "run"
    assert event["severity"] == "warning" and event["payload"]["run_id"] == run["id"]


def test_a_finished_study_writes_its_declared_event_once(tmp_path, fake):
    from tests.conftest import example
    from tests.test_studies import SWEEP, wait_study

    fake.declare_events(MANIFEST)
    runtime = make_runtime(tmp_path, fake)
    try:
        with client_for(runtime, fake) as client:
            project = example(client)
            created = client.post(f"/api/projects/{project['id']}/studies", json=SWEEP).json()
            assert wait_study(client, created["id"])["done"] == 8
            quick = client.post(
                f"/api/projects/{project['id']}/simulate", json={"model": SWEEP["model"]}
            ).json()
            wait_for(client, quick["id"])
    finally:
        runtime.shutdown()
    [event] = [item for item in fake.links.events if item["kind"] == "modelcraft.study.finished"]
    assert event["payload"] == {
        "study_id": created["id"],
        "done": 8,
        "failed": 0,
        "url": f"/model/studies/{created['id']}",
    }
