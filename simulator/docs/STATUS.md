# Status

> **Updated:** 2026-10-23 (suite refactor)

**Focus:** PlantCraft Simulator 0.4.1, the suite's OPC UA plant simulator: the 50-loop portfolio the
PlantCraft demo reads (`simcraft loops serve`) and the benchmark (`simcraft serve`). It
runs as the `simcraft` service of the suite's compose file. Only `SIMCRAFT_*` variables are
read (the older names were removed on 2026-10-23).

**Next task:** the highest open gap in [gaps.md](gaps.md).

**Blockers:** none here. G12 (regenerate the 30-seed evidence for benchmark 0.4.0) before any
publication of benchmark results.

**Numbers (2026-10-19):** `make ci` green: 88 pytest tests (78 from 0.3.7, 10 new), ruff clean,
catalog digest `sha256:6c737ebd…2339cb` unchanged. Image `simcraft:0.4.0`: read-only, uid 10004,
healthy after 53 s with the default 48 h loop backfill, 16 s for the benchmark `smoke` profile.
