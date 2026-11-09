"""The suggestions of the day, plain rules each with its reason, and what triage hides."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from plantcraft.config import plant_clock, plant_today
from plantcraft.desk.common import STALE_DAYS
from plantcraft.i18n import t

# Suggestions ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Suggestion:
    key: str
    title: str
    reason: str
    state: str
    href: str
    action: str

    def as_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "title": self.title,
            "reason": self.reason,
            "state": self.state,
            "href": self.href,
            "action": self.action,
        }


def suggest(
    *,
    username: str,
    today: date,
    actions: list[dict[str, Any]],
    followed: list[dict[str, Any]],
    conversations: list[dict[str, Any]],
    triage: dict[str, dict[str, Any]],
    now: datetime | None = None,
    limit: int = 8,
) -> list[dict[str, str]]:
    """The day's suggestions, worst first, each with its reason (suggestions,
    not orders). ``actions`` are the open ones the person owns; ``followed`` the current results
    about assets they follow (with ``open_actions``); ``conversations`` theirs."""

    moment = now or datetime.now(timezone.utc)
    found: list[Suggestion] = []
    for action in actions:
        if action.get("owner") != username or not action.get("due_at"):
            continue
        due = date.fromisoformat(action["due_at"][:10])
        href = f"/actions/{action['action_id']}"
        if due < today:
            days = (today - due).days
            found.append(
                Suggestion(
                    f"overdue:{action['action_id']}",
                    action["title"],
                    t("Past its due date by {count} days.", count=days)
                    if days > 1
                    else t("Past its due date since yesterday."),
                    "alarm",
                    href,
                    t("Open"),
                )
            )
        elif due == today:
            found.append(
                Suggestion(
                    f"due:{action['action_id']}:{today.isoformat()}",
                    action["title"],
                    t("Due today."),
                    "warning",
                    href,
                    t("Open"),
                )
            )
    for result in followed:
        if result.get("status") not in ("alarm", "warning") or result.get("open_actions"):
            continue
        ref = result["subject"]
        name = result.get("name") or ref.split(":", 1)[-1]
        title = t(
            "{name}: {summary}", name=name, summary=result.get("summary") or t("needs a look")
        )
        found.append(
            Suggestion(
                f"followed:{ref}:{result.get('app')}:{result.get('kind')}:{result.get('at', '')[:10]}",
                title,
                t("An asset you follow, with no open action."),
                result["status"],
                f"/actions?new=1&ref={ref}&title={title[:120]}",
                t("Create an action"),
            )
        )
    for conversation in conversations:
        last = conversation.get("last_message") or {}
        if (
            not conversation.get("unread")
            or last.get("author") == username
            or not last.get("created_at")
        ):
            continue
        try:
            sent = datetime.fromisoformat(str(last["created_at"]))
        except ValueError:
            continue
        sent = sent if sent.tzinfo else sent.astimezone()
        if moment - sent < timedelta(hours=4):
            continue
        name = (
            conversation.get("display_title")
            or conversation.get("title")
            or last.get("author_name")
            or ""
        )
        found.append(
            Suggestion(
                f"reply:{conversation['conversation_id']}:{last.get('message_id')}",
                t("Answer {name}", name=name),
                t(
                    "A message waiting since {when}.",
                    when=plant_clock(sent, "%d/%m %H:%M"),
                ),
                "warning",
                f"/messages/{conversation['conversation_id']}",
                t("Open"),
            )
        )
    for action in actions:
        if action.get("owner") != username or not action.get("updated_at"):
            continue
        try:
            changed = datetime.fromisoformat(str(action["updated_at"]))
        except ValueError:
            continue
        changed = changed if changed.tzinfo else changed.astimezone()
        days = (moment - changed).days
        if days >= STALE_DAYS and not (
            action.get("due_at") and action["due_at"][:10] <= today.isoformat()
        ):
            found.append(
                Suggestion(
                    f"stale:{action['action_id']}:{action['updated_at'][:10]}",
                    action["title"],
                    t("No change for {count} days: still on it?", count=days),
                    "unknown",
                    f"/actions/{action['action_id']}",
                    t("Open"),
                )
            )
    rank = {"alarm": 0, "warning": 1, "unknown": 2, "ok": 3}
    kept = [item for item in found if not _hidden(triage.get(item.key), today)]
    kept.sort(key=lambda item: rank.get(item.state, 3))
    return [item.as_dict() for item in kept[:limit]]


def _hidden(entry: dict[str, Any] | None, today: date) -> bool:
    if not entry:
        return False
    if entry["state"] == "done":
        return True
    return bool(entry.get("until")) and str(entry["until"]) > today.isoformat()


def hidden(entry: dict[str, Any] | None, today: date | None = None) -> bool:
    """A triaged entry is out of sight: done, or snoozed until a later day."""

    return _hidden(entry, today or date.fromisoformat(plant_today()))
