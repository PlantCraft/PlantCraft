"""Prompts for an AI assistant ("Copy as prompt", PlantCraft ``docs/design/copy-prompt.md``).

A Modelica class's prompt carries its text, the classes of the same project it names (extends,
components, functions), the project's outline and what this server's runner refuses, so the
answer is Modelica the person can paste back into the editor as it is. Each answer is
``plantcraft_sdk.prompts.Prompt.render()``: the text the interface copies.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from plantcraft_sdk.prompts import Prompt, code_part, json_part, question_of

from modelcraft.api.deps import CurrentUser, RuntimeDep, project_or_404
from modelcraft.api.routers.model import CLASS
from modelcraft.i18n import t
from modelcraft.modelica.source import find
from modelcraft.runs.service import project_classes

router = APIRouter(prefix="/api/prompts", tags=["prompts"])

# Classes of the project the prompt carries besides the one asked about.
MAX_USED = 8
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")


def _questions() -> dict[str, str]:
    return {
        "explain": t(
            "Explain this model: what it represents, its equations, its parameters with their "
            "units, and what its results show."
        ),
        "extend": t(
            "Extend this model with what I describe after this prompt. Answer with the whole "
            "class in Modelica, ready to replace the current one, and an experiment annotation "
            "that shows the change."
        ),
        "review": t(
            "Review this model: unbalanced equations, missing units, parameters without a "
            "sensible range, and connectors used the wrong way. Answer with the corrected class."
        ),
    }


def _class_text(files: dict[str, str], name: str) -> tuple[str, str] | None:
    """The file holding class ``name`` and the class's own text."""

    for path, text in files.items():
        found = find(text, name)
        if found is not None:
            return path, text[found.start : found.end]
    return None


@router.get("/class")
def class_prompt(
    rt: RuntimeDep,
    _user: CurrentUser,
    project_id: str = Query(min_length=1, max_length=64),
    name: str = Query(min_length=1, max_length=400, pattern=CLASS),
    question: str | None = Query(default=None, max_length=40),
) -> dict[str, Any]:
    project = project_or_404(rt, project_id)
    files = rt.projects.files(project_id)
    found = _class_text(files, name)
    if found is None:
        raise HTTPException(status_code=404, detail=t("Class not found."))
    path, source = found
    classes = project_classes(files)
    words = set(_WORD.findall(source))
    used = [
        item
        for item in classes
        if item["name"] != name
        and not name.startswith(f"{item['name']}.")
        and (item["name"] in words or item["short"] in words)
    ][:MAX_USED]
    parts = [code_part(t("Class {name} ({file})", name=name, file=path), source, "modelica")]
    for item in used:
        other = _class_text(files, item["name"])
        if other is not None:
            parts.append(
                code_part(
                    t("Used class {name} ({file})", name=item["name"], file=other[0]),
                    other[1],
                    "modelica",
                )
            )
    outline = [
        {key: item[key] for key in ("name", "restriction", "comment", "file") if item.get(key)}
        for item in classes
    ]
    parts.append(json_part(t("Classes of the project"), outline))
    notes = [
        t(
            "Write standard Modelica 3.6 that OpenModelica compiles, with the Modelica Standard "
            "Library only."
        ),
        t(
            "Keep the class name ({name}) and give every parameter a unit and a description.",
            name=name,
        ),
        t("Files and system commands (Modelica.Utilities.System, Files) are not available here."),
    ]
    if not rt.settings.allow_external:
        notes.append(t("External functions (C code) are turned off on this server."))
    prompt = Prompt(
        module="Models",
        title=t("Model: {name}", name=name),
        subject=t(
            "a Modelica class of the project {project}, simulated by the suite's Modelica "
            "runner (OpenModelica)",
            project=project.get("name") or project_id,
        ),
        question=question_of(_questions(), question, "explain"),
        parts=parts,
        notes=notes,
    )
    return prompt.render()
