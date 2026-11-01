"""Request dependencies: the runtime, the verified user, access checks and safe reads.

Every route needs a PlantCraft token with access to ``pidcraft``
(``plantcraft_sdk.server.access``). Viewers read the drawings and the map; editors send and
remove drawings, review the map and ask the model to read a scan again.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, HTTPException
from plantcraft_sdk.server.access import Access, CurrentUser, runtime

from pidcraft.api.runtime import Runtime
from pidcraft.i18n import t

ACCESS = Access("PID")
RuntimeDep = Annotated[Runtime, Depends(runtime)]
EditorUser = ACCESS.EditorUser
guarded = ACCESS.guarded

__all__ = ["CurrentUser", "EditorUser", "RuntimeDep", "guarded"]


def drawing_or_404(rt: Runtime, drawing_id: str) -> dict[str, Any]:
    found = rt.drawings.get(drawing_id)
    if found is None:
        raise HTTPException(status_code=404, detail=t("Drawing not found."))
    return found
