"""People, groups and notifications in API v1 (docs/api-v1.md, docs/notifications.md).

The shapes the platform answers, and the rules a notification follows; ``FakePlantCraft``
checks a body with :func:`check_notification`, so a body the fake accepts PlantCraft accepts.
"""

from __future__ import annotations

from typing import Any, TypedDict

from plantcraft_sdk.contract import ContractError

PRIORITIES = ("critical", "high", "medium", "low")
CATEGORIES = ("alarm", "run", "action", "info")
MAX_ACTIONS = 3
# GET opens the page; POST runs the call in the sending app as the person (SDK 0.53.0).
ACTION_METHODS = ("GET", "POST")
GROUP_KINDS = ("department", "area", "discipline", "team")
MAX_RECIPIENTS = 50
MAX_TITLE = 200
MAX_TEXT = 3000


class Person(TypedDict):
    username: str
    name: str
    role: str
    job_title: str
    unit: str
    groups: list[str]


class Group(TypedDict):
    id: str
    name: str
    kind: str
    description: str
    asset_id: str | None
    coordinator: str | None
    members: list[str]
    # The group it sits under (groups form a tree; the coordinator leads the ones below).
    parent_id: str | None


class NotificationReceipt(TypedDict):
    delivered: list[str]
    email_queued: int
    unknown: list[str]


class NotificationResolution(TypedDict):
    key: str
    resolved_at: str
    note: str


def recipient(kind: str, name: str) -> str:
    """``user:<username>`` or ``group:<id>``."""

    if kind not in {"user", "group"}:
        raise ContractError("A recipient is a user or a group.")
    return f"{kind}:{name}"


def check_notification(body: Any) -> dict[str, Any]:
    """The body of ``POST /api/v1/notifications``, checked; raises ``ContractError``."""

    if not isinstance(body, dict):
        raise ContractError("Send a JSON object with recipients and a title.")
    recipients = body.get("recipients")
    if (
        not isinstance(recipients, list)
        or not 1 <= len(recipients) <= MAX_RECIPIENTS
        or not all(isinstance(item, str) and 3 <= len(item) <= 80 for item in recipients)
    ):
        raise ContractError(f"recipients: 1 to {MAX_RECIPIENTS} of user:<name> or group:<id>.")
    title = body.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > MAX_TITLE:
        raise ContractError(f"title: 1 to {MAX_TITLE} characters.")
    text = body.get("text") or ""
    if not isinstance(text, str) or len(text) > MAX_TEXT:
        raise ContractError(f"text: at most {MAX_TEXT} characters.")
    priority = body.get("priority") or "medium"
    if priority not in PRIORITIES:
        raise ContractError("priority: critical, high, medium or low.")
    url = body.get("url")
    if url is not None and (
        not isinstance(url, str) or not url.startswith("/") or url.startswith("//")
    ):
        raise ContractError("url: a path of the suite, like /alarm/.")
    category = body.get("category")
    if category is not None and category not in CATEGORIES:
        raise ContractError("category: alarm, run, action or info.")
    actions = body.get("actions") or []
    if not isinstance(actions, list) or len(actions) > MAX_ACTIONS:
        raise ContractError(f"actions: at most {MAX_ACTIONS} buttons.")
    for action in actions:
        label = action.get("label") if isinstance(action, dict) else None
        href = action.get("href") if isinstance(action, dict) else None
        if not isinstance(label, str) or not 1 <= len(label.strip()) <= 40:
            raise ContractError("actions: each with a label of 1 to 40 characters.")
        if not isinstance(href, str) or not href.startswith("/") or href.startswith("//"):
            raise ContractError("actions: each href a path of the suite, like /alarm/alarms/12.")
        if action.get("method", "GET") not in ACTION_METHODS:
            raise ContractError("actions: method GET (open the page) or POST (run the call).")
    return {
        "recipients": list(recipients),
        "title": title.strip(),
        "text": text.strip(),
        "priority": priority,
        "url": url,
        "email": bool(body.get("email")),
        "refs": list(body.get("refs") or []),
        "key": body.get("key"),
        "category": category,
        "actions": [
            {
                "label": item["label"].strip(),
                "href": item["href"],
                "method": item.get("method", "GET"),
            }
            for item in actions
        ],
    }


def check_resolution(body: Any) -> dict[str, str]:
    """The body of ``POST /api/v1/notifications/resolve``, checked; raises ``ContractError``."""

    if not isinstance(body, dict):
        raise ContractError("Send a JSON object with the key.")
    key = body.get("key")
    if not isinstance(key, str) or not 1 <= len(key.strip()) <= 200:
        raise ContractError("key: 1 to 200 characters.")
    note = body.get("note") or ""
    if not isinstance(note, str) or len(note) > 200:
        raise ContractError("note: at most 200 characters.")
    return {"key": key.strip(), "note": note.strip()}
