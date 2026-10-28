"""History replay: every enabled alarm's past judged over the archive (editors)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from alarmcraft.api.deps import EditorUser, RuntimeDep
from alarmcraft.i18n import t
from alarmcraft.monitor.history import MAX_HOURS

router = APIRouter(prefix="/api/history", tags=["history"])


class Replay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hours: float = Field(default=24, gt=0, le=MAX_HOURS)
    acknowledged_by: str = Field(default="", max_length=80)


@router.post("/replay", status_code=202)
def replay(rt: RuntimeDep, user: EditorUser, body: Replay | None = None) -> dict[str, Any]:
    """Start the replay in the background; ``GET`` says how far it got."""

    if not rt.has_service_key:
        raise HTTPException(503, t("Alarms needs its app key to read the plant: an admin sets it."))
    body = body or Replay()
    started = rt.replay.start(body.hours, body.acknowledged_by.strip())
    if started:
        rt.audit(user, "history.replayed", "alarms", {"hours": body.hours})
    return {"started": started, **rt.replay.state}


@router.get("/replay")
def replay_status(rt: RuntimeDep, _user: EditorUser) -> dict[str, Any]:
    return rt.replay.state
