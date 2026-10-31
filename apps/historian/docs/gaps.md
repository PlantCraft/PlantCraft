# Gaps

> **Updated:** 2026-10-20

Every known shortfall of PlantCraft Historian, ranked by user impact. `B` marks a blocker for the next stage
(alpha: apps of the suite read PlantCraft Historian points through PlantCraft).

| Id | Gap | Impact | B |
|---|---|---|---|
| G15 | Live collection (archive mode) exists for OPC UA only: PI Web API signals in `archive` or `both` mode are refused; CSV files and imports are archived (round 7) | medium | |
| G16 | App standard parts not adopted yet: signal refs `signal:<source>:<tag>` (D2, waits for PlantCraft's follow-up), results/events (PlantCraft Historian publishes none; candidate: per-signal collection status), a signed `make package` run in CI (needs a publisher key) | medium | |
| G3 | Polling only: a Read per scan period (OPC UA); no subscription or report by exception into PlantCraft Historian | medium | |
| G4 | No oracle yet: archive a PlantCraft Simulator dataset and read it back, every value within its point's deviation, as `tests/floors.toml` | medium | |
| G6 | No edits of archived values with an audit trail. Backfill exists for OPC UA sources with Historical Access (`POST /api/sources/{id}/backfill`, Sources page); PI Web API sources are read in mode `source` and are not backfilled; a CSV file's past lines are archived on the first check | medium | |
| G7 | No store and forward: an edge collector that buffers while the archive is unreachable | medium | |
| G8 | Retention deletes whole chunks (up to 10,000 values), so a point keeps up to one chunk past its retention | low | |
| G18 | No migration of an existing SQLite archive into PostgreSQL (`histcraft migrate`): only matters for installs made before 2026-10-19 (none in a plant) | low | |
| G19 | Kerberos to PI Web API needs the `kerberos` extra (`requests-kerberos`, which needs the system's krb5 libraries to build): the default image speaks basic auth only (NTLM needs `requests-ntlm`, not in the image either); a `HISTCRAFT_KERBEROS=1` image variant with krb5 and a keytab mount is still to write | high | B |
| G10 | OPC DA: not offered (Sparkplug B is, read by the collector, since H10; MQTT, Modbus TCP and SQL through the gateway); the gateway holds no store and forward of its own beyond its memory buffer. A Sparkplug B node born before Historian connected is learnt only at its next birth: asking for a rebirth (NCMD) would publish to the plant | low | |
| G12 | No `tests/test_isolation.py` here (the suite's isolation test lives in PlantCraft); no pip-audit, npm audit or SBOM in this repository's CI; no e2e browser journeys | medium | |
| G13 | Text values stored as JSON lists in each chunk; long repetitive labels are left to zstd | low | |
| G14 | Interface in English only; the `t()` hook is in place, no Portuguese catalog | low | |
