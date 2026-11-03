# Recipes

The template has only what every app needs. Each recipe adds one more thing, with the lines for
`app.toml`, the code and a test. The code is written for the notes; change the names to your
object. Most of it comes from an earlier, larger version of this template (StarterCraft before
0.2.0), where it ran under the same tests.

| Recipe | Adds |
|---|---|
| [search.md](search.md) | Your objects in the suite's search (Ctrl+K) |
| [widgets.md](widgets.md) | Widgets for PlantCraft's Overview and Desk's Today |
| [events.md](events.md) | Events Alarms can turn into alarms, and the asset page shows |
| [desk.md](desk.md) | Items on Desk's calendar and to-dos for a person |
| [llm.md](llm.md) | A use of a language model, through PlantCraft |
| [refs.md](refs.md) | `#<kind>:<id>` references in messages that open your object |
| [signals.md](signals.md) | Reading assets, signals and time series from PlantCraft |
| [results.md](results.md) | Publishing a result (a status) on an asset for other apps and the asset page |
| [background.md](background.md) | Work the app does on its own, on a schedule |

## Where the code goes

Things PlantCraft *asks your app for* (search, widgets, references) are routes in
`api/routers/`. Things your app *sends to PlantCraft on its own* (events, Desk, results, model
calls) go in a `suite/` package, the only code that uses the app key:

```text
src/starter/suite/__init__.py    class Suite: one method per thing the app sends
src/starter/suite/events.py      one module per kind (events, desk, llm, results)
```

```python
# src/starter/suite/__init__.py
"""The only place the app talks to PlantCraft on its own behalf (with the app key)."""

from collections.abc import Callable
from typing import Any

from starter.suite import events


class Suite:
    def __init__(self, client: Callable[[], Any]):
        self._client = client  # answers the service client, or None without an app key

    def note_written(self, note: dict[str, Any], asset_name: str) -> None:
        events.note_written(self._client(), note, asset_name)
```

Wire it once in `Runtime.__init__` and give it to the services that need it:

```python
self.suite = Suite(lambda: self.service_client)
self.notes = NoteService(NoteStore(self.db), self.suite)
```

`suite` is layer 1 in `tests/test_suite_rules.py` (already in `LAYERS`), below the objects, so a
service may call it and it never imports a service. Without an app key (a development run)
every function returns without sending and nothing fails: the person's change is still saved.

Every recipe that writes to PlantCraft needs its permission in `app.toml` `[permissions] write`
(`events`, `results`, `llm`); every read its permission in `read`. The fake PlantCraft in the
tests refuses what is not declared.
