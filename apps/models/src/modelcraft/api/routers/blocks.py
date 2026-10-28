"""Blocks: the libraries of Modelica classes every project may use, sorted into groups.

A block library is edited like a project (its files and the workbench) but belongs to none:
its classes travel with every check, diagram and simulation of every project.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from modelcraft.api.deps import CurrentUser, EditorUser, RuntimeDep, project_or_404
from modelcraft.api.routers.projects import _identifier
from modelcraft.i18n import t
from modelcraft.projects.models import MAX_GROUP, ProjectError
from modelcraft.runs.service import project_classes

router = APIRouter(prefix="/api", tags=["blocks"])


class LibraryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    group: str = Field(default="", max_length=MAX_GROUP)
    description: str = Field(default="", max_length=2000)


class LibraryChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    group: str | None = Field(default=None, max_length=MAX_GROUP)
    description: str | None = Field(default=None, max_length=2000)


def library_or_404(rt, library_id: str) -> dict[str, Any]:
    found = project_or_404(rt, library_id)
    if found.get("kind") != "library":
        raise HTTPException(404, t("Block library not found."))
    return found


def _library(rt, item: dict[str, Any]) -> dict[str, Any]:
    files = rt.projects.files(item["id"])
    packages = sorted({path.split("/")[0].removesuffix(".mo") for path in files})
    blocks = [
        {key: cls[key] for key in ("name", "short", "restriction", "comment", "partial", "file")}
        for cls in project_classes(files)
        if cls["restriction"] not in ("package",) and not cls["partial"]
    ]
    return {**item, "group": item.get("block_group", ""), "packages": packages, "blocks": blocks}


@router.get("/blocks")
def list_blocks(rt: RuntimeDep, _user: CurrentUser) -> list[dict[str, Any]]:
    """Every block library with its blocks, by group and name."""

    libraries = [_library(rt, item) for item in rt.projects.list("library")]
    return sorted(libraries, key=lambda item: (item["group"].lower(), item["name"].lower()))


@router.post("/blocks", status_code=201)
def create_library(body: LibraryBody, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    ident = _identifier(body.name)[:60]
    taken = {path.split("/")[0].removesuffix(".mo") for path in rt.projects.library_files()}
    if ident in taken:
        raise HTTPException(409, t("A block library already has the package {name}.", name=ident))
    files = {
        f"{ident}/package.mo": f'within;\npackage {ident} "{body.name}"\nend {ident};\n',
    }
    try:
        library = rt.projects.create(
            body.name,
            by=user.username,
            description=body.description,
            files=files,
            kind="library",
            group=body.group,
        )
    except ProjectError as exc:
        raise HTTPException(422, str(exc)) from exc
    rt.audit(user, "library.created", f"project:{library['id']}", {"name": library["name"]})
    return _library(rt, library)


@router.patch("/blocks/{library_id}")
def change_library(
    library_id: str, body: LibraryChange, rt: RuntimeDep, user: EditorUser
) -> dict[str, Any]:
    library_or_404(rt, library_id)
    try:
        library = rt.projects.update(
            library_id,
            by=user.username,
            name=body.name,
            description=body.description,
            group=body.group,
        )
    except ProjectError as exc:
        raise HTTPException(422, str(exc)) from exc
    rt.audit(user, "library.changed", f"project:{library_id}", {"name": library["name"]})
    return _library(rt, library)
