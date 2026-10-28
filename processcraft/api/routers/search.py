"""HTTP routes: PlantCraft's part of the suite's search (Ctrl+K, docs/en/search.md).

The frame every app draws (``@plantcraft/ui`` ``SuiteSearch``) asks each app of the suite
``GET <prefix>api/search?q=`` at once and lists the answers by app. PlantCraft answers with
what it owns: assets, people, groups and the actions the person sees. Points live in the
Historian, dashboards in View, blocks in Link: each app answers for its own objects. Every
``href`` is a path inside PlantCraft, joined to its address by the frame.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from plantcraft_sdk.server.search import matches, rank
from processcraft.api.deps import CurrentUser, Runtime
from processcraft.api.deps import action_visibility as visibility
from processcraft.i18n import t

router = APIRouter()

FORMAT = "plantcraft-search/1"


@router.get("/api/search")
def search(
    user: CurrentUser,
    rt: Runtime,
    q: Annotated[str, Query(max_length=120)] = "",
    limit: Annotated[int, Query(ge=1, le=20)] = 6,
) -> dict[str, Any]:
    """Assets, people, groups and visible actions whose name holds every word of ``q``."""

    text = " ".join(q.split())
    if len(text) < 2:
        return {"format": FORMAT, "items": []}
    workspace = rt.workspace
    found: list[tuple[int, int, dict[str, Any]]] = []

    kinds = {item["kind"]: item["label"] for item in workspace.assets.kinds()}
    scope = rt.asset_scope(user)
    # Someone who sees part of the plant searches deeper: most matches may be out of it.
    wanted = limit * 3 if scope.everything else limit * 30
    assets = [
        item
        for item in workspace.assets.search(text, limit=wanted)
        if scope.asset(item["asset_id"])
    ]
    for asset in assets[: limit * 3]:
        title = asset["asset_id"] if asset["name"] == asset["asset_id"] else asset["name"]
        detail = asset["asset_id"] if title != asset["asset_id"] else asset["description"]
        found.append(
            (
                0,
                min(rank(text, asset["asset_id"]), rank(text, asset["name"])),
                {
                    "title": title,
                    "detail": (detail or "")[:160] or None,
                    "type": kinds.get(asset["kind"], asset["kind"]),
                    "href": f"/assets/{asset['asset_id']}",
                },
            )
        )

    for person in workspace.users.list_users(kind="person"):
        name = person.get("display_name") or person["username"]
        if matches(text, name, person["username"], person.get("email")):
            found.append(
                (
                    1,
                    rank(text, name),
                    {
                        "title": name,
                        "detail": person["username"],
                        "type": t("Person"),
                        "href": f"/people/{person['username']}",
                    },
                )
            )

    for group in workspace.groups.list():
        if matches(text, group["name"], group.get("description")):
            found.append(
                (
                    2,
                    rank(text, group["name"]),
                    {
                        "title": group["name"],
                        "detail": (group.get("description") or "")[:160] or None,
                        "type": t("Group"),
                        "href": f"/groups/{group['group_id']}",
                    },
                )
            )

    for action in workspace.actions.list(query=text, visible=visibility(rt, user), limit=limit):
        found.append(
            (
                3,
                rank(text, action["title"]),
                {
                    "title": f"AC-{action['action_id']} · {action['title']}",
                    "detail": action.get("status"),
                    "type": t("Action"),
                    "href": f"/actions/{action['action_id']}",
                },
            )
        )

    found.sort(key=lambda item: (item[1], item[0]))
    return {"format": FORMAT, "items": [item for _, _, item in found[:limit]]}


@router.get("/api/queue")
def queue(_user: CurrentUser) -> dict[str, Any]:
    """PlantCraft queues no work of its own: the frame's queue indicator asks every app of the
    suite ``GET <prefix>api/queue`` and leaves out the ones whose ``now`` is empty."""

    return {"format": "plantcraft-queue/1", "now": None, "history": []}
