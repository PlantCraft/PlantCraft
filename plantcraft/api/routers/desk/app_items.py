"""What the apps put in Desk: their calendar feeds and to-dos, read through their access."""

from __future__ import annotations

from typing import Any

from plantcraft.api.routers.desk.common import _my_groups
from plantcraft.auth.suite import app_access


def _app_names(rt: Any) -> dict[str, str]:
    return {item.id: item.name for item in rt.suite_apps()}


def app_feeds(rt: Any, apps: dict[str, str]) -> dict[str, dict[str, Any]]:
    """The calendar feeds the apps a person opens declared (``[[contributes.calendar]]``), by
    ``<app>:<feed>``, in the suite's order."""

    names = _app_names(rt)
    found: dict[str, dict[str, Any]] = {}
    for row in rt.contributions.listing(list(apps)):
        for feed in (row.get("contributes") or {}).get("calendar", []):
            found[f"{row['app']}:{feed['id']}"] = {
                "id": f"{row['app']}:{feed['id']}",
                "app": row["app"],
                "app_name": names.get(row["app"], row["app"]),
                "title": feed["title"],
                "description": feed.get("description") or "",
                "visible": feed.get("visible", True),
            }
    return found


def app_todos(rt: Any, user: str, access: Any, *, done: bool = False) -> list[dict[str, Any]]:
    """The to-dos the apps a person opens gave them or their groups, with the app's name and
    the kind's title."""

    apps = app_access(access, rt.suite_apps())
    names = _app_names(rt)
    kinds = {
        (row["app"], kind["id"]): kind["title"]
        for row in rt.contributions.listing(list(apps))
        for kind in (row.get("contributes") or {}).get("todo", [])
    }
    group_names = {group["group_id"]: group["name"] for group in rt.workspace.groups.list()}
    items = rt.app_items.todos_for(
        user, _my_groups(rt, user), apps=set(apps), done=done, limit=50 if done else 500
    )
    out = []
    for item in items:
        target_kind, _, target = item["for"].partition(":")
        out.append(
            {
                **item,
                "app_name": names.get(item["app"], item["app"]),
                "kind_title": kinds.get((item["app"], item["kind"]), item["kind"]),
                "group_name": group_names.get(target) if target_kind == "group" else None,
            }
        )
    return out
