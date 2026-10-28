"""HTTP routes: Models' part of the suite's search (Ctrl+K, PlantCraft's docs/app-standard.md
section 10): its models and its studies, each ``href`` a page here (a model's diagram, a study's
comparison, a model's single runs in Executions)."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Query
from plantcraft_sdk.server.search import SearchItem, matches, search_answer, search_text

from modelcraft.api.deps import CurrentUser, RuntimeDep, sees_study
from modelcraft.i18n import t
from modelcraft.runs.service import project_classes

router = APIRouter()


@router.get("/api/search")
def search(
    rt: RuntimeDep,
    user: CurrentUser,
    q: str = Query("", max_length=120),
    limit: int = Query(6, ge=1, le=20),
) -> dict[str, Any]:
    text = search_text(q)
    if not text:
        return search_answer([])
    scope = rt.asset_scope(user)
    models = []
    for project in rt.projects.list():
        models += [
            SearchItem(
                item["short"],
                f"/models/{quote(project['id'], safe='')}/{quote(item['name'], safe='')}",
                type=t("Model"),
                detail=" · ".join(part for part in (item.get("comment"), item["name"]) if part),
            )
            for item in project_classes(rt.projects.files(project["id"]))
            if item["restriction"] == "model"
            and item["simulable"]
            and matches(text, item["name"], item.get("comment"))
        ]
    studies = [
        SearchItem(
            study["name"],
            f"/{'executions' if study.get('kind') == 'quick' else 'studies'}/"
            f"{quote(study['id'], safe='')}",
            type=t("Study"),
            detail=" · ".join(
                part for part in (study.get("model"), study.get("project_name")) if part
            ),
        )
        for study in rt.runs.studies()
        if sees_study(scope, study)
        if matches(text, study["name"], study.get("model"), study.get("description"))
    ]
    return search_answer(models + studies, text, limit=limit)
