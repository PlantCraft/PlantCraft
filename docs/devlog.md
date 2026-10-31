# Devlog

Notes on how the module changed and why, newest first: what a later contributor would need to
know that the code and `CHANGELOG.md` do not say. One short entry per change worth explaining.

## Unreleased

- Storage test (2026-10-31): JSON kept in each app's SQLite beats loose files (3-4x faster writes, indexable, 0/100 broken after kill -9 against 71/100 for an in-place `write_text`); one shared SQLite halves throughput and makes one app's batch stall the others' writes (p99 4 -> 54 ms, 130 ms with a heavy writer); PostgreSQL with a schema per app costs ~60 us a query against ~4 us. Kept one SQLite per app; Models writes its JSON files atomically. Benchmarks in `ci/bench/storage/`.

## 0.5.1

- The repository's public history starts here; earlier releases are summarized in `CHANGELOG.md`.
