# Devlog

## 2026-10-21

- First version: projects of Modelica files (versions, import, zip export, examples), the
  Modelica runner (OpenModelica 1.24.4 and MSL 4.0.0 in its own container, no network, limits)
  behind a jobs folder, check, diagram (`getModelInstance` reduced to icons, placements,
  connections, parameters), diagram edits as text edits, library index and browser,
  simulations (solvers, overrides, plant inputs and comparison), results (matrix, thinning, CSV),
  FMU export (FMI 2/3, CS/ME), runs reported to ProcessCraft, asset page, help and tour. The
  interface: projects, the workbench (CodeMirror editor, SVG diagram editor, library, inspector,
  messages), runs and the plot page. Skeleton from AlarmCraft (same app standard).
- Tests: the API against `FakeProcessCraft` and a runner answering from recorded omc output;
  the real runner code on a stand-in omc; 9 browser journeys, green against the fake runner and
  against the real OpenModelica container.

## 2026-10-21 · Where to start, next steps

- Projects opens with "From a model to a twin" (write or draw, check and simulate, compare with
  the plant, export for Twin), counted from the projects and the runs that finished; a run ends
  with its next steps (an FMU: upload it on Twin's Models page). One more tour step points at the
  path. `@processcraft/ui` 0.6.3 (its texts in the five languages).
- The demo seed (ProcessCraft `processcraft demo seed`) simulates the examples, feeds
  `PlantCraftTwin.LoopProcess` with a loop's last hour, and exports the Furnaces FMU that a second
  twin runs in Twin.

## 2026-10-21: on the suite's shared server and test kit (processcraft-sdk 0.9.0, @processcraft/ui 0.7.0)

- Server: the SQLite store, `app.toml` and help, access checks and the web application come from
  `processcraft_sdk.server`; `db.py` and `deploy/sbom.py` are gone, `meta.py`, `api/deps.py` and
  `api/app.py` keep only the parts that are Models' own. The image writes its SBOM with the SDK.
- Interface: the API client and the Help page come from `@processcraft/ui`.
- Tests: `tests/test_suite_rules.py` (offline, layers, image, API floor, hostile inputs, on
  `processcraft_sdk.apptest`, plus the runner's standard-library rule) replaces four files; the
  test plant is `processcraft_sdk.testplant`; e2e fixtures use `processcraft_sdk.e2e`; time
  budget in `pyproject.toml` (`make test-fast`). The hostile run pairs bodies and queries instead
  of multiplying them: 11 s instead of 50 s. The queue test no longer races its worker under load.
- Docs: `AGENTS.md` is the short module file (the suite's rules live once, in ProcessCraft's
  `AGENTS.md`); the README says how the module is built (with Claude Code, in the open); `make
  test-fast` in Develop.
- `docs/gaps.md` in the suite's format (Id, Gap, Impact, B).

## 2026-10-21 (night): the integrator first; plants of your own components

- The owner: "whether we can choose the integrator", and "create the blocks, keep them, connect
  them into a plant and run it all together", as in OpenModelica.
- The simulation dialog opens with the **Integrator**: omc's solvers, each with what it is for;
  the choice is remembered per model in the browser.
- **New class** starts from templates: System (an empty diagram with an experiment), signal
  block, thermal component, electrical component (connectors, parameters, an equation and an
  icon), or the plain classes. Models and blocks of the project tree drag into another class's
  diagram like library classes (`templates.ts`, `placeable`); a class is never dropped into
  itself.
- `@processcraft/ui` 0.10.1.
- 2026-10-22 (round 5, owner's review): the Overview loses the "From a model to a twin" path; Runs
  is the suite's table (sort, search, pages) with filters for kind, status and project and a
  download per row (a simulation's CSV, an export's FMU); a run's page has no next steps and offers
  its download in the heading. The workbench's top bar drops the model picker (the tree chooses),
  shows the class in the breadcrumb, renames Download to **Project .zip** and adds Duplicate on an
  example; the ▷ beside a class now opens its simulation (it was only a mark); an empty diagram says
  so and opens the library; **New class** asks what OpenModelica's "New Modelica Class" asks
  (specialization, description, extends, package with `package.order`, partial) with the templates
  kept for models and blocks. "Publish to Twin" ends on "Create a twin with it".
- 2026-10-22: @processcraft/ui 0.13.0; the tables filter by column (the suite's MultiSelect) instead of selects beside the search.
- 2026-10-22: "Publish to Twin" became "Publish to Link" (ProcessCraft Twin is now part of Link): the FMU becomes a block of Link's Models library and "Build an algorithm with it" opens Link's editor on a new algorithm on assets around it; texts and help say Link.

## 2026-10-23: projects, studies, the queue and shared blocks (round 6)

- The owner's review: a project is an organization of models, studies and simulations; blocks are
  global and grouped like Link's algorithms; long simulations need progress and a queue; a sweep
  of inputs makes a queue of N simulations; compare them (overlay, select, statistics) and take
  everything to Jupyter.
- Menu: Overview, Projects, Studies, Simulations, Exports, Blocks. A project's page has the tabs
  Models, Studies, Simulations and Exports; the editor moved to `/projects/<id>/edit` (`?model=`
  opens a class). `/runs` and `/runs/<id>` still work.
- Studies (`runs/studies.py`, `api/routers/studies.py`): every simulation belongs to one (quick
  simulations of a model, one simulation, or a sweep). The runner's new `sweep` job builds the
  model once and runs the executable per variant with `-override`: 3 variants of
  TankLevelControl in 3.4 s in the real image.
- The queue (`runs/queue.py`): runs wait in SQLite; a dispatcher hands the oldest run of the
  highest priority (quick before sweep) and up to 9 more of the same study to the runner; a
  restart requeues what was running. Cancel is a `cancel` file the runner polls; progress is the
  last time in the results file being written.
- Comparison: overlay coloured by a varied parameter, envelope (P5, median, P95 on a common time
  grid), an indicator against a parameter, statistics (n, mean, std, P5, P50, P95, extremes);
  export as `parameters.csv`, `results.csv` and `study.ipynb`.
- Blocks: libraries are projects of `kind = library` with a group; their files join every
  project's jobs. Shipped: Process equipment (Tank, ControlValve, Pump, SensorLag) and Process
  control (PIController, SetpointProfile), checked and simulated in the real runner.
- The "Twin models" example is now "Link models" (Twin is part of Link).

## 2026-10-24 · Round 7: models as block diagrams, like Simulink

Owner's review (approved plan v2, 2026-10-24 10:55): Models works like Simulink, for study only;
Link stays the place for algorithms on the plant.

- Menu Overview · Models · Studies · Executions · Blocks, without sub-items or page tabs;
  Projects, Simulations and Exports pages are gone (their addresses lead to the new places).
- A model is a block diagram drawn in the suite's `BlockEditor` (`@processcraft/ui` 0.37.0:
  feedback loops, `real` ports) and written as Modelica declarations and `connect()` with
  placements (`modelica/blockdiagram.py`); text the diagram cannot hold stays editable in Code.
- Simulation settings beside the diagram (start, stop, solver: dassl, ida, cvode or fixed-step
  euler, heun, rungekutta, impeuler, trapezoid; step; tolerance), kept in `experiment` and
  `__OpenModelica_simulationFlags`; Run saves and simulates; the scopes' signals are plotted.
- Six block libraries (Sources, Math, Continuous, Control, Process equipment, Sinks; 28 blocks)
  and three examples (TankLevelControl, HeatExchangerOutlet, FirstOrderDeadTimeLoop), all
  checked and simulated in the real OpenModelica image. Examples are read-only and follow each
  version; Duplicate makes a copy. ProcessExamples retired.
- Studies rank the runs by an indicator and statistic (new: overshoot, settling time in a 2 %
  band, IAE), the best highlighted. Demo seed: "Tank size" (tank.A × tank.Cv, 15 runs) and
  "Heat exchanger area".
- Executions in Link's format: the suite's queue panel (`plantcraft-queue/1`), the groups
  (studies and each model's single runs), a group page; FMU exports listed apart. Publish to
  Link removed (nothing goes to Link this round); FMU export stays on a model's page.

## 2026-10-25: run.failed as an event (Alarms round 8)

- `api/runtime.py` `publish_run` posts `modelcraft.run.failed` about `app:modelcraft` when a run
  fails; `study.finished` is declared for the studies to write. `tests/test_events.py`.

## 2026-10-26: round 9 Q7c, studies (owner's Models notes, plan M6-M10)

- Inputs (M6): `StudyBody.inputs` {name: constant | step | ramp}; a fixed value moves out of the
  overrides into the input. `studies.input_csv` writes omc's `-csvInput` per simulation (a step's
  two rows a hair apart); sweeps send `inputs_files`, one per variant, and the input names never
  reach `-override`. Why LoopProcess's inputs could not be set: the form listed parameters only,
  and a code model went through the empty block diagram; it now reads omc's instance.
- Settings (M7): `@stop`, `@intervals`, `@tolerance`, `@method` in the sweep; the runner turns
  them into `-s=` and `-override=stopTime/stepSize/tolerance` per variant (`variant_flags`).
- Run time (M8): the runner measures each variant from the `variant-<n>.ok` times
  (`variant_seconds`), in place of the batch average; the study's tables say Run time.
- Run inside the study (M9): `/studies/<id>/runs/<run>`, breadcrumb Studies › study.
- Any variable (M10): Ranking and the indicator plot take any variable of the results;
  `POST /api/studies/{id}/indicators` computes them on asking; Add a chart of another variable.
- Tests: `test_studies.py` (inputs + integrators, refusals, any variable), `test_omc.py`
  (settings and inputs per variant, timing), `round9.test.ts`, e2e
  `test_a_study_drives_inputs_compares_integrators_and_keeps_its_runs`.

## 2026-10-26: round 9 Q7b, folders (M5)

- Link's folders moved into the platform so both apps share them (standardization rule):
  `processcraft_sdk.server.folders` (`FolderStore(db, kinds)`, `folders_router(kinds, editor,
  exists)`) and `@processcraft/ui` `Folders.tsx` (`configureFolders({request, href, listPath})`,
  `FolderColumn`, `FolderButton`, `FolderField`, `FolderPlaceLine`, `pc-folder-*` styles).
  Same tables and class name (`FolderStore`), so Link's data needs no migration.
- Models kinds (`FOLDER_KINDS`): `model` is `<project>/<class>` (examples too), `block` a class of a
  site library (`/api/catalog` libraries say `own`), `study` a study id (not the single runs).
  Deleting a model, a study or a project (`forget_project`) takes its objects out of folders.
- Pages: Models, Studies and Blocks lists (`pc-folder-layout`; Blocks keeps its libraries as
  `FolderButton`s above the folders), the place line on a model's and a site block's Overview
  and on a study; New model and New study carry `?folder=` and a Folder field.
- Tests: `tests/test_folders.py`, SDK `test_folders.py`, ui `folders.test.ts`, e2e
  `test_folders_hold_models_and_studies_and_moving_is_deliberate`.

## 2026-10-26: round 9 Q7b, versions and Compare (M3, M4)

- Version N of M: each save keeps the text it replaced (`file_revisions`), so `revisionOf`
  maps a number to a revision id (M is the file now, revision id 0). `_model(..., revision_id)`
  reads an older text (its class comment too); `use` saves it again with `base_updated_at`.
- Compare runs one simulation per version with the settings in use: `Workbench.start(...,
  replace={file: text})` swaps only the model's file over the project's files and the shared
  libraries. The Compare tab keeps `?versions=` and `?runs=`, follows the runs and draws the
  chosen variable per run (`seriesFacts`).
- A block's version: `library_blocks` over the library's files with that revision
  (`contractRows` lines the ports and parameters up; `CodeDiff` the file).
- Not done: a name and a note per version (Link's algorithms have them); a revision keeps
  the replaced text only, so it needs its own table. Left for when he asks.
- Tests: `tests/test_versions.py`, `round9.test.ts`, ui `compare.test.ts`, e2e
  `test_a_models_versions_open_compare_and_come_back`.


## 2026-10-26: a block's drawing and picture (round 9 Q7a, M1 and M2)

- The Overview of a block draws it with `@processcraft/ui`'s `BlockDrawing` (the one Link uses)
  and, for a block of the site's own library, `BlockImageField`. The picture lives where
  Modelica keeps one: the class's `Icon` annotation, a `Bitmap` with `imageSource` (base64).
  `modelica.edit.set_image` adds, replaces or removes that `Bitmap` and leaves the icon's other
  graphics and the documentation as they were; `interface.icon_image` reads it back, checked by
  `processcraft_sdk.images.raw_image`. Saving goes through `save_file`, so it is a new version.
- The catalog carries `image` as a path tagged with its content
  (`/api/catalog/<block>/image?v=…`), never the picture, so `/api/catalog` stays small; the
  image routes answer `Cache-Control: immutable` and a policy that runs nothing.
- Found on the way: `outline` took the `end` of `end when` (or `end if`, `end for`) for the end
  of the class, so a class annotation after such a statement was not read (OnOff's description
  was missing). `STATEMENT_ENDS` fixes it.
- Tests: `tests/test_block_images.py`, e2e `test_a_block_of_the_sites_library_takes_a_picture`.

## 2026-10-26 (optimization studies)

- A study of kind `optimization` (`runs/optimize.py`, `Workbench.start_optimization`): the spec
  keeps `optimization` (variables with start/min/max, objective, constraints, method,
  max_simulations); the optimizer runs in its own thread and asks the queue for one simulation
  at a time (a study run with its `variant`, priority of a sweep, so the queue and the compute
  workers are the same as for any study), waits for it and reads its indicators. State in
  `studies/<id>/optimization.json` (every evaluation, best, status), served with `GET /studies/<id>`.
- Deterministic on purpose: after a restart `resume_optimizations` starts the optimizer again and
  `_optimization_run` answers the points it already asked with the simulations it has.
  `study.finished` waits for the optimizer, not for an empty queue between two steps.
- Interface: the type of study on the new-study page, mode **Optimize** in the parameters table,
  the Objective section (constraints, method, most simulations), the study page's Optimization
  panel. Tests: `tests/test_optimize.py`, `studies.test.ts`.

## 2026-10-26 (built models kept by the runner)

- `runner.py`: a sweep's build is keyed by sha256 of the model, libraries, every project file and
  the build settings (`build_key`); the runner keeps the program and its runtime files
  (`model`, `model_init.xml`, `model_info.json`, `*.bin`) with the build steps' answers in its
  own `/tmp/modelcraft-builds` (32 entries, LRU), never the shared jobs folder; a hit copies them
  into the job's `out/` and the script only runs the variants. Answer gets `built`: now/cache.
- Real runner, TankLevelControl optimizations: 23 simulations 174 s -> 19 s, 56 simulations
  415 s -> 31 s, the same points and results. Test: `test_a_sweep_takes_its_built_model_from_the_cache`.

## 2026-10-27 (Overview redesign)

- New default board: `activity` (columns, simulations per day over 14 days by status) and
  `latest-study` (facts, the latest finished study or optimization and its best result), then
  models, latest simulations and studies. `run-status`, `model`, `runner` stay declared and served.
  The runner notice says what to do. Tests in `tests/test_widgets.py`.

## 2026-10-27, final review round (owner's review of Models)

- Model page on Analytics' algorithm tabs: Overview, Inputs and outputs, Diagram, Test, Used by,
  Versions, Settings (`paths.ts` MODEL_TABS; old `run`/`studies` segments map to `test`/`used-by`).
  Test lists the model's quick simulations only (study runs stay on the study). Version dialog:
  "What changed" required, name optional. Overview: no top actions. e2e journeys updated.
- Blocks as Analytics': `interface.doc_sections` reads the Documentation's `<h4>How to read it</h4>`
  and `<h4>Formula</h4>` parts (text before the first heading is the description); all 28 shipped
  blocks rewritten that way. `edit.set_binding` (a declaration's value) and `edit.rename_class`;
  `PUT /api/catalog/<block>/defaults` (site blocks, `version_note` required) and
  `POST /api/catalog/<block>/duplicate` (into the first own library, else a new SiteBlocks one).
  Tests: `tests/test_block_pages.py`, e2e blocks journey.
