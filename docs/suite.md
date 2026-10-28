# The suite at a glance

> **Updated:** 2026-10-27

PlantCraft is a platform for process engineers: one central app that holds what every module
shares, and a family of modules, each in its own folder of this repository and its own
container, that reach the plant's data only through it. This page is the map; each row links to
the folder that owns the details. Ids, prefixes, ports and container users are assigned once, in the suite table of
[app-standard.md](app-standard.md) (section 7); this page repeats them for reading only.

## Names

Only the platform carries the Craft brand (decision D10, 2026-10-20). A module is **PlantCraft
&lt;name&gt;** in documents, packages and proposals, and just **&lt;name&gt;** inside the suite
(sidebar, launcher); the names people see are in [glossary.md](glossary.md). Ids, images and URL
prefixes keep their `<function>craft` form until the final brand name (BACKLOG D5b), so nothing
breaks when names change.

## Modules

| Module | Folder | id | Prefix | Port | uid | What it does |
|---|---|---|---|---|---|---|
| PlantCraft (platform) | [root](..) | `processcraft` | `/` | 8060 | 10001 | People and access, licences, settings, the asset tree and signal roles, published results and events, messages and specialists, the launcher and the installer; `plantcraft-sdk` and `@plantcraft/ui` |
| PlantCraft Analytics | [`apps/link`](../apps/link) | `linkcraft` | `/link/` | 8140 | 10012 | Checks every signal for bad data and every control loop for oscillation, sticking and manual mode, runs process models (FMUs) beside the plant, and says why |
| PlantCraft Historian | [`apps/historian`](../apps/historian) | `histcraft` | `/hist/` | 8100 | 10008 | The data layer: every plant connection (OPC UA, PI Web API, CSV) and every history, read-only toward the plant |
| PlantCraft View | [`apps/view`](../apps/view) | `dashcraft` | `/dash/` | 8080 | 10006 | Dashboards, scheduled reports and saved trends of any signal, shared with people or by a public link |
| PlantCraft Alarms | [`apps/alarms`](../apps/alarms) | `alarmcraft` | `/alarm/` | 8110 | 10009 | Alarm limits on plant signals, the alarm summary and alarm performance against ISA-18.2 |
| PlantCraft Models | [`apps/models`](../apps/models) | `modelcraft` | `/model/` | 8130 | 10011 | A Modelica workbench: write and draw models, simulate them on plant data and export FMUs |
| PlantCraft Documents | [`apps/documents`](../apps/documents) | `doccraft` | `/doc/` | 8150 | 10015 | The plant's manuals, control narratives, datasheets and guides: read into passages, searched by words and by meaning offline, linked to the assets, and cited by the assistant |
| PlantCraft Simulator | [`simulator`](../simulator) | `simcraft` | OPC UA `:4840` | 4840 | 10004 | The simulated plant behind the demo and the benchmarks (50 loops with known faults) |

Retired ids, kept reserved so no new app takes them: `cpmcraft` and `datacraft` merged into
Analytics (D9); `twincraft` (PlantCraft Twin) merged into Analytics on 2026-10-22: its twins are
algorithms on assets there and `/twin/` opens them.

## How the pieces fit

```text
                    browser
                       |
                    proxy (HTTPS, the only published port)
       ________________|_______________________________________________
      |            |          |        |         |          |
 PlantCraft   Analytics     View    Alarms    Models    Documents     each: own folder, own image,
   (central)                                                          own database in /data
      |  API v1 (signed tokens, app keys, results, events, runs)
      |
  Historian  ---- reads ---->  plant systems (OPC UA, PI Web API, CSV): read-only, never writes
```

- **One place for what modules share.** People, access, assets, signal roles, results and events
  live in the platform once ([architecture.md](architecture.md)).
- **Modules never talk to each other.** They publish results and events in PlantCraft and read
  what others published there ([api-v1.md](api-v1.md)).
- **Everything repeated is written once.** The server skeleton, store, access checks, test kit and
  SBOM are `plantcraft-sdk` (`sdk/python`); the frame, help browser, API client and pickers are
  `@plantcraft/ui` (`ui/`). A module keeps only its own objects, methods and workflow.

## Shared code and versions

| Package | Where | What it gives every module |
|---|---|---|
| `plantcraft-sdk` | `sdk/python` | API v1 client (people, groups, notifications, results, events, runs), token checks, `@method`, blocks and algorithms (`blocks`: contract, diagram checks and runs, descriptions), compute tasks, `plantcraft-app` (check, sbom), `server` (web app, store, access, files, JSON logs, ops metrics), test kit (`apptest`, `testplant`, `e2e`, time budget) |
| `@plantcraft/ui` | `ui/` | The suite frame (sidebar, Apps, Queue, search, user menu, the assistant on every page), help browser (`AppHelp`), API client (`createApiClient`), source, signal, asset and people pickers, `DataTable`, Overview widgets, time chart, block diagram editor (`BlockEditor`), base styles |

Both are published on no index: each module vendors the exact files in `vendor/` with their
SHA-256 sums, and PlantCraft's `dev/revendor` moves every module to a new version at once. The
current versions are in `sdk/python/pyproject.toml` and `ui/package.json`.

## Where to read next

- [How we build](how-we-build.md): what the platform is for, how we think, and why it is built
  with AI in the open.
- [The app standard](app-standard.md): what every module follows.
- [Testing](testing.md): one test layout and time budget for every module.
- [Working with Claude Code](claude-code.md): the commands and prompts we use.
- [Contributing at scale](contributing-at-scale.md): many people and agents in parallel, without
  conflicts.
