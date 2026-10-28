# Devlog

Terse log, newest last: what landed, numbers, what is still open.

## 2026-10-19

- Imported the platform as ProcessCraft with fresh history. Removed pilot-specific scenarios,
  documents and competitor material, the Cloudflare tunnel and the signed-license gate.
- English is now the source language; pt-BR catalogs for the frontend and the backend, a language
  switch in the app, help pages in `docs/en` and `docs/pt-BR`.
- New visual identity (tokens, fonts, logo) and the Apache-2.0 license.
- Rules for agents (`AGENTS.md`), `ROADMAP.md`, `docs/STATUS.md`, `docs/gaps.md`, `make ci`.
- `tests/test_hostile_inputs.py`: 17 methods x 14 junk datasets and 135 API operations with junk;
  all green. Floors in `tests/floors.toml`.
- Open: G1 (formal diagnosis report), G3/G4 (oracles), G5 (product names in the UI).

## 2026-10-19 (later)

- Backend messages, method findings, help and the weekly PDF translated (`t()`); 1133 pt-BR entries, floor 1100.
- Visual identity wired into every screen and chart; app logo family (nine marks) in `docs/images/apps/`.
- Owner direction: separate apps (ProcessCraft central, CPMCraft and others in their own repositories), MVP plan steps 1-11.
- Tests: 494 passed (unit, architecture, hostile inputs, floors, i18n, offline).

## 2026-10-19 (API v1 and processcraft-sdk, MVP steps 4-6)

- `docs/api-v1.md` implemented in `processcraft/api/routers/v1.py`: Ed25519 token keys
  (`processcraft/auth/tokens.py`, beside the database, 0600, rotation keeps old public keys), app
  keys stored hashed (`auth/app_keys.py`, admin API `/api/app-keys`), central audit log
  (`processcraft/audit`), `processcraft_token` cookie at sign-in and in local mode,
  `PROCESSCRAFT_APPS` (`auth/suite.py`). Launcher on the home page; app keys under Users.
- `sdk/python` (`processcraft-sdk` 0.1.0): `jwt`, `auth` (TokenVerifier, FastAPI dependency,
  middleware), `client` (every v1 endpoint), `methods` (the one `@method` implementation;
  `processcraft.catalog.{sdk,contracts,findings,utils}` are aliases of it), `testing`
  (`FakeProcessCraft`). `make ci` installs and tests it.
- Contract tests `tests/contract/test_api_v1.py` (45, incl. read-only spy and doc/route parity);
  SDK tests 34. API operations floor 135 -> 150.
- Open: the Dockerfile and the e2e CI job must install `sdk/python` before processcraft (owned by
  the deploy thread); CPMCraft switches to the SDK client in step 7.

## 2026-10-19 (API v1 and deploy)

- API v1 (`docs/api-v1.md`) with Ed25519 tokens, app keys, audit log and contract tests; `processcraft-sdk` 0.1.0 in `sdk/python` (jwt, auth, client, methods, FakeProcessCraft).
- Isolated offline Docker deploy: `deploy/compose.yaml` (proxy only published port, `apps` internal network), `make bundle`, `install.sh` with backup, `--rollback`, firewall script; live isolation tests 24 passed; install from bundle 97 s.
- Open: npm audit shows 1 high and 2 critical transitive findings (plotly.js chain); CPMCraft image not built yet.

## 2026-10-19 (API v1 text signals, batch read, processcraft-sdk 0.2.0)

- API v1, additive only: signals and series carry `kind` (`number`, `text` from the source's
  data type); text series give labels (with `step`, the last label per step) and `value` gives
  the newest label for `agg=last`. New `POST /api/v1/series`: up to 500 signals in one request
  and one source read, 2,000,000 points per answer, failures per signal in `errors`
  (404, 422, 502, 413 postponed). Series are written with `JSONResponse` and vectorized,
  memoized ISO times (`contract.iso_many`).
- Local mode: tokens (and `POST /api/session/switch`) follow the session's current user, so
  apps' audit rows name the same person as ProcessCraft's.
- `processcraft-sdk` 0.2.0: `series_many` (chunks of 500, re-asks 413s, falls back to one
  request per signal on a ProcessCraft without the route), `series_many_pandas`,
  `series_frame` on the batch; text series as object `pandas.Series`; `FakeProcessCraft` has one
  implementation (`handle`) behind an `httpx.MockTransport` client (default) and a Starlette
  ASGI app (`transport="asgi"`, uvicorn); recorded series end at their last sample; `broken`
  signals; audit tagged with the app id from `app=` or a service token. 62 SDK tests.
- Tests: contract tests for kind, text, the batch (shape, order, limits, 413, 502, auth,
  read-only spy, one source read), local-mode user. API operations floor 150 -> 151.
- CPMCraft bench (2000 loops, 4 processes, 2 ms): 147 s -> 53-61 s cold / 46-48 s warm on this
  4-core box; the monolith's loop round measured on the same box is 47.6 s / 43.8 s.

## 2026-10-19 (central app only)

- ProcessCraft keeps users, roles, sign-in, app access, app keys, tokens, API v1, the audit log,
  data sources (PI Web API, OPC UA, CSV) and the series cache, signals, assets and asset kinds,
  the plant map, the launcher, settings and help. Removed: `applications/`, `engine/`,
  `catalog/`, `report/`, `work/`, `messages/`, `specialists/`, `visualization/`, `demo/`, their
  routers, pages, tests and docs (CPMCraft owns the analysis; the rest is parked there or
  waits for TrendCraft). Scenario loops are now loop assets (`platform/loops.py`), and the
  map's `loops` sheet writes loop assets; loop settings are left to CPMCraft with a warning.
- Floors (`tests/floors.toml`): restructuring, not a regression. The method (17), hostile-frame
  (14) and oracle floors left with the methods; they are CPMCraft's to keep. The API floor was
  151 operations of the monolith and is now 62 of the central app (13 of them API v1), with new
  floors for the 32 contract tests, 3 source types and 10 browser journeys. The pt-BR catalogs
  were pruned to the strings still in use (frontend 1584 -> 469, backend 1133 -> 316) and their
  floors restarted there.
- Tests: 183 passed, 6 skipped (was 572 passed with the analysis inside), SDK 62; e2e rewritten for the
  central app (sign-in, return to `?next=`, launcher with CPMCraft from `PROCESSCRAFT_APPS`,
  sources, plant map import, assets, users and app keys, offline and Portuguese): 10 passed.
- Dependencies: `scipy` and `reportlab` dropped (and `pillow` with them from the lock); npm:
  CodeMirror, dnd-kit and React Flow dropped.
- Upgrade: a monolith database's loop assets (origin `cpm`) are handed to the scenario origin on
  start (`AssetStore.adopt`), so their stale areas go away instead of doubling the tree.
- Live isolation (`PROCESSCRAFT_ISOLATION=live`): 24 passed. Image 743 MB -> 505 MB.
- Open: G31 (PlantCraft switch-over).

## 2026-10-20 (asset model)

- Asset types (`processcraft_sdk.assets`, `processcraft/assets/types.py`): single inheritance
  resolved on read, attributes (text, number, choice, date, asset), signal roles and "may
  contain". Starter types: site (Plant), unit, area, equipment, pump, valve, control_valve,
  instrument, loop (Control loop: loop_type, criticality, action, controller; roles pv and op
  required, sp, mode, secondary). Existing kinds stay their type; custom asset kinds are adopted
  as types under equipment. Admins edit types (`/api/asset-types`, 403 otherwise); editors fill
  records (`PATCH /api/assets/{id}/attributes`), relations (controls, measures, feeds,
  downstream of) and bind signals to roles. Every record change goes to the audit log and the
  asset's history with who and when. A hand-made asset keeps its tag as given (`asset_id`).
- Plant map: one sheet per type (asset_id, name, parent_id, description, then attributes and
  roles), a `relations` sheet, loop records in the `loops` sheet; export writes them back.
- API v1, additive: `type_path`, attribute values, `relations`, `type` filter and
  `GET /api/v1/asset-types`. `processcraft-sdk` 0.3.0 (FakeProcessCraft serves the same).
- Interface: Assets › Types (list with counts, type editor), tree filters by type and attribute
  with a table of the type's attributes, asset page with header, record form, signals by role
  ("Bind signal"), relations out and in, contents and history.
- Floors: API operations 62 -> 73 (v1 13 -> 14), contract tests 32 -> 34, browser journeys
  10 -> 12. Tests: 49 asset-model tests (hostile types, cycles, unknown keys, wrong data types,
  huge strings: never a 500).
- Open: "may contain" is advisory (offered first, not enforced); no pt-BR strings for the new
  pages yet; CPMCraft reading `type`/records (stage 2) is its own work.

## 2026-10-19 (Apps page and the installer, G16)

- Apps page (admin only): install a signed `.pcapp` from a file, from the online catalog (off
  until an admin turns it on), or register an external app (address, health check, app key shown
  once). Publisher, version, summary, permissions and SBOM are shown before confirming; update,
  rollback, uninstall and "give it an app key"; every step audited.
- Package format and checks in `processcraft/apps/package.py` (`docs/app-package.md`): the
  manifest is the app's `app.toml` (`docs/app-standard.md`) plus file hashes, Ed25519 signed;
  suite table, `plant_write = false` and `outbound = []` enforced. `deploy/package.sh --app
  app.toml` builds one from any repository; `make dev-publisher` makes a git-ignored dev key.
- New `installer` service (uid 10005, no network, read-only): the only part with the Docker
  socket; ProcessCraft hands it requests through `data/app-requests`. `install.sh --add/--remove`
  run the same code. Apps run under the standard's container rules and settings.
- Tests: package (138, hostile tars and manifests), installer with a fake Docker (29), Apps API
  (43), one e2e journey, and a live test on real Docker (`PROCESSCRAFT_INSTALLER_LIVE=live`).
- Open (G16): licence check (no licence notion yet), permission scopes on app keys, the proxy
  restart on each app change.

## 2026-10-20 (app standard, phase A)

- `docs/app-standard.md` committed: the standard every app follows (decided 2026-10-19, D1-D5).
  Built frontend files go to `<prefix>static/`; `assets/` is the asset deep link.
- API v1, additive (`api/routers/v1_links.py`, new layer-1 store `processcraft/results`):
  `PUT/GET /api/v1/results` (one row per app, subject and kind; expired results read
  `unknown` and stale; status changes kept 90 days, `GET /api/v1/results/history`),
  `POST/GET /api/v1/events` (the existing `EventStore`, kinds `<app>.<noun>.<verb>`),
  `PUT/GET /api/v1/runs` (90 days) and `PUT/GET /api/v1/schedules`. A service token writes for
  its app; a person names the app and needs editor access to it; unknown subjects are 404 per
  item. Bodies are validated without echoing input, so NaN is a 422 (G33 for the old routes).
  `processcraft.refs` ids may hold `/` (run references).
- Executions page (`/executions`, editors and admins): every app's runs and schedules, filtered
  by app and status, rows linking into the app.
- SDK, `processcraft-sdk` 0.4.0: `refs` (`parse_ref`, `format_ref`; signal refs
  read `signal:<source>:<tag>` and today's `signal:<tag>`), `links` (shared shapes and rules),
  client methods and `FakeProcessCraft` routes for the new endpoints, `app_manifest` (app.toml,
  sections 4 and 7) and `processcraft-app check [path]` (manifest, layout, pyproject version,
  Makefile targets, vendored wheel SHA-256; warns when Vite keeps `assets/`). Fixed the fake's
  value route on long windows of recorded series (mixed fractional timestamps raised
  ValueError; recorded series are now read as recorded, last sample included).
- `tests/test_suite_table.py`: `deploy/compose.yaml` users and ports, and the SDK's table,
  match section 7, and so does the installer's (`processcraft/apps/package.py`). Floors after
  merging the asset model and the Apps page: API operations 97 (v1 23), contract tests 53,
  browser journeys 14.
- Open: G32 (signal ids with their source, D2), G33 (NaN bodies on the older routes), G34
  (ProcessCraft's own `/assets/<id>` and `static/`). TrendCraft's request for a `dashboards`
  viewer claim is on hold.

## 2026-10-19 (PlantCraft runs the demo, G31 closed)

- The demo plant is PlantCraft 0.4.0 (`plantcraft loops serve`): `scenarios/opcua_demo.json`
  lists its 50 loops (205 NodeIds, checked against `plantcraft loops catalog` and read from a
  live server with no failed tag), namespace `urn:processcraft:plantcraft`, endpoint
  `opc.tcp://127.0.0.1:4840/plantcraft/`; OPC UA sources default to that namespace.
- `run_opcua_demo.py` starts PlantCraft from the installed package (state in `var/plantcraft/`)
  or uses whatever listens on 4840; without either it says how to install PlantCraft.
- Compose `plantcraft` service (profile `demo`) runs `plantcraft:${PLANTCRAFT_VERSION:-0.4.0}`
  with PlantCraft's OPC UA health check. `make plantcraft-image` builds it from
  `PLANTCRAFT_SRC` (../plantcraft); `bundle.sh` ships it when present; `install.sh --demo`
  refuses a bundle without it.
- Removed `processcraft/simulator`, its tests, `include_simulator_catalog` and
  `processcraft-opcua-server`; `simulator` is in the architecture test's MOVED table.
- Tests without PlantCraft: `tests/opcua_plant.py`, an asyncua server with the same nodes, for
  the OPC UA round trip; with PlantCraft installed, `tests/test_opcua_demo.py` also checks the
  scenario against its catalog and reads the real server. The live isolation tests use the real
  image when built, else a stand-in at `plantcraft:4840` (CI).
- Open: CI cannot build PlantCraft's image until its repository is reachable (owner decision).
- Loop records: `sync_scenario_loops` fills `loop_type`, `criticality`, `action` and
  `controller` from a scenario loop's metadata where the record has none (a person's value
  stays). The demo scenario gives all 50 PlantCraft loops their `loop_type` (13 flow, 13 level,
  9 pressure, 10 temperature, 5 composition), written in the file from the ISA letter and
  checked against PlantCraft's PV units; client tags are never guessed.

## 2026-10-19 (deep links, G34 closed)

- An asset opens at `/assets/<id>`, the assets tree at `/assets`; `/plant` and `/plant/<id>` are
  replaced in the browser by the new address (query and hash kept). Every in-app link uses
  `assetPath()` (`frontend/src/assetLinks.ts`); `/api/refs` hrefs follow.
- Vite builds into `dist/static/`; the backend mounts `/static/` and answers a missing
  `/static/...` or `/api/...` with 404, never with the page; `/assets/<id>` gets the page.
- The asset page shows **Open in**: each installed app's `<prefix>assets/<id>`. Rule
  (docs/app-standard.md, section 2): the person may open the app, and its `[requires]
  asset_types` holds the asset's type or an ancestor; an app whose manifest is unknown
  (`PROCESSCRAFT_APPS`, external) is linked for every asset. Installed apps keep
  `asset_types` from the package through the installer's record (`installed.json`).
- Tests: `tests/test_deep_links.py` (13), launcher `asset_types` in `test_apps_api.py`, 4
  frontend unit tests, 2 new browser journeys (16 in all).

## 2026-10-20 (signal ids with their source, G32 closed)

- Decision D2 done before API v1 is frozen: a signal's id is `<source id>:<tag>` (the scenario's
  source is `scenario`), built from the source registry (`processcraft/platform/signals.py`,
  `SignalCatalog`); asset role maps use the new ids. Each tag is still read from one source
  (its route, else the scenario's), so moving a tag changes its id.
- Transition: every v1 route that takes a signal id also takes a bare tag that exactly one
  source has (deprecated, dropped at the freeze); two sources: 404 naming both ids. Subjects
  and event refs written with a bare tag are stored by the new id; read filters accept both.
- Storage, additive: `asset_signals.source_id` (guarded `ALTER TABLE`), filled from the
  routes at start and after every source or map change; a one-time rename of stored
  `signal:<tag>` subjects and refs (results, result history, run subjects, events) through
  `ResultStore.rename_subjects` and `EventStore.rename_refs`, recorded in the new
  `workspace_migrations` table so it runs once.
- Refs: one rule for `processcraft.refs` and `processcraft_sdk.refs` (`check_id`): ids are
  written as they are, never percent-encoded (PI tags keep spaces and `\`); source ids widened
  to `[a-z0-9][a-z0-9_-]{0,47}` (what `source_id_for` gives). `/api/refs/{ref:path}`.
- The interface's bind picker sends v1 ids: `POST /api/assets/{id}/signals` stores the tag and
  its source; the internal `/api/signals/{tag}` routes also read a v1 id.
- `processcraft-sdk` 0.5.0: `FakeProcessCraft` signals `fake:FIC-101.PV`..., bare tags still
  read, `series=`/`broken=` keyed by id or tag (synthetic values seeded by the tag, unchanged);
  `refs.split_signal_id`, `Ref.signal_id`, `check_id`, `valid_id`.
- Apps to follow in their own PRs: CPMCraft (re-read loop roles; migrate anything keyed by a
  bare tag; vendor SDK 0.5.0); DataCraft, TrendCraft and HistCraft treat signal ids as opaque.
- Numbers: `make ci` green (556 passed, 8 skipped; SDK 150; frontend 16), browser journeys 17
  (new: a role bound from the picker by its v1 id); floors raised to contract tests 57 and
  journeys 17.

## 2026-10-20 (lists of events, subjects with commas, reproducible SDK wheel)

- G39 (reported by CPMCraft: its cold round posted about 10,300 finding events one request each,
  96.7 s against 63.2 s on the 2,000-loop bench): `POST /api/v1/events` also takes a JSON list
  of 1 to 1,000 events. Shapes (now including `refs`, checked in `EventIn`) are a 422 for the
  whole request; per-item errors (404 subject, 403 app, 422 kind or missing `app`, a subject
  events cannot store) are in `errors` as in the PUTs; 201 `{"saved", "ids", "errors"}` with
  `ids` aligned to the items. `EventStore.publish_many` records them in one transaction
  (`publish` uses it). Shape rules in `processcraft_sdk.links` (`MAX_EVENTS`, `parse_events`,
  `EventsReceipt`); `client.post_events` sends lists of 1,000; `FakeProcessCraft` serves both.
- Microbench, 10,000 events with the SDK client against ProcessCraft on uvicorn (4 cores,
  SQLite on local disk): one request each 135.5 s (74 events/s), lists of 1,000 5.9 s
  (1,704 events/s), 23x.
- G41 (reported by CPMCraft): `client.results()` joined subjects with commas and ProcessCraft
  split them, but ids may hold commas (`refs.check_id`; PI tags do). `subject` is now one
  subject per repeated parameter and never split; the client repeats it and the fake keeps
  repeated query parameters (`handle(query={"subject": [...]})`). The other v1 id filters
  (`results/history`, `events?ref`, `runs?subject`) take one id and never split. Test: a tag
  `Unit 2,FIC 101.PV` beside a decoy `Unit 2`.
- Contract tests 57 -> 60 (floor raised). `processcraft-sdk` 0.6.0; ProcessCraft requires
  `>=0.6,<0.7`. Apps: vendor 0.6.0, use `post_events` for rounds, and stop joining subjects
  with commas.
- Reproducible SDK wheel: DataCraft and TrendCraft had built 0.5.0 from the same commit with
  different SHA-256 (their setuptools differed). `make sdk-wheel` copies sdk/python's files (git's
  view, without tests) with fixed modes, builds under umask 022 with `SOURCE_DATE_EPOCH=315532800` and the
  setuptools pinned in `[build-system]` (`setuptools==80.9.0`, isolated build, no cache) and
  prints the SHA-256. Two builds, and a build from a fresh clone under another umask, give the
  same bytes: `processcraft_sdk-0.6.0-py3-none-any.whl`
  `f5abfa7d801533f7775efe8b0fb3f97b0c7e45179a9b9a87dbdf77f4b76e0ddf`. Apps vendor that wheel
  (`docs/app-standard.md`, section 3).

## 2026-10-20 (clean-install follow-ups)

From the clean offline install of 2026-10-19 (items 4 to 9 and 11 of its report):

- Kinds of an added source's signals come from that source, browsed once per source and kept
  until its settings or routes change (`SourceRegistry.signal_kinds`; unreachable: numbers,
  retried after a minute). PlantCraft's modes are `text` in API v1 and `/series` returns
  `AUTO`/`MAN`, so CPMCraft sees manual mode.
- The plant map preview and import run in a worker thread: checking an added OPC UA source's
  tags no longer fails with "asyncio.run() cannot be called from a running event loop".
- Asset attributes were already stored and imported (the loops sheet carries the Control loop
  type's attributes, JSON and Excel, since the asset model work); the report's build predated it.
- `deploy/demo/plantcraft-50-loops-map.json`, written from `scenarios/opcua_demo.json` with each
  loop's `loop_type` (`python -m tests.test_demo_map`), ships in the bundle's `demo/` with
  PlantCraft; a test imports it against the site scenario and a test OPC UA server cleanly.
- Deploy: PlantCraft on an internal `demo` network (no NAT egress without `firewall.sh`); the
  proxy and PlantCraft resolve service names only (`dns: 127.0.0.1`, checked on Docker 29: the
  embedded resolver still answers service names and asks loopback inside the container for
  anything else, which fails at once); ProcessCraft too unless `PROCESSCRAFT_DNS` is set. A live
  isolation test checks that no container resolves an external name.
- The top bar names the sources read (PlantCraft, not "CSV file"); `make sdk` installs into a
  virtual environment only.
- Open: G35 (a CI job over the whole bundle); CPMCraft's `/cpm/healthz` version is CPMCraft's.


## 2026-10-20 (data layer and derived series)

- `processcraft/platform/datalayer`: one interface, two implementations. `local` is the old
  behaviour, moved out of `routers/v1.py` unchanged (sources, catalog, history cache) plus
  derived series in `derived_series`/`derived_points` (`industrial_data/derived.py`). `histcraft`
  (`HISTCRAFT_URL`) forwards API v1 signal and series reads, derived writes, the asset page and
  history charts, connection status, result/event signal subjects, the Sources page (list, add,
  edit, remove, "Use", status and test of saved sources, browse; testing unsaved settings and
  "stop using" are a 501) and the plant
  map's sources to `{HISTCRAFT_URL}/api/v1/data/...`
  with a token ProcessCraft issues to itself (`app:processcraft`, `aud: histcraft`,
  `apps.histcraft: editor`, 5 min, cached). HistCraft's 400/404/409/413/422 pass through, other
  failures are 502, timeouts 504. Source shapes follow HistCraft's confirmed contract and are
  mapped in `datalayer/histcraft.py` only. History prewarm is off with HistCraft.
- `PUT /api/v1/series`: derived series, app service tokens only, own source `app-<app id>`
  (another app's source: 403, nothing written); up to 500 items and 100,000 values; `name`,
  `unit` (`/100` for scores), `kind`, `subject`, `result`. Read back through every v1 read;
  `GET /api/v1/signals?app&subject&result`. `processcraft-sdk` 0.7.0 (`put_series` splits long
  lists and series; the fake serves it all). `make sdk-wheel`, twice the same bytes:
  `processcraft_sdk-0.7.0-py3-none-any.whl`
  `9433a75b91630f98c84fa7687b77110a7b0cf1316d0d8fcd364f25ce8303e16d`.
- Contract tests 60 -> 76, v1 operations 23 -> 24, /api operations 97 -> 98 (floors raised).
- Open: with HistCraft, a few start-up and map-preview metadata reads still browse the scenario
  source (loop units in `platform/loops.py`, tag checks and signal names in
  `platform/plantmap.py`); the plant map's "remove sources not in the file" is not forwarded.

## 2026-10-20 (HistCraft: test unsaved settings, stop using a signal)

- With `HISTCRAFT_URL`, the Sources page's "Test" before saving forwards to HistCraft's
  `POST /api/v1/data/sources/test` (the edit body; a new source sends `password: ""`, an edit
  `null` so HistCraft uses the stored one; its 502 is `ok: false`), and "Stop using" sends
  `PATCH /api/v1/data/signals/{source}:{tag}` `{"enabled": false}` per tag (404 skipped,
  derived 422 passed on). Both were 501. Needs HistCraft main `274f47b`.
- Fixed: `source_body` sent `username`/`password_env` as `null`, which HistCraft's `SourceIn`
  (strings) refuses; now `""`.
- Bare tags: HistCraft now resolves them on `/signals/{id}`; ProcessCraft already took the
  canonical id from its answer, so there was no workaround to remove. Contract tests cover it.

## 2026-10-20 (series grids hold the last value: step-hold)

- Reported by TrendCraft: a grid (`step`) was a plain mean per `[t, t + step)`, so setpoints and
  modes recorded on change, signals scanned slower than the step and the newest step came back
  `null`, and trends ended with a gap (CPMCraft's SP/OP grids too). `shape_series` and
  `shape_text_series` (`processcraft_sdk.contract`) now hold the last value into empty steps,
  from the first sample (or the look-back value before `start`) to `end`. Not held: before the
  first sample, past a `null` sample (the source or app said "no value"), past the hold limit
  (`HOLD_STEPS` = 10 times the larger of `step` and the signal's median spacing; unbounded below
  three samples), or after now. Steps with samples keep their mean or last label.
- Server and fake: `LocalDataLayer` drops the NaN a wide read leaves where a tag has no sample
  (so they don't end holds) and asks the sources for the value before `start` on grid reads
  (`include_boundary=step is not None`; recorded reads unchanged). `FakeProcessCraft` passes its
  `now`. A contract test reads the same derived series from ProcessCraft and the fake.
- `processcraft-sdk` 0.7.1 (ProcessCraft still requires `>=0.7,<0.8`). `make sdk-wheel`, twice
  the same bytes: `processcraft_sdk-0.7.1-py3-none-any.whl`
  `f834673a986ee5ff7fe9521cdbd7e0bc1b4b04394200be328ff1feeccbcd876a`.
- Contract tests 76 -> 77 (floor raised); SDK tests 159 -> 169 (`sdk/python/tests/test_step_hold.py`).
- Open: HistCraft serves grids with its own copy of the SDK; it matches once it takes 0.7.1.
  CPMCraft's bench was not rerun here (one extra look-back read per tag on a cold cache).

## 2026-10-20 (after the MVP review)

- Owner review of the MVP (plan: "Plano pós-MVP", decisions D6-D9 in `docs/app-standard.md`).
- `ui/`: `@processcraft/ui` 0.1.0, the frame every app draws: `SuiteShell` (left sidebar with
  the app's pages, **Apps** from `GET /api/v1/apps`, Help, user menu with theme, language, About
  and Sign out; folds to icons; drawer on a phone), `HelpBrowser` (guides in folders with a
  filter), `PageTabs`, brand marks, `tokens.css`/`fonts.css`/`shell.css`, theme helpers.
  `make ui-package` packs it (same bytes twice); `make ui-check` (in `make frontend` and CI)
  fails when `frontend/vendor/processcraft-ui-0.1.0.tgz` is not what `ui/` builds.
- App family: LinkCraft (Loop Teal, two wired blocks) replaces CPMCraft, DataCraft and TrendCraft;
  their machine ids map to it.
- ProcessCraft menu: Home, Assets (tabs Assets | Asset types), Users, App keys, Apps; Help and the
  user menu at the bottom. Settings page and `GET /api/settings` removed (legacy); `/settings`
  goes home and `/settings/users` to `/users`. Executions hidden from the menu (`/executions`
  still served). Source chip removed. Language picker on the sign-in page and in the user menu.
  The home's Sources and signals card and `/data` open HistCraft's sources when it is installed.
  `/api/home` returns the version (About).
- `processcraft-sdk` 0.8.0: `processcraft-app check` wants the frame (`@processcraft/ui` from
  `vendor/`, hash in `vendor/README.md`, `SuiteShell` in `frontend/src`).
- API floor 98 -> 97 (the removed `/api/settings`; owner decision, not a regression).

## 2026-10-20: DashCraft stays its own app (`@processcraft/ui` 0.2.0)

- Owner revised D9: dashboards are only a view of HistCraft's data, so TrendCraft stays a
  separate app, renamed DashCraft (`dashcraft`, `/dash/`, port 8080, uid 10006; repository
  renamed `dashcraft`). LinkCraft is CPMCraft + DataCraft only.
- `@processcraft/ui` 0.2.0: DashCraft mark (Chart Indigo, the former TrendCraft glyph);
  `dashboards` and `trendcraft` map to it. `make ui-package` creates `frontend/vendor/` when
  missing.
- processcraft-sdk 0.8.1: the suite table's `trendcraft` row is now `dashcraft` (DashCraft,
  `/dash/`, 8080, 10006), so `processcraft-app check` accepts the renamed app.
- The stack runs DashCraft: compose service, profile, image, secrets and `DASHCRAFT_*` settings,
  the proxy serves `/dash/` and redirects `/trend/...` there, the package table and app names
  know `dashcraft`. `install.sh` moves an earlier `trendcraft` profile and `data/trendcraft/` to
  `dashcraft` on upgrade (`FORMER_APPS`); the old app key names the old id, so DashCraft gets a new
  one. Access granted to `trendcraft`/`dashboards` (or `cpmcraft`/`datacraft` for LinkCraft) keeps
  opening the new app (`FORMER_IDS` now lists several former ids per app).
- `@processcraft/ui` 0.2.1: relative imports in `dist/` carry `.js` (Node's ESM loader, e.g. in an
  app's vitest, refused them); the phone drawer's shadow only shows while it is open (it bled a grey
  band onto the page edge).
- `@processcraft/ui` 0.2.2: 0.2.1 still imported `./i18n` without `.js` (four files), so an app's
  vitest still refused the package. Fixed, and `ui/src/ui.test.ts` now fails on any relative import
  without `.js` or `.css`.
- Step 6 of the post-MVP plan, the deployment: compose service `linkcraft` (LinkCraft, `/link/`,
  8140, uid 10012, `LINKCRAFT_*`, secret `linkcraft_app_key`) replaces `cpmcraft` and `datacraft`;
  the proxy redirects `/cpm/...` and `/quality/...` to `/link/...` like `/trend/...` to
  `/dash/...`. `install.sh`: `SUITE_APPS` linkcraft, dashcraft, histcraft; `--with-linkcraft`
  (`--with-cpmcraft`, `--with-datacraft`, `--with-trendcraft` kept as aliases); LinkCraft on by
  default; `FORMER_APPS` entries are `old:new:rename|merge`: TrendCraft's folder is moved,
  CPMCraft's and DataCraft's stay (a rollback runs them again) and are copied to
  `data/linkcraft/migrate/`, with `LINKCRAFT_MIGRATE_FROM_CPMCRAFT/_DATACRAFT` set in `.env` so
  LinkCraft takes them in once. `bundle.sh`, the Makefile and `.env.example` follow. The
  launcher's and App keys' texts name LinkCraft; `run_opcua_demo.py` starts `linkcraft` on 8140.

## 2026-10-20: module names (D10), `@processcraft/ui` 0.3.1, processcraft-sdk 0.8.2

- Owner decision: only ProcessCraft keeps the Craft brand. Modules are "ProcessCraft Link",
  "ProcessCraft Historian", "ProcessCraft Dashboards", "ProcessCraft Plant" (and Twin, Alarms,
  Models); inside the suite they read "Link", "Historian", ... Ids, repositories and prefixes stay.
- ui 0.3.1: `APP_NAMES` are the short names, `appFullName()`/`appShortName()`; a module's sidebar
  lockup is its short name over "ProcessCraft"; the Apps list shows short names.
- SDK 0.8.2: the suite table's names are the full names; `app.name` accepts "ProcessCraft <Name>"
  (the old `<Function>Craft` form still parses for the retired rows).
- ProcessCraft: `/api/v1/apps` names are the full names; the launcher and an asset's "Open in"
  links show the short ones; Historian messages no longer say HistCraft.

## 2026-10-20: setpoints hold to now (processcraft-sdk 0.8.3); histcraft-db on its own network

Two open items of the offline-install report (`install-e2e/REPORT.md`, items 1 and 5).

- SP traces ended early. Root cause: the grid's hold limit (10 × max(step, median spacing))
  judges an outage by a signal's own spacing, but a signal recorded on change has no meaningful
  spacing: PlantCraft's pre-written history wrote SP every 30 s, then live it writes SP only on
  change, so the hold ended 10 min after start. Fix (SDK 0.8.3, `contract.recorded_on_change`):
  text signals and tags whose last word is `SP`, `SETPOINT` or `MODE` hold with no limit, to
  their next sample, a null sample, `end` or now; sampled signals (PV, OP) keep the limit, so an
  outage still shows as a gap there (and as a 502 when the source cannot be read).
  `shape_values(..., signal_id=)` decides; ProcessCraft's local data layer and FakeProcessCraft
  both pass the id. Contract test `test_a_setpoint_recorded_on_change_holds_to_the_end_like_the_fake`
  (CSV with SP for 5 min then silent and a 30 min PV outage: ProcessCraft and the fake answer the
  same grid; before the fix SP went null from the 16th minute). Chosen over a heartbeat/last-read
  per signal (ProcessCraft has no collector; reads are on demand) and over source activity from
  sibling signals (a single-signal read has none). Open: HistCraft shapes its own grids
  (`HISTCRAFT_URL` mode) and should adopt the same rule; a source-supplied flag (OPC UA
  `Stepped`, PI `step`) could replace the name rule later.
- `histcraft-db` now sits on its own internal network `histdb` (`PROCESSCRAFT_HISTDB_SUBNET`,
  172.30.14.0/24) with `histcraft` only; it left `apps`. `tests/test_isolation.py`: expected
  networks, `histdb` internal and only for those two, plus a live check
  (`test_live_only_histcraft_reaches_its_database`). Checked live with the real images
  (compose project from `deploy/compose.yaml`, `docker compose run --no-deps`): histcraft
  reaches histcraft-db:5432; linkcraft, dashcraft and processcraft get no name, and by IP
  "Network is unreachable". Security guide and install-offline updated.

## 2026-10-20: ProcessCraft Twin (TwinCraft) in the offline deployment

- Compose service `twincraft` (profile `twincraft`, image `twincraft:${TWINCRAFT_VERSION}`,
  uid 10010, `/twin/` on 8120, `apps` network only, `data/twincraft:/data`, secret
  `twincraft_app_key`, `TWINCRAFT_CPUS`/`_MEMORY` 2/2g). Caddyfile routes `/twin/` to
  `twincraft:8120`. `install.sh`: `SUITE_APPS` row (key provisioned like LinkCraft and
  DashCraft), `--with-twincraft` (off by default; `--all-apps` includes it), CPU fitting,
  rollback tags. `bundle.sh`/Makefile: `TWINCRAFT_VERSION`, image saved (and its
  `/app/sbom.json` shipped) when `twincraft:<version>` exists. Docs and isolation tests follow.
- Built `twincraft:0.1.0` from twincraft PR #1 head `e8e1e16` (image
  `sha256:e473b32c78ed…`). Checked live: `install.sh --dev --with-twincraft --with-dashcraft`
  into a scratch folder (images `processcraft*:0.1.0-twin` from this tree) issued Twin's app key,
  every container healthy; `/twin/healthz` ok through the proxy; `/api/v1/apps` and the launcher
  list "ProcessCraft Twin"/"Twin"; Twin's own sidebar and DashCraft's list it under Apps.

## 2026-10-20: @processcraft/ui 0.3.2, the sidebar reordered (owner feedback)

- The fold button moved to the top of the sidebar, next to the brand (under the mark when
  folded; hidden in the phone drawer, which keeps its close button). The Apps list moved to
  the bottom block, above Help; the messages button and the user menu stay last, under a line.
- ProcessCraft is always the first entry of Apps (`appsWithPlatform`, `PLATFORM_APP` = `/`),
  marked current inside ProcessCraft, so every app links back to the platform; the current
  app's entry navigates in place. Folded, the Apps header is hidden and every app keeps its mark
  with its name as the tooltip.
- vitest: order (pages, Apps, ProcessCraft, the app, Help, Messages, user), the ProcessCraft
  entry, the fold button at the top and the folded state; e2e journey
  `test_the_sidebar_folds_from_the_top_and_lists_processcraft_above_help` (also the phone
  drawer). 0.3.2 tgz sha256
  `2b9816bce56ba8d90eafb94bfdc9e7a4487052cd31cd6540650a30e7ef46d60c`; LinkCraft, DashCraft,
  HistCraft re-vendored in their own PRs; TwinCraft's thread re-vendors it.

## 2026-10-20: demo story, public demo, suite journeys

- `processcraft demo seed` writes a demo story over every installed app on PlantCraft's plant
  (stdlib HTTP only, idempotent); `install.sh --public-demo` runs it and turns on the public demo
  (read-only visitor shown on the sign-in page, rate limit, language models off). Home page tour.
- Found by walking it end to end, fixed: the plant map's signals went to the local registry when
  HistCraft is the data layer (500 "Unknown source"), sources sent options HistCraft rejects, loop
  bindings lost their source, HistCraft crashed on text MODE values and read the source once per
  signal (LinkCraft's round timed out); HistCraft now backfills (its own PR), and PlantCraft
  0.4.1's sticky valves cycle (its own PR).
- `tests/e2e_suite`: 12 browser journeys across the suite on a live install
  (`make e2e-suite SUITE_URL=...`), not in GitHub CI.

## 2026-10-20 (one interface: shared UI, uniform grid, guided tour)

- `@processcraft/ui` 0.4.0: `base.css` (page parts and the 4-column `.pc-grid`), the guided tour,
  `createNav`, session, formats, building blocks and chart colours. Link, Historian, Dashboards
  and Twin import them instead of their own copies (their `styles.css` shrank to what is theirs).
- Home: two sections on the same 4-column grid (Your apps, Plant data); the old 7-step tour
  panel is replaced by the guided tour (Home, menu, Assets, FIC-1003 in the demo, Messages,
  Actions, Users for admins, the Apps). Each app opens its own tour on the first visit.
- Tests: platform tour journey (`tests/e2e`), Link's first-visit tour, suite journeys updated.

## 2026-10-20 (tour language)

- `@processcraft/ui` 0.5.0: the tour card has a language picker (English, Português (Brasil),
  Español, Français, Deutsch). It starts from the browser language and is remembered for every
  app (`processcraft-ui:tour-language`). Tour texts go through `tt()`; their translations live
  in `ui/src/tourTexts.ts`, keyed by the English text. Only the tours are translated, not the
  interface. `SuiteShell`'s `tour` may be a function, built again when the language changes.

## 2026-10-20 (secure by default: sign-in and per-route permissions)

- `processcraft --host <network address>` refuses to start with sign-in off and says how to turn
  it on; `--no-sign-in` serves anyway, for a trusted test network. 127.0.0.1 is unchanged. Docker
  installs already turn sign-in on.
- `tests/test_route_permissions.py` walks the 89 routes of the guarded routers: without a
  session each answers 401 (only `/healthz` is open), a viewer gets 403 on every write not
  marked `open_to`, an editor gets 403 on admin routes. A new route is covered automatically.
- Open: a test that no route writes to PI or OPC UA (G10).

## 2026-10-20 (the whole suite, source to walked demo: make e2e-bundle)

- `ci/e2e-bundle.sh` (`make e2e-bundle`): builds the app images from the checkouts next to this
  one (`*_SRC`), pulls HistCraft's PostgreSQL by digest, `make bundle`, checks SHA256SUMS and that
  every app is in it, installs into `dist/e2e-bundle/install` with `--all-apps --public-demo`,
  and runs `tests/e2e_suite` against the proxy's host name. `--skip-build`, `--down`.
- First run from every main (processcraft 2ff0f5f, linkcraft afc6ea6, dashcraft 8c09852,
  histcraft 1399d1a, twincraft d5b9751, plantcraft 82c1b00): build about 4.5 min, bundle 2 min,
  install 142 s with 9 containers healthy, 13 of 13 journeys.
- Found on the way: the Makefile still defaulted to PlantCraft 0.4.0 while the bundle, compose
  and installer use 0.4.1 (`make bundle` stopped at `plantcraft-image`); now 0.4.1. The proxy's
  certificate names the host (`PROCESSCRAFT_HOSTNAME`), not `localhost`.

## 2026-10-20 (read-only on plant systems is tested: G10 closed)

- `industrial_data/pi_web_api.py`: PI Web API goes through `ReadOnlySession`, a
  `requests.Session` that raises `PiError` for any verb but GET, HEAD and OPTIONS.
- `tests/test_read_only_plant.py`: the session refuses POST/PUT/PATCH/DELETE and still reads,
  `PiWebApiSource` uses it, and an AST walk of the plant-facing modules (`industrial_data/*`,
  `platform/plantmap.py`) fails on any OPC UA write, method call or node edit, or an HTTP write
  verb in a module that imports an HTTP client.

## 2026-10-21 (ProcessCraft Alarms in the suite)

- `alarmcraft` (ProcessCraft Alarms, `/alarm/`, port 8110, uid 10009) joins `deploy/compose.yaml`
  (profile `alarmcraft`, app key secret), the proxy, `install.sh --with-alarmcraft`, the bundle,
  `dev/suite-dev`, `ci/e2e-bundle.sh` and the Mac mini runners. The app lives in
  PlantCraft/alarmcraft.

## 2026-10-21 (the user's journey: a path on each first page, follow-up on each asset)

- `@processcraft/ui` 0.6.0 (`ui/src/Journey.tsx`): `JourneyPath` (four numbered steps on the
  page grid; done ones checked, the next one highlighted), `NextSteps` (where to go from a page,
  at its bottom) and `FollowUp` (the actions about an asset, read from `GET /api/v1/actions`,
  with a New action button).
- API v1: `GET /api/v1/actions?ref=asset:<id>` (read only; people and service tokens).
  `/api/home` gains `journey`: the apps' last run, enabled schedules, subjects by their worst
  current status per app, actions open, overdue and done.
- Home: the path Connect the data → Map the plant → Let the apps watch → Act and follow up
  replaces the Plant data cards; the tour points at it. The asset page shows its follow-up.
- Link: Today's routine on the Overview (signals → loops → the worst loop → actions), follow-up
  and next steps on the loop and signal pages. Historian: From connection to trend (source →
  points → archive → a dashboard).

## 2026-10-21 · Visual review fixes, @processcraft/ui 0.6.1

- Review of every screen (light/dark, desktop/phone, tours in 5 languages) on a clean install with
  the demo; findings in the project's `revisao-visual-2026-10-21/achados.md`.
- `@processcraft/ui` 0.6.1: a long pill in `.kpi-split` wraps inside its column; on a phone the
  top bar names the app and a panel header wraps its controls; `.more` (Show more under a table)
  is shared.
- Apps page uses the 4-column grid (Register external app spans 2). A scripted specialist names
  results in words (`Link · Loop health: attention, 54/100. ...`), never by method or kind ids.

## 2026-10-21 (apps end tokens at once: revocation list, processcraft-sdk 0.8.4)

- Recommendation 2 of the security audit: disabling a person, a new password, or a change of their
  level or applications used to leave their user token working in the apps (verified offline)
  for up to 15 minutes. `workspace_users.tokens_valid_after` (Unix seconds) is set on each of
  those; ProcessCraft refuses older tokens at once (`v1_caller`) and issues new ones with `iat`
  at least that. `GET /api/v1/auth/revoked` (public) lists the SHA-256 of those usernames and the
  app keys revoked in the last hour, only while a token from before could still be alive.
- `processcraft-sdk` 0.8.4: `TokenVerifier` reads the list at most every 10 s (2 s timeout) and
  refuses those tokens with 401; ProcessCraft down or older (404) keeps the last list.
  `contract.REVOKED_PATH`, `contract.subject_digest`; `FakeProcessCraft.revoke(username)` and
  `revoked_keys`.

## 2026-10-21 (Alarms in the demo story)

- `processcraft demo seed` sets up ProcessCraft Alarms: the suggested high and low alarm of every
  loop, five story alarms (PIC-1202 pressure high, FIC-1003 feed flow low, TIC-1209 outlet
  temperature high, FIC-1214 shelved for a positioner job, LIC-1218 out of service), and two
  days of their history replayed from the archive, acknowledged by the shift supervisor.
  Journey `test_06b` walks the summary, configuration, journal and performance.

## 2026-10-21 · ProcessCraft Models (modelcraft) in the suite, @processcraft/ui 0.6.2

- New app ProcessCraft Models (`modelcraft`, `/model/`, port 8130, uid 10011): a Modelica
  workbench (editor, library, diagram, check, simulate, plot, FMI 2/3 FMU export for Twin).
- Two containers: `modelcraft` (the app, on the internal apps network) and `modelcraft-runner`
  (OpenModelica 1.24.4 and the MSL 4.0.0, `network_mode: none`, read-only, noexec `/tmp`, 4 GB,
  2 CPUs, 512 processes). They share only `data/modelcraft-jobs`.
- compose, Caddy `/model/`, `install.sh --with-modelcraft`, bundle.sh (both images), .env.example,
  e2e-bundle.sh, ci/macmini, suite-dev; isolation tests check the runner has no network.
- `@processcraft/ui` 0.6.2: the Models tour texts in pt-BR, es, fr and de.

## 2026-10-21 (Models in the demo story, @processcraft/ui 0.6.3)

- `processcraft demo seed` fills ProcessCraft Models: the examples' own experiments simulated
  (and the tank loop again with a faster controller), `PlantCraftTwin.LoopProcess` fed by a loop
  twin's signals over the last hour and compared with its PV, and the Furnaces model exported as
  an FMI 2.0 FMU, uploaded to Twin and run as a second twin, "Furnaces (FMU from Models)".
  Journey `test_06c` walks the path, the runs and the twin.
- `@processcraft/ui` 0.6.3: the tour step of Models' "From a model to a twin" in five languages.

## 2026-10-21 (suite bench at plant scale)

- `make bench-suite` (`ci/bench/suite_bench.py`, stdlib only; `docs/bench/README.md`): measures an
  installed suite end to end (HistCraft archive write, plant map, API v1 reads, Link signal checks
  and rounds, DashCraft, TwinCraft) at `small`/`target`/`stress` scale, samples `docker stats`,
  saves `docs/bench/results/<host>-<time>-<scale>.{json,md}` and compares them (`--compare`).
- First target run (2,000 loops, 8,000 signals, 24 h; 4 CPUs, 15.7 GiB): archive write 27,782
  values/s, plant map import 17.4 s, 8,000 signals over 1 h in 43.9 s, Link checks 144.5 s, rounds
  about 135 s for 2,050 loops with none unread, 24 cards in 2.05 s, twins 100 % of cycles.
- Fixed here: the plant map refused signals of a source kept only in HistCraft (`plantmap.py`
  now asks HistCraft for its sources once per file). Fixed elsewhere: HistCraft flush time grew
  with uncompacted chunks (histcraft #16), steady signals archived only hourly (histcraft #21),
  one repeated timestamp failed a Link batch of 50 loops (linkcraft #27).
- Open: HistCraft batch reads cost about 2.5 ms per signal; histcraft-db peaks near its 1 GiB limit.

## 2026-10-21 (consolidation: one server skeleton, one interface client)

- processcraft-sdk 0.9.0: `processcraft_sdk.server` holds what every app server had copied
  (6 copies, 100 to 440 lines each): `store` (SQLite `Database`, `Store`, `recorded_at`), `files`
  (`AppFiles`: `app.toml`, `/api/meta`, help index and pages), `access` (`Access`: signed-in person,
  editor, `guarded` ProcessCraft reads) and `web` (`suite_api` and `mount`: `/healthz`, `/api/me`,
  `/api/meta`, `/api/help`, `/api/status`, the interface and sign-in redirects, public pages).
  `processcraft-app sbom` (`processcraft_sdk.sbom`) replaces each app's `deploy/sbom.py`.
- `@processcraft/ui` 0.7.0: `createApiClient` (token renewal, errors, the unauthorized event),
  `AppHelp` (an app's Help page), `SourcePicker`/`AssetSearch`/`SignalSearch` with their CSS in
  `base.css`. Apps keep only their endpoint lists.
- `dev/revendor`: puts this checkout's wheel and UI package in app repositories and moves every
  pin (pyproject, app.toml, Makefile, CI, Dockerfile, package.json and lock), with one
  `vendor/README.md` text for all.
- Tests (`docs/testing.md`, new): `processcraft_sdk.apptest` (offline, layers, image, API routes
  and hostile inputs as checks that return problems), `testplant` (PlantCraft's loops, users and
  assets for a `FakeProcessCraft`, was a copy in three apps), `e2e` (forked fake, app thread,
  Chromium, pages) and the `pytest_budget` plugin (`[tool.processcraft.tests]`: per-test, slow
  and whole-run budgets; `tests/e2e` and `tests/oracles` are slow by folder; `make test-fast`).
  `processcraft-app check` asks for the `test-fast` target.
- The app standard says so (section 3, the `/api/help` shapes in section 7).
- Docs: `AGENTS.md` is the suite's single source of rules (module names per D10, the module
  table moved to the new `docs/suite.md`, section 10 on a module's short `AGENTS.md`, template in
  `docs/templates/module-AGENTS.md`); every module's `AGENTS.md` is now about 80 lines instead of
  230. New `docs/how-we-build.md` (the platform's purpose, how we think, built with Claude Code in
  the open), `docs/claude-code.md` (the same commands everywhere, prompts that work),
  `docs/contributing-at-scale.md` (parallel work, roles, the GitHub organisation plan) and
  `docs/design/copy-prompt.md` (the "Copy as prompt" buttons, next step). README's module table
  is current, and every README has "How it is built".
- Found by the shared rules while moving the modules: Historian's image label disagreed with its
  `app.toml` (fixed there); Models' hostile test took 50 s (bodies and queries now paired,
  11 s); Historian's fast loop now runs without its real-socket tests (54 s to 10 s).

## 2026-10-22 (round 5, Assets and Setup)

- `processcraft/platform/assetfile.py` and `/api/asset-file`: the asset tree in five formats
  (JSON, xlsx, CSV, B2MML EquipmentInformation, PI AF XML), read into one document, reviewed row
  by row (create, update, unchanged, error; warnings for unknown attributes, tags and sources),
  applied in one go. B2MML levels map to types (Enterprise and Site fold into the plant); AF PI
  Point config strings become signal references, `%Element%` resolved, other substitutions
  skipped with a note. XML with DOCTYPE or entities is refused. Every export reads back with no
  change (`tests/test_asset_file.py`).
- Frontend: Assets › Import (file, "place under") and its review page (tree, editable name, type
  and parent, include, filters by status, relations), Export dialog (format, branch). Signals tab:
  "Also used in". Asset types: icon picker (`typeIcons.tsx`, process symbols drawn in-house) and
  attribute guide. Setup: tiles only; Configuration file; app keys explained; dialog margins.
- Demo: Riverbend Refinery (U-100, U-200, U-300, U-900), 14 areas, 21 equipment items, a
  transmitter and a valve per loop; the map has 139 assets, 205 signal rows, 99 relations. The
  seed renames the plant and retires the old simulated unit when it is empty.

## 2026-10-22 (round 5, Actions, people and language models)

- Actions: `follow_up_action_items` (text, owner, due date, done by and when); the history
  stores "verb:item" and translates when read. Mentions are found with `find_refs` over the
  description and comments and resolved like Messages' references; a user reference opens
  `/people/<username>`. The status id `cancelled` stays; its label is Archived.
- Users: `profile_json` (checked fields, e-mail format) and `app_roles_json`; `app_access` puts
  the role per app in the token, so `TokenVerifier.can_edit` in each app honours it without an
  SDK change. Changing the roles revokes the person's tokens.
- Language models: table `language_providers`, keys under `@provider:<id>` in the key file. The
  single connection of before is adopted as the provider `default` on start (its key copied),
  and `/api/language-model` reads and writes that provider, so older clients keep working.
  Removing a provider lists the specialists that used it; they answer from scripts until given
  another model.

## 2026-10-22 (groups of people and notifications)

- `processcraft/groups` (layer 1): `user_groups` and `user_group_members`; the coordinator is
  always a member and may change the members (`PUT /api/groups/<id>/members`), admins do the rest.
  Group references `#group:<id>` resolve to `/groups/<id>`.
- `processcraft/notify` (layer 2): `NotificationCenter.notify` expands `user:`/`group:` references,
  upserts a robot user per app (kind "system", like the watch module's), reuses one conversation per
  app and person and posts `**title**` plus text with `meta.kind = "notification"`. Emails go to
  `notification_outbox`; the `mail-outbox` thread flushes every 20 s, one digest per person, 20 per
  hour, six attempts. The SMTP password sits in `mail-secret.json` (mode 600). Apps only see
  usernames, never addresses.
- API v1 people, groups and notifications are open to service tokens; `notifications` refuses a
  person's token and any link outside the suite.

- 2026-10-22: Twin out of the suite (owner's choice): twincraft removed from compose, Caddyfile (/twin/ -> /link/algorithms), install.sh (FORMER_APPS twincraft:linkcraft:merge, --with-twincraft -> linkcraft), bundle.sh, .env.example, Makefile, CI (e2e-bundle, Mac mini runner), dev scripts, suite registries (APP_NAMES, SUITE_ORDER, release NAMES; FORMER_IDS linkcraft gains twincraft; package/SDK rows stay reserved), launcher; demo_seed: link_models (POST /link/api/models/examples), Models FMU published to Link as algorithm furnaces_fmu_from_models, Furnaces dashboard on linkcraft.out_model_deviation; bench twins step -> Link model algorithm; docs.

## 2026-10-22 (night): the suite's health as signals, the diagnostic bundle

- `processcraft.watch.recorder` (`HealthRecorder`, thread `health-signals`, 60 s): metrics.json,
  the backups and the drill, and every server's `/api/ops/metrics` (`ServerMetrics`: two-minute
  `ops` tokens to the Compose services of `SERVER_URLS`, `PROCESSCRAFT_OPS_URLS` over them; only
  services Docker runs) become `system:*` values, written through
  `HistCraftDataLayer.put_system` (Historian `POST /api/v1/data/system`, histcraft PR #36).
  Errors and warnings are per-minute rates of the counters (a restarted server counts from 0).
  Up to 24 h wait in memory per signal; a 4xx answer drops a signal's values, a 5xx keeps them.
- Diagnostic bundle: installer action `diagnostics` (in-process, beside any operation) writes
  `status/diagnostics/<id>.zip`, pruned after 24 h each metrics tick; logs come from
  `docker compose logs` (the installer cannot read the apps' own log files), settings from the
  installer's environment (`.env`), all text through `installer.redact`. `install.sh
  --diagnostics` runs `processcraft-installer diagnostics --out -`.
- Open: an app installed from a package has no latency signal (no internal URL known); the
  maintenance page and update from the interface.

- 2026-10-22 (security audit): `auth.users.is_email` (one plain address: no whitespace, control characters or `,;:<>()[]\\"`) checks profile emails, the SMTP sender and the test address; `notify.send_mail` refuses any other `To` with ValueError and puts the subject on one line; `flush` marks such an email `failed` and goes on (before, a ValueError escaped and every flush stopped at that person).

- 2026-10-22: several server processes and the separate collector. `PROCESSCRAFT_WORKERS` (auto: 2-4 with HISTCRAFT_URL, else 1), `processcraft.api.serve` is the image's command, `processcraft --workers`. `processcraft.ops.workers`: `startup.lock` around building the runtime and the app, `leader.lock` for the watch, outbox and clear_busy (`ApiRuntime._lead`), `first_only` for the Apps sync. 90 store blocks that write now use `Store._write()` (BEGIN IMMEDIATE) and every connection `isolation_level="IMMEDIATE"`; without it 4 processes x 50 read-then-write bumps lost updates (`tests/test_workers.py`). Asset types cache follows `asset_type_version`. `session.secret` created with O_EXCL. Compose: `histcraft-collector` service (histcraft collect, plant/demo/histdb, health = heartbeat), histcraft API `HISTCRAFT_COLLECTOR=off` (HistCraft #37 adds the one-collector lease). Test: 3 processes, 60 concurrent asset creations from 16 clients, one cookie, one leader.
- 2026-10-22: `ci/bench/workers_bench.py` (16 people at once: session, home, asset tree, one asset, a rename in ten; 2,000 assets; 4-CPU container, clients on the same CPUs): 1 process 52.7 req/s p50 264 ms p95 595 ms; 2 processes 103.3 req/s p50 67 ms p95 453 ms; 4 processes 177.6 req/s p50 63 ms p95 228 ms; 0 errors. The first run found the asset types' version asked on every read (an asset page read it 1,000 times: 450 ms); now at most once a second per process (`VERSION_CHECK_SECONDS`).
## 2026-10-23 (corporate sign-in)

- `processcraft/directory` (layer 2): LDAP or Active Directory (ldap3, LDAPS or StartTLS only,
  service account, user bind, groups by search or memberOf) and OIDC (code flow with PKCE, state
  and nonce in the session, ID token checked against the provider's JWKS in `directory/jose.py`).
  Group rules give level, apps, app roles and groups here; the account is created on the first
  sign-in with the directory's profile and kept up to date on each. Off by default;
  `PROCESSCRAFT_CORPORATE_LOGIN=off` forbids it. The environment's admin always signs in locally.
- `workspace_users` gains `auth_source` (local, ldap, oidc) and `external_id`; directory sessions
  carry `cpm_auth_at` and end after `session_hours` or when their method is turned off.
- Setup › Corporate sign-in with a test of each method and a rules check; the sign-in page shows
  the single sign-on button. 52 tests in memory, 4 live against OpenLDAP and Keycloak
  (`dev/corporate-login`). Open: SAML, RP-initiated logout, scheduled directory sync.

## 2026-10-23 (Mac mini deploys without dropping the suite)

- The suite went down for a few seconds at 09:58Z while in use: each merge to main recreated
  the processcraft and proxy containers. The proxy image got new layers on every build because
  `ARG REVISION`/`CREATED` came before its `RUN` (two builds of an unchanged proxy: different
  layers before, identical after moving the labels to the end).
- `suite-deploy` compares layers and start settings, not image ids, and leaves an unchanged
  container running; the deploy job runs it from the checkout. Caddy retries a refused upstream
  (60 s ProcessCraft, 15 s apps), checked with an upstream that starts 3 s late: 200, not 502.
- The first deploy after this change still recreates the proxy once (its old image has the old
  layers).
- 2026-10-23: histcraft-gateway (Telegraf 1.40.2 by digest) in compose, bundle.sh/install.sh pinned-image handling, isolation tests (HistCraft #55).
- 2026-10-23: @processcraft/ui 0.24.0, shared charts: `@processcraft/ui/plot` (Plot, TimeChart), PeriodPicker, useBrandTheme, chart helpers; unused frontend Plot.tsx removed.

## 2026-10-23 (Desk's Assistant)

- Assistant page in Desk (`/assistant`): many chats per person, reads listed under each answer,
  charts with the suite's TimeChart, references to the objects read. Own engine on the existing
  `ChatModel` (OpenAI-compatible or Anthropic), no LangChain: the tools are the MCP server's.
- Found while building it: API v1 `/results` and `/events` answer every app's records to anyone
  who may read the plant; the MCP server and the Assistant now filter by the apps the person may
  open (`mcp.only_apps`). API v1 itself is unchanged (apps read each other's results through it).
- `@processcraft/ui` 0.27.0: Ask the assistant opens Desk. Tests: 7 unit, 1 e2e (a stand-in
  OpenAI-compatible model draws a chart from the demo plant).
- Open: apps revendor ui 0.27.0, then remove `/api/v1/assistant` and the Messages specialist
  responder; the tour texts still mention specialists in Messages.

## 2026-10-24 (PlantCraft round 7)

- Owner's review of PlantCraft's admin pages, plan approved 10:07: ui 0.34.0 button and form
  standard (Heading actions gap, `FormSection`, `FormFooter`, `button-icon`, `button-ghost`,
  `button-danger`), applied to PlantCraft and revendored into the five apps and the template.
- Assets open to a level; Notebooks in Desk with six examples and a new tab; audit log explorer;
  corporate sign-in and language models redrawn; Undo last import (`AssetImportStore`, undo
  journal per import); Configuration file page removed; Operations split into Health, Backups
  and Updates.
- Tests: new unit tests for the examples, audit filters and volume, the undo; e2e for the
  examples tab, the import undo and the Administration pages.

## 2026-10-24 (Sidebar round 8, phase 1)

- Owner's ask (thread "Fixar barra lateral da suíte", plan approved 18:46): `@processcraft/ui`
  0.38.0. Four quick buttons of one size: Messages, Notifications (own count, own panel at
  `/messages/notifications?embed=1`, the section tabs hidden in the panel), Assistant (lucide
  Sparkles), work queues (the old line becomes an hourglass with a count; panel lists each app,
  Full page is PlantCraft's Executions). `SidePanel.tsx`: one panel frame, slides from under the
  sidebar, `usePresence` keeps it 160 ms to fold back, `claimPanel` keeps one open.
- Fold button beside the app's name; person's menu `position: fixed` beside the sidebar, 320 px.
- Next: phase 2 (assistant chats kept, list + new chat about the page), phase 3 (the platform
  frame that keeps the sidebar loaded and swaps only the app, apps in a same-origin iframe).
- Phase 2 in the same PR (ui-only, same version): the Assistant panel lists `GET /api/assistant`
  chats (8, newest first) under the page's tasks, resumes one (`GET /chats/{id}`), starts new
  chats with `keep: true`; "New chat" and "Full page" (`/assistant/{id}`) in the header.
- Phase 3, `@processcraft/ui` 0.39.0, the frame: Caddy's `@frame` matcher (document requests
  with the session cookie under an app prefix, not `/api/`, not `pc-frame=off`) goes to
  PlantCraft, whose SPA draws the sidebar and the app in an iframe (`AppFrames`, 3 kept loaded,
  4 s to say ready or `?pc-frame=off`). Inside, `SuiteShell` becomes `FramedShell` (no sidebar,
  reports nav/heading/path, obeys go/assistant/tour/close-panels). Same-origin `postMessage`
  only; icons cleaned by an SVG allow-list. `tests/e2e/test_frame.py` drives a stand-in app.
- Found on the way: an inline iframe `ref` runs again on every render; the frame's ready flags
  are cleared in an effect over the loaded list instead.

## 2026-10-24 (journey round: clean install of the 0.4.0 candidate)

- Clean install of main (`ci/e2e-bundle.sh`, every app at 0.4.0) walked by the suite journeys: 12/15
  at first. Fixed: the seed stopped at Alarms' PIC-1202 rule (suggestions name the loop in
  `assets` since alarmcraft 0.4.0) and left three of the five rules out; PIC-1202's limit now comes
  from the archived minutes the replay reads (it replayed 0 occurrences, now 4); the visitor's
  Desk to-dos and meeting are written into Desk's store on a public demo (its API refuses the
  visitor). Journeys follow round 7 (Link and Models overviews). 15/15 after.

## 2026-10-25 (Alarms round 8, phase 1: the event as a contract)

- Owner's ask (thread "Planejar Alarms rodada 8", plan approved 00:22): a well-defined event
  every app is wired to, even those that write none yet, and Alarms the only one that judges
  them. Found on main 9d2403c: severity hidden in `payload`, no way to say a condition opened or
  closed, only Link wrote app events, Link's manifest declared 2 of the 6 it writes.
- processcraft-sdk 0.26.0 (version to confirm at merge): `EventIn` gains `severity`, `key`,
  `phase`, `category`; `processcraft_sdk.events` (`EventSpec`, `EventRule`, `EventCatalog`,
  `event_fields`, the one rule that fills them); `[[publishes.events]]` tables in `app.toml`;
  `client.put_event_catalog` / `event_catalog` / `events(key=)`; the server sends the catalog at
  start; `FakeProcessCraft` refuses undeclared kinds once an app declared a catalog.
- PlantCraft: four columns on `platform_events` (guarded `ALTER TABLE`), `event_catalogs`,
  `PUT/GET /api/v1/events/catalog`, PlantCraft's own catalog (`processcraft/events/catalog.py`:
  activity plus the suite watch's incidents as interval events: `processcraft.service.down`,
  `queue.stuck`, `disk.low`, `disk.filling`, `backup.missing`, `drill.failed`,
  `installer.silent`, `docker.down`, and `update.finished`). The watch writes them (start when
  it opens an incident, end when it closes), so the Historian's collector stopping reaches
  Alarms although the Historian has no app key. Their suggested rules stay off: the watch
  already tells the administrators, and it speaks even when Alarms is the app down.
- Next: phase 2, each app's catalog (Historian collector/source/point no-data, Link's six with
  key and phase, Models runs, View and Desk empty), then Alarms (catalog in the rule editor,
  conditions by key, delivery by priority, flood mode, chattering, stale, dependency inhibition,
  alarm philosophy, suggested rules).

## 2026-10-25 (sidebar and page top, round 8, ui 0.41.0)

- The owner's review of the persistent sidebar: fold button back at the bottom, last of the quick
  buttons; the list of apps floats (the sidebar scrolled sideways: the list was 236 px inside 224);
  the person's menu arrow points to the side. The four quick panels share one width and header,
  swap in place (no fold-back and slide-in between two), close on a second click (Messages and
  Notifications only opened) and on going to another page or app, inside the frame too (the app's
  assistant learns `still` and `close-panels` from the frame). The queues' button: turning while
  work runs, green after it finished well, red after a failure until seen. The Assistant's panel
  points an administrator to Setup › Language models (`can_set_up`).
- The page's top is the title and the buttons in one band (`Heading`, `AppOverview`, `base.css`
  hides eyebrows, lines under titles and breadcrumbs written by hand; `pc-heading-keep` keeps
  Desk's date and an action's status). Open: removing the now hidden texts from the pages, app by app.

## 2026-10-25 (night refactor, behaviour unchanged)

- Dead code and repeated helpers: PlantCraft's search uses the SDK's `matches`/`rank` (its own
  copies left); unused `UPLOAD_CHUNK`, `REFERS_BACK`, `PROVIDER_ID` removed. View keeps one
  `finite_number` (was `_number` twice) and drops the unused `ContextOption`, `ALL_LABEL`. The
  Simulator's two nearest-centroid baselines share `_fit_centroids` (same reports, checked
  against the old code on synthetic samples).

## 2026-10-25 (platform tests: faster, and on the suite's budget)

- PlantCraft's tests took 13 min; now about 9 on the same 4-core container. Two causes: the plant
  map template's OPC UA source (10.0.0.15) was dialled for real, twice 15 s per preview
  (`test_export_has_a_sheet_per_type...` 91 s -> 1 s), and every test hashed passwords with the
  product's Argon2id (64 MiB). `tests/conftest.py` now refuses any connection outside loopback at
  once and hashes with the cheapest Argon2id; `test_security.py` still holds the product's
  parameters. The platform gets `make test-fast` (AGENTS.md named it, the Makefile lacked it) and
  the SDK's time budget (`[tool.processcraft.tests]`: 10 s a test, 1200 s a run); the hostile
  inputs and the shipped map import are marked slow.

## 2026-10-25 (Alarms round 8, conditions of an app without an app key)

- The Historian has no app key, so it cannot post events. SDK 0.28.0: `ops.report_conditions`
  puts the app's open conditions (`events.Condition`) and its catalog in `GET /api/ops/metrics`;
  the health recorder hands them each minute to `processcraft.events.conditions.ConditionRelay`,
  which writes start and end in the app's name and stores what is open (`relayed_conditions`).
  An app that did not answer keeps its conditions open.
- The Historian declares `collector.stalled`, `source.disconnected` and `point.no_data` and
  reports them (`histcraft.conditions`); Alarms holds "no data" while the collector is stalled
  or the alarm's source is disconnected. Every app on SDK 0.28.

## 2026-10-25 (limits for each person on API v1, Notebooks phase 1)

- Owner plan "Notebooks no navegador e no computador" (approved 10:40), phase 1: a person's
  notebooks, scripts and assistants are limited (120 requests a minute, 2 reads at once by
  default; Setup › Notebooks). `processcraft/auth/usage.py` counts in the database (every
  process shares it); `processcraft/api/usage.py` decides what counts: access tokens always,
  browser series reads only when the proxy marks them (`X-PlantCraft-Edge` in the Caddyfile).
  Apps never count. `plantcraft-notebook` waits on 429. Tests: `tests/test_usage_limits.py`.
- Open: the Historian's query time limit (`HISTCRAFT_QUERY_TIMEOUT`, Historian thread);
  phases 2 (new Notebooks page, install in the browser, cache) and 3 (kit for the computer).

## 2026-10-25 (Notebooks phase 2: run in the browser, installed once)

- Desk › Notebooks: two blocks (browser, computer); "Install Python in this browser" fetches the
  build's files once (measured in headless Chromium against a local server: install 15 s,
  kernel ready about 10 s after). Files under `/notebooks/lite/v/<build>/`, `immutable` for a
  year; the build keeps `contentsStorageName` at the first builds' name, so edits survive
  updates. Folders Examples and My notebooks in JupyterLab; the page's lists are gone.
- Open: phase 3, the kit for the computer (Windows, macOS, Linux).

## 2026-10-25 (Notebooks phase 3: the kit for people's computers)

- `notebooks/kit/build_kit.py` builds the three kits on one Linux machine in about two minutes:
  python-build-standalone 3.12.12 (stripped: the unstripped Linux build carried 400 MB of
  symbols), wheels for each system by `uv pip install --target --python-platform`, all hashed.
  Measured zips: Windows 148 MB, macOS 128 MB, Linux 178 MB. Links stay links in the zip.
- Checked here end to end with the real Linux kit (`tests/e2e/test_notebook_kit.py`): download
  with the address added, token in a 0600 file (no vault in a container), sync of Examples and
  My notebooks, a series read in the kit's Python, JupyterLab answering on 127.0.0.1. Windows and
  macOS kits were checked for their layout only; they need a run on each system.
- Personalised download: two entries appended to the zip as it streams (local records, then the
  old central directory and the new entries' records, offsets moved), no copy of the kit.
- Not done: signed installers (D1, later), saving the computer's notebooks back to PlantCraft.
## 2026-10-25 (files written whole, never readable by others on the way)

- `processcraft.files.write_atomic` (layer 0, standard library): a hidden unique temporary file
  created with its final mode, then renamed. Five copies of write-then-chmod-then-rename move to
  it: the SMTP password, the people's model keys, the directory's bind secrets, its CA file and
  the app requests the installer watches. Before, a secret sat at the umask's mode (0644) between
  the write and the chmod, and the directory's fixed `.tmp` name could be shared by two workers.
  The installer image's own writers (`apps/installer.py`, `apps/operations.py`, `ops/snapshot.py`)
  stay as they are: that image copies only its own files.

## 2026-10-25 (owner review, round 9: Link and Models)

- ui 0.47.0: the assistant's button beside every page title (`AssistantTitleButton` in
  `Heading`), `VersionsTab` (About on top, then the versions), and a read-only diagram that shows
  only the tools that work there, without the "valid" banner.
- Link blocks and algorithms are made, edited, tested and versioned the same way: New with Import
  or Fill in the form, Edit saves a new version, a Versions tab instead of the right column, a
  Test tab that asks for the asset first, then one row per point. New algorithm page; an
  algorithm's parameters change without its diagram; algorithm files (`plantcraft-algorithm/1`).
- Link Executions list every output of the latest result again (a loop's methods, a signal's
  checks, an algorithm's outputs); an asset schedule's charts read the series it records under
  its own key. The schedule form is numbered, its preview sits under When.
- Models: New model page (Import a `.mo` file, `POST /api/models/import`, or the form), Versions
  tabs on models and blocks, "Save as version N", and an example study queued once at the first
  start (`MODELCRAFT_EXAMPLE_STUDY`).
- Open (owner's review on 2026-10-26): model algorithms in Link ("FMU from models", legacy
  inputs) and assembling algorithms from blocks in the editor.

## 2026-10-26 (night: small leftovers and page load)

- Pages load lazily in Link, View, Alarms, Historian and Models (`React.lazy` per page): opening
  an app no longer downloads Plotly, the code editor and the diagram editor. Link's first page
  went from 2.8 MB of JavaScript to 0.4 MB. The proxy keeps the hashed built files a year
  (`Cache-Control: immutable`, only on a 200), so the frame stops revalidating them at each app.
- Link: the "worst results" widget ranks by the result (lowest health, quality or score first)
  and writes its measure ("Health 30 %") instead of a bare number; a schedule's "Last" counts a
  "Run now" (`last_manual_at`, shown as "Run by hand"); the stall warning still counts from the
  calendar's own last slot.
- Platform: an asset's description shows under its title again (`pc-heading-keep`); the
  assistant's New chat is disabled while the language model is off; the user menu falls back to
  the access level when the person has no job role; progress bars have an accessible name
  (Models, Actions, Notebooks).
- Historian: an imported or app-written point reads "Imported" / "Written by its app" on its
  page and in the statuses widget, not "Collecting".
- Open: the `PlantCraftTwin` Modelica package and FMU names (renaming needs the FMUs exported
  again with OpenModelica and Link's saved algorithms migrated).

## 2026-10-26 (Alarms round 11, phase 1: platform)

- Events: only changes are written (repeated starts and ends of nothing dropped, `repeated` in
  the answer), 1000 events per hour per app with one `processcraft.events.flood` per hour,
  `EventStore.count_since` and `about`, index on `(source, at)`.
- Link: `output.status` removed; `run.failed` once per run (a 500-asset run failing was 500
  events), `schedule.stalled` once per schedule. Historian: point conditions up to 1990.
- Explorer: `GET /api/v1/explore` + `processcraft_sdk.explore` + ui `Explorer`; 5 contract
  tests. `processcraft_sdk.sandbox` (22 tests), Link's sandbox generalized.
- SDK 0.48.0, ui 0.56.0. Next: phase 2, the Alarms engine (one diagram per rule).

## 2026-10-26 (Alarms round 11, phase 4: outputs and pages)

- Each rule has outputs: Alarms (always), Dashboards (`dashboards`, on; off leaves the asset's
  `alarm_state` and the widgets out), Messages (its notify) and Email, shown only when the new
  `GET /api/v1/notifications` says PlantCraft can send it (SDK 0.50.0, read once a minute).
- Pages per the plan's section 9: `/alarms`, `/events` (Received, Open now, Catalog), `/rules`
  with `/silences`, `/history` with Journal, Sent, Performance and Targets (the philosophy).
  The older paths' redirects, the notification policies (table dropped by a migration) and the
  default policy are gone; every alarm has a rule.
- Bug found by the browser journeys: choosing Assets or Executions in Where with nothing named
  yet fell back to "Only the values named"; the choice is now kept apart from the fields.
- A rule started from an opened condition (`finding.opened`) hears its close as well.

## 2026-10-26 (Alarms round 11, phases 2 and 3: the engine)

- A rule is one diagram of alarm blocks (`alarmcraft.alarms.blocks`, 15 blocks with their docs);
  the Simple form writes it (`alarms.simple`), Blocks draws it, Python is one block run in the
  SDK's isolated area at most once a minute (administrators only write code).
- `engine.run` judges a diagram on one subject: samples per signal after the last seen (a
  late point from an app counts once), events in order, and the moments a timer elapses
  between them (for at least, clear after, a count's window), so Test over days and the cycle
  agree. Subjects: assets, branches, types, executions (schedule `subjects`, SDK 0.49.0),
  anywhere (made when an event names the asset), or one alarm per rule (members kept).
- Old rules become Simple rules once (`rules-as-diagrams`); Suggested limits and verdicts gone.
- Next: the editors on screen (Simple sentence, Blocks, Python, Test, Explorer pickers).

## 2026-10-27 (requirements from measured sizes)

- `docs/requirements.md`: minimum, recommended and large-scale infrastructure, compute workers,
  Notebooks computers and disk growth, each number with its machine and date; linked from
  install.md and install-offline.md. Measured: repository 88 MB on GitHub (49 MB of it four
  wheels committed by mistake, removed by the cleanup thread), images of one version about
  7.6 GB loaded, kits 124 to 173 MB to download and 374 to 537 MB installed, suite idle 4.5 GB
  (Windows) to 7.0 GB (Mac mini, two workers), a worker 0.67 GB.
- Lint fails on any tracked file over 2 MB.
- Open: the Historian's chunks table on the Mac mini holds 1.6 GB for 290 MB of data (space not
  reused); the load test fills the people-at-once numbers.

## 2026-10-27 (public demo visits)

- "Enter the demo" (`POST /api/demo/enter`): places in the database (`demo_visits`, `demo_line`),
  5 at once, 15 minutes each, a line with a ticket, idle 3 min gives way only to someone waiting,
  2 places per address. Visits share the `demo` account; the session's `demo_visit` must still hold
  a place. Tokens of a visit live 2 min (frame renews every 30 s with the heartbeat) and carry the
  `demo` claim.
- SDK 0.71.0: `/api/me` says `can_edit` to a visit (editors shown), `EditorUser` refuses with
  "nothing is saved"; `DemoVisitLimit` in `web.mount` holds a visit to 2 requests in flight per
  app and all visits to 4. All six apps revendored.
- The rate limit and the API v1 series budget count per visit, not per address or account.
- Open: the multi-user load test sets the real numbers (seats, query caps).
## 2026-10-27 (PlantCraft's Overview: the installation's health)

- /admin's default board is Apps online and Data connections (6 x 3), System and Recent changes
  (6 x 2); the apps' widgets, Needs attention, Open actions, Worst first and Your apps stay in the
  catalog. Saved boards are kept (`/api/home/layout` is untouched; the default applies while it
  is null). The board waits for the apps' catalogs only when it shows an app's widget, and draws
  nothing until the person's board is read (no flash of the default).
- System: `GET /api/home/system` (new `home_system` router) reads `rt.watch.overview()` and
  `rt.operations.overview()`; disk state from the watch's checks and `DISK_LOW_PCT`/`DISK_OK_PCT`
  (the data folder's disk when the installer writes no metrics), last backup, version and last
  update, people signed in today (`AuditStore.signed_in`). Disk, backup and sign-ins only for
  administrators. Recent changes reads `/api/audit?kind=changes` (administrators only, so the
  widget is offered only to them).
- Open: no "update waiting" fact (the suite never checks for updates: offline by rule); creating
  a person is not in the audit log (users router).
- 2026-10-27: `dev/sdk-version` takes the SDK/ui version at merge: merges origin/main (vendored files and version-only conflicts from main), main's next minor for each changed package, `make sdk-wheel ui-package`, `dev/revendor --all` (`--sdk-only` when ui/ is unchanged) and the platform's `frontend/`, renames "SDK x" in the branch's added Markdown lines, commits. `--check` in `dev/ship` and in Lint (`--base HEAD^1` of the PR merge commit, fetch-depth 2). Tested in a scratch clone: two branches both on SDK 0.72.0 -> 0.73.0; ui 0.73.0 twice -> 0.74.0 with a real conflict stopping first.

## 2026-10-27 (Analytics memory after the soak)

- The 3-hour soak's climb (Analytics 1.7 to 2.4 GB, PlantCraft 1.0 to 1.4 GB) is not a leak.
  On a cloud stack at target scale (2,050 loops, 8,000 signals) a `malloc_trim(0)` through gdb
  gave back 22 % of the Analytics engine (1,115 to 873 MB anon), 20 % of its server and 41 % of
  PlantCraft's four API workers (1,044 to 617 MB): glibc kept the pages each round freed.
- About 370 MB of what `docker stats` showed for Analytics was the page cache of its database
  (`total_active_file`), which grows with `run_samples` and the kernel reclaims under pressure.
- `processcraft_sdk.server.memory`: `release()` and `Releaser` (every 60 s); `web.mount` and
  PlantCraft's lifespan run one, Analytics' engine runs one and releases after each round,
  replay and asset run. Same bench again with the fix: engine 897 MB, PlantCraft workers 628 MB.
- Open: `run_samples` keeps 10 runs per loop (1.1 GB at 2,050 loops); keep fewer for rounds.

## 2026-10-27 (the public demo and the site on a cloud VM)

- `deploy/cloud/`: `push-to-vm.sh` copies main (git archive) to a VM and runs `vm.sh`: Docker,
  cloudflared, the site's server (systemd, 127.0.0.1:8090), the suite built there
  (`ci/e2e-bundle.sh --bundle-only`, new) and installed with `--public-demo` on 127.0.0.1:443.
  A Cloudflare Tunnel is the only way in; docs/public-demo.md, "On a cloud VM".
- Proxy: `PROCESSCRAFT_TRUSTED_PROXIES` (empty by default) trusts `CF-Connecting-IP` /
  `X-Forwarded-For` from those addresses; the edge snippet now sends `X-Forwarded-For
  {client_ip}`. Without it every visitor behind a tunnel shared one address (two demo places and
  one rate limit for everyone). Site chat: `SITE_TRUST_PROXY=cloudflare`.
- Site: `build.py --demo-url --contact --noindex`, privacy.html, robots.txt,
  .well-known/security.txt; facts.md now says the public demo exists (simulated data only).
- Checked with Caddy 2.11.2 (the pinned image): `caddy validate` with and without the setting;
  an echo upstream sees `X-Forwarded-For` = the CF-Connecting-IP only from the trusted address,
  the connection's own address from any other, and the connection's own with nothing trusted.

## 2026-10-27 (Desk final review: the visitor's own actions)

- Demo seed: three open actions owned by the visitor `demo` (in progress, open, blocked), each an
  operator's part in a story already seeded (FIC-1003 valve test, PIC-1202 alarm count, TT-1209
  portable reading). Desk's "My actions" was empty for whoever entered the demo. Mac mini: `demo seed`.

## 2026-10-27 (Desk final review: menu order and the Python icon)

- Desk menu: Today, Actions, Calendar, To-do, Notes, Team (when on), Notebooks last (owner).
- `PythonMark` in `@plantcraft/ui` (Simple Icons' Python logo, CC0, one colour): Notebooks in
  the menu and Historian's "Open in a notebook". TRADEMARKS.md names the PSF's mark.

## 2026-10-27 (Desk final review: a shorter Notebooks page)

- Notebooks: two cards (Run in the browser / Run on your computer, one line each) as tabs; the
  chosen one's panel below, remembered in localStorage. The red limits list is a folded "Limits of
  the browser"; the kit is three cards (install, connection code of #370, open) with OS notes and
  "Use my own Python" folded. e2e test_notebook_kit now creates a connection code (it still looked
  for the "Connect this computer" button #370 removed).
