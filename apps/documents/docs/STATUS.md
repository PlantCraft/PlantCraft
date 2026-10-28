# Status

> **Updated:** 2026-10-27 (cleanup before the load test)

**Focus:** PlantCraft Documents in the suite's 0.4.0 (no launch date yet): the plant's library, reading into passages, hybrid search offline, the assistant's tools and pages.

**Next task:** reading on a compute worker, a mounted shared folder, OCR; the full list is in [gaps.md](gaps.md).

**Blockers:** none.

**Contract:** `plantcraft-sdk` and `@plantcraft/ui` vendored in `vendor/` (the exact versions in `vendor/README.md`).
Settings and the PlantCraft connection come from the SDK (`AppSettings`, `PlatformRuntime`).

**Numbers (2026-10-27):** `make ci` green: 47 pytest tests, frontend build and tests.

See [devlog.md](devlog.md) for the history.
