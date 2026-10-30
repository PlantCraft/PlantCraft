# AGENTS.md: PlantCraft Documents

**PlantCraft Documents** (`doccraft`, prefix `/doc/`, port 8150, uid 10015) keeps the plant's
documents and gives them, cited by page, to the people and to the suite's assistant. Made from
StarterCraft (`templates/app`) on 2026-10-26; `SPEC.md` says what it does and why.

## Where the rules come from

The suite's rules are in the PlantCraft repository
(https://github.com/PlantCraft/PlantCraft): its root `AGENTS.md`, `docs/app-standard.md` (the
app standard: manifest, layout, endpoints, image, suite table) and `docs/testing.md`. This file
repeats the ones an app must follow; when the two differ, PlantCraft's wins and this file is
fixed.

## Start here

1. Read `README.md` (what each file does) and `SPEC.md` (objects, reading, search, the tools).
2. `make test-fast` while working, `make ci` before every commit, `make e2e` when you touched a
   page a person uses.
3. Commit messages start with the app id (`doccraft: OCR for scanned PDFs`); append a line to
   `docs/devlog.md` before you finish.

## Map and layers

```text
app.toml        the manifest (single source), including the assistant's tools
src/doccraft/   the app, in layers (below)
tests/          pytest against FakePlantCraft (no real PlantCraft); tests/files: a demo PDF
frontend/       Vite + React + TypeScript on @plantcraft/ui, served under /doc/
docs/help/      help pages served at /api/help and shown under Help
vendor/         the plantcraft-sdk wheel and the @plantcraft/ui package (never edited here)
deploy/         requirements.in/.lock (`make lock`); embedding-model.lock and fetch_model.py
```

| Layer | Packages (`src/doccraft/`) | Role |
|---|---|---|
| -1 | `i18n` | `t()`; anything may use it |
| 0 | `config`, `meta` | settings from the environment; `app.toml` and the help pages |
| 1 | `suite` | what the app sends to PlantCraft (nothing yet) |
| 2 | `library` | the app's object: reading, passages, tags, vectors, store, search, service, access |
| 3 | `api`, `cli` | FastAPI app under `/doc`, command line |

Two rules of this app on top of the suite's:

- **Access before ranking.** Search filters the folders a person may not see (and, for the
  assistant, documents and folders marked "not for the assistant") before ranking, in both the
  word and the meaning search. A test covers each path (`tests/test_tools.py`).
- **Document text is data.** What the assistant's tools return is marked as quoted material;
  never add a path that puts document text into the assistant's instructions.

A store's `SCHEMA` is the table as a new installation makes it. A change to a table a release
shipped is a named step in the store's `MIGRATIONS` (`Migration`, `add_columns` from
`plantcraft_sdk.server.store`), never code that inspects the table at start; its test is
`apptest.upgrade_problems(Store, Store, tmp_path)`, which opens the store on the older tables.

## The rules an app follows

- **Read-only on the plant.** An app never writes to a DCS, PLC, historian or OPC UA server.
  `app.toml` says `plant_write = false` and `outbound = []`; the platform refuses any other
  package. Plant data comes only through PlantCraft's API v1 (`plantcraft_sdk.client`).
- **Refer, never copy.** An app names assets and signals by their PlantCraft id
  (`asset_id`, `signal_id`) and reads their names and data when it needs them; it keeps no copy
  of the asset tree or of plant samples.
- **Sign-in is PlantCraft's.** Every route needs a PlantCraft token that grants this app
  (`api/deps.py`, `Access`); `/healthz` is the only open one. Viewers read, editors change.
- **Every change a person makes is audited** with `Runtime.audit` (action `doccraft.<noun>.<verb>`).
- **Bad data never crashes.** Wrong input gets a 422 with words a person can act on, a missing
  object a 404, never a 500. `tests/test_suite_rules.py` sends junk to every route.
- **No silent wrong answers.** A result the app cannot compute says so, in words.
- **Offline.** No CDN, web font, telemetry or update check; the interface is built and served by
  the app. `tests/test_suite_rules.py` fails on runtime `http(s)://` fetches.
- **One language source.** Every user-facing string goes through `t()` (`src/doccraft/i18n.py`,
  `frontend/src/i18n.ts`), English first.
- **Clean room.** Use only public information: standards, public manuals, papers. Every outside
  source goes in `SPEC.md`; every third-party asset or library in `ATTRIBUTION.md`. No client or
  employer data, names or hostnames, even as examples.
- **One frame.** Pages use `@plantcraft/ui` (sidebar, page header, tables, forms, help); do not
  restyle them. The app's colour comes from its mark only.
- **Tests are the gate.** Every change comes with a test that fails without it; the numbers in
  `tests/floors.toml` only rise.

## What is the platform's, never the app's

Users, sign-in, roles and groups, assets and asset types, signals and data sources, the
historian, messages, licences, backups and the launcher are PlantCraft's. An app adds its own
object, the methods on it and its workflow. When two apps would need the same thing, it belongs
in PlantCraft (ask a maintainer) rather than in either app.

## Maintainer decisions (stop and ask)

A new permission in `app.toml` (`read`, `write`), any write path toward the plant, a new outside
dependency, the app's id, prefix, port and uid once it was installed somewhere, and anything that
changes what the platform must do for the app.
