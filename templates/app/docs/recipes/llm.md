# A language model

An app never holds a model key and never calls a model provider. It declares a **use**, and
PlantCraft (where an administrator chose a model for that use in Setup > Language models) sends
the text and returns the answer. Every use is off until an administrator turns it on, and the
page says so in words while it is off.

`app.toml`:

```toml
[permissions]
write = ["audit", "llm"]

[[contributes.llm]]
id = "summary"
title = "Summarise a note"
reads = "The text of one note."     # what the model gets to see, shown to the administrator
default = "off"
```

`src/starter/suite/llm.py`:

```python
"""StarterCraft's one use of a language model, summary."""

from typing import Any

from plantcraft_sdk.client import PlantCraftError

USE = "summary"
SYSTEM = "Summarise the operator's note on a plant asset in one short sentence."


class NoModel(Exception):
    """No model for this use now (off, or none set up), or no app key."""


def summary(client: Any, text: str) -> str:
    if client is None:
        raise NoModel("This installation gave StarterCraft no app key.")
    try:
        return str(client.llm(USE, text, system=SYSTEM)["text"])
    except PlantCraftError as exc:
        if exc.status_code in (404, 409):
            raise NoModel(str(exc)) from exc
        raise
```

The route answers 409 with words while there is no model, and 502 when PlantCraft fails:

```python
@router.post("/notes/{note_id}/summary")
def summarise_note(note_id: str, rt: RuntimeDep, _user: CurrentUser) -> dict[str, Any]:
    note_or_404(rt, note_id)
    try:
        return {"note_id": note_id, "summary": rt.notes.summary(note_id)}
    except NoModel as exc:
        raise HTTPException(
            409, t("No language model for summaries: an administrator chooses one in Setup.")
        ) from exc
    except PlantCraftError as exc:
        raise HTTPException(502, t("PlantCraft did not answer: {error}", error=str(exc))) from exc
```

Send the model only what `reads` says, and treat its answer as a suggestion a person checks:
never let it change data on its own.

Test (`fake.links.llm_answer` is what the fake model answers; `None` is "off"):

```python
def test_the_summary_comes_from_the_model_plantcraft_gives_the_use(fake, client):
    note_id = client.post("/api/notes", json=note()).json()["note_id"]
    fake.links.llm_answer = "The valve sticks at low opening."
    answer = client.post(f"/api/notes/{note_id}/summary")
    assert answer.json()["summary"] == "The valve sticks at low opening."


def test_without_a_model_the_summary_says_so(fake, client):
    note_id = client.post("/api/notes", json=note()).json()["note_id"]
    fake.links.llm_answer = None
    assert client.post(f"/api/notes/{note_id}/summary").status_code == 409
```
