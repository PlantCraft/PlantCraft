# Changelog

Every release of PlantCraft Alarms, newest first, in the
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) form. PlantCraft's `deploy/bundle.sh`
joins it into the bundle's release notes.

## [Unreleased]

### Removed

- The Blocks editor's library endpoint (`GET /api/rules/blocks`): nothing reads it since Blocks
  was retired. Rules drawn in Blocks keep running as drawn.

## [0.5.0] - 2026-10-27

### Changed (owner's final review, 2026-10-27)

- **Menu in the order things happen**: Overview, Events, Rules, Alarms.
- **An event opens its own page**: what it is, where it came from (the Analytics execution or run
  behind it), what the app sent, the same condition's earlier starts and ends, the rules that read
  it; "Create a rule from it" is there, no longer a button on each row. `GET /api/incoming/{id}`,
  `GET /api/incoming/condition?app&key`.
- **Overview without buttons on top** ("Evaluate now" moved to the Alarms page as an icon);
  each widget's title says on hover what it shows and in which order, each performance figure
  what it means and its target (also on Performance).
- **Blocks retired**: a rule is written Simple or in Python. Simple gains "did not change" (a
  frozen value); Python opens in the suite's code editor (`@plantcraft/ui/codeEditor`), starts
  from a commented example for its inputs, shows what comes in and goes out, expands full
  screen. Blocks rules that fit were rewritten as Simple or Python (migration `blocks-retired`);
  others keep running as drawn. The demo's frozen-measurement rule is Simple.
- Rule form: conditions in their own boxes, "Add a condition" with its own space.

### Security

- **Asset scope (decision D2).** A person who sees only part of the plant (PlantCraft's token claim
  `assets`) sees and acts on only its alarms: lists, summary, journal, performance, search, sent
  notifications; alarm pages read the plant as them. `processcraft-sdk` 0.66.0.

### Added

- **A focused Overview: what is active, and is the alarm load within target?** The default board
  is the alarms by priority beside the alarm rate, the alarm summary beside the most frequent
  alarms, then the ISA-18.2 indicators. The rate is now columns of alarms raised per hour over
  24 h, stacked by priority, with a dashed line at the philosophy's per-hour target; the most
  frequent alarms are bars with their share of the load, coloured by priority; each
  performance figure has its own colour against its target. Performance answers `hourly`
  (raised per whole hour, by priority) and each top alarm's `priority`. Active and raised in
  24 h stay in "Add a widget". processcraft-sdk 0.69.0, @processcraft/ui 0.72.0.
- **A new plant's first step: "Draft the alarm rules" (`[[contributes.start]]`, processcraft-sdk
  0.65.0).** Once an administrator applies an import of assets in PlantCraft, Alarms drafts for
  each unit a rule for a loop in poor shape and one for a signal without data, both switched off
  (`POST /alarm/api/start/draft-rules`); a rule of that name is kept. With processcraft-sdk 0.65.0
  (from 0.62.0) its database also uses the rollback journal on a Docker Desktop bind mount.

### Changed

- **Rules and the alarm philosophy keep "Local time" (owner, 2026-10-27).** A rule's hours and
  the shift summaries default to the installation's zone (`local`, resolved through PlantCraft,
  so they follow it when it changes) instead of UTC, picked in the suite's time zone list
  instead of typed; the summary's "active since" is a local time. SDK 0.62.0.

### Fixed

- **The Events table fits its page** (visual sweep, 2026-10-26): long kinds and subjects wrap
  instead of pushing the last columns out of sight.

### Changed

- **Acknowledge from the notification (quick-access protocol, processcraft-sdk 0.53.0).** The
  notification's **Acknowledge** button acknowledges the alarm as the person who clicks
  (`POST /alarm/api/alarms/<id>/ack`) instead of opening it, and critical and high ones pop up in
  every app. Once its alarms are acknowledged, cleared or out of service, a notification is
  settled for everyone (`resolve_notification`, "Acknowledged by ana"): each outbox row keeps the
  key it went out under (`notice_key`, `settled_at`, migration `notice-keys`).

- **Pages cleaned up (owner's review, 2026-10-26).** Four pages: Overview, Alarms, Events, Rules.
  **Alarms** is one table of every alarm, without counts or boxes above it: Needs attention,
  Unacknowledged or All, Only mine, rows ticked to acknowledge together, and a row opens the
  alarm. An alarm's page shows its facts, its value or events, its **History** and the
  **Messages sent** about it. **History** is gone from the menu: its journal lives in each alarm,
  what was sent in each alarm, and **Performance** with its **Targets** opens from the Overview.
  **Events** is one table: **Open now** (the default) or **All** in a period, filtered by type,
  app, asset, severity, state and counted; Received, Catalog and their counts are gone. **Rules**
  switch on and off from the list, and Rules and Silences share one heading so the tabs stay in
  place; a rule's page is its facts and its alarms (its journal is in each alarm).

### Added

- **Notebooks.** `pc.app("alarms")` reads the rules (each with its sentence) and the alarms
  (with their occurrences of the last 30 days), read only. Three examples in `Examples/Alarms`:
  rules and alarms, an alarm performance study (alarms per 10 minutes, bad actors, chattering,
  standing alarms, as in ISA-18.2 and EEMUA 191) and one alarm against its signal with the
  effect of a wider deadband. The tests run each example as a notebook runs it.

- **Rules rethought (round 11, plan D1–D10; processcraft-sdk 0.51.0).** A rule reads values
  (signals and the series the apps compute) and events (what the apps report, changes only),
  and is one diagram of alarm blocks written three ways: **Simple** (up to three conditions with
  and/or, held for a time or a number of points), **Blocks** (the ui block editor with the alarm
  blocks) or **Python** (administrators only, in the SDK's isolated area, at most once a
  minute). It covers named assets, a branch, an asset type, the assets of a Link execution or
  any asset its events name; one alarm per asset, per execution or one for the rule. Values and
  events are picked in the suite's **Explorer**. The rules of an older Alarms are rewritten as
  Simple rules once (migration `rules-as-diagrams`).
- **Outputs per rule:** Alarms always; **Dashboards** (asset colour and the Active alarms
  widgets, on by default, can be turned off); **Messages**; **Email** shown only once PlantCraft
  can send it (`GET /api/v1/notifications`). `POST /api/rules/from-signal` keeps the assistant's
  "Help me create an alarm" on one signal.
- **Pages:** Overview, **Alarms** (was Active, `/alarms`), **Events** with Received, Open now and
  Catalog (was Incoming, `/events`), Rules with Silences, History with Journal, Sent,
  Performance and **Targets** (was the alarm philosophy, `/history/targets`). Tour and help
  rewritten for the new model. A rule started from an opened condition hears its close too.

### Removed

- Suggested limits, the four rule types and their editor, app verdict reading, the notification
  policies of an older Alarms (table dropped, migration `drop-policies`) and the redirects of
  older page paths.

- **The assistant on Active, Performance and Journal:** which alarms first, the load against
  the targets, what happened in the period.
- **The assistant's works on an alarm** (processcraft-sdk 0.39.0, PlantCraft `docs/assistant.md`,
  "Works"): why it fired, and PlantCraft's create an action, offered here
  (`[[contributes.assistant.offers]]`) so the action is about the alarm's asset or signal.

### Changed

- **Older databases upgrade by named steps** (`processcraft-sdk` 0.46.0): the columns added
  since the first release are the stores' `MIGRATIONS`, run once and recorded, and
  `tests/test_upgrade.py` opens each store on its older tables.
- **The suite's dialog** (`@processcraft/ui` 0.53.0, scale review A1): the shelve and silence
  windows and the delete question are the ui's `Dialog` and `confirmAction()` instead of the
  browser's confirm or a window drawn here, so they follow the theme, keep the focus inside and
  close on Escape.

- processcraft-sdk 0.35.1: the suite's rules for an app's inside (PlantCraft
  `docs/app-standard.md`, section 5). The suite's event catalog is read by the runtime, the
  stored alarm's helpers live in `alarms/records.py` (the routers import no store), and the
  events are written by the names `app.toml` declares. Nothing changes for people.

### Added

- **The Historian's conditions** (processcraft-sdk 0.28): while `histcraft.collector.stalled`
  is open, "no data" alarms and failed runs send nothing, as when the Historian is down; while
  `histcraft.source.disconnected` is open, the "no data" alarms of that source's signals send
  nothing (the source's own condition says it once). The collector's suggested rule is created
  by itself.
- **Conditions** (processcraft-sdk 0.26): an event's own `severity`, `key` and `phase`. A start
  raises (or only when still open after so many minutes), its end clears the alarm by itself,
  and events with the same key are one alarm. Incoming shows phase and key, and **Open now** lists
  the conditions started and not ended (`GET /api/conditions`).
- **Catalog** (Incoming › Catalog, `GET /api/catalog`): every event the apps declare, with the
  rule each suggests; **Use the suggested rule** (`GET /api/rules/from-catalog?kind=`). A
  suggestion an app marks enabled (system events only) is created once, by itself.
- **Alarm philosophy** (Rules › Philosophy, `GET/PUT /api/philosophy`): the statement and the
  targets (messages an hour, flood, chattering, stale, priority share, summary times). Performance
  measures against them.
- **What reaches people follows the philosophy**: critical at once (past gathering and the
  limit), high gathered, medium, low and notices in the **shift summary** (07:00 and 19:00 by
  default; a rule can ask for "always at once"); a flood is one message a person (event
  `alarmcraft.flood.started`); a chattering alarm stops sending; a stale one is not reminded; the
  summary lists what waited, chattering and stale alarms.
- **Inhibition by dependency**: while the suite watch reports the Historian or its collector down
  (or the installer silent, Docker down), "no data" alarms and failed runs send nothing (gap G9).

## [0.4.0] - 2026-10-24

### Added

- **Buttons in Messages** (processcraft-sdk 0.25.0): an alarm's message has Acknowledge and Open
  the rule beside Open (category `alarm`); a notice's has only Open the rule (category `info`, as
  the note that the hourly limit was reached).

### Changed

- **Rules make the alarms.** A rule says when (a value beyond a limit, no data, an app's verdict,
  or an event another app reports N times within a window, optionally still open after a while),
  where (a signal, assets, or every asset under a unit), what it makes (an alarm, or a notice that
  needs no acknowledgement and stays out of performance), who hears and why. It makes one alarm
  per asset (or Link schedule). `/api/rules` (list, create, change, on/off, delete, journal,
  try, from an event) replaces `POST/PUT/DELETE /api/alarms` and `/api/alarms/try`.
- **Who hears is in the rule** (`notify`): the responsible (the owner the app names, such as the
  Link schedule's owner), people and groups; gathered into one message per rule (5 minutes),
  at most 6 messages an hour per person (escalations always go), and a failed or stalled Link
  schedule inhibits the other alarms of that schedule. Messages carry the key
  `alarm:<id>:<occurrence>` (one thread per occurrence in Messages), and Acknowledge and Open the
  rule when the SDK sends actions. The policies page is gone: older policies are merged into the
  rules of the alarms they sent, then dropped.
- The menu is Overview, Active (was Alarm summary, `?rule=` keeps one rule's), Incoming, Rules
  (with Silences) and History (Journal, Sent, Performance). `/summary`, `/journal`,
  `/performance`, `/notifications` and `/alarms` redirect.
- Older alarms become single-subject rules with the same ids; their history stays.
- `app.toml` reads `events` (the suite's events, for Incoming).

### Added

- **Incoming** (`GET /api/incoming`): every event the apps published, kept 30 days, with the
  rules that counted it, and "Create a rule" from an event. The first read shows the last day.
- `GET /api/sent` (with who reached the hourly limit) and `GET /api/silences`.

### Added

- The suite's search (Ctrl+K, PlantCraft 2026-10-23): `GET /api/search` answers with its alarms, by name, signal, asset or area
  (`processcraft_sdk.server.search`). `@processcraft/ui` 0.25.0 and `processcraft-sdk` 0.21.0
  bring the search box and the queue clock to the frame; the SDK answers the frame's queue
  probe for an app without a queue, so no page logs a 404.

### Changed

- The suite's visual identity (`@processcraft/ui` 0.28.0, PlantCraft `docs/brand.md`): Inter and
  JetBrains Mono, neutral greys, sentence-case labels, the app switcher at the top of the sidebar
  and the fold button in its bottom corner. The IBM Plex packages are no longer needed.
- Every time in UTC (PlantCraft, 2026-10-23): `processcraft-sdk` 0.20.0 (`dev/revendor --sdk-only`;
  the app keeps its `@processcraft/ui`). The store writes `2026-10-23T14:05:09.123Z` whatever the
  server's time zone, and rows written before with the server's local offset are rewritten once
  at start. `PyJWT` joins `deploy/requirements.lock` (the SDK needs it). Ruff's `DTZ` rules are on.
  Notification hours stay wall-clock times in each policy's own zone.
- The first page is the Overview every app of the suite shares (`AppOverview`, ProcessCraft UI
  0.20.0): Alarms' widgets (active, the alarms that need action, the 24 h load), arranged by each
  person and kept per person. The alarm summary, where the operator acknowledges and shelves, is
  its own page (`/summary`, "Alarm summary"), and holds the asset links; widgets and the
  notifications for several alarms open it.
- `processcraft-sdk` 0.15.0.

### Added

- Widget `raised`: alarms raised in the last 24 hours, against the ISA-18.2 load (6 an hour).

## [0.3.0] - 2026-10-23

### Changed

- `processcraft-sdk` 0.14.0: Alarms reads its settings with the SDK's `AppSettings` and connects to
  ProcessCraft with `PlatformRuntime`, the same code as every app (no setting or behaviour changes).

### Added

- Hours on notification policies: always, only inside some hours (a shift) or only outside them
  (on call), in the policy's own time zone; windows may run past midnight. An alarm still
  waiting when a policy's hours begin is handed over to it once.
- Escalation on notification policies: up to five steps that tell more people (a person, a
  group, the alarm's owner or the coordinator of the policy's groups) when nobody acknowledges
  within so many minutes; acknowledging stops them. Closes G10.

### Fixed

- Choosing "The alarm's owner" in a policy's recipients saved `group:owner` (a group that does
  not exist) instead of the owner.
- Reminders and escalations waiting in the outbox are dropped once the alarm is acknowledged.

### Fixed

- An app verdict alarm's page drew its chart on a number axis while its occurrences are dates
  (the browser logged "Expected number, MNaN..."): the axis is a time axis even without samples.
- An app verdict alarm read "App verdict verdict alarm"; its condition now reads "App verdict is
  alarm" ("is warning or worse").

### Changed

- `processcraft-sdk` 0.13.0: alarm conditions read their signals straight from the Historian
  when the suite sets `PROCESSCRAFT_HISTORIAN_URL`, without the hop through ProcessCraft (and
  back through ProcessCraft when the Historian cannot answer).
- `@processcraft/ui` 0.18.0: the browser tab reads page first, then the app, then the brand
  ("Points · Historian · PlantCraft"), and its icon is always the platform's mark.
- On the suite's current shared packages, the same as every other app: `processcraft-sdk` 0.12.1
  (log lines redacted in linear time) and `@processcraft/ui` 0.17.0.

### Added

- Every alarm has an owner (a person or a group of ProcessCraft; the creator by default), an area
  (from the asset tree, or set by hand), a discipline, and a switch for notifications.
- The Overview opens on **My alarms**: those you or your groups own and those a notification
  policy sends you. Every alarm table filters by area, discipline, owner, priority and state.
- **Notifications** page: policies (areas, disciplines, from a priority) to people and groups, in
  ProcessCraft's Messages and optionally by email, gathered into one notification, with
  reminders until acknowledged; silences for planned shutdowns; what was sent.
- The editor shows the share of the chosen priority against ISA-18.2's usual guide; Performance
  names each frequent alarm's owner.
- **App verdict** alarms: raised by another app's verdict on an asset (for example Link's loop
  health, through ProcessCraft's results), with on- and off-delays; `GET /api/verdicts?asset=`
  lists the verdicts an asset has.

### Changed

- The Overview's "From signal to a calm alarm system" path is gone, as on every suite page.
- `processcraft-sdk` 0.12.0 and `@processcraft/ui` 0.16.0; logs are JSON lines
  (`configure_logging`), the data folder is declared for the suite's backup (`[backup]`).

## [0.2.0] - 2026-10-21

### Added

- First release in the suite: alarms on plant signals with deadband and delays, the alarm
  summary, acknowledge and shelve, the journal, performance against ISA-18.2 and EEMUA 191,
  try on history and suggested limits.
