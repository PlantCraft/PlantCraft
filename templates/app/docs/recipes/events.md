# Events

An event says something happened (a note was written, a run failed). PlantCraft keeps it, the
asset page shows it on its timeline, and Alarms' rules decide whether it becomes an alarm and who
hears it. **Apps report, Alarms judges**: an app never notifies people about its own events.

Every event is declared in `app.toml`, and the code writes it by that name, so a name or a
payload field the manifest lacks fails in your tests.

`app.toml`:

```toml
[permissions]
write = ["audit", "events"]

[[publishes.events]]
name = "note.written"             # sent as starter.note.written
title = "Note written"
description = "An editor wrote a note on an asset."
severity = "info"                 # info, ok, warning, critical
category = "user"                 # process, equipment, data, run, system, user
payload = { note = "Note id" }    # each field and what it holds
```

The SDK sends the catalog to PlantCraft when the app starts. Optional keys (`phase` for a
condition with a start and an end, `rule` for the rule Alarms suggests) are in PlantCraft's
`docs/app-standard.md`, section 6.

`src/starter/suite/events.py`:

```python
"""The events StarterCraft writes, by the names its app.toml declares."""

import logging
from typing import Any

from plantcraft_sdk.client import PlantCraftError
from plantcraft_sdk.events import EventCatalog

from starter.i18n import t
from starter.meta import manifest

LOGGER = logging.getLogger(__name__)


def note_written(client: Any, note: dict[str, Any], asset_name: str) -> None:
    """starter.note.written; never fails the request that wrote the note."""

    if client is None:
        return
    try:
        event = EventCatalog.from_manifest(manifest()).event(
            "note.written",
            f"asset:{note['asset_id']}",
            summary=t("Note on {asset}", asset=asset_name),
            payload={"note": note["note_id"]},
        )
        client.post_events([event])
    except (PlantCraftError, ValueError) as exc:
        LOGGER.warning("Event note.written not written: %s", exc)
```

Call it from the service (`NoteService.create`) through `Suite` ([README.md](README.md)), and
send many events as one list (`post_events`, up to 1,000), never one request each.

Test (the fake PlantCraft keeps what was sent and refuses undeclared events):

```python
def test_writing_a_note_writes_its_event(fake, client):
    client.post("/api/notes", json=note())
    [event] = [item for item in fake.links.events if item["kind"] == "starter.note.written"]
    assert event["subject"] == "asset:FIC-1001" and event["category"] == "user"
```

For the fake to know your catalog, `tests/plant.py` already sends the manifest's contributions
when it starts (`put_contributions(contributions(MANIFEST))`).
