# Blocks and algorithms

> **Updated:** 2026-10-22 · code: `src/linkcraft/blocks/`, engine and contract in
> `plantcraft_sdk.blocks` (PlantCraft's `docs/blocks.md`)

The principles are in `AGENTS.md` ("What PlantCraft Analytics is"). This note is the reference for
how they are built: what a block is, what an algorithm is, how one runs, and what it publishes.

## Blocks

A block is a typed function with a fixed contract (`plantcraft_sdk.blocks.BlockSpec`): input
and output **ports** of one type each, Pydantic **parameters**, and **descriptions** in one
format (name, summary, what it does, how to read it, assumptions, limitations, formula,
references; every port and parameter described, with its unit). `check_catalog` holds every
block to the format (`tests/test_algorithms.py`), and the same texts feed the editor's inspector
and the assistants (`block:linkcraft/<id>`, `knowledge.py`).

| Type | Carries | Wire colour in the editor |
|---|---|---|
| `series` | numbers in time (a signal on the algorithm's grid, or as recorded) | blue |
| `state` | text in time (the mode) | violet |
| `number` | one value (an index, a period) | amber |
| `result` | a result: ok, warning, bad or unknown, with a 0-100 score and a sentence | green |
| `intervals` | parts of the window (when the unit runs) | grey |

Nine libraries, 63 blocks plus one per published model (`GET /api/blocks`, the Blocks page):

| Library | Blocks | Role |
|---|---|---|
| `input` | `input.signal`, `input.state`, `input.verdict` | the asset's signals by role (on the grid, and as recorded), and the Signal quality results already given on them |
| `dq` | `dq.loop_data` and one block per signal check (`dq.frozen`, `dq.spikes`, ...) | data quality. `dq.loop_data` is the loop's gate: it passes PV, SP, OP and mode through, or gives no data with the reason |
| `transform` | error, subtract, gain and offset, expression (a·b/c and the like), engineering unit, moving average, low-pass filter, derivative, resample, detrend, difference, clip, delay, select by condition, only in operation | signal arithmetic and treatment before a method; only in operation keeps steady operation (no start-ups or shutdowns) |
| `stats` | mean, standard deviation, percentile, histogram, correlation (with lag), step changes, time outside limits | numbers over the window (only where a condition holds, when wired), for Limits to judge or the historian to keep |
| `cpm` | one block per loop method (`cpm.stiction_screening`, ...) | control performance; the result plus the method's key numbers as ports |
| `equipment` | heat exchanger UA, pump efficiency | performance of common equipment: UA from the log mean temperature difference (fouling against the clean UA), a pump's efficiency against its curve |
| `model` | one block per published model (`model.fmu_<model id>`), deviation (T²), unit in operation | process models (FMUs) run on the asset's signals: each model block gives what the model predicts and the residual (measured minus predicted) per output; `model.deviation` judges the residuals with Hotelling's T² against a calibration of normal operation held in its parameters (what PlantCraft Twin did) |
| `logic` | compare with a limit, AND / OR / NOT, worst of, average, rule (if … then), limits | conditions on signals (intervals), combined results, or a number turned into one |
| `output` | loop health, result on the asset, message, signal result | what the algorithm publishes |

A block whose required input has no data gives none either (with the reason), so a failure
stops only the blocks after it; an optional input without data counts as not wired. `logic` and
`output` blocks always run and decide (a "worst of" ignores inputs that could not judge).

The general blocks (signal treatment, math and conditions, statistics, the operating window and
equipment) cite the public sources of their methods in their descriptions: NIST/SEMATECH and
Montgomery for the statistics, Hyndman and Fan for percentiles, Freedman and Diaconis for bins,
Page and Basseville-Nikiforov for steps, Cao and Rhinehart for steady operation, Incropera and
Kern for the heat exchanger, ISO 9906 and the Pump Handbook for the pump, NIST SP 811 for units.
An expression is parsed, never evaluated as code: only a to d, numbers, + − × ÷, powers and a
fixed list of functions pass (`tests/test_general_blocks.py`).

### Site blocks: written here, versioned, isolated

Besides the blocks Analytics ships, a site writes its own (library `custom`, "Site blocks"; owner,
2026-10-23). A site block is a **block file**, `plantcraft-block/1` (`blocks/files.py`): one JSON
object with the name, library, group, tags, the docs in the format above, typed ports,
parameters (number, integer, boolean, text, choice; default, unit, limits) and the Python code,
a `run(inputs, params, ctx)` that returns one value per output port. The same file is what
**Download the file** gives, what **Import a file** reads, what the form edits and what an
assistant writes (the prompt behind "With an assistant", `GET /api/prompts/new-block`, teaches
the format, the rules and a worked example; `blocks/guide.py`).

- **Versions.** Every save is a new, immutable version with a name and what changed
  (`site_block_versions`); the pinned id is `<library>.<name>.v<n>` and an algorithm keeps the
  version it names until someone updates it. A new version that changes the ports says so
  before it is saved. Changing a default is a new version too (New version).
- **Author and owner.** Who wrote it is fixed; who answers for it (the owner) and its tags can
  change without a new version.
- **Who writes code.** Only administrators save block code, since it runs on the server; an
  editor can fill in the form, check and test it, and download the file for an administrator.
- **Isolation.** Site code never runs in Analytics' process: `blocks/sandbox.py` checks it first
  (AST: allowed modules only, numpy, pandas, math, statistics and the like; no names or
  attributes with underscores, no `open`, `eval`, `exec`, `getattr`...), then runs it in a pool of
  separate processes (`LINKCRAFT_BLOCK_WORKERS`, 2) with restricted builtins, no network, no
  files (`RLIMIT_FSIZE` 0), a memory limit (`LINKCRAFT_BLOCK_MEMORY_MB`, 1024 above the
  worker's start) and a timeout (`LINKCRAFT_BLOCK_TIMEOUT_SECONDS`, 30; the worker is replaced).
  Outputs are checked against their declared types. Versions are written as files under
  `<data dir>/blocks/` so the compute workers load them on demand.
- **Shipped blocks** are version 1. Their Code tab shows one source, the calculation the block
  runs (the method's `run`, the check, or the function the block calls; a lambda is shown as a
  `def`), never the module that declares the block. **New version** on a shipped block of `dq`,
  `transform`, `stats`, `equipment` or `logic` opens the form from that code under the same id
  (`GET /<id>/copy?edit=true`, `sources.edit_file`); its first save is version 2 on this site
  (`BlockStore.create(..., shipped=True)`), the palette lists it from then on, and the algorithms
  that use the block keep version 1 until they are updated. Deleting the site's versions goes back
  to Analytics'. **Duplicate** still makes a separate block under a new id.
- **The block page** (owner D15–D17, 2026-10-26): Overview (the block's documentation only),
  Inputs and outputs (inputs, outputs and parameters in one table), Code (one version's
  calculation; a version after the first compares with the one before), Test (the block on an
  asset's last window, each input read from a role or a signal id, every output drawn; nothing
  saved), Used by (each algorithm and the version it names) and Versions (who answers for it, then
  every version). `?version=N` opens the page at any version (`GET /<id>?version=N`, the tabs
  keep it) with a banner when it is not the one in use. **Select this version**
  (`POST /<id>/current`, `BlockStore.select`) sets the one in use: what the palette, new
  algorithms and the page take; algorithms keep the version they pin. Version 1 of a block Analytics
  ships is Analytics' own: selecting it lists the shipped block again. **New version** opens the form
  filled in from the version shown and saves the next number; **Duplicate** starts a new block
  from it (`GET /<id>/copy?version=N`).
- **The form** holds every field a shipped block has (D20): the other types an input accepts,
  an output's normal range (`low`, `high`) and which way is good (`better`), and
  `runs_on_missing`.

API (`api/routers/blocks.py`, prefix `/api/blocks`): the catalog, `GET /format`, `POST /check`,
`POST` (create), `GET /<id>`, `/<id>/code`, `/<id>/file`, `/<id>/copy`, `POST /<id>/versions`,
`POST /<id>/current`, `PATCH /<id>` (owner, tags), `DELETE /<id>` (refused while an algorithm uses it), `POST /test`.
Tests: `tests/test_site_blocks.py`, `frontend/src/blockFile.test.ts`, the e2e journey
`test_a_block_is_written_in_the_form_versioned_and_diffed`, `test_editing_a_block_link_ships_saves_version_2`.

## Algorithms

An algorithm is a diagram of blocks (version 2: nodes `{id, block, parameters, record, x, y,
label}`, edges `{source, source_port, target, target_port}`), saved with its documentation in
the format every algorithm follows (`AlgorithmDocs`: purpose, assets it reads, when to use it,
how to read its result, instructions for the assistant). Before it runs, or is saved, it is
checked (`compile_algorithm`): known blocks, valid parameters, matching types on every wire,
required inputs wired, no loops, at least one output, at most one Loop health, named and unique
results. The errors come back per block for the editor (`POST /api/algorithms/check`).

Six algorithms ship, read-only, authored by PlantCraft (people duplicate one and change the
copy):

| Algorithm | On | Replaces |
|---|---|---|
| Flow loop (`flow_loop`) | flow loops and loops of an unknown kind, by default | `loop_health`, `control_valve`, `oscillation_noise`, `all`, `general`, `tracking`, `flow_control`, `cascade`, `valve`, `oscillation` |
| Level loop (`level_loop`) | level loops, by default | `level_control` |
| Surge level (`surge_level`) | averaging levels | `surge_drum` |
| Temperature or pressure loop (`temperature_loop`) | temperature, pressure and composition loops, by default | `temperature_control`, `pressure_control`, `composition_control` |
| Signal quality (`signal_quality`) | every signal | the system protocol Signal quality |
| Unit twin (`unit_twin`) | assets with a process model (none until a copy names them) | a PlantCraft Twin twin |

Each algorithm row carries `author`, `owner`/`owner_name`, `tags`, `group_id` and `version`
(`catalog/presets.py`). A save increments the version; `algorithm_versions` keeps each one with
its own `version_name` and `version_note` (owner D19, 2026-10-26). The algorithm's page has a
block's tabs (Overview, Inputs and outputs, Diagram, Test, Used by, Versions), opens at any
version (`?version=N`, with a banner and **Use this version**, which saves that version again as
the newest, since the monitors run the newest), and one **New version** form: what it is, the
diagram edited and tested inside the form, the data window and every block's parameters, saved
with a name and what changed. The editor window (`/editor/<id>`) stays for new algorithms and
duplicates. `PATCH /api/algorithms/{id}` changes the
owner, tags and responsible group; when a group is set, only its members, its coordinators (or
those of a parent group), the owner and administrators edit or delete the algorithm
(`may_edit` in `api/routers/catalog.py`), and the API answers 403 to the others. The list
returns `used_by` (assets using it) and `editable` for the person asking.

An old protocol id keeps working wherever it is stored (a loop, a monitor, a run): it names its
replacement (`catalog/loop_types.py`, `algorithm_id`). A protocol a person saved in 0.2 (a list
of methods, or a version 1 diagram) is converted to a diagram when Analytics starts
(`blocks/stored.py`), with the loop data check drawn where it used to be implicit; a version 1
"series" output becomes a recorded port.

What a loop type changes is parameters, not the algorithm (`docs/loop-types.md`). Parameters
apply in layers: the method's default, the site's default, the loop type's, the diagram's, the
loop's own, a run's own.

## Running

The loop monitor runs each loop's algorithm on its window; a monitor runs one algorithm on
the loops it selects; Signal quality runs its diagram on every signal (`signals/assess.py`, in
worker processes). `POST /api/algorithms/test` runs a diagram once on one loop without saving
anything and returns what every wire carried (`trace`), for the editor to show next to each
port.

## Algorithms on assets

An algorithm works on control loops (the loop monitor, monitors), on signals (Signal
quality) or on **assets** (`subject_kind: "asset"`): a unit, a furnace, any asset of PlantCraft.
An algorithm on assets keeps the assets it runs on (`assets`) and its `timing`: every
`cycle_seconds` (from 10 s) it runs on each asset over the `window_seconds` ending at the run's
time, its signals read on `step_seconds` (`src/linkcraft/assets/`).

- Its **Signal** blocks read a role of the asset, a role of another asset (`asset`: a loop of the
  unit) or a signal by its id (`signal`), resolved through PlantCraft's asset records and read
  in one request.
- Its blocks keep a **memory** between runs (`Context.states`: the deviation block's count of
  deviating runs), kept per algorithm and asset and started afresh when the diagram changes.
- It **publishes** like any algorithm: results on the asset (`out_<name>`), messages (tracked per
  algorithm, so two algorithms on one asset never close each other's), and recorded ports (see
  "Recorded outputs" below).
- `POST /api/algorithms/test` with `asset_id` (and `timing`, `end`) tests it on one asset's window;
  `GET /api/algorithms/<id>/runs` gives its latest run on each asset, `POST .../run` runs it now;
  `GET /api/assets/<id>` lists the algorithms that run on an asset.

The `model` library runs only in algorithms on assets: a model block runs its FMU in a worker
process, which the loop monitor's processes do not hold.

### Calibrate

A Deviation (T²) block judges residuals against a calibration held in its own parameters: the
residuals' mean and covariance in normal operation, the asset and period it was learned on.
`POST /api/algorithms/calibrate` (`{diagram, node_id, asset_id, timing, start, end}`, editors)
learns it (`assets/calibrate.py`): the diagram runs on the asset over the period one judged part
apart (the model blocks' `judged_seconds`), as the cycle would have run it, reading the plant
once (`assets.run.runs_over`); every residual wired to the block is kept, runs that could not be
judged are left out and counted, and `models.stats.calibrate` gives the mean and covariance
(trimming outliers, warning on offsets). Nothing is saved: the editor puts the answer in the
block's parameters (the `inspectorTools` of `@plantcraft/ui`'s `BlockEditor`), and saving the
algorithm keeps it, versioned with the diagram. A period needs at most 500 runs.

### Twins as algorithms

A PlantCraft Twin twin is an algorithm on assets (`assets/twins.py`): each input and measured
output a Signal block (a scale or an offset becomes a Gain and offset block), the twin's FMU a
model block with its parameters and start parameters, the residuals into a Deviation block with
the twin's confidence, share, persistence, centring and calibration, its activity band a *Unit
in operation* block, and the result a result (`Model deviation`) and a message. Its cycle,
horizon and step are the algorithm's timing. PlantCraft Twin's oracle passes in Analytics with the
same floors (`tests/oracles/test_twin_oracle.py`): the load disturbance and the drifting sensor
found and named on every run, healthy twins quiet on 97 % of them.

An installation that ran Twin (copied once into Analytics until 2026-10-25) and added the plant's
model examples has each model twice: the copy `twin_<id>` and the example with the same name, on
the same assets. Algorithms lists those copies for an admin (`GET /api/algorithms/repeated`,
`assets.twins.repeated_twins`), and **Remove them
and their monitors** deletes them after a confirmation (`POST /api/algorithms/repeated/remove`;
refused while a loop uses one).

### Publishing a model

PlantCraft Models' **Publish to Analytics** (admins) sends a run's FMU to `POST /api/models` (the
file as the body, `name`, `description` and `origin`, the run's page); Analytics reads it (never runs
it), refuses one without a Linux 64-bit binary or above `LINKCRAFT_MAX_MODEL_MB`, and the model is
a block of the Models library at once. `GET /api/models/<id>/starter` is a new algorithm on assets
around it (each input and output a Signal block whose role the person chooses, the model,
Deviation, a result and a message): what **Build an algorithm with it** and the model block's
page open in the editor (`/editor/new?model=<id>`). Editors rename a model (`PATCH`); admins
delete one no algorithm uses.

### The plant's model examples

When the Simulator demo plant's loops are in PlantCraft, **Add the plant's model examples**
(Algorithms, editors; `GET` and `POST /api/models/examples`, `assets/examples.py`) creates the
example twins PlantCraft Twin used to offer, as algorithms on assets on the built-in models:
`example_furnaces` on the furnace loops' area (TIC-1104, TIC-1209 and FIC-1210 predicted from
their valves, result `linkcraft.out_model_deviation`), `example_fic_1001_process` and
`example_lic_1010_process` on their loops. Each is calibrated on the six hours up to the plant's
newest data; one that cannot be yet is created without and says why. One that exists is left as
it is.

## What an algorithm publishes

- **Loop health** (`output.loop_health`): the loop's health and status in PlantCraft, its
  findings as events, its health in the historian, as before.
- **Result on the asset** (`output.result`): a named result on the asset (kind
  `linkcraft.out_<name>`), beside its health.
- **Message** (`output.message`): an event when its input turns bad (or warning), closed when it
  recovers.
- **Recorded ports**: any number, result or series output with `record` on its node. On assets,
  the monitor decides what is written (below); a run without a monitor (Run now on the
  algorithm's page) keeps them in Analytics only. The `app-linkcraft:<asset>.<algorithm>.<output>`
  series written before round 8 are retired once.
- **Signal result** (`output.signal_quality`): each signal's result, as Signal quality always
  published it.

## Recorded outputs

What each run keeps in the Historian is the monitor's choice (owner, 2026-10-25, D6). A
monitor on assets lists its algorithm's recorded ports in **Recorded outputs**, one row each:
record it or not, and for how long, with what it costs before it is saved (values a day and
the space they take on all its assets; one year for what is kept forever).

| Output | Points | Kept by default |
| --- | --- | --- |
| number | one value per run | 400 days |
| result (`result`) | its score (`/100`) and its status as text, two points | forever |
| series | the whole series of each run, a runs point | the last 10 runs |

The points are `app-linkcraft:<asset>.<schedule key>.<output>` (`.status` for a result's
status), named `<tag> · <schedule> · <output>`. The monitor key comes from its name when it is
made and stays when it is renamed. The Historian keeps each point's retention locked to its
monitor (`managed_by: link:<schedule id>`): it changes here, and a row turned off stops its
writes while what it wrote stays until its time is up, as do the points of a deleted monitor.

Each asset of the monitor gets a **result asset** under it, `linkcraft.<asset>.<schedule key>`,
holding those points; it ends (and stays, with its points) when the monitor is deleted or the
asset leaves it. `GET /api/schedules/<id>` and `POST /api/schedules/preview` give the rows with
their cost per asset (`recorded_outputs`); `outputs` on a cadence is
`{output: {"record": bool, "keep": {"forever": true} | {"days": N} | {"runs": N}}}`.

## Why no graph library

The engine is the standard library's `graphlib` plus Pydantic, in the SDK so Models can use it
too. pipefunc, Hamilton, Kedro, pydra, PathSim and TensorFlow were evaluated on 2026-10-22: each
either brings a large dependency for what `graphlib` already does (order a DAG), or models a
different problem (pipelines of files, ML graphs, continuous-time simulation). The editor is
React Flow, shared by the suite as `BlockEditor` in `@plantcraft/ui`.

Parked: a simulation mode for Models, the Twin inside Analytics, new block libraries.
