"""What a person did with an inbox entry or a suggestion on Desk: done, read, or snoozed until a
day."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import Request
from pydantic import BaseModel, Field

from plantcraft.api.deps import CurrentUser, Runtime, marks_owner, open_to
from plantcraft.api.routers.desk.common import DAY, _bad, router
from plantcraft.config import plant_today

# Triage ----------------------------------------------------------------------------------------


class TriageIn(BaseModel):
    key: str = Field(min_length=1, max_length=300)
    state: str | None = Field(default=None, pattern=r"^(done|snoozed|read)$")
    until: str | None = Field(default=None, pattern=DAY)


@router.post("/api/desk/triage")
@open_to("viewer")
def triage(body: TriageIn, request: Request, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """A suggestion done, snoozed until a day, or back (``state`` null). Messages' Notifications
    keep their read and archived marks here too (``/api/notifications``). A public demo visit
    keeps its own (``marks_owner``)."""

    until = body.until or (date.fromisoformat(plant_today()) + timedelta(days=1)).isoformat()
    try:
        rt.desk.set_triage(
            marks_owner(request, rt, user),
            body.key,
            body.state,
            until if body.state == "snoozed" else None,
        )
    except ValueError as exc:
        raise _bad(exc) from exc
    return {"key": body.key, "state": body.state}
