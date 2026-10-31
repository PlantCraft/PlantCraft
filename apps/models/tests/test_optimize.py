"""Optimization studies: the optimizer alone on a known function, then end to end against the
fake PlantCraft and the fake runner (whose ``tank.level`` scales with ``controller.k``: the final
level is 1.5 and the highest 1.542 at the model's own k = 4)."""

from __future__ import annotations

import time

import numpy as np
import pytest

from modelcraft.runs import optimize
from tests.conftest import TLC, client_for, example, make_runtime


def bowl(values: dict[str, float]) -> dict:
    a, b = values["a"], values.get("b", 0.0)
    return {
        "run_id": "",
        "indicators": {"z": {"final": (a - 1.3) ** 2 + (b + 0.4) ** 2 + 2, "max": a + b}},
    }


def spec(method: str, constraints=(), goal: str = "minimize", **objective) -> dict:
    return {
        "method": method,
        "variables": [
            {"name": "a", "start": 0, "min": -2, "max": 2},
            {"name": "b", "start": 0, "min": -2, "max": 2},
        ],
        "objective": {"variable": "z", "statistic": "final", "goal": goal, **objective},
        "constraints": list(constraints),
        "max_simulations": 80,
    }


def test_each_method_finds_the_bottom_of_a_bowl():
    found = optimize.run(spec("nelder-mead"), bowl)
    assert found["status"] == "done" and found["converged"]
    assert found["best"]["values"]["a"] == pytest.approx(1.3, abs=0.01)
    assert found["best"]["values"]["b"] == pytest.approx(-0.4, abs=0.01)
    # With a constraint a + b <= 0.5 the best is on its line, closest to (1.3, -0.4).
    limit = [{"variable": "z", "statistic": "max", "op": "<=", "value": 0.5}]
    for method in ("cobyla", "slsqp"):
        found = optimize.run(spec(method, limit), bowl)
        best = found["best"]
        assert best["feasible"], method
        assert best["values"]["a"] + best["values"]["b"] == pytest.approx(0.5, abs=0.01)
        assert best["values"]["a"] == pytest.approx(1.1, abs=0.05), method


def test_the_budget_a_failed_simulation_and_a_target():
    tight = {**spec("nelder-mead"), "max_simulations": 5}
    found = optimize.run(tight, bowl)
    assert len(found["evaluations"]) == 5 and "most simulations" in found["message"]

    def fails_left(values):
        return bowl(values) if values["a"] >= 0.25 else {"run_id": "", "indicators": None}

    found = optimize.run(spec("nelder-mead"), fails_left)
    assert any(item["failed"] for item in found["evaluations"])
    assert found["best"]["values"]["a"] == pytest.approx(1.3, abs=0.02)
    one = {
        **spec("nelder-mead", goal="target", target=3.0),
        "variables": [{"name": "a", "start": 0, "min": 0, "max": 2}],
    }
    found = optimize.run(one, bowl)
    assert found["best"]["objective"] == pytest.approx(3.0, abs=1e-3)


def test_refused_before_any_simulation():
    with pytest.raises(optimize.OptimizationError):
        optimize.check(
            spec("nelder-mead", [{"variable": "z", "statistic": "max", "op": "<=", "value": 1}])
        )
    with pytest.raises(optimize.OptimizationError):
        optimize.check({**spec("cobyla"), "variables": []})


OPTIMIZATION = {
    "model": TLC,
    "name": "Gain for a final level of 2.25",
    "start": 0,
    "stop": 900,
    "intervals": 450,
    "optimization": {
        "variables": [{"name": "controller.k", "start": 4, "min": 2, "max": 8}],
        "objective": {
            "variable": "tank.level",
            "statistic": "final",
            "goal": "target",
            "target": 2.25,
        },
        "max_simulations": 40,
    },
}


def wait_optimization(client, study_id: str, seconds: float = 20) -> dict:
    deadline = time.monotonic() + seconds
    while True:
        study = client.get(f"/api/studies/{study_id}").json()
        state = study.get("optimization") or {}
        if state.get("status") not in ("running", "waiting") or time.monotonic() > deadline:
            return study
        time.sleep(0.02)


def test_an_optimization_study_finds_the_gain(client, runtime):
    runtime.workbench.poll_seconds = 0.01
    project = example(client)
    created = client.post(f"/api/projects/{project['id']}/studies", json=OPTIMIZATION)
    assert created.status_code == 201, created.text
    study = wait_optimization(client, created.json()["id"])
    state = study["optimization"]
    assert study["kind"] == "optimization" and state["status"] == "done", state
    assert state["method"] == "nelder-mead"
    # The fake runner's final level is 1.5 * k / 4: 2.25 at k = 6.
    assert state["best"]["values"]["controller.k"] == pytest.approx(6.0, abs=0.01)
    assert len(state["evaluations"]) == study["total"] == study["done"]
    assert study["spec"]["indicators"] == ["tank.level"]
    best = next(run for run in study["runs"] if run["id"] == state["best"]["run_id"])
    assert best["result"]["indicators"]["tank.level"]["final"] == pytest.approx(2.25, abs=1e-3)
    # Each simulation went through the runner on its own, with the optimizer's value.
    assert all(len(job["variants"]) == 1 for job in runtime.executor.jobs if job["kind"] == "sweep")


def test_an_optimization_with_a_constraint(client, runtime):
    runtime.workbench.poll_seconds = 0.01
    project = example(client)
    body = {
        **OPTIMIZATION,
        "optimization": {
            **OPTIMIZATION["optimization"],
            "objective": {"variable": "tank.level", "statistic": "final", "goal": "maximize"},
            "constraints": [
                {"variable": "tank.level", "statistic": "max", "op": "<=", "value": 2.0}
            ],
        },
    }
    created = client.post(f"/api/projects/{project['id']}/studies", json=body).json()
    state = wait_optimization(client, created["id"])["optimization"]
    assert state["method"] == "cobyla" and state["best"]["feasible"]
    # The highest level is 1.5424 * k / 4: at most 2.0 means k up to 5.187.
    assert state["best"]["values"]["controller.k"] == pytest.approx(5.187, abs=0.02)


def test_optimizations_refuse_bad_settings(client):
    project = example(client)
    url = f"/api/projects/{project['id']}/studies"
    bad = {
        **OPTIMIZATION["optimization"],
        "variables": [{"name": "controller.k", "start": 9, "min": 2, "max": 8}],
    }
    assert client.post(url, json={**OPTIMIZATION, "optimization": bad}).status_code == 422
    nm = {
        **OPTIMIZATION["optimization"],
        "method": "nelder-mead",
        "constraints": [{"variable": "tank.level", "statistic": "max", "op": "<=", "value": 2}],
    }
    assert client.post(url, json={**OPTIMIZATION, "optimization": nm}).status_code == 422
    swept = {**OPTIMIZATION, "sweep": [{"name": "tank.A", "mode": "list", "values": [1, 2]}]}
    assert client.post(url, json=swept).status_code == 422


def test_cancel_an_optimization_and_it_goes_on_after_a_restart(tmp_path, fake):
    runtime = make_runtime(tmp_path, fake)
    runtime.workbench.poll_seconds = 0.01
    with client_for(runtime, fake) as client:
        project = example(client)
        url = f"/api/projects/{project['id']}/studies"
        cancelled = client.post(url, json=OPTIMIZATION).json()
        assert client.post(f"/api/studies/{cancelled['id']}/cancel").status_code == 200
        assert wait_optimization(client, cancelled["id"])["optimization"]["status"] == "stopped"
        # A restart in the middle: nobody runs the queue, the optimizer waits on its first run.
        runtime.workbench.queue.shutdown()
        runtime.workbench.queue.wake = lambda: None
        study = client.post(url, json=OPTIMIZATION).json()
        assert client.delete(f"/api/studies/{study['id']}").status_code == 409
    runtime.shutdown()
    again = make_runtime(tmp_path, fake)
    again.workbench.poll_seconds = 0.01
    again.start()
    try:
        with client_for(again, fake) as client:
            found = wait_optimization(client, study["id"])
            assert found["optimization"]["status"] == "done"
            assert found["optimization"]["best"]["values"]["controller.k"] == pytest.approx(
                6.0, abs=0.01
            )
            assert (
                client.get(f"/api/studies/{cancelled['id']}").json()["optimization"]["status"]
                == "stopped"
            )
    finally:
        again.shutdown()


def pi_loop(values: dict[str, float], stop: float = 300.0, dt: float = 0.1) -> dict:
    """The example FirstOrderDeadTimeLoop, simulated here (Euler, 0.1 s): a PI with output
    limits ±5 and anti-windup on a process of gain 2, lag 20 s and dead time 5 s, setpoint
    stepping to 1 at 10 s. Its measurement's indicators, as a study reads them."""

    from modelcraft.runs.studies import settling

    k, ti = values["controller.k"], values["controller.Ti"]
    steps = int(stop / dt) + 1
    times = np.arange(steps) * dt
    delay = [0.0] * int(round(5.0 / dt))
    state = integral = 0.0
    pv = np.zeros(steps)
    for index, now in enumerate(times):
        error = (1.0 if now >= 10.0 else 0.0) - delay[0]
        output = k * (error + integral / ti)
        if -5.0 < output < 5.0:
            integral += error * dt
        pv[index] = delay[0]
        state += dt * (2.0 * min(max(output, -5.0), 5.0) - state) / 20.0
        delay = [*delay[1:], state]
    return {"run_id": "", "indicators": {"dead_time.y": {"final": pv[-1], **settling(times, pv)}}}


def test_the_example_optimization_tunes_the_pi_for_the_least_iae():
    """M2: the example optimization Models seeds, run against the loop it tunes."""

    from modelcraft.api.runtime import EXAMPLE_OPTIMIZATION

    spec = EXAMPLE_OPTIMIZATION["spec"]["optimization"]
    optimize.check(spec)
    found = optimize.run(spec, pi_loop)
    best = found["best"]
    assert found["status"] == "done" and best["feasible"]
    assert len(found["evaluations"]) <= 40
    start = pi_loop({item["name"]: item["start"] for item in spec["variables"]})
    assert best["objective"] < 0.4 * start["indicators"]["dead_time.y"]["iae"]
    tuned = pi_loop(best["values"])["indicators"]["dead_time.y"]
    assert tuned["overshoot"] <= 10.0 + 0.1
    # Beside the SIMC rule for this process (k = T / (K (tau_c + theta)) = 1.0, Ti = 20 s).
    assert best["values"]["controller.k"] == pytest.approx(1.2, abs=0.15)
    assert best["values"]["controller.Ti"] == pytest.approx(21.0, abs=3.0)
