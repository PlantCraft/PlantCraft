# Storage benchmarks (2026-10-31)

Where the suite keeps its objects and whether one database for every app would be better.

| Script | Question |
|---|---|
| `docs_bench.py` | JSON documents: loose files, SQLite TEXT (what the apps do), SQLite JSONB, PostgreSQL JSONB |
| `shared_bench.py` | one SQLite per app (today), one shared SQLite, one PostgreSQL with a schema per app, with and without a heavy writer |
| `backup_bench.py` | the suite's backup (`plantcraft.ops.snapshot`) of 7 databases, 1.5 GB, with every app writing: time and the instant each copy holds |
| `json_index_bench.py` | the notification feed (`notices_for`) on a year of messages, before and after its index on the JSON field |
| `crash_test.py` | `kill -9` in the middle of saves: in-place `write_text`, temporary + rename, SQLite, PostgreSQL |

They need `psycopg` and a PostgreSQL to point at (`--pg "host=... port=... user=..."`). Results of
the first run (4 vCPU): one SQLite per app stays; JSON stays inside it; files are written
atomically. Numbers in `docs/devlog.md` (2026-10-31).
