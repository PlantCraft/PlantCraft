"""Folders for the site's blocks, algorithms and schedules (owner D14, 2026-10-26).

The platform's routes (``plantcraft_sdk.server.folders.folders_router``): ``GET
/api/folders/<kind>`` lists the kind's folders and where each object sits; editors make, rename
and delete (empty) folders, and ``PUT /api/folders/<kind>/items/<id>`` moves one object (``""``
takes it out), recording who moved it. Executions follow their schedule's folder.
"""

from __future__ import annotations

from typing import Any

from plantcraft_sdk.server.folders import folders_router

from linkcraft.api.deps import EditorUser
from linkcraft.catalog.folders import KINDS


def _exists(rt: Any, kind: str, item_id: str) -> bool:
    if kind == "block":
        # Only the site's own blocks: the libraries Link ships are fixed.
        return rt.blocks.get(item_id) is not None
    if kind == "algorithm":
        return rt.presets.get_profile(item_id) is not None
    return rt.jobs.get_schedule(item_id) is not None


router = folders_router(KINDS, editor=EditorUser, exists=_exists)

__all__ = ["KINDS", "router"]
