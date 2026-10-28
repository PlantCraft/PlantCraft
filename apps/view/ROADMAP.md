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

## Progress log

| Date | Change |
|---|---|
| 2026-10-19 | First version, extracted from the BI dashboard of the PlantCraft monolith (cpm PR #8 and the public links of PR #11) into its own repository: own SQLite, plant data and assets through API v1 only (plantcraft-sdk 0.2.0), PlantCraft sign-in and audit, published-report reads with the app key and a shared cache, asset-relative dashboards, starter dashboards, public links, English interface under `/dash/`. pandas oracle 21/21, 4 e2e journeys. |
| 2026-10-19 | The suite's app standard: `app.toml`, `/api/meta`, `/api/help`, `assets/<id>`, image labels, `make package` (waits on PlantCraft's `deploy/package.sh`), status word `warning`; uid 10006. |
| 2026-10-19 | plantcraft-sdk 0.4.0; cards show other apps' results (CPMCraft loop health) with the producer's status; references through the SDK for subjects; `make package` builds and verifies a signed `.pcapp` with an SBOM from `deploy/sbom.py`. 6 e2e journeys. |
| 2026-10-19 | plantcraft-sdk 0.5.0: API v1 signal ids (`<source>:<tag>`); saved cards move from bare tags at every start or with `dashcraft migrate-signals`; asset pages of units, equipment and loops link here. |
| 2026-10-19 | plantcraft-sdk 0.6.0; the image carries its SBOM at `/app/sbom.json`. |
| 2026-10-20 | Trend cards draw the history apps archive in HistCraft (CPMCraft loop health). 7 e2e journeys. |
| 2026-10-20 | plantcraft-sdk 0.7.0: derived series found with API v1 filters. |
| 2026-10-20 | Card editor's Signal toggle fixed; plantcraft-sdk 0.7.1: trends of signals recorded on change reach the end. |
| 2026-10-20 | TrendCraft renamed DashCraft (`/dash/`, owner D9); the suite frame `@plantcraft/ui` 0.2.0 (sidebar, Apps, Help browser, user menu with theme); plantcraft-sdk 0.8.1; cards of CPMCraft and DataCraft read LinkCraft. 9 e2e journeys. |
| 2026-10-20 | Module names (owner decision D10): PlantCraft View in documents, the package and `app.toml`, just Dashboards inside the suite (sidebar lockup, page title, help, result labels such as "Loop health (Link)"); plantcraft-sdk 0.8.2 and `@plantcraft/ui` 0.3.1 (PlantCraft `8dfd352`): short names in the lockup and Apps list, the messages button. |
| 2026-10-21 | Every card downloads the data it shows as CSV (one row per sample for a trend, one row per item otherwise; text that a spreadsheet would read as a formula is escaped); G5 narrowed to image and PDF. |
| 2026-10-25 | **Reports** (`/reports`): sections of text, cards and events over one period, made into a PDF (ReportLab) on a daily, weekly or monthly schedule in the installation's time zone and sent to people and groups in Messages; every PDF kept; `report.sent` and `report.failed` events, runs, schedules and Desk's calendar; three examples on the demo plant. |
