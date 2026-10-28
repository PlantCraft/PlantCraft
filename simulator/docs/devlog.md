# Devlog

Terse, newest last. Releases before 0.4.0 are in `CHANGELOG.md`.

## 2026-10-19: 0.4.0, PlantCraft

- Renamed the project to `plantcraft` (package, import, CLI, image). Code reformatted at line length 100
  in its own commit.
- Namespace `urn:processcraft:plantcraft` for both servers; `benchmark_version` 0.4.0 because the
  URI is in the manifest and checkpoint. Verified the new manifest digest comes only from those
  two fields (the old values reproduce `sha256:90ba4be9…afc673`).
- Loop portfolio from ProcessCraft `processcraft/simulator` (`dynamics.py`, `server.py`,
  `storage.py`, English texts; the Portuguese original in the old platform has identical
  numbers) as `plantcraft.loops`; `catalog.py` (CPM method choices) stays in ProcessCraft and
  `plantcraft loops catalog` gives it the loop list. Reference values of PIC-1002 after one hour
  pinned from ProcessCraft's module.
- `PLANTCRAFT_*` settings with the old names as fallbacks; one health check for both servers.
- Dockerfile in the suite format (pinned digest, hashed wheelhouse, uid 10004, read-only, no pip,
  HEALTHCHECK); `make smoke` starts it as the suite does.
- No public-demo limits found on any local branch of ProcessCraft, the old platform or this
  repository, so none were carried over.
- Open: G1 (ProcessCraft switch), G11 (Portuguese catalog), G12 (30-seed evidence for 0.4.0).

## 2026-10-20: 0.4.1, sticky valves show (stick-slip)

- The four stiction loops (FIC-1003, FIC-1102, FIC-1206, FIC-1214) sat at their setpoint with the
  valve never moving: nothing pushed the controller past the dead band. A slow load change
  (2 units, 40 min period) now drives the classic stick-slip cycle, several valve jumps an hour
  and a PV error about six times larger, which is what a stiction screening is meant to find.
  Found by the suite's end-to-end demo (ProcessCraft `processcraft demo seed`).
