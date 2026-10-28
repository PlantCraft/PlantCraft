"""Trends: signals over a period, as one or several plots; saved to open again.

Everyone with access reads trends and saves their own (a trend is a working view, not a screen
for the plant); its author or an editor changes or deletes it. Data is read with the person's
own token, so PlantCraft decides which signals they see. A public demo's visitors all share one
account: they try the editor, but nothing is saved (one visitor would change another's trends).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Response

from dashcraft.api.deps import CurrentUser, RuntimeDep, guarded
from dashcraft.dashboards.trends import TrendPayload, TrendView
from dashcraft.i18n import t
from dashcraft.query.trends import read_view

router = APIRouter(prefix="/api/trends", tags=["trends"])


def _found(rt: RuntimeDep, trend_id: str) -> dict[str, Any]:
    found = rt.trends.get(trend_id) if len(trend_id) <= 40 else None
    if found is None:
        raise HTTPException(status_code=404, detail=t("Trend not found."))
    return found


def _saves(user: Any) -> None:
    if user.demo is not None:
        raise HTTPException(
            status_code=403,
            detail=t("This is a public demo: you can try everything, but nothing is saved."),
        )


def _may_change(user: Any, trend: dict[str, Any]) -> None:
    _saves(user)
    if not (user.can_edit or trend.get("created_by") == user.username):
        raise HTTPException(
            status_code=403, detail=t("Only its author or an editor can change this trend.")
        )


@router.get("")
def list_trends(rt: RuntimeDep, _user: CurrentUser) -> list[dict[str, Any]]:
    return rt.trends.list()


@router.post("", status_code=201)
def create_trend(payload: TrendPayload, rt: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    _saves(user)
    created = rt.trends.create(payload, user.username)
    rt.audit(user, "trend.create", created["trend_id"], {"name": created["name"]})
    return created


@router.post("/data")
def trend_data(view: TrendView, rt: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    """The lines of a trend, saved or not."""

    reader = rt.user_reader(user)
    return guarded(lambda: read_view(reader, view), service=False)


@router.get("/{trend_id}")
def get_trend(trend_id: str, rt: RuntimeDep, _user: CurrentUser) -> dict[str, Any]:
    return _found(rt, trend_id)


@router.put("/{trend_id}")
def update_trend(
    trend_id: str, payload: TrendPayload, rt: RuntimeDep, user: CurrentUser
) -> dict[str, Any]:
    _may_change(user, _found(rt, trend_id))
    saved = rt.trends.update(trend_id, payload, user.username)
    if saved is None:
        raise HTTPException(status_code=404, detail=t("Trend not found."))
    rt.audit(user, "trend.update", trend_id, {"name": saved["name"]})
    return saved


@router.delete("/{trend_id}", status_code=204)
def delete_trend(trend_id: str, rt: RuntimeDep, user: CurrentUser) -> Response:
    found = _found(rt, trend_id)
    _may_change(user, found)
    rt.trends.delete(trend_id)
    rt.audit(user, "trend.delete", trend_id, {"name": found["name"]})
    return Response(status_code=204)
