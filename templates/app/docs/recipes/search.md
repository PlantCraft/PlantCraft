# Search (Ctrl+K)

The suite's search box asks every app `GET /api/search?q=` and groups the answers. The SDK
answers "nothing" for an app without its own route; this adds yours.

`app.toml`:

```toml
[contributes.search]
types = ["Note"]
```

`src/starter/api/routers/search.py`:

```python
"""StarterCraft's part of the suite's search (Ctrl+K): its notes, by text or asset."""

from typing import Any

from fastapi import APIRouter, Query
from plantcraft_sdk.server.search import SearchItem, matches, search_answer, search_text

from starter.api.deps import CurrentUser, RuntimeDep
from starter.i18n import t

router = APIRouter()


@router.get("/api/search")
def search(
    rt: RuntimeDep,
    _user: CurrentUser,
    q: str = Query("", max_length=120),
    limit: int = Query(6, ge=1, le=20),
) -> dict[str, Any]:
    text = search_text(q)
    if not text:
        return search_answer([])
    found = [
        SearchItem(
            note["text"][:80], f"/notes/{note['note_id']}", type=t("Note"), detail=note["asset_id"]
        )
        for note in rt.notes.list()
        if matches(text, note["text"], note["asset_id"])
    ]
    return search_answer(found, text, limit=limit)
```

Add `search.router` to `routers=` in `api/app.py` (before the SDK's own fallback, which it
does by itself), and `"Note"` to `src/starter/locales/pt-BR.json`.

Test:

```python
def test_the_suite_search_finds_notes(client):
    client.post("/api/notes", json=note())
    found = client.get("/api/search", params={"q": "valve"}).json()
    assert [item["href"] for item in found["items"]][0].startswith("/notes/")
    assert client.get("/api/search", params={"q": "pump"}).json()["items"] == []
```

For a large table, search in SQL (`WHERE text LIKE ?`) with a limit instead of listing all rows.
