"""The workbench: check a model, its diagram and the diagram's edits, the library browser and
the Modelica runner's state."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from modelcraft.api.deps import CurrentUser, EditorUser, RuntimeDep, project_or_404
from modelcraft.i18n import t
from modelcraft.modelica import edit
from modelcraft.projects.models import Conflict, ProjectError
from modelcraft.runs.service import PolicyError, RunnerDown, WorkbenchError

router = APIRouter(prefix="/api", tags=["model"])
CLASS = r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$"


class CheckBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1, max_length=400, pattern=CLASS)


Point = tuple[float, float]


class EditBody(BaseModel):
    """One diagram edit, made on the text of the file that holds the class."""

    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1, max_length=400, pattern=CLASS)
    file: str = Field(min_length=1, max_length=400)
    base_updated_at: str | None = Field(default=None, max_length=64)
    op: Literal["add", "move", "delete", "connect", "disconnect", "modifiers"]
    type: str | None = Field(default=None, max_length=400, pattern=CLASS)
    name: str | None = Field(default=None, max_length=80)
    extent: tuple[Point, Point] | None = None
    rotation: float = Field(default=0, ge=-360, le=360)
    origin: Point | None = None
    left: str | None = Field(default=None, max_length=200)
    right: str | None = Field(default=None, max_length=200)
    points: list[Point] | None = Field(default=None, max_length=200)
    values: dict[str, str | None] | None = Field(default=None, max_length=100)


def _workbench_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PolicyError):
        return HTTPException(422, {"message": str(exc), "messages": exc.problems})
    return HTTPException(503 if isinstance(exc, RunnerDown) else 422, str(exc))


@router.get("/runner")
def runner_state(rt: RuntimeDep, _user: CurrentUser) -> dict[str, Any]:
    return {
        **rt.workbench.runner(),
        "library": rt.workbench.library_state(),
        "allow_external": rt.settings.allow_external,
    }


@router.post("/projects/{project_id}/check")
def check(project_id: str, body: CheckBody, rt: RuntimeDep, _user: EditorUser) -> dict[str, Any]:
    project_or_404(rt, project_id)
    try:
        return rt.workbench.check(project_id, body.model)
    except WorkbenchError as exc:
        raise _workbench_error(exc) from exc


@router.get("/projects/{project_id}/diagram")
def diagram(
    project_id: str,
    rt: RuntimeDep,
    _user: EditorUser,
    model: str = Query(min_length=1, max_length=400, pattern=CLASS),
) -> dict[str, Any]:
    """Drawing a diagram asks omc to instantiate the class (it runs the runner): editors only."""

    project_or_404(rt, project_id)
    try:
        return rt.workbench.diagram(project_id, model)
    except WorkbenchError as exc:
        raise _workbench_error(exc) from exc


@router.post("/projects/{project_id}/edit")
def diagram_edit(
    project_id: str, body: EditBody, rt: RuntimeDep, user: EditorUser
) -> dict[str, Any]:
    project_or_404(rt, project_id)
    current = rt.projects.file(project_id, body.file)
    if current is None:
        raise HTTPException(404, t("File not found."))
    if body.base_updated_at and body.base_updated_at != current["updated_at"]:
        raise HTTPException(
            409, t("{path} was changed since the diagram was drawn: draw it again.", path=body.file)
        )
    text = current["content"]
    try:
        if body.op == "add":
            if not body.type or not body.extent:
                raise edit.EditError(t("Adding a component needs its class and where it goes."))
            name = body.name or edit.unique_name(text, body.model, body.type.rpartition(".")[2])
            text = edit.add_component(
                text, body.model, body.type, name, [list(p) for p in body.extent], body.rotation
            )
        elif body.op == "move":
            if not body.name or not body.extent:
                raise edit.EditError(t("Moving a component needs its name and its new place."))
            text = edit.move(
                text,
                body.model,
                body.name,
                [list(p) for p in body.extent],
                body.rotation,
                list(body.origin) if body.origin else None,
            )
        elif body.op == "delete":
            text = edit.delete_component(text, body.model, body.name or "")
        elif body.op == "connect":
            text = edit.connect(
                text,
                body.model,
                body.left or "",
                body.right or "",
                [list(p) for p in body.points or []],
            )
        elif body.op == "disconnect":
            text = edit.delete_connection(text, body.model, body.left or "", body.right or "")
        else:
            text = edit.set_modifiers(text, body.model, body.name or "", body.values or {})
    except edit.EditError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        return rt.projects.save_file(
            project_id, body.file, text, by=user.username, base_updated_at=current["updated_at"]
        )
    except Conflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ProjectError as exc:
        raise HTTPException(422, str(exc)) from exc


def _library_or_503(rt) -> Any:
    index = rt.workbench.library()
    if index is None:
        rt.workbench.ensure_library()
        state = rt.workbench.library_state()
        raise HTTPException(
            503,
            state["error"]
            or t("The library is being read by the Modelica runner; it is ready in a minute."),
        )
    return index


@router.get("/library")
def library(
    rt: RuntimeDep,
    _user: CurrentUser,
    parent: str = Query(default="", max_length=400),
    q: str = Query(default="", max_length=120),
    all_parts: bool = False,
) -> dict[str, Any]:
    index = _library_or_503(rt)
    if q.strip():
        return {"parent": "", "classes": index.search(q, limit=100)}
    if parent and parent not in index:
        raise HTTPException(404, t("Class not found."))
    return {"parent": parent, "classes": index.list(parent, all_parts=all_parts)}


@router.get("/library/names")
def library_names(
    rt: RuntimeDep, _user: CurrentUser, prefix: str = Query(default="Modelica.", max_length=400)
) -> list[str]:
    """Class names for the editor's completion."""

    return _library_or_503(rt).names(prefix, limit=4000)


@router.get("/library/class")
def library_class(
    rt: RuntimeDep,
    _user: EditorUser,
    name: str = Query(min_length=1, max_length=400, pattern=CLASS),
) -> dict[str, Any]:
    """A library class: its icon, diagram, parameters, documentation and source text."""

    index = _library_or_503(rt)
    entry = index.get(name)
    if entry is None:
        raise HTTPException(404, t("Class not found."))
    try:
        found = rt.workbench.diagram(None, name, source=True)
    except WorkbenchError as exc:
        raise _workbench_error(exc) from exc
    return {**found, **entry}
