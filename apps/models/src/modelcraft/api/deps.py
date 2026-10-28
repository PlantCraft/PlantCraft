"""Request dependencies: the runtime, the verified user, access checks and safe reads.

Every route needs a PlantCraft token with access to ``modelcraft``
(``plantcraft_sdk.server.access``). Viewers open projects, read models, diagrams and run results;
editors change projects, check, simulate and export FMUs (compiling a model runs code, so it is
never a viewer's right).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, HTTPException
from plantcraft_sdk.asset_scope import AssetScope
from plantcraft_sdk.server.access import Access, CurrentUser, runtime

from modelcraft.api.runtime import Runtime
from modelcraft.i18n import t

ACCESS = Access("Models")
RuntimeDep = Annotated[Runtime, Depends(runtime)]
EditorUser = ACCESS.EditorUser
guarded = ACCESS.guarded

__all__ = ["CurrentUser", "EditorUser", "RuntimeDep", "guarded"]


def project_or_404(rt: Runtime, project_id: str) -> dict[str, Any]:
    found = rt.projects.get(project_id) if len(project_id) <= 64 else None
    if found is None:
        raise HTTPException(status_code=404, detail=t("Project not found."))
    return found


def plant_signals(run: dict[str, Any]) -> list[str]:
    """The plant's signals a simulation was fed with or compared to (``options.plant``)."""

    plant = (run.get("options") or {}).get("plant") or {}
    found = list((plant.get("inputs") or {}).values()) + list((plant.get("compare") or {}).values())
    return [str(item) for item in found if item]


def sees_run(scope: AssetScope, run: dict[str, Any]) -> bool:
    """A run is seen by who sees every plant signal it read (PlantCraft's docs/asset-scope.md);
    a run on no plant data by everyone."""

    return scope.everything or scope.all_signals(plant_signals(run))


def sees_study(scope: AssetScope, study: dict[str, Any]) -> bool:
    return sees_run(scope, {"options": (study.get("spec") or {}).get("options")})


def seen_runs(rt: Runtime, user: Any, runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scope = rt.asset_scope(user)
    return runs if scope.everything else [run for run in runs if sees_run(scope, run)]


def run_or_404(rt: Runtime, run_id: str, user: Any = None) -> dict[str, Any]:
    """The run; with ``user``, only one on plant data they see."""

    found = rt.runs.get(run_id) if len(run_id) <= 40 else None
    if found is not None and user is not None and not sees_run(rt.asset_scope(user), found):
        found = None
    if found is None:
        raise HTTPException(status_code=404, detail=t("Simulation not found."))
    return found
