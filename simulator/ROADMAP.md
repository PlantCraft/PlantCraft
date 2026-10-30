# PlantCraft Simulator roadmap

> **Last reviewed:** 2026-10-19 · **Stage:** alpha · **Version:** 0.4.0

Readiness against what tools of the category offer (`SPEC.md`). "Measured" numbers come from
tests and oracles; "estimated" ones are judgement. The ranked work list is `docs/gaps.md`.

| Area | Ready | Kind | Notes |
|---|---:|---|---|
| OPC UA read and browse | ~80% | estimated | Both servers through asyncua; Part 8 EU types missing (G5) |
| Historical Access | ~80% | estimated | Raw reads, continuation, backfill, restart continuity |
| Process models and faults | ~75% | estimated | 50-loop portfolio (10 behaviours) and 500-signal benchmark (20 scenarios) |
| Configurable signals | ~10% | estimated | Fixed models only; no user-defined tags (G6) |
| Writes and control | 0% | estimated | Read-only (G4, maintainer decision) |
| Alarms, NodeSet, replay | 0% | estimated | G8, G9, G10 |
| Security | ~20% | estimated | Hardened container; endpoint is anonymous `NoSecurity` (G3) |
| Conformance oracle | ~30% | estimated | asyncua client only (G2) |
| Deployment | ~80% | measured | Image healthy under read-only, uid 10004: 48 h loop backfill in 53 s, benchmark smoke in 16 s |
| **Overall** | **~50%** | estimated | |

## What changed

Every release, newest first: `CHANGELOG.md`.

