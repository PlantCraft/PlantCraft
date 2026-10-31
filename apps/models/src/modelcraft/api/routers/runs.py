"""Simulations and FMU exports: start one, follow it, plot its results, download them.

A simulation may take its inputs from the plant: each top-level input of the model is fed by
a signal's history over a period (read through PlantCraft, with the person's own token), and
variables may be compared with the signals they model. The model's time 0 is the period's
start.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response
from plantcraft_sdk.server.queue import queue_answer
from pydantic import BaseModel, ConfigDict, Field, field_validator

from modelcraft.api.deps import (
    CurrentUser,
    EditorUser,
    RuntimeDep,
    guarded,
    project_or_404,
    run_or_404,
    seen_runs,
)
from modelcraft.api.routers.model import CLASS, _workbench_error
from modelcraft.i18n import t
from modelcraft.omc import results
from modelcraft.omc.runner import METHODS, OVERRIDE_NAME
from modelcraft.runs.plant import PlantError, read_plant
from modelcraft.runs.plant import utc as _utc
from modelcraft.runs.service import WorkbenchError

router = APIRouter(prefix="/api", tags=["runs"])


class ComputeBody(BaseModel):
    """Where a run goes on the suite's compute workers (docs/compute.md, "Environments and
    sizes"): a worker with this environment and room for this size."""

    model_config = ConfigDict(extra="forbid")

    environment: str = Field(default="standard", pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")
    size: Literal["small", "medium", "large"] = "small"

    def options(self) -> dict[str, str] | None:
        """The run's ``compute`` option; none for the default (any worker of the suite)."""

        return None if (self.environment, self.size) == ("standard", "small") else self.model_dump()


class PlantBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: datetime
    end: datetime
    step: float | None = Field(default=None, ge=1, le=86_400)
    inputs: dict[str, str] = Field(default_factory=dict, max_length=50)
    compare: dict[str, str] = Field(default_factory=dict, max_length=20)

    @field_validator("inputs", "compare")
    @classmethod
    def _names(cls, value: dict[str, str]) -> dict[str, str]:
        for name, signal in value.items():
            if not OVERRIDE_NAME.match(name) or not signal or len(signal) > 300:
                raise ValueError(f"not a variable and a signal: {name[:60]}")
        return value


class SimulateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1, max_length=400, pattern=CLASS)
    start: float = Field(default=0, ge=-1e12, le=1e12)
    stop: float = Field(default=1, ge=-1e12, le=1e12)
    intervals: int = Field(default=500, ge=1, le=200_000)
    tolerance: float = Field(default=1e-6, gt=0, le=0.1)
    method: str = Field(default="dassl")
    overrides: dict[str, float | bool] = Field(default_factory=dict, max_length=500)
    label: str = Field(default="", max_length=120)
    plant: PlantBody | None = None
    compute: ComputeBody | None = None

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


class FmuBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1, max_length=400, pattern=CLASS)
    version: Literal["2.0", "3.0"] = "2.0"
    type: Literal["cs", "me", "me_cs"] = "cs"
    label: str = Field(default="", max_length=120)


class LabelBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(max_length=120)


class SeriesBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    names: list[str] = Field(min_length=1, max_length=40)
    max_points: int = Field(default=2000, ge=10, le=20_000)


def with_progress(rt, run: dict[str, Any], *, light: bool = False) -> dict[str, Any]:
    """The run with how far it is (running simulations); ``light`` leaves out its messages."""

    item = {**run, "progress": rt.workbench.progress(run)}
    if light:
        item.pop("messages", None)
        item["result"] = {
            key: value
            for key, value in (run.get("result") or {}).items()
            if key in ("indicators", "variables", "rows", "start", "stop")
        }
    return item


def _plant(rt, user, plant: PlantBody) -> tuple[dict[str, bytes], dict[str, Any], float]:
    """(the inputs CSV for omc, the comparison series, the period's length in seconds), read
    with the person's own token."""

    client = rt.user_client(user)
    try:
        return read_plant(
            lambda *args: guarded(lambda: client.series_many(*args), service=False),
            plant.start,
            plant.end,
            plant.step,
            plant.inputs,
            plant.compare,
        )
    except PlantError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/projects/{project_id}/simulate", status_code=201)
def simulate(
    project_id: str, body: SimulateBody, rt: RuntimeDep, user: EditorUser
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
    try:
        run = rt.workbench.start(
            project_id,
            body.model,
            "simulate",
            options,
            by=user.username,
            label=body.label,
            extra=extra,
            compare=compare,
        )
    except WorkbenchError as exc:
        raise _workbench_error(exc) from exc
    rt.audit(user, "run.started", f"project:{project_id}", {"run": run["id"], "model": body.model})
    return run


@router.post("/projects/{project_id}/fmu", status_code=201)
def export_fmu(project_id: str, body: FmuBody, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    project_or_404(rt, project_id)
    try:
        run = rt.workbench.start(
            project_id,
            body.model,
            "fmu",
            {"version": body.version, "type": body.type},
            by=user.username,
            label=body.label,
        )
    except WorkbenchError as exc:
        raise _workbench_error(exc) from exc
    rt.audit(user, "fmu.started", f"project:{project_id}", {"run": run["id"], "model": body.model})
    return run


@router.get("/runs")
def list_runs(
    rt: RuntimeDep,
    user: CurrentUser,
    project: str | None = Query(default=None, max_length=64),
    model: str | None = Query(default=None, max_length=400),
    kind: Literal["simulate", "fmu"] | None = None,
    study: str | None = Query(default=None, max_length=40),
    status: Literal["queued", "running", "done", "failed", "cancelled"] | None = None,
    limit: int = Query(default=200, ge=1, le=5000),
) -> list[dict[str, Any]]:
    runs = rt.runs.list(
        project_id=project,
        model=model,
        kind=kind,
        study_id=study,
        statuses=(status,) if status else None,
        limit=limit,
    )
    runs = seen_runs(rt, user, runs)
    return with_studies(rt, [with_progress(rt, run, light=True) for run in runs])


def with_studies(rt, runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each run with the name and kind of its study."""

    names = rt.runs.study_names({run.get("study_id") or "" for run in runs})
    return [{**run, "study": names.get(run.get("study_id") or "")} for run in runs]


@router.get("/compute/offer")
def compute_offer(rt: RuntimeDep, _user: CurrentUser) -> dict[str, Any]:
    """The environments and sizes the suite's compute workers offer now (for "Where it runs")."""

    state = rt.workbench.runner()
    return {
        "suite": "environments" in state,
        "environments": state.get("environments") or [],
        "sizes": state.get("sizes") or [],
        "workers": state.get("workers") or 0,
    }


@router.get("/queue")
def queue_numbers(
    rt: RuntimeDep,
    _user: CurrentUser,
    window: str = Query(default="24h", pattern="^(1h|24h|7d|30d)$"),
) -> dict[str, Any]:
    """The queue's numbers now and over the window, for the suite's queue panel."""

    return queue_answer(rt.queue_now(), rt.queue_metrics, window)


@router.get("/queue/runs")
def queue(rt: RuntimeDep, _user: CurrentUser) -> dict[str, Any]:
    """The simulation queue now: what runs, what waits (the first 100), the workers."""

    running = rt.runs.list(statuses=("running",), limit=200)
    waiting = rt.runs.list(statuses=("queued",), limit=5000)
    waiting.sort(key=lambda run: (-int(run.get("priority") or 0), run["created_at"]))
    return {
        **rt.workbench.queue_state(),
        # Counted from the same reads as the lists, so the numbers and the rows agree.
        "running": len(running),
        "queued": len(waiting),
        "running_runs": with_studies(rt, [with_progress(rt, run, light=True) for run in running]),
        "queued_runs": with_studies(
            rt, [with_progress(rt, run, light=True) for run in waiting[:100]]
        ),
    }


@router.get("/runs/{run_id}")
def get_run(run_id: str, rt: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    run = run_or_404(rt, run_id, user)
    study = rt.runs.study(run.get("study_id") or "")
    return {
        **with_progress(rt, run),
        "study": {"id": study["id"], "name": study["name"], "kind": study["kind"]}
        if study
        else None,
    }


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    run = run_or_404(rt, run_id, user)
    if run["status"] not in ("queued", "running"):
        raise HTTPException(409, t("The simulation is already finished."))
    rt.workbench.cancel(run_id)
    rt.audit(user, "run.cancelled", f"project:{run['project_id']}", {"run": run_id})
    return run_or_404(rt, run_id, user)


@router.patch("/runs/{run_id}")
def label_run(run_id: str, body: LabelBody, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    run_or_404(rt, run_id, user)
    return rt.runs.set_label(run_id, body.label.strip())  # type: ignore[return-value]


@router.delete("/runs/{run_id}", status_code=204)
def delete_run(run_id: str, rt: RuntimeDep, user: EditorUser) -> None:
    run = run_or_404(rt, run_id, user)
    if run["status"] in ("queued", "running"):
        raise HTTPException(409, t("The simulation is not finished yet."))
    rt.workbench.delete_run(run_id)
    rt.audit(user, "run.deleted", f"project:{run['project_id']}", {"run": run_id})


def _finished_simulation(rt, run_id: str, user: Any) -> dict[str, Any]:
    run = run_or_404(rt, run_id, user)
    if run["kind"] != "simulate":
        raise HTTPException(404, t("This is an FMU export: it has no results to plot."))
    if run["status"] != "done":
        raise HTTPException(409, t("The simulation has no results yet."))
    return run


@router.get("/runs/{run_id}/variables")
def run_variables(run_id: str, rt: RuntimeDep, user: CurrentUser) -> list[dict[str, Any]]:
    _finished_simulation(rt, run_id, user)
    return results.variables(rt.workbench.run_dir(run_id))


@router.post("/runs/{run_id}/series")
def run_series(run_id: str, body: SeriesBody, rt: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    _finished_simulation(rt, run_id, user)
    answer = results.series(rt.workbench.run_dir(run_id), body.names, max_points=body.max_points)
    compare = rt.workbench.compare(run_id)
    answer["compare"] = [{"name": name, **compare[name]} for name in body.names if name in compare]
    return answer


@router.get("/runs/{run_id}/results.csv")
def run_csv(run_id: str, rt: RuntimeDep, user: CurrentUser) -> Response:
    run = _finished_simulation(rt, run_id, user)
    text = results.csv_text(rt.workbench.run_dir(run_id))
    name = run["model"].rpartition(".")[2]
    return Response(
        text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}-{run_id}.csv"'},
    )


@router.get("/runs/{run_id}/fmu")
def run_fmu(run_id: str, rt: RuntimeDep, user: CurrentUser) -> FileResponse:
    run = run_or_404(rt, run_id, user)
    path = rt.workbench.fmu_path(run)
    if path is None:
        raise HTTPException(404, t("This simulation has no FMU."))
    return FileResponse(path, media_type="application/octet-stream", filename=path.name)


@router.get("/runs/{run_id}/files")
def run_files(run_id: str, rt: RuntimeDep, user: CurrentUser) -> dict[str, str]:
    """The project's files as they were when the run started."""

    run_or_404(rt, run_id, user)
    return rt.workbench.run_files(run_id)
