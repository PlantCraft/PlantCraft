# Status

> **Updated:** 2026-10-27 (cleanup before the load test)

## Current focus

Version 0.4.0 (signed bundles for amd64 and arm64, 2026-10-25), with no launch date: the owner
reviews the suite app by app in rounds, and the platform is readied for scale (paged lists, app
permissions, numbered migrations, a frozen API v1 contract, compute workers). Nothing is
published yet.

PlantCraft is the central app of the suite: people, groups, sign-in, access per app, app keys,
tokens, API v1, the audit log, data sources, signals, assets and asset types, the plant map,
Desk (Today, actions, calendar, notebooks, to-do, notes), messages, notifications, the
assistant, Settings, Compute, System health, Backups and Updates. The apps (Analytics,
Historian, View, Alarms, Models, Documents) and the Simulator live in this repository
(`apps/`, `simulator/`), each with its own image, and reach it through API v1 only
([suite.md](suite.md)). The day-by-day history is in [devlog.md](devlog.md).

## Contract changes

- 2026-10-28 (person's marks): `GET /api/v1/inbox` counts in `unread_messages` the conversations the
  person marked unread again, and on a public demo reads the visit's own marks (its token's `demo`
  claim). Same fields; no app change.
- 2026-10-27 (rename to PlantCraft, step 2, `plantcraft-sdk` 0.75.0, `@plantcraft/ui` 0.74.0):
  the SDK distribution, import and command are `plantcraft-sdk`, `plantcraft_sdk` and
  `plantcraft-app`; the fake and the client are `FakePlantCraft`, `PlantCraftClient` and
  `PlantCraftError`; the ui package is `@plantcraft/ui`; settings are `PLANTCRAFT_*`. Compatible
  for running installations: `PROCESSCRAFT_*` settings are copied to the new names when a process
  starts (`plantcraft_sdk.settings_compat`), and the SDK wheel keeps a `processcraft_sdk` package
  that is `plantcraft_sdk` (so `python -m processcraft_sdk.compute` in an older compose file runs).
  App ids, routes, images, the platform's package `processcraft` and API v1 are unchanged.
- 2026-10-27 (rename to PlantCraft, step 1, `processcraft-sdk` 0.74.0): the Simulator's suite id,
  package, command, image and compose service are `simcraft` (were `plantcraft`, now the
  platform's name); its variables are `SIMCRAFT_*`. The data source id `plantcraft`, the OPC UA
  endpoint `opc.tcp://plantcraft:4840/plantcraft/` (the service keeps `plantcraft` as a host
  alias) and the namespace `urn:processcraft:plantcraft` are unchanged. `install.sh` moves
  `data/plantcraft` to `data/simcraft` and `PLANTCRAFT_VERSION` to `SIMCRAFT_VERSION` on upgrade.
- 2026-10-27 (pre-retrieval, `processcraft-sdk` 0.73.0): additive. `[[contributes.assistant.tools]]`
  gains the optional `prefetch` (the key of one of the tool's text arguments): PlantCraft calls
  the tool with each question before the model answers ([assistant.md](assistant.md), "Tools
  the apps add"). Documents' `search_documents` sets it; an app on an older SDK cannot declare it.
- 2026-10-27 (asset scope in the apps, `processcraft-sdk` 0.66.0): additive. New module
  `processcraft_sdk.asset_scope` (`AssetScope`, `scope_of`, `scope_for`, `limited`) and
  `PlatformRuntime.asset_scope(user)` / `claims_scope(claims, token)`; the fake PlantCraft
  (`processcraft_sdk.testing`) applies a token's `assets` claim to assets, signals and series.
  Historian, View, Analytics, Alarms, Models and Documents keep a limited person to their part.
- 2026-10-27 (decision D2, asset scope, [asset-scope.md](asset-scope.md)): a person's token
  gains the optional claim `assets` (the roots of the asset tree they see; absent: the whole
  plant). API v1 answers a person only about those assets: assets, signals, series, values,
  results, events, runs and actions out of it are left out of lists and answer 404. Additive:
  `PUT /api/users/{username}` and the group routes take `asset_scope`. Apps' own tokens read
  everything, as before.
- 2026-10-27 (a new plant's first steps, D5 F4): additive, `processcraft-sdk` 0.65.0. A new
  `[[contributes.start]]` table and feature `start`; an app serves `POST <prefix>api/start/<id>`
  (`StartIn` in, `StartOut` out), called as the person. PlantCraft's own routes gain
  `GET /api/asset-file/start` and `POST /api/asset-file/start/{app}/{step_id}` (administrators).
  Historian, Analytics, Alarms and View declare one step each. API v1 does not change.
- 2026-10-27 (draft a new plant, owner decision D5): additive. Documents declares a third
  assistant tool, `find_tags(tags)`; PlantCraft's own routes gain `POST /api/asset-file/draft`,
  `POST /api/asset-file/draft/tags` and `GET /api/asset-file/draft/options` (administrators), and
  Setup › Language models a platform use `plant-draft`. API v1 does not change.
- 2026-10-26 (security audit, recommendations 2 to 5): API v1, `POST /api/v1/llm/{use}` needs
  the new permission `write.llm` (an app that declared its `[permissions]` without it gets 403);
  a use of an app outside `PROCESSCRAFT_APPS` starts off. `release.json` gains `permissions`
  (each suite app's, from its image's `app.toml`), which PlantCraft holds suite apps to.
  processcraft-sdk 0.59.0 (`WRITE_SCOPES["llm"]`, `CLIENT_SCOPES["llm"]`).
- 2026-10-26 (Queue panel, the overview first): `@processcraft/ui` 0.66.0: `jobsByApp` and
  `AppJobs` replace `mergeJobs` (the panel lists the apps, an app opened lists its work).
- 2026-10-26 (quick-access protocol, phase 2): API v1, additive: `GET /api/v1/queue` (a person
  only) answers `{"me", "mine", "running"}` for the Queue panel. processcraft-sdk 0.54.0
  (`PERSON_ONLY`), `@processcraft/ui` 0.65.0 (`useSuiteJobs`, `mergeJobs`, `queueJob`; an app's
  `GET /api/queue` may add `items` and `url`).
- 2026-10-26 (compute workers, phase 1): API v1, additive: `/api/v1/compute/...` (tasks for the
  compute workers, an app's token with `write.compute`, a new permission); workers' routes
  `/api/compute-worker/...` and administrators' `/api/compute`. processcraft-sdk 0.55.0
  (`processcraft_sdk.compute`). docs/compute.md.
- 2026-10-26 (quick-access protocol, phase 1, docs/quick-access.md): API v1, additive:
  notification `actions` take `method` (`GET` default, `POST` runs the call in the sending app,
  under its own prefix); `POST /api/v1/notifications/resolve` `{"key", "note"}` settles a thread
  for everyone; `GET /api/v1/inbox` answers `urgent_notification`; runs take and answer `by`,
  `progress`, `step`, `cancel`, `GET /api/v1/runs?by=`; PlantCraft notifies the starter of a run
  that fails or ends after a minute. processcraft-sdk 0.53.0 (`client.resolve_notification`,
  `runs(by=)`), `@processcraft/ui` 0.63.0 (`UrgentToast`, `runNoticeAction`).
- 2026-10-26 (Alarms round 11, phase 4): API v1, additive: `GET /api/v1/notifications`
  answers `{"email": bool}`, whether the platform can send email now; Alarms offers a rule's
  email only then. processcraft-sdk 0.51.0 (`client.notification_settings()`).
- 2026-10-26 (Alarms round 11, phases 2 and 3): API v1, additive: `PUT /api/v1/schedules`
  takes `subjects` (what each schedule runs on, `asset:`/`signal:` refs, up to 2000) and
  `GET /api/v1/schedules` answers them; Link publishes them, Alarms covers an execution's
  assets. processcraft-sdk 0.51.0.
- 2026-10-26 (Alarms round 11, phase 1): API v1, additive: `POST /api/v1/events` writes changes
  only (a repeated start or an end of nothing is answered, counted in `repeated`, not written)
  and holds each app to 1000 events per hour (429, `processcraft.events.flood`); new
  `GET /api/v1/explore`. Link's `output.status` event is removed. processcraft-sdk 0.51.0
  (`client.explore`, `processcraft_sdk.explore`, `processcraft_sdk.sandbox`).
- 2026-10-25 (scale review E2, E4): API v1, additive: `GET /api/v1/signals` and
  `GET /api/v1/assets` take `limit` and `cursor` and answer `ETag` (304 on `If-None-Match`);
  an app's service token is held to its `[permissions]` (`processcraft_sdk.scopes`, 403);
  `PUT /api/v1/contributions` takes `permissions`; `POST /api/apps/external` takes
  `permissions`. processcraft-sdk 0.42.0.
- 2026-10-25 (scale review E11): API v1, additive: `GET /api/v1/installation` adds `id`, the
  installation's UUID for good (`PROCESSCRAFT_INSTALLATION_ID`); backup manifests add
  `installation_id`. processcraft-sdk 0.42.0 `client.installation_id()`.
- 2026-10-25 (Overviews as widget boards): widget contract v1, additive: the catalog's entries
  add `kind`, `pick` and `multiple`; data shapes add `split`, `series` and `facts`; a `pick`
  widget answers `GET <prefix>api/widgets/<id>/options` and takes `?item=`. `[[contributes.widgets]]`
  adds the same three fields (SDK 0.41.0); apps declare their widgets there (docs/widgets.md).
- 2026-10-25 (assistant plan F0): deployment, additive: service `llm-egress` (uid 10014, port
  3128 on the new internal network `llm`, its own route out `egress`), PlantCraft joins `llm`
  and mounts `data/egress`; `.env` adds `PLANTCRAFT_LLM`, `PROCESSCRAFT_LLM_DNS`,
  `PROCESSCRAFT_LLM_NO_PROXY`, `PROCESSCRAFT_LLM_SUBNET`, `PROCESSCRAFT_EGRESS_SUBNET`. Interface
  API, additive: `GET /api/language-models` adds `egress` (hosts allowed, whether it answers).
  Errors of a model service now say what to fix (401 key, 404 model or address, 429 limit,
  name not resolved).
- 2026-10-25 (contracts P2): API v1, additive: `PUT /api/v1/calendar/{feed}`,
  `POST /api/v1/todos`, `GET /api/v1/todos`, `POST /api/v1/todos/close` (an app's calendar
  feeds and to-dos in Desk, declared in `[[contributes.calendar]]` and `[[contributes.todo]]`);
  interface API, additive: `GET /api/desk/calendar` adds `feeds` and `feed` events,
  `GET /api/desk/todos` adds `counts.apps`, `app_todos` and `?view=apps`,
  `POST /api/desk/app-todos/{app}/{key}`; `GET /api/v1/contributions/settings` (an app's
  installation settings) and interface `GET /api/setup/apps`, `PUT /api/setup/apps/{app}`
  (Settings › Apps). processcraft-sdk 0.33.0.
- 2026-10-25: API v1, additive (SDK 0.32.0): `POST /api/v1/llm/{use}`, an app writes with the
  model Settings gives one of its `[[contributes.llm]]` uses. Interface API: `GET
  /api/language-models` lists the apps' uses with `reads` and `app`.
- 2026-10-25 ("Padronizar contratos entre apps e PlantCraft"): API v1, additive:
  `PUT /api/v1/contributions` and `GET /api/v1/contributions` (what each app adds, app-standard
  section 4b); `GET /api/v1/installation` adds `features`; `GET /api/ops/metrics` may carry
  `contributions`. `app.toml` gains `[contributes]` and `[[publishes.series]]`; the package
  format accepts them and `[backup]`. processcraft-sdk 0.31.0.
- 2026-10-25: interface API, additive: `GET /api/operations/health` adds `certificates`
  (`[{"id", "name", "use", "not_after", "days_left", "state"}]`) and
  `POST /api/operations/certificates/{id}/renew` (admins); the data layer's
  `GET /api/v1/certificates` and `POST /api/v1/certificates/{id}/renew` are read when present.
- 2026-10-25 (PlantCraft round 8): API v1, additive: `GET /api/v1/installation` (`{"time_zone"}`). A saved time zone may
  be `local` (the installation's, resolved where it is used: SDK `utc.resolve_zone`) or a fixed
  offset (`Etc/GMT+3` is UTC−3). Interface API: `/api/setup/installation` (admins) and
  `/api/me/preferences` (`time_zone`: `plant`, `utc` or `device`; `language`). `@processcraft/ui` 0.42.0:
  `TimeZoneSelect`, `timeZoneLabel`, `offsetLabel`, `resolveTimeZone`, time zone mode `utc`; the
  user menu links to Preferences instead of drawing the time zone and the language. The backup
  schedule's default zone is `local` (`ops-settings.json` carries `local_zone` for the installer). processcraft-sdk 0.27.0.
- 2026-10-25 (Alarms round 8, the Historian's events): additive: `GET /api/ops/metrics` may
  carry `conditions` and `events` (an app without an app key, `ops.report_conditions`);
  PlantCraft writes them as that app's events (`processcraft.events.conditions`).
  processcraft-sdk 0.28.0.
- 2026-10-25 (Alarms round 8): API v1, additive: events carry `severity`, `key`, `phase` and
  `category` (`GET /api/v1/events?key=`); an app may name itself as subject (`app:<id>`);
  `PUT/GET /api/v1/events/catalog`. `app.toml` `[publishes] events` takes
  `[[publishes.events]]` tables (a bare name still declares one). processcraft-sdk 0.26.0.
- 2026-10-23: interface API, additive: `GET /api/search?q=&limit=` (format
  `plantcraft-search/1`, the suite's Ctrl+K search, every app serves the same under its prefix)
  and `GET /api/assets/<id>/situation` (an asset's Situation tab). `@processcraft/ui` 0.25.0:
  `SuiteSearch` and `SuiteQueueButton` in `SuiteShell` (props `search`, `queues`). API v1
  unchanged.
- 2026-10-22: API v1, additive: `source_kind` on signals (`opcua`, `pi_web_api`, `csv`, `derived`;
  `null` when the source is unknown), from Historian's `source_kind`. Analytics judges a CSV
  signal (laboratory analyses) as sampled. `processcraft-sdk` 0.12.2 (`derived_signal`,
  `FakeProcessCraft`).
- 2026-10-22: interface API, additive: `/api/actions/{id}/items` (checklist) and `mentions` on an
  action; `/api/people/{username}`, `/api/me/profile`; `app_roles` and `profile` on users;
  `/api/language-models` (providers, settings, test). Tokens carry the per-app role in `apps`.
  `/api/language-model` keeps its shape (the default provider). API v1 unchanged.
- 2026-10-22: interface API, additive: `/api/asset-file` (formats, `export.<kind>`, read,
  review, apply) and `used_in` on each signal of `GET /api/assets/<id>`. API v1 unchanged.
  `processcraft-sdk` 0.10.1 (new starter types only).
- 2026-10-20 (post-MVP step 7): API v1, additive: `GET /api/v1/inbox` (a person's unread
  messages and open actions, the badge of the suite frame's messages button). New interface API:
  Messages, Actions and Specialists (`docs/collaboration.md`); `@processcraft/ui` 0.3.0 draws the
  messages button. Specialist model keys live in `specialist-keys.json` beside the database.
- 2026-10-19: API v1 (`docs/api-v1.md`) served by PlantCraft and mirrored by
  `processcraft_sdk.testing.FakeProcessCraft`; the `@method` SDK lives in `sdk/python`.
- 2026-10-19: API v1, additive: `kind` (`number` or `text`) on signals and series, text series
  return labels; batch read `POST /api/v1/series`. `processcraft-sdk` 0.2.0.
- 2026-10-19: central app only. API v1 unchanged. The interface's own `/api` lost the analysis
  routes (loops, protocols, jobs, schedules, methods, quality, specialists, messages,
  dashboards, actions, notifications); `/api/home` and `/api/settings` are new shapes for the
  launcher and the settings page. Loops are assets of kind `loop` with signals by role; the
  map's loop settings (protocol, criticality...) are ignored with a warning: CPMCraft keeps them.
- 2026-10-20: API v1, additive: assets gain `type_path`, attribute values in `attributes` and
  outgoing `relations`; `type` filter (a type and its subtypes); `GET /api/v1/asset-types`.
  `processcraft-sdk` 0.3.0. The map's `criticality` is now the loop's record, no longer a warning.

- 2026-10-19: OPC UA sources default to the namespace `urn:processcraft:plantcraft` (was
  `urn:processcraft:simulator`); the demo endpoint is `opc.tcp://<host>:4840/plantcraft/`. The
  scenario flag `include_simulator_catalog` and the `processcraft-opcua-server` command are gone
  with `processcraft/simulator` (G31): the demo scenario lists the Simulator's 50 loops.
- 2026-10-19: API v1 unchanged in shape; `/api/v1/apps` and tokens' `apps` claim also list apps
  installed from the Apps page. New interface API `/api/apps` (admin only) and package format
  `.pcapp` (`docs/app-package.md`, following `docs/app-standard.md`).

- 2026-10-20: API v1, additive: results, events, runs and schedules (`PUT/GET /api/v1/results`,
  `GET /api/v1/results/history`, `POST/GET /api/v1/events`, `PUT/GET /api/v1/runs`,
  `PUT/GET /api/v1/schedules`), shared rules in `processcraft_sdk.links`; SDK `refs`,
  `app_manifest` and `processcraft-app check` (`processcraft-sdk` 0.4.0).
- 2026-10-19 (G34): the interface follows its own deep-link rule. An asset opens at
  `/assets/<id>` (`/plant/<id>` and `/plant` move there in the browser); the built files are
  served from `/static/` (Vite `assetsDir: "static"`). `/api/refs` gives `asset:<id>` the href
  `/assets/<id>`. `/api/home` apps gain `asset_types` (from `[requires] asset_types`, `null`
  when the manifest is unknown); the asset page links each app's `<prefix>assets/<id>`.
  API v1 unchanged.
- 2026-10-20: API v1, **not additive (D2, once before the freeze)**: signal ids are
  `<source id>:<tag>` (`scenario:FIC-101.PV`), also in asset role maps; references
  `signal:<source id>:<tag>`, never percent-encoded. Bare tags of one source still read until v1
  is frozen; stored subjects and refs are renamed once at start. `processcraft-sdk` 0.5.0
  (`FakeProcessCraft` signals `fake:FIC-101.PV`...). Apps (CPMCraft first) re-read roles and
  migrate settings keyed by tag in their own PRs.
- 2026-10-20: API v1, additive except one fix (G39, G41 from CPMCraft): `POST /api/v1/events`
  also takes a list of up to 1,000 events (201 `{"saved", "ids", "errors"}`, per-item errors
  like the PUTs); `GET /api/v1/results` reads one subject per repeated `subject` parameter and
  no longer splits a value on commas (ids may hold commas). `processcraft-sdk` 0.6.0
  (`client.post_events`, `results()` sends repeated parameters, `FakeProcessCraft` both);
  `make sdk-wheel` builds the wheel apps vendor, byte for byte. Apps that pass several subjects
  in one comma-joined `subject` must move to SDK 0.6.0 (or repeat the parameter).
- 2026-10-20: API v1 unchanged in shape: a signal of an added source has the `kind` that source
  reports (the Simulator's modes are `text`, with their labels in `/series` and `/value`).
  `/api/home` `source` gains `names` and its `label` names the sources read. Deploy: the Simulator
  moves to an internal `demo` network shared with PlantCraft only; `dns` on the proxy,
  the Simulator and PlantCraft (`PROCESSCRAFT_DNS`, default none); `PROCESSCRAFT_DEMO_SUBNET`.
- 2026-10-20: API v1, additive: derived series. `PUT /api/v1/series` (an app's service token
  only, its own source `app-<app id>`; `{"written", "errors"}`); derived signals carry `app`,
  `subject` and `result` in `GET /api/v1/signals`, which filters by them. `processcraft-sdk`
  0.7.0 (`processcraft_sdk.derived`, `client.put_series`, `FakeProcessCraft`); PlantCraft
  requires `>=0.7,<0.8`. New: the data layer (`processcraft/platform/datalayer`): with
  `HISTCRAFT_URL` set, PlantCraft forwards signal, series, derived and source requests to
  Historian's `/api/v1/data/...`; unset (the MVP install), nothing changes.
- 2026-10-20: with Historian (main `274f47b`), testing source settings before saving
  (`POST .../sources/test`) and "Stop using" a signal (`PATCH .../signals/{id}`
  `{"enabled": false}`) are forwarded instead of answering 501. API v1 unchanged.
- 2026-10-20: API v1 series grids (`step` given) hold the last value into empty steps
  (step-hold): same shape, but steps that were `null` now carry the last value, from the first
  sample (or the look-back value before `start`), up to a hold limit (10 times the larger of
  `step` and the signal's median spacing; a `null` sample or the present ends it). Recorded
  values (no `step`) are unchanged. `processcraft-sdk` 0.7.1 (`shape_values`, `FakeProcessCraft`);
  PlantCraft still requires `>=0.7,<0.8`. Apps that read a grid's `null` as "no sample in
  this step" (TrendCraft, CPMCraft) now see held values; Historian serves the same grids once
  it takes SDK 0.7.1.
- 2026-10-20: signals recorded on change (text signals, tags ending in `SP`, `SETPOINT` or
  `MODE`) hold on a series grid without the hold limit, up to their next sample, a `null`
  sample, `end` or now (a setpoint left alone no longer goes `null` ten spacings after its last
  change). Same shape. `processcraft-sdk` 0.8.3 (`recorded_on_change`, `shape_values(signal_id=)`,
  `FakeProcessCraft`). Historian shapes its own grids (`HISTCRAFT_URL` mode): not changed here.

## Next task

The owner's next review round starts on the version left after this night's cleanup and the
load test (2026-10-27). The rounds so far (9 and 10 for Analytics and Models, 11 for Alarms) are
merged; their detail is in [devlog.md](devlog.md) and each app's `docs/devlog.md`. After that,
the highest open gap in `docs/gaps.md` (G11 and G12 are blockers for installs without Docker).

## Blockers

- Making the repositories public is an owner decision.
- No access to a real PI Web API or plant data to validate on (G2).
