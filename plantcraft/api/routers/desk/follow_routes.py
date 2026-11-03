"""The assets a person follows on Desk."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import HTTPException, Query
from pydantic import BaseModel, Field

from plantcraft.api.deps import CurrentUser, Runtime, open_to
from plantcraft.api.routers.desk.common import _bad, followed_assets, router
from plantcraft.i18n import t
from plantcraft.refs import parse_ref

# Followed assets ------------------------------------------------------------------------------


class FollowIn(BaseModel):
    ref: str = Field(min_length=3, max_length=400)


@router.get("/api/desk/follows")
def follows(
    user: CurrentUser, rt: Runtime, ref: Annotated[str | None, Query(max_length=400)] = None
) -> dict[str, Any]:
    """The assets the person follows, worst first; with ``ref``, only whether they follow it."""

    if ref is not None:
        return {"ref": ref, "following": ref in rt.desk.follows(user)}
    rank = {"alarm": 0, "warning": 1, "unknown": 2, "ok": 3}
    items = sorted(
        followed_assets(rt, user), key=lambda item: (rank.get(item["status"], 2), item["name"])
    )
    return {"items": items}


@router.put("/api/desk/follows")
@open_to("viewer")
def follow(body: FollowIn, user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    try:
        ref = str(parse_ref(body.ref))
    except ValueError as exc:
        raise _bad(exc) from exc
    if not ref.startswith("asset:"):
        raise HTTPException(status_code=422, detail=t("Only assets can be followed."))
    if not rt.asset_scope(user).subject(ref):
        raise HTTPException(status_code=404, detail=t("Asset not found."))
    try:
        rt.desk.follow(user, ref)
    except ValueError as exc:
        raise _bad(exc) from exc
    return {"ref": ref, "following": True}


@router.delete("/api/desk/follows")
@open_to("viewer")
def unfollow(
    user: CurrentUser, rt: Runtime, ref: Annotated[str, Query(min_length=3, max_length=400)]
) -> dict[str, Any]:
    rt.desk.unfollow(user, ref)
    return {"ref": ref, "following": False}
