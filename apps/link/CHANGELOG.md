# Changelog

What changed in each version of PlantCraft Analytics (`linkcraft`), newest first
([Keep a Changelog](https://keepachangelog.com/en/1.1.0/)). An update reads it before it starts
(PlantCraft `docs/operations.md`).

## [Unreleased]

### Added

- **Days to the limit.** For loops whose health is falling, a line fitted to the last 14 days
  (6-hour means) says how many days are left until the health reaches the alarm limit (50). The
  forecast is shown only when the line fits (R² of at least 0.5) and the limit is less than a year
  away. `GET /api/loop-days-to-limit` lists the soonest first, and so does the widget "Analytics:
  closest to the limit" (`engine/days_to_limit.py`).
- **Two signal checks, rate of change (`sq_rate`) and transmitter fault levels (`sq_ne43`).**
  Rate of change counts the changes, measured over at least a minute, that are faster than the
  process can move: an absolute limit per minute, or half of the range per minute by default. NE 43
  reads a 4-20 mA signal on its range as NAMUR NE 43 does. 3.8 to 20.5 mA is measurement, and
  3.6 mA or less, 21 mA or more, is the transmitter reporting its own fault: any fault level is a
  warning, over 1% of the values is bad, and saturation beyond the measuring range is a warning.
  Both need the signal's limits (or, for the rate, a limit of its own), and otherwise do not apply.
- **Loop-hours lost by cause.** Every monitoring round adds the part of its window no earlier
  round on the loop covered, split by cause: out of normal mode, output at a limit, oscillating
  and bad signal (missing or frozen PV). `GET /api/loop-losses?days=&until=&group_by=area|loop`
  sums them by area or loop over any period up to 400 days; the widget "Analytics: loop-hours
  lost, 7 days" shows them by area on the Overview and on Desk.
- **Effective control**, a composite score per loop: the share of the time in normal mode x
  inside its operating band x with the output off its limits, from the loop's own methods (a part
  it does not measure counts as 1). `GET /api/loop-effective-control` and the widget "Analytics:
  effective control" list the lowest first.
- **Source quality, a signal check (`sq_source_quality`).** It shows how much of the window the
  source itself marked bad, substituted or uncertain, per signal, from the per-sample quality
  PlantCraft returns (OPC UA, PI and Canary keep one with every value). Bad or substituted time
  over 1% of the window is a warning and over 5% makes the data unusable. Uncertain time is a
  warning at most. On a source without quality the check does not apply. Signal quality runs it
  on number and text signals.
- **The loop page shows where the controller output spent the window**, as the share of the
  window in each 5% band. A loop that lives near 0 or 100% is saturated, and one squeezed into a
  few percent has little room left.

### Changed

- A round hands each loop only its own signals' samples. It read 50 loops at once into one
  frame of all their times and gave every loop its columns of it, so on a raw day each loop's task
  carried every other loop's times as empty rows (99.5% of a 50-loop, 200-signal batch). Building
  and shipping a batch's tasks went from 9.8 to 0.36 s, 1154 to 24 MB pickled to the compute
  processes, and 896 to 20 MB of peak memory (`ci/bench/reads/roundframes.py`), with the same
  results. A loop whose signals start later or stop earlier than the rest of its batch now gets
  the result it gets when it runs alone.
- History keeps a configurable time (`LINKCRAFT_HISTORY_DAYS`, default 90 days) and, past
  `LINKCRAFT_HISTORY_FULL_DAYS` (default 14), only the last point of each hour per loop, and per
  signal for good checks (every problem verdict stays). The hourly upkeep thins at most a day per
  pass (about 2 s for 205 loops and 821 signals), so a large existing file is worked down over
  days without holding the database. With 2050 loops and 8214
  signals the file grew without bound (F9, 2.5 to 18.5 GB in about an hour of replay); it now
  levels off. Freed space is reused, and the file only shrinks after `VACUUM`.
- The Overview keeps its answer 3 s per asset scope: with 50 people on it during a round its p95
  went from 2.0 to 0.15 s (0.6.0 load test C4 with an account per person).

### Fixed

- A round or the signal checks that could not reach the plant's data (the Historian restarting,
  for one) are tried again in 30 s, then 2 min, as one loop's run already was, instead of ending
  in an error until the next occurrence (0.6.0 load test C6, 2026-10-31).

## [0.5.1] - 2026-10-30

- Suite 0.5.1: `plantcraft-sdk` 0.79.0 and `@plantcraft/ui` 0.89.0, with the new look (the PC valve logo, Steel Blue and the new app marks).
- The app's card, guides and the site describe it as scheduled monitors, diagnostics and KPIs for signals and control loops.

### Changed

- Block code opens in the suite's Python editor (`@plantcraft/ui/codeEditor`); Analytics' own
  copy of it is gone.

## [0.5.0] - 2026-10-27

### Changed

- **A plant model example runs every hour** on a monitor named "<model>: model beside the
  plant".
- **The Overview only shows**: "Check signals now", "Run the loop monitor
  now" and "Open dashboard" are gone from its top, and so is the summary the page read only to
  draw them. A run starts on Monitors.
- **The health map is every result, by area**: assets of any type (a control loop is one of
  them) and signals, under "assets and signals", not loops apart. A square of an algorithm's
  result on an asset names the algorithm.
- **Saving a method's defaults is a new version** with a required "What changed". The page lists
  every version (who, when, the values that differ from PlantCraft's), puts an older one back in
  use, and deletes the ones not in use (`GET`/`DELETE /api/methods/<id>/defaults/versions`).
- **Every control loop block duplicates**: the copy starts by running the original on its wired
  signals. An optional parameter left empty in a copy takes the original's default.
- **Every block reads What it does, How to read it, Formula**; the Combine and Judge blocks gained
  their formulas. The block drawing keeps every port beside the box (ui 0.76.0).
- **No button repeats the side menu**: Results leaves Monitors and a monitor's page, Monitors
  leaves Results and the queue.
- **An algorithm's page works like a block's**: its parameters change on Inputs and outputs and
  are saved as the next version, with a name and a required "What changed"; "Change inputs and
  outputs in a new version" opens the diagram. Who answers for it and where it runs moved from
  Versions to a new Settings tab. The notice about algorithms copied from Twin is gone.
- **Defaults cascade: block, then algorithm, then monitor.** A monitor on assets lists every
  parameter of its algorithm's blocks with its value and where it comes from, and sets its own
  (`node_parameters` on `POST`/`PATCH /api/schedules`, applied on top of the algorithm's diagram
  when it runs).
- **The loops' round is "Control loop performance"**, renamed at start where it kept an older
  default name.

### Fixed

- **The Monitors widget and the Monitors list read an index, never the runs' rows**: the newest
  run of each target comes from covering indexes (`idx_jobs_schedule_latest`,
  `idx_jobs_kind_latest`), and the latest results' cache stamp from a write counter instead of
  every summary's length. On the Mac mini, cold reads of ~7 KB rows through Docker Desktop's
  mount cost 2 to 3.6 s.
- **The Monitors widget and Results open in under a second** instead of 4 to 12 s on the Mac mini:
  each monitor's newest run per target is one row per target straight from SQLite
  (`JobStore.latest_finished`, index `idx_jobs_schedule_subject`); before, every monitor read up
  to 2,000 whole runs and decoded their JSON to keep about 25.
- **The engine gives back the memory a round frees.** After each round, replay or asset run, and
  every minute, the engine hands the heap pages Python freed back to the system
  (`processcraft_sdk.server.memory`, processcraft-sdk 0.72.0). glibc kept them: at 2,050 loops
  the engine sat 22 % above what it used, and the soak read it as a slow climb.

- **The Analytics home stays fast with months of rounds.** Its week of loops and of signal checks
  read every row of the week (2 million loop health points and 5 million verdicts at 2,000 loops
  and 8,000 signals) and took 30 s after a month (`ci/bench/age.py`), or failed once SQLite's
  sort outgrew the 64 MB `/tmp`. Each closed day is now summed up once (`subject_health_days`,
  `quality_days`), so a load reads 6 small days and today: 1.5 s. The verdicts get an index by
  time, built once on the first start after the update (minutes on a large database).

### Changed

- **Run and monitor widgets say what their time is**: "Started 5 min ago", "Last run 2 h ago"
  under the name, instead of a bare time (SDK 0.76.0).
- Loop finding events (`linkcraft.finding.opened` and `.closed`) carry `method_name` beside
  `method_id`, so a report that counts findings by method names it.

### Security

- **Asset scope (decision D2).** A person who sees only part of the plant (PlantCraft's token claim
  `assets`) sees only its loops, results, runs, executions, signals and asset pages; any other
  answers 404. `processcraft-sdk` 0.66.0.

### Added

- **The Overview answers which loops and signals are bad now, and where.**
  Two new widgets: `in-alarm-history` (columns: loops and signals that ended each of the last 14
  days in alarm and in warning, from `subject_health` and `quality_history`) and `health-map`
  (tiles: every loop and signal by the area of its asset, each square opening its page). The
  default board is results by status, the 14 days, the health map, the worst results, the
  monitors and the queue; needs attention, last run, one result and latest runs stay served
  and can be added. Results by status takes an 8 × 2 size (it was 6 × 2). `quality_history`
  gets a time index. processcraft-sdk 0.69.0, @processcraft/ui 0.72.0.
- **A new plant's first step: "Monitor the loops" (`[[contributes.start]]`, processcraft-sdk
  0.65.0).** Once an administrator applies an import of assets in PlantCraft, Analytics reads
  its loops as that person and queues their first monitoring round (`POST
  /link/api/start/analyze-loops`); a round already waiting is not queued twice.

### Fixed

- **The Queue panel no longer slows Analytics down when many people are in.** Every page of the
  suite asks every app's queue and the sidebar asks again every few seconds; Analytics built its
  answer each time (about 110 ms of counts and job rows), and with 100 people at once that was
  most of its time (p95 18 s). The answer is kept 5 seconds, read again at once when something
  is queued or cancelled here: 17 times more requests on the same CPU (load test 2026-10-27).

- **Signal checks on the suite's compute workers as fast as here.** The cloud bench's 8,210
  signals took 257 s on the workers against 64 s in the app. A float series crossed value by
  value (15 ms and 250 KB a signal of a day at 10 s; now its bytes, 1.4 ms and 181 KB, loops'
  data too), and a batch of 200 signals went as two tasks of 150 and 50: each chunk is now a
  task of its own, as many as `LINKCRAFT_COMPUTE_SLOTS`, with two batches out at once. A naive
  time index crossed value by value too (12 ms a signal), and four threads pack the tasks (gzip
  took a tenth of a second a task in one thread). On the same stack, without rounds beside it:
  182 s on the workers, 158 s in the app.

- **A plant of thousands of loops no longer runs Analytics out of memory (load test,
  2026-10-27).** A round sent every loop's task to the compute workers at once and held all
  their data: with 2,050 loops the engine passed its 4 GB limit in 90 s, was killed and started
  the round again, without end. A round now keeps at most 200 loops out at once (memory stays
  near 1.6 GB). The tasks a stopped engine left on the workers are cancelled when it starts again,
  so the round it resumes is no longer queued behind thousands of orphans.

- **Times on the plant's clock.** The signal page's charts and quality bands
  draw in the zone every page shows (they drew UTC); the results, loop and weekly PDFs write
  their dates and windows in the installation's zone, without "UTC"; a one-off monitor says its
  moment as a time, not as ISO text. SDK 0.62.0.
- **No more restarts on Docker Desktop and no task too large for a worker** (processcraft-sdk
  0.64.0). On macOS and Windows the database uses the rollback journal instead of WAL, which
  crashed the app with a bus error under load (rounds, replays, the demo seed). A batch of
  analyses larger than a compute task takes (48 MB) goes as several tasks; one analysis larger
  than that fails with the reason instead of failing its whole batch.

### Security

- **PlantCraft's own blocks take no new version on the site, on the server too (owner,
  2026-10-26).** `POST /api/blocks/<id>/versions` answers 409 for a block Analytics ships
  (Duplicate makes one of the site's); versions a site saved before stay and still run. The
  block's page says `locked`.

### Added

- **Where an algorithm runs (processcraft-sdk 0.58.0; PlantCraft
  `docs/compute.md`, "Environments and sizes").** An algorithm names the environment (the
  executor image with the packages it needs) and the size (small, medium, large: CPUs and
  memory) its runs need, in Versions › Where it runs (a new version; `compute` in its method
  config, no schema change). Its loops' analyses, runs on assets and the editor's Test go to the
  compute workers with them, and only a worker with that environment and room for that size takes
  them. `GET /api/compute/offer` lists what the workers online offer.

- **Analyses and blocks' code on the suite's compute workers (processcraft-sdk
  0.57.0; PlantCraft `docs/compute.md`).** With `LINKCRAFT_COMPUTE=suite` (the suite's compose
  sets it) the loop analyses of rounds, executions and replays, the signal quality checks and
  every call of a site block's code leave this container, which holds the app key, for the
  executor `linkcraft-executor`: Link's own image with no network and no secret, on PlantCraft's
  machine or another (`install.sh --worker`). Loops travel 25 to a task; only plain data
  crosses (`linkcraft.engine.wire`: frames and series as their exact bytes, never pickle), and
  only the functions `suite_compute.CALLS` names run there. A task carries the site block
  versions its diagram uses. The editor's Test runs first (`interactive`), replays last
  (`backfill`), and cancelling an execution cancels its tasks. A round on the workers gives
  the same summaries as a round here (`tests/test_suite_compute.py`). `app.toml` asks for
  `write.compute`.

- **The suite Queue lists Link's executions by name (quick-access protocol, 2026-10-26).**
  `GET /api/queue` adds `url` (the Executions page) and `items`: each execution a person asked
  for (waiting, running or ended in the last 24 hours) and the rounds and replays running now,
  with who asked, its progress and, while it waits, Cancel. The PlantCraft Queue panel shows
  them under Mine and Running now (PlantCraft `docs/quick-access.md`).
- **Round 10 of the owner's review (2026-10-26): libraries, Duplicate and runs on the diagram.**
  - Blocks sit in libraries, not folders: the Blocks page's column lists the libraries under
    "Libraries", and New library (on the page and beside a block's Library in its form) makes
    one of this site (`POST /api/blocks/libraries`), listed after Analytics' own. "Group in the
    palette" left the form.
  - A block's and an algorithm's page: Duplicate beside Download the file (on every block; a
    block that reads what Analytics gives it says why it cannot be copied), New version on the
    Versions tab. A block or algorithm PlantCraft ships shows a closed lock there: it gets no
    new version on the site, Duplicate makes one's own (Edit a copy is gone).
  - A target on Results has two tabs, Overview and Runs. A run opens on the diagram, the last one as
    any other, a loop monitor's included. The last 10 runs of each target keep what each wire
    carried (thinned to 120 points), so clicking a block draws its charts; older runs keep the
    last values and Show every sample runs their window again.
  - The Over time chart draws any output the algorithm records (a loop's too, not only its
    health), over the last hour, day, week or month (`@processcraft/ui` 0.64.0).

- **A block's picture and drawing** (round 9 M1, M2, as in Simulink): a block may carry an image
  (PNG, JPEG, WebP or SVG of at most 256 KB, chosen in the block form), kept in its block file
  so each version has its own. It shows in the algorithm's diagram, in the palette and on the
  block's Overview, which now draws the block as the diagram does, inputs on the left and
  outputs on the right. An SVG is rebuilt without scripts, event handlers or outside references.
  `GET /api/blocks/{id}/image` (processcraft-sdk 0.52.0, `@processcraft/ui` 0.60.0).

### Fixed

- **Signal quality runs on the compute workers again (processcraft-sdk 0.60.0).** Every run
  failed on the workers ("function() argument 'code' must be code, not str") because the
  executor's child refused the network in a way that broke importing `httpx`.
- **A monitor with an empty data window saves again** (visual sweep, 2026-10-26): the form sent
  0 for "Analytics' default", which the API refuses, so the Loop monitor's and Signal quality's
  pages answered every preview with 422 and could not be saved. An empty window is left out.
- **Words:** the Results filter says Label, not Tag (glossary).

- **Link's works, events and refs reach PlantCraft again**: the SDK sends `files.manifest()` at
  start and Link's `Files` had only `meta()`, so nothing was sent ("Contributions not sent")
  and the assistant offered no Link card, such as a new block's form filled in.

### Changed

- **Comparing versions uses the suite's picker and code difference** (`@processcraft/ui`
  0.59.0: `ComparePicker`, `CodeDiff`, `lineDiff`), the same as Models'. Nothing changes for a
  person.
- **Folders come from the platform** (processcraft-sdk 0.50.0, `@processcraft/ui` 0.56.0): the
  same store, routes and interface, so Models files its objects the same way. Nothing changes
  for a person; the tables and ids stay.
- **Fewer events, each meaning something** (Alarms round 11): `output.status` is gone (an
  alarm on an output reads its recorded series); a failed run is one `run.failed` however many
  assets it ran on, and a stalled schedule is one `schedule.stalled` condition, not one per
  asset.

### Added

- **Schedules say what they run on** (Alarms round 11): the schedule list PlantCraft keeps
  carries each schedule's assets (`subjects`, SDK 0.51.0), so an Alarms rule over an execution
  covers its assets.
- **Compare versions** (round 9 review, D18): on a block's or an algorithm's Versions tab, tick
  two or three versions and Compare opens a Compare tab that runs each on the same asset (or
  loop) and the same data window, nothing saved: what they read once, then each output's value
  or verdict in a column per version and each series on one chart, one line per version. The
  block test endpoint takes the window's end from the page; a loop test takes `start` and `end`.
- **Folders for blocks, algorithms and schedules** (round 9 review, D14): Blocks, Algorithms,
  Schedules and Executions show their folders in a left column (`?folder=`), with **New folder**
  for editors. An object goes in the folder its list showed when it is made (a Folder field on
  the new block, algorithm and schedule forms) and moves only with **Move to folder** on its page,
  which keeps who moved it and when. Executions sit in their schedule's folder; the block
  libraries Link ships stay fixed, only the site's own blocks go in folders. Named "folders"
  because an algorithm's "group" already means the people who edit it. New tables `folders` and
  `folder_items`; `GET/POST /api/folders/<kind>`, `PATCH/DELETE /api/folders/<kind>/<id>`,
  `PUT /api/folders/<kind>/items/<id>`.
- **An execution has Overview, Last run and Runs** (round 9 review, D22/D23): an execution is
  the schedule's runs on one subject. **Last run** draws the diagram of the version that ran,
  each block with its verdict and each wire with its last value; **Show every sample** runs the
  same window again (nothing saved) so each wire shows its whole series. **Runs** lists the runs;
  one opens inside the execution with its diagram, outputs and the signals it read, and a run
  retention deleted says so. Each run now keeps what its wires carried without the samples
  (`summary.wires`) and the version that ran, for loops too; the algorithm test endpoint takes a
  loop window (`start`, `end`). "Open the asset" is now a quiet link named for the page it opens.
- **An algorithm's page works like a block's** (round 9 review, D19): tabs Overview, Inputs and
  outputs, Diagram, Test, Used by, Versions; any version opens on the page, with **Use this
  version** to make it the newest again; Edit and Edit the diagram become one **New version**
  form with the diagram edited and tested inside it, saved with a version name and what changed
  (`algorithm_versions.version_name`, `version_note`, added by a migration).
- **A block's page opens at any version** (round 9 review, D15–D17, D20): the tabs are Overview,
  Inputs and outputs, Code, Test, Used by and Versions; clicking a version shows the whole page at
  that version, with **Select this version** to make it the one in use (new algorithms and the
  palette take it; algorithms keep the version they pin). Edit is now **New version** (the form
  filled in from the version shown, saved as the next number, with who saved it) and Copy is
  **Duplicate**. The block form gains the other types an input accepts, an output's normal range
  and which way is good, and whether the block runs without data.
- **The assistant on Signal quality:** which signals have problems.
- **The assistant's works on a loop and on Results** (processcraft-sdk 0.39.0): a loop's health,
  a plot of its PV, SP and OP, what to check in the field; which results need attention first,
  what the worst have in common. They replace the pages' tasks of the same names.

### Changed

- **The schedule form is a real form** (round 9 review, D21): each part has its title and what
  it is for on the left and its fields on the right, across the page's width, stacked on a
  phone; the summary panel above it (which repeated the first part) is gone. A round's data
  window shows Link's default instead of a 0 that could not be saved.
- **Older databases upgrade by named steps** (`processcraft-sdk` 0.46.0): the columns added
  since the first release are the stores' `MIGRATIONS`, run once and recorded, and
  `tests/test_upgrade.py` opens each store on its older tables.
- **The suite's dialog** (`@processcraft/ui` 0.53.0, scale review A1): the loop and block windows
  and its six questions (deleting, closing the editor unsaved) are the ui's `Dialog` and
  `confirmAction()` instead of the browser's confirm or a window drawn here, so they follow the
  theme, keep the focus inside and close on Escape.

### Added (plan "Assistant on every page", step F3)

- **The assistant's works on Link's pages** (`[[contributes.assistant.works]]` in `app.toml`,
  processcraft-sdk 0.38.0, ui 0.49.0). Blocks and New block: write a new block with the
  assistant (administrators), or ask about the blocks; a block: ask about it. Algorithms and New
  algorithm: design a new algorithm, or ask about them; an algorithm: ask about it. Schedules,
  Executions, a monitoring round, a subject's history and one execution: ask (history, which
  algorithm and version ran, what it found). Writing a block or designing an algorithm ends in a
  card whose button opens the form filled in (`blockFromDraft`, `algorithmStart`): the person
  tests and saves there.

### Changed (owner review, round 9)

- **Executions show each output again, not only the score.** A subject's page lists every output
  of its latest result with its status, value and finding: a loop's methods (oscillation,
  stiction, saturation...), a signal's checks, an algorithm's outputs. An asset schedule's charts
  read the series it records under its own key (`<asset>.<schedule key>.<output>`, round 8 D6),
  where they had looked under the algorithm's.
- **The schedule form reads top to bottom.** Its parts are numbered like the block form's, the
  preview (occurrences in words, the next five, the time one takes) sits under the timing it
  describes instead of floating beside the form, Replay the past is its own panel at the end,
  and Delete, Cancel and Save stay in a bar at the bottom of the screen.
- **Blocks and algorithms are made, edited, tested and versioned the same way.** New block offers
  Import a file and Fill in the form; the assistant is the button beside the title (ui 0.47.0).
  The block form comes in five numbered parts (what it is, inputs, outputs, parameters, code),
  one compact row per input, output and parameter. A block's and an algorithm's versions and
  "About it" are a Versions tab (each version with its name, what changed, who and when), not a
  column beside every tab. The defaults form under Inputs and parameters is gone: Edit saves the
  next version.
- **An algorithm has Edit**: its texts, data window and every block's parameters in one form,
  without opening the diagram, saved as the next version. PlantCraft's own algorithms offer
  Edit a copy. Inputs and parameters is a read-only list like a block's (input and output blocks
  are listed once, under what it reads and gives). The Diagram tab is the diagram alone, read-only
  with only Fit to screen.
- **New algorithm** is a page like New block: Import a file (`plantcraft-algorithm/1`, what
  Download the file on an algorithm's page gives) or Fill in the form (name, what it works on,
  where to start) and continue in the diagram's window.
- **Test** of a block and of an algorithm: first the asset (or loop), then one row per input with
  the point it reads (PV, SP, OP…), then the window and Run the test.

### Changed

- processcraft-sdk 0.35.2: the suite's rules for an app's inside (PlantCraft
  `docs/app-standard.md`, section 5). The Executions charts read Link's own series through the
  runtime, a loop's setting origins live in `loops/defaults.py` and the signal settings in
  `signals/models.py`, so the routers import no store. Nothing changes for people.

### Added

- **Recorded outputs** on a schedule of an algorithm on assets (round 8, D6): one row per
  output the algorithm records, recorded or not and kept forever, for days or (a series) for its
  last executions, with the values a day and the space it takes before it is saved. The verdict
  is kept forever by default, other values 400 days, a series its last 10 executions.
  Executions write `<asset>.<schedule key>.<output>`: a verdict as its score and its status, a
  series whole for each execution; the Historian keeps them as the schedule says. Each asset of
  the schedule gets a result asset that holds them.
- The Furnaces example schedule of the demo plant records each twin's prediction as a whole
  series per execution: Historian draws the last executions one over the other.

### Removed

- Algorithms on assets no longer write `<asset>.<algorithm>.<output>`: what a run records goes
  to the Historian only through its schedule's Recorded outputs (a Run now on the algorithm's
  page keeps it in Link). The series written that way before are retired once.

### Changed

- A block's page has the same tabs as an algorithm's: Overview, Code, Inputs and parameters, Test
  and Used by, with its versions and who answers for it on the right of every tab. Inputs,
  outputs and parameters are one table, so their columns line up, and a long block's code scrolls
  inside its editor instead of the page.
- The Code tab shows one source, the calculation the block runs, instead of the module that
  declares it and the function it calls.
- processcraft-sdk 0.32 (an app without an app key reports its conditions; result assets, typed
  and runs points).
- An algorithm's page has a block's tabs: Overview (what it is for, and what it reads and gives),
  Diagram (its own tab with Open the editor, so the page scrolls again), Inputs and parameters
  (every block's parameters and, on assets, the data each run reads), Test and Used by (its loops
  or its assets, and its schedules). Its versions and who answers for it are on the right. Its
  texts, parameters and assets change on the page, each save a new version, and the editor
  window keeps the diagram, the name and the description only.
- The diagram editor says how to add a block: "Add a block" over the palette and **+ Block** in
  the toolbar (`@processcraft/ui` 0.43.0).
- A schedule's page has four parts: what it runs, when, if it fails, and owner and priority. Its
  time zone list starts with the installation's local time and UTC, and the preview says the
  schedule in words ("Every 15 minutes, Mon to Fri, 06:00 to 18:00").

### Added

- **Event catalog** (processcraft-sdk 0.26): `app.toml` declares the eight events Link writes
  (`[[publishes.events]]`: output status, status changed, run failed, schedule stalled, finding
  opened and closed, protocol alert and cleared) with their severity, category, shape and a
  suggested rule. Conditions are sent as start and end with a key (a finding, a stalled schedule,
  an output's status), so Alarms clears them by themselves.
- Schedules on a calendar: every N minutes or hours on chosen weekdays between two times of day,
  every N days or weeks at several times, every N months on a day (or the last day) or on a
  weekday such as the first Monday, with an optional first and last day (cadence `calendar`,
  `recurrence` on `POST /api/schedules`). The plain cadences stay for schedules they describe.
- Each schedule says what it does when a run cannot read the plant or finds no data: try again
  N times, M minutes apart, and give up when its next occurrence comes first (`retry`; on by
  default, twice, 5 minutes apart). An error in the algorithm is not tried again.
- Executions says how far a schedule's tries got ("try 2 of 3") and, for a failed one, after how
  many tries it gave up (`max_attempts` on each execution).
- A schedule's page shows its record over its latest executions: how many ran, failed and were
  tried again, how long they took and when the outcome last changed (`stats` on
  `GET /api/schedules/{id}`).
- Algorithms lists, for an admin, the algorithms copied from Twin that repeat one of the demo's
  examples (`twin_<id>` beside an algorithm with the same name, both running on the same assets)
  and removes them with their schedules after a confirmation (`GET /api/algorithms/repeated`,
  `POST /api/algorithms/repeated/remove`).
- Edit on a block Link ships (data quality, transforms, statistics, equipment and logic): the
  site's first save is version 2 of the same block, and the algorithms that use it keep Link's
  version 1 until they are updated. Deleting the site's versions goes back to Link's.

### Fixed

- Executions "By schedule" answered 500 ("database or disk is full") on an installation with
  thousands of executions on assets, and the events for the Alarms app failed the same way. Each
  execution kept every recorded point of its window in its summary (about 45 kB a run on the
  demo plant), and sorting the list spilled past the container's 64 MB /tmp. The list now sorts
  the ids alone, an execution keeps each recorded series' last value (the Historian has the
  points), and the summaries kept before are thinned in the background, 200 a minute.

## [0.4.0] - 2026-10-24

### Changed

- A schedule picks the algorithm and the assets it runs on; an algorithm no longer makes its own
  schedule. The schedules Link once made for asset algorithms become ordinary schedules on the same
  assets (at least every 15 minutes), and two schedules cannot run the same algorithm on the same
  asset. The schedule page shows what it runs first, then when, then who owns it, in one column;
  running more often than every 5 minutes asks for a confirmation.
- Fewer signals in Link's source of the Historian. Every series on an asset
  is `app-linkcraft:<asset>.<algorithm>.<output>`, named `<tag> · <algorithm> · <output>`: a
  loop's health (`<loop>.<algorithm>.health`, "FIC-101 · Flow loop · Health") and each output an
  algorithm records (the block's name, not its id). New versions keep writing to the same series;
  each algorithm has one text series `app-linkcraft:algorithm.<id>.version` with a point ("v3")
  when the version that runs changes. A verdict no longer writes a second `_status` series, nor
  a loop its `.status` text: the status is in the result. Once PlantCraft answers, Link retires the series it no longer
  writes (processcraft-sdk 0.24.0 `retire_series`). A scheduled run's results expire after two of
  its schedule's intervals.
- Executions and Results are one page: Executions opens on the schedules,
  each with what it concluded (how many assets OK, warning, alarm) and when it runs next; a
  schedule lists its assets by name with a word for their status (Normal, Medium, High,
  Critical); an asset shows its latest result, its series in the Historian over the last 7 days
  with a dotted line where a new version started, and its past executions. Runs a person asked
  for are in Manual runs; the queue is the Queue tab. The menu follows the work: Overview,
  Blocks, Algorithms, Schedules, Executions. The old Results addresses still open.
- An algorithm's page opens on its versions, newest first, each with its name, description,
  when and who saved it; choosing an older one shows its diagram and texts as they were. Who
  made it and who answers for it is one line (Change opens the form), and the texts What it is
  for, When to use it, How to read it and For the assistant are one under the other.
- Link tells the Alarms app about its schedules and the Alarms app decides who hears it (owner
  decision D6): `linkcraft.output.status` for each output in warning or critical at each
  execution, `linkcraft.status.changed` when a subject's state changes (back to ok clears),
  `linkcraft.run.failed` and `linkcraft.schedule.stalled` (two periods without running, said
  once), each on the asset with the schedule, algorithm, version, owner and severity. A
  schedule's page has Create alarm rule, which opens the Alarms app's rule filled in for it.
- The Overview opens on the schedules (how often each runs and how its last execution ended),
  the queue and the latest runs; the counts by status and the worst results stay in Customize.
- Only the last 50 runs per asset and schedule keep their full detail (each method's result
  and the configuration it ran with); older runs keep their summary, and the long history is in
  the Historian.
- Only the Furnaces process twin is created as a demo example, with its own schedule every 15
  minutes; the other twins stay in the Models library.

### Removed

- The Assistant page and its menu entry: the assistant is the suite's button at the top of every
  page. An old link to `/assistant` opens the Overview.

### Security

- Block code could reach the system through the modules an allowed module imports itself
  (`typing.sys.modules["os"]`, `re.enum.sys`, `dataclasses.sys`) and read files by name with
  `pandas.read_csv` and the other `read_*` functions. The modules block code imports now reach it
  through a guard that hands out only allowed modules, every `read_*` is refused, and so are
  `numpy.testing` (it runs code from text), `pandas.testing` and `ndarray.dump`.

### Added

- The suite's search (Ctrl+K, PlantCraft 2026-10-23): `GET /api/search` answers with its loops, algorithms and blocks
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
  at start. Ruff's `DTZ` rules are on.
  Due times, schedules' next runs, cutoffs and the run monitor's times are UTC (they compared as
  text across offsets before); a schedule's 08:00 stays 08:00 in its own zone.
- Results lists what any algorithm concluded on any asset: asset, type, algorithm and version,
  status, measure, main finding, tags and when. Filters by algorithm, tag, asset type, group and
  status replace the signals/loops split, each choice with the count it would keep; old
  `?kind=` links still open. "New loop", "Sync from PlantCraft" and the loop weekly report are
  gone from the page: assets, loops included, are registered on PlantCraft's Assets page.
- The asset page (`/assets/<id>`) is every algorithm's result on that asset, then its signals'
  quality; a loop asset links to its loop analysis instead of redirecting to it. An asset no
  algorithm runs on says so and offers to schedule one.
- Tour and guides speak of results and assets, not signals and loops; new guide "Results".

### Added

- `GET /api/reports/results.pdf`: the results any filter keeps as a PDF (counts per status and
  per algorithm, every result worst first). The weekly loop report is this report filtered on
  the tag *control loop*. `GET /api/results` takes `algorithm`, `tag`, `asset_type` and `group`
  and returns `options` with a count per choice.

### Fixed

- Signal quality judges only the plant's live measurements: the suite's health (source System) and CSV files imported once are no longer checked, so they no longer fill Needs attention with critical signals.
- A schedule kept on a 0.2 protocol id (`all`, `oscillation`) shows the algorithm that replaced it on Schedules and Executions.
- The Docker image did not build: the vendored `processcraft-sdk` 0.17.0 needs PyJWT, which
  `deploy/requirements.lock` lacked, so the image's `pip check` failed. Lock regenerated.
- `/link/api/ops/metrics` answered 500 (`Files` had no `app_id`), so the suite monitor could not
  read Link's counters and logged an error every minute (found on the Mac mini after 0.3.0).

### Changed

- The first page is the Overview every app of the suite shares (`AppOverview`, `@processcraft/ui`
  0.20.0): widgets each person chooses and orders, kept per person in ProcessCraft. Link draws
  richer versions of the widgets it publishes: each kind of subject, what needs a look, the last
  run, the worst first and the latest runs.

### Added

- **PlantCraft hears when Link's queue does not drain** (`processcraft-sdk` 0.19.0): Link reports
  its queue in `/link/api/ops/metrics` (`ops.report_queue`), and PlantCraft's suite watch tells the
  administrators in "Suite health" when executions wait over 30 minutes, and when it recovers.
- **Algorithms as one list** (owner's review, 2026-10-23): PlantCraft's own and the site's in one
  table with tags, author, owner, version, how many assets use each one and its status, a tag
  filter and search. Every algorithm has free tags, an owner, a version (each save adds one) and
  an optional responsible group: its members and coordinators edit it, everyone else reads it
  (`PATCH /api/algorithms/{id}`, `GET /api/user-groups`; the API answers 403).
- **Examples by loop type**: **Flow loop**, **Level loop** and **Temperature or pressure loop**
  are each kind's default, beside Surge level, Signal quality and Unit twin, authored by
  PlantCraft. Loop health, Control valve and Oscillation and noise are retired: their ids open
  Flow loop, and the valve and oscillation checks stay as blocks. On the Simulator demo plant the
  example twins are added once by themselves, calibrated and scheduled, so they run from the start.
- **One queue for everything Link runs** (owner's review, 2026-10-23): a loop's algorithm, the
  monitoring round, Signal quality, an algorithm on an asset and a replay of the past are all
  executions of one queue, run by the engine's workers in a process of their own
  (`LINKCRAFT_ENGINE`, `linkcraft engine`; one engine per database, a second waits as a
  standby), so a long round never slows the pages. A person's request runs first, then the
  schedules, then a replay. The monitoring round, Signal quality and each algorithm on assets
  (its cycle) are ordinary schedules. An occurrence whose previous one has not ended is recorded
  as skipped, with the reason, instead of piling up; a schedule can spread its executions over
  a window; an execution whose plant data did not answer is tried again after 30 s and 2 min,
  then fails with the reason; an analysis process that takes more than `LINKCRAFT_TASK_MEMORY_MB`
  (4096) fails its task alone. `GET /link/api/queue?window=` gives the queue now and over 1 h,
  24 h, 7 d or 30 d (`plantcraft-queue/1`, sampled every 15 s, kept 30 days).
- **Executions and Schedules**, entries of their own in the menu. Executions shows the queue's
  panel (`QueuePanel`, `@processcraft/ui` 0.22.0: now, and the queue, running and wait over
  time) above every execution, with filters, cancel and run again (`/link/api/executions`).
  Schedules lists every schedule, the rounds included; each opens on a page of its own (algorithm,
  subjects, frequency in the site's time zone, data window, priority, spread, owner, active) with
  a preview of how many executions each occurrence queues, the next five occurrences and whether
  the queue keeps up (`POST /link/api/schedules/preview`), Run now and, for admins, a replay of
  that schedule's past. The Overview has a Queue widget. The schedules left the Algorithms page.
- **Site blocks** (owner's review, 2026-10-23): a site writes its own blocks in Python, as block
  files (`plantcraft-block/1`) imported, filled in on a form or written with an assistant (a
  prompt that teaches the assistant Link's format). Every save is a named version with what
  changed; algorithms keep the version they use; author, owner and tags; defaults editable as a
  new version. The code runs in separate restricted processes (no files, no network, limited
  time and memory) and only administrators save it. Shipped blocks show their code read-only
  and can be copied. The block page has Overview, Code, Parameters, Versions (with a diff) and
  Test (on an asset's last window) tabs.

### Removed

- The "Copy as prompt" buttons on methods, blocks and algorithms: the prompt that matters is the
  one that creates a block (New block, "With an assistant"). `GET /api/prompts/<kind>/<id>`
  stays in the API.

## [0.3.0] - 2026-10-23

### Changed

- `processcraft-sdk` 0.14.0: Link reads its settings with the SDK's `AppSettings` and connects to
  ProcessCraft with `PlatformRuntime`, the same code as every app (no setting or behaviour changes).

### Added

- Signal quality judges laboratory analyses by their own rules: a signal from a file source
  (CSV), or one marked **Laboratory or manual samples**, skips the frozen value, noise and
  resolution checks, and its freshness and gaps are measured against its sampling interval
  (read from its samples, or set on the signal). Range, spikes and drift still judge it. Signals
  keep their source's kind (`source_kind`, from ProcessCraft API v1).

### Changed

- `processcraft-sdk` 0.13.0: loop rounds, signal checks and model algorithms read their series
  straight from the Historian when the suite sets `PROCESSCRAFT_HISTORIAN_URL`, without the
  hop through ProcessCraft (and back through ProcessCraft when the Historian cannot answer).
- `@processcraft/ui` 0.18.0: the browser tab reads page first, then the app, then the brand
  ("FIC-1003 · Link · PlantCraft"), and its icon is always the platform's mark.
- On the suite's current shared packages, the same as every other app: `processcraft-sdk` 0.12.1
  (log lines redacted in linear time).

### Fixed

- Finished runs older than 90 days are deleted with their results, hourly, like the health
  history; each subject keeps its newest run. Every schedule makes one run per subject at each
  occurrence, so the table grew for ever (2,000 loops every hour: 48,000 runs a day).
- The image builds again: the wheelhouse is built from the lock without resolving dependencies
  (`--no-deps`), so FMPy's build-only requirements the lock leaves out (cmake) are not fetched.

### Added

- The plant's model examples: with the PlantCraft demo plant in ProcessCraft, one button on
  Algorithms (`POST /api/models/examples`) creates the example twins ProcessCraft Twin offered
  (Furnaces, FIC-1001 process, LIC-1010 process) as algorithms on assets on the built-in models,
  each calibrated on the last six hours. ProcessCraft Twin leaves the suite; Link runs its twins.
- General blocks (17), each described in the block format with its public references:
  signal treatment (derivative, resample per period; the first-order filter is now named
  low-pass filter), math and conditions (expression of up to four series, parsed and never run
  as code; engineering unit for temperature, pressure, flows, length and power; compare with a
  limit with a deadband; AND / OR / NOT; select by condition), statistics in a new library
  (mean, standard deviation, percentile, histogram, correlation with lag, step changes), the
  operating window (time outside limits; only in operation, which leaves out start-ups and
  shutdowns) and a new Equipment library (heat exchanger UA by the log mean temperature
  difference, pump efficiency against its curve).
- Models library (what ProcessCraft Twin did, as blocks): every published FMU is a block
  (`model.fmu_<model id>`) whose ports are its own inputs and outputs; it runs in a worker
  process with a time limit, starts each output where the plant measured it, and gives the
  prediction and the residual per output. `model.deviation` judges residuals with Hotelling's T²
  against a calibration held in its parameters (normal, attention, problem, with the share each
  output explains); `model.operating` marks when the unit runs. The two built-in models
  (furnaces, loop process) ship in the image (`fmus/`); FMPy is a new dependency.
- Algorithms on assets (`docs/blocks-and-algorithms.md`): an algorithm can work on the assets it
  names (a unit, a furnace), each on its own cycle from 10 s over its own window. Its Signal
  blocks read a role of the asset, of another asset or a signal by id; its blocks remember
  between runs; it publishes results, messages and recorded series (every new point). The editor
  sets its timing and assets and tests it on an asset at any time; the algorithm's page shows its
  latest run on each asset and runs it now; an asset's page lists the algorithms on it. API:
  `GET /api/algorithms/<id>/runs`, `POST /api/algorithms/<id>/run`, `GET /api/asset-choices`,
  `GET /api/models`.
- Calibrate and Unit twin: a Deviation (T²) block is calibrated in the editor (select it, choose
  an asset and a period of normal operation, press Calibrate): the algorithm runs over the period
  as its cycle would have, and the residuals' mean and covariance become the block's calibration
  (`POST /api/algorithms/calibrate`). The shipped *Unit twin* algorithm runs a process model on
  an asset's OP and PV and judges its residuals. A ProcessCraft Twin twin converts to an
  algorithm on assets, and Twin's oracle passes in Link with the same floors. The built-in
  models' blocks are always in the catalog. `@processcraft/ui` 0.17.0 (inspector tools).
- Twin moves into Link: `linkcraft migrate --from-twincraft` (or `LINKCRAFT_MIGRATE_FROM_TWINCRAFT`
  at start) copies Twin's uploaded models and turns every twin into an algorithm on its asset,
  calibration included. Admins publish models (`POST /api/models`, what Models' **Publish to
  Link** sends); editors rename them, admins delete one no algorithm uses. A model block's page
  and `/editor/new?model=<id>` open a new algorithm on assets around the model
  (`GET /api/models/<id>/starter`).
- Blocks and algorithms (`docs/blocks-and-algorithms.md`). Methods and checks are blocks with
  typed inputs and outputs (signal, mode, number, verdict) in six libraries (44 blocks), each
  described in one format for people and the assistant. Protocols are algorithms: diagrams of
  blocks checked before they run (types on every wire, required inputs, no loops, an output).
  API: `GET /api/blocks`, `GET|PUT|DELETE /api/algorithms/<id>`, `POST /api/algorithms/check`,
  `/docs`, `/test` (one run on one loop, with what every wire carried).
- Any number or verdict output can be recorded in the historian, as
  `app-linkcraft:<loop>.<algorithm>.<block>.<port>` with its description; a verdict also
  records its status (0 ok, 1 warning, 2 bad).
- The assistant reads every algorithm (`algorithm:linkcraft/<id>`) and every block
  (`block:linkcraft/<id>`).
- The interface: **Algorithms** lists Link's algorithms (read-only, the reference) and the
  site's own, each with a page showing its diagram, what it is for and where it is used; the
  diagram opens in a window of its own, the suite's block editor (`@processcraft/ui` 0.15.1
  `BlockEditor`): a palette of folding libraries, typed ports, the check on every edit, a test
  on a loop (a light on each block with its message on hover, the values on the wires on demand,
  a selected block's inputs and outputs drawn over the window), the documentation beside the
  diagram, Duplicate and Save.
  **Blocks** lists every block by library, each with its ports, parameters and description. A
  loop's page draws its algorithm with what each block said in the last round.

### Changed

- Disturbance attenuation, Time in operating band, Operator interventions and Sampling quality
  cite public references (Shinskey 1996, Jelali 2006, Thornhill, Choudhury and Shah 2004) and are
  engineering heuristics, no longer site-specific. Time in operating band with limits set for the
  loop applies to any loop type; the default 20–80 band still needs a surge level.
- Five algorithms replace the twelve protocols: Loop health (every loop, whatever its type;
  the loop type now sets only parameters), Control valve, Oscillation and noise, Surge level and
  Signal quality, which now runs its own diagram on every signal. Old protocol ids keep working
  (they name their replacement) and protocols people saved are converted at start. Flow loops
  now also get oscillation and stiction diagnostics; temperature, pressure, level and
  composition loops get sensor noise and sampling quality; composition loops judge output
  travel with a wide allowance (their output is usually a setpoint).
- API: runs and results name their `algorithm` (was `protocol`); usage moved to
  `/api/algorithms/<id>/usage`; `/api/profiles`, `/api/flow-blocks` and `/api/protocols/*` are gone.

- Methods and Protocols in the menu are now Blocks and Algorithms; old addresses
  (`/protocols/...`, `/methods`) open the new pages.
- On `processcraft-sdk` 0.11.1 and `@processcraft/ui` 0.15.1. Logs are JSON lines on the console and in `<data dir>/logs`,
  like the rest of the suite, and the data folder is part of the suite's backup
  (`[backup]` in `app.toml`).

## [0.2.0] - 2026-10-21

### Added

- ProcessCraft Link joins CPMCraft and DataCraft in one app: signal quality for every signal and
  loop performance for every control loop, run on a schedule from methods wired into protocols.
- Results with pages and a run history, a documentation page per method and protocol for the
  assistant, tables that sort and filter by column like the rest of the suite.

## [0.1.0] - 2026-10-19

### Added

- First version.
