"""Optimization studies: the values of a few parameters or inputs that make an indicator best.

A person picks the **decision variables** (parameters or inputs of the model, each with a start
value and bounds), an **objective** (an indicator of one variable, as a study measures it:
final value, overshoot, settling time, IAE...; minimized, maximized or brought to a target) and,
optionally, **constraints** on other indicators (``tank.level:max <= 2.5``). The optimizer asks
for one simulation at a time (``evaluate``), reads its indicators and decides the next point,
until it converges or reaches the most simulations allowed.

The methods are scipy's, all public and derivative-free or with finite differences:
Nelder-Mead (bounds, no constraints), COBYLA (bounds and constraints) and SLSQP (bounds and
constraints, gradients by finite differences). The variables are scaled to 0..1 between their
bounds, so one step size suits every variable whatever its unit.

The optimizer is deterministic: the same study run again asks for the same points, which is how
an optimization interrupted by a restart picks up where it was (the simulations it already has
answer at once).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import numpy as np
from scipy import optimize as sp

from modelcraft.i18n import t
from modelcraft.runs.studies import STATISTICS

METHODS = ("nelder-mead", "cobyla", "slsqp")
GOALS = ("minimize", "maximize", "target")
OPERATORS = ("<=", ">=")
MAX_VARIABLES = 10
MAX_CONSTRAINTS = 10
# What a simulation that failed (or lacks the indicator) costs the optimizer.
PENALTY = 1e12
# The first step, as a share of each variable's range between its bounds.
FIRST_STEP = 0.25


class OptimizationError(ValueError):
    """An optimization the server refuses, with words a person can act on."""


class Stop(Exception):
    """The optimization was cancelled: no more simulations."""


class _Budget(Exception):
    """The most simulations allowed are done."""


def check(spec: dict[str, Any]) -> None:
    """Refuse an optimization that cannot run, before any simulation starts."""

    variables = spec.get("variables") or []
    if not variables:
        raise OptimizationError(t("Choose at least one value to optimize."))
    if len(variables) > MAX_VARIABLES:
        raise OptimizationError(t("At most {n} values can be optimized together.", n=MAX_VARIABLES))
    names = [item["name"] for item in variables]
    if len(set(names)) != len(names):
        raise OptimizationError(t("A value is optimized twice."))
    for item in variables:
        low, high, start = float(item["min"]), float(item["max"]), float(item["start"])
        if not low < high:
            raise OptimizationError(
                t("{name}: the smallest value must be below the largest.", name=item["name"])
            )
        if not low <= start <= high:
            raise OptimizationError(
                t("{name}: the start value must be within its bounds.", name=item["name"])
            )
    if spec.get("method") not in METHODS:
        raise OptimizationError(t("The method is one of {methods}.", methods=", ".join(METHODS)))
    objective = spec.get("objective") or {}
    if objective.get("statistic") not in STATISTICS or objective.get("goal") not in GOALS:
        raise OptimizationError(t("Say what the optimization minimizes, maximizes or targets."))
    if objective["goal"] == "target" and objective.get("target") is None:
        raise OptimizationError(t("Give the value the objective should reach."))
    constraints = spec.get("constraints") or []
    if len(constraints) > MAX_CONSTRAINTS:
        raise OptimizationError(t("At most {n} constraints.", n=MAX_CONSTRAINTS))
    for item in constraints:
        if item.get("statistic") not in STATISTICS or item.get("op") not in OPERATORS:
            raise OptimizationError(t("{name}: not a constraint.", name=item.get("variable")))
    if constraints and spec["method"] == "nelder-mead":
        raise OptimizationError(t("Nelder-Mead takes no constraints: use COBYLA or SLSQP."))
    if int(spec.get("max_simulations") or 0) < 2:
        raise OptimizationError(t("Allow at least 2 simulations."))


def variables_measured(spec: dict[str, Any]) -> list[str]:
    """The variables whose indicators the optimization reads."""

    names = [spec["objective"]["variable"]]
    names += [item["variable"] for item in spec.get("constraints") or []]
    return list(dict.fromkeys(names))


def _indicator(found: dict[str, Any] | None, variable: str, statistic: str) -> float | None:
    value = ((found or {}).get(variable) or {}).get(statistic)
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None


def _tolerance(value: float) -> float:
    return 1e-6 * max(1.0, abs(value))


def run(
    spec: dict[str, Any],
    evaluate: Callable[[dict[str, float]], dict[str, Any]],
    *,
    on_step: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Optimize: ``evaluate`` simulates the model with the given values and answers the
    simulation's ``run_id`` and ``indicators`` (``None`` when it failed); it may raise ``Stop``. Answers the state:
    every evaluation, the best point, why it ended."""

    check(spec)
    variables = spec["variables"]
    names = [item["name"] for item in variables]
    low = np.array([float(item["min"]) for item in variables])
    high = np.array([float(item["max"]) for item in variables])
    start = (np.array([float(item["start"]) for item in variables]) - low) / (high - low)
    objective = spec["objective"]
    constraints = spec.get("constraints") or []
    budget = int(spec["max_simulations"])
    method = spec["method"]
    state: dict[str, Any] = {"evaluations": [], "best": None, "status": "running", "message": ""}
    cache: dict[tuple[float, ...], dict[str, Any]] = {}

    def values_of(z: np.ndarray) -> dict[str, float]:
        x = low + np.clip(z, 0.0, 1.0) * (high - low)
        return {name: float(f"{value:.10g}") for name, value in zip(names, x, strict=True)}

    def measure(z: np.ndarray) -> dict[str, Any]:
        values = values_of(z)
        key = tuple(values.values())
        if key in cache:
            return cache[key]
        if len(cache) >= budget:
            raise _Budget
        simulated = evaluate(values)
        found = simulated.get("indicators")
        value = _indicator(found, objective["variable"], objective["statistic"])
        margins = []
        for item in constraints:
            measured = _indicator(found, item["variable"], item["statistic"])
            limit = float(item["value"])
            margins.append(
                None
                if measured is None
                else (limit - measured if item["op"] == "<=" else measured - limit)
            )
        if value is None:
            cost = PENALTY
        elif objective["goal"] == "minimize":
            cost = value
        elif objective["goal"] == "maximize":
            cost = -value
        else:
            cost = (value - float(objective["target"])) ** 2
        feasible = value is not None and all(
            margin is not None and margin >= -_tolerance(float(item["value"]))
            for margin, item in zip(margins, constraints, strict=True)
        )
        entry = {
            "index": len(state["evaluations"]) + 1,
            "run_id": simulated.get("run_id", ""),
            "values": values,
            "objective": value,
            "cost": cost,
            "constraints": margins,
            "feasible": feasible,
            "failed": found is None,
        }
        cache[key] = entry
        state["evaluations"].append(entry)
        state["best"] = _best(state["evaluations"])
        if on_step:
            on_step(state)
        return entry

    def cost(z: np.ndarray) -> float:
        return float(measure(z)["cost"])

    def margin(index: int) -> Callable[[np.ndarray], float]:
        def answer(z: np.ndarray) -> float:
            found = measure(z)["constraints"][index]
            return -PENALTY if found is None else float(found)

        return answer

    bounds = sp.Bounds(np.zeros(len(names)), np.ones(len(names)))
    try:
        first = measure(start)
        scale = abs(first["cost"]) if first["cost"] != PENALTY else 1.0
        if method == "nelder-mead":
            simplex = [start]
            for index in range(len(names)):
                corner = start.copy()
                step = FIRST_STEP if corner[index] + FIRST_STEP <= 1 else -FIRST_STEP
                corner[index] += step
                simplex.append(corner)
            answer = sp.minimize(
                cost,
                start,
                method="Nelder-Mead",
                bounds=bounds,
                options={
                    "initial_simplex": np.array(simplex),
                    "maxfev": budget,
                    "xatol": 1e-3,
                    "fatol": 1e-6 * max(1.0, scale),
                },
            )
        elif method == "cobyla":
            answer = sp.minimize(
                cost,
                start,
                method="COBYLA",
                bounds=bounds,
                constraints=[
                    {"type": "ineq", "fun": margin(index)} for index in range(len(constraints))
                ],
                options={"rhobeg": FIRST_STEP, "tol": 1e-3, "maxiter": budget},
            )
        else:
            answer = sp.minimize(
                cost,
                start,
                method="SLSQP",
                bounds=bounds,
                constraints=[
                    {"type": "ineq", "fun": margin(index)} for index in range(len(constraints))
                ],
                options={"maxiter": budget, "ftol": 1e-6 * max(1.0, scale), "eps": 1e-2},
            )
        state["status"] = "done"
        if len(cache) >= budget and not answer.success:
            raise _Budget
        state["message"] = (
            t("Converged: the best values change no more.")
            if answer.success
            else str(answer.message)
        )
        state["converged"] = bool(answer.success)
    except _Budget:
        state["status"] = "done"
        state["message"] = t("Reached the most simulations allowed ({n}).", n=budget)
        state["converged"] = False
    except Stop:
        state["status"] = "stopped"
        state["message"] = t("Cancelled.")
        state["converged"] = False
    state["best"] = _best(state["evaluations"])
    if state["best"] is None and state["status"] == "done":
        state["status"] = "failed"
        state["message"] = t("No simulation gave the objective a value.")
    return state


def _best(evaluations: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The best evaluation: the lowest cost among those that meet every constraint, else (none
    does) the one closest to meeting them."""

    measured = [item for item in evaluations if item["objective"] is not None]
    feasible = [item for item in measured if item["feasible"]]
    if feasible:
        return min(feasible, key=lambda item: item["cost"])
    if not measured:
        return None

    def violation(item: dict[str, Any]) -> float:
        return sum(
            PENALTY if margin is None else max(0.0, -margin) for margin in item["constraints"]
        )

    return min(measured, key=lambda item: (violation(item), item["cost"]))
