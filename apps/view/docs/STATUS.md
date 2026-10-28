# Status

> **Updated:** 2026-10-27 (cleanup before the load test)

**Focus:** PlantCraft View in the suite's 0.4.0 (no launch date yet): dashboards and trends over the Historian's signals and the apps' results, Reports as documents (scheduled PDFs to Messages), public read-only links and the built-in "Suite health" dashboard; round 10 is merged.

**Next task:** G1 (event frames, annotations and alarm marks on trends); the full list is in [gaps.md](gaps.md).

**Blockers:** none.

**Contract:** `plantcraft-sdk` and `@plantcraft/ui` vendored in `vendor/` (the exact versions in `vendor/README.md`).
Settings and the PlantCraft connection come from the SDK (`AppSettings`, `PlatformRuntime`).

**Numbers (2026-10-27):** `make ci` green: 193 pytest tests, frontend build and tests.

**Legacy:** The TrendCraft rename and the CPMCraft/DataCraft card renames were removed on 2026-10-23 (every installation had moved).

**Reports (2026-10-25):** the Reports tab (scheduled PDFs to Messages) is in; reports built from a notebook come later, and notebooks never run on the server (owner, 2026-10-25).

See [devlog.md](devlog.md) for the history.
