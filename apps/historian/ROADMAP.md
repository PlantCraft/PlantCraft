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

## What changed

Every release, newest first: `CHANGELOG.md`.

