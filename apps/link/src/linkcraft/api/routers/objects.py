"""HTTP routes: Link's blocks and algorithms for notebooks (``[[contributes.objects]]``).

PlantCraft forwards a notebook's ``pc.app("link").list("block")`` here with the person's identity
(``plantcraft_sdk.server.objects``, format ``plantcraft-objects/1``). A block or an algorithm is
read whole, with what the notebook needs to run it on the person's computer (``linkcraft.notebook``):
a site block's file with its code, an algorithm's diagram and timing. Reads only.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from plantcraft_sdk.app_manifest import parse_manifest
from plantcraft_sdk.blocks import describe_block
from plantcraft_sdk.server.objects import AppObjects, notebooks_router, object_item

from linkcraft.api.routers.blocks import _meta, _resolve, _site_meta
from linkcraft.api.routers.catalog import _algorithm, _groups, _uses
from linkcraft.blocks import CATALOG, catalog_items
from linkcraft.blocks.files import split_pinned
from linkcraft.catalog.loop_types import algorithm_id as current_id
from linkcraft.config import app_manifest
from linkcraft.notebook_examples import EXAMPLES

objects = AppObjects()
# What runs only inside Link: the blocks of a model (an FMU runs in Link's model runtime).
LINK_ONLY = ("model.",)


def _runs_here(block_id: str) -> bool:
    return not block_id.startswith(LINK_ONLY)


@objects.lister("block")
def blocks(_user: Any, rt: Any) -> list[dict[str, Any]]:
    sites = _site_meta(rt)
    found = []
    for item in catalog_items():
        meta = _meta(item["block_id"], sites)
        found.append(
            object_item(
                item["block_id"],
                item["name"],
                library=item["library"],
                group=item["group"] or None,
                summary=item["summary"],
                inputs=", ".join(port["port"] for port in item["inputs"]),
                outputs=", ".join(port["port"] for port in item["outputs"]),
                site=meta["site"],
                runs_here=_runs_here(item["block_id"]),
            )
        )
    return found


@objects.getter("block")
def block(_user: Any, rt: Any, block_id: str) -> dict[str, Any] | None:
    resolved = _resolve(block_id)
    found = CATALOG.get(resolved)
    if found is None or resolved.startswith("draft."):
        return None
    meta = _meta(resolved, _site_meta(rt))
    item = {**describe_block(found.spec), **meta, "runs_here": _runs_here(resolved)}
    item.pop("parameter_schema", None)
    pinned = split_pinned(resolved)
    if pinned and rt.blocks.get(pinned[0]):
        file = rt.blocks.file(pinned[0], pinned[1])
        if file is not None:
            # A block written on the site runs its own code on the person's computer.
            item["file"] = file.model_dump(mode="json")
    return {"id": block_id, **item}


@objects.lister("algorithm")
def algorithms(_user: Any, rt: Any) -> list[dict[str, Any]]:
    return [
        object_item(
            profile["profile_id"],
            profile["name"],
            description=profile.get("description") or "",
            version=int(profile.get("version") or 1),
            system=bool(profile.get("system")),
        )
        for profile in rt.presets.list_profiles()
    ]


@objects.getter("algorithm")
def algorithm(user: Any, rt: Any, algorithm_id: str) -> dict[str, Any] | None:
    profile = rt.presets.get_profile(current_id(algorithm_id))
    if profile is None:
        return None
    try:
        found = _algorithm(
            profile,
            user=user,
            groups=_groups(rt, user),
            used=_uses(rt).get(profile["profile_id"], 0),
        )
    except HTTPException:
        return None
    return {"id": algorithm_id, **found, "name": found["name"]}


router = objects.router()


def notebooks() -> Any:
    """Link's examples and its runtime (``[contributes.notebooks]`` of its ``app.toml``)."""

    data = app_manifest()
    return notebooks_router(EXAMPLES, parse_manifest(data) if data else None)
