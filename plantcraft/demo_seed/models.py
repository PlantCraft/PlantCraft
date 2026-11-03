"""PlantCraft Models: simulations, studies, the level controller's optimization and the Furnaces
FMU published to Analytics."""

from __future__ import annotations

import time
import urllib.parse
from typing import Any

from .base import Http, SeedError, Suite, _detail, log, wait_until

# PlantCraft Models --------------------------------------------------------------------------

# (model, label): one run of each example with its own simulation settings, as Run on the
# model's page does (Executions groups them as the model's single runs).
MODEL_RUNS = [
    ("PlantCraftExamples.TankLevelControl", "Base case"),
    ("PlantCraftExamples.HeatExchangerOutlet", "Base case"),
    ("PlantCraftExamples.FirstOrderDeadTimeLoop", "Base case"),
]
# Grid studies the demo leaves ready to compare ("a tank of several sizes").
MODEL_STUDIES = [
    {
        "model": "PlantCraftExamples.TankLevelControl",
        "name": "Tank size",
        "description": "Which tank holds the level best through the setpoint and outlet steps: "
        "five cross-sections by three outlet valves.",
        "sweep": [
            {"name": "tank.A", "mode": "range", "start": 2, "stop": 6, "count": 5},
            {"name": "tank.Cv", "mode": "list", "values": [0.03, 0.05, 0.08]},
        ],
        "indicators": ["tank.level", "pump.speed"],
    },
    {
        "model": "PlantCraftExamples.HeatExchangerOutlet",
        "name": "Heat exchanger area",
        "description": "How much area cools the hot outlet enough after the hot flow rises.",
        "sweep": [{"name": "exchanger.A", "mode": "list", "values": [5, 10, 15, 20, 30]}],
        "indicators": ["exchanger.Th_out", "exchanger.duty"],
    },
]
# An optimization study (Models, 2026-10-26): the level controller's gain and integral time that
# follow the setpoint step with the least error, overshooting it by 5 % at most.
MODEL_OPTIMIZATION = {
    "model": "PlantCraftExamples.TankLevelControl",
    "name": "Tune the level controller",
    "description": "The gain and integral time that bring the tank's level to its new setpoint "
    "with the least error (IAE), overshooting it by 5 % at most. COBYLA, one simulation at a time.",
    "indicators": ["tank.level", "pump.speed"],
    "optimization": {
        "variables": [
            {"name": "controller.k", "start": 4, "min": 1, "max": 10},
            {"name": "controller.Ti", "start": 60, "min": 10, "max": 300},
        ],
        "objective": {"variable": "tank.level", "statistic": "iae", "goal": "minimize"},
        "constraints": [
            {"variable": "tank.level", "statistic": "overshoot", "op": "<=", "value": 5}
        ],
        "method": "cobyla",
        "max_simulations": 40,
    },
}
MODEL_FMU = "PlantCraftTwin.Furnaces"
MODEL_FMU_LABEL = "Furnaces for Analytics"
MODEL_PLANT_LABEL = "{loop} on the last hour"
# The loop a LoopProcess simulation is fed by, with its parameters in the Simulator (Analytics'
# FIC-1001 model example).
PLANT_LOOP = "FIC-1001"
PLANT_LOOP_PARAMETERS = {"K": 0.55, "tau": 110.0, "theta": 8.0, "y0": 55.0}
CALIBRATION_HOURS = 6


def _model_run(model: Http, project_id: str, kind: str, body: dict[str, Any], wait: float) -> Any:
    run = model.post(f"/api/projects/{project_id}/{kind}", body)
    return wait_until(
        f"Models: {body['model']} ({kind})",
        lambda: (
            lambda found: found if found["status"] in ("done", "failed", "cancelled") else None
        )(model.get(f"/api/runs/{run['id']}")),
        wait,
        every=4.0,
    )


def _settings(model: Http, project_id: str, name: str) -> dict[str, Any]:
    """The model's own simulation settings, as a study's start, stop, intervals and solver."""

    found = model.get(f"/api/models/{project_id}/{urllib.parse.quote(name, safe='')}")["settings"]
    start, stop = float(found["start"]), float(found["stop"])
    intervals = max(1, min(200_000, round((stop - start) / float(found["interval"]))))
    return {
        "start": start,
        "stop": stop,
        "intervals": intervals,
        "tolerance": found["tolerance"],
        "method": found["solver"],
    }


def _signal_of(platform: Http, source: dict[str, Any], cache: dict[str, Any]) -> str | None:
    if source.get("signal_id"):
        return source["signal_id"]
    asset = source.get("asset_id")
    if not asset:
        return None
    if asset not in cache:
        cache[asset] = platform.call(
            "GET", f"/api/v1/assets/{urllib.parse.quote(asset)}", ok=(404,)
        )[1]
    return ((cache[asset] or {}).get("signals") or {}).get(source.get("role") or "")


def _plant_run(platform: Http) -> tuple[str, dict[str, Any]] | None:
    """A simulation of FIC-1001's process model on the plant's last hour, compared with it."""

    cache: dict[str, Any] = {}
    valve = _signal_of(platform, {"asset_id": PLANT_LOOP, "role": "op"}, cache)
    measured = _signal_of(platform, {"asset_id": PLANT_LOOP, "role": "pv"}, cache)
    if not valve or not measured:
        return None
    end = time.time() - 60
    stamp = lambda moment: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(moment))  # noqa: E731
    return PLANT_LOOP, {
        "model": "PlantCraftTwin.LoopProcess",
        "start": 0,
        "stop": 3600,
        "intervals": 720,
        "overrides": {**PLANT_LOOP_PARAMETERS, "y_start": PLANT_LOOP_PARAMETERS["y0"]},
        "label": MODEL_PLANT_LABEL.format(loop=PLANT_LOOP),
        "plant": {
            "start": stamp(end - 3600),
            "end": stamp(end),
            "step": 5,
            "inputs": {"u": valve},
            "compare": {"y": measured},
        },
    }


def _model_study(model: Http, project_id: str, plan: dict[str, Any], wait: float) -> None:
    """A grid study, started once and followed until its simulations end."""

    body = {"model": plan["model"], **_settings(model, project_id, plan["model"])}
    body.update({key: value for key, value in plan.items() if key != "model"})
    study = model.post(f"/api/projects/{project_id}/studies", body)
    found = wait_until(
        f"Models: the study {plan['name']}",
        lambda: (lambda got: got if not got["queued"] and not got["running"] else None)(
            model.get(f"/api/studies/{study['id']}")
        ),
        wait,
        every=4.0,
    )
    log(f"Models: study '{plan['name']}', {found['done']} of {found['total']} simulations done")


def modelcraft(model: Http, suite: Suite, link: Http | None, platform: Http) -> None:
    """A run of each example diagram, one simulation on plant data, the grid studies "Tank size"
    and "Heat exchanger area" ready to compare, and the Furnaces FMU running in Analytics.
    Re-runnable: a run whose label is already there is not started again, nor a study."""

    wait_until(
        "the Modelica runner",
        lambda: model.get("/api/runner").get("available"),
        suite.wait,
        every=5.0,
    )
    projects = {item["name"]: item for item in model.get("/api/projects")}
    examples = projects.get("Examples")
    twins = projects.get("Analytics models")
    if not examples or not twins:
        raise SeedError("the example projects are missing in Models")
    done = {(run["model"], run.get("label")) for run in model.get("/api/runs?limit=1000")}
    for name, label in MODEL_RUNS:
        if (name, label) in done:
            continue
        run = model.post(
            f"/api/models/{examples['id']}/{urllib.parse.quote(name, safe='')}/run",
            {"label": label},
        )
        found = wait_until(
            f"Models: {name}",
            lambda run=run: (
                lambda got: got if got["status"] in ("done", "failed", "cancelled") else None
            )(model.get(f"/api/runs/{run['id']}")),
            suite.wait,
            every=4.0,
        )
        log(f"Models: {name} '{label}' {found['status']}")
    plan = _plant_run(platform)
    if plan and (plan[1]["model"], plan[1]["label"]) not in done:
        status, run = model.call(
            "POST", f"/api/projects/{twins['id']}/simulate", plan[1], ok=(422,)
        )
        if status == 422:
            log(f"Models: {plan[0]} on plant data skipped ({_detail(run)})")
        else:
            log(f"Models: LoopProcess fed by {plan[0]}'s last hour")
    studies = {item["name"] for item in model.get("/api/studies")}
    for plan_study in MODEL_STUDIES:
        if plan_study["name"] not in studies:
            _model_study(model, examples["id"], plan_study, suite.wait)
    if MODEL_OPTIMIZATION["name"] not in studies:
        # Started and left to the queue: it runs on while the seed goes on (a few minutes).
        body = {
            **_settings(model, examples["id"], MODEL_OPTIMIZATION["model"]),
            **MODEL_OPTIMIZATION,
        }
        status, answer = model.call(
            "POST", f"/api/projects/{examples['id']}/studies", body, ok=(422,)
        )
        log(
            f"Models: optimization '{MODEL_OPTIMIZATION['name']}' started"
            if status < 300
            else f"Models: optimization skipped ({_detail(answer)})"
        )
    fmu = next(
        (
            run
            for run in model.get("/api/runs?kind=fmu&limit=1000")
            if run.get("label") == MODEL_FMU_LABEL and run["status"] == "done"
        ),
        None,
    )
    if fmu is None:
        body = {"model": MODEL_FMU, "version": "2.0", "type": "cs", "label": MODEL_FMU_LABEL}
        fmu = _model_run(model, twins["id"], "fmu", body, suite.wait)
        if fmu["status"] != "done":
            raise SeedError(f"the {MODEL_FMU} FMU failed: {fmu.get('summary')}")
        log(f"Models: {MODEL_FMU} exported as an FMI 2.0 co-simulation FMU")
