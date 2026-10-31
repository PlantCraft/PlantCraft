# Gaps

> **Updated:** 2026-10-31

Every known shortfall of PlantCraft Simulator, ranked by user impact. `B` marks a blocker for the next
stage. When a gap closes, delete its row in the same change and note it in `CHANGELOG.md`.

| Id | Gap | Impact | B |
|---|---|---|---|
| G11 | Benchmark catalog texts (loop, signal and scenario names and descriptions, OPC UA property `DescriptionPtBr`) are in Portuguese; the suite is English only. Translating them changes the catalog digest and the benchmark identity (maintainer decision) | high | |
| G12 | The 30-seed scenario study and the 600-run isolation matrix were not regenerated for benchmark 0.4.0 (their digests embed `benchmark_version`); `docs/validation.md` still lists the 0.3.0 identities | medium | B |
| G3 | Endpoints are anonymous `NoSecurity` only: no signed/encrypted policies, certificates or user authentication | medium | |
| G2 | Conformance is checked with the asyncua client only; no run of an independent reference client or the OPC Foundation's Compliance Test Tool | medium | |
| G4 | No writable nodes (setpoints, modes, outputs), so ModelCraft/MPC cannot close a loop on the simulator. Any write path is a maintainer decision | medium | |
| G14 | No pip-audit, image vulnerability scan or CycloneDX SBOM in CI | medium | |
| G15 | The loop portfolio publishes `Bad` only for a scheduled fault (`--faults`), never on its own; subscriptions are not covered by a test | low | |
| G5 | Engineering units are string properties, not OPC UA Part 8 `EUInformation` and `EURange` | low | |
| G6 | No user-defined tags or signal generators (sine, ramp, random, step); models are fixed in code | low | |
| G8 | No OPC UA alarms and conditions | low | |
| G9 | No NodeSet2 import or export of the address space | low | |
| G10 | No replay of a recorded CSV as live tags | low | |
| G13 | Two SQLite historian classes (`storage.BulkHistorySQLite` for the benchmark, `loops.storage.LoopHistorySQLite` for the portfolio) with different retention and checkpoint rules; merge them once both behaviours are covered by one test set | low | |
| G7 | `SPEC.md` names no public pages of the commercial tools studied yet | low | |
| G16 | The `simcraft` name is not yet published on any package index; the old distribution name has no final release pointing to it (maintainer decision) | low | |
