# Compute workers

The apps of the suite never run the code people write inside their own containers. Analytics'
blocks and algorithms, and Models' simulations, run on **compute workers**: machines of the
internal network that an administrator registers in PlantCraft › Settings › Compute. One worker
comes with every installation; more workers, on this machine or on others, spread the load when
many people run at once. Decided by the owner on 2026-10-26 (plan "Workers de cálculo", D1 to
D10); this page is the reference.

## How a task travels

```text
app (Analytics, Models)          PlantCraft                      a worker
  reads the data it needs   -->  queue of compute tasks  <--  gateway: asks for tasks when it
  with its own token,            (Settings › Compute)         has room; no open port
  packs a job folder        <--  the answer               -->  executor of the app: runs the
  reads result.json + out/                                     task with no network, no secret
```

1. The app reads the data a task needs with its own token and packs a **job folder**: `job.json`
   and the files its executor reads, as a tar archive. It sends it with
   `POST /api/v1/compute/tasks` (`ComputeClient.submit`), with the app's version, a priority and
   optional labels.
2. A worker's **gateway** asks PlantCraft for tasks (`POST /api/compute-worker/lease`) for the
   executors beside it that have room, waiting up to 20 seconds for one. PlantCraft gives each
   task to one worker at a time, for a lease of 30 seconds that the gateway renews every 10.
3. The gateway puts the task in the executor's folder; the **executor** runs it and writes
   `result.json` and the files under `out/`; the gateway sends them back.
4. The app waits (`POST /api/v1/compute/wait`, `ComputeClient.answers`), reads the answer and
   drops it (`DELETE`). PlantCraft keeps answers nobody collected for an hour and the task rows
   for 7 days (the numbers of Settings › Compute).

PlantCraft never opens an archive. Only an app's own token sends tasks (`write.compute` in its
`[permissions]`), and an app sees only its own tasks.

## Who runs what first

- A task runs only on an executor of **its app and version** (a worker updated later than the
  app, or earlier, gets none of its tasks until both match) and on a worker with **all its
  labels** (for example `big-memory`, given when the worker is added).
- **Priority**: `interactive` (someone clicked and waits: Test, Run now, Simulate) before `run`
  (monitors on their cadence) before `backfill` (history, large sweeps).
- Among the apps of one priority, the app served longest ago goes first, so one app's thousand
  tasks never hold another's back.
- Each executor has slots (by default the machine's cores less one); a gateway asks only for as
  many tasks as it has free slots. That is the whole load balancing: a busy worker asks for
  nothing, a free one asks.

## Environments and sizes

Each algorithm of Analytics and each simulation or study of Models says **where it runs**
(decided 2026-10-26, on the owner's ask that a model or algorithm name the image and the machine
it needs):

- **Environment**: the executor image with the packages the code needs. `standard` is the app's
  own image, which every worker has. Another environment (for example `ml`, with extra wheels)
  is an executor started with `--environment ml` from an image built for it; a task of that
  environment goes only to a worker running such an executor.
- **Size**: the CPUs and memory one task needs.

| Size | CPUs | Memory | Goes to |
|---|---|---|---|
| `small` (the default) | 1 | 1 GB | any worker |
| `medium` | 2 | 4 GB | a machine with at least 2 CPUs and 4 GB |
| `large` | 4 | 16 GB | a machine with at least 4 CPUs and 16 GB |

Each worker's gateway reports its machine (CPUs and memory, 10 % margin on the memory) and the
environment of each executor beside it; PlantCraft gives a task only to a worker whose executor
runs its app, version **and environment** and whose machine has room for its **size**. A worker
that has not reported its machine yet takes only small tasks, and an executor's own memory per
task (its `--memory-mb`, in its heartbeat) caps the size it takes, whatever the machine has. The memory a task may use is the
larger of its size's and the app's limit, never above what the executor allows
(`--memory-mb`).

The app passes both with `ComputeClient.submit(..., environment=, size=)` (query parameters of
`POST /api/v1/compute/tasks`); `GET /api/v1/compute/capacity` takes them too and lists the
`environments` and `sizes` the workers online offer. Analytics keeps them in the algorithm
(page Versions › Where it runs, a new version; `compute` in its method config) and sends a
loop's analysis, a run on an asset and the editor's Test with them; Models keeps them in the
simulation or study (Simulation settings › Environment and Size). When no worker online offers
what a task asks, it waits and Settings › Compute warns, naming the environment and size.

A custom environment is an image built on the app's own, with the wheels it needs from a local
folder (the platform stays offline):

```dockerfile
FROM linkcraft:<version>
COPY wheels/ /tmp/wheels/
RUN pip install --no-index --find-links /tmp/wheels scikit-learn && rm -rf /tmp/wheels
```

and an executor service like `linkcraft-executor` with that image, the command's
`--environment ml`, and the folder `data/compute-jobs/linkcraft.ml` mounted as its jobs folder
(`PLANTCRAFT_COMPUTE_ENVIRONMENT=ml` does the same as the flag). The gateway finds it by its
heartbeat.

## When something fails

| What happens | What the suite does |
|---|---|
| The task's code raises, runs out of time or memory | The executor stops that task alone (its own process) and answers `{"status": "error", "error"}`; the app shows the reason |
| The task is cancelled (`POST .../cancel`, a cancelled run) | The worker hears it at its next heartbeat and stops it |
| An executor stops (its heartbeat is a minute old) while its gateway runs | The gateway gives its tasks back at once, for another worker |
| A worker is revoked | Its gateway is refused, says so in its log and waits to be stopped (no restart loop); "Enroll again" in Settings › Compute gives it a new one-time code under the same name |
| PlantCraft restarts while an app waits for answers | The app keeps waiting (up to 5 minutes unreachable): the tasks are in PlantCraft's database |
| A worker stops answering (machine off, network cut) | Its tasks' leases run out (30 s) and they go back to the queue, for another worker; after three tries a task fails with the reason |
| No worker online runs an app's tasks | They wait; after 2 minutes System tells the administrators in Messages, and the app shows "waiting for a compute worker" (`GET /api/v1/compute/capacity`) |
| PlantCraft restarts | The queue is in its database: nothing is lost |

## Security

- The gateway opens **no port**: it calls PlantCraft, over the proxy's HTTPS from another machine
  or over the internal network on this one. One firewall rule is enough: the worker to
  PlantCraft, port 443.
- A worker enrolls with a **one-time code** an administrator makes (valid 15 minutes) and gets a
  credential of its own (`pcw_…`), kept by PlantCraft only as a hash. It opens the workers'
  routes and nothing else: no signal, asset, person or result. An administrator pauses (the
  worker ends what it runs and takes nothing more) or revokes it at once; each change is in the
  audit log.
- The **executor** is the sandbox: no network at all (`network_mode: none`), no secret, a
  read-only image, no capabilities, limits on CPU, memory and processes, and a time and memory
  limit per task. It shares only its job folder with the gateway. The checks of block code
  (`plantcraft_sdk.sandbox`) stay as a second layer.
- Archives are read with care in both directions: plain files and folders only, no link, no
  absolute path, no `..`, at most 64 MB and 10,000 files. An answer comes from code people
  wrote, so the gateway never follows a link out of the job's folder, and keeps its credential
  outside the job folders.
- Tasks carry only the data they need: a worker never reads the plant and holds no app key.

## Running a worker

The two parts are `python -m plantcraft_sdk.compute gateway` (in PlantCraft's image) and
`python -m plantcraft_sdk.compute executor --app <id> --handler <module:function>` (in each
app's own image, so its version always matches the app's). They share one folder per app:

```text
<jobs>/<app>/queue/<id>/      a task, renamed in whole by the gateway (job.json, task.json, files)
<jobs>/<app>/work/<id>/       claimed by the executor (an atomic rename)
<jobs>/<app>/work/<id>/cancel written by the gateway: stop this task
<jobs>/<app>/done/<id>/       the answer (result.json, out/), renamed in when complete
<jobs>/<app>/runner.json      the executor's heartbeat: app, version, environment, workers, memory_mb, at
```

An executor of another environment than `standard` uses the folder `<jobs>/<app>.<environment>/`
(below).

This is the protocol PlantCraft Models' runner has used from the start, so it runs behind a
gateway as it is (`modelcraft-executor`, below). `plantcraft_sdk.compute.selftest:answer` is a handler for
trying a worker end to end (`echo`, `sleep`, `fail`, `sum`).

The administrators' routes (session, administrators only) are `GET /api/compute` (workers,
queue per app and priority, limits), `POST /api/compute/workers` (a name and labels: the
one-time code and the command for the other machine), `POST /api/compute/workers/{id}/code`,
`.../pause`, `.../resume`, `.../revoke`, `DELETE /api/compute/workers/{id}` and
`PUT /api/compute/limits/{app}` (`timeout_seconds`, `memory_mb`). `GET /api/compute/summary` (anyone signed in) gives the workers per
app for the Queue panel: names, states, environments, slots, what runs and the largest size, no
host, label or credential. The workers' routes are
`POST /api/compute-worker/enroll`, `.../lease`, `.../heartbeat`,
`GET /api/compute-worker/tasks/{id}/input` and `POST /api/compute-worker/tasks/{id}/answer`.

Settings: `PLANTCRAFT_COMPUTE_MAX_MB` (64), the most a task takes or gives;
`PLANTCRAFT_COMPUTE_LOCAL_KEY_FILE`, the credential of the installation's own worker, written
by `install.sh`.

### The installation's own worker

`deploy/compose.yaml` runs one worker on PlantCraft's machine from the start: the service
`compute-gateway` (user 10020, PlantCraft's image) on the internal network `compute`, which only
PlantCraft shares, with `data/compute-jobs/` as its job folders. `install.sh` writes its
credential once to `data/compute-local-key` (read by the gateway and, for its hash, by
PlantCraft), so it shows in Settings › Compute as `local`, already enrolled. Each app's
executor joins it as a service of the app's profile with `network_mode: none`, mounting only
`data/compute-jobs/<app>/`. The gateway writes `gateway.json` in the jobs folder each time
PlantCraft answers its heartbeat; the container's healthcheck reads it.

### Settings › Compute

The page `/setup/compute` (administrators) lists the workers with their state (online, paused,
offline, waiting for its machine, code expired, revoked), the apps and versions each runs with
its free slots, the machine's CPUs, load and memory, and its tasks of the last 24 hours. Add
worker shows the one-time code and the command for the other machine once. Each app has its
numbers (waiting, running, done and failed in 24 h) and its limits per task (time, memory). A
warning shows when tasks of an app wait for 2 minutes with no online worker running their
version; the same goes to the administrators in Messages.

### Analytics on the workers

Analytics (`linkcraft`) sends three kinds of task, each with up to 25 items (D6):

| Kind | What runs on the worker | Priority |
|---|---|---|
| `loop` | a loop's analysis (its methods or its algorithm's diagram) on the data the app read | `run` (rounds and executions), `backfill` (replays) |
| `signals` | the signal quality checks of a chunk of signals | `run` |
| `code` | one call of a site block's code, for a diagram that runs in the app (the editor's Test, runs on assets) | `interactive` (Test), `run` |

The app's container reads the plant's data and sends it; the executor `linkcraft-executor` (the
app's own image, `--handler linkcraft.api.compute:answer`) runs only the functions the app names
in `linkcraft.engine.suite_compute.CALLS`, on plain data: JSON, with frames, series and arrays
as their exact bytes (`linkcraft.engine.wire`), never pickle. A task carries the files of the
site's block versions its diagrams use. Cancelling an execution cancels its tasks (the run is
the execution). `LINKCRAFT_COMPUTE=local` runs everything in the app's container, as before.

### Models on the workers

Each check, diagram, simulation, sweep and FMU export of PlantCraft Models (`modelcraft`) is
one task of the kind the job is (`check`, `simulate`, `sweep`, `fmu`, ...), with the run's id
as its run and the job's time limit plus a minute. The executor `modelcraft-executor` is the
Modelica runner (`modelcraft-runner` image, OpenModelica and the Modelica Standard Library,
`python3 /opt/runner/runner.py`): it writes every `omc` script itself from the job's checked
fields, as before. Its heartbeat names its version `runner-<protocol>`, which Models asks for,
so a worker with another runner protocol never takes Models' jobs. The answer (result.json and
the files the runner keeps under `out/`) comes back to Models' `data/jobs/collected/`.
Cancelling a run cancels its task. While a simulation runs on a worker, Models does not follow
its progress (its partial results stay on the worker): the run shows as running until it
ends. `MODELCRAFT_RUNNER=queue` hands the jobs to a runner sharing a folder with Models instead
(development), `local` runs omc in Models' own process.

### A worker on another machine

On the other machine, with the same release bundle (Docker and the Compose plugin):

```bash
./install.sh --worker --platform https://plantcraft.plant.local --code 7K2M-9QXD \
    --ca local-ca-root.crt
```

The code and the command come from Settings › Compute › Add worker; `--ca` is PlantCraft's
`local-ca-root.crt` when its certificate is the local CA's. The worker's folder
(`/opt/plantcraft-worker`, or `--prefix`) holds `compose.yaml` (the bundle's
`compose-worker.yaml`), `.env` and `data/`: the gateway trades the code for its credential
(`data/worker/credential`, 0600, user 10020) on its first start, and `install.sh` takes the
code out of `.env`. Each app of the bundle with an executor runs in its profile. The gateway's
network reaches PlantCraft only through the machine's routes; the executors have none. Running
`./install.sh --worker` again in that folder applies an update of the bundle.
