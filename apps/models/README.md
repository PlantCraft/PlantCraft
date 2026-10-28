<p align="center"><img src="docs/images/logo.svg" width="72" height="72" alt="PlantCraft Models"></p>

# PlantCraft Models

A Modelica workbench in the browser, as an app of the
[PlantCraft](https://github.com/PlantCraft/PlantCraft) suite.

- **Projects of Modelica files**: packages as folders (`package.mo`, `package.order`), import of
  `.mo` files, download as a zip, the last 50 versions of every file, example projects (a tank
  level loop, a heat exchanger, a reactor, the models PlantCraft Analytics ships).
- **A Modelica editor**: highlighting, completion of library and project classes, OpenModelica's
  errors and warnings on their lines, save with Ctrl+S and no lost work when two people save.
- **Diagrams**: the class drawn from its `Placement` and `Line` annotations with the library's
  icons; drag classes from the Modelica Standard Library, move, rotate, delete, connect
  connectors and set parameters. Every change is a text edit, so the text stays the one source.
- **The library browser**: the Modelica Standard Library 4.0.0, searchable, with each class's
  icon, parameters, documentation and text.
- **Check, simulate, plot**: OpenModelica checks the model (equations and variables, or what is
  wrong where), simulates it with the chosen solver, period and parameter overrides; the results
  are plotted (with min/max thinning), compared with other simulations and downloaded as CSV.
- **Plant data**: a simulation can take its inputs from the plant's history (signals read
  through PlantCraft with the person's own access) and be drawn against the plant's signals.
- **FMU export**: FMI 2.0 or 3.0, co-simulation (CVODE inside) or model exchange, Linux 64-bit,
  for PlantCraft Analytics and any FMI tool.
- **Suite integration**: runs listed on PlantCraft's runs page, an asset's page with the
  simulations that used its signals, audit of every change, the suite frame, help and tour.

## How it fits the suite

PlantCraft Models follows the suite's app standard (PlantCraft `docs/app-standard.md`): its
metadata lives in [`app.toml`](app.toml) (id `modelcraft`, prefix `/model/`, port 8130, uid
10011), and it serves `/healthz`, `/api/meta`, `/api/help` and `assets/<id>`.

```text
browser ── proxy ─┬─ /        PlantCraft         users, sign-in, assets, signals, runs, audit
                  └─ /model/  PlantCraft Models  projects, files, runs (own SQLite + data folder)
                                    │ compute tasks (PlantCraft's queue, a worker's gateway)
                              modelcraft-executor  OpenModelica 1.24 + MSL 4.0.0
                                                   no network, no secrets, read-only, limits
PlantCraft Models ── PlantCraft API v1 (plantcraft-sdk) ──> assets, signals, series;
                                                                  runs, audit
```

OpenModelica never runs in the app's container: every check, diagram, simulation and export is
a task of PlantCraft's compute workers, answered by the **runner** (`deploy/runner/`), which has no network
at all, no secret, a read-only root filesystem and CPU, memory, process and time limits. Before
a job leaves, the app refuses `external` code and the file and system functions of
`Modelica.Utilities` (the runner checks again). People sign in at PlantCraft; Models verifies
their token offline and records every change in PlantCraft's audit log.

## Run it

```sh
python -m venv .venv && . .venv/bin/activate
make deps                                  # plantcraft-sdk from vendor/, then PlantCraft Models
(cd frontend && npm ci && npm run build)   # the interface, served under /model/
make runner-image                          # the Modelica runner (OpenModelica + MSL), once

# The runner, on a jobs folder the app shares (in the suite, PlantCraft's compute workers run it):
mkdir -p var/jobs && make runner JOBS=$PWD/var/jobs
export MODELCRAFT_RUNNER=queue MODELCRAFT_JOBS_DIR=$PWD/var/jobs

# In PlantCraft: list modelcraft=/model/ in PLANTCRAFT_APPS, then an admin creates an app key
# for modelcraft (Apps page, or POST /api/app-keys).
export PLANTCRAFT_URL=http://127.0.0.1:8060
export PLANTCRAFT_APP_KEY=...            # or PLANTCRAFT_APP_KEY_FILE=/path/to/key
modelcraft serve --port 8130               # http://127.0.0.1:8130/model/
modelcraft check                           # app key, PlantCraft and the runner reachable
```

With OpenModelica installed on the machine, `MODELCRAFT_RUNNER=local` runs the same runner code
in the app's process instead (development only).

| Variable | Default | Meaning |
|---|---|---|
| `PLANTCRAFT_URL` | `http://127.0.0.1:8060` | PlantCraft as Models reaches it |
| `PLANTCRAFT_PUBLIC_URL` | (same host) | PlantCraft as the browser reaches it, for sign-in |
| `PLANTCRAFT_APP_KEY`, `PLANTCRAFT_APP_KEY_FILE` | empty | App key: Models reports its runs to PlantCraft |
| `MODELCRAFT_ROOT_PATH` | `/model` | Path prefix the proxy forwards unchanged |
| `MODELCRAFT_DATA_DIR` | `var` (`/data` in the image) | SQLite database, run results and FMUs |
| `MODELCRAFT_RUNNER` | `suite` | `suite`: the runners on PlantCraft's compute workers (needs the app key); `queue`: a runner sharing `MODELCRAFT_JOBS_DIR`; `local`: omc on this machine |
| `MODELCRAFT_JOBS_DIR` | `<data dir>/jobs` | Where the answers are collected; with `queue`, the folder shared with the runner |
| `MODELCRAFT_ALLOW_EXTERNAL` | `false` | Allow `external` functions (C code) in models |
| `MODELCRAFT_CHECK_SECONDS`, `MODELCRAFT_RUN_SECONDS` | `120`, `600` | Time limits of a check or diagram, of a simulation or export |
| `MODELCRAFT_RUN_WORKERS` | `2` | Jobs given to the runner at the same time (about half the cores) |
| `MODELCRAFT_STUDY_MAX_RUNS` | `500` | The most simulations one study may hold |
| `MODELCRAFT_EXAMPLES` | `true` | Create the example projects at the first start |
| `MODELCRAFT_EXAMPLE_STUDY` | `true` | Queue the example study (three controller gains on the tank) once, so it is ready to read |
| `MODELCRAFT_HOST`, `MODELCRAFT_PORT` | `127.0.0.1`, `8130` (`0.0.0.0` in the image) | Bind address and port |

In the suite, PlantCraft Models runs as the `modelcraft` service of PlantCraft's compose file
and its runner as `modelcraft-executor` on PlantCraft's compute workers (the installation's own,
and any other machine's: PlantCraft docs/compute.md), both built from this repository's `Dockerfile` (`make image`) and
`deploy/runner/Dockerfile` (`make runner-image`). The app image carries its SPDX SBOM at
`/app/sbom.json`; `make package` builds the signed `modelcraft-<version>.pcapp` with
PlantCraft's `deploy/package.sh`.

## Develop

`make test-fast` is the quick loop while working (no slow tier); `make ci` runs what CI runs: the app standard check, ruff, the frontend build and tests, and
pytest (the API against `FakePlantCraft` and a recorded runner, the real runner code on a stand-in
omc, the Modelica text edits, hostile inputs, architecture, offline). `make e2e` runs the
Playwright journeys; with `MODELCRAFT_E2E_JOBS` naming a running runner's jobs folder they run
against the real OpenModelica. Read [AGENTS.md](AGENTS.md) before changing anything.

## How it is built

PlantCraft Models is **vibe coded**: written almost entirely by [Claude Code](https://claude.com/claude-code)
(Anthropic's Claude Opus 5.5 model), directed by a process engineer who decides what to build,
reviews the results and owns every decision. We say so openly. It is how one person with an AI
agent can bring industrial software within reach of researchers and process engineers who would
never get a licence for it, and it is why the rules are strict: one standard for every module,
tests that fail on network access, junk input, upward imports and slow tests, oracles on public
data, and a security audit per stage ([AGENTS.md](AGENTS.md)). The suite is also meant to be
used with AI. More in PlantCraft's
[How we build](https://github.com/PlantCraft/PlantCraft/blob/main/docs/how-we-build.md).

## License

Apache-2.0 ([LICENSE](LICENSE)). OpenModelica runs as a separate program in its own container and
is not part of this code. Third-party software: [ATTRIBUTION.md](ATTRIBUTION.md).
