# AGENTS.md: PlantCraft Analytics

**Read the suite's rules first**: the repository's root `AGENTS.md` (`../../AGENTS.md`), the single
source of rules for the platform and every app. This file adds only
what is particular to PlantCraft Analytics; where the two differ, ask the owner which one wins and fix the other.

This folder is **PlantCraft Analytics** (`linkcraft`, prefix `/link/`, port 8140, uid 10012):
Checks every signal for bad data and every control loop for oscillation, sticking and manual mode, and says why.

## What PlantCraft Analytics is (above every block and algorithm)

Owner's governing principle (2026-10-22): the philosophy of the app matters more than any one
block or algorithm, and every change keeps to it and refines it. PlantCraft Analytics is an engine of
**monitoring algorithms** that run on their own, routinely, over the plant's assets and return an
explained verdict:

1. **Blocks with a contract.** Every block declares typed, described inputs, outputs and
   parameters. No calculation hides outside a block.
2. **Algorithms are diagrams.** An algorithm is blocks wired together, validated before it runs.
   What runs is exactly what the diagram shows (no implicit steps).
3. **They run routinely.** Algorithms are scheduled (every hour, every day, on chosen assets) and
   can replay a past period.
4. **Everything is described for people and for the AI.** Blocks, ports, parameters, algorithms
   and recorded series carry descriptions in one fixed format; that text is the assistant's
   context.
5. **Results stay in the suite.** The verdict goes to the asset; chosen outputs go to the
   Historian as described series, so Trends, Dashboards and the assistant read them.

Control loop performance (CPM) and data quality are only the first block libraries. A change that
breaks one of these points needs the owner's decision first. Methods and checks are **blocks**
and protocols are **algorithms**: diagrams of blocks (`docs/blocks-and-algorithms.md`).

## Start here

1. `git status`, `git log origin/main..HEAD`, open PRs; then `docs/STATUS.md`, `docs/gaps.md`,
   `ROADMAP.md` and `SPEC.md` of this folder.
2. `make test-fast` while working, `make ci` before every push, `make e2e` when you touched a user
   journey (the same commands in every folder: PlantCraft `docs/claude-code.md`).
3. Commit messages start with `linkcraft: `; append a line to `docs/devlog.md` before you finish.

## Map and layers

This folder:

```text
src/linkcraft/   the app (layers below); tests/ (pytest, against FakePlantCraft); tests/oracles/
frontend/       Vite + React + TypeScript, served under /link/ (base path in vite.config.ts)
vendor/         the plantcraft-sdk wheel and the @plantcraft/ui package PlantCraft Analytics pins (never
               edited here; SHA256 in its README)
deploy/         requirements.in/.lock: hashed dependencies of the Docker image (`make lock`)
```

| Layer | Packages (`src/linkcraft/`) | Role |
|---|---|---|
| -1 | `i18n` | `t()`; anything may use it |
| 0 | `db`, `config`, `notebook_examples` | the SDK store with second-precision times, settings from the environment; the examples Notebooks shows |
| 1 | `methods`, `models` | the signal checks (`signal/`), the loop data gate (`quality/`), the CPM methods (`cpm/`); help pages and guides (`help/`); process models (FMUs) |
| 2 | `catalog`, `data` | method and check registries, labels, help, loop types, stored algorithms; API v1 series to frames and samples |
| 3 | `engine`, `blocks` | jobs, schedules, compute pool, latest results; the block catalog and the shipped algorithms (`docs/blocks-and-algorithms.md`) |
| 4 | `loops`, `signals`, `assets`, `report`, `knowledge` | loop store and sync, analysis, monitoring round; signal store, Signal quality engine and publishing; algorithms on assets; PDF reports; what the assistant reads about Analytics |
| 5 | `api`, `cli`, `bench`, `notebook` | FastAPI app under `/link`, command line, benchmark, blocks and algorithms run in a notebook |

- **Where loops come from** (SPEC.md, "Loop source"): PlantCraft assets of kind `loop` with
  signal roles, synced into PlantCraft Analytics's own loop table every round (`origin = processcraft`: name
  and signals are owned by PlantCraft, CPM settings by PlantCraft Analytics), plus loops defined here from
  v1 signal ids (`origin = user`).
- **Signal quality first.** The system algorithm Signal quality (`signals/`, schedule
  `round-signal_quality`) runs the Data quality checks (`sq_*`, group `signal_quality`, role
  `signal`) on every signal. A loop is judged on its signals' latest verdicts (`loops/suite.py`,
  `quality_verdicts`): a bad PV or OP blocks it. The loop data check (`dq.loop_data`, drawn in
  every loop algorithm; methods `dq_*`) still runs first and decides when a verdict is missing
  or stale; CPM blocks do not run on data it rejects.
- **Site block code never runs in Link's process.** Blocks written on a site (library `custom`)
  go through `blocks/sandbox.py`: the AST check, then a separate restricted process (no files,
  no network, memory and time limits). Never call their `run` directly, never widen
  `ALLOWED_MODULES` or allow underscore names without the owner's decision, and keep versions
  immutable (a change is a new version; `docs/blocks-and-algorithms.md`, "Site blocks").
- **The interface frame is `@plantcraft/ui`** (`SuiteShell`, `HelpBrowser`, tokens, fonts,
  marks); never copy its pieces here. If the frame lacks something, note it for PlantCraft.
- **People's requests use their own token** (`Runtime.user_client(user)`), so PlantCraft's
  permissions apply; background work uses the app's service token. Every change a person makes
  is recorded with `POST /api/v1/audit` (`Runtime.audit`).

The layer table is enforced by `tests/test_suite_rules.py` (`plantcraft_sdk.apptest`).

## This module's own rules

- **Language**: user-facing text is English only for now: every string goes through `t()` (`src/linkcraft/i18n.py`, `frontend/src/i18n.ts`) so a Portuguese catalog can be added later (parked in `docs/gaps.md`).
- **Bad data never crashes.** NaN, gaps, constant signals, empty windows, wrong units, a dead
  source, a malformed CSV or plant map: every method returns a Finding marked `apt=false` with a
  reason a person can act on, never an exception or a 500. Unfinished features return "not
  supported" and are hidden in the UI.
- **Every analysis is a `@method`** (from `plantcraft-sdk`): id, label, inputs by signal role,
   parameters with labels, `run`, `describe(metrics)`, tests. UI, CLI, API, algorithms, rounds and
   specialists all call methods by id.
- Tests talk to `plantcraft_sdk.testing.FakePlantCraft`, never to a real PlantCraft; the
  known-fault loops are in `tests/plant.py`.
- Performance is a feature: `python -m linkcraft.bench --loops 2000 --processes 4 --latency-ms 2`
  must not regress more than 20% (last measured in `docs/devlog.md`).

## Oracles and floors

PlantCraft Analytics's oracles: the International Stiction Database (Jelali and Huang), simulator
loops with known faults, and synthetic signals with injected freezes, spikes, gaps and drifts
(`tests/oracles/`); their pass count is the `[oracles]` floor in `tests/floors.toml`. The fetch
script for pinned public data is not written yet (`docs/gaps.md`).
