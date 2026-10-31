# Changelog

Every release of PlantCraft (ProcessCraft until 2026-10-27), `plantcraft-sdk` and `@plantcraft/ui`, newest first, in the
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) form (Added, Changed, Fixed, Security).
`deploy/bundle.sh` joins this file with every module's `CHANGELOG.md` into the bundle's
`RELEASE-NOTES.md` (`docs/operations.md`, section 3).

## [Unreleased]

### Changed

- **The Historian answers from several processes (0.6.0 load tests, 2026-10-31).** Heavy reads
  ran in one Python process on one core. `histcraft serve` now starts as many processes as the
  CPUs its container may use (`HISTCRAFT_WORKERS`, `auto` by default: the container's CPU limit,
  up to 4; one where SQLite cannot use WAL, as on a Docker Desktop bind mount, or with the
  collector inside). Each process holds its part of `HISTCRAFT_READ_VALUES`, and only one samples
  the work queue. With ten methods at once (`ci/bench/extreme.py`, C2, 2 CPUs) Analytics' round
  went from 16 to 12 s. `plantcraft-sdk` 0.80.0 gains `plantcraft_sdk.server.workers` (the
  start lock, the leader and `worker_count`), which PlantCraft now uses too.
- **One machine profile sizes the whole suite (plan B, 2026-10-31).** `install.sh --machine
  small|medium|large|xlarge|auto|off` (default `auto`, from the CPUs and memory Docker sees,
  within `PLANTCRAFT_MAX_CPUS`/`PLANTCRAFT_MAX_MEMORY`) fills about 30 settings from one table:
  every container's limits, the processes of PlantCraft and the Historian, Analytics' executions
  and compute slots, Models' runs, the Historian's read budget and database memory. Before, the
  defaults added up to 30 CPUs and 34 GB on any machine. A value changed by hand is kept.
  `compose.yaml` now passes `LINKCRAFT_WORKERS`, `LINKCRAFT_COMPUTE_SLOTS`,
  `HISTCRAFT_READ_VALUES` and `HISTCRAFT_WORKERS`, which `.env` could not change before.
- **Pools are sized by the container's CPUs, not the host's.** Inside a container
  `os.cpu_count()` counts every core of the machine: Analytics ran 8 executions at once with a
  4-CPU limit on a 12-core Mac mini. PlantCraft's processes, Analytics' executions and processes,
  and a compute worker's slots now use `plantcraft_sdk.server.workers.available_cpus` (the cgroup
  limit).
- **`install.sh` fits every CPU limit to small hosts**, also the ones left at their default in
  `compose.yaml` (a 2-CPU machine stopped on `LINKCRAFT_EXECUTOR_CPUS`, default 4).

### Fixed

- **Accessibility: no WCAG AA finding left in the suite's frame.** An axe-core sweep of 35 pages
  (desktop and phone, every app, 2026-10-31) found no critical issue and five small ones, all in
  shared parts: the count badges on the sidebar had white on red or light blue (3.5:1 and 2.5:1;
  now 5.4:1 and 6.7:1, `--pc-chrome-problem`), the tour card's head counted as a second page
  banner, the frame's `main` around an app had no name of its own, To-do, Notes and Messages
  jumped from `h1` to `h3`, a table column with only buttons had an empty header (now "Actions"
  for screen readers, in `DataTable` and Historian's sources), and the block editor's status
  lights had a label but no role (`role="img"`).
- **The demo journeys (`tests/e2e_suite`) follow the current sign-in page and tour.** They still
  looked for "Public demo" / "A visit lasts" (the visit clock went away on 2026-10-28), for the
  older "read-only" refusal and for the tour's last step "Your apps"; 13 of 15 failed on a VM
  after the update from 0.5.1, all from the first. 15 of 15 pass on main.
- **Trends keep their spikes.** When a trend had more points than a chart takes (1,500 by
  default), PlantCraft kept every n-th point, so any event shorter than the gap vanished: a day at
  1 s with twenty 5 s spikes showed none of them. Each stretch of the series now keeps its lowest
  and highest value, in time order, so every spike, trip and step is drawn at its full height
  with the same number of points (`plantcraft/industrial_data/thinning.py`; Historian and direct
  sources alike). Values that are not numbers (states) still keep every n-th point.

- **Installing again, or a release after its candidates, works without a manual step.**
  `install.sh` compared versions with `sort -V`, which puts `0.5.1-rc3` after `0.5.1`, so the
  update from a release candidate to its release was refused as going back; versions now order
  as the release check does (`0.5.1-rc3` < `0.5.1`). Before starting the containers of a new or
  repeated install, `install.sh` removes the ones already there (data, settings, images and
  backups stay), so a container left from an earlier run can no longer hold its name
  ("already in use") and need `docker compose down` by hand.

## [0.5.1] - 2026-10-30

### Changed

- **New look: the PC valve logo and Steel Blue.** The mark is now the
  letters P and C drawn as a control valve on a process line; the brand colour moves from
  `#0A66D0` to Steel Blue `#2E5A88` (`#3D78B6` on dark), across buttons, links, selection, focus
  and the sidebar accent. App tiles keep their hues, toned toward the new blue, with dark values
  that hold on black. New app marks: Analytics (two connected blocks), Models (a distillation
  column), Desk (console with the day's checklist), Alarms (a bell without the limit line),
  Historian (the data cylinder without the time axis), Documents (a page without the
  magnifier). The family image no longer shows the plant simulator, which is not an app. New
  [`brand/`](brand/) folder with PNG logos and the LinkedIn avatar and banner.

### Added

- **"Talk to us" in the public demo.** A visit shows a small button at the bottom right on every
  page, the apps included, that opens the site's contact form in a new tab
  (`PLANTCRAFT_PUBLIC_DEMO_CONTACT_URL`, an https address; `deploy/cloud/vm.sh` points it at
  `plantcraft.io/#talk`, which opens the form at once). The page after a visit ends offers it
  too. Without the setting nothing shows.

- **The public demo starts the same for every visitor.** A visit starts
  with the newest 20 notifications unread and the rest read, whatever the live plant added, and
  the seed leaves the newest message of 4 conversations unread (the Messages badge shows 4).
  Opening a conversation is now the visit's own read mark, like every other mark since the
  check and favorites: before, it marked the shared demo account, so the next visitor found
  everything read.

- **Tables and pages on a phone (fine pass 2026-10-28, ui 0.86.0).** A table column can be left
  out on a phone (`DataColumn.phone: "hide"`), cells are tighter there, a number and its unit
  never split, and a header actions cell keeps the header's rule. Overview widgets stacked on a
  phone are as tall as what they show (no empty desktop row under a short list; `CardGrid`
  `phoneHeight`). Page tabs that scroll sideways fade at the edge with more tabs and keep the
  active one in view. System health and Backups leave their secondary columns out on a phone; a
  state, a size and a backup's name stay on one line.

- **Check, seen or not, favorites.** A notification gets a check (done) in its
  row, in the quick-access panel, when it is open and on the page it opens (a small bar on the
  action or the alarm); one button turns it seen and not seen again. A conversation and an
  assistant chat can be marked unread until opened; the three take a star, favorites first.
  `PUT /api/me/marks`. On the public demo each visit marks for itself only.

### Changed

- **The platform's Python package is `plantcraft`.** The folder at the root of
  the repository, every import and `python -m plantcraft.<module>` follow the product's name, and
  the distribution is `plantcraft`. `processcraft` still runs: the console script, and inside the
  images `python -m processcraft.<module>` (`plantcraft/legacy.py`), so an older `install.sh`, a
  rollback to 0.5.0 and the Backups page keep driving every version's installer image. Image and
  service names, data folders, the app id, cookies and stored ids are unchanged.

- **Contributing is one clear path.** The README leads with how the suite fits together and how
  to contribute (commands moved to `docs/development.md`). Issue forms for a bug, an idea, a
  question and a change to the core; `.github/labels.yml` is the label set a workflow keeps on the
  repository; `docs/maintainers.md` is how issues and pull requests are answered, and a Claude
  Code skill (`.claude/skills/review-contribution`) checks whether a pull request fits. The
  agent rules and module pages are written for any contributor: no dated notes, no internal
  codes, and STATUS and devlog pages start fresh (the CHANGELOG is the record).

- **Analytics says what it is:** scheduled monitors, diagnostics and KPIs for signals and control
  loops, in its card, the guides and the site. The name stays.

- **Turn the assistant on in four steps.** `docs/assistant.md` opens with them (it is off until an
  administrator connects a model), linked from the README and the install guide; the public
  demo's assistant says so too.

- **Architecture in pictures and the zones of a contribution.** `docs/architecture.md` opens with
  the suite in one diagram, how the apps talk (one sticky valve) and what is core and what is open;
  `CONTRIBUTING.md` says when an issue comes first. The Zones check (`dev/pr-zones`) shows a pull
  request's zones on its run page and holds a fork's core change to an agreed issue.

### Fixed

- **The Historian answers raw reads about four times faster.** Writing the time of every value
  one by one was 79 % of a raw read of millisecond samples (a day of the demo's 167 plant
  signals: 3.1 s, now 0.85 s). `plantcraft-sdk` writes sub-second times for a whole series at
  once, with the same text as before. With ten methods reading at once, Analytics' round went
  from 30 to 16 s.

- **A new install on macOS or Windows starts.** On a Docker Desktop bind mount several
  PlantCraft processes wrote a new database at once and corrupted it ("database disk image is
  malformed"): file locks do not hold between processes there. PlantCraft now runs one process
  wherever SQLite cannot use WAL, whatever `PLANTCRAFT_WORKERS` says. Building a release works
  with `python3` only (macOS) in every app's Makefile too.

- **View no longer runs out of memory with many viewers.** Its short cache kept expired
  diagram data until it held 4,096 entries; on the public demo View reached its 2 GiB limit and
  was stopped (2026-10-29). Expired data now leaves at once, and viewers asking for the same
  data together share one read.

- **The old name is gone from what people type and download.** The command
  is `plantcraft` (`processcraft` still works), release files are
  `plantcraft-<version>-linux-<arch>-bundle.tar.gz`, `ssh-keygen` checks them as
  `release@plantcraft` (same key; a signature does not carry the name), the update page names
  every app with its current name (Analytics, View, Historian, Simulator) and the user guides say
  Analytics and View where they still said Link and Dashboards. The site's chat knows the former
  names. The Python package, images, services and data ids keep `processcraft`, so installations
  and their data do not change.

- **Running from source says which Python to use (#10).** The demo from source is tested on
  Python 3.12 and 3.13, and on 3.15 asyncua, the OPC UA library, fails to read, so signals show
  no values. The README and the install guide now say 3.12 or 3.13 (the Simulator needs 3.12),
  and `run_opcua_demo.py` warns on a newer Python. Thanks to the reporter of #10.

- **Analytics rounds no longer fail with "PlantCraft could not be reached: timed out" (demo,
  2026-10-29, SDK 0.78.0).** A loop round reads a day of every loop's signals; while the
  Historian served other long reads, the round's read waited its turn in the Historian's read
  budget (up to 30 s) longer than the SDK client's 15 s, so the client asked again while its
  first read still ran, three times, and the round failed (22 times in 8 h on the demo, "failed"
  in the Queue). The SDK's series reads now wait 90 s (`SERIES_TIMEOUT`, other calls keep 15 s)
  and PlantCraft waits 75 s for the Historian (`HISTCRAFT_TIMEOUT_SECONDS`, was 40 s), longer
  than the budget wait plus the Historian's own 30 s read limit.

- **Public demo, found by testing it online (2026-10-27).** The maintenance and manager guides
  opened "Report not found": the demo's visitor joins the Instrumentation and control group,
  which View's Control loops folder is shown to. The demo's four calculated signals are made
  again (their formulas named the Simulator's tags without `CPM.Loops.`). The visit's clock sits
  at the bottom (it covered Desk's greeting, and on a phone the tour's buttons); the guide's
  card no longer overflows with a long role name. An IPv6 visitor's places are counted by its
  /64, not by each device. Desk's Unread messages shows a reference by its name, not
  `#[name](action:9)`.
- **The site's chat** gives OpenAI's reasoning models room to think (empty answers came back as
  "cannot answer right now"), asks once more when the model fails, logs why, and answers
  Portuguese in Brazilian Portuguese.


## [0.5.0] - 2026-10-27

### Changed

- **One place to navigate, one look.** The side menu and the tabs are the
  only navigation: no Overview has buttons at its top (PlantCraft's tour moves to the person's
  menu, Analytics' Signal quality loses the button that repeated its Settings tab); top
  icon buttons and secondary buttons look the same in every app. The rules are written in
  `docs/ui-guidelines.md` and partly checked by `tests/test_visual_rules.py`.
- **The demo's Analytics keeps three monitors**: Control loop performance,
  Signal quality and the Furnaces model beside the plant. `processcraft demo seed` no longer
  writes the Valve health algorithm, its three monitors (valve health, oscillation watch, daily
  review) or Analytics' copy of the FMU Models exports; the story's texts name Control loop
  performance instead.
- **The demo has four calculated signals in Historian** (`calc:U100.FEED.TOTAL`, a sum;
  `calc:TIC-1209.DEV`, a deviation from setpoint; `calc:FIC-1210.KGH`, a unit conversion;
  `calc:FIC-1001.TODAY`, a totalizer since midnight), found with Signals' Type filter.
- **Every widget mark says what it is on hover (`@plantcraft/ui` 0.77.0).** A square of a status
  map, a column, a bar, a part of a split and a point of a trend show a note beside the pointer
  (and on keyboard focus): its name, its group, its time and its value; a list row or fact whose
  text is cut shows it in full. One note per page on `document.body`, so a card never clips it;
  text only. The browser's slow `title` on squares is gone (owner review, 2026-10-27).

- **Notebooks is two cards: Run in the browser, Run on your computer.** The chosen one opens its
  steps below and the page remembers it. The browser's limits fold under one line; the kit is
  three steps side by side (install, connect with a connection code, open), with each system's
  install notes and "Use my own Python" folded.
- **A widget list row says what its time is (`plantcraft-sdk` 0.76.0).** A time goes in the line
  below the name with its word ("Updated 5 h ago", "Started 2 min ago"), never as a bare
  "5 h ago" in the row's value, where nobody could tell what happened then (owner review,
  2026-10-27). `apptest.widget_problems` fails a bare time; `docs/widgets.md` says so.
- **Desk's menu ends with Notebooks, shown with the Python logo (`@plantcraft/ui` 0.75.0).**
  Today, Actions, Calendar, To-do, Notes (and Team) come first; Notebooks, the most complex, is
  last. `PythonMark` (the Python logo in the text's colour) replaces the notebook-and-pen icon in
  the menu and on Historian's "Open in a notebook".
- **ProcessCraft is PlantCraft (`plantcraft-sdk` 0.75.0, `@plantcraft/ui` 0.74.0).** Every
  screen, help page, document and message says PlantCraft. The SDK is `plantcraft-sdk` (import
  `plantcraft_sdk`, command `plantcraft-app`; `FakePlantCraft`, `PlantCraftClient`,
  `PlantCraftError`), the interface package `@plantcraft/ui`, and every setting
  `PLANTCRAFT_*`. The old settings `PROCESSCRAFT_*` are still read (`install.sh` renames them in
  `.env` on upgrade), and `import processcraft_sdk` still works for code and compose files
  written before. A new installation goes to `/opt/plantcraft`; one in `/opt/processcraft` stays
  there. The registry names Analytics and View ("PlantCraft Analytics", "PlantCraft View").
  `dev/rename-plantcraft` brings a branch made before to the new names.
- **The Simulator is `simcraft` (`processcraft-sdk` 0.74.0).** The platform takes the name
  PlantCraft, so the Simulator's id, image, command and compose service move from `plantcraft`
  to `simcraft` and its settings to `SIMCRAFT_*`. People still see "Simulator". An upgrade moves
  `data/plantcraft` to `data/simcraft` and `PLANTCRAFT_VERSION` to `SIMCRAFT_VERSION`; sources
  keep reading the demo plant at `opc.tcp://plantcraft:4840/plantcraft/`.

### Fixed

- **Long processes give freed memory back (`processcraft-sdk` 0.72.0).** Python frees a large
  piece of work, but glibc keeps the pages in its heaps, so a server's memory climbs toward its
  largest peak and stays there; the 3-hour soak read it as a slow leak (Analytics 1.7 to 2.4 GB,
  PlantCraft 1.0 to 1.4 GB). `processcraft_sdk.server.memory` calls `malloc_trim` every minute in
  every app server (`web.mount`) and in PlantCraft's API workers, and Analytics' engine also
  after each round. At 2,050 loops one trim gave back 22 % of the engine and 41 % of PlantCraft's
  workers. A part of the rest of the soak's climb was the page cache of Analytics' growing
  database, which `docker stats` counts while it is active and the kernel takes back on demand.

- **SQLite's temporary files go next to each app's data, not in the 64 MB `/tmp`**
  (`SQLITE_TMPDIR=/data` in `deploy/compose.yaml`). A query that sorts months of rows spilled
  more than that and failed with "database or disk is full" (Analytics' home after a month at
  2,000 loops, found by `ci/bench/age.py`).

### Added

- **The assistant searches the documents with each question (`processcraft-sdk` 0.73.0).** An
  app's assistant tool may ask for each question (`prefetch` in `[[contributes.assistant.tools]]`):
  PlantCraft calls it with the person's question, as the person, before the model answers, and
  the model starts from what it found, so a small model no longer has to pick Documents' search
  to read the plant's manuals. The person's folders, asset scope and "not for the assistant"
  still decide what it reads; a document becomes a source only when the answer names it
  ([docs/assistant.md](docs/assistant.md), "Tools the apps add").

- **The suite months old in a few hours (`ci/bench/age.py`) and a frozen suite for the long
  tests (`ci/bench/frozen.sh`)** (docs/bench/README.md). The age writes the bench plant's past
  through the apps' own stores in steps (3, 6, 12 months) and measures the same pack at each; the
  frozen suite is a second installation from a bundle, under its own Compose project and port,
  that no deploy touches.

### Added

- **Demo guides by role.** The public demo asks what the visitor does (control room operator,
  process engineer, control and instrumentation engineer, maintenance and reliability, plant or
  area manager, IT, OT and security, or just look around) and opens that role's guide: a card above
  every app that walks five to seven screens across the suite in the role's words, with fold,
  Back, Another role and close. `processcraft demo seed` writes the pages the story's names open
  (`GET /api/demo/guides`); the role picked is in the visit's audit entry. On any installation
  with the demo story, the user menu has **Guided demo by role** (docs/public-demo.md).
- **Public demo visits (`processcraft-sdk` 0.71.0).** "Enter the demo" gives a visit of the
  read-only visitor in one of `PROCESSCRAFT_PUBLIC_DEMO_SEATS` places (5) for
  `PROCESSCRAFT_PUBLIC_DEMO_MINUTES` (15), with a line to wait in (number in line, about how
  long), a countdown above every screen with Leave, and idle visitors giving way to someone
  waiting. The apps show their editors to a visit and save nothing; each visit is held to a few
  requests in flight in every app (`processcraft_sdk.server.demo`). From outside, the visitor
  account no longer signs in with its password, and the sign-in page no longer shows it
  ([docs/public-demo.md](docs/public-demo.md)).
- **The demo story is connected.** `processcraft demo seed` now links what the team wrote to what
  it is about: each action names the documents it follows, the dashboard and report that show it,
  the assistant chat that explained it and the conversation that asked for it, and carries a
  checklist half done; messages and comments mention them (`#[label](kind:id)`); the assistant's
  example answers list their sources, two of them asked in Alarms and Documents; a third
  conversation today (the PIC-1202 alarm), and the pinned "Start here" note follows one problem
  from Analytics to its action. A documents', dashboards' and reports' links read their names
  (the seed explains them to PlantCraft, API v1 knowledge). Seeded again, an older installation
  gets the links without losing anything.
- **`conversation:<id>` is a reference** (an action can name the conversation it came from): it
  reads "Conversation #N" and opens it in Messages for its members.

- **The demo draws Riverbend Refinery as one process display.** `processcraft demo seed` creates
  "Riverbend plant" in View's Operation folder (`deploy/demo/diagrams/`), with a page each for the
  overview, preheat and furnace, the column, the reactor loop, separation, amine and sulfur,
  utilities and effluent. Each of the 50 loops is on one page with its PV, SP, OP, mode and
  health; symbols keep the library's proportions, lines run from port to port, and the arrows at
  the edges open the next page. The eight one-page diagrams of earlier seeds are removed.
  `dev/demo_plant_drawing.py` redraws it.
- **Three more widget shapes for the Overviews (`processcraft-sdk` 0.69.0, `@processcraft/ui`
  0.72.0).** `bars` (a ranking with an optional target line), `columns` (a count per hour or day,
  stacked by status, with a target line) and `tiles` (a status map: one square per loop or signal,
  in groups). `processcraft_sdk.widgets` builds them (`bars`, `columns`, `tiles` and their parts),
  `apptest.widget_problems` checks them, `WidgetKinds.tsx` draws them ([docs/widgets.md](docs/widgets.md)).

- **PlantCraft's Overview answers "is the installation healthy?".** The new
  board is Apps online and Data connections, then **System** (problems open, free disk at the
  suite watch's thresholds, last backup, version, who signed in today; `GET /api/home/system`,
  read from what the watch and the Backups and Updates pages keep) and, for administrators,
  **Recent changes** from the audit log, on the person's clock. The apps' widgets, Needs
  attention, Open actions, Worst first and Your apps stay in Customize; a board someone arranged
  is kept. The page no longer waits for the apps' catalogs unless the board shows an app's widget.

- **Every app keeps a limited person to their part of the plant (decision D2, part 2;
  `processcraft-sdk` 0.66.0).** `processcraft_sdk.asset_scope` reads the token's claim `assets`
  and asks PlantCraft, as the person, which assets and signals they see (kept a minute; nothing if
  PlantCraft cannot say). Historian (direct reads, points, trends, search, exports), View
  (dashboards and reports read as the person; no public link or schedule set up by a limited
  person), Analytics (loops, results, runs), Alarms (alarms, summary, journal, actions), Models
  (simulations and studies on plant data) and Documents (documents about assets, search, the
  assistant's tools) answer them only about it ([docs/asset-scope.md](docs/asset-scope.md)).

- **A new plant's first steps in the apps (owner decision D5, F4; `processcraft-sdk` 0.65.0).**
  An app declares in `[[contributes.start]]` what it starts on the assets an import wrote, and
  serves it as `POST <prefix>api/start/<id>` (`StartIn`, `StartOut`). Once an import is applied,
  Assets › Import lists the installed apps' steps (`GET /api/asset-file/start`) and takes the
  ticked ones as the administrator (`POST /api/asset-file/start/<app>/<id>`, audited
  `assets.start_step`). Historian collects the import's signals from the sources it holds,
  Analytics reads its loops and queues their first round, Alarms drafts two rules per unit
  switched off, View draws one overview per unit. Each step skips what it did already.

### Changed

- **Public demo: 10 places, 4 requests in flight per visit and 8 for all visits in each app** (were
  5, 2 and 4), from the multi-user load test ([docs/public-demo.md](docs/public-demo.md)).
- **The demo tells one story, a week at Riverbend Refinery.** `processcraft
  demo seed` lost the code that migrated older demos (retired dashboards, renamed rules and
  folders) and speaks the glossary's names (Analytics, Historian, View). Its past is dated on
  the plant's clock. New in the story: Models' optimization study "Tune the level controller",
  three assistant chats (two shared with everyone, citing the demo documents), two notebooks of
  loop data, and a pinned Desk note "Start here" with a checklist through every app. Alarms'
  philosophy and deliveries use the plant's own zone ("local").

### Fixed

- **The assistant answers in the language of the question.** A short English question ("What
  dead band was measured on FV-1003?") was answered in Portuguese, the asker's settings: the
  language is now told from one clear word instead of two.
- **The assistant's chat list is quick with many chats.** `GET /api/assistant` names the
  profiles and resolves the chats' links once for the whole list instead of once per chat (each
  link read built the person's access again). `ci/bench/load_users.py` leaves out recorded calls to
  objects the install does not have (they counted as failures) and takes `--max-failed`.

- **PlantCraft answers five times more requests on the same CPU.** Every store call opened a new
  SQLite connection (about a millisecond each, the schema read again), and one request asks for
  20 to 40 of them: with 50 people at once a page waited 8.5 s at p95 on 4 vCPU. A connection
  whose block ended now goes back to its thread and serves the next block (rolled back if it
  left a transaction open; a block inside another still gets its own). `/api/home` 74 -> 14 ms,
  the sidebar's calls 75 -> 11 ms; 4 processes answer 119 instead of 20 requests a second
  (`ci/bench/load_users.py`, which now also asks heavy questions of the data and records the
  screens with `ci/bench/record_pages.py`).

- **Messages and action comments show a labelled mention (`#[label](kind:id)`) as its chip**,
  not as raw text, and the conversation list previews it as its label.
- **A public demo no longer refuses the suite's own apps.** The per-address limit counted
  Analytics' calls inside the internal network too (its rounds pass 600 a minute and stopped with
  429); it now counts only what comes through the proxy (`X-PlantCraft-Edge`).

- **A revoked compute worker shows unhealthy at once (`processcraft-sdk` 0.70.0).** Its gateway
  waits to be stopped and now drops its health file, so Docker stops calling it healthy.

- **A compute worker fills a freed slot at once (`processcraft-sdk` 0.68.0).** With every slot
  busy the gateway paused half a second before asking for more; on tasks under a second (a chunk
  of Analytics' signal checks) the slots sat idle a third of the time. A task that ends wakes it.

- **A compute worker fills a freed slot at once (`processcraft-sdk` 0.67.0; load test,
  2026-10-27).** While tasks run on a worker, its gateway asks PlantCraft for more with a 1 s
  wait instead of 20 s. An idle executor (Models) held the long wait while Analytics' slots
  freed, so a full queue ran four tasks every 20 s. An Analytics round of 2,050 loops now takes
  about 2.5 minutes on 4 vCPU.

- **Every time a person reads is on their clock, never UTC (`processcraft-sdk`
  0.62.0, `@processcraft/ui` 0.71.0).** The watch's messages and Desk's suggestions write the
  plant's time instead of "UTC"; the assistant is told the plant's time now and to answer in it;
  a datetime field of an assistant card reads and saves in the zone the pages show; the
  notebooks (`plantcraft-notebook` 0.2.0) index their tables in the plant's local time
  (`pc.zone()`, `pc.use_zone("UTC")` to change it) and read a time without an offset as that
  zone. The SDK writes local text once (`processcraft_sdk.utc.local_text`, with `zone_of` and
  `use_installation_zone`, Analytics' "local" clock until now); the ui adds `fileTime`,
  `fileTimeHeader` and `fileStamp` for the files people download. `tests/test_local_times.py`
  fails on the ways a UTC time slipped onto a screen before.
- **SQLite databases on Docker Desktop no longer crash their app (processcraft-sdk 0.64.0).** On
  a Docker Desktop bind mount (macOS `virtiofs`/`fakeowner`, Windows `9p`/`grpcfuse`), a network
  share or FUSE, several processes mapping one WAL database's `-shm` file end in a bus error
  (SIGBUS): Analytics restarted in a loop on the Mac mini and published no results. The SDK's
  `Database` now uses WAL only where its shared memory is safe and the rollback journal
  (`TRUNCATE`) there; `PROCESSCRAFT_SQLITE_JOURNAL` (`wal`, `truncate`, `delete`) overrides it.
  Analytics and Models revendored; the other apps take it at their next revendor.
- **Compute: a stopped executor or a PlantCraft restart no longer strands a task.** A gateway
  whose executor stopped answering (no heartbeat for 60 s) gives its tasks back at once, so
  another worker runs them, instead of renewing their leases until the time limit.
  `ComputeClient.answers` keeps waiting through up to 5 minutes of PlantCraft being unreachable
  (a restart cut Models' wait and failed the run).
  An executor's own memory per task (`--memory-mb`) now caps the size it takes, and a revoked
  worker's gateway waits to be stopped instead of exiting into a restart loop.

### Security

- **The platform review's decisions ("Faça as mudanças").**
  - Having an app means reading what it publishes, wherever it shows: a person reads the
    results, result history, events, runs, schedules and texts of the apps they may open (API v1
    and the assistant through it, the asset's page, Desk); administrators and app tokens read
    all (D1).
  - A link to an app's item (`#run:linkcraft/7`, a model, an app's text) says only its kind and id
    to someone who may not open that app (I3).
  - The assistant's share dialog says the answers were read with the owner's access, and only an
    administrator shares a chat with everyone (D3).
  - A write that rides the session cookies from another origin (`Sec-Fetch-Site`) is refused
    (S1).
  - The actions list resolves the references of its page once, and a link to an action reads
    only its title and status (P1, P2).

- **The security audit's last four points (`processcraft-sdk` 0.59.0).**
  - Writing with a language model (`POST /api/v1/llm/{use}`) needs the new permission
    `write.llm` in the app's `[permissions]`, and a use of an app outside the suite's bundle
    (`PROCESSCRAFT_APPS`) starts off whatever it declares, until an administrator gives it a
    model. Settings › Language models now keeps "Default model" when an administrator picks it
    for such a use.
  - The permissions of the suite's own apps are pinned by the bundle: `deploy/bundle.sh` writes
    each app's `[permissions]` (from the `app.toml` in its image) into the signed
    `release.json`, and PlantCraft holds the app's token to them; what the app declares when it
    starts may only narrow them.
  - The Notebooks kit's token lasts at most the administrator's limit for tokens (Setup,
    30 days by default; 90 at most), no longer always 90 days.
  - A report's public link draws its charts again: the proxy leaves `/dash/share/report/*` the
    page's own, stricter policy, which runs only the page's script, by its hash.

### Added

- **Draft a new plant (owner decision D5, 2026-10-27).** Assets › Import drafts the first tree
  of a plant from its tags: a source's browse or a tag spreadsheet (`POST
  /api/asset-file/draft/tags`), read as ISA-5.1 (loops, their signals by role, loop type,
  transmitter and valve by number); placed in units, areas and equipment by the plant's documents
  when PlantCraft Documents is installed (its new `find_tags` tool, called as the person); and,
  for the loops still unsure, by the language model of the new use "Plant draft", which only
  reads tag names, descriptions and passages Documents gives the assistant, and whose answers
  naming anything the sources do not are dropped (`processcraft/platform/plantdraft.py`, `POST
  /api/asset-file/draft`). The draft opens on the import's review page with a confidence and the
  cited passage per row, a "To check" filter and units left out with what is under them. On the
  demo plant's 205 tags and twelve documents it rebuilds the shipped map: 50 of 50 loops in
  their unit and area, 205 of 205 signal roles, 100 of 100 transmitters and valves on their
  equipment, 21 of 21 pieces of equipment with their type, 97 of 99 relations
  (`tests/test_plant_draft.py`).

- **Documents, a new app: the plant's documents for people and the assistant (owner,
  2026-10-26, plan "Documents"; `processcraft-sdk` 0.61.0, `@processcraft/ui` 0.70.0).**
  `apps/documents` (id `doccraft`, `/doc/`, port 8150, uid 10015, profile `doccraft`,
  `install.sh --with-doccraft`): folders with access, revisions by document number, PDF, Word,
  Excel, PowerPoint, text, Markdown, CSV and HTML read into passages with page and section, the
  plant's tags linked to its assets, and a search by words (SQLite FTS5) and by meaning
  (multilingual-e5-small in ONNX, bundled in the image) fused by rank, all offline.
  `deploy/demo/documents/` holds twelve demo documents of the Simulator plant and 40 evaluation
  questions; `processcraft demo seed` sends them.
- **The apps add tools to the assistant (`[[contributes.assistant.tools]]`, SDK 0.61.0).** An
  app declares a read-only tool and serves it at `<prefix>api/assistant/tools/<id>`; PlantCraft
  lists it to the model as `<app>_<id>` in Desk's assistant, the side panel and the MCP server,
  calls it through `POST /api/v1/apps/<app>/tools/<id>` as the person who asks, and keeps the
  `ref` of what it returns as sources (`docs/assistant.md`, "Tools the apps add";
  `GET /api/v1/tools`). Analytics' loop works and Alarms' "Why did this alarm fire?" search the
  documents when Documents is installed.
- **The assistant reads before it asks, and reads more of the plant (owner, 2026-10-26;
  `@processcraft/ui` 0.69.0).** Real questions on the demo plant (round 4) answered without
  reading when the question left something unsaid. Now:
  - the assistant calls a tool first with sensible defaults and says which it took;
  - "this week" is given in the prompt;
  - `list_actions` reads every action this person sees, filtered by status;
  - `search_assets` finds a type with its subtypes (equipment finds pumps);
  - `count_results` counts stale results, and stale results are named as stopped, not ok.
  - An opened create card's Open hands its fields to the form again, which used to open empty.
  - Analytics' new-algorithm card also takes its diagram written as calls
    (`f = dq.frozen(series = pv)`), and a port name the block lacks is read as any port that fits.

- **The Queue panel shows an app's compute workers (`@processcraft/ui`
  0.67.0).** An app opened in the panel lists the workers that run its tasks (name, online or
  paused, its tasks running of the slots, environments, the largest size the machine takes), or
  says none does. `GET /api/compute/summary` gives it to anyone signed in, without hosts, labels
  or credentials.

### Added

- **Each task says where it runs: environment and size (processcraft-sdk
  0.58.0; docs/compute.md, "Environments and sizes").** A compute task carries an environment
  (the executor image with the packages its code needs; `standard` by default) and a size
  (`small` 1 CPU 1 GB, `medium` 2 CPUs 4 GB, `large` 4 CPUs 16 GB). Executors announce their
  environment (`--environment`, folder `<app>.<environment>`), gateways their machine's CPUs and
  memory, and PlantCraft gives a task only to a worker that runs its environment and has room
  for its size; capacity lists what the workers offer. Settings › Compute shows each executor's
  environment, the largest size each machine takes, and names the environment and size of tasks
  waiting with no worker.

### Changed

- **The Queue panel shows the apps first (`@processcraft/ui` 0.66.0).** Mine
  and Running now made the panel too long: it now lists each app's numbers, with a "mine" mark
  where the person has work waiting or running, and an app opened lists its work (progress,
  Cancel, what ended in the last day) and links to its own page. `jobsByApp` replaces
  `mergeJobs`.
- **The suite's words (`@processcraft/ui` 0.62.0; docs/glossary.md).** The
  app Link is called **Analytics** in the suite's menu, the tab titles, search and the docs; its
  id, route `/link/` and package keep their names until the brand's final name (BACKLOG D5b). The
  frame says **Queues** (was Work queues), the search finds **signals** and a block's input
  preview counts **values** (was points). The tours' translations follow the renamed texts. In
  Alarms and PlantCraft, a Link execution or schedule is an **Analytics run** or **monitor**.

### Fixed

- **Results come in pages: none is left out (2026-10-27; `processcraft-sdk` 0.63.0).**
  `GET /api/v1/results` cut its list at 5,000 by subject without a word: on a plant with
  1,000 bench loops the assistant read only their results and none of the plant's.
  It now answers in pages (`limit`, `cursor`, `X-Next-Cursor`, like the other lists); the
  assistant and the MCP server read up to ten pages and say when the list goes on, the SDK's
  `results()` reads every page, and a specialist's "what needs attention" reads every result
  that is not ok.

- **The compute workers import what subclasses a socket (processcraft-sdk 0.60.0).** An
  executor's child replaced `socket.socket` with a function to refuse the network, so a module
  imported after it that subclasses the socket (`ssl`, which `httpx` brings in) failed to
  import: Analytics' Signal quality failed on the workers in every run ("function() argument
  'code' must be code, not str"). The socket is now a class whose instances refuse to open.

- **Suite names on every screen (visual sweep, 2026-10-26; `@processcraft/ui` 0.68.0).** The
  Apps table, Settings › Compute and App keys, and the Queue panel's rows said "PlantCraft Link"
  and "PlantCraft Dashboards" from the manifests; they say Analytics and View, as the side bar
  does. The demo's alert rule and texts say Analytics and alert ("Analytics monitor failed",
  renamed on the next seed).
- **Tables fit a phone** (visual sweep; `@processcraft/ui` 0.68.0): the hidden "Actions" label of
  a table's last column stretched Apps, Users, Compute and Backups to 500-850 px wide on a phone;
  it stays inside the table's own scroll now.

- **A page's work answers from the page:** the assistant reads the
  page's sections and its tools, and never asks the person to paste what is on their page (six
  of 45 works evaluated with a small model did).
- **The assistant counts long lists and says when a restart cut an answer.**
  - A tool answer too long for the model keeps whole items and says the total. Before, text cut
    mid-list was counted as 28 of 50 valves.
  - An answer cut by a restart of PlantCraft says so, with Try again.
  - Alarms' rules tell "enabled" apart from how many alarms they have.
- **The assistant after twenty real questions.**
  - "Which alarms are active?" reads Alarms' alarms as they are now (`list_app_objects` with
    `where active=true`), not older results.
  - A tool call a model writes as text is left out of the answer; an answer with nothing else
    fails with Try again.
  - Questions on how PlantCraft works read the Help first.
  - "Yesterday" comes with its bounds in the plant's time zone, never the last 24 hours, and
    `read_series` carries each signal's unit.
  - The model answers in the language the person writes in, and names the card's own button.
- **The assistant after its first real-model check (`@processcraft/ui`
  0.61.0).**
  - Asked in any chat to create a block, a small model now gets one tool per kind, with its
    fields typed and its instructions. Before, it sent a block's inputs as text or as an object
    ten times and gave up. Lists written as text or as objects are read as lists. A refused
    proposal shows as a failed step with why.
  - New read-only tools `list_object_kinds`, `list_app_objects` and `get_app_object` read
    Link's blocks and algorithms, Models' models and other app objects, so an answer can count
    or find them.
  - A list cut at its limit says its total, so an answer counts from it.
  - A signal's value and a chart's series carry the signal's unit, so the model no longer
    makes one up.
  - The assistant writes times in the plant's time zone, and "yesterday" is the plant's day.
  - A chart's period shows in the suite's display time zone, like Trends.

### Added

- **Models on the compute workers ([docs/compute.md](docs/compute.md)).**
  PlantCraft Models' Modelica runner is now an executor of the compute workers:
  `modelcraft-executor` (the `modelcraft-runner` image, user 10020, no network) takes its jobs
  from `data/compute-jobs/modelcraft/` through `compute-gateway`, here and on other machines
  (`install.sh --worker` runs it beside Analytics' executor). Models sends each check,
  simulation, sweep and FMU export as a compute task (`MODELCRAFT_RUNNER=suite`, the default)
  and shares no folder with its runner any more: `data/modelcraft-jobs/` is no longer used. The
  service `modelcraft-runner` is now `modelcraft-executor`; its limits are
  `MODELCRAFT_EXECUTOR_CPUS`, `MODELCRAFT_EXECUTOR_MEMORY` and `MODELCRAFT_EXECUTOR_SLOTS` (were
  `MODELCRAFT_RUNNER_*`). A simulation on a worker shows no progress until it ends.

- **Analytics on the compute workers; a worker on another machine (owner, 2026-10-26;
  `processcraft-sdk` 0.57.0; [docs/compute.md](docs/compute.md)).** `deploy/compose.yaml` runs
  `linkcraft-executor` with Analytics (its own image, user 10020, no network, no secret,
  `data/compute-jobs/linkcraft`), and Analytics sends its analyses and blocks' code there
  (`LINKCRAFT_COMPUTE=suite`). `install.sh --worker --platform URL --code CODE [--ca FILE]`
  installs a worker on another machine from the same bundle (`compose-worker.yaml`: the gateway
  and the executors, nothing listening). `python -m processcraft_sdk.compute executor` takes the
  installed package's version when `--version` is left out.

- **The Queue lists the work, not only numbers (`processcraft-sdk` 0.54.0,
  `@processcraft/ui` 0.65.0; [docs/quick-access.md](docs/quick-access.md)).** The Queue panel
  shows Mine (what the person started, with its progress, step and Cancel, and what ended in the
  last day), Running now and By app. PlantCraft answers the runs part (`GET /api/v1/queue`); the
  panel joins the items an app without an app key lists in its own queue (Historian's imports)
  and the app's own page of its queue (`url`).
- **Libraries and locked versions (Link round 10; `@processcraft/ui` 0.64.0).** `LibraryColumn`
  lists a page's libraries under a "Libraries" heading in the left column, where objects belong
  to a library instead of a folder. `VersionsTab` takes `actions` beside its title (New version)
  and `VersionLock` says, with a closed lock, why an object gets no new version (PlantCraft's
  own).

- **Settings › Compute and the installation's own worker (`processcraft-sdk`
  0.56.0; [docs/compute.md](docs/compute.md)).** Administrators see the compute workers at
  `/setup/compute`: state, the apps and versions each runs with its free slots, the machine's
  load and memory, tasks of the last 24 hours; they add a worker (its one-time code and command
  shown once), pause, resume, revoke or remove it, and set each app's time and memory per task.
  `deploy/compose.yaml` runs `compute-gateway` (user 10020) on a new internal network `compute`
  that only PlantCraft shares; `install.sh` writes its credential once (`data/compute-local-key`),
  so it starts enrolled. The gateway writes `gateway.json` when PlantCraft answers its heartbeat,
  for its healthcheck.

- **Compute workers (`processcraft-sdk` 0.55.0).** The apps hand the code
  people write to a pool of compute workers instead of running it in their own containers
  ([docs/compute.md](docs/compute.md)). PlantCraft keeps the queue of compute tasks
  (`processcraft.compute`): API v1 `/api/v1/compute/...` for the apps (`write.compute`, an app
  sees only its own tasks), `/api/compute-worker/...` for the workers (a one-time code, then a
  credential of the worker's own, kept hashed), `/api/compute` for administrators (add, pause,
  resume, revoke, limits per app; audited). A task runs on an executor of its app and version
  and a worker with its labels; `interactive` before `run` before `backfill`, apps taking turns;
  30 s leases renewed by a heartbeat, three tries, and System tells the administrators when tasks
  wait 2 minutes with no worker for them. `processcraft_sdk.compute`: the job folder (tar
  archives read with care), `ComputeClient` (submit, wait, answers, cancel), the worker's
  gateway (no open port) and the app's executor (no network, one process per slot, time and
  memory limits, cancel), `python -m processcraft_sdk.compute gateway|executor`.

- **One protocol for the quick-access bar; notifications that act and settle for everyone
  (`processcraft-sdk` 0.53.0, `@processcraft/ui` 0.63.0;
  [docs/quick-access.md](docs/quick-access.md)).** A notification's button can run the call in
  the app that sent it, as the person (`"method": "POST"`, only under that app's own prefix):
  Acknowledge in a notification acknowledges the alarm. `POST /api/v1/notifications/resolve`
  (`client.resolve_notification`) settles a thread for everyone who received it: off their
  count, no buttons, "Acknowledged by Ana". A critical or high notification pops up in any app
  with its buttons (`urgent_notification` of `GET /api/v1/inbox`, read every 15 s). Runs carry
  `by`, `progress`, `step` and `cancel` for the suite's Queue, and PlantCraft tells the person
  who started a run when it fails or ends after more than a minute.
- **A block's picture and drawing (Models round 9 M1, M2; `processcraft-sdk` 0.52.0,
  `@processcraft/ui` 0.60.0).** `processcraft_sdk.images` checks a block's image once (PNG, JPEG
  or WebP by their first bytes; an SVG rebuilt from a short list of drawing elements, so no
  script, event handler or outside reference survives; at most 256 KB) and serves it cached for
  good under a URL tagged with its content. `BlockSpec.image` holds it and `describe_block` gives
  its path, never the picture, so a catalog stays small. In `@processcraft/ui`, the diagram's
  node and the palette show it, `BlockDrawing` draws a block as the diagram does (inputs left,
  outputs right, names and units) for a block's Overview, and `BlockImageField` chooses it.
  Link keeps it in the block file (so in each version); Models in the class's `Icon` annotation
  (a `Bitmap`), so it is saved with the library file and Modelica tools show it too.
- **The assistant's answers stream, say what they are doing and go on elsewhere (owner,
  2026-10-26; `@processcraft/ui` 0.57.0).** The text shows as the model writes it (OpenAI and
  Anthropic), with a line for thinking, the read running, drawing the chart or preparing the
  card, and the seconds so far; a failed answer has Try again. Charts have Full screen, one plot
  per signal, and Open in Trends (View opens `/dash/trends?signal=&start=&end=`). Sources link
  to their pages (a signal to a trend of it) and list only what was read. Any chat
  prepares a card for what the person asks to create (`propose_create`): a block opens its form
  filled in instead of a file to copy. Desk's Assistant shows the cards too. The prompt asks the
  model to search before reading an id, count from complete lists and not repeat a closing
  question.
- **Comparing versions in the suite's interface (`@processcraft/ui` 0.59.0):** `ComparePicker`
  (tick two or three versions under a versions list), `comparedVersions` (`?versions=1,3`),
  `lineDiff` and `CodeDiff` (a code difference as `git diff` shows it). Link's blocks and
  algorithms and Models' models and blocks use them.
- **Folders for any app's objects (Models round 9 M5; `processcraft-sdk` 0.50.0,
  `@processcraft/ui` 0.56.0).** Link's folders move into the platform so every app files its
  objects the same way: `processcraft_sdk.server.folders` (`FolderStore` with the app's kinds,
  `folders_router` for `/api/folders/<kind>`, who moved what and when) and `@processcraft/ui`'s
  `FolderColumn`, `FolderField`, `FolderPlaceLine` and `useFolders`, set up once with
  `configureFolders`. Link uses them unchanged for its blocks, algorithms and schedules; Models
  gets folders for its models, blocks and studies.
- **Platform email for apps (Alarms round 11, phase 4; `processcraft-sdk` 0.51.0).**
  `GET /api/v1/notifications` answers `{"email": bool}` (an app's token with the
  notifications permission), `client.notification_settings()`; Alarms shows a rule's email
  output only when PlantCraft can send it. Alarms' pages are now Overview, Alarms, Events,
  Rules and History, with per-rule outputs (Alarms, dashboards, messages, email).
- **Alarms rules as diagrams (Alarms round 11, phases 2 and 3; `processcraft-sdk` 0.51.0).** A
  rule is written in a Simple sentence (up to three conditions on values or events, joined by
  and or or, held for a time or a number of points), in Blocks (the alarm blocks: values,
  events open or counted, compare, between, changed, rate, deviation, and, or, not, for at
  least, times in a window, Python, Raise an alarm) or in Python (administrators only, in the
  isolated area). It covers named assets, every asset under a branch or of a type, the assets
  of Link executions, or any asset its events name; one alarm per asset, per execution or one
  for the whole rule. Schedules say what they run on (`subjects`), so a rule over an execution
  follows its assets. The rules of an older Alarms are rewritten as Simple rules once
  (migration `rules-as-diagrams`). Suggested limits are gone.
- **Five more cases in the assistant's Evaluate:** yesterday's average of a
  signal asked as "yesterday", a time series of the last 24 hours asked in words, the installed
  apps, a Link block identified by its title, and how many of an app's results are in alarm.
- **The assistant's chats are organised like ChatGPT's.** A person puts
  chats in their own groups, archives them and reads the archive, and shares a chat like a
  dashboard (everyone, or people and groups): the others read it and continue it in a copy. A
  chat is a ref (`chat:<id>`), so its link or reference goes in an action or a message
  (docs/assistant.md, "What a person sees"). New: `PUT /api/assistant/chats/{id}/sharing`,
  `POST /api/assistant/chats/{id}/copy`; `PATCH` takes `folder` and `archived`.
- **Models, the Historian and every app's examples in notebooks (owner, 2026-10-26;
  `processcraft-sdk` 0.49.0).** `pc.app("models")` reads Models' models and runs (a finished
  simulation with its results); `model.run(stop=...)` queues a simulation in Models' queue and
  `.wait()` waits for it, only when an administrator switches on **Simulations from notebooks**
  (Setup › Apps › Models, off by default) and only for Models' editors
  (`POST /api/v1/apps/{app}/objects/{kind}/run`, the one request a person's access token may send,
  audited). New examples: `Examples/Models` (models and their runs, simulate a model) and
  `Examples/Historian` (raw samples and means, export a long period). Every app runs its
  examples' cells in its tests as a notebook runs them (`apptest.run_examples`).
- **Every app's objects in a notebook, one format (`processcraft-sdk`
  0.48.0).** `pc.app("link").blocks()`, `.get("block", id)` and `.run(...)`: an app declares its
  kinds in `[[contributes.objects]]` and its examples and runtime in `[contributes.notebooks]`
  (`processcraft_sdk.server.objects`, `processcraft_sdk.notebooks`), and PlantCraft forwards a
  notebook's reads with the person's identity (`GET /api/v1/objects`,
  `/api/v1/apps/{app}/objects/{kind}[/{id}]`, `/api/v1/apps/{app}/notebooks/runtime`). Link
  offers its blocks and algorithms, which run in the notebook with Link's own code (on the
  person's computer or in the browser; nothing runs on the server), and four examples in
  `Examples/Analytics`: run a block, write and test a block, run an algorithm, loop health. The
  Examples folder has one folder per app; PlantCraft's own four examples replace the six
  overlapping ones. The browser and the kit carry pydantic for the apps' runtimes.
- **PlantCraft Notebooks, opened from PlantCraft.** The kit becomes an app:
  a Windows setup (NSIS, for the user only), a macOS app and a Linux folder with `Install.sh`,
  with the examples inside. It answers `plantcraft-notebooks://` links: "Connect this computer"
  trades a one-time code (`POST /api/notebooks/pair`, `/api/notebooks/pair/redeem`, two
  minutes, once) for the kit's token, so nobody copies a token; "Open on my computer" and, by
  choice, every "Open in a notebook" open JupyterLab on the computer, synchronized, with a strip
  saying where it runs. JupyterLab runs in the background on 127.0.0.1 with a password of its own.
- **Each page offers its own works (`processcraft-sdk` 0.47.0,
  `@processcraft/ui` 0.55.0).** The generic "What needs attention here?" no longer shows on every
  page; "Explain this page" is the suite's only one, and each page offers what fits it: a list
  finds and creates its objects, an object page explains, changes or copies that object
  (docs/assistant.md, "What each page offers"). A work keeps only the page's facts it names
  (`context`), and `create`, `open` and `form` may hold `{subject}`, the id of the page's object.
  PlantCraft's 13 pages now offer 28 works (Find actions, Suggest the next step, Plan my day,
  Which runs failed, Explain one of its signals…); Help me create an action is offered on an
  action, an asset, Today and Needs attention.
- **The apps' pages offer their own works too (all five apps on `processcraft-sdk` 0.47.0 and
  `@processcraft/ui` 0.55.0).** Link: 36 works, among them on a block Explain this block, Help me
  change this block (its next version opens filled in), Make a new block from this one and Where
  is it used?, and on an algorithm How do I read its result? and Design a new algorithm from this
  one. Alarms: Help me create an alarm (the assistant proposes the rule; Create calls
  `POST /api/rules`) and its Rules and Rule pages get the assistant. Historian: What was its
  average yesterday?, Find a signal, Compare with another signal. View: Plan a new dashboard,
  Plan a new report, Explain one card. Models: Help me change this model, What should I try next?
  The pages' last code-side tasks became works.

- **The apps' tables change by named steps too (scale review E10, `processcraft-sdk` 0.46.0).**
  The 10 stores of Alarms, Link, Models and View that checked their columns at every start now
  list `MIGRATIONS` (`add_columns`), run once per database and recorded in `sdk_migrations`.
  `apptest.upgrade_problems()` opens a store on its tables as an older release wrote them;
  every app tests its stores with it. (Historian keeps its own `Database.add_columns`, which
  also runs on PostgreSQL.)
- **One signal picker answer (scale review A5, `processcraft-sdk` 0.45.0).**
  `processcraft_sdk.server.picker.signal_choices` ranks the signals an app's `/api/signals`
  answers (plant signals before derived series, then exact, prefix and other matches) and keeps
  the picker's fields. Alarms, Models and View use it instead of three copies; Alarms and
  Models now rank as View did.
- **An app starts with one call (scale review A2, A3, `@processcraft/ui` 0.54.0).** `startApp(App,
  { t, statusTones })` applies the theme, hands the app's `t` and status ids to the shared
  components and draws the app; `useSuiteSession()` renews the token and signs in again on a
  second 401; `formatReading()` writes a value with 4 significant digits and its unit. Every app
  and the template drop their copies of `session.ts`, `brandTheme.ts`, the session lines of
  `App.tsx` and the `Plot.tsx` bridges.
- **One dialog for the suite (scale review A1, `@processcraft/ui` 0.53.0).** `Dialog` (named by
  its title, focus moves in and stays inside, back to the opener on close; Escape, the × or a
  click outside close it, the click only until a field is changed; `onSubmit` makes it a form)
  and `confirmAction()`, a promise in place of `window.confirm`. Alarms, Historian, Link and
  Models use them for their 14 confirmations and 11 windows that each app drew by hand (Models
  had its own `Dialog`); View follows. The apps move from ui 0.50.0 to 0.53.0, so they take the
  0.52.0 contrast too.

### Changed

- **Notebooks on your computer, without the traps.** With Notebooks on, the
  kit is offered whenever the installation has one (one switch; an administrator may still take
  it away), so nobody lands on a bare wheel. "Use my own Python instead" gives the whole commands
  (a virtual environment, as PEP 668 asks on macOS and Linux) and warns that pip refuses a
  renamed file. An example opens from the Examples folder instead of writing a copy into My
  notebooks, and the copies the old example cards wrote are dropped (migration
  `example-copies-2026-10-26`). JupyterLite says "In this browser" at the top right.

- **Every app's `make ci` is the same (scale review A7, `processcraft-sdk` 0.44.0).** `deps
  standard lint frontend test`, where `standard` runs `processcraft_sdk.app_cli check` (Link and
  Historian called it `check`, the others ran `processcraft-app` from the PATH);
  `processcraft-app check` now refuses a Makefile without `standard` or with another `ci`.

### Removed

- **Legacy nobody reaches any more (night cleanup, 2026-10-25).** Link's one-time copy of a
  PlantCraft Twin (`linkcraft migrate`, `LINKCRAFT_MIGRATE_FROM_TWINCRAFT`; it ran on the only
  installation that had Twin) and install.sh's merged-app renames (`FORMER_APPS`,
  `--with-twincraft`). 414 Portuguese texts no screen says any more, and the tour's 60.
  `@processcraft/ui` 0.51.0 drops `AssistantPanel`, `AssistantButton` and their helpers
  (`orderSpecialists`, `readableMentions`, `awaitingReply`, `ASSISTANT_POLL_MS`), unused since
  the assistant moved beside every page; `assistantUrl` stays. `/api/v1/assistant` stays
  until API v1's next major version (it is in the 0.4.0 contract).

### Fixed

- **OpenAI's reasoning models answer with tools.** A work on Today answered 400 "function tools
  with reasoning effort are not supported" (gpt-6-luna in chat completions). OpenAI's own
  service is now asked through its Responses API, which takes tools with reasoning; other
  OpenAI-compatible servers keep chat completions. Each OpenAI provider gets a **Reasoning
  effort** in Settings › Language models (the service's default, none, minimal, low, medium,
  high), and a provider's **Test** now offers the model a tool, as the assistant does, so this
  kind of refusal shows there.

- **OpenAI's newer models answer again.** They refuse `max_tokens` ("Use
  'max_completion_tokens' instead", 400 in Settings › Language models › Test). The OpenAI client
  sends `max_completion_tokens` to OpenAI's own address and `max_tokens` to compatible servers on
  the plant's network, and switches once when the service names the other form.
- **Accessibility (WCAG 2.1 AA, axe on 36 screens in both themes).** `@processcraft/ui` 0.52.0:
  quiet text (`--pc-text-4`, the sidebar's section names) reaches 4.5:1 on every surface, with
  `--pc-text-3` a step darker in the light theme to keep the two apart; the Help index is a
  plain list. The Calendar's arrows are no unnamed images, and View's folder buttons sit beside
  the folder's heading instead of inside it (a control in a control).
- **A new person's PlantCraft Overview has no holes**: the default board lays out the small
  widgets first, then the medium and the large ones, so each row of the grid fills.
- **Two suite journeys followed screens that changed**: the read-only diagram has no "valid"
  banner since Link round 9, and Alarms' Active page is checked by its counts, which show
  whether the simulated plant has alarms now or none.

### Added

- **Files a public repository needs**: a code of conduct, the names and logos policy
  (`TRADEMARKS.md`), issue and pull request forms, the support and API policy
  (`docs/support-policy.md`) and disaster recovery with RPO and RTO
  (`docs/disaster-recovery.md`).

### Security

- **Every suite app now declares what it uses, and its tests prove it (scale review E4,
  `processcraft-sdk` 0.43.0).** `FakeProcessCraft` holds an app's token to the `permissions`
  of its contributions, as PlantCraft does, and records every permission an app's token uses;
  `apptest.permission_problems` fails an app's test run on one its `app.toml` does not
  declare. Link, Historian, View, Alarms, Models and the starter template vendor SDK 0.43.0,
  which sends `[permissions]` with the contributions, so PlantCraft holds each to them.
- **An app's token is held to its `[permissions]` (scale review E4).** Every
  API v1 route names the permission it needs (`processcraft_sdk.scopes`); an app's own service
  token gets `403` on a route it did not ask for. A packaged app is held to its signed manifest,
  an external app to what the administrator granted at registration (by default it reads the
  plant and writes to the audit log), a suite app to what it declares at start (SDK 0.42 sends
  `permissions` with its contributions). A person's routes (inbox, actions, assistant,
  notebooks) are closed to apps. New permissions: `read.runs`, `read.schedules`,
  `read.people`, `read.knowledge`, `write.series`, `write.notifications`, `write.knowledge`.
  `PROCESSCRAFT_APP_PERMISSIONS=audit` only logs.

### Fixed

- **The signal list at 50,000 signals (scale review E14).** Building the signal catalog read
  the source registry once per tag (about 40 s at 50,000 signals, on every list, batch and
  lookup); it reads it once, and the catalog is built at most every 2 s (at once after a
  change in the same process). A recorded file's end time no longer copies the file, a page
  of a list is no longer sorted again, and a reader's series is not copied to be shaped.
  `ci/bench/platform_scale.py` runs PlantCraft with 50,000 signals and 50 apps at once: the
  apps' round went from 571 s to 164 s on 4 CPUs (`docs/bench/README.md`).

### Added

- **API v1 kept as published (scale review E3).** `docs/api/v1/openapi.json` (written by
  `make api-contract`) is API v1 as served, `docs/api/v1/releases/0.4.0.json` as 0.4.0 served
  it; CI refuses an unwritten change to API v1 and any change that breaks a release
  (`processcraft.api.contract.breaking`). `docs/api-v1-reference.md` lists every route with
  its parameters and the permission an app needs. The previous SDK (the one the apps vendor)
  runs a suite app's calls against PlantCraft in CI.
- **Numbered migrations (scale review E10).** `processcraft-sdk` 0.42.0: a store lists the
  changes to its shipped tables in `MIGRATIONS` (`Migration`, `add_columns`); each runs once per
  database, in its own transaction, recorded in `sdk_migrations`, so an installation that
  skipped releases runs every step it missed. PlantCraft's ten stores that probed their columns
  at start now list them. `tests/schemas/0.4.0.sql` is the 0.4.0 schema; an upgrade test opens
  every release's schema with today's code (`dev/schema-snapshot/dump.py` at each release).
- **Lists in pages, and unchanged lists as a 304 (scale review E2).** `GET /api/v1/signals`
  and `GET /api/v1/assets` take `limit` and `cursor` (id order, `X-Next-Cursor`,
  `X-Total-Count`) and answer an `ETag`; `If-None-Match` gets a `304`. `processcraft-sdk`
  0.42.0: `processcraft_sdk.server.paging` for any list route; `client.signals()` and
  `client.assets()` read in pages of 5,000 and keep each with its ETag.
- **An app outside the suite table names no port and no user (scale review E5).** `[runtime]`
  `port` defaults to 8000 (each app listens in its own container, so ports are never shared
  out) and `uid` to one made from the app id (20000-59999); only the prefix must be free on the
  installation. The installer no longer refuses two apps with the same port or user.
- **The installation's id (scale review E11).** Every installation names
  itself with a UUID that never changes, so a company's plants and sites can be told apart and
  put together later: `install.sh` writes `PROCESSCRAFT_INSTALLATION_ID` once (installations
  from before get theirs on the next upgrade), `GET /api/v1/installation` and Setup ›
  Installation answer it as `id`, and every backup's manifest carries `installation_id`.
  `processcraft-sdk` 0.42.0: `client.installation_id()`.
- **Every app's Overview is a board of widgets like Desk's Today, and the apps publish many more
  .** Desk's Today offers the widgets of every installed app; an app's Overview
  offers only its own; each person arranges theirs. `processcraft-sdk` 0.41.0:
  `[[contributes.widgets]]` gains `kind` (`number`, `list`, `split`, `series`, `facts`), `pick`
  (a widget about one thing the person picks, with `<id>/options` and `?item=`) and `multiple`;
  `processcraft_sdk.widgets` serves the declared catalog (`catalog(manifest, t)`) and builds every
  shape (`number`, `items`, `split`, `series`, `facts`, `options`, `ago`); `apptest.widget_problems`
  calls every widget in its declared shape, and `contribution_problems` fails on widgets served
  but not declared, or a `pick` without options. `@processcraft/ui` 0.50.0: `WidgetKinds.tsx`
  draws the three new shapes (a bar split by status, a small area chart, a card of facts), the
  gear's dialog of a `pick` widget lists the app's options and titles the card by the one
  picked, and `AppOverview defaultLayout` takes placements with sizes. Link, Historian, Alarms,
  Models and View declare 5 to 8 widgets each in `app.toml` (one schedule, one result of an
  execution, a point's last hour, the alarm rate, one model, a saved trend...) and name a
  finished-looking default board.

- **The assistant's works (plan "Assistant on every page", step F1).**
  `processcraft-sdk` 0.37.0: `[[contributes.assistant.works]]` (`AssistantWork`, `WorkField`,
  `check_fields`, `fields_schema`): what the assistant does on each page, ask or create, declared
  as data. PlantCraft: `processcraft/assistant_works` (registry of PlantCraft's and the apps'
  works, the context in fixed sections `assistant-context/1`), `GET /api/assistant/works`, chats
  started with `work` and `page`, the model's `propose` tool (checked fields, a card the person
  creates from with one click; the model never writes) and `POST /api/assistant/chats/{id}/proposals`.
  `@processcraft/ui` 0.48.0: the button beside the title opens a menu of the page's works and
  tasks; `useAssistantPage` takes `page`, `facts`, `view`; the panel starts a work with them and
  draws a proposal as a card (`ProposalCard`: the fields editable, Create through the object's own
  route, Put aside).
- **Link's works (step F3, points 9-17).** Blocks, a block, Algorithms, an algorithm, Schedules,
  Executions, a monitoring round, a subject's history and one execution; writing a block and
  designing an algorithm continue in their forms (apps/link/CHANGELOG.md).
- **A work may continue in the object's own form (step F3).** `processcraft-sdk` 0.42.0:
  `AssistantWork.form` instead of `create` for an object finished where it is made (a block's
  code, an algorithm's diagram). `@processcraft/ui` 0.49.0: the card's button opens that form
  with the fields as a draft (`takeAssistantDraft`); the proposal becomes `opened`.
- **An app offers PlantCraft's works on its pages (step F4).** `processcraft-sdk` 0.39.0:
  `[[contributes.assistant.offers]]` (`AssistantOffer`: `work`, `pages`): one of PlantCraft's
  works, such as creating an action, offered on the app's own pages with PlantCraft's route. The
  create-an-action work puts what the page is about in the new action.
- **Desk's works (step F2, points 1-6 of the plan).** Actions: create an action with the assistant
  or ask about the board; one action: ask about it; Calendar: add an event or ask about what is
  coming; Notes, To-do and Notebooks: ask. Each page names itself (`page`) with a few facts and
  what it shows; the Actions page and an action's page now carry the assistant's button beside the
  title. A create work may be offered to viewers when its route takes them (a calendar event).
- **Assets' works (step F4, points 7-8 of the plan).** The tree: create an asset with the
  assistant (admins, as the New asset button) or ask how the tree is organized and what is missing;
  one asset: how it is doing now, plot its main signals, what the apps concluded (these were the
  page's tasks). Both pages carry the assistant's button beside the title.
- **Evaluate works.** Settings › Language models › Evaluate works asks each of
  the assistant's works the way its page asks it, with the context PlantCraft builds for a person
  and a subject read from this installation, and checks that the model reads it: an answer that
  reads the plant and names the page's subject, or a card with the object's fields. Each case
  shows the context sent and the card proposed (`assistant_chat/work_evals.py`,
  `POST /api/assistant/evals` with `suite: "works"`).
- **The assistant on more pages (evening).** Desk's Today, Needs attention,
  Types, Help and Executions; the Historian's points and sources; Alarms' active alarms,
  performance and journal; View's dashboards, reports and trends; Link's signal quality; Models'
  models, studies and a study: one ask work each, about what the page shows. A page that sends
  more than 8,000 characters of rows has them cut instead of the chat being refused.
- **The apps' works (step F4, points 18-20, and the older tasks).** Historian: a point's
  behaviour and quality. Alarms: why an alarm fired, and creating an action from it. View: a
  dashboard (explain it, what changed in the period) and a report. Link: a loop and Results.
  Models: a new model and a model. The pages' older tasks became works.
- **llm-egress (step F0b):** the suite's one way out to a language model in the cloud, only to the
  hosts of the providers an administrator added (docs/security-guide.md). Clearer errors from a
  model service (401 key, 404 model or address, 429 limit or credit, name not resolved).
- **The assistant's button beside every page's title (Link and Models round 9).**
  `@processcraft/ui` 0.47.0: `Heading` draws `AssistantTitleButton` beside the title on every page
  of every app, where the shell draws the assistant's panel and the installation offers a model;
  it opens the same panel as the sidebar's, on the page's tasks (`useAssistantPage`), and
  `openPageAssistant()` does the same from code. `assistant={false}` leaves it out. `VersionsTab`:
  an object's versions in a tab of their own (About on top, then every version newest first with
  its name, what changed, who and when), for Link's blocks and algorithms and Models' objects.
  The block diagram read-only (an algorithm's page) shows only Fit to screen, not the editing
  tools disabled, and a valid diagram no longer takes a banner (its problems still do).

### Changed

- A public demo keeps language models for the editors and administrators an administrator
  created; visitors and the apps' uses stay without (#233). A provider whose address is the
  vendor's own site means the vendor's API.
- **Written once, in the apps (refactor, owner 2026-10-25, no change in behaviour).**
  `processcraft-sdk` 0.36.0: `processcraft_sdk.server.lease.FileLease`, the one-process lock that
  Link's engine (`EngineLease`) and the Historian's collector (`FileLease`) each had a copy of.
  `@processcraft/ui` 0.46.0: `fillText` (the `{name}` filler of every app's `t`, the shared
  components and the tour) and `saveFile` (a file handed to the person: View's CSV and
  dashboard export, the Historian's packages and trend CSV, Link's block files, Models'
  downloads, PlantCraft's certificates). The stores of Historian, Alarms, Models and Link no
  longer re-export what moved to their `models`/`records`/`defaults` modules: importers name the
  new module. Every app, the template and the platform frontend revendored.

### Fixed

- `processcraft-sdk` 0.35.2: `apptest.contribution_problems` counts an event named in full
  (`"<app>.<name>"`) or as `f"{APP_ID}.<name>"`, as the apps write them.
- `processcraft-sdk` 0.35.1: `apptest.ui_copy_problems` accepts a `Plot.tsx` or `HelpPage.tsx`
  that re-exports or wraps `@processcraft/ui`'s, and the type declarations (`.d.ts`) the
  package's sources need.

### Added

- `processcraft-sdk` 0.35.0: **one inside for every app** (contracts P3). `apptest` checks four
  more rules: `suite_problems` (only `suite/` talks to PlantCraft for the app),
  `router_problems` (routers import no store), `contribution_problems` (every `[contributes]`
  and event table has its code and route) and `ui_copy_problems` (no copies of
  `@processcraft/ui`). StarterCraft shows each one: `suite/` (events, Desk feed and to-do, a
  model use), `notes/models.py` + `service.py`, a follow-up day and person on each note (on
  Desk's calendar and in that person's to-do), **Summarise** through Settings › Language models,
  and `#starter_note:<id>` references (`docs/app-standard.md`, section 5).

### Changed

- **Written once (refactor, owner 2026-10-25, no change in behaviour).** `processcraft-sdk`
  0.34.0: `processcraft_sdk.utc.parse_instant` reads an ISO 8601 time (None when unreadable)
  for the suite watch, the home page, certificates and assistant tokens, which each had a copy.
  PlantCraft's `Database` and `Store` (`processcraft.db`) are the SDK's with PlantCraft's
  differences (no schema stamp, writes take the lock at once, its own clock), and
  `processcraft.config.env_flag` is the SDK's. The platform's dialogs draw one `Modal`
  (`frontend/src/Modal.tsx`) instead of nine copies of the backdrop and header.

### Fixed

- `processcraft-sdk` 0.32.1: `FakeProcessCraft` lists odd asset items (not objects) again
  instead of failing on them while it hides result assets.

### Added

- `processcraft-sdk` 0.32.0 and API v1: **an app writes with a language model through
  PlantCraft**. Each `[[contributes.llm]]` use gets its own line in Setup ›
  Language models (`<app id>:<id>`, with what it sends), where an administrator gives it the
  default, another model or none. `client.llm(use, messages)` (`POST /api/v1/llm/{use}`):
  PlantCraft picks the model, keeps the key, counts the calls per plant day
  (`PLANTCRAFT_LLM_APP_DAILY`, 500) and audits each one. `FakeProcessCraft` answers it.

### Changed

- **Settings › Language models, in the order it is set up**. First the
  providers: the same vendor may come more than once, each with its own key; each model is
  tested when the provider is saved. Then **Models by use**: the default and, for each part of
  the suite that writes with a model (the Assistant now; apps will add theirs), the default,
  another provider's model or off. The switch beside the default is gone: choosing a default is
  what turns models on, and with no default yet the first model that answers its test becomes
  it. An installation whose switch was off keeps no default after the upgrade (models stay
  off). `PLANTCRAFT_LLM=off` forbids models (`PROCESSCRAFT_LLM` still counts), and the pages no
  longer show the variable's name.
- `@processcraft/ui` 0.44.0: the Assistant's button stays where it is, dimmed, while no model
  is set up, and says why; an administrator's click opens Settings › Language models.

### Added

- `processcraft-sdk` 0.33.0 and API v1: **the apps' calendar feeds and to-dos in Desk**
  (contracts P2). An app sends a feed it declared in `[[contributes.calendar]]` whole,
  `PUT /api/v1/calendar/{feed}` (2,000 items, each for `user:`, `group:` or `everyone`), and
  gives to-dos of the kinds it declared in `[[contributes.todo]]`, `POST /api/v1/todos`
  (upserted by `key`, 200 open per app and person or group), reads them back with who ticked
  them (`GET /api/v1/todos`) and closes them (`POST /api/v1/todos/close`). Desk › Calendar has
  a chip per feed and Desk › To-do a **From apps** view (and those due in My day). SDK
  `processcraft_sdk.desk`, `put_calendar`, `put_todo`, `todos`, `close_todos`; `FakeProcessCraft`
  serves the routes (`fake.tick_todo`).
- **The apps' reference kinds link to their pages** (contracts P2b): a `#<kind>:<id>` of a kind
  an installed app declares in `[[contributes.refs]]` shows the kind's title and opens its `url`
  (`{id}` replaced) in Messages, Actions and notes, named by the app's text about it or by its
  id. The manifest refuses a kind whose page is outside the app's prefix.
- **Setup › Apps** (contracts P2c): each app's installation settings (`[[contributes.settings]]`)
  drawn by their type and saved for it (audit log; a secret is never shown again), and links to
  its own Setup pages (`[[contributes.setup]]`). The app reads them with SDK
  `client.app_settings()`, `GET /api/v1/contributions/settings` (its service token only);
  `processcraft_sdk.contributes.setting_value` checks a value the same way everywhere.
- `processcraft-sdk` 0.31.0 and API v1: **what an app adds to PlantCraft, declared once**
  (app-standard section 4b, "Padronizar contratos entre apps e PlantCraft"). `app.toml` gains
  `[contributes]` (uses of a language model, widgets, search, calendar feeds, to-do kinds,
  reference kinds, installation settings, Setup pages, work queue) and `[[publishes.series]]`
  (the series it writes to the Historian), checked by `processcraft_sdk.contributes`. The SDK's
  server sends all of it when the app starts, `PUT /api/v1/contributions` (the event catalog
  with it; an older PlantCraft gets the catalog alone; an app without an app key carries it in
  its metrics), and PlantCraft keeps one row per app (`GET /api/v1/contributions`).
  `GET /api/v1/installation` names the `features` it draws (`client.features()`). The Apps page
  shows what a package and each installed app add. `FakeProcessCraft` serves both routes.
- `processcraft-sdk` 0.30.0 and API v1: **typed points, retention set by their app, and runs
  points** (Link and Models round 8, D6, with the Historian's H1 and H2). A derived point's
  `kind` is `number`, `integer`, `boolean`, `text`, `instant` or `structured`, read back
  typed; `retention_days` (0: forever) and `managed_by` lock its retention to the writing app,
  and derived signals list both. `PUT /api/v1/series/runs` writes one whole series per
  execution to a runs point that keeps the newest `keep_runs` (default 10); `GET
  .../series?run=|runs=` and `GET /api/v1/signals/{id}/runs` read them. Forwarded to the
  Historian, kept in PlantCraft without one. SDK `put_series_runs`, `series_runs`,
  `series_run_list`, `processcraft_sdk.derived.typed_value` and `RunIn`, shared with
  `FakeProcessCraft`.
- **Notebooks kit: JupyterLab on your own computer** (phase 3). Notebooks ›
  Run on your computer offers a zip for Windows (x64), macOS (Apple silicon) and Linux (x64),
  130 to 180 MB: a portable Python 3.12 with JupyterLab, numpy, pandas, scipy and matplotlib (the
  browser's versions) and `plantcraft-notebook`, opened with two double-clicks ("Configure
  token", "Open notebooks"), no installation and no administrator rights. PlantCraft adds the
  server's address (and the local certificate authority) to each zip as it sends it, never a
  token; `POST /api/notebooks/token` creates the kit's 90-day token, which the kit keeps in the
  system's vault. JupyterLab listens on 127.0.0.1 only; notebooks live in `PlantCraft notebooks`
  in Documents, and the kit copies Examples and the person's notebooks there
  (`GET /api/v1/notebooks`, `pc.sync()`), never over an edited one. It warns a week before the
  token ends and when the server has a newer kit. Off until an administrator turns it on
  (Setup › Notebooks); an optional part of the offline bundle (`notebook-kits/`,
  `make notebook-kits`, every file pinned by SHA-256).
- **Notebooks: run in the browser or on your computer** (phase 2). Desk ›
  Notebooks has two blocks. "Run in the browser" installs Python into the browser once with its
  progress (`GET /api/notebooks/files`; about 130 MB, 15 s on a local network), checks it is still
  there on the next visit and then only offers "Open JupyterLab"; its limits are listed in red.
  JupyterLite is served under its build (`/notebooks/lite/v/<build>/`, `processcraft/notebooks/dist.py`)
  with a year of browser cache, and keeps a person's edits under one storage name across builds.
  JupyterLab opens with two folders, **Examples** (read from the server) and **My notebooks**
  (was `PlantCraft`, whose notebooks still open), says "Starting Python on your computer…" while
  a kernel starts (`notebooks/lab/plantcraft-status.js`) and shows JupyterLite's loading
  indicator. "Run on your computer" keeps the package and the access token.

- `processcraft-sdk` 0.29.0 and API v1: **result assets** (Link and Models round 8, D6). What an app
  records about an asset gets an asset of its own, of the new starter type `result`, under it:
  the points one Link schedule writes for one loop hang there by role. Only the app makes them
  (`PUT /api/v1/assets/results`, its whole set; `POST /api/v1/assets/results/remove`); those
  it stops listing turn `ended` and keep their points. `GET /api/v1/assets` and the plant tree
  hide them unless asked ("Show app results"). SDK `sync_result_assets`,
  `remove_result_assets`, `assets(results=True)` and `parse_result_assets`, shared with
  `FakeProcessCraft`.
- **Limits for each person on API v1** (Notebooks plan): what one person's
  notebooks, scripts and assistants ask the plant for is limited, 120 requests a minute and 2
  reads at once by default, set in Setup › Notebooks (`PUT /api/notebooks/limits`, audited).
  Counted: every request with an access token (`pcat_`, one budget per token) and the series
  reads a browser sends through the proxy, which now marks them (`X-PlantCraft-Edge`). The apps'
  own reads never count, so a heavy notebook cannot slow Link, Alarms or View. Over the limit:
  429 with `Retry-After`; `plantcraft-notebook` waits and retries by itself; the first refusal
  of each minute per person is audited (`usage.limited`). Counted in the database, so every
  server process shares the same budget (`processcraft/auth/usage.py`).
- `processcraft-sdk` 0.28.0: **an app without an app key reports its conditions** (Alarms round
  8). The Historian answers the suite and never calls it, so it cannot post events; it names
  the conditions it has open now with `processcraft_sdk.server.ops.report_conditions`
  (`processcraft_sdk.events.Condition`: a declared `interval` event, its key, summary and
  subject), and `GET /api/ops/metrics` carries them with the app's event catalog
  (`send_event_catalog` without an app key). PlantCraft's health recorder reads the metrics
  every minute and writes each condition in the app's name (`processcraft.events.conditions`):
  a `start` when it appears, an `end` when it is gone; an app that did not answer keeps its
  conditions open, and they are stored, so a restart repeats or forgets nothing.
- `processcraft-sdk` 0.26.0 and API v1: **the event as a contract of the suite** (Alarms round
  8). An event carries its own `severity` (info, ok, warning, critical), `phase` (instant, or
  start and end of a condition named by `key`, like an interval) and `category`; `GET
  /api/v1/events?key=` reads one condition. Every app declares the events it writes in
  `[[publishes.events]]` of its `app.toml` (title, description, default severity, category,
  phase, payload fields and the rule Alarms suggests), checked by `processcraft-app check`;
  `processcraft_sdk.events.EventCatalog` writes them by name, the SDK's server sends the catalog
  at start (`PUT /api/v1/events/catalog`) and `GET /api/v1/events/catalog` lists every app's,
  PlantCraft's own first (asset and action activity, and `processcraft.*` about the
  installation's health). An undeclared kind is still recorded, logged once and listed as
  `undeclared`; `FakeProcessCraft` refuses it, so a typo fails in the app's tests. An app may
  write about itself with the subject `app:<its id>`.
- **Preferences** in the person's menu: where times are shown (Local time,
  UTC, or this device when it is elsewhere) and the language, saved for the account.
- **Setup › Installation**: the installation's time zone, picked from a list, saved in PlantCraft
  (it wins over `PROCESSCRAFT_TIMEZONE`); every app reads it from `GET /api/v1/installation`.
- `@processcraft/ui` 0.42.0: `TimeZoneSelect`, the one time zone picker: the person's default first
  ("Local time · Sao Paulo (UTC−3)" or UTC), then the other, the fixed offsets, the cities last.
- `processcraft-sdk` 0.27.0: `ProcessCraftClient.installation_time_zone()` and `utc.resolve_zone`.
- **Health › Certificates**: the HTTPS certificate and the Historian's OPC UA certificates with
  the date each expires; the administrators are told 30 days before and reminded 7 days before;
  the Historian's client certificate is renewed from the page.

### Changed

- Screens organized after the owner's walkthrough (2026-10-25). **PlantCraft's menu**: Overview,
  Assets, Health and Preferences on top for everyone (no "Plant" heading), then Administration with
  Users, Apps, Backups, Updates and Setup last; an app's settings close its menu everywhere
  (`tests/test_menu_order.py`). **Health** for everyone: a read-only view of whether each part of
  the suite runs (`GET /api/operations/status`); the disk, backups and certificates stay with the
  administrators. **Desk**: an Actions card opens in place on hover with its description, assets,
  owner and age (no bare text tooltip), the owner's initials are centred, a column shows only its
  count; **Team** is hidden until Setup › Desk (was Calendars) shows it (`/api/desk/team-page`).
  **Alarms**: Active's counts are the suite's indicator cards. **View**: each folder is its own
  band with its count; View keeps Suite health in a folder of its own, Platform; the demo's
  Instrumentation folder is Control loops.
- `@processcraft/ui` 0.45.0: the person's menu starts with the theme, then My profile,
  Preferences, Help, Take the tour and Sign out; About is gone and the version is a quiet line at
  the menu's foot. A page's tabs scroll sideways only: the line under them is drawn inside the
  band, so no vertical scroll bar shows (Link's Executions and block pages showed one). What
  floats closes alike (`dismiss.ts`): the person's menu, the list of apps and the quick panels
  close on Escape and on a click outside them, also a click on the app's page inside the frame;
  before, only the person's menu did, and only outside the frame. Every
  app, the template and the platform frontend revendored (SDK unchanged).
- `@processcraft/ui` 0.43.0: the block diagram editor says how to add a block. The palette opens
  with "Add a block" and how to use it, and the toolbar's **+ Block** goes to the palette's search.
  `ParameterField`, the inspector's field for one parameter of a block, is exported so an app's
  own page can edit a diagram's parameters outside the editor (Link's Inputs and parameters tab,
  Models' model page, round 8). Every app and the template revendored.
- Desk round 8 (docs/desk.md). **Actions**: the board's cards are compact by default (title,
  then number, due date, checklist and owner; the description on hover), with a Compact/Detailed
  switch kept per browser; each column's count is a pill, with a red one for its late actions.
  **Calendar**: the title opens a month and year picker, and a **Year** view (FullCalendar
  multiMonth, MIT) shows the twelve months; `/api/desk/calendar` answers up to a year.
  **To-do**: the fixed views stand apart from **My lists** and **Shared with my groups**, and an
  empty To-do offers a few examples. **Team**: an administrator sees every group with a leader's
  rights; **All groups** (`?group=all`, the default with more than one group) shows every group's
  people and how each is doing today. The demo adds an IT and automation team led by the
  administrator, and who is away or busy today.

- `@processcraft/ui` 0.41.0, the sidebar and the page's top (round 8): the fold
  button is the last of the quick buttons at the bottom, so it stays where it was clicked; the
  list of apps floats over the sidebar and the page, as wide as its names (the sidebar no longer
  scrolls sideways); the person's menu arrow points to the side it opens. The four quick panels
  have one width and one header (the Assistant's lost its own New chat button; "Your chats" goes
  back), going from one straight to another swaps what is inside without sliding, the button of
  the open panel closes it (Messages and Notifications only opened), and going to another page or
  app closes it, inside the frame too. The work queues' button turns while work runs, is green for
  a moment when it finished well and red after a failure until its panel is opened. The
  Assistant's panel, when no model answers, points an administrator to Settings › Language models
  (`GET /api/assistant` says `can_set_up`). The page's top is the title at the left and the
  buttons at the right in a band of one height: `Heading` and `AppOverview` no longer draw the
  line above the title or the one under it, and `base.css` hides them (and `.breadcrumb`) on pages
  that write them by hand (`pc-heading-keep` keeps a line that must stay).

- Backups: the schedule's time zone is picked from the list and is Local time by default; the
  times are time fields. `install.sh` adopts the server's zone on an upgrade when the
  installation still had UTC, which nobody had chosen.

### Fixed

- App packages: a manifest with `[backup]` (every app of the suite since 0.4.0) was refused as
  an unknown section; `[backup]`, `[contributes]` and `[[publishes.series]]` now pack.
- A new installation no longer takes its first daily backup (and, on a Sunday, the restore drill)
  while its databases are still starting: the schedule waits 15 minutes after its first look. A
  clean install shows no failed backup and drill in Backups.

## [0.4.0] - 2026-10-24

### Security

- Contributions from outside (docs/contributing-safety.md): `.github/CODEOWNERS` names the owner
  for sign-in and permissions, the assistant's tools, the stores, Link's sandbox and the Models
  runners, the installer, CI, dependencies, the agents' rules and the tests that hold them. A
  fork's pull request never runs on the Mac mini (every `runs-on` sends it to GitHub's runners)
  and the deploy jobs run only from `main`. Every workflow's token is read-only, no checkout keeps
  the token, every action is pinned to a commit SHA (Dependabot bumps them). A new **Security**
  workflow runs on every pull request: gitleaks over the tree and the pull request's commits,
  bandit (high severity), zizmor over the workflows and pip-audit of every image's lock.
  `tests/test_contributing_safety.py` holds these rules.
- `processcraft-sdk` 0.23.0: `apptest.open_routes` asks every API route without a token; each
  app's `test_suite_rules.py` fails on a route that answers (View's public links excepted).
- The assistant's tools only read: `tests/test_mcp.py` fails on a tool that is not a GET of API v1
  (or the series read). The assistant is told that what its tools return is data, never
  instructions, and to say when it looks like an attempt to steer it.
- `ci/e2e-upgrade.sh` builds the apps from this repository's `apps/` (it still looked for the old
  checkouts next to it).

### Added

- `@processcraft/ui` 0.40.0: a chart with `useResizeHandler` (`@processcraft/ui/plot`) also
  follows its own box, not only the window, so it redraws when the sidebar folds, a panel opens
  or a dashboard grid lays out again (View's trend cards drew 4 px past their card on the Mac
  mini after round 8).
- `@processcraft/ui` 0.39.0, the suite's frame (sidebar round 8): PlantCraft
  draws the sidebar once and the apps run beside it as content only, in a same-origin iframe, so
  switching apps never loads the sidebar again and every app shows the platform's sidebar. The
  proxy (`deploy/proxy/Caddyfile`, and the routes the installer writes for an app installed later)
  sends a signed-in page under an app's prefix to PlantCraft; the app inside tells the frame its
  pages and where it is (`FramedShell`), the frame asks it to go to a page or open its assistant
  or tour (`AppFrames`). The last three apps stay loaded; an app on an older ui opens on its own
  page (`?pc-frame=off`). Icons an app sends are cleaned to SVG shapes.
- `@processcraft/ui` 0.38.0, the sidebar's round 8: four quick buttons above
  the person, all alike: Messages and Notifications (each with its own unread count), the
  Assistant (a spark, like the others) and the work queues (an hourglass with what runs and
  waits). Each opens the same panel (`SidePanel`), out from under the sidebar's edge on the left
  and folding back the same way, with Full page and close in its header; one panel at a time.
  The fold button moves beside the app's name; the person's menu is a floating window beside the
  sidebar instead of a strip its width. Every app and the template revendored.
- The Assistant's panel works like a chat in Messages: a new chat about the page, and the
  person's earlier chats under it to continue one. Every chat is kept, private to the person, in
  Desk's Assistant (Full page opens it there); closing the panel no longer deletes it.

- Desk's Team, round 7 (docs/desk.md): for every member of a group, not only
  its leader. People (away or busy by their calendar, without saying why; open and late actions;
  a chat button), the group's actions on a board by status or by person (a leader drags a card to
  hand it over or change its status), the week ahead, the day's shift handover note (shared with
  the group) and the assets in alarm its people follow. `#note:`, `#todo:` and `#event:`
  mentions; the `#` picker offers a person their notes and to-dos. The demo seeds a shared note,
  U-100's shift-start list and handover, and the visitor's to-dos and a weekly meeting (the
  visitor sits in U-100 operations). The tour visits Team.
- Desk's Notes, round 7 (docs/desk.md): notes private until shared with
  people or groups, in a Tiptap editor (MIT; loaded only on `/notes`) with headings, lists, a
  checklist and `#` mentions of assets and actions; saved as one types; the line under the cursor
  becomes a to-do or an action (with its mentions); a calendar event has an **Event note**.
  `/api/desk/notes` (a note comes with its mentions resolved); table `desk_notes`.
- Desk's To-do, round 7 (docs/desk.md): in the place of Routines and the day's
  checklist. My day, Planned, All and Done; lists of one's own and a group's shared lists, each
  with a colour; a to-do has a date, a repeat (every day, on weekdays, on some days), steps and
  notes, changes order by dragging (or Alt and an arrow key) and turns into an action when it
  needs someone else. `/api/desk/todos`, `/api/desk/todo-lists`; tables `desk_todos` and
  `desk_todo_lists`. The checklists and routines of before became to-dos once, with nothing
  lost; `/api/desk/checklist` and `/api/desk/routines` are gone, `/routines` leads to `/todo`,
  and Today's checklist card is now **My day**.
- Desk's calendar, round 7 (docs/desk.md): events of each person's own, made
  by a click or a drag on the calendar (or **New event**), moved and stretched by dragging,
  repeated every day, on weekdays, every week or every month, laid out in the plant's time zone
  (`/api/desk/events`, table `desk_events`). The apps' scheduled runs start hidden and the runs
  of one hour come as one entry that opens their list.
- `processcraft-sdk` 0.24.0: `retire_series(signals)`, and API v1 `POST /api/v1/series/retire`:
  an app retires the derived series it no longer writes (its own source only; the Historian
  keeps the archive for its retired days). Link uses it to drop the series it stopped writing.
- PlantCraft round 7 (owner's review, 2026-10-24; `@processcraft/ui` 0.34.0):
  - One way to draw buttons and forms everywhere: a page's actions at the right of its title, 8 px
    apart, one blue primary and grey secondaries, red only to delete or take back, every button
    36 px with a 16 px icon, Refresh as an icon. Settings pages are one panel of `FormSection`s
    (title and explanation at the left, fields at the right) with `FormFooter`
    (docs/app-standard.md, section 10). Every app takes the new package.
  - Assets: **Open to level** 1, 2, 3 or All (level 2 by default, kept in the browser) and
    **Collapse all**.
  - Notebooks moved to Desk, after Calendar: six examples that run on any installation, the
    notebooks open in a new tab (no frame inside the page), the folder date no longer shows 1970,
    and the administrator's switch moved to Setup › Notebooks.
  - Audit log in the style of a log explorer: period picker, quick filters (changes, sign-ins,
    failed), person and app, a volume chart (click a bar to zoom), a detail drawer and older rows
    on demand (`GET /api/audit/volume`; `/api/audit` takes `kind` and `before_id`).
  - Corporate sign-in, Language models, Email, Calendars and AI assistant access redrawn on the
    form standard.
  - **Undo last import** on Assets › Import: what the last import created is removed and what it
    changed returns (`GET /api/asset-file/last-import`, `POST /api/asset-file/undo`). Setup's
    Configuration file page is gone (`/data/import` leads to the asset import); the plant map stays
    for scripts through `/api/map`.
  - Health, Backups and Updates are three pages under Administration (`/health`, `/backups`,
    `/updates`); the backup schedule moved from Setup into Backups. `/operations` and
    `/setup/backups` lead to the new pages.
- Desk's visual widgets (docs/desk.md): world clocks (up to six time zones),
  the month (a dot on each busy day; a day opens the calendar on it, now with a day view), today
  as a timeline with a line at now, actions as a board (drag a card to move it), unread chat
  messages and a quick note saved as you type. Today's top is only the greeting, the date and the
  time. A new person's Desk starts in whole rows. `/widgets` draws every widget at every size it
  allows; `tests/e2e/test_widgets.py` fails when one spills out of its card.
- The assistant on every page (docs/assistant.md, `@processcraft/ui` 0.32.0):
  one **Assistant** button at the top right of every page of every app opens a side panel on the
  right, over the page. It first asks what the person wants to do: the tasks the page's developer
  declared with `useAssistantPage({place, context, tasks})` (each with the instructions the model
  gets, the context it reads and, when it needs one, the person's words, such as "Which
  execution?"), then the suite's own ("Explain this page", "What needs attention here?"), or the
  person's own words. Alarms, Historian, Link (results, loop, run, algorithm), Models, View and
  PlantCraft's assets declare theirs. The person reads what the model got under See the context.
  The panel's chat is not kept unless the person continues it in Desk; closing the panel deletes it.
  The assistant's mark (a small box with a spark) is the same everywhere. The apps take
  `processcraft-sdk` 0.22.0 with it.
- One Help for the suite: Help left the apps' menus for the person's menu; it
  opens PlantCraft's Help at that app's guides, with every app the person may open at the top. The
  assistant reads PlantCraft's guides with a new `read_help` tool.
- The assistant's evaluation (Settings › Language models › Evaluate): questions whose right answer is
  read from the plant's data at each run (a signal's mean and maximum over a day, a chart, an asset
  count, a tag that does not exist, an app the person may not open, a translation), asked with the
  assistant's tools and permissions and checked against those golden answers.

### Changed

- `@processcraft/ui` 0.37.0 (Models round 7): `BlockEditor` draws models that
  are integrated over time. `allowLoops` lets wires close feedback loops (a controller reading the
  level it moves), "Arrange" lays such loops out left to right, and the port type `real` (a value
  continuous in time, Models' signals) has its colour and label. New blocks are named in
  snake_case of their kind (`first_order`), so the names are valid Modelica. The legend names
  the kinds of wire the catalog has.
- Widgets have fixed sizes (docs/widgets.md, `@processcraft/ui` 0.36.0): each
  declares one to three sizes, 1 to 3 rows high (`sizes`; standard ones from `size`), and draws
  what fits each one (`rows`, `listRows`, `bodyPixels`). Dragging only moves a card; its gear
  picks the size with a preview. A size saved before becomes the closest allowed. "Add a widget"
  opens a window with the apps at the left and their widgets, previewed, at the right. An app may
  publish `sizes` in its catalog. `CardGrid` takes `resizable` (default: while editing). New:
  `WidgetCard`, `WidgetPicker`, `WidgetGallery` (every widget at every size, for a test page).
- `processcraft-sdk` 0.25.0: `notify(..., category=, actions=)`. A notification says what it is about
  (`alarm`, `run`, `action`, `info`) and carries up to three buttons (`{"label", "href"}`, paths
  of the suite) beside Open (docs/api-v1.md). The suite's messages button counts unread
  notifications with the chats when the platform sends them apart (`unreadCount`).
- Messages has two sections: **Chats** and **Notifications**, read like an
  email inbox. Notifications gather what apps send (one thread per app and `key`, unread again on
  each new event, with its priority, category and up to three buttons), changes others made to the
  person's actions and alarms on the assets they follow; filters (All, Unread, Alarms, Actions,
  Runs, Archived), search, mark read or unread, archive, mark all read (`GET /api/notifications`,
  `POST /api/notifications/marks`). Desk's Inbox page is gone (`/inbox` opens the notifications);
  its widget shows the unread notifications and opens Messages over Desk. `GET /api/v1/inbox`
  counts `unread_notifications` apart from `unread_messages` (chats only); the suite's messages button
  shows both together.
- `@processcraft/ui` 0.33.0: Messages and the Assistant cross every app. One
  row above the person's name holds **Messages** (with its unread count), the **Assistant** and the
  fold button; Messages opens PlantCraft's Messages over the page, in a panel on the right, without
  leaving the app (`MessagesDrawer.tsx`, `/messages?embed=1`), and closing it returns to the same
  screen. The Assistant's button left the top right of the pages for that row. Desk's menu no longer
  lists Messages and the Assistant; `/messages` and `/assistant` stay as their full pages.
- The assistant is for the platform only: in Desk and in the side panel it
  helps with PlantCraft and the plant and politely declines anything else (translations, general
  texts, general knowledge); in the side panel it keeps to the page and the task chosen. Desk's
  first questions are about the plant and the platform, and the evaluation's last case checks
  that a translation is declined.
- Interface language: English only for now. Portuguese is switched off until
  the interface settles: the platform answers in English whatever the browser asks, and no
  language picker is shown (sign-in, user menu, tour). The catalogs stay;
  `PROCESSCRAFT_TRANSLATIONS=1` and `TRANSLATIONS` in `frontend/src/i18n.ts` bring them back.
- Times are stored and computed in UTC and shown in local time: the plant's
  time zone (`PROCESSCRAFT_TIMEZONE`, which the platform hands to every page in the
  `processcraft_time_zone` cookie) or, chosen in the user menu (Times: Plant / This device), the
  device's own. Dates, charts (Plotly draws the UTC times at the zone's wall clock), period
  inputs and the Desk greeting follow it; a new install sets `PROCESSCRAFT_TIMEZONE` to the
  server's time zone.
- `@processcraft/ui` 0.31.0: `timeZone.ts` (`displayTimeZone`, `wallClock`, `fromWallClock`,
  `zonedFigure`, `setTimeZoneMode`), `formatDate(value, options)` in local time, `Plot` that
  draws in the display zone, `PhoneFold` and `useNarrowScreen`, widgets after the first two
  folded to their title on a phone, `fitHeight` for a read-only diagram, `translationsOn`.

### Fixed

- Health showed "Nothing to watch" while the installer ran: with several workers, the page is served by one that does not tick; the watch keeps its last look in the database.
- The Overview's Data connections lists only real connections (not what apps write, the suite's health or imports).
- Demo seed on a clean install: Alarms' five example rules all made (suggestions name their loop in `assets` since Alarms 0.4.0), PIC-1202's limit taken from the archived minutes so the replayed past holds alarms, and the visitor's Desk to-dos written on a public demo.
- `@processcraft/ui` 0.35.0: chart tooltips read in the dark theme. Plotly's hover label had no
  colours of its own, so a unified tooltip was a white box with light text; it now takes the
  theme's surface, axis and text colours (`plotTheme`), for every app's charts.

- Journey review (2026-10-23), second batch:
  - Demo: the control room starts the shift with "FIC-1003 feed flow below minimum" active and
    not acknowledged (owner U-100 operations), so the operator's journey has an alarm to answer.
  - On a phone, a loop's page in Link folds its long parts (algorithm, method results, series,
    settings, runs) to one line each, and Desk folds the widgets after the first two.
  - View: a text signal (a mode, running or stopped) in a trend is a band of states under the
    plot's lines, not an error.
  - Historian: the Overview's Sources sit beside the points not collecting (no empty half row);
    the Sources table draws Browse, Test and Backfill as icons so every button fits.
  - Link: a loop's algorithm diagram is as tall as fitting it to the width takes (it was drawn
    too small to read); "Worst first" writes a score in % like a health, with its label.
  - Assistant off: an administrator gets a button to Setup › Language model; anyone else is
    told who turns it on.

- Journey review (2026-10-23), fresh install of the bundle with the demo:
  - Link: a model or site block saved after start now runs. The engine works in a process of
    its own and only learned the catalog at start, so the demo's "Furnaces (FMU from Models)"
    failed every minute ("Unknown block"); before each execution the engine now catches up
    with the models and block versions the web process saved (`Runtime.sync_catalog`).
  - `@processcraft/ui` 0.30.0: a tour that opens by itself keeps its first step on the page the
    person opened, so a link followed from a message or an alarm is no longer replaced by Desk.
  - On a phone, the top bar names the app again: Desk's name was white on white and the apps'
    ran into the wordmark ("LinkPlantCraft").
  - The platform tour says "signed in read-only" only to read-only people of a public demo, not
    to its administrator.
  - View: signal search lists numeric signals before text ones (a trend has no line for a mode).
  - pt-BR: "Fila livre" for an idle queue (was "parada", read as stopped) and "ações" where
    "actions" was left in English.
  - `ci/e2e-bundle.sh` pulls every third-party image compose.yaml pins by digest (Telegraf
    and PostgreSQL), written plain or as `${VAR:-default}`.

### Added

- The soak (`ci/bench/soak.py`, `make soak`): days on one build with the Mac mini's automatic
  deploys held (`data/deploy-hold`, read by `ci/macmini/suite-deploy`), a person's probes every
  minute and the suite's own `system` signals read back into a verdict: no restart, up 99.5 %,
  memory flat, queues that drain, disk, probes and fresh live values (docs/bench/README.md).
  `suite_bench.py --cleanup` removes what a `--keep` run left.

### Changed

- Visual identity (`docs/brand.md`; `@processcraft/ui` 0.28.0): Inter (variable,
  optical sizes) and JetBrains Mono replace IBM Plex, self-hosted inside the package
  (`ui/src/fonts/`, OFL), with one type scale (page title 28 Bold, section 20, highlight 16,
  body 14, card label 13, caption 12, numbers 28 SemiBold). Neutral greys (`#F5F5F7` canvas,
  black in dark), PlantCraft Blue `#0A66D0`, status colours with AA text variants, a graphite
  sidebar. Sentence case instead of uppercase labels; the line above a page title is a crumb.
  A source with no news is grey (`unknown` -> inactive), offline stays red.
- The sidebar: the app's name at the top opens the app switcher (Desk first, PlantCraft last,
  set apart); the fold button stays in the bottom corner beside the person and the messages,
  and the `[` key folds and unfolds the menu. Messages is an icon with a red count of unread
  messages; a new message shows a short notice and the tab title starts with the count, `(2) `.
- The sign-in page is plain: the mark, "Sign in to PlantCraft" and the installation (plant,
  version, internal network or public demo; `GET /api/session` now says `installation`).
- The PlantCraft mark (bigger valve, shorter stem) and a new Link glyph (one block in a feedback
  loop); Twin's mark is gone (its machine ids map to Link). `dev/brand-logos` writes the logo
  files, the favicon and the link preview (`docs/images/social.svg`, `social.png`).

- Every time in UTC (`processcraft-sdk` 0.20.0): PlantCraft and the SDK store and answer
  times as `2026-10-23T14:05:09.123Z` (`processcraft_sdk.utc`: `utc_iso`, `normalize_times`),
  whatever the server's time zone; text order is time order, so SQL filters compare them right
  across offsets (before, a row written at `-03:00` and a cutoff at `+00:00` could compare
  wrong). Existing rows are rewritten once at start (`utc-times-2026-10-23`, in PlantCraft's
  database and in each app's database through the SDK's `Database`). `PROCESSCRAFT_TIMEZONE`
  (the plant's zone, UTC by default) decides where "today" begins for due dates. Ruff's `DTZ`
  rules now refuse a time without a zone. `dev/revendor --sdk-only` moves apps to a new SDK and
  leaves each app's `@processcraft/ui` as it is.

### Added

- **Assistant** in Desk (docs/assistant.md): each person keeps many chats with
  the installation's language model (or an active specialist), each on its own subject, from a
  translation to "plot FIC-101 yesterday". The model reads the plant only through the MCP
  server's read-only tools, as the person who asks (API v1 in the process, a token issued at each
  read); each read is listed under the answer and audited (`assistant.tool`). `show_chart` draws up
  to 6 signals' history with the suite's TimeChart. Limits: `PROCESSCRAFT_ASSISTANT_WORKERS` (4),
  `PROCESSCRAFT_ASSISTANT_DAILY` (300 answers per person), one answer at a time. Specialists no
  longer answer in Messages; Messages links to the Assistant. `@processcraft/ui` 0.27.0: an app's
  **Ask the assistant** opens a new Desk chat about the object (`assistantUrl`) instead of a
  Messages conversation.

- **Desk**, each person's day, is the suite's first screen (docs/desk.md):
  Today (widgets each person arranges: coming days, actions, inbox, checklist, suggestions,
  followed assets, team, plus every app's widgets), Inbox (done and snooze), Calendar (month,
  week and list with FullCalendar; actions, checklist, routines, alarms on followed assets,
  scheduled runs and calendars imported from Outlook or Google, by `.ics` file or, when an
  administrator allows the servers in Setup › Calendars, by link), Routines and Team. **Follow**
  on an asset's page. PlantCraft's pages move under `/admin` and PlantCraft is last in the list
  of apps.
- `@processcraft/ui` 0.26.0: `CardGrid`, the suite's card grid (12 columns, View's sizes,
  react-grid-layout 2.2.4); `WidgetBoard` draws on it: drag by the title, resize from the corner,
  a gear for each card's settings, widgets added more than once, a discreet **Customize**.
  Saved layouts keep positions (`BoardItem`); the old list of ids is still read.
- `@processcraft/ui` 0.29.0: an app outside the family draws the suite's frame too:
  `SuiteShell` takes any app id with `appName`, `AppMark` and `AppLockup` draw a neutral letter
  tile and the manifest's name, and the tab reads "Page · StarterCraft · PlantCraft".
- `processcraft-sdk` 0.22.0: an app outside the suite table passes `processcraft-app check`
  when its prefix, port and uid belong to no row and to no stack service, its uid is between
  10002 and 65533 and its name is not "PlantCraft X" (the platform's installer already allowed
  it). The app template, `templates/app` (StarterCraft), uses it; `run_opcua_demo.py --app
  id=url` starts an app of one's own beside the demo.
- `processcraft-sdk` 0.21.0: `processcraft_sdk.server.search` (`SearchItem`, `search_text`,
  `matches`, `search_answer`) writes an app's `GET /api/search` in the suite's format, and
  `suite_api` answers the frame's `GET /api/search` and `GET /api/queue` probes with "nothing"
  for an app that does not pass its own, so no app answers them with a 404.
- Search the whole suite (`docs/app-standard.md` section 10): Ctrl+K (Cmd+K)
  on any screen, or the search entry at the top of every app's sidebar, finds a point, an asset,
  a dashboard, a block or a person. `@processcraft/ui` 0.25.0 `SuiteSearch` asks every app at
  once (`GET <prefix>api/search?q=`, format `plantcraft-search/1`) and lists the answers by app;
  PlantCraft answers for assets, people, groups and the actions the person sees
  (`GET /api/search`). The apps answer for their own objects as they take ui 0.25.0.
- The suite's work queues in every app's sidebar: `@processcraft/ui` 0.25.0
  `SuiteQueueButton` sums what runs and waits in every app that serves `GET <prefix>api/queue`
  ("4 running · 12 waiting"), turns to attention when the oldest item waited 30 minutes or an
  item failed, and opens each app's numbers with a link to its executions.
- An asset's **Situation** tab: what every app published about the asset,
  its signals and the assets inside it (alarms, Link's diagnoses, models...), worst first and
  by app, with links into each app, the open actions, the latest events and the runs that
  covered it (`GET /api/assets/<id>/situation`).
- `ci/e2e-upgrade.sh` (`docs/operations.md` section 3): a released bundle
  installed with data, updated to what the checkouts build now and rolled back, with a
  fingerprint through the APIs (`ci/upgrade/fingerprint.py`: every list's ids, a closed past
  hour of signal values, the results, the audit log) that must keep everything. Run it before
  every release: `FROM_BUNDLE=<released bundle> make e2e-upgrade`.

- Notebooks (`docs/en/notebooks.md`): Jupyter inside PlantCraft, off until an
  administrator turns it on. JupyterLite with a pruned Pyodide 0.27.6 (numpy, pandas, scipy,
  matplotlib) is built into the image by `notebooks/build.py` (`make notebooks`, pins and
  SHA-256 in `notebooks/pins.json`, about 130 MB) and served at `/notebooks/lite/` to viewers and
  up; nothing is downloaded at run time. `/notebooks?signals=...&start=...&end=...` and
  `?asset=...` write a notebook that already loads them into the person's `PlantCraft` folder
  (`POST /api/notebooks`, audited as `notebooks.create`). The `plantcraft-notebook` package
  (`notebooks/python`, `import plantcraft_notebook as pc`: `signals`, `series`, `value`,
  `assets`, `asset`, `results`, `events`) reads API v1 as the person, in the browser through
  their session and on their computer through an access token: API v1 now accepts `pcat_`
  tokens while Notebooks are on, for reads only. The proxy gives `/notebooks/lite/` alone a
  Content-Security-Policy that also allows `'unsafe-eval' 'wasm-unsafe-eval'`.
- Setup › Audit log (administrators): every row of the central audit log, newest first, by
  period (24 hours to a year) with search, filters per person, app and action, and a CSV download
  (`GET /api/audit`, `GET /api/audit.csv`, at most 5,000 rows; spreadsheet formulas neutralised).
  Sign-ins are audited too: `session.sign_in` (method local, admin, LDAP or OIDC),
  `session.sign_in_failed` (reason), `session.sign_in_blocked` (throttled) and
  `session.sign_out`, each with the address it came from (IEC 62443-4-2 CR 2.8, gap G31 closed).
- Disk forecast: the suite watch keeps an hourly sample of the free disk for 7 days and, after a
  day, says in how many days the disk fills at the current pace (Operations › Suite health,
  `disk_forecast` in `/api/operations/health`). Under 30 days "System" tells the administrators in
  Messages (closed again past 45 days or when the disk stops shrinking).
- Help › Sizing the server (`docs/en/sizing.md`, `docs/pt-BR/sizing.md`): CPU, memory and disk by
  plant size, from the bench's measured numbers, and how to measure a machine.
- The admins hear when a work queue does not drain (Link round 6): `processcraft-sdk` 0.19.0
  `ops.report_queue(now)` puts what an app's queue holds in `GET /api/ops/metrics` (`queue`);
  PlantCraft writes it as `system:<service>.queue_items` and `.queue_wait_min`, and the watch
  opens the incident `queue:<service>` in "Suite health" when items wait and the oldest has
  waited over 30 minutes (two ticks), with its recovery (`docs/operations.md`, section 4).

- A work queue looks the same in every app: `processcraft-sdk` 0.17.0
  `processcraft_sdk.server.queue` (`QueueNow`, `QueueMetrics` keeping a sample every 15 s for
  30 days, `QueueSampler`, `queue_answer`, format `plantcraft-queue/1`) and `@processcraft/ui`
  0.22.0 `QueuePanel` and `QueueSummary` (the numbers of now and the items in the queue, running
  and the wait over 1 hour to 30 days). First used by Link's Executions page and Models'
  simulations (`docs/app-standard.md`, section 6).
- `@processcraft/ui` 0.23.0: a sidebar page may list entries under it (`ShellNavItem.children`,
  `ShellNavChild`), indented and hidden while the sidebar is folded. Models lists its pinned and
  recent projects under Projects.
- Demo (Models round 6): a parameter sweep study, "Level controller tuning" (TankLevelControl
  over 4 gains and 2 integral times, 8 simulations with indicators), ready to compare. The
  simulations an older demo made before studies are made again once, inside studies; the FMU
  export Link uses stays. The example project "Twin models" is now "Link models".

### Changed

- Demo (View round 6): three example dashboards in two folders instead of six in a flat list:
  **Operation** (everyone) holds "Plant overview" (with its public link) and "Control room"
  (three pages turning every minute in full screen, kiosk, shared cursor); **Instrumentation**
  (the Instrumentation and control group only) holds "Loop detail", from View's template. The
  dashboards earlier demos seeded ("Valves under watch", "Furnaces and their twin", the unit
  overview, repeats) are removed while nobody changed them since; edited ones stay.
- The platform is **PlantCraft**: every name a person reads (interface, help,
  installer, documents) says PlantCraft, and the OPC UA plant simulator is the **Simulator**.
  Package names, `PROCESSCRAFT_*` variables, URLs, app ids and the installation folder are
  unchanged. `@processcraft/ui` 0.21.0 (the lockup, `APP_NAMES`, `appFullName`; `appShortName`
  still reads manifests that say "ProcessCraft <module>") and `processcraft-sdk` 0.16.0 (its
  texts; `GROUP_KINDS` gains `department`, `Group` gains `parent_id`).
- Setup keeps only what has no other place (configuration file, corporate sign-in, language
  models, assistant access, email, backups); asset types stay under Assets. Assets › Import
  copies a prompt that explains the asset file to an AI assistant.
- Groups form a tree (department, area, discipline, team); a person may be in several; a
  group's coordinator leads it. Actions go to a person, a group or both, and each person sees
  theirs, their groups' and, as a leader, the groups' below; admins see all. Every group has its
  own conversation, and a new conversation can take a whole group.
- Plant data left the platform: `/data` opens the Historian's sources, or says to install it.
  The help is rewritten around the Overview, Assets, Actions, Messages, groups and Setup.

### Fixed

- The public demo's visitor sees the team's actions again (the groups' rule hid every action
  assigned to a group from it), and PlantCraft answers the frame's queue probe instead of a
  404. Found by the first upgrade test, which also brought three demo journeys up to date.
- `@processcraft/ui` 0.24.1: the queue chart spans its whole window (1 hour to 30 days, ending
  now) even while the history holds one sample, instead of zooming into milliseconds.

- Mac mini deploys no longer drop the whole suite for a few seconds after every merge. The proxy
  was recreated each time because the commit and build time, set before the image's `RUN`, gave
  it new layers. These labels now come last in both Dockerfiles, `ci/macmini/suite-deploy`
  recreates only containers whose content changed, and the proxy waits for a restarting server
  (`lb_try_duration`) instead of answering 502.

### Added

- `@processcraft/ui` 0.24.0, shared charts (Historian round 6; owner, 2026-10-23: charts used by
  more than one app live in the package): the subpath `@processcraft/ui/plot` with `Plot` (the
  suite's one Plotly build; `react-plotly.js` and `plotly.js-cartesian-dist-min` are optional
  peers) and `TimeChart` (lines, quality bands, the user's theme or a fixed one, a solid
  background so the PNG reads, a toolbar slot); `PeriodPicker`, `useBrandTheme` and the pure
  helpers `timeFigure`, `qualityBands`, `bandShapes`, `sharedUnit`, `periodRange`,
  `choosePeriod`, `localOf`, `isoOf`. The platform's unused local `Plot.tsx` is removed.

- `histcraft-gateway` (profile `histcraft`): Telegraf 1.40.2, pinned by digest and bundled like
  `histcraft-db`, reads Historian's MQTT, Modbus TCP and SQL sources and pushes their values to
  `histcraft-collector` (`HISTCRAFT_INGEST_PORT=8186`). Its configuration is written by the
  collector into `data/histcraft/gateway/` (read-only mount, 0600). On `plant` and `demo` only.
  `install.sh` and `bundle.sh` handle `HISTCRAFT_GATEWAY_IMAGE` as they do the database's.

- `dev/snapshot` (`docs/publishing.md`): the suite's public snapshot, one clean commit per
  repository from `main`, written as git bundles the owner pushes to the new repositories. Links
  are rewritten to the new owner, and the owner's own build machine is left out. Gates: words
  that must not be published (from a list kept outside every repository), no secret (gitleaks,
  `.gitleaks.toml` for the tests' made-up keys), a license on every package. Nothing is created
  or pushed.
- `@processcraft/ui` 0.20.0: `AppOverview`, every app's first page drawn like ProcessCraft's
  Overview: the app's name above "Overview", its intro and actions, its notices, then a board of
  the widgets it publishes (and any the page draws) that each person arranges, kept per app in
  ProcessCraft (`/api/home/layout?page=<app id>`, `useOverviewLayout`). `WidgetBoard` gets
  "Restore the default" while customizing (`onReset`).
- AI assistant access (`docs/assistant-access.md`): a read-only MCP server at `/mcp`, off by
  default (Setup › AI assistant access; `PROCESSCRAFT_MCP=off` forbids it). People create their
  own access tokens on their profile and give them to their assistant (Claude Desktop, Claude
  Code or any MCP client). Fifteen tools read API v1 as the token's owner: assets and types,
  signals, values and history, the apps' results (loop health, alarms), events, runs, actions and
  the apps' knowledge texts. Nothing writes; tokens are stored as SHA-256, expire (30 days by
  default) and are revocable; every tool call is audited.

- "Copy as prompt" (`docs/design/copy-prompt.md`): a button that puts a ready prompt about one
  object on the clipboard for the AI assistant the plant allows. Nothing is sent anywhere.
  `processcraft-sdk` 0.15.0 brings the template (`processcraft_sdk.prompts`: what ProcessCraft
  is, the module, the house rules, the question, the parts as fenced blocks, at most 30 000
  characters, and no password, key, address or user name ever) and `@processcraft/ui` 0.19.0
  the button (`CopyPrompt`, with preset questions and a selected-text dialog when the browser
  has no clipboard).
- Setup › Configuration file: **Copy as prompt** for the plant map (`GET /api/prompts/plant-map`),
  to build the map from equipment documents or review a file. It replaces the prompt that the
  sources guide asked people to copy by hand.

### Documentation

- The security guide matches 0.3.0 and after: language models (off by default, `PROCESSCRAFT_LLM`,
  reached over the plant conduit), the per-route permission test, signed releases for x86_64 and
  arm64, scheduled backups with the Historian's incrementals and the restore drill, and what the
  audit log still lacks (sign-ins, a page to read it: G31). Its Portuguese version is a full
  translation again (it had been a stub since 2026-10-19).
- The firewall table of the offline install lists the two flows that stay closed until turned
  on: a company language model and people's AI assistants (`/mcp`, through the same proxy).
- README and How we build: Copy as prompt and the MCP server as the ways the suite is used with
  AI; the Portuguese summary says why the suite is vibe coded.

### Security

- The MCP server and the Assistant take out of every tool answer the results, events, runs and
  texts of apps the person may not open (`mcp.only_apps`); API v1's `/results` and `/events`
  answered them to anyone who may read the plant.

- Passwords of people who sign in here are stored as **Argon2id** (`argon2-cffi`, RFC 9106
  low-memory profile) instead of PBKDF2-SHA256 with 240,000 rounds. Older hashes still check; the
  person's next sign-in stores the password again as Argon2id, which ends their other sessions
  once. A password typed to confirm an action inside a session never rehashes.
- `processcraft-sdk` 0.18.0: tokens between PlantCraft and the apps are signed and checked by **PyJWT**
  (`processcraft_sdk.jwt` keeps its functions and errors; `decode` loses the unused `now`). Its
  wheel needs `PyJWT` beside it in each app's lock; tokens are interchangeable with older SDKs.
- Corporate sign-in with OpenID Connect checks the ID token's signature and claims with
  **joserfc** (Authlib's JOSE library) instead of our own JOSE code (`directory/jose.py`).

## [0.3.0] - 2026-10-23

### Added

- `processcraft-sdk` 0.14.0: the settings and the ProcessCraft connection every app wrote for
  itself, once: `server.settings` (`AppSettings` with the common variables, `env_flag`,
  `env_number`, `env_text`, `env_root_path`, `app_key_from_environment`) and `server.platform`
  (`PlatformRuntime`: HTTP client, token verifier, service client, `user_client`, `audit`).
- The suite's health as signals: every minute ProcessCraft writes each service's state, response
  time, CPU, memory, restarts, errors and warnings, the free disk and the backups to the
  Historian's source "System" (`system:<service>.up`...), kept 90 days, so trends, dashboards and
  alarms read them like plant signals. Values wait up to 24 h while the Historian is down; the
  watch and its messages never depend on it.
- "Download diagnostic bundle" on the Health panel and `install.sh --diagnostics`: a zip of
  versions, Docker's view, health, the end of each service's log and the settings with every
  secret replaced, for support. Never databases, plant data or keys; kept 24 h, audited.
- Apps read series straight from the Historian (`processcraft-sdk` 0.13.0): with
  `PROCESSCRAFT_HISTORIAN_URL` (set by the compose file and the app installer from
  `HISTCRAFT_URL`), `signals`, `signal`, `series`, `series_many` and `value` go to the
  Historian's own API v1 reads (same shapes and access rule: a verified token at viewer level or
  above), saving the hop through ProcessCraft. A Historian without them, or out of reach, leaves
  the reads to ProcessCraft (`docs/api-v1.md`, "Direct reads from the Historian").
- API v1 passes the Historian's series and batch answers on as they came, without parsing and
  writing the JSON again.
- ProcessCraft answers from several processes (`PROCESSCRAFT_WORKERS`, default `auto`: 2 to 4
  with Historian as the data layer, 1 otherwise), so many people at once no longer wait in one
  line. Blocks that write open with `BEGIN IMMEDIATE`; the first start, the suite watch and the
  email outbox run in one process at a time (`processcraft.ops.workers`, `docs/operations.md`
  section 6). The image runs `python -m processcraft.api.serve`.
- Historian's collector runs as its own service, `histcraft-collector`; `histcraft` answers the
  pages and API with `HISTCRAFT_COLLECTOR=off`. An update or restart of the server no longer
  stops the recording. An existing installation gets it with its next update.
- Backups take the Historian's database by blocks (PostgreSQL 17 `pg_basebackup`), no longer
  as a `pg_dump`: a full copy about once a week and, on the other days, an incremental one with
  only the blocks changed since. Each is checked by `pg_verifybackup`; a restore and the restore
  drill join the chain with `pg_combinebackup`, check the result and start it on a new timeline,
  after which the next backup is full. Retention keeps every backup a kept one builds on, and the
  Backups page shows each backup's Historian part (full or incremental, and on which backup).
  Backups taken with a `pg_dump` still restore. `histcraft-db` runs with `summarize_wal=on`.
- Bundles for 64-bit ARM servers: one bundle per processor,
  `processcraft-<version>-linux-amd64-bundle.tar.gz` and `...-linux-arm64-...`
  (`make bundle ARCH=arm64 DOCKER_BUILD_FLAGS="--platform linux/arm64"`). `install.sh` refuses a
  bundle for the other processor unless `--allow-emulation`.
  With Docker's containerd image store a bundle saves only its processor's part of each image;
  `bundle.env` names the digest PostgreSQL was saved under (`HISTCRAFT_DB_IMAGE`), and
  `install.sh` writes it to `.env` for `histcraft-db`.
- Signed releases with a real publisher key (ProcessCraft, key id `af2643fa16867976`, in
  `deploy/trusted-publishers/`). A first install now checks the signature too (it used to check
  only `SHA256SUMS`), against the key the bundle carries or `--publisher-key FILE`, and prints
  the key id; an unsigned bundle needs `--allow-unsigned`. The archive's hash is signed in
  OpenSSH's format (`.tar.gz.sha256.sig`), so the download is checked with `ssh-keygen -Y verify`
  before it is unpacked. An installation that trusts no publisher yet checks its first signed
  update against the bundle's key and says so.
- API v1: every signal says its source's kind in `source_kind` (`opcua`, `pi_web_api`, `csv` for
  laboratory analyses and manual entries, `derived`), so apps can judge a sampled signal by its
  own rules. `processcraft-sdk` 0.12.2 serves it from `FakeProcessCraft` and derived signals.
- Demo: an "On call" group (coordinated by the operations supervisor) and Alarms policies with
  hours and escalation: U-100 and U-200 operations escalate to their coordinator after 15 minutes
  without acknowledgement, instruments go to the day shift, on call hears critical alarms at
  night and at weekends (America/Sao_Paulo). A re-run updates the policies an older seed made.

### Security

- A plant source's saved password only goes to the server it was typed for, as the directory's
  and the email server's do: changing an added OPC UA or PI Web API source's address or user, in
  Setup or in its connection test, asks for its password again (security audit 2026-10-23).
- A saved secret only goes to the server it was typed for: changing the directory's address or
  bind account, the identity provider, or the email server's address, port or account asks for
  the LDAP bind password, the OIDC client secret or the SMTP password again. Before, an admin of
  ProcessCraft could send the company's service password to a server of their own with one test
  (security audit 2026-10-22).
- Email notifications: an address with a line break in a person's own profile stopped the outbox
  for everyone after that person (the email header refused it with an error the outbox did not
  expect). Addresses in profiles, the sender and the test email are now one plain address (no
  spaces, line breaks or list separators); a title's line breaks become spaces in the subject; an
  email that can never go fails alone and the others still go (security audit 2026-10-22).
- `processcraft-sdk` 0.12.1: redacting secrets from a log line took time growing with the square
  of its length (2.6 s for a line of 8,000 letters, holding the app's only process), so one
  request with a long address could stall an app. The secret names now start where a word
  starts and a line is redacted in linear time (8,000 letters: under 1 ms).

### Removed

- The compatibility layer for CPMCraft, DataCraft and TrendCraft (renamed or merged into Link
  and View on 2026-10-20; every installation has moved): `install.sh` no longer accepts
  `--with-cpmcraft`, `--with-datacraft` or `--with-trendcraft` nor moves their profiles and
  data, the proxy no longer redirects `/cpm/`, `/quality/` and `/trend/`, and
  `LINKCRAFT_MIGRATE_FROM_CPMCRAFT` / `_DATACRAFT` are gone from the compose file and `.env`.
  ProcessCraft Twin's move into Link stays until every installation has made it. People's access
  under the old ids still opens the new apps.
- Routes nothing called any more: `GET /api/data/connection`, `/api/data/assets` and
  `/api/data/signals` (the pages read each source's own signals), `POST
  /api/data/sources/{id}/signals/unbind` (the asset page unbinds) and `GET /api/messages/unread`
  (the conversation list and `/api/v1/me` carry the count). Unused helpers went with them, and
  the unused `gunicorn` dependency.
- `processcraft-sdk` 0.13.1: `FakeProcessCraft`'s default app is `linkcraft` (was `cpmcraft`) and
  the examples name current apps.

### Changed

- ProcessCraft Twin leaves the suite: its twins run in ProcessCraft Link as
  algorithms on assets. The installation, bundle, menu, CI runners and suite registries no longer
  carry `twincraft`; `/twin/` opens Link's algorithms and `--with-twincraft` means LinkCraft. An
  upgrade turns the `twincraft` profile into `linkcraft` and LinkCraft takes in Twin's uploaded
  models and twins once (`LINKCRAFT_MIGRATE_FROM_TWINCRAFT`); `data/twincraft/` stays for a
  rollback. People's access to Twin opens Link. The demo story creates Link's model examples of
  the plant, publishes the Furnaces FMU from Models to Link and its "Furnaces and their twin"
  dashboard reads `linkcraft.out_model_deviation` (an older demo's dashboard is repaired). The
  benchmark's twin step runs a Link model algorithm on the bench loops.
- `@processcraft/ui` 0.18.0: one browser tab for the whole suite. The shell names every tab page
  first, then the app, then the brand ("FIC-1003 · Link · PlantCraft"; the platform's home is
  just "PlantCraft"), from the page's own heading (`useTabTitle`, `tabTitle`; a page can set
  `data-tab-title` on its `<h1>`), and every tab shows the platform's mark as its icon
  (`BRAND_FAVICON`). The brand is written once, `BRAND_NAME` in `appMarks.ts`; the rest of the
  interface keeps its current name until the code is renamed.
- HistCraft's database (`histcraft-db`) is sized for its container: `shared_buffers` 512 MB,
  `effective_cache_size` 1 GB, `work_mem` 16 MB, a larger WAL and an autovacuum that visits the
  archive's chunks sooner (PostgreSQL's defaults assume 128 MB). Its memory limit goes from 1 GiB
  to 2 GiB (`HISTCRAFT_DB_MEMORY`; `HISTCRAFT_DB_SHARED_BUFFERS` and `HISTCRAFT_DB_CACHE_SIZE`
  follow it). The 2026-10-21 bench peaked at 985 MB of the old 1 GiB.
- Platform events older than two years are dropped, at most once an hour as new events arrive
  (`PROCESSCRAFT_EVENT_RETENTION_DAYS`, `0` keeps them all); the table grew without end. The
  audit log is kept whole.
- `@processcraft/ui` 0.17.0: `BlockEditor` takes `inspectorTools`, the app's own tools for the
  selected block shown in the inspector under its name (ProcessCraft Link's Calibrate on a
  Deviation (T²) block). Fixed: an object parameter showed as "[object Object]" in the inspector;
  it is edited as JSON text like any other structured value.
- Demo: Alarms starts from a rationalized list instead of a high and a low on every loop: 25
  alarms with owners (the operations groups of U-100 and U-200, instrumentation, process
  engineering, the shift supervisor), disciplines and their cause, consequence and action, plus
  one raised by Link's loop-health verdict; three notification policies (each unit's operations
  from high, by email, with reminders; instruments and analyzers) and a silence on U-300.
- `@processcraft/ui` 0.15.1, `BlockEditor` after its first review: the palette's libraries fold
  (all folded at first, one open at a time; a search opens those it finds blocks in); a test run
  shows as a light on each block (green, amber, red, grey) with what the block said in a tip on
  hover, instead of a line under it; the values on the wires wait behind a "Values on wires"
  switch; selecting a block shows, under "Last test", what entered it on each wire and what left
  it, series drawn over the window (with the value under the pointer), modes as a strip, numbers
  and verdicts as they came.

### Added

- Assistant references `algorithm:<app>/<id>` and `block:<app>/<id>`: an app's algorithms and
  blocks open the assistant with that app's specialists, like its runs (ProcessCraft Link
  publishes both to `/knowledge`).
- `@processcraft/ui` 0.15.0: `BlockEditor` (`@processcraft/ui/blockEditor` and
  `blockEditor.css`), the one diagram editor of the suite (ProcessCraft Link's algorithms,
  ProcessCraft Models later): a palette of blocks by library with search, drag or click to add;
  typed ports colored by type, the inputs a wire can enter lit while it is drawn and a refused wire
  said why; an inspector with the block's parameters as a form from their schema, its wiring, its
  outputs with what the last test carried and whether they are recorded, and its descriptions;
  the check's problems linked to their blocks; undo, redo, copy, paste, delete, Arrange and fit,
  with the usual keys. The pure model (`blockModel`) is tested apart. `@xyflow/react` 12 is an
  optional peer dependency: only an app that shows the editor installs it.

### Fixed

- Found by the end-to-end test of the whole suite on a fresh install (2026-10-22):
  - `processcraft demo seed` failed on Link and View: it still saved the "Valve health" protocol
    in Link's 0.2 form (`PUT /api/profiles`, gone in Link 0.3) and drew View's dials one row high
    (View asks for two). The demo's Valve health is now a copy of Link's Control valve algorithm
    with a Message block on its verdict, and the dials are two rows high.
  - The Overview's "Data connections" said "No news" for every source while the Historian showed
    them connected: HistCraft's data API names the collector's view `status`, not `state`.
  - An action's history showed an empty first line; it reads "Created the action".
  - `install.sh --dev --all-apps` turned on no app: in a source checkout the apps are the ones
    whose image is built locally.

- `BlockEditor`: the output ports' circles sat one row below their names (React Flow's `source`
  class picked up the base styles' `.source` margin).
- `processcraft-sdk` 0.11.1: an optional input wired to a block that had nothing to give (no
  data) now counts as not wired, so the block runs on the inputs it has; it is skipped only when
  none of its wired inputs has a value, or a required one has none. A parameter whose default
  comes from a factory (a list) shows that default in `describe_block` instead of failing to
  serialize.

- `processcraft-sdk` 0.11.0: blocks and algorithms (`processcraft_sdk.blocks`, `docs/blocks.md`).
  A block declares typed inputs and outputs (series, state, number, result, intervals),
  parameters and descriptions in one format; an algorithm is a diagram of blocks, checked
  before it runs (types on every wire, required inputs, no loops, an output) and run in order
  with the standard library's `graphlib`, a failing block leaving only the blocks after it
  without a value. The same descriptions feed the editor and the assistants (`block_markdown`,
  `algorithm_markdown`), and `check_block` / `check_algorithm` hold them to the format.
- Derived series carry a `description` (`PUT /api/v1/series`), listed with the signal like a
  plant signal's.
- Groups of people (`/users/groups`, `/groups/<id>`, `processcraft/groups`): a name, a kind
  (area, discipline or team), an optional asset (the area it covers), a coordinator who keeps
  the members, and the members. A person's page lists their groups. Every app reads them through
  API v1 to name an owner or the recipients of a notification (`docs/groups.md`).
- Notifications (`POST /api/v1/notifications`, `processcraft/notify`): an app notifies people
  and groups; each person gets a message from the app in Messages (one conversation per app,
  with the priority and a link) and, optionally, an email. Setup › Email sets the plant's SMTP
  server (off by default, password beside the database); each person chooses in their profile
  whether they want email and from which priority. Emails wait in an outbox, go out as one digest
  per person and at most 20 per hour (`docs/notifications.md`).
- API v1: `GET /api/v1/people`, `GET /api/v1/groups` (no email addresses ever leave the
  platform).
- `processcraft-sdk` 0.12.0: `people()`, `groups()`, `notify(...)`, `FakeProcessCraft` groups and
  notifications.
- `@processcraft/ui` 0.16.0: `RecipientPicker` (people and groups, one or many).
- Demo: eight people with full profiles and six groups (U-100 and U-200 operations, process
  engineering, instrumentation, electrical and mechanical maintenance).

- Actions: a checklist per action (items with who and by when, ticked by editors, kept in the
  history); "#" mentions of assets, people and runs in the description and comments, shown as
  links; every person's name opens their page. Cancelled is shown as **Archived**.
- People (`/people/<username>`, `/people/me`): a profile each person keeps (job title, internal
  or external, organization, email, phone, unit) with their open actions; admins also see the
  access. Users: a role per app (e.g. Viewer in Historian, Editor in Link), carried in the token.
- Setup > Language models: several providers, each with a name, a format, an address, a key and
  the list of models it serves, with a test per model; one is the installation's default and
  each specialist answers with the default, a provider and model chosen for it, or scripts.

- Assets › Import and Assets › Export (`/api/asset-file`, `processcraft/platform/assetfile.py`):
  the tree alone (assets, records, signal references, relations) in ProcessCraft's JSON, Excel,
  CSV, ISA-95 B2MML (EquipmentInformation) and PI AF XML, the whole plant or one branch. An
  import opens a review page: the file as a tree, each asset new, changed, unchanged or with an
  error, with the name, type and place editable and any row left out; nothing is written while an
  included row has an error.
- An asset's Signals tab says where else each signal is used (`used_in` on `/api/assets/<id>`):
  one signal may be referenced by several assets, a loop's PV is also its transmitter's.
- `processcraft-sdk` 0.10.1: starter types vessel, column, heat exchanger, furnace, compressor and
  tank, with their attributes and signal roles.
- The asset type editor: about 150 icons in groups (process symbols first) behind a "+" with a
  search, and a guide to each attribute field (key, name, data type, unit, required, inherited,
  signal roles).
- The demo plant is a refinery with four units, fourteen areas and the equipment the loops sit
  on (tanks, pumps, exchangers, furnaces, columns, reactors, drums, compressors); each loop
  has its transmitter and control valve, with controls, measures and feeds relations.

- Overview widgets (`docs/widgets.md`): the first page is the Overview, a page of widgets each
  person arranges (`/api/home/layout`); ProcessCraft's own (needs attention, open actions, apps
  online, data connections, worst first, your apps) and those each installed app publishes
  under `<prefix>/api/widgets`, so nothing depends on a given app being installed.
- Setup > Backups: the backup and restore drill schedule moved from Operations, which now only
  watches and acts (the two overlapped).
- `@processcraft/ui` 0.11.0: `DataTable` (sort by any column, filter, pages of 25/50/100, a
  checkbox per row with actions on the rows ticked) and `WidgetBoard`; Help, the tour and About
  in the user menu, which closes on a click outside; the apps in the order data flows
  (Historian, Link, Models, Twin, Alarms, View last).
- `@processcraft/ui` 0.11.1: the Overview's widgets keep their own height and fill gaps, so a
  short widget beside a long list no longer leaves an empty box. The launcher, apps online and
  every other list of apps follow the suite's order too. `NextSteps` takes a `limit` (Setup shows
  all five of its pages, Backups included).
- `@processcraft/ui` 0.12.0: the suite's time chart (`timeChartLayout`, `timePlotConfig`,
  `timeHover`, `TIME_WINDOWS`, `windowLabel`): one layout, hover and set of buttons for every
  trend, so View's Trends and a point's page in the Historian draw the same chart.
- `@processcraft/ui` 0.13.0: a `DataTable` column can carry `filter` (`true` lists the values
  found in the rows; `{options}` fixes the list; `value` says what a row is filtered by), shown
  as the suite's MultiSelect (checkboxes with counts) beside the search, with "Clear filters"
  and "N of M"; `initialFilters` opens the table already filtered; `rowClassName` styles a row. The user menu opens the person's profile (ProcessCraft's
  `/people/me`; `onOpenProfile` inside ProcessCraft), and `platformUrl(apps, page)` links any
  ProcessCraft page from an app. Additive: tables without `filter` behave as before.

- The installation's language model (Setup > Language model, `/api/language-model`): one
  connection, the company's own model or a local one, that every specialist answers with; the
  OpenAI chat completions format (vLLM, Ollama, LM Studio, Azure OpenAI, gateways) beside
  Anthropic's Messages API, with tool calls in both; a test button. A specialist answers with
  the installation's model, a model of its own or scripts only (`model.source`).
- `app:<id>` references: a whole app, for the assistant page an app gives itself.
- Home at a glance: an **Alarms** count and an **Open actions** count, each a button to its
  page; the alarms page (`/attention`, `/api/home/attention`) with status and app filters; a
  status panel (`/api/home/status`) with each app online or not (the suite watch, else its key
  used lately) and each HistCraft connection.
- Actions as a Kanban board by status, with how long each card has been there
  (`status_since`) and drag to move; each action on its own page instead of a side panel.
- The asset page redone in tabs (overview, signals, inside, relations, actions, history), the
  signals as one table by role; the "Open in" links are gone.
- `@processcraft/ui` 0.10.1: tour texts of the new Home and asset page.
- `@processcraft/ui` 0.10.0: `MultiSelect` (a filter of several values in a dropdown, with
  counts) and `AssistantPanel` `inline` (the assistant as a page) with "New conversation".

- Knowledge (API v1 `/knowledge`, SDK `put_knowledge`, `delete_knowledge`, `knowledge`): the
  apps explain their objects in text (a protocol's meaning, inputs, outputs and assistant
  instructions; a run's report) and the specialists answer from it, with two new model tools
  (`search_knowledge`, `recent_runs`).
- The assistant of an app (API v1 `/assistant`, `@processcraft/ui` 0.9.0 `AssistantButton` and
  `AssistantPanel`): "Ask the assistant" on a run, a protocol or a loop starts a conversation
  with a specialist about it, kept in Messages.
- `run:<app>/<run id>` references resolve to the run; a reference of a kind no module owns
  resolves to the text an app wrote about it. A bare mention may hold `/` and `:`
  (`#run:linkcraft/42`).
- Setup page (administrators): connect the data, map the plant, install the apps and give people
  access, the four steps that were on Home, with asset types, the plant map import, app keys and
  operations beside them.
- Home lists what needs someone across the apps, worst first (`/api/home` `attention`: alarm,
  then warning, lowest score first; an asset opens on its page here), then the follow-up of the
  actions and the apps.
- `@processcraft/ui` 0.8.0: menu entries can carry a `section` (a heading over each group); the
  routine (`JourneyPath`) folds to one line, remembers it per page, and starts folded once every
  step is done; tour texts for Link's Results and export, View and the new Home.

### Changed

- `@processcraft/ui` 0.14.0: Help is the last entry of every app's pages in the left sidebar (the
  app's own guides, inside the app), no longer in the user menu; the tour's last step says so.
- Setup shows only its tiles, in three groups (plant and data, people and apps, settings); the
  four-step path and the intro text are gone. "Import plant map" is now
  **Configuration file** (sources, signals, assets and loops); App keys explain what they are for.
- Dialogs keep the same side margins for their fields as for their header and footer.
- The menu has two groups: Work (Home, Assets, Actions) and, for administrators, Administration
  (Setup, Users, Apps, Operations). App keys is a tab of Apps (`/apps/keys`; `/app-keys` moves
  there).
- Dashboards is shown as **View** (`dashcraft`; ids, repository and `/dash/` unchanged).

## [0.2.0] - 2026-10-21

### Added

- The suite watches itself (`processcraft.watch`, `docs/operations.md` section 4): the installer
  writes Docker's view of every service and the free disk every 30 s (`metrics.json`); when a
  service stops, fails its health check or restarts in a loop, the disk runs low, no good backup
  was made for 26 h or a restore drill fails, the robot user "System" tells the administrators in
  the conversation "Suite health", and again when it is back. A banner and the Health panel of
  the Operations page (`GET /api/operations/health`) show it too.
- `processcraft-sdk` 0.10.0, the base of backup, updates and monitoring (`docs/operations.md`):
  JSON logs to rotating files with secrets redacted (`processcraft_sdk.server.logs`), a request
  id and one log line per request, `GET /api/ops/metrics` in every app
  (`processcraft_sdk.server.ops`), the schema stamp that keeps an older app from opening a newer
  database (`Database(path, version=...)`, `SchemaTooNew`), and the `[backup]` table of
  `app.toml`.
- `processcraft-app check` holds every app to `CHANGELOG.md`, `[backup]` and the suite's logs.
- ProcessCraft logs as JSON to `data/processcraft/logs/processcraft.jsonl`, with request ids.
- Backups while the suite runs, checked before they count (`install.sh --backup`), every night at
  02:00 with retention; restore with an automatic return when the suite does not come back
  (`--restore NAME`); a weekly restore drill into an isolated copy (`--drill`).
- Safe updates: `release.json`, `RELEASE-NOTES.md` and a signed `SHA256SUMS` in every bundle;
  `install.sh` checks signature, versions and disk with the installed version, backs up first,
  verifies every service after the update and returns to the old version by itself when one is
  not healthy; `--rollback` restores the backup taken before the last update.

- The Backups page for administrators (`/operations`): back up now, check a backup, the restore
  drill, restore with the password and the backup's name typed again, the schedule, the
  installed version with its release notes and the last update, the history of operations.

### Changed

- `install.sh --rollback` returns to the version before the last update through its verified
  backup (installations of 0.1.0 keep the earlier stop-and-copy rollback).
- The suite is 0.2.0 (ProcessCraft and every app), so that `install.sh` treats a 0.1.0 server as
  an update: it backs up first, checks the new version's health and can roll back. A bundle of
  the same version only applies its settings again.

### Fixed

- The restore drill no longer fails on every real installation with "installer mounts the
  Docker socket": its isolation check now skips the installer, which the drill never starts.
- `make bundle` stops with an error when HistCraft's database image or the Models runner image is
  missing, instead of warning and shipping a bundle without that app.

## [0.1.0] - 2026-10-20

### Added

- The platform (people and access, the asset tree, sources and signals, results and events,
  messages and specialists, the Apps page and its installer), `processcraft-sdk` 0.9.0 and
  `@processcraft/ui` 0.7.0, and the offline bundle with `install.sh` (backup before an upgrade,
  `--rollback`).
