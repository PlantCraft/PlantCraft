# PlantCraft Simulator spec

Category: plant simulators for testing industrial software. Tools in this category publish
simulated process signals through a standard interface (OPC UA here), with history, so
historians, analytics, monitoring and control software can be developed, tested and
demonstrated without a running plant. They range from tag simulators (sine, ramp, random) to
dynamic process models with injected faults. Tools studied (research only): commercial OPC UA
simulation servers and process training simulators; their public pages are still to be listed
(`docs/gaps.md`). Sources are public only (clean room, see AGENTS.md).

## Sources

| Source | Link | Read on |
|---|---|---|
| OPC UA Part 4: Services | https://reference.opcfoundation.org/Core/Part4/v105/docs/ | 2026-10-19 |
| OPC UA Part 8: Data Access | https://reference.opcfoundation.org/Core/Part8/v105/docs/ | 2026-10-19 |
| OPC UA Part 11: Historical Access | https://reference.opcfoundation.org/Core/Part11/v105/docs/ | 2026-10-19 |
| OPC UA Part 9: Alarms and Conditions | https://reference.opcfoundation.org/Core/Part9/v105/docs/ | 2026-10-19 |
| Downs and Vogel (1993), A plant-wide industrial process control problem | https://doi.org/10.1016/0098-1354(93)80018-I | 2026-10-19 |
| Bartyś et al. (2006), Introduction to the DAMADICS actuator FDI benchmark study | https://doi.org/10.1016/j.conengprac.2005.06.015 | 2026-10-19 |
| Choudhury, Thornhill and Shah (2005), Modelling valve stiction | https://doi.org/10.1016/j.conengprac.2004.05.005 | 2026-10-19 |
| Public pages of commercial OPC UA simulation servers | to be added (G7) | |

## Features

| Area | Feature in the target tools | Source | Ours | Test or oracle |
|---|---|---|---|---|
| Server | OPC UA server, browse and read of simulated variables | Part 4 | done (both servers) | `tests/test_server.py`, `tests/test_loops.py` |
| Server | Subscriptions to value changes | Part 4 | done (asyncua; not tested here) | |
| Server | Engineering units and descriptions on each variable | Part 8 | partial: properties, not the Part 8 `EUInformation`/`EURange` types (G5) | `tests/test_server.py` |
| History | Historical Access, raw reads with continuation points | Part 11 | done | `tests/test_server.py` |
| History | History available from the first connection (backfill) | category | done (benchmark per profile, loops 48 h) | `tests/test_loops.py` |
| History | Restart continues without gaps or duplicates | category | done | `tests/test_server.py`, `make smoke` |
| Signals | Configurable tag simulators (sine, ramp, random, step) | category | missing: models are fixed in code (G6) | |
| Signals | Status codes and timestamps per value (good, uncertain, bad, no communication) | Part 4, Part 8 | done (benchmark); loops publish `Good` only | `tests/test_server.py` |
| Process | Dynamic closed loops (PID, process, dead time, valve) | Downs and Vogel 1993 | done: 50-loop portfolio and 50-loop coupled benchmark | `tests/test_loops.py`, `tests/test_model.py` |
| Process | Injected faults (stiction, oscillation, saturation, sensor, communication) | DAMADICS, Choudhury 2005 | done | `tests/test_engine.py`, `tests/test_experiments.py` |
| Process | Plant-wide coupling between units | Downs and Vogel 1993 | done (benchmark) | `tests/test_model.py` |
| Process | Ground truth of every injected fault, kept apart from the data | category | done (benchmark truth artifact) | `tests/test_dataset.py` |
| Process | Offline datasets with manifest and digests | category | done (benchmark) | `tests/test_contracts.py` |
| Control | Writable setpoints, modes and outputs from a client | category | missing: read-only today; an owner decision (G4) | |
| Alarms | Alarms and conditions events | Part 9 | missing (G8) | |
| Address space | Import or export a NodeSet2 model | Part 6 | missing (G9) | |
| Replay | Replay a recorded CSV as live tags | category | missing (G10) | |
| Security | Signed and encrypted endpoints, user authentication | Part 2, Part 4 | missing: anonymous `NoSecurity` only (G3) | |
| Conformance | Checked by a standard OPC UA client | OPC Foundation CTT | partial: asyncua client only (G2) | `tests/test_server.py`, `tests/test_loops.py` |
| Deployment | Container with health check, offline install | category | done (`Dockerfile`, `make smoke`) | CI container smoke |
