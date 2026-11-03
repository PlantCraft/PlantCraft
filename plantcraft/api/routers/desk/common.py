"""What Desk's routes share: the one ``router``, days, groups and the assets a person follows."""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException

from plantcraft.actions import OPEN_STATUSES
from plantcraft.api.deps import action_visibility
from plantcraft.api.routers.messages import _resolve, present_ref
from plantcraft.config import plant_today
from plantcraft.db import utc_text
from plantcraft.desk import occurrences
from plantcraft.i18n import t

router = APIRouter()

DAY = r"^\d{4}-\d{2}-\d{2}$"
# The calendar answers for two months at most at once (a month view with its edges).
# The calendar's widest view is a year (round 8), with the days of the weeks around it.
MAX_SPAN_DAYS = 380


def _today(day: str | None) -> date:
    if not day:
        return date.fromisoformat(plant_today())
    try:
        return date.fromisoformat(day)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=t("The day must be a date (YYYY-MM-DD).")
        ) from exc


def _bad(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


def _my_groups(rt: Any, user: str) -> list[str]:
    return [group["group_id"] for group in rt.workspace.groups.of(user)]


def _worst(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    rank = {"alarm": 3, "warning": 2, "unknown": 1, "ok": 0}
    worst: dict[str, dict[str, Any]] = {}
    for result in results:
        current = worst.get(result["subject"])
        if current is None or rank.get(result["status"], 0) > rank.get(current["status"], 0):
            worst[result["subject"]] = result
    return worst


def _open_refs(rt: Any, user: str) -> Counter[str]:
    """Open actions per item, of those ``user`` sees (another group's do not count)."""

    counts: Counter[str] = Counter()
    found = rt.workspace.actions.list(
        statuses=list(OPEN_STATUSES), visible=action_visibility(rt, user), limit=5000
    )
    for action in found:
        counts.update(set(action["refs"]))
    return counts


def followed_assets(rt: Any, user: str) -> list[dict[str, Any]]:
    """The assets the person follows with their worst current result and open actions."""

    # An asset that left the person's asset scope is no longer followed (docs/asset-scope.md).
    scope = rt.asset_scope(user)
    refs = [ref for ref in rt.desk.follows(user) if scope.subject(ref)]
    if not refs:
        return []
    now = utc_text()
    current = [
        item
        for item in rt.workspace.results.results(subjects=refs, apps=rt.apps_for(user))
        if not item.get("expires_at") or item["expires_at"] > now
    ]
    worst = _worst(current)
    open_refs = _open_refs(rt, user)
    items = []
    for ref in refs:
        resolved = present_ref(_resolve(rt, ref, user))
        result = worst.get(ref)
        items.append(
            {
                "ref": ref,
                "name": resolved.get("title") or ref.split(":", 1)[-1],
                "kind_label": resolved.get("kind_label"),
                "href": resolved.get("href"),
                "exists": resolved.get("exists"),
                "subject": ref,
                "status": result["status"] if result else "unknown",
                "summary": result["summary"] if result else "",
                "app": result["app"] if result else None,
                "kind": result["kind"] if result else None,
                "at": result["at"] if result else None,
                "open_actions": open_refs.get(ref, 0),
            }
        )
    return items


def _today_todos(rt: Any, user: str, day: date) -> list[dict[str, Any]]:
    """My day: what is due by ``day`` (late ones too) or was picked for it, and what was done
    on it."""

    iso = day.isoformat()
    groups = _my_groups(rt, user)
    open_ = [
        item
        for item in rt.desk.todos(user, groups, done=False)
        if (item["due"] and item["due"] <= iso) or item["my_day"] == iso
    ]
    done = [
        item
        for item in rt.desk.todos(user, groups, done=True, limit=200)
        if (item["done_at"] or "")[:10] == iso or item["due"] == iso
    ]
    return open_ + done


def _present_note(rt: Any, user: str, note: dict[str, Any]) -> dict[str, Any]:
    names = {item["username"]: item["display_name"] for item in rt.workspace.users.list_users()}
    groups = {group["group_id"]: group["name"] for group in rt.workspace.groups.list()}
    shared = [
        {
            "ref": item,
            "name": (names if item.startswith("user:") else groups).get(
                item.split(":", 1)[1], item
            ),
        }
        for item in note.get("shared") or []
    ]
    return {
        **note,
        "mine": note["owner"] == user,
        "owner_name": names.get(note["owner"], note["owner"]),
        "shared": shared,
    }


def note_mentions(body: Any) -> list[str]:
    """The ``#`` mentions written in a note's body (Tiptap ``mention`` nodes), in order."""

    found: list[str] = []
    stack = [body]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if node.get("type") == "mention":
                ref = str((node.get("attrs") or {}).get("id") or "")
                if ref and ref not in found:
                    found.append(ref)
            stack.extend(reversed(node.get("content") or []))
    return found[:100]


def _with_refs(rt: Any, user: str, note: dict[str, Any]) -> dict[str, Any]:
    return {
        **_present_note(rt, user, note),
        "refs": [present_ref(_resolve(rt, ref, user)) for ref in note_mentions(note.get("body"))],
    }


def own_events(rt: Any, user: str, low: date, high: date) -> list[dict[str, Any]]:
    """The person's events laid out on the plant days [low, high], one entry each time."""

    found = []
    for event in rt.desk.events(user, low, high):
        for start, end in occurrences(event, low, high):
            found.append(
                {
                    "id": f"event:{event['event_id']}"
                    + (f":{start[:10]}" if event["repeat"] else ""),
                    "event_id": event["event_id"],
                    "title": event["title"],
                    "start": start,
                    "end": end,
                    "all_day": event["all_day"],
                    "kind": "event",
                    "editable": True,
                    "repeat": event["repeat"],
                    "series_start": event["start"],
                    "series_end": event["end"],
                    "detail": event["notes"][:200],
                }
            )
    return found
