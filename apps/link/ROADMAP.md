# PlantCraft Analytics roadmap

> **Last reviewed:** 2026-10-20 · **Stage:** alpha · **Version:** 0.1.0 (PlantCraft Analytics: CPMCraft and DataCraft merged)

Readiness against what tools of the category offer (`SPEC.md`). "Measured" numbers come from
tests and oracles; "estimated" ones are judgement. The ranked work list is `docs/gaps.md`.

| Area | Ready | Kind | Notes |
|---|---:|---|---|
| Data through PlantCraft API v1 | ~80% | estimated | Batch series reads, text (mode) signals, values, asset catalog (types, attributes, roles, relations), signal catalog, signal ids `<source>:<tag>`, results, derived series (loop health and status, signal quality), events (as lists), runs and schedules through plantcraft-sdk 0.8.3, audit |
| Signal quality (from DataCraft) | ~65% | estimated | 8 checks on every signal, system protocol with schedule and runs, signal pages, verdicts published on signals and assets and read by the loops; synthetic oracle 90 cases measured; no cross-signal checks (mass balance) |
| Loop data gate | ~60% | estimated | 3 checks; defers to the signals' verdicts when they are fresh |
| Diagnosis methods | ~60% | estimated | 14 methods; simulator oracle 10/10 measured, stiction screen has no PV-OP shape test (G28), ISDB not pinned (G3), no Harris index (G19) |
| Protocols (block diagrams) | ~75% | estimated | Editor, check, preview, save; defaults per loop type (2026-10-19) |
| Engine (rounds, schedules, runs) | ~75% | measured | 2000 loops / 4 processes / 2 ms latency: 63.4-71.9 s cold with about 10,300 finding events in 11 requests and 4,000 derived series in 8, 46.3-55.5 s warm (2026-10-20) (one POST per event: 96.7/57.3; was 147/121) |
| Loop page and reports | ~50% | estimated | Trends, findings, PDF; no economics or recommendation (G1) |
| Interface (suite frame) | ~70% | estimated | `@plantcraft/ui` 0.3.1: SuiteShell (with the messages button), HelpBrowser, tokens; Overview with the week; light, dark and phone checked by e2e; English only (G24) |
| Deployment | ~65% | estimated | Image for the suite's compose file; signed `.pcapp` from `make package` (PlantCraft's `deploy/package.sh`); one version (app.toml) for tag, label and `/healthz`; no isolation test here (G20) |
| **Overall** | **~50%** | estimated | CPMCraft and DataCraft as one app, on the suite frame |

## What changed

Every release, newest first: `CHANGELOG.md`.

