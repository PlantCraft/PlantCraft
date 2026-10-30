<p align="center"><img src="docs/images/logo.svg" width="72" height="72" alt="PlantCraft Analytics"></p>

# PlantCraft Analytics

Signal quality and control loop performance for process plants, as an app of the
[PlantCraft](https://github.com/PlantCraft/PlantCraft) suite. PlantCraft Analytics is the former
CPMCraft and DataCraft made one app (owner decision D9).

PlantCraft Analytics checks every signal of a plant for bad data, and every control loop for oscillation,
sticking, saturation and manual mode, on a cadence, and says why. The loop methods read the
signal results first: a frozen transmitter reads "data not usable", not "bad tuning".

- **Overview**: what needs attention, each kind of target by status and the latest runs; "Open
  dashboard" goes to PlantCraft View (`/dash/`). Analytics also publishes widgets for the
  PlantCraft Overview (`/api/widgets`).
- **Signals** from PlantCraft's signal catalog, each with its result (good, suspect, bad,
  unknown), quality 0-100, the events each check found on its chart, and its own settings.
- **Loops** from PlantCraft assets of kind `loop` (synced every run; registered on
  PlantCraft's Assets page); trends, limiting criterion, findings and a PDF.
- **Results**: what any algorithm concluded on any asset, filtered by algorithm, label, asset
  type, group and status, with a PDF **Report** of what the filter keeps, and a **Run history**
  tab: every run of every algorithm on one list. Each asset has its page: every algorithm's
  result on it and its signals' quality.
- **Algorithms**: diagrams of blocks with typed inputs and outputs, checked before they run.
  Six ship, authored by PlantCraft: **Flow loop**, **Level loop**, **Surge level**,
  **Temperature or pressure loop**, **Signal quality** and **Unit twin**; people duplicate one
  and draw their own, with labels, an owner, a version and a responsible group. Each says where it is used. The monitors (interval,
  hour, day, week or once) are below the list.
- **Blocks** in seven libraries: inputs, **Data quality** (the loop data check and 8 checks on
  signals), transforms, **Control loop performance** (one per method), **Models** (one per
  published FMU, and the deviation of the plant from it), logic and outputs, each
  with its ports, parameters, formula, references and limits.
- **Help** in the suite's help browser: guides and a page per method.

## How it fits the suite

```text
browser ── proxy ─┬─ /       PlantCraft             users, sign-in, connections (PI, OPC UA), assets, signals
                  ├─ /link/  PlantCraft Analytics        signals, loops, blocks, algorithms, runs, reports (own SQLite)
                  └─ /dash/  PlantCraft View  dashboards (reads Analytics' results and series)
PlantCraft Analytics ── PlantCraft API v1 (plantcraft-sdk) ──> series, values, assets, audit
```

PlantCraft Analytics never opens a historian or an OPC UA connection: all plant data comes
from the PlantCraft API v1 through `plantcraft_sdk.client`. People sign in
at PlantCraft; PlantCraft Analytics verifies their token offline (`TokenVerifier`, app id
`linkcraft`) and records every change in PlantCraft's audit log. Background
work uses a service token obtained with an app key.

PlantCraft Analytics follows the PlantCraft app standard (it is the reference app):

- `app.toml` is the one source of its metadata (id `linkcraft`, prefix `/link/`, port 8140,
  uid 10012); the image labels (`org.processcraft.app.{id,prefix,port}`), `make image` and
  `/link/api/meta` read it.
- It publishes each loop's health as a `linkcraft.loop_health` result on `asset:<id>` and, one
  point per run, as the derived series `app-linkcraft:<loop id>.<algorithm>.health` (`/100`);
  each output an algorithm records as `app-linkcraft:<asset>.<algorithm>.<output>` and each
  algorithm's version as `app-linkcraft:algorithm.<id>.version`; each signal's result as a `linkcraft.signal_quality`
  result on the signal and on each asset (the worst of its signals), and as the derived series
  `app-linkcraft:<signal id>.quality` (`/100`); its findings as `linkcraft.finding.opened|closed`
  events and, for the Alarms app to decide on, only what changes: `linkcraft.status.changed`
  (a target's state in a monitor), `linkcraft.run.failed` (once per run of a monitor) and
  `linkcraft.schedule.stalled` (one condition per monitor) (`api/events.py`: monitor,
  algorithm, version, owner and severity in the payload; an Alarms rule reads the outputs as
  the series above); its rounds and Signal quality runs as runs, and its monitor list. A loop is judged on
  its signals' latest in-app results (the loop data gate decides when they are missing or
  stale). A PlantCraft without these endpoints is fine: each 404 is logged once.
- `/link/assets/<id>` opens the loop of that asset or says PlantCraft Analytics does not cover it;
  `/link/api/help` lists the help pages. Built files are served from `/link/static/`.

## Run it

```sh
python -m venv .venv && . .venv/bin/activate
make deps                                  # plantcraft-sdk from vendor/, then PlantCraft Analytics
(cd frontend && npm ci && npm run build)   # the interface, served under /link/

# In PlantCraft: PLANTCRAFT_APPS=linkcraft=/link/ plantcraft --port 8060,
# then an admin creates an app key for linkcraft (Settings, or POST /api/app-keys).
export PLANTCRAFT_URL=http://127.0.0.1:8060
export PLANTCRAFT_APP_KEY=...            # or PLANTCRAFT_APP_KEY_FILE=/path/to/key
linkcraft serve --port 8140                 # http://127.0.0.1:8140/link/
```

In the suite, PlantCraft Analytics runs as the `linkcraft` service of PlantCraft's
`deploy/compose.yaml` (profile `linkcraft`), built from this repository's
`Dockerfile` (`make image`; `make package` will build the signed `.pcapp` once
PlantCraft's `deploy/package.sh` lands, and is a stub until then).

| Variable | Default | Meaning |
|---|---|---|
| `PLANTCRAFT_URL` | `http://127.0.0.1:8060` | PlantCraft as PlantCraft Analytics reaches it |
| `PLANTCRAFT_PUBLIC_URL` | (same host) | PlantCraft as the browser reaches it, for sign-in |
| `PLANTCRAFT_APP_KEY`, `PLANTCRAFT_APP_KEY_FILE` | `<data dir>/linkcraft-app-key` | App key for background work |
| `LINKCRAFT_ROOT_PATH` | `/link` | Path prefix the proxy forwards unchanged |
| `LINKCRAFT_DATA_DIR` | `var` (`/data` in the image) | SQLite database and state |
| `LINKCRAFT_ROUND_MINUTES`, `LINKCRAFT_WINDOW_MINUTES`, `LINKCRAFT_RESAMPLE_SECONDS` | 10, 1440, 60 | Round cadence, analysis window, grid |
| `LINKCRAFT_SIGNAL_ROUND_MINUTES`, `LINKCRAFT_SIGNAL_WINDOW_HOURS` | 15, 24 | Signal quality monitor and window at first start (admins change them in the app) |
| `LINKCRAFT_SCHEDULER_ENABLED` | `true` | Rounds and monitors in the background |
| `LINKCRAFT_ENGINE` | `process` | Where the monitors and the queue run: `process` (a process of its own, started by `linkcraft serve`), `external` (a separate service runs `linkcraft engine`), `inline` (in the server's process) |
| `LINKCRAFT_WORKERS` | CPUs (2 to 8) | Runs the engine works on at the same time |
| `LINKCRAFT_LOOP_ASSET_KIND` | `loop` | Asset kind read as loops |
| `LINKCRAFT_COMPUTE` | `local` (`suite` in the suite's compose) | Where analyses and blocks' code run: processes here, or the suite's compute workers (PlantCraft `docs/compute.md`) |
| `LINKCRAFT_COMPUTE_SLOTS` | 8 | With `suite`: how many tasks a round expects to run at once (its chunks) |
| `LINKCRAFT_PROCESSES` | CPU count - 1 (max 16; 0 on 2 cores) | Processes analysing loops (`local`) |
| `LINKCRAFT_SIMULATION_WORKERS` | 2 | Processes running process models (FMUs) |
| `LINKCRAFT_SIMULATION_TIMEOUT` | 60 | Seconds one model run may take |
| `LINKCRAFT_MAX_MODEL_MB` | 200 | Largest model file an admin may publish |
| `LINKCRAFT_MODEL_UPLOAD` | on | Whether admins may publish models |
| `LINKCRAFT_LOG_LEVEL` | `INFO` | Log level |
| `LINKCRAFT_APP_TOML`, `LINKCRAFT_REVISION` | checkout's `app.toml` and git (`/app` and the build arg in the image) | What `/api/meta` serves |

## Develop

`make test-fast` is the quick loop while working (no slow tier); `make ci` runs what CI runs: `plantcraft-app check`, ruff, the frontend build and tests, and
pytest (methods, signal checks, blocks and algorithms, engine, API against `FakePlantCraft`, hostile
inputs, migration, architecture, offline). The interface draws the suite frame from
`@plantcraft/ui` (vendored with the SDK in `vendor/`). `python -m linkcraft.bench --loops 2000 --processes 4
--latency-ms 2` times a run in turn against an in-process PlantCraft. Read
[AGENTS.md](AGENTS.md) before changing anything.

## How it is built

PlantCraft Analytics is **vibe coded**: written almost entirely by [Claude Code](https://claude.com/claude-code)
(Anthropic's Claude Opus 5.5 model), directed by a process engineer who decides what to build,
reviews the results and owns every decision. We say so openly. It is how one person with an AI
agent can bring industrial software within reach of researchers and process engineers who would
never get a licence for it, and it is why the rules are strict: one standard for every module,
tests that fail on network access, junk input, upward imports and slow tests, oracles on public
data, and a security audit per stage ([AGENTS.md](AGENTS.md)). The suite is also meant to be
used with AI. More in PlantCraft's
[How we build](https://github.com/PlantCraft/PlantCraft/blob/main/docs/how-we-build.md).

## License

Apache-2.0 ([LICENSE](LICENSE)). Third-party assets: [ATTRIBUTION.md](ATTRIBUTION.md).
