# AGENTS.md: PlantCraft Models

**Read the suite's rules first**: the repository's root `AGENTS.md` (`../../AGENTS.md`), the single
source of rules for the platform and every app. This file adds only
what is particular to PlantCraft Models; where the two differ, ask a maintainer which one wins and fix the other.

This folder is **PlantCraft Models** (`modelcraft`, prefix `/model/`, port 8130, uid 10011):
A Modelica workbench: write and draw models, simulate them on plant data and export FMUs.

## Start here

1. `git status`, `git log origin/main..HEAD`, open PRs; then `docs/STATUS.md`, `docs/gaps.md`,
   `ROADMAP.md` and `SPEC.md` of this folder.
2. `make test-fast` while working, `make ci` before every push, `make e2e` when you touched a user
   journey (the same commands in every folder: PlantCraft `docs/claude-code.md`).
3. Commit messages start with `modelcraft: `; append a line to `docs/devlog.md` before you finish.

## Map and layers

This folder:

```text
app.toml        the manifest: id, version, prefix, port, uid, permissions (single source; tested)
src/modelcraft/  the app (layers below); tests/ (pytest, against FakePlantCraft and a recorded runner)
docs/help/      help pages served at /api/help and shown under Help
frontend/       Vite + React + TypeScript, served under /model/ (base path in vite.config.ts)
vendor/         the plantcraft-sdk wheel and the @plantcraft/ui package PlantCraft Models pins (never
                edited here; SHA-256 of both in its README)
deploy/         requirements.in/.lock (+ overrides.txt): hashed dependencies of the image (`make lock`);
                runner/Dockerfile: the Modelica runner image (OpenModelica + MSL, `make runner-image`)
```

| Layer | Packages (`src/modelcraft/`) | Role |
|---|---|---|
| -1 | `i18n` | `t()`; anything may use it |
| 0 | `config`, `meta` | settings from the environment, `app.toml` and help pages (files written whole or not at all are `plantcraft_sdk.files`, the store is `plantcraft_sdk.server.store`) |
| 0 | `examples` | the example projects (Modelica files, package data) |
| 1 | `projects`, `modelica` | the project store (files, versions); Modelica text: tokens, outline, policy, diagram edits |
| 2 | `omc` | the runner (stdlib only, also the runner image's program), jobs, messages, results, library index, diagram reduction |
| 3 | `runs` | the run store and the workbench service (check, diagram, library, runs) |
| 4 | `api`, `cli` | FastAPI app under `/model`, command line |

- **omc never runs in the app's process in the suite.** Every job goes to the runner container
  through the jobs folder (`omc/jobs.py` `QueueExecutor`); `LocalExecutor` is for development.
  `omc/runner.py` imports only the standard library (it is copied alone into the runner image;
  `tests/test_suite_rules.py` checks it).
- **The policy runs before every job** (`modelica.source.policy`: no `external`, no
  `Modelica.Utilities.System/Files/Internal`), and the runner checks again. Never add a job kind
  that skips it, never pass a person's text into an omc script unquoted (`runner.mos_string`).
- **The text is the one source.** The diagram is drawn from omc's instance of the class; every
  diagram change is a text edit (`modelica/edit.py`) saved like a person's save (optimistic
  concurrency with `base_updated_at`). Never keep a second model of the diagram.
- **A run keeps the project's files** as they were (`files.json` in its folder); results are
  read from the run's folder, never recomputed from the current text.
- **Who reads plant data.** Signals for a simulation are read with the editor's own token; the
  service token only reports runs.
- **Every change to a project's shape and every run** (projects and files created, renamed,
  deleted, imported; runs started, deleted) is recorded with `POST /api/v1/audit`
  (`Runtime.audit`); file saves are kept as versions with who saved them.

The layer table is enforced by `tests/test_suite_rules.py` (`plantcraft_sdk.apptest`).

## This module's own rules

- **Language**: user-facing text is English only for now: every string goes through `t()` (`src/modelcraft/i18n.py`, `frontend/src/i18n.ts`) so a Portuguese catalog can be added later (parked in `docs/gaps.md`).
- **Bad input never crashes.** A model that does not compile, a solver that fails, a runner
  that stopped, NaN in results, gaps in plant data: the person gets omc's messages or the reason
  in words they can act on; never an exception or a 500. Unfinished features return "not supported" and are hidden in the UI.
- **No silent wrong answers.** A failed check or run is shown as failed with omc's messages,
  never as an empty plot; a plot that thins points keeps every minimum and maximum. People
  design and tune with these results.
- **One path to omc**: checks, diagrams, the library index, simulations and exports all go through `Workbench._run_job` (policy, executor, time limit).
- **Clean room** (suite rule): the tools studied for this module, for public behaviour only, are AVEVA, AspenTech, Siemens, Yokogawa, Honeywell, Cognite.
- Tests talk to `plantcraft_sdk.testing.FakePlantCraft`, never to a real PlantCraft; the
  test plant (loops, a pump, a text signal, every kind of user) is in `tests/plant.py`.
- Tests run against `tests/fake_runner.py` (answers recorded from OpenModelica 1.24.4); the real
  runner code runs on a stand-in omc in `tests/test_omc.py`. With the runner image built,
  `MODELCRAFT_E2E_JOBS` runs the browser journeys against the real OpenModelica.
- Performance is a feature: plots read only the columns they show from the run's matrix and thin
  them to a few thousand points; the library is indexed once per runner version.

## Oracles and floors

PlantCraft Models' oracle (planned): the Modelica Standard Library's own examples with their
reference results (the MSL regression reference files), simulated through the runner and
compared within tolerance; today the examples of `src/modelcraft/examples` are simulated with the
real OpenModelica by hand and in the e2e journeys.
