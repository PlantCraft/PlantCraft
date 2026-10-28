"""Messages' Notifications (owner, 2026-10-24): what came to a person besides conversations, read
like an email inbox beside the chats. Three sources:

- what apps sent (``POST /api/v1/notifications``): one thread per app and ``key`` (an alarm fired,
  reminded, escalated, cleared), with its priority, category and buttons;
- changes other people made to the person's actions and their groups' (comments, status, due);
- alarms and warnings on the assets the person follows.

An entry's key carries its newest event, so a new event brings a read or archived thread back
as unread. Read and archived marks live in Desk's triage (``read``, ``done``) and go after 45
days; the feed shows the last ``FEED_DAYS``.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from processcraft.api.deps import action_visibility
from processcraft.db import utc_text
from processcraft.desk import hidden
from processcraft.i18n import t

FEED_DAYS = 30
CATEGORIES = ("alarm", "run", "action", "info")
_TITLE = re.compile(r"^\*\*(?P<title>.+?)\*\*\s*(?:\n+(?P<text>.*))?$", re.DOTALL)


def _split(body: str) -> tuple[str, str]:
    """A notification's message is ``**title**`` and its text below."""

    match = _TITLE.match(body or "")
    if not match:
        return (body or "").strip()[:200], ""
    return match["title"].strip(), (match["text"] or "").strip()


def _app_threads(rt: Any, user: str, since: str) -> list[dict[str, Any]]:
    from processcraft.api.routers.messages import _resolve, present_ref

    threads: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for message in rt.workspace.messages.notices_for(user, since=since):
        meta = message.get("meta") or {}
        app = str(meta.get("app") or message["author"])
        thread = str(meta.get("key") or f"message-{message['message_id']}")
        threads.setdefault((app, thread), []).append(message)
    settled = rt.notifications.store.resolutions(sorted({app for app, _ in threads}))
    items = []
    for (app, thread), messages in threads.items():
        newest = messages[0]
        meta = newest.get("meta") or {}
        title, text = _split(newest["text"])
        # Settled by the app after its newest send: read for everyone, no buttons.
        resolution = settled.get((app, thread))
        if resolution and str(resolution["at"]) < str(newest["created_at"]):
            resolution = None
        category = meta.get("category") if meta.get("category") in CATEGORIES else None
        refs = []
        for ref in newest.get("refs") or []:
            refs.append(present_ref(_resolve(rt, ref, user)))
        items.append(
            {
                "key": f"notice:{app}:{thread}:{newest['message_id']}",
                "kind": "notice",
                "category": category or ("alarm" if app == "alarmcraft" else "info"),
                "priority": meta.get("priority") or "medium",
                "priority_label": meta.get("priority_label"),
                "app": app,
                "from": newest.get("author_name") or app,
                "title": title,
                "detail": text,
                "at": newest["created_at"],
                "href": meta.get("url"),
                "actions": []
                if resolution
                else [
                    {
                        "label": item["label"],
                        "href": item["href"],
                        "method": "POST" if item.get("method") == "POST" else "GET",
                    }
                    for item in meta.get("actions") or []
                    if isinstance(item, dict) and item.get("label") and item.get("href")
                ][:3],
                "refs": refs,
                "resolved": resolution,
                "seen": bool(newest.get("read")) or resolution is not None,
                "history": [
                    {
                        "title": _split(message["text"])[0],
                        "text": _split(message["text"])[1],
                        "at": message["created_at"],
                        "priority": (message.get("meta") or {}).get("priority"),
                    }
                    for message in messages[:20]
                ],
            }
        )
    return items


def _action_changes(rt: Any, user: str, since: str) -> list[dict[str, Any]]:
    seen = action_visibility(rt, user)
    actions: dict[int, dict[str, Any]] = {}
    for view in ("mine", "groups", "created"):
        for action in rt.workspace.actions.list(visible=seen, view=view, limit=200):
            if str(action.get("updated_at") or "") >= since:
                actions[action["action_id"]] = action
    items = []
    for action in sorted(actions.values(), key=lambda item: item["updated_at"], reverse=True)[:60]:
        for entry in rt.workspace.actions.history(action["action_id"]):
            if entry["actor"] == user or str(entry["created_at"]) < since:
                continue
            items.append(
                {
                    "key": f"action:{action['action_id']}:{entry['created_at']}:{entry['kind']}",
                    "kind": "action",
                    "category": "action",
                    "priority": action.get("priority") or "medium",
                    "app": "processcraft",
                    "from": entry["actor_name"],
                    "title": action["title"],
                    "detail": entry["text"][:500],
                    "at": entry["created_at"],
                    "href": f"/actions/{action['action_id']}",
                    "actions": [],
                    "refs": [],
                    "seen": False,
                    "history": [],
                }
            )
    return items


def _followed_alarms(rt: Any, user: str, since: str) -> list[dict[str, Any]]:
    from processcraft.api.routers.desk import followed_assets

    items = []
    for item in followed_assets(rt, user):
        if item["status"] not in ("alarm", "warning") or not item.get("at"):
            continue
        if str(item["at"]) < since[:10]:
            continue
        items.append(
            {
                "key": f"result:{item['ref']}:{item['app']}:{item['kind']}:{item['at']}",
                "kind": "followed",
                "category": "alarm",
                "priority": "high" if item["status"] == "alarm" else "medium",
                "app": item.get("app") or "",
                "from": item.get("kind_label") or t("Followed asset"),
                "title": item["name"],
                "detail": item["summary"],
                "at": item["at"],
                "href": item.get("href"),
                "actions": [],
                "refs": [],
                "seen": False,
                "history": [],
                "state": item["status"],
            }
        )
    return items


def mark_key(key: str) -> str:
    """What a favorite is kept under: an app's notification thread without its newest event (a
    new event keeps the star), any other entry as it is."""

    if key.startswith("notice:"):
        head, _, tail = key.rpartition(":")
        if tail.isdigit() and head.count(":") >= 2:
            return head
    return key


def notification_feed(rt: Any, user: str, owner: str | None = None) -> list[dict[str, Any]]:
    """Every entry of the last ``FEED_DAYS``, newest first, each with ``state``: ``unread``,
    ``read`` or ``archived``, and ``starred``. ``owner``: whose marks they are (a public demo
    visit keeps its own, ``marks_owner``)."""

    since = utc_text(datetime.now(timezone.utc) - timedelta(days=FEED_DAYS))
    items = [
        *_app_threads(rt, user, since),
        *_action_changes(rt, user, since),
        *_followed_alarms(rt, user, since),
    ]
    marks = rt.desk.triage(owner or user)
    stars = rt.desk.marks(owner or user, "star")
    for item in items:
        mark = marks.get(item["key"])
        item["starred"] = mark_key(item["key"]) in stars
        if mark and mark["state"] in ("done", "snoozed") and hidden(mark):
            item["state"] = "archived"
        elif mark and mark["state"] == "unread":
            item["state"] = "unread"
        elif (mark and mark["state"] == "read") or item.pop("seen", False):
            item["state"] = "read"
        else:
            item["state"] = "unread"
        item.pop("seen", None)
    items.sort(key=lambda item: str(item.get("at") or ""), reverse=True)
    return items[:300]


def marked_unread_chats(rt: Any, user: str, owner: str) -> int:
    """Conversations the person marked unread that have no unread message of their own (what the
    unread count adds for them)."""

    marked = rt.desk.marks(owner, "unread")
    if not marked:
        return 0
    return sum(
        1
        for item in rt.workspace.messages.list_for(user)
        if f"conversation:{item['conversation_id']}" in marked and not item.get("unread")
    )


# How recent an unread critical or high notification must be to pop up in every app.
URGENT_MINUTES = 60


def inbox_notices(
    rt: Any, user: str, owner: str | None = None
) -> tuple[int, dict[str, Any] | None]:
    """The unread count and the newest unread critical or high notification an app sent in the
    last ``URGENT_MINUTES`` (shown at once in whatever app the person has open, with its
    buttons), from one reading of the feed."""

    items = notification_feed(rt, user, owner)
    unread = [item for item in items if item["state"] == "unread"]
    since = utc_text(datetime.now(timezone.utc) - timedelta(minutes=URGENT_MINUTES))
    urgent = next(
        (
            item
            for item in unread
            if item["kind"] == "notice"
            and item["priority"] in ("critical", "high")
            and str(item["at"]) >= since
        ),
        None,
    )
    if urgent is not None:
        fields = ("key", "title", "detail", "priority", "priority_label", "from", "at", "href")
        urgent = {field: urgent.get(field) for field in fields} | {"actions": urgent["actions"]}
    return len(unread), urgent
