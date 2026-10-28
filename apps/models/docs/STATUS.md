# Status

> **Updated:** 2026-10-27 (cleanup before the load test)

**Focus:** PlantCraft Models in the suite's 0.4.0 (no launch date yet): block diagram models simulated over time (Modelica underneath), versions and Compare, studies (grids and optimization) ranked by indicators, Simulations and the queue; round 9 is merged.

**Next task:** G4 (fluid and thermal libraries) and G5 (fitting to plant data); the full list is in [gaps.md](gaps.md).

**Blockers:** none.

**Contract:** `plantcraft-sdk` and `@plantcraft/ui` vendored in `vendor/` (the exact versions in `vendor/README.md`).
Settings and the PlantCraft connection come from the SDK (`AppSettings`, `PlatformRuntime`).

**Numbers (2026-10-27):** `make ci` green: 136 pytest tests, frontend build and tests.

See [devlog.md](devlog.md) for the history.
