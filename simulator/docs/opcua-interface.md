# OPC UA interface

PlantCraft Simulator has two servers, `simcraft serve` (the benchmark) and `simcraft loops serve`
(the 50-loop portfolio of the PlantCraft demo). Both register the same namespace URI and are
never served from one process; their NodeIds do not overlap.

## Namespace

```text
urn:processcraft:plantcraft
```

Until 0.4.0 the benchmark used a repository URL and PlantCraft's demo server used `urn:processcraft:simulator`. A client resolves the runtime
namespace index from the URI; the endpoint path is not checked by the server, so
`opc.tcp://host:4840/processcraft/simulator/` still connects to `/plantcraft/`.
`simcraft loops serve --namespace-uri urn:processcraft:simulator` (or
`SIMCRAFT_NAMESPACE_URI`) serves the loops under the old URI while a client is being
updated; the benchmark URI is fixed because it is part of the benchmark identity.

## Loop portfolio (`simcraft loops serve`)

```text
Objects
└── CPM
    └── Loops
        └── <LOOP_ID>            properties Name, Behavior, Description, EngineeringUnit
            ├── PV, SP, OP       Double
            ├── MODE             String, "AUTO" or "MAN" (written only when it changes)
            └── SECONDARY        Double, five interaction loops only
```

String NodeIds are `CPM.Loops.<LOOP_ID>.<SIGNAL>`, 205 in all; `simcraft loops catalog` prints
them with each loop's texts. On a fresh start the server backfills `SIMCRAFT_HISTORY_HOURS`
(48) of history at `SIMCRAFT_HISTORY_SAMPLE_SECONDS` (30) before the port opens, then writes
every `SIMCRAFT_REALTIME_SECONDS` (1) and historizes numeric values at most every
`SIMCRAFT_HISTORIAN_SECONDS` (5). Retention is two days. The dynamic state (true PV,
integral, OP, valve position, sensor bias, dead-time buffer) is saved in `SIMCRAFT_STATE_DB`;
a restart simulates the time it was down instead of jumping. Inconsistent files are recreated.
Values carry `Good` status and equal source and server timestamps.

## Settings

| Variable | Server |
|---|---|
| `SIMCRAFT_ENDPOINT` | both (bind) |
| `SIMCRAFT_HISTORY_DB`, `SIMCRAFT_STATE_DB` | loops |
| `SIMCRAFT_HISTORY_HOURS`, `SIMCRAFT_HISTORY_SAMPLE_SECONDS` | loops |
| `SIMCRAFT_REALTIME_SECONDS`, `SIMCRAFT_HISTORIAN_SECONDS` | loops |
| `SIMCRAFT_NAMESPACE_URI` | loops, health check |
| `SIMCRAFT_LOG_LEVEL` | loops |
| `SIMCRAFT_HEALTH_ENDPOINT` | health check |
| `SIMCRAFT_MAX_SAMPLE_AGE_SECONDS` | health check |

The benchmark's historian path is the `--history-db` option only (default
`var/history.sqlite3`), so it can never adopt the portfolio's historian file.

## Benchmark hierarchy (`simcraft serve`)

Logical hierarchy:

```text
Objects
└── Plant
    ├── ControlLoops
    │   └── <LOOP>
    │       ├── PV
    │       ├── SP
    │       ├── OP
    │       ├── MODE
    │       └── MVFB
    └── Areas
        └── <AREA>
            └── <EQUIPMENT>
                └── <SIGNAL>
```

Each Variable exposes `SignalId`, `EngineeringUnit`, and `DescriptionPtBr`
properties. Stable string identifiers are listed in the signal catalog. A
client must resolve the runtime namespace index from the namespace URI rather
than assuming `ns=2`.

## Time and quality

Each published `DataValue` carries source and server timestamps. Normal values
use `Good`; deliberate bad-quality cases use `Bad`; irregular-cadence cases use
`Uncertain` and retain their shifted source timestamp. Gap and communication
loss scenarios omit observations rather than fabricating zeroes.

Historical reads return the values, statuses, and timestamps that were
observed. This follows the OPC UA Part 11 principle that raw historical data
represent what a subscriber would have seen at that time.

Source timestamps are normalized to UTC before SQLite encoding and query
bounds use the same representation. Both interval endpoints are inclusive.
Ascending and reverse reads are supported; empty ranges return no values.
Responses are capped by the selected runtime profile and use OPC UA
continuation points without repeating or skipping the boundary sample.

Different catalog cadences remain different in history. `Good`, `Uncertain`,
`Bad`, and `BadNoCommunication` have explicit status-code mappings. Gap and
communication-loss scenarios do not create synthetic zeroes or historical
rows; recovery resumes with a fresh `Good` value and timestamp. Irregular
cadence retains different source and server timestamps.

## Retention and restart

When history is enabled, each node is pruned against the configured retention
window as new values arrive. Observation rows and the simulator checkpoint are
committed in one SQLite transaction. The checkpoint pins benchmark version,
catalog digest, namespace, seed, UTC origin, elapsed time, integration step,
publication cadence, and scenario cycle.

On restart, the deterministic model replays to the checkpoint without writing
the bootstrap period again. If wall-clock time advanced while the server was
offline, the model then advances deterministically across that interval and
writes one current frame; the outage remains an explicit gap rather than a
fabricated historical stream. Existing historical rows otherwise remain
unchanged and live publication continues from the next frame. A configuration
mismatch fails before the endpoint starts. A database containing observations
without a complete checkpoint is treated as an interrupted bootstrap and
requires an explicit `--reset`; it is never silently repaired or duplicated.

## Security boundary

Both servers implement only an anonymous `NoSecurity` development profile; the
local `compose.yaml` publishes the port on host loopback and the suite keeps it on
the `plant` network without publishing it. This profile is not suitable for an
untrusted network. Certificate-based SignAndEncrypt profiles and user identity
configuration are required before any non-local deployment guidance.

## Compatibility test

The server publishes a non-historized `Plant.SimulatorHeartbeat` technical node
outside the 500-Signal scientific catalog. Its source timestamp advances with
each simulation frame even when a declared scenario intentionally suppresses
Signal observations. The container healthcheck reads this node and rejects
stale or implausibly future source timestamps in addition to checking server
state; it therefore measures process liveness without erasing simulated data
unavailability. The loop portfolio has no heartbeat node; the same health check
(`python -m simcraft.healthcheck`) reads `CPM.Loops.FIC-1001.PV` there instead.

The automated suite starts the server on ephemeral loopback ports and resolves
the namespace by URI with an independent `asyncua` client. It verifies the
500-node map, current values and engineering metadata, multi-page Historical
Access, inclusive and reverse bounds, empty ranges, mixed cadences, status and
timestamp preservation, gaps, recovery, retention, restart continuity, and
checkpoint mismatch rejection.
