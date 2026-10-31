"""Trackings (M3): a model run against the plant on a schedule, its error kept as a signal.

``GET/POST /api/trackings``, ``GET/PUT/DELETE /api/trackings/{id}`` and
``POST /api/trackings/{id}/run`` (run now). Editors change them; everyone reads them. The
schedule and the signals are ``runs/tracking.py``.
"""

from __future__ import annotations

import math
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from modelcraft.api.deps import CurrentUser, EditorUser, RuntimeDep, project_or_404
from modelcraft.api.routers.model import CLASS
from modelcraft.i18n import t
from modelcraft.omc.runner import OVERRIDE_NAME

router = APIRouter(prefix="/api", tags=["trackings"])


def _variables(value: dict[str, str]) -> dict[str, str]:
    for name, signal in value.items():
        if not OVERRIDE_NAME.match(name) or not signal or len(signal) > 300:
            raise ValueError(f"not a variable and a signal: {name[:60]}")
    return value


class TrackingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=400, pattern=CLASS)
    name: str = Field(min_length=1, max_length=120)
    inputs: dict[str, str] = Field(default_factory=dict, max_length=50)
    compare: dict[str, str] = Field(min_length=1, max_length=20)
    # The window simulated each time (minutes up to now) and how often (minutes).
    window_minutes: float = Field(default=60, ge=5, le=7 * 24 * 60)
    every_minutes: float = Field(default=15, ge=5, le=7 * 24 * 60)
    step_seconds: float | None = Field(default=None, ge=1, le=86_400)
    intervals: int = Field(default=500, ge=10, le=20_000)
    overrides: dict[str, float | bool] = Field(default_factory=dict, max_length=500)
    # Optional alarm: the mean absolute error above which a variable is off the plant.
    limits: dict[str, float] = Field(default_factory=dict, max_length=20)
    enabled: bool = True

    @field_validator("inputs", "compare")
    @classmethod
    def _names(cls, value: dict[str, str]) -> dict[str, str]:
        return _variables(value)

    @field_validator("limits")
    @classmethod
    def _limits(cls, value: dict[str, float]) -> dict[str, float]:
        for name, limit in value.items():
            if not math.isfinite(limit) or limit <= 0:
                raise ValueError(f"a limit is a positive number: {name[:60]}")
        return value

    def config(self) -> dict[str, Any]:
        unknown = set(self.limits) - set(self.compare)
        if unknown:
            raise HTTPException(
                422, t("A limit names a variable that is not compared: {name}", name=min(unknown))
            )
        return self.model_dump(
            include={"inputs", "compare", "window_minutes", "every_minutes", "step_seconds",
                     "intervals", "overrides", "limits"}
        )  # fmt: skip


def _tracking_or_404(rt, tracking_id: str) -> dict[str, Any]:
    found = rt.trackings.get(tracking_id) if len(tracking_id) <= 64 else None
    if found is None:
        raise HTTPException(404, t("Tracking not found."))
    return found


@router.get("/trackings")
def list_trackings(
    rt: RuntimeDep, _user: CurrentUser, project: str | None = Query(default=None, max_length=64)
) -> list[dict[str, Any]]:
    return rt.trackings.list(project)


@router.post("/trackings", status_code=201)
def create_tracking(body: TrackingBody, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    project_or_404(rt, body.project_id)
    found = rt.trackings.create(
        body.project_id, body.model, body.name.strip(), body.config(), by=user.username
    )
    if not body.enabled:
        found = rt.trackings.update(found["id"], enabled=False)
    rt.audit(user, "tracking.created", f"project:{body.project_id}", {"tracking": found["id"]})
    return found


@router.get("/trackings/{tracking_id}")
def get_tracking(tracking_id: str, rt: RuntimeDep, _user: CurrentUser) -> dict[str, Any]:
    return _tracking_or_404(rt, tracking_id)


@router.put("/trackings/{tracking_id}")
def update_tracking(
    tracking_id: str, body: TrackingBody, rt: RuntimeDep, user: EditorUser
) -> dict[str, Any]:
    found = _tracking_or_404(rt, tracking_id)
    if body.project_id != found["project_id"] or body.model != found["model"]:
        raise HTTPException(422, t("A tracking keeps its project and model: add a new one."))
    updated = rt.trackings.update(
        tracking_id, name=body.name.strip(), config=body.config(), enabled=body.enabled
    )
    rt.audit(user, "tracking.updated", f"project:{found['project_id']}", {"tracking": tracking_id})
    return updated  # type: ignore[return-value]


@router.delete("/trackings/{tracking_id}", status_code=204)
def delete_tracking(tracking_id: str, rt: RuntimeDep, user: EditorUser) -> None:
    found = _tracking_or_404(rt, tracking_id)
    rt.trackings.delete(tracking_id)
    rt.audit(user, "tracking.deleted", f"project:{found['project_id']}", {"tracking": tracking_id})


@router.post("/trackings/{tracking_id}/run", status_code=202)
def run_tracking(tracking_id: str, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    """Run the tracking now, whatever its schedule; the tracking (its last run queued or the
    reason it could not start)."""

    found = _tracking_or_404(rt, tracking_id)
    rt.tracker.run_now(found)
    rt.audit(user, "tracking.run", f"project:{found['project_id']}", {"tracking": tracking_id})
    return _tracking_or_404(rt, tracking_id)
