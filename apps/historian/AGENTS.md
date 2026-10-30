# AGENTS.md: PlantCraft Historian

**Read the suite's rules first**: the repository's root `AGENTS.md` (`../../AGENTS.md`), the single
source of rules for the platform and every app. This file adds only
what is particular to PlantCraft Historian; where the two differ, ask a maintainer which one wins and fix the other.

This folder is **PlantCraft Historian** (`histcraft`, prefix `/hist/`, port 8100, uid 10008):
The suite's data layer: every plant connection and every history, read-only toward the plant.

## Start here

1. `git status`, `git log origin/main..HEAD`, open PRs; then `docs/STATUS.md`, `docs/gaps.md`,
   `ROADMAP.md` and `SPEC.md` of this folder.
2. `make test-fast` while working, `make ci` before every push, `make e2e` when you touched a user
   journey (the same commands in every folder: PlantCraft `docs/claude-code.md`).
3. Commit messages start with `histcraft: `; append a line to `docs/devlog.md` before you finish.

## Map and layers

This folder:

```text
src/histcraft/  the app (layers below); tests/ (pytest, against FakePlantCraft and a test OPC UA server)
frontend/       Vite + React + TypeScript, served under /hist/ (base path in vite.config.ts)
vendor/         the plantcraft-sdk wheel PlantCraft Historian pins (never edited here; SHA256 in its README)
deploy/         requirements.in/.lock (hashed dependencies of the image), compose snippet for the suite
```

| Layer | Packages (`src/histcraft/`) | Role |
|---|---|---|
| -1 | `i18n` | `t()`; anything may use it |
| 0 | `db`, `config`, `meta`, `vault` | `Database`/`Store` (PostgreSQL or SQLite), settings from the environment, encrypted source passwords |
| 1 | `archive`, `catalog`, `sources` | compression, chunk codec, archive store and reads; sources, points, settings; history read from PI Web API, OPC UA HA and CSV (`sources.history.open_source`) |
| 2 | `collector` | OPC UA live reader and the collection loop |
| 3 | `api`, `cli`, `bench` | FastAPI app under `/hist`, command line, benchmark |

- **PlantCraft Historian is the suite's data layer** (`docs/boundary.md`, `docs/data-layer.md`): the only
  component that talks to plant systems, always **read-only** (PI Web API GET only; OPC UA Read,
  Browse and HistoryRead only; `tests/test_read_only.py`). Never add a write path to PI, OPC UA,
  a DCS or a PLC; derived series stay in PlantCraft Historian.
- **Who writes what:** the server writes the configuration and apps' derived series
  (`POST /api/v1/data/derived` only); the collector writes collected values
  (`tests/test_suite_rules.py`). In plants both live in one PostgreSQL database
  (`HISTCRAFT_DATABASE_URL`); without it, two SQLite files (tests, demos). Stores write one SQL
  both engines run (`db.py` translates the rest), and `make test-postgres` runs every test on
  PostgreSQL (CI job `postgres`).
- **Passwords** of sources are encrypted with `vault.Vault` (key file outside the database),
  never logged, never sent back to a page or to PlantCraft.
- **Apps read data only through the PlantCraft API v1** (`docs/api-v1.md`) with a signed token
  they verify offline; they never call PlantCraft Historian directly. PlantCraft Historian's `/api/v1/data` routes
  accept only PlantCraft's own token (`sub: app:processcraft`).
- **Every change a person makes** is recorded in PlantCraft's audit log with their own token
  (`POST /api/v1/audit`, `Runtime.audit`). PlantCraft Historian has no background work against PlantCraft,
  so it needs no app key.

The layer table is enforced by `tests/test_suite_rules.py` (`plantcraft_sdk.apptest`).

## This module's own rules

- **Bad data never crashes.** NaN, bad quality, a dead or slow server, a malformed node id, junk
  query parameters: the collector archives a "no data" marker and keeps going, every route
  answers 4xx with a reason, never a 500. Unfinished features are hidden in the UI.
- **Never invent values.** The archive is never bridged across a gap (lost connection, bad
  quality, collector stopped), and nothing is rebuilt after the newest value read.
- **Each table is owned by one module** (a `Store` with its `SCHEMA`). Columns are added with a
   guarded `ALTER TABLE`; never edit existing rows by hand. The chunk format
   (`archive/codec.py`) is versioned by its first byte: a new format is a new byte, and old
   chunks stay readable.
- **No outbound network by default.** No CDN, web fonts, telemetry, update checks or analytics.
  Fonts and scripts are bundled. The only outbound connections are PlantCraft (signing keys,
  audit) and the OPC UA servers an admin configures, from the collector only.
  `tests/test_suite_rules.py` fails on any `http(s)://` fetched at runtime that is not configured.
- Tests talk to `plantcraft_sdk.testing.FakePlantCraft`, never to a real PlantCraft, and to
  the small OPC UA server in `tests/opcua_server.py`.
- Performance is a feature: `python -m histcraft.bench --points 2000 --seconds 1800` must not
  regress more than 20% (last measured in `docs/devlog.md`).

## Oracles and floors

PlantCraft Historian's oracle is not written yet (`docs/gaps.md`): a
PlantCraft Simulator dataset archived and read back, every value within its point's deviation.
