# OPC UA demo plant (the Simulator)

The demo reads a simulated plant over OPC UA: the Simulator's 50-loop portfolio
(`simcraft loops serve`). The Simulator is its own product (`simcraft`, in `simulator/`); until 0.4.0 the same simulator lived here as
`processcraft/simulator` (gap G31, closed 2026-10-19). PlantCraft reads it
like any other OPC UA server, through OPC UA Historical Access, and never
imports it. The Simulator's own documentation (`docs/opcua-interface.md` in its
repository) is the reference for its nodes, settings and history.

The case is deliberately generic: it exercises the platform and the apps
without depending on any real plant.

## Quick start

Install PlantCraft and the Simulator into the same Python environment, then run
the integrated command:

```bash
python3 -m pip install -e sdk/python -e '.[server,opcua]'
python3 -m pip install -e simulator         # the Simulator, in simulator/
python3 run_opcua_demo.py --browser
```

This command:

1. starts `simcraft loops serve` at `opc.tcp://0.0.0.0:4840/plantcraft/`
   (from the `simcraft` command, or `python -m simcraft` when only the
   package is importable), with its historian and state in `var/simcraft/`;
2. waits for the Simulator to finish the initial 48 hours of history (the first
   start takes the longest);
3. opens the platform with `scenarios/opcua_demo.json`, reading
   `opc.tcp://127.0.0.1:4840/plantcraft/`;
4. stops the Simulator when the platform exits.

When something already listens on port 4840 the script uses it and starts no
server, so the Simulator can also run on its own (`simcraft loops serve`) or in
a container. Without the Simulator installed and with nothing on port 4840, the
script says how to install it and stops.

With Node.js 22 installed, the script builds the interface on its own when
`frontend/dist` is missing or out of date (`--skip-build` turns this off). The
platform opens at http://127.0.0.1:8060.

Other options:

```bash
python3 run_opcua_demo.py --reset            # renew: the Simulator's history and a fresh workspace
python3 run_opcua_demo.py --reset-simulator  # rebuild the Simulator's 48 simulated hours only
```

To run the components separately:

```bash
simcraft loops serve
plantcraft --scenario scenarios/opcua_demo.json --browser
```

## The loops

The loops cover ten conditions. The first ten are the reference cases:

| Loop | Behaviour | Expected evidence |
|---|---|---|
| FIC-1001 | healthy | good tracking and low variability |
| PIC-1002 | oscillation | dominant period close to 12 minutes |
| FIC-1003 | stiction | OP in steps and jumps |
| LIC-1004 | saturation | OP close to 100% and a permanent error |
| TIC-1005 | manual | about six hours a day in MAN |
| AIC-1006 | noise | high-frequency variation on the PV |
| FIC-1007 | setpoint activity | campaign change every 30 minutes |
| PIC-1008 | drift | growing bias compensated by the OP |
| TIC-1009 | disturbance | recurring load steps |
| LIC-1010 | interaction | lagged correlation with a secondary variable |

The other forty (`FIC-1101` and onwards) repeat these behaviours across
distillation, utilities and other areas, with different seeds, units and
dynamics. `scenarios/opcua_demo.json` lists all fifty with their signals by
role; PlantCraft shows each one as a loop asset and Analytics picks the
methods that suit it. `simcraft loops catalog` prints the Simulator's list, and
`tests/test_opcua_demo.py` checks the scenario against it whenever the Simulator
is installed.

Each loop's `metadata.loop_type` (flow, level, pressure, temperature,
composition) is written in the scenario from its ISA 5.1 tag letter and checked
against the engineering unit the Simulator gives its PV. The sync copies it, and
any `criticality`, `action` or `controller` a scenario loop gives, into the
loop's record where the record has no value yet, so Analytics can choose an
algorithm; a value a person set stays. PlantCraft never guesses a type from a
client's tag.

These behaviours are known hypotheses of the simulator. On real data, the same
methodological result is only screening evidence and needs operational
confirmation.

## Tags and namespace

The namespace is `urn:processcraft:plantcraft` (the default of every OPC UA
source). Variables use string NodeIds, 205 in all:

```text
CPM.Loops.<LOOP_ID>.PV
CPM.Loops.<LOOP_ID>.SP
CPM.Loops.<LOOP_ID>.OP
CPM.Loops.<LOOP_ID>.MODE
CPM.Loops.<LOOP_ID>.SECONDARY    five interaction loops only
```

The scenario's tags are derived from the variables configured on each loop, so
there is no second list to drift. `PLANTCRAFT_OPCUA_ENDPOINT` overrides the
endpoint declared in the scenario.

A workspace or source saved before 2026-10-19 may still name
`urn:processcraft:simulator` and `/processcraft/simulator/`: the Simulator ignores
the endpoint path, and `simcraft loops serve --namespace-uri
urn:processcraft:simulator` serves the old namespace while such a source is
edited.

## History and continuity

The Simulator backfills 48 hours at a 30-second step, then writes every second and
historizes every 5 seconds; retention is two days. Its dynamic state survives
restarts: it simulates the time it was down instead of jumping. The settings
are the Simulator's `SIMCRAFT_*` variables (`SIMCRAFT_HISTORY_HOURS`,
`SIMCRAFT_HISTORY_DB`, `SIMCRAFT_STATE_DB`, ...), listed in its
documentation.

## Containers

```bash
make image simcraft-image      # simcraft-image builds from simulator/ (SIMCRAFT_SRC)
deploy/install.sh --dev --demo
```

The `demo` profile runs the Simulator's image `simcraft:${SIMCRAFT_VERSION}`
(0.5.0) as the `simcraft` service (also reachable as `plantcraft`, its host name before 0.5.0): uid 10004, the `plant` network only, the
suite's hardening, its history and state in `data/simcraft`, and the Simulator's
own OPC UA health check. Port `4840` is not published on the host: add it as an
OPC UA source in PlantCraft at `opc.tcp://plantcraft:4840/plantcraft/`. See
[install-offline.md](install-offline.md) for the full topology and for bundles
with and without the Simulator.

The demo endpoint uses `NoSecurity` and anonymous access to reduce local
friction, so it must stay isolated. In a real industrial integration, enable
certificates, a signing/encryption policy and authentication even when the
endpoint is on a private network.

## Tests without the Simulator

CI cannot install the Simulator (a separate, private repository). The OPC UA
round trip in `tests/test_opcua_demo.py` therefore runs against
`tests/opcua_plant.py`, a small asyncua server that publishes the same address
space (namespace, `CPM/Loops/<loop>` objects, NodeIds, `Name` and
`EngineeringUnit` properties) for the scenario's loops with a few minutes of
synthetic history. It reproduces the interface, not the dynamics. With
The Simulator installed, the same file also checks the scenario against
`simcraft loops catalog` and reads all 205 tags from a real
`simcraft loops serve`.
