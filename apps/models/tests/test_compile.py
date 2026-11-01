"""Compiled models (2026-11-01): Compile on a model's page keeps an FMU with the model, and the
page says whether the model is compiled, from which version, and when it fell out of date."""

from __future__ import annotations

from tests.conftest import TLC, TLC_FILE, client_for, editable_example, wait_for
from tests.test_versions import _save


def _build(client, pid: str) -> dict:
    answer = client.get(f"/api/models/{pid}/{TLC}/build")
    assert answer.status_code == 200, answer.text
    return answer.json()


def _compile(client, pid: str) -> dict:
    started = client.post(f"/api/models/{pid}/{TLC}/compile")
    assert started.status_code == 201, started.text
    run = wait_for(client, started.json()["id"])
    assert run["status"] == "done", run
    return run


def _listed(client, pid: str) -> str:
    models = client.get("/api/models").json()
    return next(m for m in models if m["project_id"] == pid and m["model"] == TLC)["build"]


def test_a_model_compiles_and_falls_out_of_date_when_it_changes(client):
    pid = editable_example(client)["id"]
    assert _build(client, pid) == {"state": "not_compiled", "compiled": None, "builds": []}
    assert _listed(client, pid) == "not_compiled"

    run = _compile(client, pid)
    assert run["kind"] == "fmu" and run["options"]["compile"] is True
    built = _build(client, pid)
    assert built["state"] == "compiled"
    compiled = built["compiled"]
    assert compiled["id"] == run["id"] and compiled["current"] and compiled["version"] == 1
    assert compiled["fmi_version"] == "2.0" and compiled["fmu_type"] == "cs"
    assert compiled["sha256"] and compiled["errors"] == 0
    assert client.get(f"/api/runs/{run['id']}/fmu").status_code == 200
    assert _listed(client, pid) == "compiled"

    _save(client, pid, TLC_FILE, lambda text: text.replace("Tank level control", "Tank level v2"))
    stale = _build(client, pid)
    assert stale["state"] == "out_of_date"
    # Still the compiled version, now known as version 1 of 2.
    assert stale["compiled"]["id"] == run["id"] and not stale["compiled"]["current"]
    assert stale["compiled"]["version"] == 1
    assert _listed(client, pid) == "out_of_date"

    again = _compile(client, pid)
    fresh = _build(client, pid)
    assert fresh["state"] == "compiled" and fresh["compiled"]["id"] == again["id"]
    assert fresh["compiled"]["version"] == 2
    assert [b["id"] for b in fresh["builds"]] == [again["id"], run["id"]]


def test_a_model_keeps_its_last_three_compilations(client):
    pid = editable_example(client)["id"]
    ids = [_compile(client, pid)["id"] for _ in range(4)]
    kept = [b["id"] for b in _build(client, pid)["builds"]]
    assert kept == list(reversed(ids))[:3]
    assert client.get(f"/api/runs/{ids[0]}").status_code == 404


def test_the_state_of_a_compilation(runtime):
    state = runtime.workbench.build_state

    def run(status: str, source: str = "now") -> dict:
        return {"id": status + source, "status": status, "options": {"source": source}}

    assert state([], "now") == ("not_compiled", None)
    assert state([run("done")], "now") == ("compiled", run("done"))
    assert state([run("done", "before")], "now") == ("out_of_date", run("done", "before"))
    # The newest attempt failed: said so, with the version that did compile kept.
    assert state([run("failed"), run("done", "before")], "now") == (
        "failed",
        run("done", "before"),
    )
    assert state([run("failed")], "now") == ("failed", None)
    assert state([run("queued"), run("done")], "now") == ("compiling", run("done"))
    assert state([run("cancelled"), run("done")], "now") == ("compiled", run("done"))


def test_compiling_needs_an_editor(runtime, fake, client):
    pid = editable_example(client)["id"]
    with client_for(runtime, fake, "operator") as viewer:
        assert viewer.post(f"/api/models/{pid}/{TLC}/compile").status_code == 403
        assert viewer.get(f"/api/models/{pid}/{TLC}/build").status_code == 200
    assert client.get(f"/api/models/{pid}/Nope.Model/build").status_code == 404
