# Devlog

Notes on how the module changed and why, newest first: what a later contributor would need to
know that the code and `CHANGELOG.md` do not say. One short entry per change worth explaining.

## Unreleased

- Backup of the suite at one instant (2026-10-31): `plantcraft.ops.snapshot` opens a read snapshot of every SQLite file first, then copies each in one step. Before, the copy in steps of 4,096 pages restarted at every commit of another process: with 7 databases (1.5 GB) and apps committing 20 times a second it had not finished after 16 minutes; now 28 s, the same as idle, and every database holds the same instant (0.0 s apart, against minutes).
- Storage test (2026-10-31): JSON kept in each app's SQLite beats loose files (3-4x faster writes, indexable, 0/100 broken after kill -9 against 71/100 for an in-place `write_text`); one shared SQLite halves throughput and makes one app's batch stall the others' writes (p99 4 -> 54 ms, 130 ms with a heavy writer); PostgreSQL with a schema per app costs ~60 us a query against ~4 us. Kept one SQLite per app; Models writes its JSON files atomically. Benchmarks in `ci/bench/storage/`.

## 0.5.1

- The repository's public history starts here; earlier releases are summarized in `CHANGELOG.md`.
