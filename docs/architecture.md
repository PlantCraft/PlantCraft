# Architecture

PlantCraft is one **platform** and a set of **apps** on top of it. The platform holds what every
app shares (people, the plant's assets and signals, the assistant, Desk, Notebooks, messages, and
the results and events the apps publish). Each app keeps only its own objects, methods and
workflow, runs in its own container and talks to the platform through one contract, API v1. A new
app, official or yours, plugs in the same way.

## The suite in one picture

```mermaid
flowchart TB
    people(["People, in a browser"])
    proxy["HTTPS proxy<br/>the only published port"]

    subgraph platform["PlantCraft platform (this repository's root)"]
        direction LR
        core["People, sign-in and access<br/>Assets and signals<br/>Results, events, runs<br/>Messages and notifications"]
        own["Desk (each person's day)<br/>Notebooks<br/>Assistant on every page<br/>Apps and updates"]
    end

    subgraph apps["Apps (apps/&lt;app&gt;, one container each)"]
        direction LR
        historian["Historian<br/>plant connections and history"]
        analytics["Analytics<br/>signal quality, loops,<br/>blocks and algorithms"]
        view["View<br/>dashboards, Process diagrams,<br/>reports, trends"]
        alarms["Alarms<br/>ISA-18.2 rules and alarms"]
        models["Models<br/>Modelica, studies, FMUs"]
        documents["Documents<br/>manuals, P&amp;IDs, procedures"]
        yours["Your app<br/>from templates/app"]
    end

    plant[("Plant systems<br/>OPC UA, PI Web API, MQTT,<br/>Modbus TCP, SQL, CSV")]

    people --> proxy
    proxy --> platform
    proxy --> apps
    apps <-->|"API v1: signed tokens, app keys"| platform
    historian -->|"reads only, never writes"| plant
```

- **The platform is the hub; apps are the spokes.** Apps never call each other. Each one
  publishes results and events in PlantCraft and reads what the others published there.
- **The Historian is the data layer.** It is the only app that connects to the plant, and only to
  read. The other apps read signals' history through PlantCraft or straight from the Historian,
  with the same access rules.
- **The same frame everywhere.** Every app uses `@plantcraft/ui` (sidebar, search, help, the
  assistant, pickers, tables and charts) and `plantcraft-sdk` (server, store, access checks,
  tests), so the suite reads as one product.

## How the apps talk: one sticky valve

A control valve starts sticking. This is how the apps find it, without one importing another:

```mermaid
sequenceDiagram
    autonumber
    participant Plant as Plant (OPC UA, PI)
    participant Hist as Historian
    participant An as Analytics
    participant PC as PlantCraft
    participant Al as Alarms
    participant Vi as View
    participant Who as Engineer

    Hist->>Plant: read the loop's PV, SP and OP (read-only)
    An->>Hist: series of the loop's signals (API v1)
    An->>An: run the loop's algorithm (blocks): stiction found
    An->>PC: publish a result on asset FIC-1003 (warning, score, one sentence)
    PC-->>Al: the result is readable by every app
    Al->>PC: a rule on that result raises an alarm, sends an event
    PC->>Who: a notification in Messages and on Desk
    Vi->>PC: the asset's status on the dashboard and the Process diagram
    Who->>PC: asks the assistant "why is FIC-1003 red?"
    PC-->>Who: answer from the result, the trend and the valve's manual (Documents)
```

What each step uses:

| Step | Contract | Where it is written |
|---|---|---|
| Sign-in for every app | Short-lived Ed25519 tokens, checked offline against `/api/v1/keys` | [api-v1.md](api-v1.md) |
| Work in the background | App keys issued by an administrator | [api-v1.md](api-v1.md) |
| Signals and their history | `signal:<source>:<tag>` references, `POST /api/v1/series` | [app-standard.md](app-standard.md), section 2 |
| Findings about the plant | Results on assets and signals (`ok`, `warning`, `alarm`, `unknown`) | [app-standard.md](app-standard.md), section 6 |
| Things that happened | Events, declared in each app's `app.toml` | [app-standard.md](app-standard.md), section 4 |
| What an app adds to the platform | `[contributes]` in `app.toml`: assistant uses, Desk widgets, calendar, to-dos, search, settings | [app-standard.md](app-standard.md), section 4b |

## Core and extensions

What is the base, and what is meant to grow:

| Layer | What it is | Folders | Changes |
|---|---|---|---|
| **Core** | The platform, the contract and the shared code every app depends on | `processcraft/`, `frontend/`, `sdk/python/`, `ui/`, `docs/api/v1/`, `deploy/`, `.github/`, `ci/` | Additive only, after an issue agreed with a maintainer ([CONTRIBUTING.md](../CONTRIBUTING.md#what-is-core-and-what-is-open)) |
| **Official apps** | The apps shipped with the suite | `apps/<app>/` | Inside one app, with that app's tests; never reaching into another app or the core |
| **Content** | Methods, blocks, algorithms, alarm rule templates, model libraries, notebook examples, translations, documentation | inside the app that owns them, `docs/` | The most welcome contributions, from public references |
| **Your apps** | Apps for one process, client or research topic | your own repository, from [`templates/app`](../templates/app) | No pull request here: they build on the published SDK and install as a signed package |

## Inside the platform

The rest of this page explains how the platform's own code is split and the rules that keep it
that way. The platform is a Python package (`processcraft/`, the name before PlantCraft) with a
FastAPI backend and a React + TypeScript frontend (`frontend/`); its state lives in one local
SQLite database.

## Philosophy

- **One place for what every app shares.** People and their access, data
  sources, signals and the asset tree live here once; an app never keeps its
  own copy of the plant or its own user directory.
- **Apps talk through a contract.** API v1 (`docs/api-v1.md`) is the only way
  an app reaches PlantCraft, and `sdk/python` (`plantcraft-sdk`) is the
  only code apps import from it. PlantCraft never imports an app.
- **PlantCraft never writes to the process.** It reads the plant's
  historians; it never writes to a controller.
- **Offline and on premises.** No outbound network beyond the data sources an
  administrator configures (`tests/test_offline.py`).

## Layers

Code is split into modules that only import downward: a module may import from
its own package or from a lower layer, never from a higher one. Modules in the
top layer may import each other. `tests/test_architecture.py` enforces this and
fails on any violation; its `LAYERS` table and the one below must agree. Its
`MOVED` table lists the packages that left for the apps; nothing may import
them again.

| Layer | Modules | Role |
| --- | --- | --- |
| 0 | `db`, `config`, `refs`, `i18n`, `files` | Shared SQLite store and scenarios; `kind:id` references; interface language and translation catalogs; files written whole, created with their final mode |
| 1 | `industrial_data`, `auth`, `assets`, `events`, `audit`, `apps`, `results`, `compute`, `groups`, `notebooks`, `installation` | Data sources (CSV, PI Web API, OPC UA) and the history cache; people, access, token keys, app keys and the suite's apps; asset tree; events; central audit log; signed app packages, the installer service and the Apps page's logic; the results, runs and schedules the apps publish; the compute workers and the queue of tasks the apps hand them; groups of people; the notebooks switch and the notebooks written for each person; the installation's time zone (Settings › Installation) |
| 2 | `platform`, `notify`, `desk` | Workspace (the stores), source registry, scenario loops as assets, plant map import and export; the apps' notifications to people (Messages and the email outbox); Desk, each person's day (to-dos, own events, followed assets, calendars) |
| 3 | `api`, `cli` | HTTP (the interface's `/api` and API v1), command line |

The demo plant is the Simulator, its own product (`simcraft loops serve`, namespace
`urn:processcraft:plantcraft`): PlantCraft reads it over OPC UA like any other server and
never imports it. `processcraft/simulator` moved there (gap G31, closed 2026-10-19).

Each module owns its tables: a `Store` subclass (`processcraft/db.py`) with a
`SCHEMA` string. A change to a table a release already shipped is a named step in
the store's `MIGRATIONS` (`Migration`, `add_columns` from `plantcraft_sdk.server.store`):
each runs once per database and is recorded in `sdk_migrations`, so an installation that
skipped releases runs every step it missed, in order. `tests/test_upgrade_schema.py` opens
the schema of every published release (`tests/schemas/`) and expects today's tables. A database from the
monolith opens as is: the tables of the removed modules stay untouched.

```mermaid
flowchart TB
    UI["Frontend<br/>React + TypeScript"]
    Apps["Apps of the suite<br/>Analytics, Historian, View, ..."]
    API["api<br/>/api and /api/v1"]
    Platform["platform<br/>workspace, sources, loops, plant map"]
    Auth["auth, audit<br/>people, tokens, app keys"]
    Assets["assets<br/>asset tree"]
    Data["industrial_data<br/>OPC UA, PI Web API, CSV, history cache"]
    DB["db<br/>SQLite"]

    UI -->|"HTTP / JSON, session"| API
    Apps -->|"API v1, tokens"| API
    API --> Platform
    API --> Auth
    Platform --> Assets
    Platform --> Data
    Auth --> DB
    Assets --> DB
    Data --> DB
```

## The apps of the suite

- `PLANTCRAFT_APPS` lists the apps installed beside PlantCraft
  (`linkcraft=/link/@0.1.0,...`, `processcraft/auth/suite.py`). The launcher on
  the home page shows each one, locked for a person whose access does not
  include it.
- A person signs in here. PlantCraft issues a short-lived Ed25519 token
  (`processcraft/auth/tokens.py`) and keeps it fresh in the
  `processcraft_token` cookie; an app verifies it offline against
  `/api/v1/keys`.
- Background work (Analytics' schedules) uses a service token obtained with an
  app key (`processcraft/auth/app_keys.py`), which an admin issues under
  **Settings → Users and app keys**.
- Every write an app makes through API v1, and every app key change, is
  recorded in the central audit log (`processcraft/audit`).
- Apps link only through PlantCraft (`docs/app-standard.md`, section 6):
  they publish **results** about assets and signals and **events**, and
  report their **runs** and **schedules** (`api/routers/v1_links.py`, stored
  by `processcraft/results` and `processcraft/events`). The Executions page
  shows every app's runs and schedules, read-only.
- A person's apps may name an app by its id (`linkcraft`) or by the module it
  grew from inside the monolith (`cpm`), so access granted before the split
  keeps working (`FORMER_IDS`).

## Loops

PlantCraft does not analyse loops; it describes them. A loop is an asset of
kind `loop` whose signals carry roles (`pv`, `sp`, `op`, `mode`, `secondary`).
They come from three places, each with its own origin:

- the scenario file's `loops` (origin `scenario`, kept in step by
  `processcraft/platform/loops.py` at every start);
- the plant map's `loops` sheet (origin `map`);
- a person, in the asset tree (origin `manual`, never changed by a sync).

Analytics reads every loop asset with its signals through `GET /api/v1/assets`.
The loop's analysis settings (algorithm, criticality, enabled methods) are
Analytics': the map ignores those columns with a warning.

## Data sources

Connectors in `processcraft/industrial_data` (OPC UA Historical Access, PI Web
API, CSV) implement `read_window` and `read_range`, normalize timestamps to the
scenario time zone, isolate failures per tag and return a wide `DataFrame`
indexed by time. Reads go through a local history cache in SQLite, and each tag
is read from the source that owns it. On start, PlantCraft fills the cache
for the last 48 hours of the scenario's signals in the background
(`PLANTCRAFT_PREWARM_HISTORY`).

## Interface language

English is the source language of every user-facing string; Brazilian
Portuguese is a translation. The backend uses `t()` from `processcraft.i18n`,
the frontend `t()` from `frontend/src/i18n.ts`, and the English text is the
catalog key.

## Anti-patterns

- PlantCraft importing an app, or naming one outside `auth/suite.py`.
- An app reaching the database or a source directly instead of API v1.
- A second copy of a contract (`_v2`) instead of an additive change.
- Analysis code (methods, scores, diagnoses) coming back into PlantCraft:
  it belongs to an app.

## Acceptance checklist for a change

- Which layer owns the logic, and which store owns its table?
- Does it change API v1? Then `docs/api-v1.md`, the contract tests and
  `FakePlantCraft` change in the same commit, additively.
- Can it be tested without the frontend and without a live data source?
- Does `make ci` pass?
