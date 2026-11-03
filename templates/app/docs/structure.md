# Structure

```text
app.toml              the manifest: id, name, version, prefix, port, permissions (single source)
pyproject.toml        the Python package and its dependencies
Makefile              every command: ci, dev, serve, rename, image, package
Dockerfile            the image: three stages, hashed dependencies, non-root, read-only root
src/starter/          the server (Python, FastAPI on plantcraft-sdk)
frontend/             the interface (Vite, React, TypeScript on @plantcraft/ui)
tests/                pytest against a fake PlantCraft; tests/e2e: browser journeys
docs/                 this documentation, the help pages (docs/help) and the app's own notes
vendor/               the plantcraft-sdk wheel and the @plantcraft/ui package, with their hashes
deploy/               requirements.in and requirements.lock: the image's pinned dependencies
prompts/              prompts for a coding agent: new app, add an object, add a page, try, package
tools/rename.py       make rename
.github/workflows/    ci.yml: make ci on every push and pull request
AGENTS.md, CLAUDE.md  the rules, for people and for coding agents
SPEC.md, ROADMAP.md   what the app does and its public sources; what comes next
CHANGELOG.md          what changed in each version
SECURITY.md, LICENSE, ATTRIBUTION.md   how to report a flaw, the licence, third-party credits
```

## The server: `src/starter/`

| File | What it does |
|---|---|
| `__init__.py` | `APP_ID` and `__version__` |
| `i18n.py`, `locales/` | `t()` and the server's translations ([translations.md](translations.md)) |
| `config.py` | `Settings`: every setting from the environment, each with a safe default |
| `meta.py` | Reads `app.toml` and the help pages for `/api/meta` and `/api/help` |
| `notes/models.py` | `NoteDraft`: what a person may send, with every limit |
| `notes/store.py` | `NoteStore`: the `notes` table in the app's SQLite database |
| `notes/service.py` | `NoteService`: the rules of the object, without HTTP |
| `api/runtime.py` | `Runtime`: one server's settings, database, services and PlantCraft clients |
| `api/deps.py` | Who may do what (`CurrentUser`, `EditorUser`) and shared checks (`note_or_404`) |
| `api/routers/notes.py` | The HTTP routes of the notes |
| `api/app.py` | `create_app()`: the suite's standard endpoints plus your routers and the built interface |
| `cli.py` | `starter serve` and `starter check` |

### Layers

The code is in layers, and a package imports only from layers below it. `tests/test_suite_rules.py`
holds the table and fails on an import that points up.

| Layer | Packages | Role |
|---|---|---|
| -1 | `i18n` | `t()`; anything may use it |
| 0 | `config`, `meta` | settings, the manifest, the help pages |
| 1 | `suite` | what the app sends to PlantCraft on its own (events, Desk, a model); empty in the template, see [recipes/](recipes/README.md) |
| 2 | `notes` | the app's object: contract, store, service |
| 3 | `api`, `cli` | the entry points |

A second object goes beside `notes`, in its own package with the same three files. Code that
computes something from plant signals (a method) goes in a package between the objects and the
API; add it to `LAYERS` in `tests/test_suite_rules.py`.

Within the API, routers stay thin: they check the input and the person, call the service and
answer. Only the service touches the store, and only `suite/` sends anything to PlantCraft for
the app (a page that reads plant data as the person stays in its router).

## The interface: `frontend/src/`

| File | What it does |
|---|---|
| `main.tsx` | Starts the app: theme, language, the frame |
| `App.tsx` | The frame (`SuiteShell`) and the routes: which page each path shows |
| `pages.tsx` | `NAV` (the sidebar) and the guided tour |
| `NotesPage.tsx` | The pages of the notes: list with the form, one note, one asset's notes |
| `SuitePages.tsx` | The help page, the same in every app |
| `api.ts` | Every call to the server, typed |
| `types.ts` | The shapes the server sends |
| `nav.ts` | Paths under the app's prefix, `Link`, `navigate` |
| `i18n.ts`, `locales/` | `t()` and the interface's translations |
| `ui.tsx` | The shared blocks the pages use, in one import |
| `*.test.ts(x)` | Vitest tests |

## Tests: `tests/`

| File | What it checks |
|---|---|
| `plant.py`, `conftest.py` | A fake PlantCraft with a small plant and four people; a runtime and a client wired to it |
| `test_notes.py` | The object: create, change, delete, limits, who may do what |
| `test_app_standard.py` | `app.toml` agrees with the code; the standard endpoints answer |
| `test_suite_rules.py` | Offline, layers, thin routers, junk never answers 500, no route without a token, the image |
| `test_rename.py` | `make rename` leaves no trace of the template's name |
| `floors.toml` | Numbers that only rise (API operations under test) |
| `e2e/` | Browser journeys with Playwright (`make e2e`) |
