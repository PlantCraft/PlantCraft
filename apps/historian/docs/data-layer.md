# PlantCraft Historian as the suite's data layer: the contract with PlantCraft

> **Status:** decided by the maintainer on 2026-10-19 (the other apps change to fit the new
> architecture). PlantCraft Historian owns every connection to plant
> systems and every history; PlantCraft keeps people, assets, apps and the single API door.
> This file is the contract between the two; the PlantCraft Historian side is implemented in this
> repository, the PlantCraft side by its owner thread.

## Who does what

| | PlantCraft Historian | PlantCraft |
|---|---|---|
| Networks | `plant` (PI, OPC UA, CSV folders) and `apps` | `apps` only |
| Sources | PI Web API, OPC UA (live and Historical Access), CSV, and each app's derived source; their credentials (encrypted) and pages (`/hist/sources`) | none: the Sources page links to PlantCraft Historian |
| History | per signal: read from the source, archived here, or both; retention; backfill | none (its read cache goes away) |
| API v1 for apps | serves the data routes below to PlantCraft only | unchanged for apps: `/api/v1/signals*`, `/series`, `/value` forward to PlantCraft Historian; new `PUT /api/v1/series` (apps write derived series) |
| Assets, roles, plant map | | unchanged: roles bind signal ids (`<source id>:<tag>`) |

Apps change nothing to read data. They keep calling PlantCraft's API v1 with their own token;
PlantCraft decides who may read, then asks PlantCraft Historian. Since 2026-10-23 they may
also read straight from PlantCraft Historian (next section), with the same token and rule.

## Reads straight from PlantCraft Historian (all under `/hist/api/v1`)

`src/histcraft/api/routers/reads.py` serves API v1's reads itself, so long reads skip the hop
through PlantCraft (and PlantCraft parsing and writing their JSON again). Same paths, shapes,
limits and errors as PlantCraft's API v1:

| Method and path | Answer |
|---|---|
| `GET /reads` | `{"api": 1}`: the reads below are served (`plantcraft-sdk` 0.13.0 asks once) |
| `GET /signals?q&app&subject&result`, `GET /signals/{id}` | as `/api/v1/data` below |
| `GET /signals/{id}/series?start&end&step`, `POST /series` | as `/api/v1/data` below |
| `GET /signals/{id}/value?agg&window` | as `/api/v1/data` below |

Who reads is who reads PlantCraft's API v1: a token PlantCraft signed (a person's or an app's
service token, `aud` `processcraft` or `histcraft`), not ended early (PlantCraft's
`/api/v1/auth/revoked`, read again every 10 s), at level `viewer`, `editor` or `admin`; a
dashboards-only person gets 403. Access to the Historian app is not needed (a person who reads
series in Link reads them here). Nothing here writes. Apps send these reads here when
`PLANTCRAFT_HISTORIAN_URL` is set (the suite sets it to `HISTCRAFT_URL`).

A batch reads the catalog in one query per source, the archive of all its signals in one query
(PostgreSQL: each point's neighbour chunks by a `LATERAL` lookup on the primary key) and the
snapshots in one more, instead of four queries per signal; a grid of whole hours still comes from
the hourly rollups.

## The archive in PostgreSQL

`chunks` (partitioned by `t0`) and `rollups` (by `hour`) have one table per UTC month,
`<table>_yYYYYmMM`, made by the write that first needs it (attached, so it never waits for a
write in flight), and two edge tables for times before 1900 and from 2200. Hourly housekeeping
drops a past month when every chunk in it ends before its point's retention cutoff (and a rollup
month when it ends by then); a month holding a point that is no longer in the catalog stays.
Everything else in retention deletes chunk by chunk, as on SQLite. An archive made by 0.3.0 or
earlier is turned into this layout on start (`archive/partitions.py`). The suite's backups copy
the database files (`pg_basebackup`, full and incremental) and need no change; the restore drill
reads every table, the monthly ones included.

## How the collector writes (Historian 0.5)

Every `HISTCRAFT_FLUSH_SECONDS` (5 s) the collector writes the snapshots and one `recent` row
holding every point's newly archived values (one statement, whatever the number of points); every
`HISTCRAFT_ARCHIVE_SECONDS` (60 s) `ArchiveStore.settle` moves those rows into one chunk per
point, with one statement per table for all points (PostgreSQL: arrays and `unnest`). Reads add
the recent rows to the chunks, so a trend still reaches the present; each process decodes a row
once. Rows a stopped collector left are settled by the next one.

Chunks are zstd frames of byte-shuffled differences and values, float32 when every value is one
exactly (`archive/codec.py`, about 15 % smaller than the zlib chunks of 0.4 and five times faster
to write); chunks written before are read as they are and rewritten in the new layout when
compaction merges them. Compaction reads only the chunks that merge. A day after a month ends,
housekeeping copies that month once into a fresh table in key order and swaps it in
(`partitions.rewrite_month`: reads go on, a write to that month waits for the copy), then does
the same for that month's rollups. It gives back the space compaction's rewrites leave behind
and puts each point's rows of the month side by side.

Compaction goes by tiers of time (Historian 0.5): once an hour is closed its minute chunks merge
into one; once a day is closed its hours merge (into chunks of 10,000 values at most); once a
month is closed its days do. Chunks merge only with the chunks of the same hour, day or month, and
only when two neighbours fit together, so each value is rewritten three times at most and a full
chunk never again. Before, every hourly run rewrote each point's growing chunk until it held
10,000 values, which wrote about 18 times the archived bytes to the WAL. The collector looks back
to the start of the previous month only: older months are done (a backfill writes chunks of its
own size).

The writes that come back every few seconds are kept light. `snapshots` (each point's latest
value and status, rewritten every flush) is an UNLOGGED table in PostgreSQL: it writes nothing
to the WAL, and after a database crash or a restore from `pg_basebackup` it starts empty, the
next flush writes the live points again and housekeeping gives the others (imports, apps' series)
their last archived value. The values counted per point and hour (`point_hours`, "values per
day") reach the database every 10 minutes and at the collector's last flush, not every minute.
Measured with the collector's write path (300 points, 3 days across a month's end, PostgreSQL 16):
see the devlog of 2026-10-27.

A read finds a point's chunks by their start only: those starting inside the range, the last one
starting before it (it reaches into the range, or holds the value just before) and the first one
after it, all through the primary key `(point, t0)` (a point's chunks never overlap). PostgreSQL
opens only the months that hold them, so a read costs the same with a month or ten years of
history. Measured on a year of 800 points (18 GB, 4.9 billion values, 2026-10-27, cold cache):
one point's day 15 ms, its year as an hourly trend 71 ms, its 13 million raw values 0.9 s.

The hourly rollups also keep each hour's lowest and highest archived value and how many values
it holds: the min/max band of a trend on whole hours reads them past 7 days, and a window's
`mean`, `min` and `max` (`/value`) read the rollups of its whole hours and the samples of its
ends only. Rows kept before 0.5 are built again by the next housekeepings.

Daily and monthly rollups (H9, `rollups_coarse`, level 1 and 2) sum a closed UTC day's hours
and a closed month's days, in order from the newest one kept; a write into the past drops them
from there (with the hours it drops) and housekeeping sums them again. A grid of whole days and
a long window's mean, min and max read the coarsest rows that fit and the hours only at the
ends: a year as a daily trend 11 ms instead of 44, a 364-day mean 7.5 ms instead of 41
(`ci/bench/storage/rollup_levels.md`). Raw values, hourly, daily and monthly rollups each have a
retention (`retention_days`, `hourly_retention_days`, `daily_retention_days`,
`monthly_retention_days`); a level is kept at least as long as the raw values and the finer
levels (`forecast.level_days`), so the rollups outlive the values they were summed from.

## Calling PlantCraft Historian

Base URL `http://histcraft:8100/hist` (in the suite; `HISTCRAFT_URL` in PlantCraft). Every
call carries a token PlantCraft signs for itself, verified by PlantCraft Historian offline with
PlantCraft's JWKS:

```python
token, _ = issuer.issue(
    "app:processcraft", ttl=300, audience="histcraft", apps={"histcraft": "editor"}
)
```

PlantCraft Historian accepts on these routes only tokens whose `sub` is `app:processcraft` (people use
PlantCraft Historian's pages, not these routes). Nothing is shared or stored.

## Routes (all under `/hist/api/v1/data`)

Shapes, limits and error codes are those of PlantCraft's `docs/api-v1.md`
(`plantcraft_sdk.contract`); signal ids are D2 ids, `<source id>:<tag>`.

| Method and path | Answer |
|---|---|
| `GET /sources` | `[{"id", "name", "kind", "enabled", "mode", "default_mode", "endpoint", "namespace_uri", "username", "password_env", "has_password", "options", "status": {"ok", "message", "checked_at"} \| null, "signals"}]` (never a password) |
| `POST /sources` | create a plant source (below); 201 with the source as in `GET /sources`, plus `signals_added` |
| `PUT /sources/{id}` | update it (same body without `signals`; `password` omitted or `null` keeps the stored one) |
| `DELETE /sources/{id}` | 204; 409 while it still has signals |
| `POST /sources/test` | test settings not saved yet: body as `PUT /sources/{id}`; without `password`, the stored one of that id is used; answer as below |
| `POST /sources/{id}/test` | reach the source now: `{"ok": true, "detail": {...}}` (PI: server, version, user; OPC UA: endpoint, namespaces; CSV: files, newest, tags, layout), or 502 with the source's own words |
| `POST /sources/{id}/browse` | body `{"root"?, "limit"?}` (default 5,000, at most 20,000): `{"variables": [{"address", "tag", "name", "path", "kind", "step", "unit", "description", "low", "high"}], "truncated", "limit"}` |
| `POST /sources/{id}/signals` | `{"signals": [...]}` as in `POST /sources`, or `{"all": true, "root"?: str}` for every variable the source shows (up to 20,000); defaults for items that set none: `mode`, `scan_seconds`, `deviation`. Answer `{"added": [signal ids], "skipped": [...]}`; a signal already there is skipped |
| `POST /imports/check?name=&timezone=` | editors; body = the CSV (at most 200 MB). `{"token", "file_name", "bytes", "timezone", "ok", "report"}`: layout, period, rows, values, tags, `errors` and `warnings` (`{"message", "lines", "count", "tags"?}`); nothing is written. A file without errors waits 24 h under `<data>/imports/pending` |
| `POST /imports` | editors; `{"token", "name"}` creates source `import-<n>` (kind `import`, mode `archive`) and its points; the collector writes the values and deletes the file. 410 when the checked file is gone |
| `GET /imports` | `[{"id", "name", "file_name", "points", "values", "written", "start_ms", "end_ms", "imported_by", "created", "status": "writing" \| "done" \| "error" \| "gone", "detail"}]`, newest first |
| `DELETE /imports/{id}` | editors; removes the import, its points and every value it brought; answers `{"id", "points"}` |
| `GET /signals?q=&source=&app=&subject=&result=` | `[{"id", "name", "source", "unit", "description", "low", "high", "kind", "mode", "source_kind", "app", "subject", "result", "retention_days", "managed_by"}]`: the API v1 signal shape plus `mode` and `source_kind` (`opcua`, `pi_web_api`, `csv`, `derived`, `system`: the apps judge a laboratory signal from a file by its own rules), and for derived signals `app`, `subject`, `result` (`null` otherwise), the retention in effect (`0`: forever) and what sets it when an app does (`managed_by`, else `null`) |
| `GET /signals/{id}` | one signal, same shape; 404 when unknown. Every `{id}` route also takes a bare tag when exactly one source has it |
| `PATCH /signals/{id}` | change a plant signal (`enabled`, `mode`, `name`, `unit`, `description`, `low`, `high`, `step`, `scan_seconds`, `deviation`, `max_seconds`, `retention_days`); `{"enabled": false}` stops using it and keeps its history; answers the signal |
| `DELETE /signals/{id}` | remove a signal and its archived values; 204 |
| `GET /signals/{id}/series?start&end&step` | API v1 series `{"signal", "kind", "t", "v"}` |
| `POST /series` | API v1 batch: body `{"signals", "start", "end", "step"}`, answer `{"series", "errors"}` |
| `GET /signals/{id}/value?agg&window` | API v1 value `{"signal", "agg", "window", "value", "at"}` |
| `POST /derived` | write an app's computed series (below) |
| `POST /derived/runs` | write one run of an app's series outputs, kind `runs` (below) |
| `GET /signals/{id}/runs?limit=50` | a runs signal's executions, newest first: `{"signal", "runs": [{"run_at", "start", "end", "n"}]}` (empty for other signals) |
| `POST /system` | write the suite's own health, source `system` (below) |

`mode` is `source` (history read from the source on each request; nothing kept), `archive`
(collected on a scan, compressed, kept here) or `both` (archived, and what the archive lacks is
read from the source). A source has a default mode; a signal may override it. Defaults: PI Web
API `source`, OPC UA `archive`, derived `archive`. Calculated, CSV, import, MQTT, Sparkplug B, Modbus and
SQL points are always `archive`.

`both` reads the source's part of a batch in one request per source. To stop reading the source
at all, an administrator backfills it (Sources page, `POST /api/sources/{id}/backfill`,
body `{"hours": 48}`): the collector copies the source's own history of its archived signals
(OPC UA HistoryRead) into the archive, in windows of six hours, up to each signal's first archived
value; `GET /api/requests/{id}` answers `{"signals", "values", "failed", "errors"}` when done.

A signal added by tag takes its kind from the source's browse. When the source could not be
browsed at that moment the signal is a number; if the source then answers text (a MODE reading
AUTO), the collector makes it a text step after three reads, drops its archive (only "no data"
markers) and backfills that signal alone.

### Sources (PlantCraft's Connections page)

`POST /sources`, body:

```json
{"id": "pi", "name": "Plant PI", "kind": "pi_web_api", "endpoint": "https://pi.example/piwebapi",
 "username": "svc_reader", "password": "...", "mode": "",
 "options": {"server": "PISRV", "auth_type": "kerberos", "verify_ssl": true},
 "enabled": true, "signals": ["FIC101.PV", {"tag": "FIC101.MODE", "kind": "text"}]}
```

- `kind`: `pi_web_api` (`endpoint` https://, `options.server` required), `opcua` (`endpoint`
  opc.tcp://, `namespace_uri`), `csv` (`endpoint` = a file, or a glob in the last
  path part, in PlantCraft Historian's container, inside `HISTCRAFT_CSV_DIRS` (default `/csv`) or
  `<data dir>/files`; `options.check_minutes` 0.5-1440, default 5; the collector archives new lines
  and files, mode always `archive`). `import` sources are created only by `POST /api/imports`. `derived` sources cannot be created: they appear on an app's first write.
- `mode`: empty for the kind's default. `options` per kind: `catalog/store.py` `SOURCE_OPTIONS`.
- `password` is stored encrypted and never returned (`has_password`); `password_env` names an
  environment variable instead. Signals: a tag, or `{"tag", "address", "name", "unit",
  "description", "low", "high", "kind", "step", "mode", "scan_seconds", "deviation"}`; the signal id
  is `<id>:<tag>`. Only the signals added here are listed by `GET /signals`: add every signal the
  apps need (`"all": true` adds a whole source), in mode `source` when the source keeps history.
- Without `deviation`, a number archived here is compressed to 0.2% of its range after an
  exception of 0.1% (round 8 D1). Every number point has a range (D2), in this order: the
  server's (OPC UA `EURange`, PI `Zero` to `Zero + Span`), a person's (the point page, a points
  CSV), else one the collector suggests from the point's first day of values (its extremes plus
  10% on each side, rounded outward; `range_origin` `suggested` until a person saves it). Until
  then, the compression is that share of the value (`deviation_percent` on the point).
- Errors: 409 (the id exists), 422 (invalid; `detail` says which field).

Errors: 401 (no or bad token), 403 (a token other than PlantCraft's), 404, 422, 502 (the plant
source failed; `detail` says why), 503 (PlantCraft Historian is starting).

## Derived series (apps write what they compute)

`POST /hist/api/v1/data/derived`, body:

```json
{
  "series": [
    {"app": "cpmcraft", "signal": "app-cpmcraft:FIC-101.health", "name": "FIC-101 health",
     "unit": "%", "kind": "number", "subject": "asset:fic-101", "result": "loop_health",
     "t": ["2026-10-20T10:00:00Z", "..."], "v": [93.5, "..."]}
  ]
}
```

- PlantCraft serves it to apps as `PUT /api/v1/series` and fills each item's `app` from the
  caller's service token (`sub: app:<id>`). People cannot write. A top-level `"app"` is the
  default for items without one.
- A derived signal's source id is `app-<app id>` (a plant source may share an app's own id, as
  PlantCraft Simulator's does); PlantCraft Historian creates the source (kind `derived`, mode `archive`) and the
  signal on the first write. An app writes only its own source: any other source is a 403 for
  that signal.
- `subject` (what the series is about, such as `asset:fic-101`) and `result` (what it holds,
  such as `loop_health`) are stored, returned on the signal and filterable on `GET /signals`.
- At most 500 series and 100,000 values per call; `t` ascending ISO 8601 with offset; `v` as
  the signal's `kind` says, or `null` (a gap). A value at a time already stored replaces it.
  `name`, `unit`, `description`, `low`, `high` update the signal when given.
- `kind` (default `number`; a signal's kind never changes, another one is a 409):

  | kind | `v` written | `v` read |
  |---|---|---|
  | `number` | a number | a float; lines between values, averages on a grid |
  | `integer` | a whole number (`1.5` is a 422) | an int |
  | `boolean` | `true` or `false` | a bool |
  | `text` | text, cut at 1,000 characters | text |
  | `instant` | an ISO 8601 time with offset | an ISO 8601 time (UTC) |
  | `structured` | a JSON object or array, up to 64 kB | the object or array |

  All but `number` are recorded on change and held until the next value: a grid gives the
  value in effect at the end of each cell, never a mean. `integer`, `boolean` and `instant`
  are stored as numbers (an instant as UTC milliseconds); `text` and `structured` as labels.
- `retention_days` (0 to 36,500; `0` keeps the values forever) and `managed_by` (up to 100
  characters, such as `link:<schedule id>`) are written when given; `null` or missing leaves
  them as they are, an empty `managed_by` clears it. A signal with `managed_by` has its
  retention and compression set by that app only: changing them here (`PATCH`, the point
  page) is a 409 naming it.
- Answer `{"written": <values>, "errors": [{"signal", "status", "detail"}]}`.
- Derived values are never written to a plant system: there is no route to do so.

## Runs: one series per execution (kind `runs`)

An app's output that is a whole series each time it runs (a Link schedule's step response,
a model's prediction over the next hours) is one signal of kind `runs`: every execution is
kept as a series of its own, keyed by the run's time, instead of being written over the last.

`POST /hist/api/v1/data/derived/runs`, body:

```json
{"app": "linkcraft", "series": [
  {"signal": "app-linkcraft:FIC-101.response", "name": "FIC-101 step response", "unit": "%",
   "subject": "asset:fic-101", "result": "step_response", "managed_by": "link:<schedule>",
   "keep_runs": 10, "keep_days": null,
   "run_at": "2026-10-25T10:00:00Z", "t": ["2026-10-25T09:00:00Z", "..."], "v": [1.5, "..."]}
]}
```

- The signal is created with kind `runs` on its first run; a signal of another kind is a 409.
  `run_at` and `t` are ISO 8601 with offset, `t` ascending; `v` numbers or `null` (a gap). A
  run holds at most 20,000 values (100,000 per call). The same `run_at` again replaces that run.
- `keep_runs` (1 to 1,000, default 10): the newest runs kept; each write drops the older ones.
  `keep_days` (1 to 36,500): runs older than that are dropped too; `null` keeps them by count
  only (the signal's `retention_days` is then 0).
- Answer `{"written": <runs written>, "errors": [{"signal", "status", "detail"}]}`.
- Reads: `GET /signals/{id}/series?run=latest` (the default), `run=<ISO run time>` or `runs=N`
  (1 to 50, the newest N) answers `{"signal", "kind": "runs", "runs": [{"run_at", "t", "v"}]}`,
  newest first; `start`, `end` and `step` do not apply. In `POST /series` a runs signal answers
  its newest run as a plain series with `run_at` added. The point page offers the newest run,
  any one run, or the newest 5 or 10 together (runs over the same window overlay; runs over
  consecutive windows read as one continuous series).

## The suite's health (source `system`)

`POST /hist/api/v1/data/system`, body `{"series": [...]}`: the items of a derived write without
`app`, each signal `system:<name>`. PlantCraft's monitor writes it every minute
(PlantCraft `docs/operations.md`, section 4): `system:<service>.up`, `.latency_ms`,
`.cpu_pct`, `.mem_mb`, `.mem_pct`, `.restarts`, `.errors`, `.warnings`;
`system:host.disk_free_gb`, `.disk_free_pct`; `system:backup.age_h`, `.ok`, `.drill_ok`.

- The source `system` ("System", kind `system`, mode `archive`, kept 90 days) is created on the
  first write. Its id is reserved: no plant source may take it and no source may be of kind
  `system` (422). A plant source that took the id before it was reserved keeps its data and the
  health write is refused (403 for each signal).
- Only PlantCraft's own token writes it (403 otherwise); its signals are read like any other,
  and cannot be changed or collected. Same limits and answer as derived writes.

## Moving the sources out of PlantCraft

Once, at the upgrade, PlantCraft sends its sources to PlantCraft Historian and stops reading the plant:

`POST /hist/api/v1/data/sources/import`, body `{"sources": [ ... ]}`, each item the source as
PlantCraft keeps it: `{"id", "name", "type": "pi_web_api" | "opcua" | "csv", ...the fields of
DataSourceConfig..., "password": "<clear text or null>", "tags": [...]}`. PlantCraft Historian stores the
password encrypted (key in its data folder, like PlantCraft's), keeps the source id (so signal
ids do not change), adds each tag as a signal with the source's default mode, and answers
`{"imported": [ids], "skipped": [{"id", "reason"}]}`. Importing a source id twice updates it.
The call goes over the internal apps network only; PlantCraft then forgets the password.

## What PlantCraft changes (owner thread)

1. `HISTCRAFT_URL`; `/api/v1/signals*`, `/series`, `/value` forward to the routes above (same
   answers, the caller checked first as today); `PUT /api/v1/series` for app tokens; the
   Connections page calls `POST/PUT/DELETE /sources` and `POST /sources/{id}/signals`.
2. The upgrade step above, then `industrial_data` (sources, PI Web API client, cache, PI check)
   is removed; `processcraft pi check` moves to `histcraft pi check`.
3. The Connections page creates and edits sources through the routes above; PlantCraft Historian's own
   page (`/hist/sources`) shows the same sources with their collection state.
4. Compose and bundle: PlantCraft leaves the `plant` network; PlantCraft Historian and its database
   `histcraft-db` are part of every install (no longer an optional app), the `histcraft`
   image and the `postgres` image are in the bundle.
5. `FakePlantCraft` keeps serving data to apps as today (apps see no change); a
   `FakeHistCraft` for PlantCraft's own tests can come from PlantCraft Historian's tests on request.
