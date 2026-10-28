"""Studies: a model simulated once or over a sweep of parameter values, followed in the queue,
compared and exported (CSV and a Jupyter notebook)."""

from __future__ import annotations

import math
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from modelcraft.api.deps import CurrentUser, EditorUser, RuntimeDep, project_or_404, sees_study
from modelcraft.api.routers.model import CLASS, _workbench_error
from modelcraft.api.routers.runs import ComputeBody, PlantBody, _plant, _utc, with_progress
from modelcraft.i18n import t
from modelcraft.omc import results
from modelcraft.omc.runner import METHODS, OVERRIDE_NAME, SETTINGS
from modelcraft.runs import optimize, studies
from modelcraft.runs.models import STATUSES
from modelcraft.runs.service import WorkbenchError

router = APIRouter(prefix="/api", tags=["studies"])
MAX_SWEPT = 10
MAX_INDICATORS = 20


class SweepItem(BaseModel):
    """One varied parameter, input or simulation setting (``@tolerance``, ``@method``,
    ``@stop``, ``@intervals``): a range (from, to, how many values) or a list of values."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    mode: Literal["range", "list"]
    start: float | None = None
    stop: float | None = None
    count: int | None = Field(default=None, ge=1, le=studies.MAX_VALUES_PER_PARAMETER)
    values: list[float | bool | str] | None = Field(
        default=None, max_length=studies.MAX_VALUES_PER_PARAMETER
    )

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if value not in SETTINGS and not OVERRIDE_NAME.match(value):
            raise ValueError(f"not a parameter name: {value[:60]}")
        return value

    @model_validator(mode="after")
    def _complete(self) -> SweepItem:
        if self.name == "@method":
            if self.mode != "list" or not self.values:
                raise ValueError("@method: a list of integrators")
            if any(value not in METHODS for value in self.values):
                raise ValueError(f"@method: one of {', '.join(METHODS)}")
            return self
        if self.mode == "range":
            if self.start is None or self.stop is None or self.count is None:
                raise ValueError(f"{self.name}: a range needs from, to and how many values")
            if not (math.isfinite(self.start) and math.isfinite(self.stop)):
                raise ValueError(f"{self.name}: not a finite number")
            numbers = [self.start, self.stop]
        elif not self.values:
            raise ValueError(f"{self.name}: the list has no values")
        elif any(
            isinstance(v, str) or not isinstance(v, bool) and not math.isfinite(v)
            for v in self.values
        ):
            raise ValueError(f"{self.name}: not a finite number")
        else:
            numbers = [float(v) for v in self.values]
        if self.name == "@tolerance" and any(not 0 < v <= 0.1 for v in numbers):
            raise ValueError("@tolerance: between 0 and 0.1")
        if self.name == "@intervals" and any(not 1 <= v <= 200_000 for v in numbers):
            raise ValueError("@intervals: from 1 to 200000")
        return self


class InputShape(BaseModel):
    """How a study drives one of the model's inputs (round 9 M6). Its value is the study's
    fixed or swept one; a step goes from ``before`` to it at ``at``, a ramp from ``at`` to
    ``end``."""

    model_config = ConfigDict(extra="forbid")

    shape: Literal["constant", "step", "ramp"] = "constant"
    value: float | None = None
    before: float | None = None
    at: float | None = Field(default=None, ge=-1e12, le=1e12)
    end: float | None = Field(default=None, ge=-1e12, le=1e12)

    @model_validator(mode="after")
    def _complete(self) -> InputShape:
        for number in (self.value, self.before, self.at, self.end):
            if number is not None and not math.isfinite(number):
                raise ValueError("not a finite number")
        if self.shape != "constant" and (self.before is None or self.at is None):
            raise ValueError("a step or a ramp needs the value before and when it starts")
        if self.shape == "ramp" and (self.end is None or self.end <= (self.at or 0)):
            raise ValueError("a ramp ends after it starts")
        return self


class DecisionVariable(BaseModel):
    """A parameter or an input the optimization changes, from ``start`` within its bounds."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    start: float
    min: float
    max: float

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not OVERRIDE_NAME.match(value):
            raise ValueError(f"not a parameter name: {value[:60]}")
        return value

    @model_validator(mode="after")
    def _bounds(self) -> DecisionVariable:
        if not all(math.isfinite(v) for v in (self.start, self.min, self.max)):
            raise ValueError(f"{self.name}: not a finite number")
        if not self.min < self.max:
            raise ValueError(f"{self.name}: the smallest value must be below the largest")
        if not self.min <= self.start <= self.max:
            raise ValueError(f"{self.name}: the start value must be within its bounds")
        return self


class Objective(BaseModel):
    """What the optimization makes best: an indicator of a variable (``tank.level``, ``iae``)."""

    model_config = ConfigDict(extra="forbid")

    variable: str = Field(min_length=1, max_length=400)
    statistic: Literal[studies.STATISTICS] = "final"  # type: ignore[valid-type]
    goal: Literal[optimize.GOALS] = "minimize"  # type: ignore[valid-type]
    target: float | None = None

    @field_validator("variable")
    @classmethod
    def _variable(cls, value: str) -> str:
        if not OVERRIDE_NAME.match(value):
            raise ValueError(f"not a variable name: {value[:60]}")
        return value

    @model_validator(mode="after")
    def _target(self) -> Objective:
        if self.goal == "target" and (self.target is None or not math.isfinite(self.target)):
            raise ValueError("give the value the objective should reach")
        return self


class Constraint(BaseModel):
    """An indicator kept below or above a value (``tank.level`` ``max`` ``<=`` 2.5)."""

    model_config = ConfigDict(extra="forbid")

    variable: str = Field(min_length=1, max_length=400)
    statistic: Literal[studies.STATISTICS] = "max"  # type: ignore[valid-type]
    op: Literal[optimize.OPERATORS] = "<="  # type: ignore[valid-type]
    value: float

    @field_validator("variable")
    @classmethod
    def _variable(cls, value: str) -> str:
        if not OVERRIDE_NAME.match(value):
            raise ValueError(f"not a variable name: {value[:60]}")
        return value

    @field_validator("value")
    @classmethod
    def _value(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("not a finite number")
        return value


class OptimizationBody(BaseModel):
    """An optimization study (``runs/optimize.py``): the values it changes, what it makes best,
    the constraints, the method and the most simulations it may run."""

    model_config = ConfigDict(extra="forbid")

    variables: list[DecisionVariable] = Field(min_length=1, max_length=optimize.MAX_VARIABLES)
    objective: Objective
    constraints: list[Constraint] = Field(default_factory=list, max_length=optimize.MAX_CONSTRAINTS)
    method: Literal[optimize.METHODS] | None = None  # type: ignore[valid-type]
    max_simulations: int = Field(default=60, ge=2, le=5000)

    @model_validator(mode="after")
    def _method(self) -> OptimizationBody:
        # Nelder-Mead unless there are constraints, then COBYLA (both without derivatives).
        if self.method is None:
            self.method = "cobyla" if self.constraints else "nelder-mead"
        if self.constraints and self.method == "nelder-mead":
            raise ValueError("Nelder-Mead takes no constraints: use COBYLA or SLSQP")
        return self


class StudyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1, max_length=400, pattern=CLASS)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    start: float = Field(default=0, ge=-1e12, le=1e12)
    stop: float = Field(default=1, ge=-1e12, le=1e12)
    intervals: int = Field(default=500, ge=1, le=200_000)
    tolerance: float = Field(default=1e-6, gt=0, le=0.1)
    method: str = Field(default="dassl")
    overrides: dict[str, float | bool] = Field(default_factory=dict, max_length=500)
    sweep: list[SweepItem] = Field(default_factory=list, max_length=MAX_SWEPT)
    indicators: list[str] = Field(default_factory=list, max_length=MAX_INDICATORS)
    inputs: dict[str, InputShape] = Field(default_factory=dict, max_length=50)
    time_limit: float | None = Field(default=None, ge=10)
    plant: PlantBody | None = None
    optimization: OptimizationBody | None = None
    compute: ComputeBody | None = None

    @field_validator("inputs")
    @classmethod
    def _inputs(cls, value: dict[str, InputShape]) -> dict[str, InputShape]:
        for name in value:
            if not OVERRIDE_NAME.match(name):
                raise ValueError(f"not an input name: {name[:60]}")
        return value

    @field_validator("method")
    @classmethod
    def _method(cls, value: str) -> str:
        if value not in METHODS:
            raise ValueError(f"one of {', '.join(METHODS)}")
        return value

    @field_validator("overrides")
    @classmethod
    def _overrides(cls, value: dict[str, float | bool]) -> dict[str, float | bool]:
        for name, number in value.items():
            if not OVERRIDE_NAME.match(name):
                raise ValueError(f"not a parameter name: {name[:60]}")
            if not isinstance(number, bool) and not math.isfinite(number):
                raise ValueError(f"not a finite number: {name[:60]}")
        return value

    @field_validator("indicators")
    @classmethod
    def _indicators(cls, value: list[str]) -> list[str]:
        for name in value:
            if not OVERRIDE_NAME.match(name):
                raise ValueError(f"not a variable name: {name[:60]}")
        return list(dict.fromkeys(value))


class PreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1, max_length=400, pattern=CLASS)
    sweep: list[SweepItem] = Field(default_factory=list, max_length=MAX_SWEPT)


class StudyChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class StudySeriesBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=400)
    runs: list[str] | None = Field(default=None, max_length=500)
    max_points: int = Field(default=1000, ge=10, le=5000)
    envelope: bool = True


def study_or_404(rt, study_id: str, user: Any = None) -> dict[str, Any]:
    """The study; with ``user``, only one on plant data they see."""

    found = rt.runs.study(study_id)
    if found is not None and user is not None and not sees_study(rt.asset_scope(user), found):
        found = None
    if found is None:
        raise HTTPException(404, t("Study not found."))
    return found


def _estimate(rt, model: str, count: int) -> dict[str, Any]:
    """Seconds per simulation from this model's last finished simulations, and the total with
    the queue's workers."""

    done = [
        run["seconds"]
        for run in rt.runs.list(model=model, kind="simulate", statuses=("done",), limit=20)
        if run.get("seconds")
    ]
    each = sum(done) / len(done) if done else None
    workers = rt.workbench.queue.workers
    return {
        "seconds_each": each,
        "seconds_total": each * count / workers if each is not None else None,
    }


@router.get("/studies")
def list_studies(
    rt: RuntimeDep,
    user: CurrentUser,
    project: str | None = Query(default=None, max_length=64),
    model: str | None = Query(default=None, max_length=400),
) -> list[dict[str, Any]]:
    scope = rt.asset_scope(user)
    return [
        study
        for study in rt.runs.studies(project_id=project, model=model)
        if sees_study(scope, study)
    ]


@router.post("/projects/{project_id}/studies/preview")
def preview_study(
    project_id: str, body: PreviewBody, rt: RuntimeDep, _user: CurrentUser
) -> dict[str, Any]:
    project_or_404(rt, project_id)
    try:
        count = studies.count([item.model_dump() for item in body.sweep])
    except studies.StudyError as exc:
        raise HTTPException(422, str(exc)) from exc
    limit = rt.settings.study_max_runs
    return {
        "count": count,
        "limit": limit,
        "warn_above": min(100, limit),
        **_estimate(rt, body.model, count),
    }


@router.post("/projects/{project_id}/studies", status_code=201)
def create_study(
    project_id: str, body: StudyBody, rt: RuntimeDep, user: EditorUser
) -> dict[str, Any]:
    project_or_404(rt, project_id)
    options: dict[str, Any] = {
        "start": body.start,
        "stop": body.stop,
        "intervals": body.intervals,
        "tolerance": body.tolerance,
        "method": body.method,
        "overrides": body.overrides,
    }
    if body.time_limit:
        options["time_limit"] = min(body.time_limit, rt.settings.max_run_seconds)
    extra: dict[str, bytes] = {}
    compare: dict[str, Any] = {}
    if body.plant is not None:
        extra, compare, duration = _plant(rt, user, body.plant)
        options.update(start=0.0, stop=duration)
        options["plant"] = {
            "start": _utc(body.plant.start).isoformat(),
            "end": _utc(body.plant.end).isoformat(),
            "inputs": body.plant.inputs,
            "compare": body.plant.compare,
        }
    if body.compute is not None and body.compute.options():
        options["compute"] = body.compute.options()
    if options["stop"] <= options["start"]:
        raise HTTPException(422, t("The stop time must come after the start time."))
    if body.inputs:
        options["inputs"] = _inputs(body, options)
    for item in body.sweep:
        if item.name == "@stop" and min(_numbers(item)) <= options["start"]:
            raise HTTPException(422, t("The stop time must come after the start time."))
    spec = {
        "options": options,
        "sweep": [item.model_dump(exclude_none=True) for item in body.sweep],
        "indicators": body.indicators,
    }
    if body.optimization is not None:
        return _create_optimization(rt, user, project_id, body, spec)
    try:
        study = rt.workbench.start_study(
            project_id,
            body.model,
            name=body.name.strip(),
            description=body.description,
            spec=spec,
            by=user.username,
            max_runs=rt.settings.study_max_runs,
            extra=extra,
            compare=compare,
        )
    except studies.StudyError as exc:
        raise HTTPException(422, str(exc)) from exc
    except WorkbenchError as exc:
        raise _workbench_error(exc) from exc
    rt.audit(
        user,
        "study.started",
        f"project:{project_id}",
        {"study": study["id"], "model": body.model, "name": study["name"]},
    )
    return {**study, **rt.runs.study_counts(study["id"])}


def _create_optimization(rt, user, project_id: str, body: StudyBody, spec: dict[str, Any]):
    """An optimization study: one simulation at a time, until the best values are found."""

    optimization = body.optimization
    assert optimization is not None
    if body.sweep:
        raise HTTPException(422, t("An optimization varies no other value: remove the sweep."))
    found = optimization.model_dump()
    # The optimized values are no longer fixed: the optimizer sets them in every simulation.
    for item in optimization.variables:
        spec["options"]["overrides"].pop(item.name, None)
    spec["optimization"] = found
    spec["indicators"] = list(
        dict.fromkeys([*optimize.variables_measured(found), *body.indicators])
    )[: MAX_INDICATORS + optimize.MAX_CONSTRAINTS + 1]
    try:
        study = rt.workbench.start_optimization(
            project_id,
            body.model,
            name=body.name.strip(),
            description=body.description,
            spec=spec,
            by=user.username,
            max_runs=rt.settings.study_max_runs,
        )
    except optimize.OptimizationError as exc:
        raise HTTPException(422, str(exc)) from exc
    except WorkbenchError as exc:
        raise _workbench_error(exc) from exc
    rt.audit(
        user,
        "study.started",
        f"project:{project_id}",
        {"study": study["id"], "model": body.model, "name": study["name"], "kind": "optimization"},
    )
    return {**study, **rt.runs.study_counts(study["id"])}


def _numbers(item: SweepItem) -> list[float]:
    if item.mode == "range":
        return [float(item.start or 0), float(item.stop or 0)]
    return [float(value) for value in item.values or [] if not isinstance(value, str)]


def _inputs(body: StudyBody, options: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The inputs the study drives, each with its fixed value (moved out of the parameters'
    overrides) unless it is swept."""

    if body.plant is not None:
        raise HTTPException(422, t("A study on plant data takes its inputs from the plant."))
    swept = {item.name for item in body.sweep}
    if body.optimization is not None:
        swept |= {item.name for item in body.optimization.variables}
    shapes: dict[str, dict[str, Any]] = {}
    for name, shape in body.inputs.items():
        found = shape.model_dump(exclude_none=True)
        if name in options["overrides"]:
            found["value"] = float(options["overrides"].pop(name))
        if "value" not in found and name not in swept:
            raise HTTPException(422, t("{name}: give the input a value.", name=name))
        shapes[name] = found
    return shapes


@router.get("/studies/{study_id}")
def get_study(study_id: str, rt: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    study = study_or_404(rt, study_id, user)
    runs = rt.runs.list(study_id=study_id, limit=5000)
    # Counted from the same read as the list, so the two always agree.
    counts = {status: 0 for status in STATUSES}
    for run in runs:
        counts[run["status"]] = counts.get(run["status"], 0) + 1
    if study["kind"] == "optimization":
        study = {**study, "optimization": rt.workbench.optimization(study_id)}
    return {
        **study,
        **counts,
        "total": len(runs),
        "runs": [with_progress(rt, run, light=True) for run in reversed(runs)],
    }


@router.patch("/studies/{study_id}")
def change_study(
    study_id: str, body: StudyChange, rt: RuntimeDep, user: EditorUser
) -> dict[str, Any]:
    study_or_404(rt, study_id, user)
    rt.runs.rename_study(study_id, body.name.strip(), body.description)
    return study_or_404(rt, study_id, user)


@router.post("/studies/{study_id}/cancel")
def cancel_study(study_id: str, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    study = study_or_404(rt, study_id, user)
    cancelled = rt.workbench.cancel_study(study_id)
    rt.audit(user, "study.cancelled", f"project:{study['project_id']}", {"study": study_id})
    return {"cancelled": cancelled}


@router.delete("/studies/{study_id}", status_code=204)
def delete_study(study_id: str, rt: RuntimeDep, user: EditorUser) -> None:
    study = study_or_404(rt, study_id, user)
    counts = rt.runs.study_counts(study_id)
    if counts["queued"] or counts["running"] or rt.workbench.optimizing(study_id):
        raise HTTPException(409, t("The study is still running: cancel it first."))
    rt.workbench.delete_study(study_id)
    rt.folders.forget("study", study_id)
    rt.audit(user, "study.deleted", f"project:{study['project_id']}", {"study": study_id})


@router.post("/studies/{study_id}/series")
def study_series(
    study_id: str, body: StudySeriesBody, rt: RuntimeDep, user: CurrentUser
) -> dict[str, Any]:
    """One variable of the study's finished simulations (or of those listed), and their
    envelope."""

    study_or_404(rt, study_id, user)
    runs = rt.runs.list(study_id=study_id, statuses=("done",), limit=5000)
    if body.runs is not None:
        wanted = set(body.runs)
        runs = [run for run in runs if run["id"] in wanted]
    runs = list(reversed(runs))
    per_run = max(50, min(body.max_points, 200_000 // max(1, len(runs))))
    found = []
    for run in runs:
        answer = results.series(rt.workbench.run_dir(run["id"]), [body.name], max_points=per_run)
        if answer["series"]:
            found.append(
                {
                    "run_id": run["id"],
                    "label": run.get("label") or run["id"],
                    "variant": run.get("variant") or {},
                    "time": answer["series"][0]["time"],
                    "values": answer["series"][0]["values"],
                }
            )
    envelope = (
        studies.envelope(rt.workbench.run_dir, runs, body.name, body.max_points)
        if body.envelope and len(runs) > 1
        else None
    )
    return {"name": body.name, "series": found, "envelope": envelope}


class IndicatorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=400)


@router.post("/studies/{study_id}/indicators")
def study_indicators(
    study_id: str, body: IndicatorBody, rt: RuntimeDep, user: CurrentUser
) -> dict[str, Any]:
    """The indicators of any variable of the study's finished simulations, computed now (the
    ones named when it started are kept with each run; round 9 M10)."""

    study_or_404(rt, study_id, user)
    if not OVERRIDE_NAME.match(body.name):
        raise HTTPException(422, t("Not a variable name: {name}", name=body.name[:60]))
    runs = rt.runs.list(study_id=study_id, statuses=("done",), limit=5000)
    found = {}
    for run in runs:
        kept = (run.get("result") or {}).get("indicators", {}).get(body.name)
        value = kept or studies.indicators(rt.workbench.run_dir(run["id"]), [body.name]).get(
            body.name
        )
        if value:
            found[run["id"]] = value
    return {"name": body.name, "runs": found}


@router.get("/studies/{study_id}/statistics")
def study_statistics(study_id: str, rt: RuntimeDep, user: CurrentUser) -> list[dict[str, Any]]:
    study_or_404(rt, study_id, user)
    return studies.statistics(rt.runs.list(study_id=study_id, limit=5000))


@router.get("/studies/{study_id}/export.zip")
def export_study(study_id: str, rt: RuntimeDep, user: CurrentUser) -> Response:
    study = study_or_404(rt, study_id, user)
    runs = list(reversed(rt.runs.list(study_id=study_id, limit=5000)))
    files = rt.workbench.run_files(runs[0]["id"]) if runs else {}
    data = studies.export_zip(study, runs, files, rt.workbench.run_dir)
    name = "".join(c if c.isalnum() or c in "-_" else "-" for c in study["name"])[:60] or study_id
    return Response(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}.zip"'},
    )
