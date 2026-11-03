# Widgets

Widgets are small cards PlantCraft draws on its Overview and on Desk's Today, from data your app
answers. Each widget has one of the suite's shapes (`number`, `list`, `series`, `facts`,
`split`), built by `plantcraft_sdk.widgets`. PlantCraft's `docs/widgets.md` lists them all.

`app.toml`:

```toml
[[contributes.widgets]]
id = "count"
title = "StarterCraft: notes"
description = "How many notes there are."
size = "s"
kind = "number"
default = true                # on a new Overview without anyone adding it

[[contributes.widgets]]
id = "latest"
title = "StarterCraft: latest notes"
description = "The newest notes, each one click away."
size = "m"
kind = "list"
```

`src/starter/api/routers/widgets.py`:

```python
"""StarterCraft's widgets, for PlantCraft's Overview and Desk's Today."""

from typing import Any

from fastapi import APIRouter, HTTPException
from plantcraft_sdk import widgets as w

from starter.api.deps import CurrentUser, RuntimeDep
from starter.i18n import t
from starter.meta import FILES

router = APIRouter(prefix="/api/widgets")


@router.get("")
def widgets(_user: CurrentUser) -> dict[str, Any]:
    return w.catalog(FILES.manifest(), t)


@router.get("/{widget_id}")
def widget(widget_id: str, rt: RuntimeDep, _user: CurrentUser) -> dict[str, Any]:
    root = rt.settings.root_path
    notes = rt.notes.list()
    if widget_id == "count":
        return w.number(len(notes), label=t("notes"), href=f"{root}/notes")
    if widget_id == "latest":
        return w.items(
            [
                w.item(
                    note["text"][:80],
                    detail=note["asset_id"],
                    href=f"{root}/notes/{note['note_id']}",
                )
                for note in notes[:8]
            ],
            href=f"{root}/notes",
            empty=t("No note yet."),
        )
    raise HTTPException(status_code=404, detail=t("Widget not found."))
```

Add `widgets.router` to `routers=` in `api/app.py` and the new strings to the catalog.

Test (checks every declared widget answers in its declared shape):

```python
from plantcraft_sdk import apptest


def test_the_widgets_answer_in_the_shapes_app_toml_declares(client):
    client.post("/api/notes", json=note())
    assert apptest.widget_problems(client, "") == []
    assert client.get("/api/widgets/count").json()["value"] == 1
```
