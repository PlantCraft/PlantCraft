# Devlog

Terse log, newest last.

## 2026-10-19

- Repository opened (the maintainer created `PlantCraft/histcraft`). Boundary with ProcessCraft decided
  and written down (`docs/boundary.md`): nothing moves out of ProcessCraft; HistCraft adds
  collection, archive and reads; apps keep reading through ProcessCraft (a `histcraft` source).
- Archive: chunk codec (deltas + float64 + zlib, text as JSON), store with neighbours on read,
  compaction to 10,000-value chunks, retention by chunk. Swinging-door compressor with max
  interval, step and text points, gaps. Reads: recorded, time-weighted grid (exact integrals of
  the rebuilt line), aggregates; v1 shapes from `processcraft_sdk.contract`.
- Collector: asyncio, one OPC UA connection per source, one schedule per scan period, reconnect
  with backoff, gaps on loss and on stop, requests (browse, test, read) for the server. A
  non-reentrant lock deadlocked on connection loss (found by the lost-server test); now an RLock.
- OPC UA timestamps: a source timestamp only moves when the value changes, and PlantCraft leaves
  ServerTimestamp at its start time; an unchanged value is stamped with the read time.
- Bench (`python -m histcraft.bench --points 2000 --seconds 1800`, this container): 105,992
  values/s, compression 6.1:1, 1.457 bytes per value read, compaction 6 s, grid read 2.2 ms.
- Live: PlantCraft smoke profile, 501 points browsed (4 s) and archived at 1 s; 491 collecting,
  10 bad (the simulator's injected quality faults on PIC-605 and AIC-904), 500 reads/s.

## 2026-10-19 (evening): the suite's app standard

- Adopted the decided app standard (ProcessCraft `docs/app-standard.md`): `app.toml`, port 8100,
  uid 10008 (direct collector 10013), `/api/meta`, `/api/help` with `docs/help/`, built files in
  `static/`, `make e2e` and `make package` targets, OCI app labels.
- "Only ProcessCraft reaches plant systems": new source kind `processcraft`, read with
  `POST /api/v1/values/current` (contract agreed with the ProcessCraft owner thread; the route is
  not in ProcessCraft yet, G15). Direct OPC UA is behind `HISTCRAFT_OPCUA` (off in the image) and
  the plant-network collector moved to an optional compose profile, pending the owner's decision.
- SDK 0.4.0 vendored (ProcessCraft main 7ddfaab, reproducible wheel); `processcraft-app check .` runs in `make ci`; `tests/floors.toml` (API operations, source kinds, compression ratio and density, test count, help pages); `make package` calls ProcessCraft's `deploy/package.sh --app app.toml --key`.

## 2026-10-19 (night): PostgreSQL

- Database choice for HistCraft (asked by the maintainer): plain PostgreSQL, decided 22:44. TimescaleDB
  was dropped over its licence: compression, retention policies and continuous aggregates are
  under the Timescale License, which allows shipping it only inside products "not primarily
  database storage" whose users cannot change the schema; a historian with the client's own
  database password does not fit. Compared also QuestDB, ClickHouse, InfluxDB 3 Core, IoTDB and
  TDengine (comparison in the data-layer proposal, section 6).
- `Database` takes a file path (SQLite) or a `postgresql://` URL; stores write one SQL
  (`ON CONFLICT`, `RETURNING`), `db.py` translates parameters, `LIKE` and the schema
  (`BIGINT` ms, `BYTEA`, identity ids, `{ANY}` = `JSONB` for snapshot values), pools
  connections (psycopg 3) and replaces NUL in text (PostgreSQL refuses it; found by the hostile
  inputs test). Adding points skips taken tags with `ON CONFLICT DO NOTHING`, because an error
  would end a PostgreSQL transaction.
- One flush of all points is now one `SELECT` and one pipelined `executemany`: PostgreSQL went
  from 17x to 47x real time for 2,000 points at 1 s (SQLite 60x to 63x).
- Every test runs on both engines (`make test-postgres`, CI job `postgres`, a schema per test);
  the docker job starts `histcraft-db` hardened as in compose and HistCraft on it.

## 2026-10-20: the suite's data layer

- The maintainer (2026-10-19 23:15): HistCraft owns every connection and every history. The
  `processcraft` source kind and the app key are gone; sources are `pi_web_api`, `opcua`, `csv`
  and `derived` (`app-<app>`). Signal ids everywhere are `<source id>:<tag>`; two sources may
  share a tag.
- `histcraft.sources`: PI Web API (GET only, paging, retries, digital states), OPC UA Historical
  Access (HistoryRead raw) and CSV, ported clean from ProcessCraft's adapters behind one
  `open_source(row, password)` interface in UTC ms; tests against local stand-ins.
- Per-signal mode: `source` reads the source per request (one call per source for a batch),
  `archive` the collected archive, `both` the archive and the source before it. Archive mode is
  refused for PI and CSV (G15).
- `/api/v1/data` for ProcessCraft only: signals with `app`, `subject`, `result` filters; series,
  batch, value; `POST /derived` (per-item app, merge-replace of overlapping chunks); sources
  create, update, delete, add signals, import.
- Source passwords encrypted with Fernet (`vault.py`), key file outside the database.
- Kerberos to PI is an optional extra: `gssapi` has no wheels, so it stays out of the image (G19).

## 2026-10-20 (afternoon): suite frame and settings in three levels

- Owner decisions D6 and D8 (ProcessCraft `docs/app-standard.md`, sections 10-11). Vendored
  `processcraft-sdk` 0.8.1 (its `processcraft-app check` now wants the ui package) and
  `@processcraft/ui` 0.2.0 in `vendor/` (hashes in `vendor/README.md`; the Docker frontend stage
  checks the tgz before `npm ci`).
- The top bar is gone: `SuiteShell` draws the sidebar (Overview, Sources, Points, Settings; the
  suite's Apps from `/api/v1/apps`; Help; user menu with theme, About with the version from
  `/api/meta`, Sign out = `POST /api/logout` on ProcessCraft, then `/`). New Help page with
  `HelpBrowser` over `/api/help`. `initTheme()` before the first render; tokens, fonts and shell
  styles come from the package; the local `tokens.css`, `fonts.css`, `Brand.tsx` and
  `appMarks.ts` (and its test) are removed. No language picker (English only).
- Settings in three levels, the most specific wins: general (Settings page) -> source (four new
  nullable columns on `sources`, added by a guarded `ALTER TABLE`: `Store.COLUMNS` and
  `Database.add_columns`, both engines) -> point. Points gained `inherits` (which of scan,
  deviation, max interval they take from above; `retention_days` NULL = inherit). Points added
  before keep their values as their own. Every point read resolves the values in effect, with
  `own` and `origins`; the collector (scan, compression) and the hourly retention use them.
  A source PUT that leaves a field out keeps it; null clears it. Browse leaves scan empty so
  new points inherit.
- `GET /api/points/{signal}` (37 operations); point page says "30 days, from the source".
  `tests/test_settings_levels.py` (6 tests: source beats general, point beats source, clearing,
  partial PUT, housekeeping uses the source retention, API); hostile inputs cover the new fields
  and route. 141 pytest (green on SQLite and PostgreSQL 16), 12 vitest.
- Screenshots (1440x900) taken for the review, kept outside the repository.
- Open: no e2e browser journeys yet (G12); ProcessCraft's Connections page does not show the
  source settings yet (the fields are in `/api/v1/data/sources`).


## 2026-10-20: @processcraft/ui 0.2.2

- Re-vendored `@processcraft/ui` 0.2.2 (ProcessCraft `11ce318`, sha256 `1a3d81f1...b3ab`): every
  relative import in its `dist` carries `.js`, and the phone drawer casts its shadow only when open.

## 2026-10-20: module names (D10), processcraft-sdk 0.8.2, @processcraft/ui 0.3.1

- Owner decision D10: only ProcessCraft keeps the Craft brand. This app is **ProcessCraft
  Historian** in documents, the package, `app.toml` (`name`, which `processcraft-app check`
  compares with the SDK's suite table) and the README, and just **Historian** inside the suite:
  page `<title>`, help guides and interface messages. Ids, the repository, `histcraft serve`,
  `HISTCRAFT_*`, the images and `/hist/` stay. AGENTS.md's map and oracle table name the current
  modules (Link for the former CPMCraft and DataCraft, Dashboards for TrendCraft).
- Re-vendored processcraft-sdk 0.8.2 (sha256 `e115d981...f959`) and `@processcraft/ui` 0.3.1
  (sha256 `04540bed...445da`), both from ProcessCraft `8dfd352`: the sidebar lockup shows
  "Historian" over "ProcessCraft", the Apps list shows short names, and a Messages button above
  the user menu reads ProcessCraft's `GET /api/v1/inbox`.

## 2026-10-20: install test fixes (user menu role, Browse compression)

- The user menu showed an admin as "editor" (the token's access to this app, which is only
  `editor` or `viewer`). `/api/me` gained `role`: `admin` for a ProcessCraft admin, else the
  access; the frame shows it. Test: `test_me_role_shows_an_admin_as_admin`.
- Points added from Browse got no compression: most OPC UA servers publish no `EURange`, and the
  default deviation (0.1 % of span) gave 0 without a span. A number point that inherits its
  deviation and has no range now takes that share of its value (`deviation_percent` on the
  point; the compressor keeps each segment within that share of the value it starts from).
  Points with a range, their own deviation, step and text points are unchanged. Tests in
  `tests/test_settings_levels.py`, `tests/test_compression.py` and `levels.test.ts`. 145 pytest,
  13 vitest.

## 2026-10-20: processcraft-sdk 0.8.3; setpoints and modes hold to now on a grid

- processcraft-sdk 0.8.3 vendored (ProcessCraft `7bcf870`, sha256 `e87b2459...6757b`), pins in
  the Makefile, Dockerfile, pyproject and `app.toml`; `@processcraft/ui` stays 0.3.1.
- HistCraft builds the grids ProcessCraft serves when HistCraft is its data layer, so it follows
  0.8.3's rule: a signal recorded on change (`recorded_on_change(tag, kind)`: text, or a tag
  ending in SP, SETPOINT or MODE) is rebuilt as steps and holds its last value until its next
  sample, a "no data" marker, `end` or now (`archive/query.py`, `_hold_on_change`). A setpoint
  read from a source's history and then left alone no longer goes null after its last sample.
  Recorded values and other signals are unchanged. Tests: `test_query.py`
  (`test_signals_recorded_on_change_hold_to_now_on_a_grid`,
  `test_the_on_change_hold_stops_at_now_and_at_a_null_sample`).

## 2026-10-20: number points that read text heal themselves

- Found on a demo install: about 15 minutes after the seed, LinkCraft marked FIC-1003 "Data not
  usable" because its MODE had no sample in 24 h. The MODE point had been added as a number (the
  source could not be browsed at that moment, so the default kind stayed), and a number point
  archives a text value as a "no data" marker only.
- The collector now turns a number point whose source answers text three reads in a row into a
  text step (`CatalogStore.make_text`), drops its archive (only markers) and queues a backfill of
  that point alone (`detail.points`, 48 h). Installs that already have such points heal on the
  next collector start, with no action.
- A point whose kind or step changes keeps its collector state object: the scan task holds it,
  and a new object would have stopped receiving readings.

## 2026-10-20: @processcraft/ui 0.3.2, the sidebar reordered

- `@processcraft/ui` 0.3.2 vendored (sha256 `2b9816bc...ef46d60c`), 0.3.1 removed. The fold
  button is at the top of the sidebar, the Apps list sits at the bottom above Help, and
  ProcessCraft is always the first app, so the platform is one click away from every page
  (owner feedback). No code change here.

## 2026-10-20: backfill; text values in number points; one source read per batch

- Found by the suite's end-to-end demo (ProcessCraft `processcraft demo seed` on PlantCraft):
  a MODE signal added by tag was archived as a number, and its text snapshot ("AUTO") made every
  batch read containing it fail (`ValueError`, ProcessCraft answered 502). Signals given by tag
  now take kind, step, unit and name from the source's browse; a text value in a number point
  reads as a gap.
- `both` read the source once per signal of a batch (a new OPC UA session each, about 0.75 s):
  LinkCraft's round of 200 signals timed out. The source's part of a batch is now one read per
  source.
- Backfill (gap G6, first half): `POST /api/sources/{id}/backfill` and a Backfill button on the
  Sources page; the collector copies the source's history into the archive in the background
  (`collector/backfill.py`, `tests/test_backfill.py`).

## 2026-10-21: recent source reads in memory (G20)

- `sources/cache.py` (`RecentReads`): per (source and its last change, address) the values of
  the last read and the span they cover. Inside the span: memory. Past its end: the source is
  asked from 5 min before the cached end (late samples) to the new end, and the tail joined on.
  A span is read whole again after `HISTCRAFT_SOURCE_CACHE_SECONDS` (300; 0 turns it off), and
  errors are never kept. At most 5,000 addresses and 200,000 values per address.
- Used by `Runtime.recorded` for PI Web API and OPC UA sources; CSV keeps its own in-memory
  frame (read again when the file changes), so it is not cached twice and a deleted file is
  seen at once.
- Tests: `tests/test_source_cache.py` (a refresh answers like a whole read; errors, earlier
  starts, changed sources and old spans read the source again) and a PI signal read twice
  through `/api/v1/data` in `tests/test_api.py`.

## 2026-10-21: hourly rollups for long trends (G9, part)

- Table `rollups (point, hour, step, cover, area)`: for each sealed hour (one that ends before
  the point's last archived value) the time with data and the integral of the rebuilt signal,
  linear or held as the reads rebuild it (`step` or recorded on change). The first archived hour
  is left out (a `both` point joins its source's values there).
- `Reader.series` on a grid of whole hours, starting on an hour, reads them: a cell whose hours
  are all there is `sum(area) / sum(cover)`; runs of cells that are not come from the samples as
  before. Same numbers as the samples (tests compare to 1e-9 on hourly, 6-hourly and daily grids).
- The collector's housekeeping fills missing hours, at most 31 days per point per run
  (`rollup.BUILD_HOURS`). `append` drops hours from the one holding the stored value before its
  first new value; `replace` drops the hours between the stored values around the new ones;
  `prune` the hours up to the first value left; `delete_points` all of them.
- Bench (PostgreSQL, 2,000 points, 30 min), before and after: compaction 24.0 s and 25.0 s,
  grid read 3.4 ms and 4.1 ms, raw read 2.6 ms and 3.0 ms (one run each).
- Monthly partitions stay open in G9.

## 2026-10-21 — a flush costs the same with any number of chunks waiting for compaction

- Found by the suite bench at 8,000 signals (ProcessCraft `ci/bench/suite_bench.py`): since the
  hourly rollups, `append` found the hours to drop with `MIN(t0)`/`MAX(t1)` over every chunk of
  the point. The collector flushes every 5 s and compacts hourly, so up to ~1,440 chunks per point
  wait: each flush grew ~9 ms per chunk at 8,000 points (0.53 s after 30 flushes, 1.7 s after 180;
  past the 5 s flush period in about an hour). Now one row through the primary key: the last chunk
  starting before the new values (chunks of a point never overlap); a test checks it against the
  full scan on 200 flushes.
- 8,000 points, PostgreSQL, one flush per 5 s with 2 values per point: 0.45-0.50 s per flush,
  flat over 480 flushes (was 0.53 s rising to 1.69 s by 180).
- `histcraft.bench` reports the first and last minute's mean flush. PostgreSQL, 2,000 points,
  30 min, before and after: 38,947 and 97,722 values/s (19.5x and 48.9x real time), flush 98 ms
  -> 392 ms and 78 ms -> 83 ms, compaction 18.2 s and 18.0 s, grid read 2.7 and 2.9 ms.

## 2026-10-21 — a steady signal is archived every 10 minutes (was every hour)

- Suite bench at 2,000 loops: every bench loop came out "data not usable" because its constant
  setpoint was archived once an hour (`default_max_seconds` 3,600) and Link's availability check
  counts an interval above 10 min as a gap ("Samples cover 17% of the window; 24 gaps, the
  longest 60 min"). Any real loop with a setpoint steady for more than 10 minutes hits this.
- `default_max_seconds` is now 600: points that inherit it follow, points or sources that set
  their own keep it. Cost: at most 144 values a day for a signal that never moves.
- Still open: PI Web API sources read in `source` mode keep PI's own compression maximum (often
  8 h), so Link needs a gap rule that knows the historian's maximum interval (Link side).

## 2026-10-21: on the suite's shared server and test kit (processcraft-sdk 0.9.0, @processcraft/ui 0.7.0)

- Server: the web application, access checks, `app.toml` and help come from
  `processcraft_sdk.server` (`meta.py` and `api/app.py` keep only Historian's own parts; `db.py`
  stays: PostgreSQL or SQLite). `/api/help` now answers the suite's shape (`id`, `title`,
  `category`); the image puts the guides in `/app/docs/help` like every app. The image's
  description label is now `app.toml`'s summary (the suite rule found it).
- Interface: the API client and the Help page come from `@processcraft/ui`.
- Tests: `tests/test_suite_rules.py` (offline, layers, image, and Historian's two boundary rules,
  on `processcraft_sdk.apptest`) replaces `test_offline` and `test_architecture`; the tests
  against a real OPC UA server are the slow tier, so `make test-fast` runs in 10 s instead of
  54 s; time budget in `pyproject.toml`. The SBOM stays `deploy/sbom.py` (CycloneDX with the
  interface's npm packages) until the SDK's covers them.
- Docs: `AGENTS.md` is the short module file (the suite's rules live once, in ProcessCraft's
  `AGENTS.md`); the README says how the module is built (with Claude Code, in the open); `make
  test-fast` in Develop.

## 2026-10-21: Export (the owner: data is exported from the Historian)

- **Export** (`/export`, `api/routers/export.py`, `export/package.py`): tags, loops, groups of
  loops or a whole unit, in any mix, over a period, as one ZIP (`series.csv` wide in UTC,
  `signals.csv`, `assets.csv`, `plant-map.json`, `manifest.json` with a SHA-256 per file,
  `README.txt`). Loops and groups come from ProcessCraft's asset tree read with the person's own
  token; an asset takes everything under it. As recorded up to 7 days, means up to 31 days, 500
  tags per package. Optional aliases (S001, A001) with the key downloaded apart. Audited as
  `histcraft.export`. Link's export (a first version, earlier today) moved here.
- `@processcraft/ui` 0.9.0 (the assistant panel the apps open beside their objects).

## 2026-10-21 (night): Export by list, saved exports

- The owner: "search, tick with a checkbox, add, and everything added goes to a list below;
  Export exports it", "no Loops mode", "a way to save this export configuration".
- **Export page**: one search over assets of every kind and tags, a **Kind** filter
  (`MultiSelect` from `@processcraft/ui` 0.10.0; a loop is one kind of asset among others),
  checkboxes and **Add**. `POST /api/export/resolve` turns the assets added into their tags (with
  the asset and role each came from); the page then exports exactly that list
  (`expand_assets: false`), the assets kept as metadata.
- **Saved exports** (`export/saved.py`, `/api/export/saved`): name, tags, assets, a relative or
  fixed period, resolution, aliases. Anyone who exports saves; the author or an editor changes or
  deletes.

## 2026-10-22: owner's review, round 5

- **Sources**: Add source asks the type first (OPC UA, PI Web API, CSV file, each explained),
  then opens that type's form; "Kind" is "Type" everywhere. Every source has a page
  (`/sources/<id>`): what it is, how it is read, the settings it gives its points (in effect and
  from where) and its points; a derived source names its app ("Link") and links to it.
- **CSV upload** (`POST /api/sources/files?name=`, admins): a wide CSV sent from the page is kept
  in `HISTCRAFT_DATA_DIR/files/` (same name replaces it) and the form fills the path. The demo
  seed (ProcessCraft) sends a month of lab analyses this way: source `lab`, the second type of
  source beside PlantCraft's OPC UA server.
- **Points**: the suite's `DataTable` (pages of 25/50/100, filter, sort by every column), status
  tiles and the source filter kept; a source's page uses the same columns.
- **A point's trend** draws with `@processcraft/ui` 0.12.0's time chart (the layout, hover and
  buttons of View's Trends) and the same period picker (last 15 minutes to 30 days, or from–to).
- **Settings**: tiles like ProcessCraft's Setup; one, "Retention and collection", opens the
  general level (general, source, point: the most specific wins).
- **Export**: the download says where the file went and what it holds (`X-Package-Rows`,
  `-Signals`, `-Not-Read` from the manifest). A small ZIP is normal: two hours at the default
  "every 10 minutes" is 12 rows per tag, and CSV compresses well.
- Overview: the "From connection to trend" box is gone (owner: removed page by page).

## 2026-10-22: housekeeping beside the flushes

- Suite architecture review: on PostgreSQL with 8,000 points at 1 s, the hourly compaction took
  118 s in one transaction, awaited in the collector loop, so nothing was flushed (and the
  heartbeat stood still) for two minutes every hour.
- Now housekeeping runs in its own task beside the flushes, and `compact` and `prune` take one
  short transaction per point with a 1 ms pause between points (Python's lock is not fair).
  Measured on PostgreSQL, 8,000 points, 30 min of 5 s chunks: flushes during the compaction
  p50 388 ms, max 589 ms (before: none for its whole length). The compaction itself takes longer
  (214 s instead of 121 s), which is fine once an hour.

## 2026-10-22 (night): the suite's health as signals

- The source `system` (kind `system`, mode `archive`, 90 days, reserved id) and
  `POST /api/v1/data/system`, written every minute by ProcessCraft's monitor (ProcessCraft
  `docs/operations.md`, section 4). Derived and system writes share `_store`; the pages treat
  both kinds as written by the suite (`isWritten`), never browsed, tested or edited.

## 2026-10-22: the collector as its own service

- The suite's compose file runs `histcraft-collector` (`histcraft collect`, same image, no port,
  health = heartbeat) beside `histcraft serve` (`HISTCRAFT_COLLECTOR=off`). An update or restart
  of the server, or a heavy query in it, no longer pauses the recording.
- One collector per archive (`collector/lease.py`): PostgreSQL session advisory lock
  `(420710, hashtext(current_schema()))` on a connection outside the pool, or `flock` on
  `archive.sqlite3.collector.lock`. A second collector logs that it waits as a standby and asks
  again every 5 s; a dropped lease connection stops collection (exit 1, the container restarts).
  `histcraft housekeeping` now refuses to run beside a collector. Tests:
  `tests/test_collector_lease.py` (SQLite and PostgreSQL).
- 2026-10-23: Sources review (round 6): retired apps' derived sources marked and removable with their points, Twin's dropped on start, CSV "Read in place", Export filter "Type".
- 2026-10-23: G5 quality kept: uncertain OPC UA values archived with quality, `qualities` table of changes, trend shading, "quality not reported" for sources without it.
- 2026-10-23: G2 secure OPC UA: Sign/SignAndEncrypt, client certificate in <data>/pki, server pinned by SHA-256 (Test shows it, admin trusts), history reads too.
- 2026-10-23: G11 (part): point list CSV export/import with preview and per-line errors.
- 2026-10-23: G11 closed: calculated points and totalizers (source calc, formula allow list, collector CalcReader, quality from inputs).
- 2026-10-23: G10 (most): gateway Telegraf -> collector line-protocol ingest, MQTT/Modbus/SQL sources, generated allowlisted config.
- 2026-10-23: point trend on @processcraft/ui 0.24.0 TimeChart + PeriodPicker; local Plot.tsx, qualityBands, localOf/isoOf removed.
- 2026-10-24: round 7: CSV imports (check, confirm, list, delete with data; collector writes, file deleted) and CSV files sources (file or pattern, checked every N minutes, archived); `sources/csv_table.py` reads both; bench cleanup misses fixed (#140).
- 2026-10-24: round 7: source checks against the Simulator's test kit (sources_check/, pinned Telegraf from Docker Hub without Docker); 4 gateway/OPC UA bugs found and fixed (docs/source-checks.md). make sources-public from this container: no route to the public servers (non-HTTP egress blocked).
- 2026-10-25: Alarms round 8: `histcraft.conditions` names what is open (collector stalled, source disconnected, point without data, at most 50) from the collector's state and snapshots, no archive read; `ops.report_conditions` puts them in `/api/ops/metrics` and PlantCraft writes them as `histcraft.*` events (SDK 0.28). Three events declared in `app.toml`.
- 2026-10-26: round 10 review: Imports/Exports split into sidebar pages (no PageTabs), Add source type picker as a list, import examples open checked in the dialog; browser check of every import format (examples, ; with decimal comma, tab, pipe, epoch, notes above header, xlsx, next file, delete, exported series.csv re-imported); fixed export losing a column when two sources share a tag.
- 2026-10-26: write path for 2k-50k points (stack review): collector writes one `recent` row per 5 s flush and settles to chunks every 60 s with one unnest statement per table; zstd + byte-shuffle codec (0x20/0x21, float32 when exact; zlib 0x10/0x11 still read); compaction 200 points per transaction reading only the chunks it merges; closed months rewritten once (detach/attach swap); rollups keep low/high/n, used by `/value` mean/min/max and the trend band past 7 days. Bench (4-core x86, PG 16 on 2 cores, 5 min at 1 s): 50k points 1.44 -> 0.11 cores, capacity 1.7x -> 16.5x real time.
- 2026-10-27: one-year archive bench (800 points x 365 days, 18 GB, PG 16, shared_buffers 512 MB): reads find chunks by `t0` only (range + last before + first after; was `t1 >= start`, which walked the point's whole history: 1,347 -> 11 pages for a day); `rewrite_closed` also rewrites closed rollups months (a year's trend 8,846 -> 170 pages, cold 470 -> 71 ms).
- 2026-10-27: Overview redesign: default board statuses (8x2) + collector, new `stored` (columns, values per hour over 24 h from `point_hours`: at most 25 rows per point, one GROUP BY hour for an unlimited person, never a read of chunks) + new `source-map` (tiles, enabled signals by source, worst source first; stale = `conditions.stale_ms`), then not-collecting + archive (trimmed to on disk, grows, disk full in, free, oldest). points, trend, sources stay declared and served. SDK 0.69.0, ui 0.72.0.
- 2026-10-27: tiered compaction (closed hour -> day -> month, merge only within the tier and when neighbours fit; collector looks back to the previous month), UNLOGGED `snapshots` + `refill_snapshots`, `point_hours` written every 10 min. WAL bench (collector write path with simulated clock, 300 points, 1 day, PG 16 defaults): 1,562 MB -> 328 MB; before: snapshots 999, compaction 303, settle 204 MB.
- 2026-10-27: final review round: collector + archive widgets as lists (SDK 0.76.0 rule: times in detail), source map orders plant sources before app/system series and carries each signal's description in its square's detail; signal list export/import moved from Signals to Exports/Imports (SignalList.tsx); Signals Type filter on the scan column.
- 2026-10-28: `signal_shape` (API of other apps) gives low/high only when the range is the source's or a person's: a suggested range stays in the Historian until confirmed (Analytics judged data against it).
