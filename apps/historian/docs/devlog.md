# Devlog

Notes on how the module changed and why, newest first: what a later contributor would need to
know that the code and `CHANGELOG.md` do not say. One short entry per change worth explaining.

## Unreleased

- Data lake feed (2026-11-03, `export/lake.py`): the collector, not the server, writes the files, because it is the one process per archive (no two server processes writing the same hour) and it already runs the hourly housekeeping; the feed runs first in `_housekeep` so compaction never delays a period. Only the export's listed tags travel, never its assets: the asset tree is read from PlantCraft with a person's token and the feed runs as nobody, which is also why only administrators may turn one on. The state is its own table (`lake_feeds`: next period, last file, problem) so a saved export's payload stays what the person saved; a feed turned off forgets it and starts again from the last ended period. `point_ref` moved to `archive/query.py` for the collector to read like the API does.

## 0.5.1

- The repository's public history starts here; earlier releases are summarized in `CHANGELOG.md`.
