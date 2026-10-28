# Devlog

Terse, newest last.

## 2026-10-19: first version, extracted from the monolith's BI dashboard

- New repository in the layout of CPMCraft: `src/trendcraft` (layers i18n, db/config,
  dashboards, query, api/cli; `tests/test_architecture.py`), `tests`, `frontend` (base `/trend/`),
  `vendor` (processcraft-sdk 0.2.0, sha256 `cd2fcb58…3214`), `deploy/requirements.lock`.
- Ported from cpm PR #8 and #11: dashboards of KPI, trend, bar and table cards on a 12-column
  grid, refresh, full screen, public links. Rewritten against API v1: items by signal id, asset +
  role or `$context` + role; reads in `query/cards.py` (one batch series request per trend card,
  steps from a fixed list, at most ~600 points; an empty window anchors to the newest sample).
- Published-report reads: saved dashboards and public links read with the service token (app
  key) through a shared TTL cache (data 10 s, asset metadata 60 s); editors' pickers and preview
  read with their own token. The picked asset must be of the dashboard's `context_kind`.
- Public links: `secrets.token_urlsafe(32)`, stored as SHA-256, shown once, revocable, gone with
  the dashboard; `TRENDCRAFT_PUBLIC_LINKS=false` turns them off; pages served `no-store`,
  `no-referrer`.
- Concurrent edits: `base_updated_at` (millisecond timestamps) answers 409 with the current
  dashboard; the interface asks before replacing the other version.
- Starter dashboards from the asset model: "Loop detail" for the most common asset kind with a
  `pv` role, and one overview per unit.
- Tests: 94 pytest (model, store, card reads, API against `FakeProcessCraft`, public links,
  hostile inputs over 20 API operations, pandas oracle 21/21, architecture, offline, config,
  floors), 16 vitest, 4 Playwright journeys (`make e2e`).
- Found: the SDK's `FakeProcessCraft` value route fails on a 366-day window (it compares ISO
  times written in two formats); the anchor reads use 7d then 366d windows and pass. Reported
  to ProcessCraft.
- Smoke test of the image (`--read-only --cap-drop ALL`, key as a file secret) against the
  real ProcessCraft (generic demo): cards read FIC-101 through API v1, public link page answers
  `no-store` and `no-referrer`, audit rows `trendcraft.dashboard.create` and
  `trendcraft.share.create` with `app_id = trendcraft`.
- KPI values keep their decimals (49.97 shows 50.0, not 50).

## 2026-10-19: the suite's app standard (decided by the owner)

- `app.toml` at the root (id, version, category, summary, runtime prefix/port/uid 10006, requires
  sdk 0.2.0, permissions read assets/signals/series and write audit, nothing published yet);
  `tests/test_app_standard.py` checks it against `pyproject.toml`, `__version__`, settings, the
  Makefile and the Dockerfile.
- `/api/meta` (manifest + `TRENDCRAFT_REVISION`), `/api/help` and `/api/help/<id>` (the Markdown of
  `docs/help`, shown under Help), and `assets/<id>`: the dashboards that pick assets of its kind or
  name it (`GET /api/asset-dashboards?asset=`, read with the person's token). Built files moved
  from `assets/` to `static/` so the asset page has its path.
- Image: `org.processcraft.app.{id,prefix,port}` labels, description = summary, `app.toml` and
  `docs/help` in `/app`. `make package` calls ProcessCraft's `deploy/package.sh` (not landed: G13).
- Card states use the suite's words: `warning` instead of `warn` (shown as "Attention").
- Not yet: references through the SDK's refs helpers and API v1 results on cards (sdk 0.3.0; G12, G2).


## 2026-10-19: processcraft-sdk 0.4.0, app results on cards, the package

- Vendored processcraft-sdk 0.4.0 (built reproducibly from processcraft main 7ddfaab, sha256 in
  `vendor/README.md`); `make ci` runs `processcraft-app check .` first.
- A card item can show another app's result: `{asset_id | $context | signal_id, result:
  "<app>.<kind>"}` on KPI, bar and table cards (not trends). The status comes from the producer
  and is never recoloured by limits; the value is the score (/100) or the result's value; an
  expired result reads stale and unknown. `app.toml` consumes `cpmcraft.loop_health`.
  The editor lists the results published for the picked asset (`GET /api/result-kinds`).
- Subjects are built with the SDK's `asset_ref`/`signal_ref`; stored cards keep bare ids (G12).
- `make package`: SBOM from inside the image (`deploy/sbom.py`, dpkg and Python packages, no
  network), then ProcessCraft's `deploy/package.sh`; verified with a development key (G14).
- Saves in the same millisecond still conflict (`updated_at` always moves forward).

## 2026-10-19: processcraft-sdk 0.5.0, API v1 signal ids (D2)

- Vendored processcraft-sdk 0.5.0 (ProcessCraft main 764c6c9, reproducible build, hash in
  `vendor/README.md`). Signal ids are `<source id>:<tag>`; TrendCraft never builds one.
- Saved cards with bare tags move to the new ids at every start (and `trendcraft
  migrate-signals`): from ProcessCraft's signal list, only a tag exactly one source has; the
  dashboard's `updated_at` stays, so an open draft still saves. Bare tags still read until the
  freeze meanwhile.
- `[requires] asset_types = ["unit", "equipment", "loop"]`: ProcessCraft's asset pages of those
  types (and subtypes) link to TrendCraft's `assets/<id>`.

## 2026-10-19: processcraft-sdk 0.6.0, SBOM in the image

- processcraft-sdk 0.6.0 from ProcessCraft's own `make sdk-wheel` (main 45721a4); the hash
  matches the one ProcessCraft publishes.
- The image carries its SPDX SBOM at `/app/sbom.json` (written by `deploy/sbom.py --here` at
  build time), which the suite bundle collects; `make package` uses it.

## 2026-10-20: trends of what apps archive (HistCraft as the data layer)

- Apps archive what they compute (CPMCraft's loop health over time) in HistCraft as derived
  signals; API v1 lists them with `app`, `subject` and `result` (contract agreed with the
  ProcessCraft thread, SDK 0.7.0). A `result` item on a trend card draws that series (the
  number one, never the text status series); "keeps no history ... here yet" when there is none.
- `/api/result-kinds` also counts `history` (subjects with a series); the editor offers results
  on trends only when some asset has history.

## 2026-10-20: processcraft-sdk 0.7.0

- processcraft-sdk 0.7.0 (ProcessCraft main 026eab8, `make sdk-wheel`, same hash). A result's
  history is found with API v1's `?app=&subject=&result=` filters (closes G15); the editor's
  asset picker filters by subject too.

## 2026-10-20: findings of the suite's clean install

- The card editor's "Signal" toggle now works: an item switched to Signal has `signal_id: ""`
  until a signal is picked, and `itemMode` reads that as signal mode (it read it as asset).
  New e2e journey picks a signal by search.
- FIC-1003 SP's empty last point: API v1's grid (mean per step) leaves the newest step empty
  when no sample arrived in it; reported to ProcessCraft (G16), not papered over here.

## 2026-10-20: processcraft-sdk 0.7.1 (step-hold grid)

- processcraft-sdk 0.7.1 (ProcessCraft main 883effd, `make sdk-wheel`, same hash): API v1's
  grid holds the last value in steps without samples, so a setpoint recorded on change reaches
  the end of its trend (closes G16; test in `tests/test_query.py`).

## 2026-10-20: DashCraft, the suite frame, LinkCraft

- TrendCraft renamed DashCraft (owner, D9): package/CLI `dashcraft`, prefix `/dash/`,
  `DASHCRAFT_*` settings, mark and image `dashcraft`; port 8080 and uid 10006 unchanged. A data
  folder of TrendCraft carries on (`trendcraft.sqlite3` renamed at start, `trendcraft-app-key`
  still read; `tests/test_config.py`).
- processcraft-sdk 0.8.1 (ProcessCraft 459ffa2: suite table with `dashcraft`) and
  @processcraft/ui 0.2.0 vendored with their SHA-256; `processcraft-app check` (frame check) ok.
- The interface draws the suite frame (D6): SuiteShell with Dashboards, Apps, Help and the user
  menu (theme light/dark/system, About with the version, Sign out at ProcessCraft); HelpBrowser
  with folders from `/api/help`'s new `category`. Top menu, user chip and the local copies of
  tokens, fonts and brand marks removed. Full screen hides the frame; public links never had it.
- Cards of CPMCraft and DataCraft read LinkCraft (`dashboards/merged_apps.py`): old result kinds
  and `app-cpmcraft:`/`app-datacraft:` series are renamed when a card loads and once at start
  in the store; app.toml consumes `linkcraft.loop_health` and `linkcraft.signal_quality`.
- 137 pytest (9 e2e journeys, one new for the frame and full screen), 16 vitest.
- Open: the Apps list in the sidebar is empty under the e2e fake (it reads `/api/v1/apps` on
  the shared host, which only ProcessCraft serves).

## 2026-10-20: @processcraft/ui 0.2.2

- Re-vendored `@processcraft/ui` 0.2.2 (ProcessCraft `11ce318`, sha256 `1a3d81f1...b3ab`): every
  relative import in its `dist` carries `.js`, and the phone drawer casts its shadow only when open.

## 2026-10-20: module names (D10), processcraft-sdk 0.8.2, @processcraft/ui 0.3.1

- Owner decision D10: only ProcessCraft keeps the Craft brand. This app is **ProcessCraft
  Dashboards** in documents, the package, `app.toml` (`name`, which `processcraft-app check`
  compares with the SDK's suite table) and the README, and just **Dashboards** inside the suite:
  page `<title>`, help guides, interface and API messages. A card's result label uses the
  producer's short name ("Loop health (Link)"; it was `APP_NAMES` + "Craft", which ui 0.3.1's
  short names would have turned into "DashboardsCraft"). Ids, the repository, `dashcraft serve`,
  `DASHCRAFT_*`, the image and `/dash/` stay; TrendCraft, CPMCraft and DataCraft stay where they
  explain the history.
- Re-vendored processcraft-sdk 0.8.2 (sha256 `e115d981...f959`) and `@processcraft/ui` 0.3.1
  (sha256 `04540bed...445da`), both from ProcessCraft `8dfd352`: the sidebar lockup shows
  "Dashboards" over "ProcessCraft", the Apps list shows short names, and a Messages button above
  the user menu reads ProcessCraft's `GET /api/v1/inbox` (the test fake has none: the 404 leaves
  the button without a badge). Test fakes list the apps by their full names, as ProcessCraft does.

## 2026-10-20: install test fixes (user menu role, signal search order)

- The user menu showed an admin as "editor" (the token's access to this app is only `editor`
  or `viewer`). `/api/me` gained `role`: `admin` for a ProcessCraft admin, else the access; the
  frame shows it. Test: `test_me_role_shows_an_admin_as_admin`.
- Signal search listed the series apps derive (`app-linkcraft:...`) above the plant tag
  searched for. `/api/signals` now ranks plant signals first, then derived series; within each,
  exact, then prefix, then other matches of the tag (or name), ProcessCraft's order kept.
  Tests: `test_signal_search_lists_plant_signals_before_derived_series`,
  `test_signal_ranking_puts_exact_and_prefix_tags_first`. 133 pytest, 16 vitest.

## 2026-10-20: processcraft-sdk 0.8.3

- processcraft-sdk 0.8.3 vendored (ProcessCraft `7bcf870`, sha256 `e87b2459...6757b`), pins in
  the Makefile, CI, Dockerfile, pyproject and `app.toml`; `@processcraft/ui` stays 0.3.1. 0.8.3
  adds `recorded_on_change(signal_id, kind)`: setpoints, modes and text signals hold on series
  grids, with no limit, until their next sample, a null sample, `end` or now (ProcessCraft
  `docs/api-v1.md`, step-hold); `FakeProcessCraft` shapes grids the same way. No code change here.

## 2026-10-20: @processcraft/ui 0.3.2, the sidebar reordered

- `@processcraft/ui` 0.3.2 vendored (sha256 `2b9816bc...ef46d60c`), 0.3.1 removed. The fold
  button is at the top of the sidebar, the Apps list sits at the bottom above Help, and
  ProcessCraft is always the first app, so the platform is one click away from every page
  (owner feedback). No code change here.
## 2026-10-21: a card's data as CSV (G5, part)

- A download button in every card's header saves what the card shows, as read (no new request):
  `cardCsv` and `cardCsvName` in `frontend/src/model.ts`, tests in `frontend/src/csv.test.ts`.
  UTF-8 with BOM so a spreadsheet reads accents; a cell starting with `=`, `+`, `-` or `@` that
  is not a number gets a leading `'`.
- The loop-detail journey downloads the PV trend and checks its header and rows.
- Image and PDF export stay open in G5.

## 2026-10-21: on the suite's shared server and test kit (processcraft-sdk 0.9.0, @processcraft/ui 0.7.0)

- Server: the SQLite store, `app.toml` and help, access checks and the web application (with the
  public `share/` pages) come from `processcraft_sdk.server`; `db.py` and `deploy/sbom.py` are
  gone, `meta.py`, `api/deps.py` and `api/app.py` keep only the parts that are Dashboards' own.
  The image writes its SBOM with the SDK.
- Interface: the API client (public links call it with `signedIn: false`), the error message,
  the Help page and the segmented control come from `@processcraft/ui`.
- Tests: `tests/test_suite_rules.py` (offline, layers, image, API floor, hostile inputs, on
  `processcraft_sdk.apptest`) replaces four files; e2e fixtures use `processcraft_sdk.e2e`
  (`app_url`, as in every app); time budget in `pyproject.toml` (`make test-fast`).
- Docs: `AGENTS.md` is the short module file (the suite's rules live once, in ProcessCraft's
  `AGENTS.md`); the README says how the module is built (with Claude Code, in the open); `make
  test-fast` in Develop.

## 2026-10-21: View and Trends (the suite's organisation, owner decisions of 2026-10-21)

- The suite shows this module as **View** (`@processcraft/ui` 0.8.0 `appLabel`); app.toml, ids
  and `/dash/` stay. Subtitle "Dashboards and trends"; the tour opens with "Welcome to View".
- **Trends**: `/api/trends` (list, save, change, delete; `dashboards/trends.py`, table `trends`)
  and `POST /api/trends/data` (`query/trends.py`), read with the person's token. Up to 6 plots of
  8 signals on a shared time axis; relative window or fixed period (at most 366 days); means of
  an interval (automatic, 1 min to 1 day) or as recorded. A relative period with no samples moves
  to the newest data, like a trend card. Min/max per interval needs a Historian aggregate (next).
- Saved trends belong to everyone; any person with access may save one, its author or an editor
  changes it (audited `trend.*`).

## 2026-10-21: trends, a summary and a style per line

- Each trend line has `agg` (mean, last, first, min, max) and `style` (mode lines/markers/both,
  shape linear/hv/spline, colour or automatic, width, dash, point size, left or right axis);
  saved with the trend, validated in `dashboards/trends.py`.
- `query/trends.py`: means keep the batch series read; other summaries read the samples as
  recorded (at most 200 000 per line, otherwise the mean with a note) and summarise each interval
  in `summarise` (last/first/min/max of the samples in it).
- Interface: the "Aggregation" select is now "Interval"; clicking a line opens its editor; chips
  show the colour and the summary; notes under the chart; `trendTraces` builds the traces and
  axes (a right axis overlays each plot's axis); CSV columns by signal and summary.
- Tests: 3 pytest, 2 vitest. Help page `trends`.

## 2026-10-21 (night): each trend line on its own

- The owner: "configure each line truly on its own: colour, dash and interval; PV blue, solid,
  every minute; SP a lighter blue, dashed, every hour".
- `TrendLine.step_seconds` (None: the trend's interval; 0: as recorded). `query/trends.py` reads
  each distinct interval in one batch and summarises min/max/last/first at the line's own
  interval; every line answers its `step`. The line dialog groups **Data** (interval, summary)
  and **Look** (colour, dash, draw as, width, axis); the chip shows a sample of the line's colour
  and dash and its own interval. `@processcraft/ui` 0.10.0.

## 2026-10-22: the suite's time chart

- Trends and the cards take their layout, hover and buttons from `@processcraft/ui` 0.12.0
  (`timeChartLayout`, `timePlotConfig`); the Historian's point page draws the same chart (owner,
  2026-10-22: "everything that can be standardized is standardized").
- 2026-10-22: card height in rows of the grid (1 to 8 rows of 91 px; width any 2 to 12 of 12
  columns) and pages (tabs) per dashboard, with turning pages in full screen and on public links
  (owner: "quantos espaços de altura", "mais páginas ao dashboard"). Saved dashboards migrate
  once at start (`grid` column: short 1 -> 2 rows, tall 2 -> 4, the same pixels); the API still
  takes a dashboard without `pages` (one page).

## 2026-10-22 (night): the dashboard Suite health

- `dashboards/suite_health.py`: `build(signals)` (pure) and `ensure(store, client)`, which asks
  API v1 for the tags of each `system:*` suffix (`.up`, `.latency_ms`... `host.disk_free`,
  `backup.`) with the service token and creates or redraws the one dashboard with
  `builtin = 'suite-health'` (new guarded column). At start and on the dashboards list, at most
  every 10 minutes. PUT and DELETE answer 409 on it; a copy is an ordinary dashboard; the pages
  hide Edit and Delete and show "Kept by the suite".

## 2026-10-23: round 6, folders and Config (owner review)

- The owner found many "Loop detail" copies: `POST /dashboards/starter` created both templates at
  every click, and New dashboard saved an empty "New dashboard" before the editor opened. Now the
  templates live in the New dashboard dialog (`GET /api/templates`, normalised through
  `DashboardPayload`), `/d/new` keeps the draft in the module and `sessionStorage` until Save, and
  a one-off clean-up (`dashboard_marks`) removes untouched repeats and empty "New dashboard"s.
- Folders (`dashboards/folders.py`, Grafana's folders without nesting): `may_see`/`may_edit` are
  pure; `api/deps.Permissions` reads the folders and, only when one is restricted, the person's
  groups (`Runtime.groups_of`, meta cache, service key else the person's token; unreadable = none).
- Config sections, versions (`dashboard_versions`, 30 kept, written in the same transaction as the
  save), JSON export/import, shared cursor (`cursor.tsx`, one redraw a frame), kiosk.

## 2026-10-24: the browser journeys' time budget

- `suite_seconds` 30 -> 80: `make e2e` runs the 13 browser journeys as one pytest run under the
  same budget, and they now take 33 to 42 s (the assistant button and one Help from ui 0.32.0
  added steps). 80 is about twice that; the unit run takes about 20 s.

## 2026-10-25: Reports (owner: "crie uma aba no view que são os reports e crie alguns exemplos")

- A report is sections (text, card, events, page break) read over one period that ends when it is
  made; cards are the dashboards' cards, read with `read_card` and the period as window; events
  are the latest of up to 10 kinds API v1 keeps, cut to the period, with a count per kind.
- Made three ways (a run's trigger): on its schedule (every day, week or month at a time of the
  installation's time zone, read with View's app key like a published dashboard), Send now
  (an editor) and Download PDF (any viewer, sent to nobody). The PDF (ReportLab, charts drawn by
  hand: trends with a right axis for a second unit, scatter, tiles, dials, bars, tables) and
  every run are kept in SQLite, the newest 100 of each report.
- A send notifies the recipients in Messages (one notification per report, the PDF as its
  action), writes `dashcraft.report.sent` (or `report.failed`, which tells the admins by
  default), the run, PlantCraft's list of schedules and the coming sends on Desk's calendar.
- One process sends (a file lease in the data folder); a send missed while View was down is made
  once at start. A copy starts unscheduled.
- Folders: reports are filed in the dashboards' folders (who sees, who edits); a folder holding
  reports is not deleted.
- Not now (owner, 2026-10-25): reports from notebooks; notebooks never run on the server.
- Demo: `processcraft/demo_seed.py` adds "U-100 daily report", "Control loops weekly
  performance" and "Alarm summary, weekly", each sent once when created.

## 2026-10-26: round 10, reports as documents (owner review of View)

- Text cells are Markdown (`reports/markdown.py`: a small parser for headings 1-4, lists, tables,
  quotes, rules and http(s)/relative links only), drawn by the PDF, Word, HTML and the page.
- One neutral `reports/document.py` (parts, cards as series, tiles, bars, tables) feeds the Word
  (hand-written WordprocessingML, charts rastered with Pillow), the HTML (inline SVG and script,
  CSP `default-src 'none'`) and the Markdown files; the PDF keeps its own drawing.
- A report's public link reuses `dashboard_shares` with a `target` column; the page is made when
  it opens, read with View's app key.
- `GET /api/dashboards/{id}/as-report` drafts a report from a dashboard (`reports/starter.py`).
- General is reserved; a migration folds a saved "General" folder into it.

## 2026-10-27: diagrams phase 4, drawn from assets and drafted by a model (backend)

- `diagrams/autodraw.py`: longest-path layers over feeds/downstream_of (back edges from a
  depth-first walk in name order go along a lane under the graph), loops onto what they
  control or measure (at most three bubbles per symbol, the rest in rows below), grid 10, the
  canvas grows to 8000 px then the drawing shrinks; capped at 600 elements with a note.
- `diagrams/draft.py` + `suite/llm.py`: use `diagram-draft` (off), `write.llm`; the answer's JSON
  is checked element by element, bindings to assets or roles outside the unit dropped.
- Contributions: objects `diagram`, search type Diagram, refs `diagram`, widget `diagrams`,
  start step `unit-diagrams`, works diagram-explain/changes/gaps and diagram-plan.

## 2026-10-27: diagrams phase 5b, public links, kiosk and the diagram panel

- Diagram links reuse `dashboard_shares` with `target` "diagram" (no new table or migration):
  `GET/POST /api/diagrams/{id}/shares`, `DELETE .../{share_id}`, the same `ShareBody`,
  `link_days`, `links_on` and `whole_plant` as dashboards; deleting a diagram revokes its links.
- `GET /api/public/diagram/{token}` (the diagram with only the symbols it uses) and
  `.../data?window&end` (read with View's app key); the page `share/diagram/<token>` reuses the
  viewer with its time bar; `?screen=1` is the kiosk. A rotation between several diagrams is not
  built (a dashboard's pages already rotate, and can hold diagram panels).
- Card kind `diagram` (`diagram_id`, no items, 2 rows or more): read in `api/views.py`
  `diagram_card` (diagrams sit above `query`), live values over the dashboard's window, series
  left out. Signed in, the folder decides (`Permissions.sees`); on a public link only a diagram
  in General or a folder naming no viewers (`deps.everyone_sees`). Reports refuse the kind.
- Tests: `tests/test_diagram_links.py` (14), two journeys in `tests/e2e/test_diagrams.py`.
