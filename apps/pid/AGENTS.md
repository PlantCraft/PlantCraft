# AGENTS.md: PlantCraft PID, the starting point for an app of your own

This folder is a working app of the PlantCraft suite, made to be copied: **PlantCraft PID**
(`pidcraft`, prefix `/pid/`, port 8160, uid 10016) keeps a note on any asset of the plant.
It has every part a suite app has and nothing else, so an agent (Claude Code or another) can turn
it into a new app in one session and try it inside the platform.

It lives in two places: `templates/app/` of the PlantCraft repository (where CI tests it against
the current SDK and interface) and the app template repository made from it at each release.
Everything below holds in both.

## Where the rules come from

The suite's rules are in the PlantCraft repository
(https://github.com/PlantCraft/PlantCraft): its root `AGENTS.md`, `docs/app-standard.md` (the
app standard: manifest, layout, endpoints, image, suite table) and `docs/testing.md`. This file
repeats the ones an app must follow; when the two differ, PlantCraft's wins and this file is
fixed.

## Start here

1. Read `README.md` (what each file does) and `prompts/README.md` (the prompts to build an app).
2. New app: `make rename NAME=Logbook` once (it becomes LogbookCraft, id `logbook`), then build
   the object and its pages (prompts `02` and `03`), then try it (prompt `04`).
3. `make test-fast` while working, `make ci` before every commit, `make e2e` when you touched a
   page a person uses.
4. Commit messages start with the app id (`logbook: shift entries per unit`); append a line to
   `docs/devlog.md` before you finish.

## Map and layers

```text
app.toml        the manifest: id, name, version, prefix, port, uid, permissions (single source)
src/pid/    the app, in layers (below)
tests/          pytest against FakePlantCraft (no real PlantCraft); tests/e2e: browser journeys
frontend/       Vite + React + TypeScript on @plantcraft/ui, served under /pid/
docs/help/      help pages served at /api/help and shown under Help
vendor/         the plantcraft-sdk wheel and the @plantcraft/ui package (never edited here)
deploy/         requirements.in/.lock: the image's hashed dependencies (`make lock`)
prompts/        prompts for an agent: new app, add an object, add a page, try it, package it
tools/          rename.py (`make rename`)
```

| Layer | Packages (`src/pid/`) | Role |
|---|---|---|
| -1 | `i18n` | `t()`; anything may use it |
| 0 | `config`, `meta` | settings from the environment; `app.toml` and the help pages |
| 1 | `notes` | the app's object: its contract (`NoteDraft`) and its store (`NoteStore`) |
| 2 | `api`, `cli` | FastAPI app under `/pid`, command line |

A new object goes in layer 1 beside `notes` (its own package: contract and store). Methods that
compute something (an analysis on plant signals) go in a layer between the objects and the API.
`tests/test_suite_rules.py` enforces the table: a package imports only from lower layers.

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
- **Every change a person makes is audited** with `Runtime.audit` (action `pidcraft.<noun>.<verb>`).
- **Bad data never crashes.** Wrong input gets a 422 with words a person can act on, a missing
  object a 404, never a 500. `tests/test_suite_rules.py` sends junk to every route.
- **No silent wrong answers.** A result the app cannot compute says so, in words.
- **Offline.** No CDN, web font, telemetry or update check; the interface is built and served by
  the app. `tests/test_suite_rules.py` fails on runtime `http(s)://` fetches.
- **One language source.** Every user-facing string goes through `t()` (`src/pid/i18n.py`,
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
