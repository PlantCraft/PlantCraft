"""HTTP routes: API v1's notebooks, for the Notebooks kit on a person's computer (docs/api-v1.md).

The kit (``plantcraft_notebook.kit``) reads them with the person's access token when it opens and
on ``pc.sync()``: the examples, and the notebooks PlantCraft wrote for that person ("Open in a
notebook"), the same two folders the browser's JupyterLab shows. Read-only, and only while
Notebooks is on; ``kit_version`` is the kits' version on this server, so the kit can say when a
newer one is here, and ``token_expires_at`` when the token it reads with ends.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from processcraft.api import notebook_examples as examples
from processcraft.api.deps import Runtime
from processcraft.api.identity import V1Reader
from processcraft.i18n import t
from processcraft.notebooks import EXAMPLES_FOLDER, FOLDER, kits

router = APIRouter(prefix="/api/v1")


def _person(caller: Any) -> str:
    if caller.app_id:
        raise HTTPException(status_code=403, detail=t("Notebooks belong to people, not apps."))
    return caller.username


def _on(rt: Any) -> None:
    if not rt.workspace.notebooks.enabled():
        raise HTTPException(status_code=404, detail=t("Notebooks are off."))


@router.get("/notebooks")
def notebooks(caller: V1Reader, rt: Runtime) -> dict[str, Any]:
    """The examples and the person's notebooks: names and paths for ``/notebooks/file``."""

    _on(rt)
    user = _person(caller)
    listing = kits.catalog()
    return {
        # One folder per app (Examples/PlantCraft, Examples/Analytics), as in the browser.
        "examples": [
            {"name": item["name"], "path": item["path"], "app": item["app"]}
            for item in examples.listing(rt, user)
        ],
        "mine": [
            {"name": item["name"], "path": item["path"], "created_at": item["created_at"]}
            for item in rt.workspace.notebooks.list(user)
        ],
        "kit_version": listing["version"] if listing else None,
        # When the person's access token ends (None for a session): the kit says so a week before.
        "token_expires_at": caller.claims.get("token_expires_at"),
    }


@router.get("/notebooks/file")
def notebook_file(
    caller: V1Reader, rt: Runtime, path: str = Query(min_length=3, max_length=300)
) -> dict[str, Any]:
    """One notebook (``.ipynb`` JSON) by its path: ``Examples/<app>/<name>`` or
    ``My notebooks/<name>``."""

    _on(rt)
    user = _person(caller)
    folder, _, name = path.partition("/")
    if folder == EXAMPLES_FOLDER:
        item = examples.find(rt, user, path)
        found = examples.notebook(rt, user, item) if item else None
        if found is not None:
            return found
    elif folder == FOLDER:
        mine = rt.workspace.notebooks.get(user, name, content=True)
        if mine is not None:
            return mine["content"]
    raise HTTPException(status_code=404, detail=t("Not found."))
