# References in messages

People write `#asset:FIC-1001` in PlantCraft's messages and it becomes a link. An app can add
its own kind, so `#starter_note:<id>` opens one of your notes: PlantCraft asks your app what it
names, as the person reading, and shows the title and state.

`app.toml`:

```toml
[[contributes.refs]]
kind = "starter_note"            # <app id>_<object>
title = "Note"
url = "/starter/notes/{id}"
```

`src/starter/api/routers/refs.py`:

```python
"""What a #starter_note:<id> names, for the person asking."""

from typing import Any

from fastapi import APIRouter

from starter.api.deps import CurrentUser, RuntimeDep, note_or_404

router = APIRouter()
KIND = "starter_note"


@router.get(f"/api/refs/{KIND}/{{note_id}}")
def note_ref(note_id: str, rt: RuntimeDep, _user: CurrentUser) -> dict[str, Any]:
    note = note_or_404(rt, note_id)
    return {"title": note["text"][:80], "status": None, "url": f"/starter/notes/{note['note_id']}"}
```

Add `refs.router` to `routers=` in `api/app.py`. The interface needs a route for
`/notes/<id>`, which the template already has.

Test:

```python
def test_a_reference_names_the_note_for_whoever_reads_it(runtime, fake, client):
    note_id = client.post("/api/notes", json=note()).json()["note_id"]
    with client_for(runtime, fake, "operator") as operator:
        ref = operator.get(f"/api/refs/starter_note/{note_id}")
        assert operator.get("/api/refs/starter_note/nowhere").status_code == 404
    assert ref.json()["url"] == f"/starter/notes/{note_id}"
```
