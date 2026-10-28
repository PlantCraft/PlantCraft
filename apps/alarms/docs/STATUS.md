# Status

> **Updated:** 2026-10-27 (cleanup before the load test)

**Focus:** PlantCraft Alarms in the suite's 0.4.0 (no launch date yet): rules (Simple, Blocks or Python) raise ISA-18.2 alarms and alerts from signals, app results and the suite's events; the Active list, history and performance; round 11 (events, rules from an event, notification actions) is merged.

**Next task:** G3 and G6 in [gaps.md](gaps.md).

**Blockers:** none.

**Contract:** `plantcraft-sdk` and `@plantcraft/ui` vendored in `vendor/` (the exact versions in `vendor/README.md`).
Settings and the PlantCraft connection come from the SDK (`AppSettings`, `PlatformRuntime`).

**Numbers (2026-10-27):** `make ci` green: 112 pytest tests, frontend build and tests.

See [devlog.md](devlog.md) for the history.
