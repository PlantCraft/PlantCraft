"""What StarterCraft puts in Desk (PlantCraft ``plantcraft_sdk.desk``): the notes that ask for
a follow-up, on the calendar feed ``follow-ups`` and as a to-do of kind ``follow-up`` for the
person named. Both are declared in ``app.toml`` (``[[contributes.calendar]]``,
``[[contributes.todo]]``); PlantCraft refuses what is not."""

from __future__ import annotations

import logging
from typing import Any

from plantcraft_sdk.client import PlantCraftError
from plantcraft_sdk.desk import MAX_FEED_ITEMS

from starter.i18n import t

LOGGER = logging.getLogger(__name__)
FEED = "follow-ups"
TODO_KIND = "follow-up"


def _key(note_id: str) -> str:
    return f"note:{note_id}"


def send_follow_ups(client: Any, notes: list[dict[str, Any]]) -> None:
    """The feed's whole list, sent again after each change (the newest first if there are many)."""

    if client is None:
        return
    items = [
        {
            "id": note["note_id"],
            "title": t("Follow up {asset}", asset=note["asset_id"]),
            "start": note["follow_up"],
            "all_day": True,
            "audience": f"user:{note['follow_up_by']}" if note.get("follow_up_by") else "everyone",
            "ref": f"asset:{note['asset_id']}",
            "url": f"/starter/notes/{note['note_id']}",
            "detail": note["text"][:300],
        }
        for note in notes[-MAX_FEED_ITEMS:]
    ]
    try:
        client.put_calendar(FEED, items)
    except PlantCraftError as exc:
        LOGGER.warning("Calendar feed %s not sent: %s", FEED, exc)


def follow_up_todo(client: Any, note: dict[str, Any], asset_name: str) -> None:
    """The person's to-do for the note; closed when the note no longer asks for one."""

    if client is None:
        return
    try:
        if not note.get("follow_up_by"):
            client.close_todos([_key(note["note_id"])])
            return
        client.put_todo(
            {
                "key": _key(note["note_id"]),
                "kind": TODO_KIND,
                "title": t("Follow up the note on {asset}", asset=asset_name),
                "for": f"user:{note['follow_up_by']}",
                "due": note.get("follow_up"),
                "ref": f"asset:{note['asset_id']}",
                "url": f"/starter/notes/{note['note_id']}",
                "detail": note["text"][:300],
            }
        )
    except PlantCraftError as exc:
        LOGGER.warning("To-do for note %s not sent: %s", note["note_id"], exc)


def close_follow_up(client: Any, note_id: str) -> None:
    if client is None:
        return
    try:
        client.close_todos([_key(note_id)])
    except PlantCraftError as exc:
        LOGGER.warning("To-do for note %s not closed: %s", note_id, exc)
