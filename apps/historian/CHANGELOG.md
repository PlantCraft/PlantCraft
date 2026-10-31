# Changelog

Every release of PlantCraft Historian (`histcraft`), newest first, in the
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) form. PlantCraft's `deploy/bundle.sh`
joins it into the bundle's release notes.

## [Unreleased]

### Added

- **Notes on a signal**, at an instant or over an interval: the signal's page lists the notes of
  the period shown and editors add them (their own removed by them, any by an administrator);
  `GET`, `POST` and `DELETE /api/v1/annotations` for scripts and apps. Each note is told to
  PlantCraft as the event `histcraft.annotation.added` (*Note on a signal*), posted by the page in
  the person's name, since the Historian never calls the suite.
- **Shortest interval between archived values** per number signal (`min_seconds`, PI's
  CompMin; empty: none), on the signal's page and in `PATCH /api/points/{signal}`: a faster
  change is held until then. Gaps, quality changes, step and text signals are never held back.
  The step marker (a held value that jumps is archived at its last read before the jump, so a
  trend draws a step) is now pinned by tests and described in the compression help.
- **Laboratory results as signals (`laboratory:<analysis>`).** `POST /api/v1/lab` (editors, or a
  bridge from the LIMS with a person's key) stores each result at its sampling time, however late
  it arrives, with the times it reached the laboratory and was approved; it reads as `uncertain`
  until approved and `bad` when rejected, and writing the same sample again (a retest) replaces
  its value and counts the write. `GET /api/v1/lab/{signal}` lists a window's samples with their
  times and how late each was written. Trends, Analytics and the estimators read the analysis as
  any signal, at the time the sample was taken (industry reference library, LIMS and MES).
- **A limit on the points it records**, from `MAX_SIGNALS` of PlantCraft's installation file
  (`PLANTCRAFT_MAX_SIGNALS`): points past it are skipped with the reason; the series apps write
  do not count.

### Changed

- **Reads of the same hours decode each archive chunk once.** Each process keeps the chunks it
  decoded last (`HISTCRAFT_CHUNK_CACHE_MB`, 32 by default, 0 turns it off); a chunk's bytes are
  its key, so a rewritten chunk is read anew. A read of 167 signals over a day went from 1.0 to
  0.45 s, and an Analytics round, its checks and its methods a quarter to a third faster under
  the 0.6.0 load test C2 (2026-10-31).

### Fixed

- The points export's file name keeps only safe characters (a tag with others answered 500).

## [0.5.1] - 2026-10-30

- Suite 0.5.1: `plantcraft-sdk` 0.79.0 and `@plantcraft/ui` 0.89.0, with the new look (the PC valve logo, Steel Blue and the new app marks).

### Changed

- The OPC UA client certificate downloads as `plantcraft-historian.der`.

### Fixed

- A public demo's visitors export, but save, change or delete no saved export: they all share
  one account.

## [0.5.0] - 2026-10-27

### Changed

- **Final review round (2026-10-27).** The collector and archive widgets are lists like the
  cards beside them (no big number or badge of their own); the source map puts the plant's
  sources before the series apps and PlantCraft write, and each square's hover says what the
  signal is. Signals keeps only **Add calculated signal** (adding from a source is on Sources, in the menu; owner rule: no header button for a page the menu has): **Export signal list** moved to
  Exports and **Import signal list** to Imports. Signals gains a **Type** filter (plant,
  calculated, imported, written by an app or by PlantCraft).

- **The sources widget says since when each source is connected** ("OPC UA · Connected 5 h ago")
  instead of a bare time (SDK 0.76.0).
- **Overview, redesigned around "is data arriving from every source, and will the disk hold?"**
  Signals by status beside the collector; two new widgets, **values stored** (per hour over the
  last 24 h, from the archive's per-hour counts, never a read of the values) and **source map**
  (every enabled signal as a square by source: collecting, late or uncertain, not collecting,
  source disabled; each a link to its signal); then the signals not collecting beside the
  archive, now trimmed to on disk, growth, disk full in, free and oldest value. The points count,
  the trend and the sources leave the default board but stay available. `processcraft-sdk`
  0.69.0, `@processcraft/ui` 0.72.0.

### Security

- **Asset scope (decision D2).** A person who sees only part of the plant (PlantCraft's token claim
  `assets`) reads here only its points: the direct reads (`/api/v1/signals`, series, values,
  batches), the Points pages and trends, the widgets, the search and the exports. `processcraft-sdk`
  0.66.0.

### Changed

- **Much lighter writes to PostgreSQL (WAL).** Compaction goes by tiers of time: a closed hour's
  minute chunks merge into one, a closed day's hours, then a closed month's days; a value is
  rewritten three times at most and a full chunk never again (before, each point's growing chunk
  was rewritten every hour). `snapshots`, rewritten every flush, is UNLOGGED (refilled from the
  archive after a database crash); values per hour are counted every 10 minutes, not every
  minute. Collector write path, 300 points, one day: 1.56 GB of WAL -> 0.33 GB (50x -> 10x the
  values archived). Reads unchanged.

### Fixed

- **Long reads at once no longer take the Historian past its memory.** Several raw reads of
  fast signals in parallel (a day of 20 signals is over a million values) built every answer
  whole in memory, about 220 MB each, and the container restarted at its 2 GiB limit (Mac mini
  stress test, 2026-10-27). Batch answers are now JSON as soon as each series is read (about a
  quarter of the memory), skip FastAPI's per-item encoder, and the reads in flight share a
  budget of `HISTCRAFT_READ_VALUES` values (default 4 million): a read past it waits, and after
  `HISTCRAFT_QUERY_TIMEOUT` answers 503, which the SDK's client asks again. The image runs with
  two malloc arenas (`MALLOC_ARENA_MAX=2`), so that memory goes back to the system after the
  reads. Load test: 16 raw reads of 700,000 values at once peaked at 1.82 GiB of 2 and stayed at
  1.4 GiB; now 0.93 GiB peak.
- **Compacting a long backlog no longer runs out of memory.** After a backfill (90 days of
  minute chunks for 120 points) compaction held every small chunk of 200 points at once and
  took the process past 8 GiB; it now goes in steps of at most 20,000 chunks and fewer points
  per batch: 13 million chunks in 13 minutes under 540 MB.
- **processcraft-sdk 0.64.0** (from 0.52.0): its queue database uses the rollback journal on a
  Docker Desktop bind mount, where WAL can crash an app with several processes (bus error).

### Added

- **A new plant's first step: "Collect the signals" (`[[contributes.start]]`, processcraft-sdk
  0.65.0).** Once an administrator applies an import of assets in PlantCraft, the Historian
  collects the signals it bound from the sources it holds, described by each source's browse
  (`POST /hist/api/start/collect-signals`); signals collected already are kept, and those of a
  source it does not hold are counted.

- **Imports in the suite's work queue** (owner's Alarms review, 2026-10-26): `GET /api/queue`
  answers `plantcraft-queue/1` with the files waiting, being written and finished in the last
  24 hours (`items`: who, step, progress 0-1, cancel while waiting) and the page it links to
  (`url`: Imports); its numbers are sampled every 15 s into `queue.sqlite3`. The Imports list
  shows each file's progress; a file still waiting can be cancelled
  (`POST /api/imports/{id}/cancel`).
- **An import repeats from a folder** (`PUT /api/imports/{id}/repeat`): every 15 minutes to
  every day the collector reads each new or changed file of a pattern inside the CSV folders,
  the way the import reads its files, into the same signals (new tags become signals). The
  files are only read. A repeating import is also listed under Sources.

### Changed

- **The collector writes 50,000 points with a fraction of the CPU** (stack review, 2026-10-26):
  every 5 s it writes one row holding all points' new values (the archive's recent values,
  which reads include) and once a minute moves them into one chunk per point, with one
  statement per table for all points instead of three per point
  (`HISTCRAFT_ARCHIVE_SECONDS`, 60). Chunks are written as zstd with byte-shuffled values
  (float32 when exact): smaller and faster to write; chunks written before are read as they
  are. Compaction reads only the chunks it merges, and a month closed for a day is copied once
  into a fresh table, giving back the space compaction left. New dependency: `zstandard`
  (BSD-3-Clause).
- **Hourly rollups keep each hour's lowest and highest value and its count**: the min/max band
  of trends longer than 7 days, and a window's mean, min or max (`/value`), read them instead
  of every value. Existing rollups are built again by the hourly housekeeping.
- **A point without data is reported once when it starts and once when it ends**, for up to
  1990 points (was 50), under the platform's event limits (Alarms round 11).
- **Imports and Exports are each a page of the sidebar** (owner's review, 2026-10-26), no
  longer two tabs under one title; `/transfer` and `/export` still open them.
- **Add source lists the types** as a plain list (icon, name, a few words) instead of cards.
- **The import examples open in the import dialog**, checked, for whoever can import (a
  download alone looked like nothing happened); the example can still be downloaded there.

### Fixed

- **A short read no longer walks a signal's whole history** (one-year archive bench,
  2026-10-27): a read found its chunks by `t0 <= end AND t1 >= start`, so PostgreSQL went through
  the index entries of every month before the range (1,347 pages for one day of a signal with a
  year of history; 11 now). Chunks of a signal never overlap, so a range needs the chunks
  starting inside it plus the last one before and the first one after, all found by `t0`.
- **Closed months of hourly rollups are rewritten too**: the collector writes every signal's
  hour at once, so a signal's year of rollups sat on one page per hour (8,760 pages for a
  year's trend). The hourly housekeeping now rewrites a closed month of `rollups` in key order
  after the one of `chunks`; a cold one-year trend went from 470 ms to 71 ms.
- **No "no data" for signals the collector does not read** (visual sweep, 2026-10-26):
  `histcraft.point.no_data` named the signals apps write (an Analytics algorithm's version,
  written once per version), the suite's health and imported files, and Alarms' "No data from
  the plant" raised 57 false alerts on a fresh demo. Only collected sources are judged now.
- **Words:** the Historian's messages and widgets say signal, not point (glossary); the disk
  forecast says "Not in sight" past ten years instead of "623046 days".

- **An export of one tag from two sources keeps both columns** (2026-10-26): two imports of
  the same file, or a tag in two plants, wrote one `series.csv` column and lost the other.
  Such columns are now named `source:tag`.

- **Deleting points leaves nothing behind** (2026-10-26, found by the bench on the Mac mini):
  removing thousands of points at once could end in a PostgreSQL deadlock and leave their
  hourly counts (`point_hours`) behind. Points are now deleted in batches of 500, each a short
  transaction taking the tables in the order writes do, tried again on a deadlock, and the
  collector's sweep finds rows of removed points in every point table, so anything a failed
  delete left goes on the next sweep.

### Added

- **The assistant on Points and Sources:** which points need attention, ask about the sources.
- **The assistant's works on a point** (processcraft-sdk 0.39.0, PlantCraft `docs/assistant.md`,
  "Works"): explain the signal's behaviour, check its quality. They replace the page's two
  similar tasks.

### Changed

- **The suite's dialog** (`@processcraft/ui` 0.53.0, scale review A1): its seven windows (sources,
  browse, imports, point list, calculated point) and the remove and delete questions are the ui's
  `Dialog` and `confirmAction()` instead of the browser's confirm or a window drawn here, so they
  follow the theme, keep the focus inside and close on Escape.

- processcraft-sdk 0.35.1: the suite's rules for an app's inside (PlantCraft
  `docs/app-standard.md`, section 5) run here too. The catalog's shapes and rules
  (`SourceIn`, `PointIn`, the kinds and settings, `CatalogError`) live in `catalog/models.py`
  and the stored time in `clock.py`, so the routers import no store. Nothing changes for
  people.

### Added

- **Disk forecast and alert** (owner, round 8 D4, 2026-10-25): Settings › Retention and
  collection says how much the archive grows a year and when the disk is full ("13 GB a year;
  the disk (500 GB free) is full in 4 years"), from the values archived in the last 24 h, each
  point growing until its retention deletes as much as it writes (0 days keeps it forever).
  The collector's housekeeping stores the forecast hourly, and a new event
  `histcraft.archive.disk_low` opens when the disk fills in fewer than 90 days (rule: admins,
  high). `GET /api/overview` carries it as `archive.forecast`.
- **Every number point has a range** (owner, round 8 D2, 2026-10-25): the server's (OPC UA
  `EURange`, and now PI's `Zero` and `Span` from Browse), else a person's, else one suggested
  by the collector's hourly housekeeping from the point's first day of values (its extremes
  plus 10 % each side, rounded outward, from 0 for values never below it). Points carry
  `range_origin` (`source`, `edited`, `suggested`, or empty while there is none); the point
  page edits the range, says where it comes from and confirms a suggestion. The compression
  follows the range from then on; values archived before are not touched.
- **Compression like PI's, with profiles** (owner, round 8 D1, 2026-10-25): before the
  swinging door, an exception (general setting `default_exception_percent`, 0.1 % of the span)
  takes a value within it of the last one passed on as that value, so noise below it is never
  archived; the compression deviation default is now 0.2 % of the span (was 0.1 %, which on a
  point without a range was 0.1 % of the value, below the noise: 40,000 to 85,000 values a
  day per PV in the Simulator; now 2,000 to 12,000). A point picks a profile: Standard (the
  general settings), Fine (0.05 % and 0.1 %), No compression, or Custom (its own exception and
  deviation in engineering units). The longest interval between archived values stays 10 min:
  Link's availability check counts a longer interval as missing data. Values archived before
  are not touched (D3).

- **Runs: one series per execution** (Link and Historian round 8, H2): a derived signal of
  kind `runs` keeps each run of an app's series output as a series of its own, keyed by the
  run's time (`POST /api/v1/data/derived/runs`), the newest `keep_runs` (default 10) and, when
  the app says so, none older than `keep_days`. Reads give the newest run, one run or the
  newest N (`series?run=`, `runs=`), and `GET /signals/{id}/runs` lists them. The point page
  picks a run or draws the newest 5 or 10 together.
- **Reads have a time limit** (with PlantCraft's per-person limits on API
  v1): a read of series (`GET /api/v1/data/signals/{id}/series`, `POST /api/v1/data/series`,
  the point page's trend) stops after `HISTCRAFT_QUERY_TIMEOUT` seconds (default 30) as
  PostgreSQL's `statement_timeout`, for that read's transaction only, and answers 504 "This
  read took longer than 30 s: ask for a shorter period or a larger step." The collector's
  writes and migrations have no limit; SQLite installations have none either.

- **More kinds of value, kept forever, set by the app** (Link and Historian round 8, H1): a
  derived signal is `number`, `integer`, `boolean`, `text`, `instant` (an ISO time) or
  `structured` (a JSON object or array, up to 64 kB); reads come back typed by kind and the
  point page draws on/off as 1 and 0 and times and structured values as labels. A retention of
  `0` days keeps a point (or a source's points) forever. `POST /api/v1/data/derived` takes
  `retention_days` and `managed_by` (such as `link:<schedule>`): such a point's retention and
  compression are then changed only by its app (409 for people). Signal descriptions carry
  `retention_days` and `managed_by`. Texts are now cut at 1,000 characters (was 500).

- **Its events** (processcraft-sdk 0.28, Alarms round 8): `app.toml` declares
  `collector.stalled` (no heartbeat for two minutes), `source.disconnected` (key `source:<id>`)
  and `point.no_data` (a point of a connected source whose last value is bad or older than ten
  of its scans, at least 10 min; key `point:<id>`, at most 50, the oldest first). The Historian
  has no app key: it names them in `GET /api/ops/metrics` (`histcraft.conditions`) and
  PlantCraft's monitor writes them as its events, start and end. A disconnected source is one
  condition, not one per point; while the collector is stalled nothing else is said. The
  suggested rule of `collector.stalled` is on in a new installation.
- **A source's archive at a glance**: the source page shows the values
  archived in the last 24 h (and the point that archives most), the archive's size, the
  compression since the collector started and the latest value with the points in error. The
  point list and the point page show each point's values for the last 24 h; Overview the total.
- **A point's trend, looked at closely**: values as recorded (up to a day)
  or as averages, the lowest and highest value in each average as a band (up to a week; API
  `extremes=true` on a point's series), the archived values as dots, the compression deviation
  around them, the same period before, a day or a week earlier, and the series as CSV.
- **Imports read more files, and are kept**: Excel (`.xlsx`, a sheet of your
  choice, through openpyxl) next to CSV/TSV; checking a file fills in how it is read (separator,
  decimal mark, rows to skip, wide or long layout, time column and format, day or month first,
  tag/value/quality columns, tag prefix) with the first rows as read, and any of it can be changed
  and checked again. An import is kept like an export: "Import the next file" adds another file
  to it (an overlapping period is replaced), and example files for both layouts download from
  the Imports page.
- **Certificates for PlantCraft's Health** (B17): `GET /api/v1/certificates` lists the
  Historian's OPC UA client certificate and each source's trusted server certificate with its
  expiry and SHA-256 (read with a service token); `POST /api/v1/certificates/opcua-client/renew`
  (administrators) makes a new client certificate and answers it as PEM, for the servers to
  trust. Server certificates seen are kept in `<data>/pki/servers/` so their expiry is known.

### Changed

- Time zones are picked from the suite's list (ui 0.42.0): an import's "Local time" is the
  installation's zone when the file is read; a CSV source names its zone (UTC, a fixed offset
  or a city).
- processcraft-sdk 0.26 (the event's own fields and catalogs); no events declared yet.
- A new client certificate is valid for two years, not ten (existing ones are kept until
  renewed).
- Pages no longer count the archive themselves: the collector keeps each point's totals
  (`point_totals`, counted again every 5 minutes and after housekeeping) and its values per hour
  of their time (`point_hours`, a week). Opening Points used to scan every chunk.

## [0.4.0] - 2026-10-24

### Added

- **Source checks** (`make sources-check`, `docs/source-checks.md`, CI job `sources`): CSV, PI
  Web API, OPC UA, MQTT, Modbus and SQL against the Simulator's test kit, the gateway kinds
  through the suite's pinned Telegraf. `make sources-public` checks public servers by hand.
- The demo seed adds an example import (`pilot-test-run-2026-09.csv`, six hours of a pilot
  unit's test run), so a fresh demo shows Import & export with one finished import.
- **Import & export › Imports**: a CSV file loaded once. Historian checks it
  first (layout, separator, decimal comma, time format and zone, per-line errors and notes) and
  writes nothing until the person confirms; the collector writes the values and deletes the
  uploaded file. Each import is a source `import-<n>` kept until deleted; deleting it removes its
  points and values. `POST /api/imports/check`, `POST /api/imports`, `GET /api/imports`,
  `DELETE /api/imports/{id}`; help page Imports.
- **CSV files** sources watch a file or a pattern (`/csv/lab/*.csv`) another application keeps
  writing: the collector checks every `check_minutes` (default 5), archives new lines and new
  files and never moves them. Long layout (time, tag, value, quality) as well as wide.
- The suite's search (Ctrl+K, PlantCraft 2026-10-23): `GET /api/search` answers with its points and sources
  (`processcraft_sdk.server.search`). `@processcraft/ui` 0.25.0 and `processcraft-sdk` 0.21.0
  bring the search box and the queue clock to the frame; the SDK answers the frame's queue
  probe for an app without a queue, so no page logs a 404.

### Fixed

- Found by the source checks: Modbus 64-bit registers take Telegraf's eight-letter byte orders
  (four-letter ones are read as their long names); integer registers with a fractional scale
  keep their decimals (sent as FIXED/UFIXED); SQL sources no longer list the time and tag
  columns as points; OPC UA history reads (backfill, mode `both`) take the whole NodeId Browse
  gives.
- A stop or lost connection always archives its "no data" marker: a source clock at or a few ms
  ahead of the collector's no longer swallows it (the marker goes 1 ms after the last value).

### Changed

- The suite's button and form standard (`@processcraft/ui` 0.34.0, app standard §10): Settings ›
  Retention and collection and a point's Collection and compression are a `form-panel` with
  `FormSection`s and a `FormFooter`; Remove, Delete and Delete for good are `button-danger`; a
  saved export's delete is an icon button. The Export form's own footer style is gone.
- A point of a CSV, import or gateway source no longer shows a scan period of its own (its values
  are not read on a scan) and says where they come from; a point page opens its trend on a window
  that holds the newest value (a lab analysis every 4 h no longer opens on an empty hour). The
  import check quotes the separator and decimal it found.
- Points: the button that loads a list of points is **Import point list**, apart from
  Import & export's **Import CSV**, which loads values.
- CSV sources are archived (mode `archive`) instead of read in place; an existing CSV source's
  file is archived on its first check. The upload on the Sources page gave way to Imports.
- Nav: Export becomes **Import & export** with tabs Imports and Exports (`/transfer`; `/export`
  still opens Exports). Texts: "Points from this source", "Point defaults for this source".
- The suite's visual identity (`@processcraft/ui` 0.28.0, PlantCraft `docs/brand.md`): Inter and
  JetBrains Mono, neutral greys, sentence-case labels, the app switcher at the top of the sidebar
  and the fold button in its bottom corner. The IBM Plex packages are no longer needed.
- Every time in UTC (PlantCraft, 2026-10-23): `processcraft-sdk` 0.20.0 (`dev/revendor --sdk-only`;
  the app keeps its `@processcraft/ui`). The store writes `2026-10-23T14:05:09.123Z` whatever the
  server's time zone, and rows written before with the server's local offset are rewritten once
  at start. `PyJWT` joins `deploy/requirements.lock` (the SDK needs it). Ruff's `DTZ` rules are on.
  The catalog's and saved exports' `created`/`updated` are rewritten too (`Store.TIMES`); the PI
  diagnosis says its time in UTC.

### Added

- "Open in a notebook" on the Export page and on a point's page: PlantCraft's
  Notebooks open a notebook that already loads those tags over that period (Python in the
  browser, offline). Shown only when PlantCraft's API v1 `/me` gives a `notebooks_url`.

### Changed

- Removing a point retires it instead of deleting its history: it is no
  longer collected, listed or read by the apps, its archive stays for 30 days
  (`catalog.store.RETIRED_DAYS`) and an admin restores it as it was from Points › Removed points
  (`GET /api/points/retired`, `POST /api/points/restore`). After 30 days the collector's hourly
  housekeeping deletes it for good; an admin may do it earlier by typing the count
  (`POST /api/points/purge`). PlantCraft removing a signal (`DELETE /api/v1/data/signals/{id}`)
  retires it too. Audited as `points.retire`, `points.restore`, `points.purge`.

### Fixed

- The collector no longer loses the values it read when the archive's database fails (a restart,
  an update, a full disk): a failed flush keeps them in memory and the next flush writes them (up
  to a day per point at one value a second, the newest kept), collection goes on meanwhile, and
  values still waiting when the collector stops are written to `<data>/collector/held-values.jsonl`
  and archived by the next collector on its first flush.

### Changed

- A point's trend is the suite's shared time chart (`@processcraft/ui` 0.24.0, `TimeChart` and
  `PeriodPicker` from `@processcraft/ui/plot`): the same chart, period picker and quality bands as
  every app, following the theme (the PNG too). Historian keeps no Plotly wrapper of its own.
- Sources (owner review, 2026-10-23): the derived source of an app merged into Link (Twin,
  CPMCraft, DataCraft) shows "App retired" and an admin may remove it with its points and their
  history (`DELETE /api/sources/{id}?with_points=true`, audited with the count). Twin's source
  (`app-twincraft`) is removed on start: Link writes its own series since 0.3.0. A CSV file shows
  "Read in place" instead of waiting for a connection it never has. The Export filter is "Type".

### Added

- The gateway (G10): MQTT brokers, Modbus TCP devices and SQL databases as sources, read by
  Telegraf (the `histcraft-gateway` service) and pushed to the collector in InfluxDB line
  protocol (`POST /api/v2/write` on `HISTCRAFT_INGEST_PORT`, token in `<data>/gateway/token`).
  The collector writes the gateway's whole configuration from the sources (only
  `inputs.mqtt_consumer`, `inputs.modbus`, `inputs.sql` and one output to itself), so nothing
  in the gateway can write to a plant system; an SQL source runs one checked SELECT. Values go
  through the same compression and archive as OPC UA's; Browse lists the series received and
  a silent source is a gap after 60 s. The Sources page offers six plant types.

- Calculated points and totalizers (G11): **Add calculated point** on Points. A formula reads
  other archived points as `[source:tag]` with arithmetic, comparisons, `and`/`or`/`not` and
  abs, min, max, sqrt, exp, log, log10, round, clip and if; `total(..., per="h", reset="day")`
  integrates a rate and restarts each hour, day or month (UTC). Formulas are checked against
  an allow list (never run as code), read only points the collector archives, and never loop.
  The collector evaluates them on their scan (source `calc`) and archives them like any point:
  any input bad is a gap, any input uncertain makes the result uncertain. A formula can change
  on the point's page or by CSV.

- The point list as CSV (G11): **Export CSV** on Points (`GET /api/points/export`, a source's
  with `source_id`) and **Import CSV** for editors (`POST /api/points/import`, a preview of what
  is added, changed and unchanged with every bad line, then `apply=true`, audited). An empty
  setting cell inherits, so a file exported and imported again changes nothing.

- Secure OPC UA (G2): Sign or SignAndEncrypt with Basic256Sha256, Aes128_Sha256_RsaOaep or
  Aes256_Sha256_RsaPss, for live reads, browsing, tests, Historical Access and backfill.
  Historian makes its client certificate once (self-signed, ten years, `<data>/pki/`, key 0600;
  `GET /api/opcua/certificate` to download it). The server's certificate is trusted by its
  SHA-256 thumbprint: the first Test shows it, an admin trusts it
  (`POST /api/sources/{id}/trust`, audited), and a server presenting another one is refused.

- Quality kept with the values (G5). An OPC UA value whose status is Uncertain is archived with its
  quality instead of becoming a gap; a Bad one stays a gap and is marked bad. Changes of quality
  are kept in `qualities` (one row per change; the value where it changed is always archived),
  pruned with retention and removed with their point. The point's trend shades uncertain,
  substituted and bad periods (`quality` in `GET /api/points/{signal}/series`); the status shows
  "Uncertain value". Sources that report no quality (CSV, apps' series) say so on the point page:
  their values count as good (`quality_reported` on sources and points).

- `processcraft-sdk` 0.15.0 and `@processcraft/ui` 0.20.0.
- The first page is the Overview every app of the suite shares (`AppOverview`, `@processcraft/ui`
  0.20.0): widgets each person chooses and orders, kept per person in ProcessCraft. Its widgets: the
  collector, points, archive, compression and sources; the notice for a stopped collector stays
  above them.
- The PostgreSQL archive is partitioned by month: `chunks` by its first time, `rollups` by
  hour, one table per UTC month (`chunks_y2026m10`), made as writes need them, plus two edge
  tables before 1900 and from 2200. Retention drops a past month whose every value is past its
  point's retention as one table, instead of deleting its rows (no dead rows left for VACUUM, the
  disk given back); the rest is still deleted chunk by chunk. Reads are unchanged.
- An archive made by 0.3.0 or earlier is migrated on the first start, in one transaction (its
  rows are copied into the monthly tables; the server and the collector wait meanwhile, about
  15 s per million chunks on a laptop-class machine). SQLite archives are not partitioned. The
  suite's incremental backups (`pg_basebackup`) and their restore drill need no change.

## [0.3.0] - 2026-10-23

### Security

- A source's stored password only goes to the server and user it was typed for: changing an
  OPC UA or PI Web API source's address or user, or testing such settings, asks for the password
  again (422), so an admin can never send it to a server of their own (security audit 2026-10-23).

### Changed

- `processcraft-sdk` 0.14.0: The Historian reads its settings with the SDK's `AppSettings` and connects to
  ProcessCraft with `PlatformRuntime`, the same code as every app (no setting or behaviour changes).

### Added

- API v1 reads served to the apps directly (`/hist/api/v1/signals`, `/series`, `/value`,
  `/reads`), with the same shapes and the access rule of ProcessCraft's API v1: a verified,
  not revoked token at viewer level or above (`docs/data-layer.md`). Apps on
  `processcraft-sdk` 0.13.0 read here when `PROCESSCRAFT_HISTORIAN_URL` is set.
- The source `system` ("System"): the suite's own health (each service up, its latency, CPU,
  memory, restarts, errors and warnings; the free disk; the backups), written by ProcessCraft
  every minute through `POST /api/v1/data/system` and kept 90 days. Read-only on the Sources and
  Points pages; its id is reserved.

### Security

- A CSV source reads only files in `HISTCRAFT_CSV_DIRS` (default `/csv`, the installation's
  `data/histcraft-csv`) and the CSVs sent from the Sources page (`<data dir>/files`), once links
  are followed. Before, an administrator could point one at any file of the container, such as
  `/proc/self/environ`, and browse its contents as column names (security audit 2026-10-22).

### Changed

- On `processcraft-sdk` 0.13.0, the same version as every other app.
- A batch of signals reads the archive in a few queries instead of four per signal: 500 signals
  over the last hour in 0.12 s instead of 1.6 s, and on a 60 s grid over 6 h in 0.24 s instead
  of 1.4 s (PostgreSQL 16, 4,000 points, measured on the request itself).
- The suite runs the collector as its own service, `histcraft-collector` (`histcraft collect`),
  and `histcraft serve` with `HISTCRAFT_COLLECTOR=off`: restarting or updating the server, or a
  heavy query, no longer stops the recording.
- One collector per archive: a collector holds a lease while it writes (PostgreSQL advisory lock,
  or a `flock` beside the SQLite archive); a second one waits as a standby and takes over when
  the first stops. A collector that loses its lease stops (exit 1, its container restarts).
  `histcraft housekeeping` is refused while a collector runs.

- `GET /api/v1/data/signals` answers each signal's `source_kind` (`opcua`, `pi_web_api`, `csv`,
  `derived`), so the apps can judge a laboratory signal from a file by its own rules.
- `@processcraft/ui` 0.18.0: the browser tab reads page first, then the app, then the brand
  ("Points · Historian · PlantCraft"), and its icon is always the platform's mark.
- On the suite's current shared packages: `processcraft-sdk` 0.12.1 and `@processcraft/ui`
  0.17.0, the same versions as every other app.
- Logs are JSON lines (`processcraft_sdk.server.logs`), to standard error and, for the server, to
  a rotating file under the data folder's `logs/`, with a request id per request.
- `[backup]` in `app.toml` names this app's SQLite files, so the suite's backup copies them
  online and checks them.

## [0.2.0] - 2026-10-21

### Added

- First release in the suite's offline bundle.
