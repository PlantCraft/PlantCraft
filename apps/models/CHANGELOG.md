# Changelog

Every release of PlantCraft Models, newest first, in the
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) form. PlantCraft's `deploy/bundle.sh`
joins it into the bundle's release notes.

## [Unreleased]

### Added

- **An open chemical process library: OMChemSim, with a flash drum example** (gap M1).
  - The runner image now holds OMChemSim (FOSSEE, IIT Bombay, BSD-3-Clause, package
    `Simulator`), pinned by commit. It has components with their constants, thermodynamic
    packages, streams and unit operations from mixers to distillation.
  - A job loads it only when the project's files use it.
  - The new example project "Process library examples" (`PlantCraftProcess.MethanolWaterFlash`)
    splits a methanol and water feed into vapour and liquid with Raoult's law while the feed
    heats from 350 K to 360 K.
  - ThermoSysPro is not shipped, because its Modelica License 2 binds modified copies and the
    built executables. `docs/process-libraries.md` explains this and how a site can add it to
    its own image.
  - Runner protocol 4: the runner's heartbeat lists each library with its version.
- **An example optimization comes ready: tune a PI for the least IAE.** Next to the example
  study, Models queues "Example: tune the PI for the least IAE" once. It is an optimization on
  `FirstOrderDeadTimeLoop` that changes the controller's gain and integral time, from a sluggish
  start (k 0.4, Ti 60 s), to bring the loop to its new setpoint with the least integral of
  absolute error, overshooting by 10% at most (COBYLA). On that process it ends near k 1.2 and
  Ti 21 s in about 35 simulations, close to the SIMC rule's k 1.0 and Ti 20 s.
  `MODELCRAFT_EXAMPLE_STUDY=false` leaves it out too.

### Fixed

- A study's ranking table scrolls inside its panel on a phone instead of pushing the page sideways.
- Colours and shadows named after tokens that do not exist use the suite's tokens, so they follow
  the dark theme.
- A run's `files.json` and `compare.json`, a result's `names.json` and `variables.json` and the cached reading of a library model are written whole or not at all (temporary file, fsync, rename): a process killed while writing one no longer leaves broken JSON behind.

### Security

- The Modelica runner image upgrades its base packages when it is built.

## [0.5.1] - 2026-10-30

- Suite 0.5.1: `plantcraft-sdk` 0.79.0 and `@plantcraft/ui` 0.89.0, with the new look (the PC valve logo, Steel Blue and the new app marks).

## [0.5.0] - 2026-10-27

### Security

- **Asset scope (decision D2).** A person who sees only part of the plant (PlantCraft's token claim
  `assets`) sees only the simulations and studies whose plant signals they all see; one on no plant
  data is everyone's. `processcraft-sdk` 0.66.0.

### Changed

- **A block's page has the tabs of an Analytics block**: Overview is its drawing
  and About this block (What it does, How to read it, Formula, written anew for the 28 blocks
  Models ships, as headed parts of the class's Documentation); its ports and parameters moved to
  Inputs and outputs. **Duplicate** works on any block, the shipped ones too: the copy goes to the
  site's first library of its own (made as "This site's blocks" when there is none). A site
  block's **defaults** change on Inputs and outputs: `PUT /api/catalog/<block>/defaults` writes
  them in its declarations, a new version with what changed (required). The Simulations pages lost
  their Studies button (it is in the side menu).
- **A model's page has the tabs of an Analytics algorithm**: Overview (what it
  is, no results), Inputs and outputs (what it reads and gives, and every block's parameters, each
  saying whether it is the block's default or the model's own value), Diagram, Test (was Run: one
  simulation, a check; the studies run a model for real), Used by (its studies, was Studies),
  Versions and Settings (the simulation settings and About it, which was on Versions). Run and
  New study left the top of the page; `/run` and `/studies` lead to the new tabs. Saving a version
  asks what changed; its name is optional.
- **The Overview has no buttons on top**: Open the models and New model are in the side menu and on
  Models.

- **The simulations widget says "Started 5 min ago"** under the name instead of a bare time
  (SDK 0.76.0).
- **The Overview answers "what ran, what did it give, and where do I continue?"** Two new widgets,
  `activity` (simulations and study runs per day over 14 days, stacked by status, days on the
  installation's clock) and `latest-study` (the latest finished study or optimization: its best
  values, or how many cases a sweep simulated), then the models, latest simulations and studies.
  `run-status`, `model` and `runner` leave the default board (still served); the runner shows
  only as a notice while it is down. The studies widget keeps to the person's asset scope.
  `processcraft-sdk` 0.69.0, `@processcraft/ui` 0.72.0.
- The example project is called "Analytics models" (the glossary's name for the app).

### Fixed

- **Models' executor says how much memory a task may use.** Its heartbeat carries
  `memory_mb` (`--memory-mb`, `MODELCRAFT_JOB_MEMORY_MB`), so PlantCraft sends it only the
  sizes that fit, as Analytics' executor does. Before, every worker offered Models `large`.

- **processcraft-sdk 0.64.0**: the database uses the rollback journal on a Docker Desktop bind
  mount, where WAL can crash an app with several processes (bus error).

### Added

- **A name and what changed for each version of a model (round 9 M4).** Save as version asks
  for a name and an optional note, as Analytics' algorithms do; the Versions tab shows them, and
  a version used again keeps its name. `PUT /api/models/<project>/<model>` and the file save take
  `version_name` and `version_note`; two columns on `project_files` and `file_revisions`.
- **The runner keeps built models** (its own `/tmp`, the last 32): a study's next batch and each
  step of an optimization with the same files and settings skip OpenModelica's build (about
  5 s for the examples) and only run the program. `MODELCRAFT_RUNNER_CACHE=` turns it off.

- **Optimization studies** (`/studies/new`, **Find the best values**): up to 10 inputs or
  parameters changed within bounds to minimize, maximize or bring to a target one indicator of a
  variable (final value, overshoot, settling time, IAE...), with optional constraints on other
  indicators. SciPy's Nelder-Mead, COBYLA or SLSQP pick one simulation at a time from the results
  of those before; the study's page shows the best values, the best simulation and the objective
  of every simulation with the best so far. An optimization a restart interrupts goes on at the
  next start. New dependency: `scipy` (the optimizers; BSD-3-Clause).
- **Where a simulation runs** (PlantCraft docs/compute.md, "Environments and sizes"): a
  simulation or study may name an environment and a size (`compute: {environment, size}`;
  Simulation settings › Environment and Size in the study form), and its jobs go only to a
  compute worker that offers them. `GET /api/compute/offer` lists what the workers online offer.
  processcraft-sdk 0.58.0.

- **Jobs on PlantCraft's compute workers** (PlantCraft docs/compute.md): with
  `MODELCRAFT_RUNNER=suite`, the default, each check, diagram, simulation, sweep and FMU export
  is a compute task that the runner behind a worker's gateway answers, on PlantCraft's machine
  or another; Models needs the `write.compute` permission and shares no folder with the runner.
  The runner's heartbeat names its app and protocol (`runner-3`), so only a runner that speaks
  it takes the jobs, and its image runs as the compute user (10020). Cancelling a run cancels
  its task; a simulation on a worker shows no progress until it ends. `queue` keeps the shared
  folder for development.

- **Simulations in the suite's Queue** (PlantCraft docs/quick-access.md): a simulation is
  reported when it is queued, starts and ends, with who started it and Cancel while it waits or
  runs, so it shows under Mine in the Queue panel and PlantCraft tells that person when it fails
  or ends after more than a minute.
- **A block's picture and drawing** (round 9 M1, M2): a block's Overview draws it as a model's
  diagram does (inputs on the left, outputs on the right, names and units), and a block of the
  site's own library takes a picture there (PNG, JPEG, WebP or SVG, at most 256 KB). The picture
  is written in the class's `Icon` annotation as a `Bitmap`, so it is saved with the library
  file as a new version and Modelica tools show it too; it shows in the diagram and the palette.
  `PUT /api/catalog/{block}/image`, `GET /api/catalog/{block}/image` and
  `GET /api/catalog/{block}/versions/{rev}/image` (processcraft-sdk 0.52.0, ui 0.60.0).

### Fixed

- **processcraft-sdk 0.60.0:** the compute executor's child imports modules that subclass a
  socket (`ssl`, through `httpx`), which failed before.

- **A block with `end when`, `end if` or `end for` in its equations** was read as ending there:
  its documentation (and anything after) was missed. The class now ends at its own `end`.

- **Versions of a model and of a block, as Link's** (round 9 M3, M4): a model's older version
  opens read-only on its Overview, Diagram and Inputs tabs (`?version=N`) and Use this version
  saves it again as the newest; two or three versions compare on the same simulation settings (the
  settings in use), their variable on one chart with final, lowest, highest and run time. A
  block's versions compare their inputs, outputs and parameters side by side and what changed in
  the code. `GET /api/models/{p}/{m}/versions/{rev}`, `POST .../versions/{rev}/use`,
  `POST /api/models/{p}/{m}/compare`, `GET /api/catalog/{block}/versions/{rev}` (ui 0.59.0).
- **Folders for models, blocks and studies** (round 9 M5), as Link's: a column on the left of
  each list, Move to folder on the object's page (who moved it, when) and the folder chosen on
  New model and New study (Run again with changes keeps the study's folder). Only the site's own
  blocks go in folders; the shipped libraries stay above them. The filter by model on Studies
  stays. `GET/POST /api/folders/{model|block|study}` (processcraft-sdk 0.50.0, ui 0.56.0).
- **Studies drive the model's inputs and vary its simulation settings** (round 9 Q7c): a
  model's own inputs (``u`` and ``d`` of a model written as code) are held at a value, stepped
  or ramped to it, fixed or swept like a parameter; stop time, intervals, tolerance and the
  integrator are varied too, to compare them. Each simulation of a sweep has its own run time
  (runner 3). A study's run opens inside the study, and any variable of the results is ranked,
  plotted against a parameter or given a chart of its own after the study ran
  (``POST /api/studies/{id}/indicators``).
- **The assistant on Models, Studies and a study:** which model fits a question, ask about the
  studies, what a study found.
- **The assistant's works** (processcraft-sdk 0.39.0, PlantCraft `docs/assistant.md`,
  "Works"): design a new model; on a model, explain what it represents and suggest a study.
  They replace the pages' tasks of the same names.

### Changed (- **The suite's dialog** (`@processcraft/ui` 0.53.0, scale review A1): its windows and the delete
  questions are the ui's `Dialog` and `confirmAction()` instead of the browser's confirm or a
  window drawn here, so they follow the theme, keep the focus inside and close on Escape.

owner review, round 9)

- **Models follows Link's new pages.** New model is a page of its own, as Link's New block:
  import a Modelica file (`POST /api/models/import`, the file as it is, opened on its first
  model) or fill in the form and go on in the editor; the assistant is the button beside the
  title. A model and a block have a Versions tab (what it is on top, then each version, newest
  first) instead of the column on the right, and saving a model's inputs says which version it
  makes ("Save as version 3") in a bar that stays at the bottom of the screen.
- **An example study comes ready.** At the first start Models queues "Example: controller gain"
  (the tank's level with three controller gains), so a new install has a study already run to
  read; `MODELCRAFT_EXAMPLE_STUDY=false` leaves it out.

### Changed

- **Older databases upgrade by named steps** (`processcraft-sdk` 0.46.0): the columns added
  since the first release are the stores' `MIGRATIONS`, run once and recorded, and
  `tests/test_upgrade.py` opens each store on its older tables.
- processcraft-sdk 0.35.1: the suite's rules for an app's inside (PlantCraft
  `docs/app-standard.md`, section 5). `suite/` is the only code that talks to PlantCraft (runs
  on Executions, events by name through `EventCatalog`); `projects/models.py` and
  `runs/models.py` hold the limits and errors, so the routers import no store.
- A study's last simulation writes `modelcraft.study.finished` (done and failed counts), as
  `app.toml` declared; quick simulations do not.
- **Studies redone** (round 8 M2): a study starts on a page of its own, **New study** on the
  Studies page, with any model of any project chosen there (it no longer has to be opened from
  the model first); a model's New study opens the same page with the model chosen. The form is
  in sections (what it studies, experiment, inputs and parameters, what it compares) with a
  preview of the simulations it makes. A study's results can be drawn **side by side**: one chart
  per value of a varied parameter, on one scale.
- **Executions as Link's** (round 8 M3): the study takes the schedule's place and the simulation
  the asset's. **By study** lists the studies and each model's single runs with what they vary
  and how their simulations ended; a group's page (`/executions/<id>`) has a summary and its
  simulations; **Queue** (`/executions/queue`) has the queue panel and every run, FMU exports
  included.

- processcraft-sdk 0.28 (an app without an app key reports its conditions).
- Models has Link's pages (round 8). The menu is Overview · Blocks · Models ·
  Studies · Executions. A model's page has tabs: Overview (what it is, what it reads and what its
  scopes show, its last run), Diagram (a preview, with Open the editor), Inputs and parameters
  (every block's parameters and the simulation settings, saved on the page), Run (its runs) and
  Studies; its versions and what it is sit on the right (`/models/<project>/<class>/<tab>`).
- The diagram editor opens in a window of its own, as Link's algorithm editor
  (`/editor/<project>/<class>`); a save there tells the model's page.
- One kind of model: a model written in Modelica code opens on the same page, as the one block
  of its diagram (its inputs, outputs and parameters, `code_block` on
  `GET /api/models/<project>/<class>`); its code is one click away. The list's "Drawn as" column
  is now "Blocks".
- A block's page has tabs: Overview, Code, Inputs and parameters (one table) and Used by, the
  models that place it (`GET /api/catalog/<id>/used-by`).

### Added

- **Events** (processcraft-sdk 0.26): `app.toml` declares `run.failed` and `study.finished`; a
  failed simulation writes `modelcraft.run.failed` (permission `events`), so Alarms can tell its
  owner.

## [0.4.0] - 2026-10-24

### Changed

- Models works like Simulink (round 7): a model is a block diagram in the
  suite's editor (`@processcraft/ui` 0.37.0, feedback loops) with its simulation settings beside
  it (start, stop, solver, step, tolerance); Run simulates it and plots its scopes. Menu
  Overview · Models · Studies · Executions · Blocks; Projects, Simulations and Exports pages are
  gone (their addresses lead to the new places); Publish to Link removed. Six block libraries
  (28 blocks), three read-only examples (`PlantCraftExamples`) replacing `ProcessExamples`.
  Studies rank the runs (new indicators: overshoot, settling time, IAE). Executions in Link's
  format with the suite's queue panel; `GET /api/queue` answers `plantcraft-queue/1` (the old
  lists at `/api/queue/runs`). The Overview widget `projects` is now `models` (the old id still
  answers).

### Added

- The suite's search (Ctrl+K, PlantCraft 2026-10-23): `GET /api/search` answers with its projects, the models in them and its studies
  (`processcraft_sdk.server.search`). `@processcraft/ui` 0.25.0 and `processcraft-sdk` 0.21.0
  bring the search box and the queue clock to the frame; the SDK answers the frame's queue
  probe for an app without a queue, so no page logs a 404.

### Changed

- The suite's visual identity (`@processcraft/ui` 0.28.0, PlantCraft `docs/brand.md`): Inter and
  JetBrains Mono, neutral greys, sentence-case labels, the app switcher at the top of the sidebar
  and the fold button in its bottom corner. The IBM Plex packages are no longer needed.
- Every time in UTC (PlantCraft, 2026-10-23): `processcraft-sdk` 0.20.0 (`dev/revendor --sdk-only`;
  the app keeps its `@processcraft/ui`). The store writes `2026-10-23T14:05:09.123Z` whatever the
  server's time zone, and rows written before with the server's local offset are rewritten once
  at start. `PyJWT` joins `deploy/requirements.lock` (the SDK needs it). Ruff's `DTZ` rules are on.
  Simulation ids take their time in UTC.

### Added

- **Studies**: a model simulated once or over a sweep of parameter values (ranges and lists,
  every combination), with indicators measured in each simulation (final, smallest, largest,
  mean, integral). The study's page overlays a variable of every simulation coloured by a varied
  parameter, draws the envelope, plots an indicator against a parameter and gives statistics;
  **Export for Jupyter** downloads the parameters, the results and a notebook
  (`/api/studies…`, `MODELCRAFT_STUDY_MAX_RUNS`, 500 by default).
- **The simulation queue** (`/simulations`, `GET /api/queue`): what runs with its progress, what
  waits, and **Cancel** (`POST /api/runs/{id}/cancel`, `POST /api/studies/{id}/cancel`). The queue
  is kept in the database and survives restarts; quick simulations go ahead of studies; a study's
  simulations are built once per batch (`MODELCRAFT_RUN_BATCH`, 10) by the runner's new `sweep`
  job (runner 2).
- **Blocks** (`/blocks`, `/api/blocks`): libraries of Modelica blocks shared by every project, in
  groups. Process equipment and Process control ship with Models; the editor's Library tab
  offers them for dragging.
- A project's page (`/projects/<id>`) with its Models, Studies, Simulations and Exports;
  **Exports** lists the FMU exports apart.

### Changed

- Charts come from the suite's shared Plotly build (`@processcraft/ui/plot`, ui 0.24.0); the
  local `Plot.tsx` is gone.
- The menu is Overview, Projects, Studies, Simulations, Exports and Blocks; the editor is at
  `/projects/<id>/edit`. Old `/runs` links land on Simulations.
- The "Twin models" example project is called "Link models".
- A simulation may run up to 6 hours when its study says so (`MODELCRAFT_MAX_RUN_SECONDS`).

- The first page is the Overview every app of the suite shares (`AppOverview`, `@processcraft/ui`
  0.20.0): widgets each person chooses and orders, kept per person in ProcessCraft. Its widgets: the
  Modelica runner, the projects and the latest runs. The projects are their own page (`/projects`,
  "Projects" in the menu), where a project's breadcrumb returns.

### Added

- Widget `projects`: the Modelica projects, the examples first.
- **Copy as prompt** in the editor (`GET /api/prompts/class?project_id&name`): a ready prompt for
  the AI assistant the plant allows, with the class's Modelica text, the project classes it
  uses, the project's outline and what this server's runner refuses, so the answer pastes back
  into the editor. Preset questions (explain, extend, review); nothing is sent, the text only
  goes to the clipboard. `processcraft-sdk` 0.15.0 and `@processcraft/ui` 0.19.0.

### Fixed

- The Overview's Models widget says Code for a model written as code (it said 0 blocks).
- An install updated from 0.3 keeps its Examples project (it was ProcessExamples): the same
  project takes the new examples, with its simulations and exports, instead of being deleted and
  made again under a new id.

## [0.3.0] - 2026-10-23

### Changed

- `processcraft-sdk` 0.14.0: Models reads its settings with the SDK's `AppSettings` and connects to
  ProcessCraft with `PlatformRuntime`, the same code as every app (no setting or behaviour changes).
- `processcraft-sdk` 0.13.0: model runs read their inputs straight from the Historian when the
  suite sets `PROCESSCRAFT_HISTORIAN_URL`, without the hop through ProcessCraft (and back through
  ProcessCraft when the Historian cannot answer).
- `@processcraft/ui` 0.18.0: the browser tab reads page first, then the app, then the brand
  ("Points · Historian · PlantCraft"), and its icon is always the platform's mark.
- On the suite's current shared packages: `processcraft-sdk` 0.12.1 and `@processcraft/ui`
  0.17.0, the same versions as every other app.
- Logs are JSON lines (`processcraft_sdk.server.logs`), to standard error and, for the server, to
  a rotating file under the data folder's `logs/`, with a request id per request.
- `[backup]` in `app.toml` names this app's SQLite files, so the suite's backup copies them
  online and checks them.

## [0.2.0] - 2026-10-21

### Added

- First release in the suite's offline bundle.
