"""HTTP routes: Models' models and runs for notebooks (``[[contributes.objects]]``).

PlantCraft forwards a notebook's ``pc.app("models").list("model")`` here with the person's
identity (``plantcraft_sdk.server.objects``, format ``plantcraft-objects/1``). A model is read
with its settings, its ports and parameters; a run with its state and, once a simulation is done,
its results. ``model.run(...)`` from a notebook queues a simulation in Models' own queue, as the
page's Simulate does, only when an administrator switched on "Simulations from notebooks" (Setup ›
Apps, off by default: owner, 2026-10-26, D4) and only for an editor of Models.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from plantcraft_sdk.app_manifest import parse_manifest
from plantcraft_sdk.server.objects import AppObjects, notebooks_router, object_item
from pydantic import ValidationError

from modelcraft.api.deps import seen_runs
from modelcraft.api.routers.model import _workbench_error
from modelcraft.api.routers.models import _model, list_models
from modelcraft.api.routers.runs import SimulateBody, with_progress
from modelcraft.i18n import t
from modelcraft.meta import FILES
from modelcraft.modelica import blockdiagram
from modelcraft.modelica.edit import EditError
from modelcraft.notebook_examples import EXAMPLES
from modelcraft.omc import results
from modelcraft.runs.service import WorkbenchError

objects = AppObjects()
SWITCH = "notebook_runs"
# A finished simulation's results in one read: the variables a notebook plots, thinned.
MAX_VARIABLES = 60
MAX_POINTS = 2000
# What a notebook may set for one simulation (the page's Simulate form, without plant data).
RUN_OPTIONS = {"start", "stop", "intervals", "tolerance", "method", "overrides", "label"}


def _split(model_id: str) -> tuple[str, str]:
    project_id, _, model = model_id.partition("/")
    if not project_id or not model:
        raise HTTPException(404, t("Model not found."))
    return project_id, model


@objects.lister("model")
def models(user: Any, rt: Any) -> list[dict[str, Any]]:
    return [
        object_item(
            f"{item['project_id']}/{item['model']}",
            item["name"],
            project=item["project"],
            model=item["model"],
            description=item.get("description") or "",
            example=bool(item.get("example")),
            updated_at=item.get("updated_at"),
        )
        for item in list_models(rt, user)
    ]


@objects.getter("model")
def model(_user: Any, rt: Any, model_id: str) -> dict[str, Any] | None:
    project_id, name = _split(model_id)
    try:
        found = _model(rt, project_id, name)
    except HTTPException:
        return None
    found.pop("diagram", None)
    return {"id": model_id, **found}


@objects.lister("run")
def runs(user: Any, rt: Any) -> list[dict[str, Any]]:
    return [
        object_item(
            run["id"],
            run.get("label") or run["model"],
            model=f"{run['project_id']}/{run['model']}",
            kind_of_run=run["kind"],
            status=run["status"],
            created_at=run.get("created_at"),
            finished_at=run.get("finished_at"),
            by=run.get("created_by"),
        )
        for run in seen_runs(rt, user, rt.runs.list(limit=200))
    ]


@objects.getter("run")
def run(user: Any, rt: Any, run_id: str) -> dict[str, Any] | None:
    found = rt.runs.get(run_id)
    if found is None or not seen_runs(rt, user, [found]):
        return None
    item = {**with_progress(rt, found, light=True), "name": found.get("label") or found["model"]}
    if found["kind"] == "simulate" and found["status"] == "done":
        folder = rt.workbench.run_dir(run_id)
        names = [
            variable["name"]
            for variable in results.variables(folder)
            if variable.get("kind") != "parameter"
        ][:MAX_VARIABLES]
        read = results.series(folder, names, max_points=MAX_POINTS)
        # One time axis per variable (each thinned on its own): a notebook makes a table of it.
        item["results"] = {
            serie["name"]: {"time": serie["time"], "values": serie["values"]}
            for serie in read["series"]
        }
    return {"id": run_id, **item}


def _allowed(rt: Any) -> bool:
    return rt.suite.setting(SWITCH) is True


@objects.runner("model")
def simulate(user: Any, rt: Any, model_id: str, options: dict[str, Any]) -> dict[str, Any]:
    if not _allowed(rt):
        raise HTTPException(
            403,
            t(
                "Simulations from notebooks are off. An administrator switches them on in "
                "PlantCraft › Setup › Apps › Models."
            ),
        )
    if not user.can_edit:
        raise HTTPException(403, t("Your access to Models is read-only."))
    project_id, name = _split(model_id)
    current = _model(rt, project_id, name)
    unknown = sorted(set(options) - RUN_OPTIONS)
    if unknown:
        raise HTTPException(422, t("Unknown options: {names}.", names=", ".join(unknown)))
    try:
        defaults = blockdiagram.run_options(current["settings"])
        body = SimulateBody(model=name, **{**defaults, **options})
    except (EditError, ValidationError) as exc:
        raise HTTPException(422, str(exc)[:500]) from exc
    if body.stop <= body.start:
        raise HTTPException(422, t("The stop time must come after the start time."))
    chosen = body.model_dump(exclude={"model", "label", "plant"})
    try:
        started = rt.workbench.start(
            project_id,
            name,
            "simulate",
            chosen,
            by=user.username,
            label=body.label or t("From a notebook"),
        )
    except WorkbenchError as exc:
        raise _workbench_error(exc) from exc
    rt.audit(
        user,
        "run.started",
        f"project:{project_id}",
        {"run": started["id"], "model": name, "from": "notebook"},
    )
    return {"kind": "run", "id": started["id"]}


router = objects.router()


def notebooks() -> Any:
    """Models' examples (``[contributes.notebooks]`` of its ``app.toml``)."""

    data = FILES.manifest()
    return notebooks_router(EXAMPLES, parse_manifest(data) if data else None)
