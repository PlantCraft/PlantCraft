# Devlog

Terse, newest last.

## 2026-10-19: extraction from the ProcessCraft monolith

- New repository layout: `src/cpmcraft`, `tests`, `frontend` (base `/cpm/`), `vendor` (the
  processcraft-sdk 0.1.0 wheel, sha256 `8f09ddd2…2579`), `deploy/requirements.lock`.
- Ported: the CPM methods and the data quality methods (as the gate), method registry, labels,
  flow diagrams and system protocols, engine (jobs, schedules, compute pool, latest), loop
  analysis and monitoring round, weekly PDF; new per-loop PDF.
- Plant data only through API v1 (`data/plant.py`): recorded values first, grid means when a
  window holds more than 200k points, mode numbers as text, the round ends at the newest sample
  ProcessCraft reports. Loops from assets of kind `loop` plus loops defined here (SPEC.md).
- Sign-in by ProcessCraft tokens (`TokenVerifier`, app `cpmcraft`); user requests forward the
  person's token; background work uses the app key (`PROCESSCRAFT_APP_KEY(_FILE)`); every change
  audited in ProcessCraft.
- Frontend: loops list, loop page (trends, findings, settings, PDF), protocol editor, runs and
  schedules, methods; ProcessCraft brand, `AppLockup app="cpmcraft"`, link back to ProcessCraft.
- Tests: 341 pytest (known-fault loops against `FakeProcessCraft`, hostile inputs over 17 methods
  × 14 frames and 34 API operations, architecture, offline, floors) and 12 vitest.
- Bench (`python -m cpmcraft.bench --loops 2000 --processes 4 --latency-ms 2`, fake served by 4
  uvicorn processes on the same 4-core box): cold 146.9 s (817 loops/min), warm 120.6 s.
- Smoke test against the real ProcessCraft (generic demo): FIC-101 synced and diagnosed through
  the API, PDF rendered, audit row `cpmcraft.loop.updated` with `app_id = cpmcraft`.
- Open: G3 oracle, G16 text signals, parked items in `docs/gaps.md`.

## 2026-10-19: processcraft-sdk 0.2.0, batch reads, text modes, bench

- `vendor/` now holds processcraft-sdk 0.2.0 (sha256 `cd2fcb58…3214`, reproducible build); pins
  in `pyproject.toml`, `Makefile`, `Dockerfile` and `vendor/README.md`. `deploy/requirements.lock`
  is unchanged: the SDK's dependencies did not change and the lock leaves the SDK out.
- `data/plant.py` reads with `series_many_pandas` (`POST /api/v1/series`): one request per batch
  of signals, split over up to 4 parallel requests of at least 40 signals; 422 signals (too many
  recorded values) asked again as one mean per step; 404/502 per signal listed in
  `failed_tags`; the batch raises only when every signal failed with 5xx. Text signals
  (`kind: text`, "AUTO"/"MAN") keep their labels, so `manual_mode_fraction` sees them (G16).
- `ensure_initial_jobs` writes the portfolio's baseline jobs in one transaction
  (`JobStore.record_completed_jobs`); 2000 jobs took about 14 s as 6000 small transactions.
- Tests run on the SDK's `httpx.MockTransport` fake (no Starlette TestClient, no event loop per
  request). The bench stays on real HTTP (the fake under 4 uvicorn processes): it is the honest
  number, since series travel as JSON through sockets to a separate server as they do from
  ProcessCraft, and here it is also faster than `--transport mock` (64 s / 59 s), where the fake's
  JSON work shares the reader's interpreter lock. `--transport mock` stays for timing CPMCraft
  alone; the bench now counts and delays real HTTP requests (an httpx request hook).
- Bench (`python -m cpmcraft.bench --loops 2000 --processes 4 --latency-ms 2`, 4-core box):
  cold 61.2 s and 52.7 s, warm 46.3 s and 48.4 s (two runs), 125 requests per round (was
  146.9 s / 120.6 s, about 6000 requests). The monolith's loop round on the same box today:
  47.6 s cold / 43.8 s warm (`python -m processcraft.demo.bench --round ...`), so CPMCraft is
  within 20% warm and about 11-29% over cold. The 27 s target is not reachable on this box: the
  analysis alone is about 60 ms per loop, 120 CPU-seconds for 2000 loops on 4 cores (30 s),
  before any JSON. What is left of the data path is JSON (13.5 MB per 150 signals of 6 h at
  10 s: about 0.25 s to write and 0.15 s to read).
- `.gitignore` matched `data/` and `oracles/` anywhere, so `src/cpmcraft/data` (the API v1
  adapter) and `tests/oracles/README.md` were never committed and a fresh clone did not import;
  both patterns are anchored at the root now and the files are tracked.
- Open: G3 oracle; a perf floor is not in `tests/floors.toml` (machine-dependent).

## 2026-10-19: oracles (MVP step 10)

- Simulator oracle (`tests/oracles/`): PlantCraft's loop dynamics copied with attribution; 10
  loops with a known fault (healthy x2, external-disturbance and tuning oscillation, stuck
  valve, saturation, sensor noise, frozen sensor, manual mode, setpoint changes), each with the
  methods that must and must not flag it, run as one monitoring round through FakeProcessCraft.
  7 of 10 pass; floor `simulator_cases = 7`. Failures are strict xfails: G27 (one SP step reads
  as oscillation), G28 (stiction screen on a saturated OP and on a tuning oscillation).
- The simulator's stiction model never cycles (G30); the stiction case expects a stuck valve.
- ISDB: `fetch_isdb.py` (URL from the book page, sha256 TODO: `sites.ualberta.ca` blocked by the
  egress policy here) and `test_isdb_oracle.py` (skips without data or transcribed labels; its
  scoring path is tested on a synthetic layout). Open: pin the archive, transcribe labels (G3).

## 2026-10-19: e2e journeys

- `tests/e2e` (Playwright, sync API, no pytest plugin): FakeProcessCraft served by forked uvicorn,
  CPMCraft by a uvicorn thread with `frontend/dist`. 6 journeys green: no token -> `/login?next=`,
  loops list, loop page (Plotly traces, findings, status and health), run now, protocol editor
  (React Flow nodes), loop PDF download. Skip without Playwright/Chromium unless
  `CPMCRAFT_E2E_REQUIRED=1` (`make e2e`, CI job `e2e`).
- Screenshot review: the loop page's status pill stretched across its card; fixed in CSS.

## 2026-10-19: oracle false alarms (G27 closed, G28 downgraded)

- `oscillation_autocorrelation`: flagged only when the ACF peak is >= 0.3 *and* the period is
  regular, r = mean(Tp)/(3 std Tp) > 1 over up to ten periods between alternate ACF zero
  crossings (Thornhill, Huang and Zhang 2003). Healthy SP step: peak 0.37, r 0.50, ok. External
  and tuning oscillations r 100 and 9.8, still bad. New metrics `regularity`,
  `zero_crossing_period_seconds`, `oscillating`; new parameter `min_regularity`.
- `stiction_screening`: OP moves touching a sample at a limit (same rule as
  `op_saturation_fraction`) are left out; a jump counts only right after a stuck move (stick
  then slip, Choudhury, Thornhill and Shah 2005). Tuning oscillation: jumps 94 %, slips 0.6 %,
  ok; pinned OP: nothing screened, `not_applicable`, and `describe` says why. The oracle's
  `clear` list now means "must not flag" (ok, not_applicable or insufficient_data); `flags`
  stays strict. `describe`
  now warns from score 25, as the status does (it said "no clear signature" on warnings).
- Simulator oracle 7 -> 10 of 10, floor raised. No PV-OP shape test yet (G28, see the gap for
  why Horch's test was not added). Bench (2000 loops, 4 processes, 2 ms): baseline 52.4 s
  cold / 54.6 s warm; after 47.1-57.1 s cold / 42.1-59.5 s warm over two runs (noisy shared box).

## 2026-10-19: loops through the asset catalog, loop-type defaults, method help

- Sync (`loops/sync.py`): a loop is an asset whose `type_path` contains `loop` (fallback `kind`);
  `loop_type`, `criticality`, `action`, `controller`, `relations` and `type_path` go into the
  loop's `asset_record`; required roles from `GET /api/v1/asset-types` along the type path,
  PV and OP when not served (404 today). Hostile payloads tested (missing fields, wrong types,
  parent cycles, unknown loop types, junk type lists): never a crash.
- Incomplete records: a loop asset without a required role is listed (status `incomplete`,
  roles missing, "bind them on the asset's page in ProcessCraft"), never analysed, runs 409.
- Defaults per loop type (`catalog/loop_types.py`, table in `docs/loop-types.md`): flow ->
  `flow_control`, level -> `surge_drum`, pressure/temperature/composition -> three new system
  protocols, plus time-scale parameters under the protocol's. Criticality from the record.
  Protocol and criticality changed here go into `set_here` and win over the record (rows synced
  before keep non-default choices); PATCH `reset` gives them back; the loop page says "from the
  asset record", "set here" or "CPMCraft default".
- Method help: one Markdown page per method (`methods/help/`), served by `/api/help/*`, Help
  section in the interface, a link from every finding; a test checks sections, parameters and
  defaults against the methods.
- Numbers: 421 pytest (10 skipped: e2e without the env, ISDB), 14 vitest, 9 e2e journeys;
  simulator oracle 10/10. Bench (2000 loops, 4 processes, 2 ms): 58.6 s cold / 52.3 s warm,
  126 requests (one more: asset types).
- Found: `sampling_quality` measures the grid (G31, high: caps health at 40 on the default
  grid with the "all" protocol). Open: G31, G32 (re-vendor at sdk 0.3.0), G33.

## 2026-10-19: sampling quality judges the recorded data (G31)

- Root cause: the method assumes acquisition timestamps (its definition; Bauer et al. 2016 name
  coarse or compressed historian data as the obstacle), yet it read the regular frame, so its
  median was always the grid step (60 s against 30 s recommended: score 60, component 40 on every
  loop) and grid interpolation hid holes. It now reads the PV's recorded samples
  (`LoopDataset.raw`, already fetched without a `step`; no extra requests) and reports
  `largest_gap_seconds` and `timestamp_source`. Regression tests: `tests/test_sampling_quality.py`
  (5, all failed before).
- 50-loop simulator scenario (ProcessCraft's `LOOP_DEFINITIONS`, 24 h at 30 s, "all" protocol,
  60 s grid), health before -> after: healthy 3.2-19.0 -> 8.1-47.5; stiction 26.6-33.9 ->
  66.6-84.8; sensor drift 4.5-13.3 -> 11.2-33.2; disturbance, interaction, manual, noise,
  oscillation, saturation and setpoint activity 0-0.3 -> 0-0.7. Sampling component 40 -> 100 on
  every loop (recorded median 30 s).
- Healthy loops still do not score high under "all": `disturbance_attenuation` (a surge-level
  method) scores flow, pressure and temperature loops 11-39. Opened G34.
- Simulator oracle 10/10. Bench (2000 loops, 4 processes, 2 ms, box loaded by other work):
  before 78.3 s cold / 73.6 s warm, after 55.4 s / 49.9 s in back-to-back runs (noise, not a
  speed-up); 125 requests.

## 2026-10-19: the app standard (CPMCraft as the reference app)

- Asset types read as ProcessCraft PR #3 serves them: a tree (`children`) with inherited roles
  resolved, roles `{key, name, unit, required}`; walked without recursion; `CatalogFake` aligned.
- `app.toml` (section 4) is the one source of the metadata; `make image` passes its values as
  build args, the image carries `org.processcraft.app.{id,prefix,port}` and `app.toml`, and
  `tests/test_app_manifest.py` fails when pyproject, the Makefile, the Vite base or the
  Dockerfile disagree. `make package` is a stub until ProcessCraft's `deploy/package.sh`.
- `/api/meta` (manifest plus revision, auth), `/api/help` (help index), `assets/<id>` deep link
  (`/api/assets/<id>`: the loop, or "CPMCraft does not cover this asset"). Built files moved to
  `<prefix>static/`.
- Suite contract (`data/suite.py`, to remove at sdk 0.3.0; `loops/suite.py`): `loop_health`
  results per asset loop after each round (expire after two round periods), finding events
  opened/closed (kept in `suite_findings`), rounds as runs (manual, schedule, api), the
  schedule list after every change; DataCraft's `signal_quality` read before judging a loop
  (unusable or alarm stops it with DataCraft's summary; fresh results on every signal replace
  the built-in gate; stale or missing ones fall back to it). Every endpoint optional: a 404 is
  logged once and retried after an hour. Tested against `tests/suite_fake.py` (contract-shaped,
  422 on anything off-contract), including `<source>:<tag>` signal ids (D2) end to end.
- UI: method results read OK / Attention / Alarm, the loop page shows the published status.
- Numbers: 463 pytest (12 skipped: e2e without the env, ISDB), 16 vitest, 11 e2e journeys;
  simulator oracle 10/10. Bench (2000 loops, 4 processes, 2 ms; the bench's fake does not serve
  the suite endpoints, so it measures the 404 path): 63.2 s cold / 56.2 s warm, 131 / 125
  requests. Image built and smoke-tested read-only (labels, `/cpm/static/`, deep-link sign-in
  redirect, `/api/meta` 401 without a token).
- Open: G35 (suite contract ahead of ProcessCraft and sdk 0.3.0).

## 2026-10-19: G34, health of the 50-loop scenario

- `disturbance_attenuation` and `operating_band_fraction` return "not applicable" (out of the
  score) unless the asset record's `loop_type` is `level` or the protocol sets
  `assume_surge_level` (`surge_drum` does). The loop type reaches the methods as dataset
  metadata (`methods/cpm/_surge_level.py`).
- `error_metrics_basic`: default tolerance 4 % and band 1 % of the PV span (`pv_span`), else of
  the median |SP|; an absolute `error_tolerance`/`acceptable_band` wins; a zero setpoint falls
  back to the old 1.0/0.5. Basis: Bauer et al. 2016 rank a loop population by KPIs, which needs
  errors in a common scale. New metrics `scale`, `tolerance_basis`, `mae_percent_of_scale`.
- Loop type `level` starts on a new Level loop protocol (`level_control`, tight: scored on the
  error); `surge_drum` is chosen on the loop page for averaging levels (G38). The demo's levels
  are tight PI loops: on `surge_drum` they scored 52-56 and their faults overlapped (25-83).
- ProcessCraft patch `0001-scenario-loops-loop-type.patch`
  (against a373cff, applies on main): the simulator catalog gives each loop `metadata.loop_type`
  from its ISA letter, and `sync_scenario_loops` writes loop_type, criticality, action and
  controller from a scenario loop's metadata into empty record fields. PlantCraft's
  `loop_catalog()` has no loop type either.
- 50-loop scenario (24 h at 30 s, default analysis), health min-max per class, before -> after.
  Untyped ("all"): healthy 8.1-47.5 -> 79.9-91.2; stiction 66.6-84.8 -> 82.3-93.5; sensor
  drift 11.2-33.2 -> 88.5-93.4; noise 0-0.7 -> 39.9-60.5; manual 0 -> 42.8-55.6; disturbance 0
  -> 0-55.2; oscillation 0 -> 19.3-33.8; interaction 0 -> 8.8-17.1; saturation and setpoint
  activity 0 -> 0. Typed (as with the patch): identical after; before, healthy 52.2-78.9.
  Stiction and sensor drift stay with the healthy loops (G37).
- 468 pytest (12 skipped), simulator oracle 10/10, floors unchanged.

## 2026-10-20: processcraft-sdk 0.5.0, the suite contract through the SDK, signal ids (D2)

- `vendor/`: processcraft-sdk 0.5.0, built reproducibly from ProcessCraft `acad665`
  (`SOURCE_DATE_EPOCH=1792368000 python -m build --wheel --no-isolation`, twice, same bytes),
  sha256 `7dad6847…e62b`. Lock unchanged (same dependencies).
- G35 closed: `data/suite.py` calls the SDK client (`put_results`, `results`, `post_event`,
  `put_runs`, `put_schedules`), references come from `processcraft_sdk.refs`; still optional
  (a route's 404 is logged once and retried after an hour; a 404 naming an item is not a
  missing route). `tests/suite_fake.py` removed: tests read the SDK fake's `fake.links` and
  publish DataCraft's results with its own app key.
- G32 closed: `client.asset_types()`; the test plant uses the SDK fake's type catalog (starter
  types plus a `cascade_loop`), whose `children` are type ids; `CatalogFake` removed;
  `OlderProcessCraft` stands for a server without the catalog and the suite routes.
- D2: signal ids are `<source id>:<tag>` and opaque (`fake:FIC-101.PV` in tests). A loop
  defined here stores the id ProcessCraft answers for what was typed; loops saved with bare
  tags are looked up once per loop (`workspace_loops.signals_checked_at`, guarded
  `ALTER TABLE`) and renamed with a `signal_ids_renamed` configuration event; an unknown tag
  is kept, a failed lookup retried. Loops from assets follow the role maps at every sync.
- Found by the bench against the SDK fake (which now serves the suite): a run with more than
  500 subjects is a 422 (now capped at 500), and a first round posts one event per finding.
  Events now go as a lone probe then 16 at a time. Bench (2000 loops, 4 processes, 2 ms):
  sequential 565 s cold; 8 threads 127.4 s; 16 threads 96.7 s cold / 57.3 s warm, 10,471 /
  172 requests (10,298 events). Warm is unchanged (56.2 s before); the cold round's extra
  time is publishing that the 404 path skipped before (G39: no batch route for events).
- `make ci` runs `processcraft-app check` (needed `docs/help/`, a link to the method help
  pages). `[requires] asset_types = ["loop"]` was already the starter Control loop id; a
  test now ties it to the SDK's starter types.
- Numbers: 482 pytest (12 skipped: e2e without the env, ISDB), 16 vitest, 11 e2e journeys;
  simulator oracle 10/10; floors unchanged.
- Open: G39 (batch events), G40 (`make package` against `deploy/package.sh`), G41 (subjects
  read comma-separated).

## 2026-10-20: processcraft-sdk 0.6.0, events as lists, make package, one version

- `vendor/`: processcraft-sdk 0.6.0, the wheel of ProcessCraft's `make sdk-wheel` at `cb2dbb9`
  (byte for byte: sha256 `f5abfa7d801533f7775efe8b0fb3f97b0c7e45179a9b9a87dbdf77f4b76e0ddf`, as
  expected). Lock unchanged.
- G39 closed: `SuiteClient.post_events` sends a round's finding events in lists of up to 1,000
  (`client.post_events`) and says per event whether ProcessCraft took it; an event refused in
  the list (unknown subject) stays out, the rest are recorded; a failed request stops the
  round's events (sent again next round); a missing route is still logged once and retried an
  hour later; a list refused whole (422: a ProcessCraft before lists, or one malformed event)
  is sent one event at a time. The 16-thread single-POST path is gone.
- G41 closed: SDK 0.6.0 reads results with one `subject` parameter per subject; the opaque-ids
  test has a comma in its tags.
- Bench (`python -m cpmcraft.bench --loops 2000 --processes 4 --latency-ms 2`, SDK 0.6.0 fake
  over HTTP; now reports `event_requests` and `events` apart), three runs:

  | Run | Cold s | Warm s | Cold requests | Event requests / events |
  |---|---:|---:|---:|---|
  | 1 | 61.65 | 49.83 | 184 | 11 / about 10,300 |
  | 2 | 69.78 | 47.67 | 184 | 11 / 10,307 |
  | 3 | 64.18 | 45.37 | 184 | 11 / 10,303 |

  Was 96.7 s / 57.3 s with one POST per event, 63.2 s / 56.2 s before publishing (404 path):
  cold is within 20% of 63.2 s (run 2 overlapped other work on the box).
- G40: `make package` calls ProcessCraft's `deploy/package.sh` (PROCESSCRAFT_DIR, PUBLISHER_KEY,
  SBOM); without a key it makes a development pair in `build/dev-publisher/` (gitignored) and
  verifies the package against it; `deploy/sbom.py` writes an SPDX SBOM from inside the image.
  Run here: `dist/cpmcraft-0.1.0.pcapp` (108 MB) built and verified. G40 now holds only the
  500-subject run limit.
- One version: `__version__` is the installed package's (pyproject, tied to app.toml), the
  Dockerfile keeps no version and refuses a `VERSION` that is not app.toml's, `make image
  VERSION=...` is refused, CI's docker job checks tag, label and `/cpm/healthz` agree (checked
  locally: the image answers `{"status":"ok","version":"0.1.0"}`).
- Numbers: 485 pytest (2 skipped), 16 vitest, 11 e2e journeys, simulator oracle 10/10; floors
  unchanged.

## 2026-10-20: processcraft-sdk 0.7.0, loop health as derived series

- `vendor/`: processcraft-sdk 0.7.0, the wheel of ProcessCraft's `make sdk-wheel` at `026eab8`
  (sha256 `9433a75b91630f98c84fa7687b77110a7b0cf1316d0d8fcd364f25ce8303e16d`, as expected);
  pinned in pyproject, app.toml, Makefile, CI and the Dockerfile. Lock unchanged.
- After every round each asset loop gets one point at the round time in two derived series of
  CPMCraft's source (`client.put_series`, all loops in one list, the SDK splits it into requests
  of 500): `app-cpmcraft:<loop id>.health` (name `<tag> health`, unit `/100`, number) and
  `app-cpmcraft:<loop id>.status` (text: critical, high, medium, normal, or no_data and the
  like), both with subject `asset:<loop id>` and result `loop_health`. A loop without health
  writes a null point. Same loops as the results (user loops and incomplete records publish
  nothing). Written after results and events; a 404 for the route is logged once and retried an
  hour later, any other failure is logged and the round goes on; an item ProcessCraft would
  refuse is left out before the request.
- `app.toml`: the SDK's manifest has no field for derived series (`[publishes]` takes results
  and events, `[permissions]` write has no `series`), so they are described in a comment by the
  `loop_health` result (G42).
- Found: the SDK's `FakeProcessCraft` takes a recorded plant's "now" from every series it holds,
  derived ones included, so the health point at wall-clock time emptied the next round's window
  in tests; ProcessCraft takes it from the CSV file only. `tests/plant.py` `PlantFake` leaves
  derived series out until the SDK's fake does (G42).
- Bench (`python -m cpmcraft.bench --loops 2000 --processes 4 --latency-ms 2`, SDK 0.7.0 fake
  over HTTP, now with `series_requests`), box shared with other work (load 5 on 4 cores):

  | Run | Cold s | Warm s | Cold requests | Series requests | Events |
  |---|---:|---:|---:|---:|---:|
  | 1 | 63.43 | 55.46 | 192 | 8 | 10,292 |
  | 2 | 71.89 | 46.27 | 192 | 8 | 10,298 |
  | 3 | 63.40 | 53.64 | 192 | 8 | 10,301 |

  Was 61.7-69.8 s / 45.4-49.8 s: the series writes cost about 3.2 s per round (8 requests of
  500 items; 0.12 s of it building and checking the items, the rest the fake), within 20 %.
- Numbers: 490 pytest (2 skipped), 16 vitest, 11 e2e journeys, simulator oracle 10/10; floors
  unchanged.

## 2026-10-20: LinkCraft, CPMCraft and DataCraft as one app on the suite frame

- Rename (owner decision D9): CPMCraft is LinkCraft, id `linkcraft`, prefix `/link/`, port 8140,
  uid 10012, env prefix `LINKCRAFT_`, package and CLI `linkcraft`. The `cpm` method group and the
  domain words keep their names.
- `vendor/`: processcraft-sdk 0.8.1 (sha256 `229167fa…a897a3`; the suite table names `linkcraft`
  and `dashcraft`) and `@processcraft/ui` 0.2.0 (sha256 `d84500e3…2366a4`), pinned in pyproject,
  app.toml (`sdk = "0.8.1"`), the Makefile, CI, the Dockerfile (which checks the UI tarball's
  hash before `npm ci`) and `frontend/package.json`. `processcraft-app check` passes the new
  frame check.
- DataCraft merged: its 8 checks are the Data quality methods (`sq_*`; DataCraft's `dq_*` ids
  are mapped on migration), registered apart from the loop gate (`catalog/signal_checks.py`) so
  the gate's `dq_availability` keeps its id; its round is the system protocol Signal quality
  (`signals/`, schedule `round-signal_quality`, runs `signal-quality-<n>`), its pages the Signals
  pages, its settings the protocol page. Verdicts are published as `linkcraft.signal_quality` on
  each signal and asset and as `app-linkcraft:<signal>.quality`. The loops read the in-app
  verdicts (`loops/suite.py`), no longer `datacraft.signal_quality`.
- Found by the browser journeys: the frozen check called a saturated or manually held OP bad
  data, which hid PIC-103's saturation and FIC-101's manual stretches behind "data not usable".
  The controller output joined the setpoint and mode as constant by design (`CONSTANT_ROLES`):
  the loop methods judge a still OP. With that, the loops' statuses are the same as with the
  gate alone (TIC-104, a stuck PV, stays "data not usable").
- Migration: `linkcraft migrate --from-cpmcraft ... --from-datacraft ...` or
  `LINKCRAFT_MIGRATE_FROM_*` at start; each source copied once (`migrations`), the old databases
  only read (attached read-only).
- Interface: SuiteShell with Overview, Signals, Loops, Runs, Protocols, Methods and Help; Help is
  the HelpBrowser over `/api/help/docs` (guides in `methods/help/guides/`, a page per method
  with this site's defaults, the loop-type table written from the defaults); the Overview shows
  signals and loops now and per day over the week, and "Open dashboard" goes to `/dash/`. The
  app's own top bar, tokens, fonts and marks are gone.
- Numbers: 928 pytest outside the browser, 18 e2e journeys (light, dark and phone screenshots),
  18 vitest; simulator oracle 10/10, signal synthetic oracle 90 cases.


## 2026-10-20: @processcraft/ui 0.2.2

- Re-vendored `@processcraft/ui` 0.2.2 (ProcessCraft `11ce318`, sha256 `1a3d81f1...b3ab`): every
  relative import in its `dist` carries `.js`, and the phone drawer casts its shadow only when open.
  vitest no longer inlines the package (G44 closed).

## 2026-10-20: module names (D10), processcraft-sdk 0.8.2, @processcraft/ui 0.3.1

- Owner decision D10: only ProcessCraft keeps the Craft brand. This app is **ProcessCraft Link**
  in documents, the package, `app.toml` (`name`, which `processcraft-app check` compares with the
  SDK's suite table) and the README, and just **Link** inside the suite: page `<title>`, help
  guides, interface and API messages people read. PDF reports and the OpenAPI title say
  ProcessCraft Link. Ids, the repository, `linkcraft serve`, `LINKCRAFT_*`, the image and `/link/`
  stay. Other modules follow the same rule (Dashboards, Plant); CPMCraft and DataCraft stay where
  they explain the history (migration, D9).
- Re-vendored processcraft-sdk 0.8.2 (sha256 `e115d981...f959`) and `@processcraft/ui` 0.3.1
  (sha256 `04540bed...445da`), both from ProcessCraft `8dfd352`: the sidebar lockup shows "Link"
  over "ProcessCraft", the Apps list shows short names, and a Messages button above the user menu
  reads ProcessCraft's `GET /api/v1/inbox` (FakeProcessCraft has none: the 404 leaves the button
  without a badge). Test fakes list the apps by their full names, as ProcessCraft now does.

## 2026-10-20: install test fixes (user menu role, image SBOM)

- The user menu showed an admin as "editor" (the token's access to this app is only `editor`
  or `viewer`). `/api/me` gained `role`: `admin` for a ProcessCraft admin, else the access; the
  frame shows it. Test: `test_me_role_shows_an_admin_as_admin`.
- The image had no `/app/sbom.json`, unlike Dashboards and Historian. `deploy/sbom.py --here`
  runs inside the image at build (`SBOM_CREATED` = the build time) and writes the SPDX 2.3 SBOM
  there; `make package` signs that file (`docker run ... cat /app/sbom.json`). CI's docker job
  checks it names linkcraft, fastapi and processcraft-sdk; `tests/test_app_manifest.py` checks
  the Dockerfile, Makefile and CI wiring and runs `--here` locally. Built locally: 116 packages.
  930 pytest, 18 vitest.

## 2026-10-20: processcraft-sdk 0.8.3

- processcraft-sdk 0.8.3 vendored (ProcessCraft `7bcf870`, sha256 `e87b2459...6757b`), pins in
  the Makefile, CI, Dockerfile, pyproject and `app.toml`; `@processcraft/ui` stays 0.3.1. 0.8.3
  adds `recorded_on_change(signal_id, kind)`: setpoints, modes and text signals hold on series
  grids, with no limit, until their next sample, a null sample, `end` or now (ProcessCraft
  `docs/api-v1.md`, step-hold); `FakeProcessCraft` shapes grids the same way. No code change here.

## 2026-10-20: protocols built on the canvas (plan step 8)

- The protocol diagram gained result blocks (`catalog/flow.py`, `catalog/flow_eval.py`): Data
  quality checks on any signal or transform, the Signal quality verdict of a role, Worst of,
  Average and Rule combinations, and three outputs: a result on the loop (`out_<name>`), a series
  (`app-linkcraft:<loop>.out_<name>`) and a message (events `linkcraft.protocol.alert|cleared`, the suite alert shape,
  tracked in FindingStore so a run does not repeat it). Wires are typed: signals into
  transforms, checks and methods; results into combinations and outputs.
- Outputs are published by rounds and by scheduled runs (`loops/suite.publish_outputs`); a
  protocol with checks but no scored method gives status `no_score`. Saving a protocol refreshes
  the schedules that run it; the editor schedules it itself (every N minutes, all or chosen loops).
- The Signal quality check helpers moved to `catalog/signal_checks.py` so the catalog layer can
  run them.
- Seen on the demo: FIC-105's stiction screen says Alarm while its loop score stays 100 (G37); the
  recipe "Valve and PV quality" surfaces it through its own result.
- Numbers: 952 pytest, 19 e2e journeys, 19 vitest.

## 2026-10-20: @processcraft/ui 0.3.2, the sidebar reordered

- `@processcraft/ui` 0.3.2 vendored (sha256 `2b9816bc...ef46d60c`), 0.3.1 removed. The fold
  button is at the top of the sidebar, the Apps list sits at the bottom above Help, and
  ProcessCraft is always the first app, so the platform is one click away from every page
  (owner feedback). No code change here.

## 2026-10-21: minimum-variance (Harris) index (G19)

- `methods/cpm/harris.py` (`@method harris_index`): e = PV - SP (or PV minus its mean), AR model
  by least squares (order 20, at least the dead time plus one), impulse response psi;
  eta = sigma_a^2 * sum(psi_0..psi_(b-1))^2 / var(e). The dead time b comes from
  `dead_time_seconds`, else the lag of the largest cross-correlation of OP and PV differences,
  else one sample (`delay_source`: parameter, estimated, assumed). Score 0 at eta >= 0.5, 100 at
  eta <= 0.1, linear between.
- Help page `methods/help/harris_index.md`. Not added to the default protocols: it would move
  every loop's score; engineers add it in the protocol editor.
- Tests `tests/test_harris.py`: AR(1) errors against the closed form
  (1 - phi^2) * sum(phi^(2k), k < b) within 0.02, white noise at minimum variance, a sluggish
  loop scoring 100, the dead time found from OP moves.

## 2026-10-21: likely causes on the loop page and in the PDF (G1, part)

- `report/causes.py`: eight causes, each with the methods that support it (`bad` counts 2,
  `warning` 1), the methods that speak against it, and the first step to take. A cause needs
  one of its main signs (stiction needs the stiction screen, saturation the saturation check);
  causes are ranked by support minus what speaks against them, three at most.
- `GET /api/loops/{id}` returns `likely_causes`; the loop page shows them above the alerts; the
  PDF has a "Likely causes and what to do first" table.
- On the test plant the round's known faults get the right first cause: fic-105 stiction,
  pic-103 saturation, lic-102 tuning or a neighbour, fic-101 none (`tests/test_rounds.py`);
  the e2e journey checks the fic-105 page. Economic impact stays open in G1.

## 2026-10-21 — a time given twice no longer fails a batch of 50 loops

- Suite bench at 2,000 loops (ProcessCraft `ci/bench/suite_bench.py`): 15 signals whose archive
  had overlapping chunks came back with repeated times; `pd.concat` in `PlantData.read_range`
  raised "cannot reindex on an axis with duplicate labels" and the round skipped their whole
  read batch (2 x 50 loops kept their last result). Each series now keeps the last value of a
  repeated time; test `test_a_time_given_twice_does_not_fail_the_batch`.

## 2026-10-21: on the suite's shared server and test kit (processcraft-sdk 0.9.0, @processcraft/ui 0.7.0)

- Server: the web application, access checks and the SQLite store come from
  `processcraft_sdk.server` (`db.py` keeps only `TIMESPEC = "seconds"`); the asset deep link
  moved to `api/routers/assets.py`. Link keeps its own help routes (guides and a page per method
  with this site's defaults) and its engine's `/api/status`. `deploy/sbom.py` is gone: the image
  writes its SBOM with `python -m processcraft_sdk.sbom`.
- Interface: the API client comes from `@processcraft/ui` (`createApiClient`).
- Tests: `tests/test_suite_rules.py` (offline, layers, image, floors, API routes with junk, on
  `processcraft_sdk.apptest`) replaces `test_offline`, `test_architecture` and `test_floors`;
  `test_hostile_inputs.py` keeps the methods; e2e fixtures use `processcraft_sdk.e2e`
  (`app_url`, as in every app); time budget in `pyproject.toml` (`make test-fast`).
- Docs: `AGENTS.md` is the short module file (the suite's rules live once, in ProcessCraft's
  `AGENTS.md`); the README says how the module is built (with Claude Code, in the open); `make
  test-fast` in Develop.

## 2026-10-21: Results and Export (the suite's organisation, owner decisions of 2026-10-21)

- **Results** (`/results`, `GET /api/results`): signals and loops on one list, in the suite's
  statuses (ok, warning, alarm, unknown), filtered by kind and status, each row with its headline
  measure, protocol and limiting finding. A new kind of subject is one more builder in
  `api/routers/results.py`. The old `/signals` and `/loops` lists land here with their filters.
- A result page (loop, signal) reads the same way: the headline ("Health 0.3 · Alarm"), the
  protocol drawn with each block's outcome (`ProtocolView`), the outputs, the input series and
  the output series. Runs stay where they were.
- **Export** (`/export`, `POST /api/export`): a ZIP for a consultant or another ProcessCraft:
  `series.csv` (wide, UTC; as recorded or means), `signals.csv`, `loops.csv`, `results.csv`,
  `plant-map.json` (ProcessCraft's map format) and a manifest with a SHA-256 per file. Loops
  by area or id, signals by source; up to 31 days and 1,000 signals; read with the person's own
  token; audited as `linkcraft.export`. Optional aliases (S001, L001) with the key downloaded
  apart (`/api/export/key`). Everyone with access may export (owner). Next: import as the
  reverse, and an export "connection" that sends on a schedule.
- `@processcraft/ui` 0.8.0 (the routine can be folded or hidden). SDK stays 0.9.0.

## 2026-10-21: the assistant beside runs and protocols; export moves to Historian (owner)

- **Export removed**: data belongs to Historian, which now exports tags, loops, groups of loops
  or a whole unit (the owner, second round). `/export`, `api/routers/export.py` and
  `report/package.py` are gone.
- **Protocol documentation** (protocol editor, Documentation): what it evaluates, inputs,
  outputs, how to read it and instructions for the assistant (a prompt), saved in the
  protocol's `method_config.docs`. A field left empty is generated from the diagram and the
  methods' own descriptions, assumptions and limitations (`linkcraft.knowledge`,
  `POST /api/protocols/docs`).
- **Ask the assistant** on a run (loop runs and Signal quality runs), on a protocol and on the
  Signal quality protocol (`AssistantButton` of `@processcraft/ui` 0.9.0). Before the panel
  opens, `POST /api/assistant/prepare` writes the object's text to ProcessCraft's
  `/api/v1/knowledge` (a run's report: status, window, health, limiting method, each method's
  finding); every protocol is written at start and on save. A ProcessCraft without the route
  answers 404 and Link carries on (logged once, tried again an hour later). SDK stays 0.9.0
  (`client._send` when the client has no `put_knowledge`).
- Comments on runs: later (owner).

## 2026-10-21: filters as dropdowns, one list of protocols, method groups, the Assistant page

- Owner's review (round 3): nothing in Link is "for loops" or "for signals" by construction.
  Results filters kind and status with `MultiSelect` dropdowns (`@processcraft/ui` 0.10.0,
  several values, counts) instead of rows of buttons; Protocols is one list (Signal quality is
  a system protocol among the others); Methods shows the groups in a left column and the
  chosen group's methods beside it (`?group=` in the address).
- Assistant page (`/assistant`, own menu entry): `AssistantPanel inline` about `app:linkcraft`.
  `POST /api/assistant/prepare` with `app:linkcraft` publishes an overview (`overview_item`:
  counts by kind and status, worst 40 results with their limiting method and finding, the
  protocols, the latest runs) so a specialist answers "which loops are worst?" from it and from
  ProcessCraft's results (ProcessCraft resolves `app:` references from this release on).
- Tests: `test_the_assistant_page_reads_everything_link_judged`, `pagesLayout.test.ts`.
- 2026-10-22: AGENTS.md and SPEC.md state the owner's governing principle (blocks with contracts, algorithms as diagrams, routine runs, descriptions for people and AI, results in the suite); docs/blocks-and-algorithms.md records the agreed design.
- 2026-10-22: blocks and algorithms implemented (`src/linkcraft/blocks/`, layer 3): 44 blocks, 5 shipped algorithms, 0.2 protocols converted at start, Signal quality runs its diagram (oracles unchanged), recorded ports to the historian, algorithm/block knowledge; old `catalog/flow.py`, `flow_eval.py`, `protocols.py` removed. Tests: `tests/test_algorithms.py`.
- 2026-10-22: interface on the suite's BlockEditor (`@processcraft/ui` 0.15.0): Algorithms list and page, the editor in its own window (`/editor/<id>`, outside the frame), Blocks list and page, loop page draws its algorithm; ProtocolEditor/flow files removed; `/api/algorithms` gives `aliases` (0.2 ids). Tests: `frontend/src/algorithms.test.ts`, e2e journeys for the algorithm page, editor window, duplicate-test-save-schedule and blocks.
- 2026-10-22: editor review (`@processcraft/ui` 0.15.1): palette libraries fold, one open at a time; a test shows a light on each block with its message on hover; values on wires behind a switch; a selected block shows its inputs and outputs of the last test over time; output port circles aligned with their names. Tests: e2e duplicate-test-save-schedule checks all four.
- 2026-10-22: phase 4 (Twin into Link), engine: `src/linkcraft/models/` (FMU inspection, model store, simulation pool, T² statistics, built-in FMUs, from twincraft) and the `model` block library (`blocks/models.py`: a block per published model, `model.deviation`, `model.operating`; `catalog.register_models`); FMPy in the lock with deploy/overrides.txt; FMUs copied to `/app/fmus`. Tests: `tests/test_model_blocks.py`, `test_model_stats.py`, `test_model_simulate.py`.
- 2026-10-22: phase 4, assets as subjects: `src/linkcraft/assets/` (layer 4: `run.py` reads what the signal blocks name and runs the diagram with the blocks' memory, `store.py` keeps each algorithm and asset's latest run, memory and last written points, `service.py` runs them on their cycle and publishes); `input.signal` gets `asset` and `signal`; `blocks/run.py` holds the trace and recorded-port helpers (from `loops/analysis.py`); the publisher sends series points and scopes messages per algorithm; models and the asset cycle wired into the Runtime (`LINKCRAFT_SIMULATION_WORKERS`, `_TIMEOUT`, `LINKCRAFT_MAX_MODEL_MB`, `LINKCRAFT_MODEL_UPLOAD`); editor and pages for timing, assets, asset tests and runs. Tests: `tests/test_asset_algorithms.py`.
- 2026-10-22: image build fixed: `pip wheel --no-deps` for the wheelhouse (the lock is complete; without it pip resolved FMPy's cmake requirement and refused it under --require-hashes). Checked by downloading every locked wheel for aarch64 with hashes.
- 2026-10-22: phase 4, Calibrate and Unit twin: `assets/calibrate.py` (a deviation block's calibration learned over a period, `POST /api/algorithms/calibrate`), `assets.run.runs_over` and `segment_ends` (runs end to end over a period, one plant read), `assets/twins.py` (a Twin twin as a diagram and timing), the shipped `unit_twin` algorithm, built-in model blocks registered at import (`models.builtin.builtin_models`), `blocks.models.unjudgeable` shared by judging and calibrating, start parameters found for `TIC1104_PV` -> `TIC1104.y_start`; editor: Calibrate in the Deviation block's inspector (`@processcraft/ui` 0.17.0 `inspectorTools`). Tests: `tests/test_calibrate.py`, `tests/oracles/test_twin_oracle.py` (Twin's floors), `frontend/src/calibrate.test.ts`.
- 2026-10-22: Twin into Link, stage 4: `migrate --from-twincraft` (models and twins as algorithms on assets, calibration kept), model publishing API (POST/PATCH/DELETE /api/models, /starter), `/editor/new?model=<id>` and "New algorithm with this model" on a model block's page; ModelCraft's Publish to Link.
- 2026-10-22: the model starter guesses each signal block's role (outputs PV; u/OP/valve inputs OP, others secondary) so it opens valid.
- 2026-10-22: general blocks (17): transform.derivative/resample/expression/unit/select/operation_filter, logic.compare/combine (conditions.py), stats library (mean, std, percentile, histogram, correlation, steps, outside_limits), equipment library (heat_exchanger, pump); public references in each description; tests/test_general_blocks.py.
- 2026-10-22: attenuation, operating band, interventions and sampling quality made general: public references added (`methods/references.py`), maturity engineering heuristic, operating band with its own limits applies to any loop. Tests: `tests/test_methods.py::test_operating_band_with_own_limits_applies_to_any_loop`.
- 2026-10-22: Twin out of the suite, Link side: `assets/examples.py` (Twin's example twins ported: Furnaces on the furnace area, FIC-1001 and LIC-1010 process), `GET/POST /api/models/examples` (calibrated up to the plant's newest data), "Add the plant's model examples" on Algorithms. Tests: `tests/test_model_examples.py`.
- 2026-10-23: Link round 6, stage 1 (site blocks; owner's review, plan approved 10:06): block files `plantcraft-block/1` with Python code (`blocks/files.py`), immutable named versions pinned as `<family>.v<n>` (`blocks/store.py`, `site.py`, the catalog loads versions lazily from `<data dir>/blocks/`), site code checked and run in separate restricted processes (`blocks/sandbox.py`), shipped code shown read-only and copyable (`blocks/sources.py`), the new-block prompt for assistants (`blocks/guide.py`, `/api/prompts/new-block`), `/api/blocks` router (create, versions, owner and tags, delete, check, test on an asset). Interface: Blocks list with search and author, block page with Overview, Code, Parameters, Versions (diff) and Test tabs, New block by file, form or assistant, CodeMirror 6 editor (own `code` chunk). "Copy as prompt" buttons removed from blocks, methods and algorithms (the owner meant a prompt to create blocks). Tests: `tests/test_site_blocks.py`, `frontend/src/blockFile.test.ts`, e2e `test_a_block_is_written_in_the_form_versioned_and_diffed`.
- 2026-10-23: Link round 6, stage 2b (the queue): every execution is a row of `analysis_jobs` with `work` (loop, round, asset, replay), `priority` (manual 100, scheduled 50, replay 10), `due_at`, `attempts`, progress and `worker`; `JobStore.claim_next` takes the next due one in one `UPDATE ... RETURNING`. `engine/dispatcher.py` (workers, `RetryLater` with 30 s / 2 min waits), `engine/service.py` (`Engine`: scheduler, workers, queue samples via `processcraft_sdk.server.queue`), `engine/process.py` (`LINKCRAFT_ENGINE`: the child `linkcraft engine`, restarted when it stops; `flock` lease beside the database; a child stops with its server); `engine/worker.py` removed. Rounds are ordinary schedules (one `*` execution; the header kept in the schedule's last summary, read by `/api/status` and the weekly report); skip-if-busy and spread in `materialize_occurrence`; asset cycles become `algorithm-<id>` schedules (`Runtime.sync_asset_schedules`, kind `cycle`), the asset cycle thread is gone. `GET /api/queue`. Tests: `tests/test_queue_engine.py`.
- 2026-10-23: Link round 6, stage 2c: `api/routers/executions.py` (`GET /api/executions`, cancel, rerun), schedules API (`GET /api/schedules/{id}`, `POST /api/schedules/preview` with `Runtime.capacity` from `JobStore.mean_seconds` and `JobStore.upcoming`, `POST /api/schedules/{id}/replay`; priority, spread, owner and time zone editable; rounds and asset cycles keep their subjects, cycles their timing). `LatestStore.version` reads the table too, so the pages see the engine process's writes. Frontend: `ExecutionsPage.tsx` (QueuePanel + list), `SchedulesPage.tsx` (list and full-page form with preview), Queue widget on the Overview, nav entries. Replays of one schedule (`HistoryReplay.replay(schedule_id=)`); replayed loop runs are created running so the queue's workers never take them. Tests: `tests/test_queue_engine.py`, `frontend/src/schedules.test.ts`, two e2e journeys.
- 2026-10-23: `@processcraft/ui` 0.24.1 vendored (processcraft#114; 0.23.0 adds entries under a sidebar page, 0.24.0 shared charts): the Executions queue chart spans the whole window chosen, ending now, instead of zooming into milliseconds with one sample.
- 2026-10-23: Link round 6, stage 3 (algorithms): `method_profiles` gains `author`, `owner`, `owner_name`, `tags_json`, `group_id`, `version` (added on start; a save increments `version`; `PresetStore.update_meta`). Shipped set rebuilt in `blocks/algorithms.py`: `flow_loop`, `level_loop`, `temperature_loop` (Harris), `surge_level`, `signal_quality`, `unit_twin`, tagged; per-type defaults and the 0.2/0.3 alias map in `catalog/loop_types.py` (`loop_health`, `control_valve`, `oscillation_noise` -> `flow_loop`). `may_edit` in `api/routers/catalog.py` (platform groups cached a minute, members and coordinators up the tree), `used_by` per algorithm. Frontend: `AlgorithmsPage` is one `DataTable` with a tag `MultiSelect`; the algorithm page's Stewardship panel edits owner, group and tags; the editor opens read-only for those outside the group. Also: the queue's workers share one wake event, and a worker clearing it after a stop left the others waiting out their idle check (2 s per shutdown); the wake now stays set once stopping (`engine/dispatcher.py`).
- 2026-10-23: The Simulator plant's example twins are added by the scheduler's tick (`Runtime.add_model_examples`, service client, `assets.examples.create_examples` shared with `POST /api/models/examples`), once: `link_marks` row `model-examples`; another plant is looked at again every 10 minutes.
- 2026-10-23: `make lock` after the SDK 0.17.0 vendor (#62): `pyjwt==2.15.1` added to `deploy/requirements.lock` (the image's `pip check` failed without it; checked with the lock installed `--require-hashes --no-deps` in a clean venv plus the vendored wheels, `pip check` clean apart from the three FMPy extras the Dockerfile ignores).
- 2026-10-23: Link round 6, stage 2d: `processcraft-sdk` 0.19.0 vendored (processcraft#116); `Runtime.start` calls `ops.report_queue(self.engine.live)` and `shutdown` clears it, so `/api/ops/metrics` carries `queue` for PlantCraft's watch (`queue:linkcraft`). Test: `test_the_ops_metrics_carry_the_queue_for_plantcraft_s_watch`.
- 2026-10-23: Link round 6, stage 4: `/api/results` rows of any algorithm (signal, loop and asset-run rows, with algorithm version, tags, asset type and group) and filters `algorithm`, `tag`, `asset_type`, `group` with per-choice counts (`options`); `GET /api/reports/results.pdf` (`report/results.py`, reuses the weekly report styles); `GET /api/assets/<id>/link` returns every matching result instead of short-circuiting loops; ResultsPage drops LoopForm, sync and the weekly report; AssetLinkPage lists results; guide `results`. Tests: `test_results_api.py`, `test_asset_algorithms.py`, `test_app_standard.py`, e2e `test_the_asset_page_lists_every_algorithm_s_result`, `test_results_filter_by_tag_and_print_what_they_keep`.

## 2026-10-25: events declared, with severity, key and phase (Alarms round 8)

- `app.toml` `[[publishes.events]]` replaces the two-name list (it wrote eight kinds);
  `tests/test_event_catalog.py` holds code and manifest together, and `tests/plant.py` makes the
  fake refuse an undeclared kind. `api/events.py`, `loops/suite.py` and `data/suite.py` send
  `severity`, `key` (`<schedule>:<subject>`, `<asset>/<method>`) and `phase`.

## 2026-10-26: Link round 9 review, Q1 (blocks)

- `GET /api/blocks/{id}?version=N` (the page of one version; `in_use` beside `number`),
  `POST /api/blocks/{id}/current` (`BlockStore.select`; version 1 of a shipped block pops
  `CURRENT`, and `sync` does the same in the engine's process), `GET /{id}/copy?version=N`, and
  `POST /test` runs the exact catalog id it is given. `_meta` treats a shipped block whose site
  version in use is Link's own as a site block at version 1.
- Frontend: `BLOCK_TABS` reordered, `ShownVersion` banner, `versionAddress`, New version /
  Duplicate, `EditBlockPage` from `?version` with next = newest + 1, BlockForm "Also accepts",
  normal range, better when, runs on missing. Tests: `test_a_block_page_opens_any_version_and_one_is_selected_for_use`, `round9.test.ts`, e2e block journeys.

## 2026-10-26: Link round 9 review, Q2 (algorithms)

- `algorithm_versions` gains `version_name`, `version_note` (migration `version-notes`;
  `_VERSION_ROW` names its columns); `AlgorithmPayload.version_name/version_note`; the versions
  list returns them.
- `AlgorithmsPage.tsx`: `ALGORITHM_TABS` reordered, `?version=N` instead of a state, `ShownVersion`
  (Use this version saves it as the newest), `NewVersion` (BlockEditor, test, calibrate, timing and
  parameters in one form) with `VersionDialog`; Edit the diagram / Open the diagram buttons gone
  from the page. Tests: `test_a_new_version_keeps_its_own_name_and_what_changed`, `round9.test.ts`,
  e2e algorithm journeys.

## 2026-10-26: Link round 9 review, Q3 (schedule form)

- `SchedulesPage.tsx`: `Part` (fieldset with a hidden legend, `.schedule-part` grid: head 200-280 px,
  body up to 760 px; one column under 860 px) replaces `PartLegend`; `WhatItRuns` removed (the
  algorithm's link and version sit under its field). `lookback_minutes` 0 shows empty with "Link's
  default". e2e checks the layout at 1440 and 390 px and takes light, dark and phone screenshots.

## 2026-10-26: Link round 9 review, Q4 (executions and runs)

- Backend: `blocks.run.wires` (each output port's trace with only its last point) in asset and loop
  run summaries; `algorithm_version` kept by loop jobs (`LoopMonitor._version_run`) and rounds
  (`effective_method_config` returns `version`); `subject_history` answers `last_run` and, with
  `?run=`, `run` (`_asked_run`, none when not this subject's or pruned); `TestPayload.start` runs a
  loop over a past window (`LoopMonitor.preview(start, end)`).
- Frontend: `SubjectHistoryPage` tabs Overview / Last run / Runs via `?tab=&run=` (`subjectQuery`),
  `RunView.tsx` (lazy: React Flow loads only on a run) with Show every sample; the subject's page
  is a quiet link (`subjectPlace`). Tests: `test_execution_groups.py`, `round9.test.ts`, e2e
  `test_a_run_opens_inside_its_execution` (the e2e plant now has one manual run of FIC-101).

## 2026-10-26: Link round 9 review, Q5 (folders)

- `catalog/folders.py` `FolderStore` (`folders`, `folder_items`, one name per kind, a full folder
  is not deleted, objects deleted leave their folder) and `api/routers/folders.py`; block moves
  only for `site_blocks` (shipped libraries stay fixed). Called "folders", not "groups": an
  algorithm's `group_id` is the user group that edits it.
- Frontend `Folders.tsx`: `FolderColumn` (the `methods-layout` left column, also under the block
  libraries), `FolderField` on the three create forms (`?folder=` from the list), `FolderPlaceLine`
  with Move to folder (its dialog has no form: the schedule page is a form). Executions list by
  schedule folder. Tests: `tests/test_folders.py`, `round9.test.ts`, e2e
  `test_folders_hold_algorithms_and_schedules_and_moving_is_deliberate`.

## 2026-10-26: Link round 9 review, Q6 (compare versions)

- `Compare.tsx`: `ComparePicker` under the Versions tab (2 or 3 ticks, `/compare?versions=1,3`),
  `blockComparison` / `algorithmComparison` (inputs from the first run, outputs by key, recorded
  ports as series), `CompareView` (columns per version, overlay charts only for rows with samples).
  `BlockTest` and the algorithm `TestTab` take `compare`: the first run fixes the window
  (`window.end`, or `source_start`/`source_end` for loops) and the others reuse it. Version ids:
  `versionBlockId` (Link's shipped version 1 is the family id). Tests: `round9.test.ts`, e2e
  block and unit twin journeys.

- Test budget: `suite_seconds` 180 -> 360. The whole run (1187 tests, all passing) took 222 s on
  the shared Mac mini runner and 229 s in a container, so main's Link job was red on time alone.
  The slowest test, the junk sweep over every API route (36 s, already `slow`), spends about 10 ms
  on each of its ~3600 requests, with no single slow handler to fix.

## 2026-10-26: folders move into the platform (Models round 9 M5)

- `catalog/folders.py` is now `FolderStore` of `processcraft_sdk.server.folders` with Link's
  kinds; `api/routers/folders.py` is `folders_router(KINDS, editor, exists)`. The frontend's
  `Folders.tsx` is gone: the pages import `FolderColumn`, `FolderPlaceLine`, `FolderField`,
  `FolderButton` (the block libraries) from `@processcraft/ui`, set up in `api.ts`
  (`configureFolders`). `methods-layout`/`methods-group` became the suite's `pc-folder-layout` /
  `pc-folder`; the e2e reads `#pc-folder-name`, `#pc-folder-target`, `.pc-folder-place`.

## 2026-10-26: the compare picker and code difference move into the platform

- `ComparePicker`, `comparedVersions`, `lineDiff` and the code difference (`CodeDiff`, `pc-diff-*`)
  come from `@processcraft/ui` 0.59.0; `Compare.tsx` keeps Link's comparisons and wraps the
  picker with the Compare tab's address. The e2e reads `.pc-diff-added`.


## 2026-10-26: a block's picture and drawing (round 9 Q7a, M1 and M2)

- A block file takes `image`, a data URL checked by `processcraft_sdk.images.block_image` (PNG,
  JPEG, WebP by their first bytes; an SVG rebuilt from an allow-list; at most 256 KB). It goes
  in `BlockSpec.image`, so each pinned version has its own; `describe_block` gives the path
  `/api/blocks/<id>/image?v=<tag>` and the frontend turns it into the browser's with
  `withImageHrefs`. The node, the palette (`@processcraft/ui` 0.60.0) and the Overview's
  `BlockDrawing` show it; the form chooses it with `BlockImageField` (`#blkf-image`).
- Tests: `test_a_block_keeps_its_image_with_the_version_and_serves_it_by_a_tagged_url`; the
  block journey sets a picture and checks the drawing loads it.

## 2026-10-26: round 10 of the owner's review (libraries, Duplicate, runs on the diagram)

- Libraries: `site_libraries` in `BlockStore` (`create_library`, `libraries`), listed by
  `catalog.libraries(site=...)` before Outputs, `POST /api/blocks/libraries`. A block file's
  library is one Link opens or any id matching `files.LIBRARY` that is not closed
  (`open_library`), so worker processes read a site library's blocks without the table.
  Blocks lost their folders (`useFolders("block")`, `FolderPlaceLine`, `FolderField`); the
  `block` folder kind's rows stay unused.
- Lock: New version moves to the Versions tab (`VersionsTab.actions`); a block that is not a
  site block (`canNewVersion`) and a system algorithm show `VersionLock`. The server still
  takes a site version of a shipped block (D2, 2026-10-25), only the page no longer offers it.
- Runs: `blocks.run.samples` (120 points per wire) goes with each run's summary and
  `engine.samples.RunSampleStore` keeps it, apart from the summary (`lean_summary` drops it),
  for the newest 10 runs per subject and schedule (`run_samples`; a loop's round keyed
  `<loop>@<source_end>` in scope `round`, as it keeps no job). `_last_run` and `_asked_run`
  return the samples as `wires` with `sampled`; `_past` gives a loop's kept rounds an id.
  `prune_jobs` drops samples of deleted jobs. Tabs Overview and Runs (`?tab=last-run` and
  `run=last` open the last run); `lastValues` draws an old run's one-point series as numbers.
- Over time: one output at a time (`#subject-output`, every recorded output of a loop too),
  `PeriodPicker` with 1 h, 24 h, 7 d, 30 d.
- Tests: `test_a_site_makes_its_own_libraries_and_puts_blocks_in_them`,
  `test_only_the_last_10_runs_of_a_subject_keep_their_samples`, the subject test checks the
  samples and a round's run; `round10.test.ts`; e2e
  `test_a_block_plantcraft_ships_is_locked_and_duplicates_into_a_new_block` (replaces the
  shipped-edit journey) and the execution journey clicks a block for its chart.

## 2026-10-27: the Overview answers which loops and signals are bad now, and where

- New widgets (`api/plant_widgets.py`): `in-alarm-history` (columns, 14 days on the
  installation's clock; past days from `subject_health` and `quality_history`, the status each
  subject ended the day with, read again every six hours; today from the live results) and
  `health-map` (tiles by the parent asset of each loop and signal, from the synced asset tree
  or the loop's stored area and unit; past 1500 squares the alarm and warning ones stay first).
  `quality_history` gets a time index. Default board: results 8 × 2, 14 days 4 × 2, health map
  8 × 3, worst 4 × 3, monitors and queue 6 × 3. SDK 0.69.0, ui 0.72.0.
- Tests: `tests/test_overview_widgets.py`; the overview e2e journey checks the new cards.
- 2026-10-28: demo fine pass. FIC-1003 read "Data not usable" because the Historian handed its
  first-day *suggested* ranges (unconfirmed) as engineering limits, so Signal quality's range and
  noise checks failed PVs and OPs of most loops (OP 47-52 % judged against a 3.8-wide range):
  the Historian now gives other apps only confirmed ranges. Results/widgets name signals
  `AIC-1006 · OP` (`results.signal_label`); the health map puts a loop's SP and mode in its area;
  a Signal quality run's page lists the signals it judged; signal chart axis "Time" (local);
  loop title is id · name.
