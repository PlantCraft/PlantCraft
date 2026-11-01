# The server

The server is a FastAPI application built on `plantcraft-sdk` (imported as `plantcraft_sdk`).
The SDK gives every app the same skeleton, so your code holds only your object and its rules.

## What the SDK gives you for free

`create_app()` in `src/starter/api/app.py` calls `web.suite_api(...)` and `web.mount(...)`. With
no code of yours, the app already serves:

| Route | What it is |
|---|---|
| `GET /healthz` | 200 when ready (open, for the container's health check) |
| `GET /api/me` | Who is signed in, their level in this app, the app's version |
| `GET /api/meta` | `app.toml` as JSON, plus the build revision |
| `GET /api/help`, `GET /api/help/{id}` | The help pages of `docs/help/` |
| `GET /api/search`, `GET /api/queue` | Empty answers for the suite's frame until you add your own ([recipes/search.md](recipes/search.md)) |
| `GET /api/docs` | The OpenAPI page, only when `PLANTCRAFT_OPENAPI=1` |
| `/<prefix>...` | The built interface, with the sign-in redirect for a browser without a token |

Every route lives under the app's prefix (`/starter/` in the template) behind PlantCraft's
proxy; `/healthz` also answers at the root.

## Settings

`src/starter/config.py` reads everything from the environment. Each setting has a safe default,
and secrets are never logged.

| Variable | Default | Meaning |
|---|---|---|
| `PLANTCRAFT_URL` | `http://127.0.0.1:8060` | PlantCraft's API, as this server reaches it |
| `PLANTCRAFT_PUBLIC_URL` | same origin | PlantCraft as the browser reaches it (the sign-in page) |
| `PLANTCRAFT_APP_KEY` / `PLANTCRAFT_APP_KEY_FILE` | empty | The app key, for what the app does on its own |
| `STARTER_DATA_DIR` | `var` | The data folder (SQLite database, logs) |
| `STARTER_ROOT_PATH` | `/starter` | The prefix |
| `STARTER_LOG_LEVEL` | `INFO` | Log level (JSON lines to standard error and `logs/` in the data folder) |
| `STARTER_HOST`, `STARTER_PORT` | `127.0.0.1`, `9100` | Where `starter serve` listens |

A setting of your own: add a field to `Settings` and read it in `from_environment()` with the
`STARTER_` prefix. Document it in the docstring table.

## The runtime

`Runtime` (`src/starter/api/runtime.py`) is one server: its settings, its database, its services
and its PlantCraft clients. It extends the SDK's `PlatformRuntime`, which gives:

- `rt.user_client(user)`: a PlantCraft client acting **as the person**. Use it for what a page
  shows, so PlantCraft's own permissions decide what each person sees.
- `rt.service_client`: a client acting **as the app**, with the app key, or `None` when there is
  none (a development run). Use it only for what the app does on its own, from `suite/`.
- `rt.audit(user, action, subject, detail)`: one line in PlantCraft's audit log, as
  `starter.<action>`. It never blocks the change if PlantCraft is down.

Add each new service to `Runtime.__init__` beside `self.notes`. Background work starts in
`start()` and stops in `shutdown()` ([recipes/background.md](recipes/background.md)).

## Who may do what

`src/starter/api/deps.py` builds the checks once:

```python
ACCESS = Access("Starter")  # the app's short name, used in messages
EditorUser = ACCESS.EditorUser  # editors and admins; viewers get 403 with a reason
CurrentUser  # anyone PlantCraft let into the app; 401 without a token
```

A route takes one of them as a parameter. A route with neither would answer without a token:
`tests/test_suite_rules.py` finds it and fails.

```python
@router.post("/notes", status_code=201)
def create_note(draft: NoteDraft, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    name = _asset_name(rt, user, draft.asset_id)
    note = rt.notes.create(draft, user.username)
    rt.audit(user, "note.created", note["note_id"], {"asset": draft.asset_id})
    return {**note, "asset_name": name}
```

`user.username`, `user.name`, `user.can_edit` and `user.is_admin` are there when you need them.

## Reading the plant

Plant data always comes from PlantCraft, read with the person's client:

```python
client = rt.user_client(user)
asset = client.asset("FIC-1001")  # name, type, parent, signals by role
assets = client.assets()  # the asset tree the person may see
signal = client.signal("opcua:FIC-1001.PV")  # one signal: unit, source, description
series = client.series("opcua:FIC-1001.PV", start, end, step=60)  # one mean per minute
```

Wrap a read in `guarded(lambda: ..., service=False)`: a PlantCraft failure becomes an answer the
browser can act on (401, 403, 404, 422 or 502), never a 500. Add the read permission to
`app.toml` (`read = ["assets", "signals", "series"]`); the fake PlantCraft in the tests refuses
a read the manifest does not declare. More in [recipes/signals.md](recipes/signals.md).

## Input, errors and words

- Every body is a pydantic model with `extra="forbid"` and a limit on every field
  (`src/starter/notes/models.py`). FastAPI answers 422 for anything else.
- A missing object is a 404 (`note_or_404`), a refusal a 403, a conflict a 409, with a `detail`
  a person can act on, through `t()`.
- Never let an exception escape as a 500. `tests/test_suite_rules.py` sends junk to every route
  and fails on any 5xx.
- A computation that cannot judge says so ("not enough data in the last hour"), never a number it
  does not trust.

## Adding a route

1. The model in `<object>/models.py`, the rule in `<object>/service.py`, the table in
   `<object>/store.py` ([data.md](data.md)).
2. The route in `api/routers/<object>.py`, with `CurrentUser` or `EditorUser`, and an audit line
   on every change.
3. Register a new router in `create_app()` (`routers=(notes.router, logbook.router)`).
4. A test for the rule, for bad input (422), a missing object (404) and a viewer (403), written
   first. Raise `operations` in `tests/floors.toml` when the junk test reaches more routes.
