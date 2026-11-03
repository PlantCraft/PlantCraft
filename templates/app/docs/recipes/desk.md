# Desk: calendar and to-do

Desk is PlantCraft's personal page: a calendar, a to-do list and Today. An app puts items there
through two declared contributions:

- a **calendar feed**: the app sends the feed's whole list again after each change;
- a **to-do** for a person or everyone, with a key the app uses to close it.

The example: a note may ask for a follow-up on a day, by a person.

`app.toml`:

```toml
[[contributes.calendar]]
id = "follow-ups"
title = "Follow-ups"
description = "The notes that ask for a follow-up, on their day."

[[contributes.todo]]
id = "follow-up"
title = "Follow up a note"
```

Add `follow_up` (a day, `^\d{4}-\d{2}-\d{2}$`) and `follow_up_by` (a username) to `NoteDraft`
and to the table (a `MIGRATIONS` step if a version was already released, [../data.md](../data.md)),
and a store method `follow_ups()` that lists the notes with a follow-up by day.

`src/starter/suite/desk.py`:

```python
"""What StarterCraft puts in Desk: follow-ups on the calendar and in a person's to-do."""

import logging
from typing import Any

from plantcraft_sdk.client import PlantCraftError
from plantcraft_sdk.desk import MAX_FEED_ITEMS

from starter.i18n import t

LOGGER = logging.getLogger(__name__)
FEED, TODO_KIND = "follow-ups", "follow-up"


def send_follow_ups(client: Any, notes: list[dict[str, Any]]) -> None:
    """The feed's whole list, sent again after each change."""

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
    key = f"note:{note['note_id']}"
    try:
        if not note.get("follow_up_by"):
            client.close_todos([key])
            return
        client.put_todo(
            {
                "key": key,
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
```

In `NoteService`, after a create or update call `follow_up_todo(...)` and
`send_follow_ups(store.follow_ups())`; after a delete close the to-do
(`client.close_todos([f"note:{note_id}"])`) and send the feed again.

Test:

```python
def test_a_follow_up_goes_to_the_calendar_and_to_the_persons_todo(fake, client):
    body = note(follow_up="2026-11-03", follow_up_by="operator")
    note_id = client.post("/api/notes", json=body).json()["note_id"]
    [item] = fake.links.calendar[("starter", "follow-ups")]
    assert item["start"].startswith("2026-11-03") and item["audience"] == "user:operator"
    todo = fake.links.todos[("starter", f"note:{note_id}")]
    assert todo["kind"] == "follow-up" and todo["for"] == "user:operator"
```
