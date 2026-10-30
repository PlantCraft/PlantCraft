# PlantCraft Historian roadmap

> **Last reviewed:** 2026-10-20 · **Stage:** preview · **Version:** 0.1.0

Readiness against what tools of the category offer (`SPEC.md`). "Measured" numbers come from
tests and benchmarks; "estimated" ones are judgement. The ranked work list is `docs/gaps.md`.

| Area | Ready | Kind | Notes |
|---|---:|---|---|
| Collection (OPC UA) | ~50% | estimated | Polling Read, browse, reconnect, gaps; no subscriptions, no secure channel (G2, G3) |
| Compression | ~70% | measured | Swinging door within the deviation on 7,200-value random walks; one-stage filter |
| Archive | ~55% | measured | ~1.5 bytes per value read (2,000 points, 1 s, noisy); no quality flags (G5) |
| Reads | ~60% | estimated | Recorded, time-weighted grid, aggregates in v1 shapes |
| Suite integration | ~30% | estimated | Data API ready; PlantCraft `histcraft` source not merged yet (G1) |
| Pages | ~60% | estimated | Overview, sources and browse, points, trend, settings in three levels, help; the suite frame (`@plantcraft/ui`) |
| Deployment | ~40% | estimated | Image and compose snippet; not in PlantCraft's bundle yet (G1) |
| **Overall** | **~45%** | estimated | Preview: first version |

## Progress log

| Date | Change |
|---|---|
| 2026-10-19 | First version: OPC UA collector (read-only, own container on the plant network), swinging-door compression, chunked archive with retention and compaction, reads in API v1 shapes, pages under `/hist/`. Boundary with PlantCraft in `docs/boundary.md`. Bench: 2,000 points at 1 s handled 53x faster than real time; 501 the Simulator points collected live at 500 reads/s. |
| 2026-10-20 | Suite frame `@plantcraft/ui` 0.2.0 (D6) and SDK 0.8.1; settings in three levels, general, per source, per point, the most specific wins (D8), shown with their origin on the point page. |
| 2026-10-20 | Module names (owner decision D10): PlantCraft Historian in documents, the package and `app.toml`, just Historian inside the suite (sidebar lockup, page title, help); plantcraft-sdk 0.8.2 and `@plantcraft/ui` 0.3.1 (PlantCraft `8dfd352`): short names in the lockup and Apps list, the messages button. |
| 2026-10-20 | Closed G1 and G17: PlantCraft forwards API v1 data and source admin to Historian when `HISTCRAFT_URL` is set (`plantcraft/platform/datalayer/histcraft.py`), and its bundle and `install.sh` carry `histcraft-db` (pinned by digest, its own data folder and password, `pg_dump` before upgrades). |
| 2026-10-21 | Closed G20: recent reads of PI and OPC UA signals in `source` mode stay in memory (`sources/cache.py`, `HISTCRAFT_SOURCE_CACHE_SECONDS`, 300 s): a read inside them is answered there, a refresh up to now asks the source only for the last minutes; CSV files were already held in memory by their reader. |
| 2026-10-21 | G9 narrowed to partitions: hourly rollups (`archive/rollup.py`, table `rollups`) keep per point and hour the covered time and the integral of the rebuilt signal; a trend on an hourly or coarser grid reads them and takes only the hours they lack (the newest, or one a write changed) from the chunks, with the same numbers. The collector fills up to a month per point at each housekeeping; every write drops the hours it changes. |
