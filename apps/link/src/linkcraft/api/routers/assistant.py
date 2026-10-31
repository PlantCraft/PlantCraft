"""The assistant beside Analytics' objects (``AssistantButton`` of ``@plantcraft/ui``).

Before the panel opens, the page asks Analytics to write what it knows about the object to
PlantCraft (``linkcraft.knowledge``): an algorithm's documentation, a run's report. The
conversation itself happens in PlantCraft (API v1 ``/assistant``), with the person's token.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from linkcraft.api.deps import CurrentUser, RuntimeDep

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class PreparePayload(BaseModel):
    ref: str = Field(min_length=3, max_length=400)


@router.post("/prepare")
def prepare(payload: PreparePayload, _user: CurrentUser, rt: RuntimeDep) -> dict[str, Any]:
    """Publish the text about ``ref`` (an algorithm or a run of Analytics); others are left alone."""

    return {"ref": payload.ref, "published": rt.publish_explanation(payload.ref)}
