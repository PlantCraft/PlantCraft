"""Models' objects for notebooks (``plantcraft-objects/1``): models and runs read with
``pc.app("models")``, a simulation queued from a notebook only when an administrator allows it,
and the examples run as a person's notebook runs them."""

from __future__ import annotations

from pathlib import Path

from plantcraft_sdk import apptest
from plantcraft_sdk.notebooks import example_problems

from modelcraft.notebook_examples import EXAMPLES
from tests.conftest import TLC, client_for, example, wait_for

ROOT = Path(__file__).resolve().parents[1]


def _model_id(client) -> str:
    return f"{example(client)['id']}/{TLC}"


def _allow(fake, on: bool = True) -> None:
    fake.links.settings["modelcraft"] = {"notebook_runs": on}


def test_models_serves_its_models_and_runs_in_the_suite_format(client):
    assert apptest.objects_problems(client, "", ROOT) == []
    assert example_problems(EXAMPLES) == []
    listed = client.get("/api/objects/model").json()["items"]
    assert _model_id(client) in {item["id"] for item in listed}
    one = client.get(f"/api/objects/model/{_model_id(client)}").json()
    assert one["kind"] == "model" and one["model"] == TLC and "settings" in one
    assert "diagram" not in one


def test_a_simulation_from_a_notebook_waits_for_the_administrator(client, fake):
    model_id = _model_id(client)
    refused = client.post("/api/objects/model/run", json={"id": model_id})
    assert refused.status_code == 403 and "Setup" in refused.json()["detail"]
    _allow(fake)
    started = client.post(
        "/api/objects/model/run", json={"id": model_id, "options": {"stop": 20, "label": "nb"}}
    )
    assert started.status_code == 201, started.text
    reference = started.json()["started"]
    assert reference["kind"] == "run"
    run = wait_for(client, reference["id"])
    assert run["status"] == "done" and run["options"]["stop"] == 20 and run["label"] == "nb"
    read = client.get(f"/api/objects/run/{reference['id']}").json()
    assert read["status"] == "done" and read["results"]
    first = next(iter(read["results"].values()))
    assert len(first["time"]) == len(first["values"]) > 1
    assert (
        client.post(
            "/api/objects/model/run", json={"id": model_id, "options": {"colour": "red"}}
        ).status_code
        == 422
    )
    assert client.post("/api/objects/model/run", json={"id": "x/Nope"}).status_code == 404


def test_a_viewer_reads_but_does_not_simulate(runtime, fake):
    _allow(fake)
    with client_for(runtime, fake, "operator") as viewer:
        assert viewer.get("/api/objects/model").status_code == 200
        answer = viewer.post("/api/objects/model/run", json={"id": _model_id(viewer)})
        assert answer.status_code == 403


def test_every_example_runs_as_a_notebook_runs_it(client, fake):
    _allow(fake)
    problems = apptest.run_examples(EXAMPLES, client, "", fake, root=ROOT)
    assert problems == [], "\n".join(problems)
