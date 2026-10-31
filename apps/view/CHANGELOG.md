# Changelog

Every release of PlantCraft View, newest first, in the
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) form. PlantCraft's `deploy/bundle.sh`
joins it into the bundle's release notes.

## [Unreleased]

### Added

- **The ISA-101 analog indicator, on a gauge card and under a diagram's value.** A grey bar over the
  signal's range draws the normal range as a darker band, the LL, L, H and HH limits as ticks (a
  card takes them from its thresholds, a diagram value from its limits), the setpoint as a hollow
  mark (a signal of role SP of the same asset) and the value as a pointer that takes the warning
  or alarm colour only out of normal. Gauge style **Analog indicator (ISA-101)**; a diagram
  value's **Analog indicator** box, with its scale, normal range and setpoint.
- **A stat's line shades the normal range.** The new standard options **Normal range from** and
  **to** (empty: between the thresholds' normal step and the next) draw a grey band under the
  line, so a value leaving its normal range stands out.
- **Laboratory results in Trends.** A `laboratory:<analysis>` signal is drawn as markers at its
  sampling times, never averaged over the interval, whenever the result arrived. The tooltip
  gives its status (approved, not yet approved, rejected) and when it was received and approved.
  An approved result is a filled circle, one not yet approved an open circle, a rejected one an x.
- **A process display marks an alarm by its priority (ISA-101).** A symbol bound to Alarms'
  alarm state gets a mark in its corner while an alarm is active, with a shape and a number for
  the most urgent priority: a square with 1 for critical, a triangle with 2 for high, a diamond
  with 3 for medium and a circle with 4 for low. Colour is only the third cue, so the mark still
  reads without colour.
- **Assistant sections in reports.** A report section the language model writes from the
  latest loop, signal-quality and alarm results and the period's events about the assets an
  editor picks (checkboxes, or a description the model turns into a pick). The requirements are
  an editable prompt; feedback on an edition goes to the model, which proposes the next
  requirements, kept version by version. Tags and dates the text gives that the facts do not are
  flagged in the section. Two new language model uses, `report-write` and `report-tune`, are off
  until an administrator gives them a model.
- **Reports over whole calendar periods.** A scheduled report can cover the last whole day,
  week, two weeks, month or quarter on the plant's clock, with every read pinned to the period's
  end.

### Fixed

- A report's event tables scroll inside their section on a phone instead of pushing the page sideways.
- Colours and shadows named after tokens that do not exist use the suite's tokens, so they follow
  the dark theme.
- **A process display opens in under a second.** The demo's Riverbend plant has 289 bindings,
  and View read each value and app result one at a time (about 250 requests, 2.8 to 4.9 s each
  time its short cache had expired). It now reads every signal's newest point in one batch of
  the last two minutes, each app result kind in one request, and the rest side by side: 0.4 to
  0.5 s on the same installation, with the same values and states. A signal quiet for longer
  still asks for its last value on its own.

## [0.5.1] - 2026-10-30

- **Memory stays bounded under many viewers.** View's short cache let expired values go only
  when it held 4,096 of them, so a diagram's window of series per request piled up until the
  container reached its 2 GiB limit and was stopped (public demo, 2026-10-29), or stalled for
  minutes; expired values now leave at every store. Viewers asking for the same data together
  share one read.
- Suite 0.5.1: `plantcraft-sdk` 0.79.0 and `@plantcraft/ui` 0.89.0, with the new look (the PC valve logo, Steel Blue and the new app marks).

### Added

- **Full screen keeps a strip of its own**. A process display in full screen
  has a top strip with its name, its page or part tabs, one time button and the way out; the
  drawing starts below it, never under it. The time button says what is shown (Live and the
  period, or the instant played back) and opens the period, playback and Live under it on a
  click or while the pointer rests on it. Playback keeps playing when the display goes full
  screen or back.

- **Parts of a process display**. A large page names its parts; the viewer
  shows tabs over it, **Overview** (the whole drawing) and one per part, that zoom there, full
  screen too, with `?part=` in the address. The demo's Riverbend plant has its seven parts, and
  the seed gives them to the one-page display of the day before.

### Fixed

- A public demo's visitor opens Dashboards, Reports and Process without errors: the reads behind
  the editors they are shown (people and groups to pick, templates, assets, asset kinds, event
  kinds, previews, versions) answer them, a public link list comes back empty, and every save is
  still refused (fine pass 2026-10-28, item 31).
- Trends' signal search works for everyone who can save a trend (it was an editor's only, so a
  viewer's search came back empty). A public demo's visitors try Trends but save, change or
  delete no trend: they all share one account.
- The furnace symbol drew a path command inside a polyline (a console error on every display
  with a furnace).


## [0.5.0] - 2026-10-27

### Added

- **A process display opens over itself**. A click on a value draws its trend
  in a window (period, interval, line settings and CSV as in Trends, **Open in Trends** to go on);
  a click on a piece of equipment opens its panel beside the drawing (values, signals, its
  dashboards, **Asset page**) instead of a dashboard page. **Full screen** is the browser's own,
  and both open inside it. A vessel's level fills the vessel's outline, with its surface drawn.
  `asset-dashboards` also answers the asset's signals, description and kind label.
- **Zoom in a process display.** The wheel or a double click zooms about the pointer, a drag
  moves a zoomed drawing, and buttons zoom in, out and back to the whole drawing; a drag never
  opens what it started on. A new link, **a part of this drawing**, zooms to an area of the same
  page ("x, y, width, height"), so a large drawing has buttons that take you to each part.
- **Demo: Riverbend plant on one page**. The seven parts of the plant sit
  side by side on a 4800 x 2700 page; each off-page button zooms to the part it names. The seed
  redraws a demo display it made earlier with pages; one someone changed is left alone.

### Changed

- A process display opens without its description over the drawing (as a dashboard).

### Added

- **Report sections that count their events.** An events section can now **count** the period's
  events by what they are about, their kind, their severity or one field of their payload
  (`group_by`: `subject`, `kind`, `severity`, `payload.<field>`) and rank the groups, the most
  first: count, share, latest time and what happened then, the row marked by the worst severity,
  and a sentence naming the largest ("Most often: FIC-1003, 9 of 24 (38%)."). The same in the
  PDF, Word, HTML, Markdown and on the page; the editor's **Show** picks it. A `payload.<x>_id`
  group is named by the event's `<x>_name` where the app gives it. So a report says which loops
  had the most findings, which problems were the most frequent, or which alarms are the bad
  actors, instead of listing events.
- **Demo: four descriptive example reports** replace the short, dashboard-like ones: *Control
  loops weekly performance* (loops with problems, most frequent problems, worst loops, a stiction
  section and an oscillation section, recommended actions), *Alarm summary, weekly* (load, top 10
  bad actors and priorities against ISA-18.2 and EEMUA 191), *U-100 daily report* (the crude unit's
  day for the handover) and *Valve and instrument health, monthly*. Text explains every measure.
- **Process displays draw cleaner.** Symbols keep their own proportions in any box (a pump is
  never squashed; the selection, ports, level fill and labels follow the drawing; resizing keeps
  the drawing's ratio, Shift frees it); only unit blocks and off-page connectors stretch (new
  `stretch` in the symbol library). Lines leave and enter ports straight out with a stub, take
  as few square bends as they can, go round the two symbols they join rather than through them,
  and sit on the grid; a line to no port meets the side of the symbol that faces the other end.
  Arrowheads are small, filled, in the line's colour and end on the port; long process runs show
  small flow arrows; line labels sit over the longest level stretch. Labels can go `inside`
  (vessels, blocks) besides above, below, left and right. Off-page connectors are buttons: a
  pill with their label and a chevron the way the line goes. The demo's displays carry their
  connectors' labels in the button and their free line ends on the drawings' outlines.

- **Diagrams, phase 5b: public links, kiosk and a diagram panel.** An editor of a diagram makes
  public links to it (**Share**), with the dashboards' rules: off with `DASHCRAFT_PUBLIC_LINKS`,
  View's app key needed, 7 to 365 days (until revoked: administrators only), revoked at once or
  when the diagram is deleted, listed in every link's review. `share/diagram/<token>` opens the
  diagram read-only without sign-in, live and with its time bar (`GET
  /dash/api/public/diagram/<token>` and `.../data`); `?screen=1` (or **Full screen**) is the
  kiosk: the diagram alone. Dashboards get a **Diagram** panel: a saved diagram live, scaled to
  the panel, reading the dashboard's time window (else its own); a click opens the diagram. A
  viewer who may not see the diagram's folder, a public link to a diagram in a closed folder, or
  a deleted diagram shows "not available" in its place. Reports take no diagram panel.
- **Diagrams, phase 2: the pages.** Diagrams in the side bar: the list by folder; a diagram live
  (values, state colours, tank levels, running pumps, flow in lines, refreshed on their own), a
  time bar that plays the window back at 1x to 600x or from any past end, full screen, a legend
  of media and states; and the editor: drag equipment from the library, join ports by dragging,
  pick the asset a symbol draws and its state, level and running are bound at once, values and
  texts, undo and redo, copy, turn, flip, zoom, and the bound values read while drawing.
- **Diagrams, phase 1 (API only, no page yet).** Process graphics of a unit: symbols from a
  library (one JSON per symbol, drawings filtered to basic shapes), lines between their ports,
  values and texts, bound to signals, assets and roles, or other apps' results (alarm state, loop
  health). Saved with versions in folders like dashboards; `GET /dash/api/diagrams/<id>/data`
  reads every binding now and the window behind it in one batch, for live view and playback.
  Stale or unreadable values show as unknown, never as normal.
- **Process (was Diagrams), with pages.** The menu and the screens say Process and process
  display (ids and URLs stay `diagrams`). One display holds the whole plant: pages (`pages`, each
  element's `page`, links of kind `page`) with tabs as dashboards have, added, renamed, moved
  and removed in the editor; the data endpoints read one page (`?page=`). The new plant's first
  step draws one display with a page per unit. The time bar has two rows: the period and its end
  (Now or a date) above, play, speed, the instant and Live below. The description shows under
  the name, and the assistant's button appears once.
- **Diagrams, phase 5a.** Resize a symbol by its corners (Shift frees the proportions), drag a
  stretch of a routed line across itself (the bends stay square), and **Versions** in the editor
  brings one of the last 30 saves back onto the canvas. A symbol dropped past the canvas edge is
  kept inside. The viewer's legend uses the suite's levels (OK, Warning, Critical, Unknown) and
  its times follow the display time zone.
- **Diagrams, phase 4.** `POST /dash/api/diagrams/draw-from-assets` lays out a
  unit's diagram from its assets in PlantCraft, no model: a symbol per piece of equipment, loops
  as bubbles with their health, PV and SP, process lines from the feeds and downstream-of
  relations, left to right on the grid. A new plant's first step `unit-diagrams` saves one per
  unit. `POST /dash/api/diagrams/draft` asks the language model use `diagram-draft` (off until
  an administrator gives it a model) for a draft from a description, and repairs what breaks the
  format, with a note for each change. Diagrams are objects for the assistant, in Ctrl+K search,
  `#diagram:<id>` references, a "diagrams" widget and four assistant works.

### Security

- **Asset scope (decision D2).** A person who sees only part of the plant (PlantCraft's token claim
  `assets`) reads saved dashboards and reports as themselves, never with View's own token; kept PDFs
  are their own or those sent to them; they set up no public link and no scheduled report.
  `processcraft-sdk` 0.66.0.

### Added

- **A new plant's first step: "Draw the unit overviews" (`[[contributes.start]]`,
  processcraft-sdk 0.65.0).** Once an administrator applies an import of assets in PlantCraft,
  View saves one overview dashboard per unit in General (`POST /dash/api/start/unit-overviews`),
  with every loop under the unit at any depth, in tables of twelve (`unit_overviews`); a
  dashboard of that name is kept. With processcraft-sdk 0.65.0
  (from 0.62.0) its database also uses the rollback journal on a Docker Desktop bind mount.

### Changed

- **Overview widgets say when each thing was updated.** Dashboards, saved trends and process
  displays show "Updated 5 h ago" under the name, like Reports shows its next send; the panel and
  element counts are gone. The one-signal trend widget is removed; the Overview now shows
  Dashboards, Reports, Saved trends and Process displays (SDK 0.76.0).
- **Overview: public links as a list, and no create buttons.** The public links widget lists
  each link with what it opens and when it was last opened; new dashboards and trends are made on
  their own tabs. Saved trends come first.
- **A dashboard opens without its description over the panels** (a text panel says what it
  should); descriptions in the lists of dashboards, reports and process displays keep to two
  lines. The process displays list drops the element count.
- **Download asks the format on the list of reports too** (the last PDF, Word, HTML,
  Markdown), as on the report's page.
- **Public link tables keep one line per link**: what it opens, its kind and who created it in
  columns of their own.
- **A shorter Overview.** A new person's board is the dashboards beside the
  reports, then the trend changed last across the page; public links and one dashboard stay in
  "Add a widget". Each report says when it goes out next ("Next: Mon 08:00", on the plant's
  clock) or "Not scheduled", its dot how the last send went; without a saved trend the trend card
  links to Trends. processcraft-sdk 0.69.0, ui 0.72.0.

### Fixed

- **A dashboard's link opens the dashboard.** A `#dashboard:` reference in a message, an action or
  a note opened the list of dashboards; it opens the dashboard itself now.
- **Times on the person's clock.** A fixed period in Trends is labelled in the
  zone the pages show; the CSV of a panel and of a trend write their times on that clock, name
  the zone in the header ("time (UTC−3)") and in the file name. ui 0.71.0, SDK 0.62.0.

### Security

- A folder that no longer exists keeps its dashboards for administrators only, as in Documents
  (platform review I1, 2026-10-27).
- **Public links expire (review decision D4, 2026-10-27).** A new link of a dashboard or a report
  opens for 7, 30, 90 (the default) or 365 days; "until revoked", for a control room screen, is an
  administrator's choice. Links made before keep opening until revoked. Administrators review and
  revoke every link of the installation from Dashboards › Public links (`GET /api/shares`).
- **A report's public link draws its charts under the suite's proxy.** Its policy runs only the
  page's own script, by its SHA-256 (no `'unsafe-inline'`); PlantCraft's proxy leaves that page
  this policy instead of the suite's, which stopped the script.

### Fixed

- **Words:** View's messages say panel, not card (glossary; visual sweep, 2026-10-26).

- **The image builds again**: `pillow>=10,<14` matches the lock's pillow 13.0.0 (the
  `<13` bound failed `pip check` in the Docker build, so View stopped deploying).

### Added

- **Trends opens the assistant's chart**: `/trends?signal=A&signal=B&start=&end=`
  starts a new trend with those signals over that period; the app declares the `trend` ref kind
  so the assistant's charts link here (Open in Trends).

### Changed

- **The menu reads Overview, Dashboards, Reports, Trends** (owner review, round 10), and the
  Reports page lists its folders as Dashboards does: General first, then each folder, a New
  folder button and the same settings (who sees, who edits its dashboards and reports).
- **A report's text is a Markdown cell**, as in a notebook: headings of four levels, lists,
  tables, quotes and links, written in place (double-click, Shift+Enter or Escape to close) with
  "+ Add a cell below" between cells. Saved text sections become cells once (their heading field
  turns into a `#` heading).

- **View's windows and questions are the suite's** (scale review A1): its nine dialogs (config,
  public links, new dashboard, folder, new report, a trend's line, a report's text, events and
  settings) open in the ui's `Dialog` (focus moves in and stays in, Escape closes, a click outside
  no longer throws typed work away) and its eleven `window.confirm` questions are
  `confirmAction`, with a Delete, Remove, Revoke, Restore, Replace or Send button. A dialog's name
  is now its title ("Config of Feed section").

### Fixed

- **Two "General" folders** (owner review, round 10): General is what is outside every folder,
  so no folder may take its name; a saved open folder named General is folded into it once, and
  a restricted one is renamed "General (restricted)".

- **Quiet text reads at AA contrast** (`@processcraft/ui` 0.53.0, from 0.50.0): the suite's
  contrast fix of ui 0.52.0.
- **A folder's buttons (new dashboard or report, settings, delete) sit beside its heading**, not
  inside the `<summary>` that opens and closes it: a screen reader met a control in a control.

### Added

- **A report's outline**: its headings in a side list that follows the reading; the PDF lists
  them as bookmarks.
- **A report downloads as Word (.docx), HTML or Markdown** besides PDF: Word keeps the headings
  (navigation pane), tables and charts as images; HTML is one self-contained page with its
  outline and charts that show each line's value under the pointer and hide a line from its
  legend; Markdown writes the cells back and each card as its values.
- **A report's public link** (as a dashboard's): the HTML page read when it opens, without sign
  in, until revoked; deleting the report revokes its links.
- **New report › Start from a dashboard**: its pages as headings, its cards as cells in the
  grid's order. Demo: each example dashboard has its report, made this way, in its folder:
  "Plant overview, daily", "Control room shift report", "Loop detail, weekly" and "Suite health
  weekly".

- **The assistant on Dashboards, Reports and Trends:** which dashboard shows what I need, ask
  about the reports, explain the trend on screen.
- **The assistant's works on a report**: summarize it for the shift, what it should also show.
  They replace the page's tasks of the same names.
- **The assistant's works on a dashboard** (processcraft-sdk 0.39.0, PlantCraft
  `docs/assistant.md`, "Works"): explain the dashboard, what changed in the period. The
  assistant's button sits beside the dashboard's title.
- **Reports** (`/reports`): documents of text, cards and the period's events, made into a PDF
  every day, week or month (or on demand) and sent to people and groups in Messages; every PDF
  kept on the report's Sent tab; `report.sent` and `report.failed` events, the schedules in
  PlantCraft and the coming sends on Desk's calendar; search, `#report:<id>` references and an
  Overview widget. ReportLab draws the PDF.

### Changed

- **Older databases upgrade by named steps** (`processcraft-sdk` 0.46.0): the columns added
  since the first release are the stores' `MIGRATIONS`, run once and recorded, and
  `tests/test_upgrade.py` opens each store on its older tables.
- processcraft-sdk 0.35.0: the suite's rules for an app's inside (PlantCraft
  `docs/app-standard.md`, section 5) run here too; the routers no longer import the dashboard
  store (`Conflict` lives with the dashboard model).

- processcraft-sdk 0.28 (an app without an app key reports its conditions); nothing else changes.
- processcraft-sdk 0.26 (the event's own fields and catalogs); no events declared yet.

## [0.4.0] - 2026-10-24

### Added

- Round 7 (owner review 2026-10-24, after Grafana's model; Grafana itself is not embedded):
  - **Variables** (Config › Variables) replace the single asset picker: asset (of a kind, under
    a parent variable), custom and interval types, several values, **All**, `${name}` in signal
    lines, signal names, titles, notes and windows, `?var-name=` in the address, and cards that
    **repeat** for every value picked. Old dashboards open with their asset as the first variable.
  - Cards carry **field options** as in Grafana: defaults (unit, decimals, min, max, colour),
    **threshold steps** (absolute or percent, shown as lines, areas or both, with labels),
    **value mappings**, **overrides** by role, signal or name, and per-kind options (legend
    table, axes, soft min and max, line styles, bar direction, gauge or bar gauge, table columns).
  - A card line can be **every signal of an asset**, filtered by role; a card stands for up to
    24 signals.
  - The **card editor** is full screen: the card type first, then a live preview and the
    options in searchable groups; **Visualization** changes the type and keeps the signals,
    thresholds, mappings and overrides.
  - Cards are **dragged and resized** on the platform's CardGrid; Duplicate places a copy.
  - A visual test (`tests/e2e/test_visual.py`): a 14-card gallery in light and dark, wide and
    phone, checked for overflow, contrast and card errors.
- The suite's search (Ctrl+K, PlantCraft 2026-10-23): `GET /api/search` answers with the dashboards the person sees and the saved trends
  (`processcraft_sdk.server.search`). `@processcraft/ui` 0.25.0 and `processcraft-sdk` 0.21.0
  bring the search box and the queue clock to the frame; the SDK answers the frame's queue
  probe for an app without a queue, so no page logs a 404.

### Fixed

- The move arrows swapped the wrong cards (gone with drag and drop).
- KPI and "value and line" cards are one **Stat** card; gauges take several signals.
- Colours too light on white (or too dark on black) are made readable; text on a filled cell
  is white or black, whichever reads. Threshold areas no longer stretch an axis to 1e300.
- The chart tooltip in the dark theme is readable (`@processcraft/ui` hover label).

### Changed

- `@processcraft/ui` 0.35.0 (readable dark tooltips) and `processcraft-sdk` 0.24.0.
- The suite's visual identity (`@processcraft/ui` 0.28.0, PlantCraft `docs/brand.md`): Inter and
  JetBrains Mono, neutral greys, sentence-case labels, the app switcher at the top of the sidebar
  and the fold button in its bottom corner. The IBM Plex packages are no longer needed.
- Every time in UTC (PlantCraft, 2026-10-23): `processcraft-sdk` 0.20.0 (`dev/revendor --sdk-only`;
  the app keeps its `@processcraft/ui`). The store writes `2026-10-23T14:05:09.123Z` whatever the
  server's time zone, and rows written before with the server's local offset are rewritten once
  at start. `PyJWT` joins `deploy/requirements.lock` (the SDK needs it). Ruff's `DTZ` rules are on.
- Trends (owner review, 2026-10-23): an axis names a unit only when every line on it shares it
  (it named the first line's before). Full screen and the new **Chart** theme ("As the
  platform", light or dark, the PNG included, kept per browser) sit in a bar above the chart on
  the left, clear of Plotly's buttons. The PNG is named after the trend.
- `@processcraft/ui` 0.24.0: `Plot` comes from `@processcraft/ui/plot` (the local Plotly build and
  its type shim are gone), `localOf`/`isoOf` from the package.
- The Starter dashboards button is gone: its two dashboards are templates of New dashboard.
  `POST /api/dashboards/starter` stays for scripts and no longer repeats a dashboard already in
  General. Once, at start, the empty "New dashboard" left by the old button and the untouched
  repeats of a dashboard (same name and cards, never saved again, no public link) are removed.
- A trend card with three units or more shows none on its axis (each line keeps its own).
- `processcraft-sdk` 0.15.0 and `@processcraft/ui` 0.20.0.
- The first page is the Overview every app of the suite shares (`AppOverview`, `@processcraft/ui`
  0.20.0): widgets each person chooses and orders, kept per person in ProcessCraft. Its widgets:
  dashboards, saved trends and public links. The dashboards are their own page (`/dashboards`,
  "Dashboards" in the menu), where a dashboard's breadcrumb returns.

### Added

- Round 6 (owner review, 2026-10-23). **Folders** (`/api/folders`, table `dashboard_folders`):
  who sees (`viewers`) and who edits (`editors`) their dashboards, as `user:<name>` and
  `group:<id>` of the platform (read from `GET /api/v1/groups` once a minute); empty means
  everyone. Enforced on every route: the list, a dashboard, its cards, shares, versions, asset
  pages and widgets (404 when not seen, 403 when not edited). `GET /api/directory` feeds the
  pickers (`RecipientPicker`).
- **New dashboard** dialog: name, folder, start from an empty grid, a template
  (`GET /api/templates`, from the plant's assets) or an exported file; the editor opens at
  `/d/new` and nothing is saved before Save.
- **Config** next to Share and Edit (saves at once), in sections General (folder, tags), Time
  (the window it opens with, `default_window`), Display (`shared_cursor`, `kiosk`), Asset,
  Versions (`dashboard_versions`, last 30 saves, `POST …/versions/{n}/restore`) and JSON
  (export; import from New dashboard).
- Widgets `trends` (the saved trends) and `public-links` (how many public links are open).

## [0.3.0] - 2026-10-23

### Changed

- `processcraft-sdk` 0.14.0: View reads its settings with the SDK's `AppSettings` and connects to
  ProcessCraft with `PlatformRuntime`, the same code as every app (no setting or behaviour changes).

### Added

- The dashboard "Suite health", kept by View over the Historian's source "System" that
  ProcessCraft writes every minute: free disk, last backup and restore drill, every service up,
  response time, errors, CPU, memory and restarts. Created when the source appears, redrawn when
  the services change, read-only (copy it to change it).

### Changed

- `processcraft-sdk` 0.13.0: dashboard cards read their series straight from the Historian
  when the suite sets `PROCESSCRAFT_HISTORIAN_URL`, without the hop through ProcessCraft (and
  back through ProcessCraft when the Historian cannot answer).
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
