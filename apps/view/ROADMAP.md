# PlantCraft View roadmap

> **Last reviewed:** 2026-10-20 · **Stage:** alpha · **Version:** 0.1.0

Readiness against what tools of the category offer (`SPEC.md`). "Measured" numbers come from
tests and oracles; "estimated" ones are judgement. The ranked work list is `docs/gaps.md`.

| Area | Ready | Kind | Notes |
|---|---:|---|---|
| Data through PlantCraft API v1 | ~80% | estimated | Batch series, aggregated values, assets, signals, audit; shared TTL cache |
| Cards (KPI, trend, bar, table) | ~60% | estimated | Limits, two axes, empty-window anchor; no event frames or annotations (G1) |
| Asset-relative dashboards | ~60% | estimated | `$context` + role, picker by kind; no asset tree browser (G3) |
| Screens (refresh, full screen, URL state) | ~70% | estimated | No drag-and-drop layout (G4) |
| Sharing (public links, starters) | ~70% | estimated | No export to image, PDF or CSV (G5) |
| Deployment | ~60% | estimated | Image for the suite's compose file; no isolation test or SBOM here (G6) |
| **Overall** | **~40%** | estimated | First version as its own app |

## What changed

Every release, newest first: `CHANGELOG.md`.

