# Status

> **Updated:** 2026-10-27 (cleanup before the load test)

**Focus:** PlantCraft Analytics (folder `apps/link`, id `linkcraft`) in the suite's 0.4.0 (no launch date yet): blocks, libraries and algorithms that run as monitors on loops, signals and assets, with Signal quality, loop performance and process models (FMUs); rounds 9 and 10 of the owner's review are merged; runs can go to the compute workers.

**Next task:** G3 (score the International Stiction Database) and G1 (economic impact of a loop's causes); the full list is in [gaps.md](gaps.md).

**Blockers:** none.

**Contract:** `plantcraft-sdk` and `@plantcraft/ui` vendored in `vendor/` (the exact versions in `vendor/README.md`).
Settings and the PlantCraft connection come from the SDK (`AppSettings`, `PlatformRuntime`).

**Numbers (2026-10-27):** `make ci` green: 1214 pytest tests, frontend build and tests.

**Legacy:** none. The one-time copies from CPMCraft and DataCraft (removed 2026-10-23) and from Twin (removed 2026-10-25, after it ran on the only installation that had Twin) are gone.

See [devlog.md](devlog.md) for the history.
