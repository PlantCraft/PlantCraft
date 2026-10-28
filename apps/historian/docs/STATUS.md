# Status

> **Updated:** 2026-10-27 (cleanup before the load test)

**Focus:** PlantCraft Historian in the suite's 0.4.0 (no launch date yet): the suite's data layer: PI Web API, OPC UA, CSV and gateway sources read-only, the archive (SQLite or PostgreSQL) with the fast write path, recurring imports and exports, apps' derived signals and API v1 reads served to the apps directly; the collector runs as its own service (`histcraft collect`).

**Next task:** G2 (secure OPC UA channel) and G15 (live collection from PI Web API); the full list is in [gaps.md](gaps.md).

**Blockers:** none.

**Contract:** `plantcraft-sdk` and `@plantcraft/ui` vendored in `vendor/` (the exact versions in `vendor/README.md`).
Settings and the PlantCraft connection come from the SDK (`AppSettings`, `PlatformRuntime`).

**Numbers (2026-10-27):** `make ci` green: 346 pytest tests, frontend build and tests.

See [devlog.md](devlog.md) for the history.
