# The Modelica runner (administrators)

Models does not compile or run models in its own container. It hands every check, diagram,
simulation and export to the **Modelica runner**, a separate container with OpenModelica 1.24
and the Modelica Standard Library 4.0.0:

- **No network at all** (`network_mode: none`): it cannot reach the plant, PlantCraft or the
  internet.
- **No secrets**: no app key, no token, no database.
- **Read-only** root filesystem, no Linux capabilities, its own user (uid 10011).
- **Limits**: CPU, memory and number of processes in the compose file; each job has a time limit
  (2 minutes for a check or diagram, 10 for a simulation or export), a memory limit and a file
  size limit, and runs in its own process group, which is killed at the time limit.

Models and the runner share only a jobs folder: Models writes a job (the model's files and
what to do), the runner answers with the results. Models checks every job before it leaves (no
`external` code, no file or system functions), and the runner checks it again.

## Built models are kept

Building a model (OpenModelica turns it into a C program and compiles it) takes most of a
simulation's time: about 5 seconds for the examples, against a fraction of a second to run it.
The runner keeps the last 32 models it built for studies in its own `/tmp` (never in the jobs
folder, which Models can write): a study's next batch, or the next step of an optimization, with
the same files, model and simulation settings runs the program it already has and only changes
the parameters. Any change to a file builds again. A restart of the runner empties it.
`--cache ""` (or `MODELCRAFT_RUNNER_CACHE=`) turns it off.

## Its state

The Overview shows whether the runner is available, its OpenModelica version and its
library. The runner writes a heartbeat every 10 seconds; when it stops, Models says so, keeps
editing open and refuses checks and simulations until it is back. The simulation queue is kept in the
database: simulations that were running when Models restarted wait in the queue again (an FMU
export that was going on is marked failed).

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `MODELCRAFT_RUN_WORKERS` | `2` | Jobs given to the runner at the same time (a quick simulation, or a batch of a study). Size it to the cores the runner may use: about half of the machine's |
| `MODELCRAFT_RUN_BATCH` | `10` | Simulations of a study built once and run one after the other in one job |
| `MODELCRAFT_STUDY_MAX_RUNS` | `500` | The most simulations one study may hold (the new-study page warns above 100) |
| `MODELCRAFT_CHECK_SECONDS` | `120` | Time limit of a check or a diagram |
| `MODELCRAFT_RUN_SECONDS` | `600` | Time limit of a quick simulation or an export, and of a study's simulation that sets none |
| `MODELCRAFT_MAX_RUN_SECONDS` | `21600` | The longest time limit a study may set for each simulation (6 hours) |
| `MODELCRAFT_ALLOW_EXTERNAL` | `false` | Allow `external` functions (C code) in models. Leave off unless every editor is trusted to run code on the server |
