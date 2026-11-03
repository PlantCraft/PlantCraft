"""Desk's day: what the Overview's Desk widgets read at once."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Query, Request

from plantcraft.actions import OPEN_STATUSES
from plantcraft.api.deps import CurrentUser, Runtime, action_visibility, marks_owner
from plantcraft.api.feed import visit_reads
from plantcraft.api.routers.desk.common import DAY, _today, _today_todos, followed_assets, router
from plantcraft.desk import suggest

# Today ----------------------------------------------------------------------------------------


@router.get("/api/desk/today")
def today(
    request: Request,
    user: CurrentUser,
    rt: Runtime,
    day: Annotated[str | None, Query(pattern=DAY)] = None,
) -> dict[str, Any]:
    """What the Overview's Desk widgets read at once: the day's to-dos (My day), the person's
    open actions by due date, the assets they follow and the day's suggestions."""

    when = _today(day)
    seen = action_visibility(rt, user)
    mine = rt.workspace.actions.list(
        statuses=list(OPEN_STATUSES), visible=seen, view="mine", limit=500
    )
    followed = followed_assets(rt, user)
    owner = marks_owner(request, rt, user)
    conversations = rt.workspace.messages.list_for(user, limit=50, read_upto=visit_reads(rt, owner))
    triage = rt.desk.triage(owner)
    iso = when.isoformat()
    overdue = [item for item in mine if item.get("due_at") and item["due_at"][:10] < iso]
    due_today = [item for item in mine if item.get("due_at") and item["due_at"][:10] == iso]
    return {
        "day": iso,
        "todos": _today_todos(rt, user, when),
        "actions": {"open": len(mine), "overdue": len(overdue), "today": len(due_today)},
        "followed": followed,
        "suggestions": suggest(
            username=user,
            today=when,
            actions=mine,
            followed=followed,
            conversations=conversations,
            triage=triage,
        ),
        "unread": sum(int(item.get("unread") or 0) for item in conversations),
    }
