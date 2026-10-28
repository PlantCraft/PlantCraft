"""Folders for the site's models, blocks and studies (round 9, M5), as Link's.

The platform's routes (``plantcraft_sdk.server.folders.folders_router``): ``GET
/api/folders/<kind>`` lists the kind's folders and where each object sits; editors make, rename
and delete (empty) folders, and ``PUT /api/folders/<kind>/items/<id>`` moves one object (``""``
takes it out), recording who moved it and when. A model is ``<project>/<class>``; a block its
class name, only in the site's own libraries (the shipped ones stay as they are); a study its id
(the single runs of a model are not a study and stay out).
"""

from __future__ import annotations

from typing import Any

from plantcraft_sdk.server.folders import folders_router

from modelcraft.api.deps import EditorUser
from modelcraft.api.routers.models import catalog
from modelcraft.api.runtime import FOLDER_KINDS as KINDS
from modelcraft.runs.service import project_classes


def _exists(rt: Any, kind: str, item_id: str) -> bool:
    if kind == "model":
        project_id, _, model = item_id.partition("/")
        project = rt.projects.get(project_id)
        if project is None or project.get("kind", "project") != "project":
            return False
        return any(
            item["name"] == model and item["restriction"] == "model"
            for item in project_classes(rt.projects.files(project_id))
        )
    if kind == "block":
        block = catalog(rt).get(item_id)
        library = rt.projects.get(block["library"]) if block else None
        return library is not None and not library["example"]
    study = rt.runs.study(item_id)
    return study is not None and study.get("kind") != "quick"


def forget_project(rt: Any, project_id: str) -> None:
    """A deleted project's models (or a deleted library's blocks) leave their folders."""

    for item_id in rt.folders.items("model"):
        if item_id.startswith(f"{project_id}/"):
            rt.folders.forget("model", item_id)
    for block_id, block in catalog(rt).items():
        if block["library"] == project_id:
            rt.folders.forget("block", block_id)


router = folders_router(KINDS, editor=EditorUser, exists=_exists)

__all__ = ["KINDS", "forget_project", "router"]
