"""Projects and their Modelica files: list, create, open, edit, rename, delete, history, import
and export."""

from __future__ import annotations

import io
import zipfile
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from modelcraft.api.deps import CurrentUser, EditorUser, RuntimeDep, project_or_404
from modelcraft.i18n import t
from modelcraft.projects.models import (
    MAX_FILE_BYTES,
    MAX_FILES,
    Conflict,
    ProjectError,
    ReadOnly,
    check_path,
)
from modelcraft.runs.service import project_classes

router = APIRouter(prefix="/api", tags=["projects"])
TEMPLATES = ("blank", "model", "package")


class ProjectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    template: str = Field(default="model", pattern="^(blank|model|package)$")


class ProjectChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class DuplicateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)


class FileBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=400)
    content: str = Field(default="", max_length=MAX_FILE_BYTES)


class SaveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(max_length=MAX_FILE_BYTES)
    base_updated_at: str | None = Field(default=None, max_length=64)
    version_name: str = Field(default="", max_length=120)
    version_note: str = Field(default="", max_length=2000)


class RenameBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=400)


class ImportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    files: dict[str, str] = Field(max_length=MAX_FILES)
    replace: bool = False


def _identifier(name: str) -> str:
    words = [word for word in "".join(c if c.isalnum() else " " for c in name).split() if word]
    ident = "".join(word[:1].upper() + word[1:] for word in words) or "Model"
    return ident if ident[0].isalpha() else f"M{ident}"


def template_files(template: str, name: str) -> dict[str, str]:
    ident = _identifier(name)[:60]
    if template == "blank":
        return {}
    if template == "package":
        return {
            f"{ident}/package.mo": f'within;\npackage {ident} "{name}"\nend {ident};\n',
            f"{ident}/Model.mo": (
                f'within {ident};\nmodel Model "A first model"\n'
                '  parameter Real tau(unit = "s") = 10 "Time constant";\n'
                "  Real x(start = 0, fixed = true);\nequation\n  tau * der(x) = 1 - x;\n"
                "  annotation(experiment(StartTime = 0, StopTime = 60, Interval = 0.1));\nend Model;\n"
            ),
        }
    return {
        f"{ident}.mo": (
            f'model {ident} "{name}"\n'
            '  parameter Real tau(unit = "s") = 10 "Time constant";\n'
            "  Real x(start = 0, fixed = true);\nequation\n  tau * der(x) = 1 - x;\n"
            f"  annotation(experiment(StartTime = 0, StopTime = 60, Interval = 0.1));\nend {ident};\n"
        )
    }


def _refused(exc: ProjectError) -> HTTPException:
    status = 409 if isinstance(exc, Conflict) else 403 if isinstance(exc, ReadOnly) else 422
    return HTTPException(status_code=status, detail=str(exc))


@router.get("/projects")
def list_projects(rt: RuntimeDep, _user: CurrentUser) -> list[dict[str, Any]]:
    """The projects, each with how many models, studies, simulations and FMU exports it has."""

    counts = rt.runs.project_counts()
    found = []
    for project in rt.projects.list():
        models = sum(
            1 for item in project_classes(rt.projects.files(project["id"])) if item["simulable"]
        )
        found.append({**project, "models": models, **counts.get(project["id"], {})})
    return found


@router.post("/projects", status_code=201)
def create_project(body: ProjectBody, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    try:
        project = rt.projects.create(
            body.name,
            by=user.username,
            description=body.description,
            files=template_files(body.template, body.name),
        )
    except ProjectError as exc:
        raise _refused(exc) from exc
    rt.audit(user, "project.created", f"project:{project['id']}", {"name": project["name"]})
    return project


@router.get("/projects/{project_id}")
def get_project(project_id: str, rt: RuntimeDep, _user: CurrentUser) -> dict[str, Any]:
    project = project_or_404(rt, project_id)
    return {**project, "classes": project_classes(rt.projects.files(project_id))}


@router.patch("/projects/{project_id}")
def change_project(
    project_id: str, body: ProjectChange, rt: RuntimeDep, user: EditorUser
) -> dict[str, Any]:
    project_or_404(rt, project_id)
    try:
        project = rt.projects.update(
            project_id, by=user.username, name=body.name, description=body.description
        )
    except ProjectError as exc:
        raise _refused(exc) from exc
    rt.audit(user, "project.changed", f"project:{project_id}", {"name": project["name"]})
    return project


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str, rt: RuntimeDep, user: EditorUser) -> None:
    project = project_or_404(rt, project_id)
    if project["example"]:
        raise _refused(ReadOnly(t("Examples stay: duplicate one to change it.")))
    if any(
        run["status"] in ("queued", "running")
        for run in rt.runs.list(project_id=project_id, limit=5000)
    ):
        raise HTTPException(
            409, t("Simulations of this project are still running: cancel them first.")
        )
    from modelcraft.api.routers.folders import forget_project  # folders reads the catalog

    for study in rt.runs.studies(project_id=project_id):
        rt.workbench.delete_study(study["id"])
        rt.folders.forget("study", study["id"])
    for run in rt.runs.list(project_id=project_id, limit=5000):
        rt.workbench.delete_run(run["id"])
    forget_project(rt, project_id)
    rt.projects.delete(project_id, by=user.username)
    rt.audit(user, "project.deleted", f"project:{project_id}", {"name": project["name"]})


@router.post("/projects/{project_id}/duplicate", status_code=201)
def duplicate_project(
    project_id: str, body: DuplicateBody, rt: RuntimeDep, user: EditorUser
) -> dict[str, Any]:
    project_or_404(rt, project_id)
    try:
        project = rt.projects.duplicate(project_id, body.name, by=user.username)
    except ProjectError as exc:
        raise _refused(exc) from exc
    rt.audit(
        user,
        "project.created",
        f"project:{project['id']}",
        {"name": project["name"], "from": project_id},
    )
    return project


@router.get("/projects/{project_id}/classes")
def classes(project_id: str, rt: RuntimeDep, _user: CurrentUser) -> list[dict[str, Any]]:
    project_or_404(rt, project_id)
    return project_classes(rt.projects.files(project_id))


@router.post("/projects/{project_id}/files", status_code=201)
def create_file(
    project_id: str, body: FileBody, rt: RuntimeDep, user: EditorUser
) -> dict[str, Any]:
    project_or_404(rt, project_id)
    try:
        saved = rt.projects.save_file(
            project_id, body.path, body.content, by=user.username, create=True
        )
    except ProjectError as exc:
        raise _refused(exc) from exc
    rt.audit(user, "file.created", f"project:{project_id}", {"path": saved["path"]})
    return saved


@router.get("/projects/{project_id}/files/{path:path}/revisions")
def file_revisions(
    project_id: str, path: str, rt: RuntimeDep, _user: CurrentUser
) -> list[dict[str, Any]]:
    project_or_404(rt, project_id)
    return rt.projects.revisions(project_id, path)


@router.get("/projects/{project_id}/revisions/{revision_id}")
def file_revision(
    project_id: str, revision_id: int, rt: RuntimeDep, _user: CurrentUser
) -> dict[str, Any]:
    project_or_404(rt, project_id)
    found = rt.projects.revision(project_id, revision_id) if 0 < revision_id < 2**62 else None
    if found is None:
        raise HTTPException(404, t("Version not found."))
    return found


@router.post("/projects/{project_id}/files/{path:path}/rename")
def rename_file(
    project_id: str, path: str, body: RenameBody, rt: RuntimeDep, user: EditorUser
) -> dict[str, Any]:
    project_or_404(rt, project_id)
    try:
        saved = rt.projects.rename_file(project_id, path, body.path, by=user.username)
    except ProjectError as exc:
        raise _refused(exc) from exc
    except KeyError as exc:
        raise HTTPException(404, t("File not found.")) from exc
    rt.audit(user, "file.renamed", f"project:{project_id}", {"path": path, "to": saved["path"]})
    return saved


@router.get("/projects/{project_id}/files/{path:path}")
def get_file(project_id: str, path: str, rt: RuntimeDep, _user: CurrentUser) -> dict[str, Any]:
    project_or_404(rt, project_id)
    found = rt.projects.file(project_id, path) if len(path) <= 400 else None
    if found is None:
        raise HTTPException(404, t("File not found."))
    return found


@router.put("/projects/{project_id}/files/{path:path}")
def save_file(
    project_id: str, path: str, body: SaveBody, rt: RuntimeDep, user: EditorUser
) -> dict[str, Any]:
    project_or_404(rt, project_id)
    if rt.projects.file(project_id, path) is None:
        raise HTTPException(404, t("File not found."))
    try:
        return rt.projects.save_file(
            project_id,
            path,
            body.content,
            by=user.username,
            base_updated_at=body.base_updated_at,
            version_name=body.version_name,
            version_note=body.version_note,
        )
    except ProjectError as exc:
        raise _refused(exc) from exc


@router.delete("/projects/{project_id}/files/{path:path}", status_code=204)
def delete_file(project_id: str, path: str, rt: RuntimeDep, user: EditorUser) -> None:
    project_or_404(rt, project_id)
    try:
        rt.projects.delete_file(project_id, path, by=user.username)
    except ProjectError as exc:
        raise _refused(exc) from exc
    except KeyError as exc:
        raise HTTPException(404, t("File not found.")) from exc
    rt.audit(user, "file.deleted", f"project:{project_id}", {"path": path})


@router.post("/projects/{project_id}/import")
def import_files(
    project_id: str, body: ImportBody, rt: RuntimeDep, user: EditorUser
) -> dict[str, Any]:
    """Add Modelica files (read by the browser from the person's computer)."""

    project_or_404(rt, project_id)
    try:
        paths = {check_path(path): text for path, text in body.files.items()}
    except ProjectError as exc:
        raise _refused(exc) from exc
    existing = rt.projects.files(project_id)
    clashes = sorted(set(paths) & set(existing))
    if clashes and not body.replace:
        raise HTTPException(
            409, t("These files already exist: {paths}", paths=", ".join(clashes[:10]))
        )
    saved = []
    try:
        for path, text in paths.items():
            rt.projects.save_file(
                project_id, path, text, by=user.username, create=path not in existing
            )
            saved.append(path)
    except ProjectError as exc:
        raise _refused(exc) from exc
    rt.audit(user, "file.imported", f"project:{project_id}", {"paths": saved[:50]})
    return {"saved": saved}


@router.get("/projects/{project_id}/export")
def export_project(project_id: str, rt: RuntimeDep, _user: CurrentUser) -> Response:
    """The project's files as a zip, as they are laid out in a Modelica library folder."""

    project = project_or_404(rt, project_id)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, text in rt.projects.files(project_id).items():
            archive.writestr(path, text)
    name = (
        "".join(c if c.isalnum() or c in "-_" else "-" for c in project["name"]).strip("-")
        or "project"
    )
    return Response(
        buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}.zip"'},
    )
