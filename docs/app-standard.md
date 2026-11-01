# The PlantCraft app standard

> **Decided** by a maintainer on 2026-10-19 ("sim para todos", all five points D1-D5 below).
> Every app of the suite follows it; Analytics is the reference.

## Decisions (2026-10-19)

| | Decision |
|---|---|
| D1 | This file is the standard for every app. Apps adapt in their own PRs, CPMCraft first. |
| D2 | Signals are named `signal:<source id>:<tag>` (e.g. `signal:pi:FIC1001.PV`), unique even when two sources share a tag. Today's bare-tag ids change once, before API v1 is frozen. |
| D3 | Installing from the internet catalog is **off by default**; an admin turns it on; the publisher signature is always checked. The offline `.pcapp` file always works. |
| D4 | Registering an app already running elsewhere stays: admin only, shown as "external". |
| D5 | One status vocabulary for every app: `ok`, `warning` (shown as "Attention"), `alarm`, `unknown`, plus `usable`. DataCraft maps good/suspect/bad to ok/warning/alarm and "apt" to `usable`. |

## Decisions (2026-10-20, after the MVP review)

| | Decision |
|---|---|
| D6 | Every app draws the same frame, `@plantcraft/ui` (section 10): one left sidebar with the app's brand and the fold button at the top, the app's pages ending with its own Help, and at the bottom every app the person may open (PlantCraft first, always), then the messages button and the user menu (theme, language, tour, about, sign out). |
| D7 | Analysis apps order their pages the same way: Overview, the objects they analyse, Runs, Protocols, Methods, Help. |
| D8 | Sources and signals are Historian's: connections, tags, collection, history and their settings (general, per source, per point; the most specific wins). PlantCraft keeps assets, asset types and which signal fills each role. |
| D9 | CPMCraft and DataCraft become one app, **LinkCraft** (`linkcraft`, `/link/`): signals and loops, with methods wired as blocks into protocols that run on a schedule (section 11). TrendCraft stays a separate app, renamed **DashCraft** (`dashcraft`, `/dash/`): it only shows the data HistCraft and the apps hold. |
| D10 | Only the platform keeps the Craft brand. A module's display name is **PlantCraft <name>** in documents, packages and proposals (PlantCraft Analytics, Historian, View, Plant, Twin, Alarms, Models) and just **<name>** inside the suite (sidebar, launcher). Ids, repositories, images and URL prefixes keep their `<function>craft` form. |

Every app of the suite (Analytics, the Simulator, View, Historian and the ones to
come) follows this one standard: the same metadata, the same repository layout, the same image and
package, the same runtime settings, the same way to name assets and signals, and one way to talk
to PlantCraft and to other apps. A reader who knows one app knows them all; the installer, the
launcher and the security guide treat every app the same ("bem padronizada para não virar uma
bagunça").

Apps are **independent**: each runs alone against PlantCraft, none needs another to work. They
are linked only by what they publish in PlantCraft (section 6). They look like one product
because they draw the same frame (section 10).

This file is the standard. `docs/api-v1.md` is the contract it refers to; `docs/app-package.md`
is the package format. Change them only in a PlantCraft PR, with a devlog line and a message to
every app thread; apps then follow in their own PRs.

## 1. What lives where

| Lives in PlantCraft (central) | Lives in each app |
|---|---|
| People, sign-in, roles, app access | Its own analysis, settings and screens |
| Licences: which apps a client may enable | Its own methods, protocols, parameters |
| Data sources (PI, OPC UA, CSV) and their credentials | Its own schedules and executions (runs) |
| The signal (tag) catalog, signal kinds, units, history reads | Its own database, in its own `/data` volume |
| The asset tree, asset types, attributes, signal roles, relations | Settings people change in the app (they override asset-record defaults) |
| Published results and events of every app | Help pages for its methods and screens |
| Read-only overview of every app's runs and schedules | |
| The audit log, the launcher, the Apps page and the installer | |

Rules that follow from it:

- **Tags, assets and people exist once, in PlantCraft.** An app never keeps its own tag list,
  asset tree or user table; it reads them through API v1 and refers to them as section 2 says.
  It may cache them, but PlantCraft is always right.
- **Only the data layer reaches plant systems.** An app never opens PI, OPC UA, a CSV folder or a
  database of the plant. Historian is the suite's data layer: when it is installed
  (`HISTCRAFT_URL` on PlantCraft), it is the only component that reaches plant data sources and
  data stores, and PlantCraft forwards every signal, series and source request to it (section
  3, "The data layer"). Without Historian, PlantCraft reads the sources itself. The Simulator is
  the one exception: it *is* a simulated plant, and the suite reads it as a data source like any
  other.
- **An app suggests, the client owns.** An app may suggest asset types and roles at install time
  (Analytics suggests "Control loop"); afterwards they belong to the client and the app only checks
  that what it needs is still there, showing "Incomplete record" when it is not.
- **Licences are checked in one place.** PlantCraft only issues a token with `apps[<id>]` for
  apps the client's licence covers and the person may open; the app checks that claim and nothing
  else.

## 2. One way to reference things

Every app writes references the same way: in results, events, runs, URLs, exports, help pages
and its own database.

| Reference | Form | Example |
|---|---|---|
| Asset | `asset:<asset id>` | `asset:u200-fic1001` |
| Signal | `signal:<source id>:<tag>`  | `signal:pi:FIC1001.PV` |
| Person | `user:<user name>` | `user:ana.lima` |
| Result | `<app id>.<kind>` | `linkcraft.signal_quality` |
| Run | `run:<app id>/<run id>` | `run:linkcraft/2026-10-19-0600` |

- **Asset ids are stable.** PlantCraft assigns them, a rename keeps the id, a deleted id is
  never reused. Apps store ids, never names or tree paths; they show the current name read from
  PlantCraft.
- **A loop's signals come from its roles**, never from a tag typed into an app: Analytics asks for
  the asset's `pv`, `op`, `sp` roles. If the client rewires a role in PlantCraft, every app
  follows.
- **Deep links are uniform.** PlantCraft shows an asset at `/assets/<id>`. Every app that works
  on assets serves `<prefix>assets/<id>` (Analytics: `/link/assets/<id>`), which opens its own page
  for that asset or says "this app does not cover this asset". The asset page in PlantCraft
  links to every installed app this way, and apps link to each other the same way (a link in the
  browser, never a call between apps).
- **Which apps the asset page links.** An app is linked when the person may open it and its
  `app.toml` lists the asset's type, or a type it descends from, in `[requires] asset_types`
  (an empty list: never linked). An app whose manifest PlantCraft has not seen (listed in
  `PLANTCRAFT_APPS`, or registered as external) is linked for every asset, and its
  `assets/<id>` says whether it covers it. `/api/home` gives each app's `asset_types` (`null`
  when unknown) and the interface filters with the asset's `type_path`.
- The SDK has `parse_ref`/`format_ref`; no app builds or parses these strings by hand.
- **A signal's id in API v1 is `<source id>:<tag>`** (`scenario:FIC-101.PV`, `pi:FIC1001.PV`;
  the scenario's own source is `scenario`), and its reference is `signal:` plus that id. Done
  on 2026-10-20 (D2). Until API v1 is frozen PlantCraft still reads a bare tag that exactly
  one source has (deprecated); two sources with that tag answer 404 naming both ids.
- **Ids are written as they are, never percent-encoded** (decided 2026-10-20): any id is 1 to
  300 characters, no control characters, no spaces at either end. A PI tag keeps its spaces,
  `/`, `\` and `:` (`signal:pi:Unit 2\FIC 101.PV`). Apps store and compare references as
  text; only a URL path encodes the id (`quote(id, safe="")`). `plantcraft.refs` and
  `plantcraft_sdk.refs` apply this one rule (`check_id`); a source id is lower-case letters,
  digits, `_` and `-` (`[a-z0-9][a-z0-9_-]{0,47}`), so `parse_ref` splits `<source>:<tag>` at the
  first `:` after it.

## 3. Talking: API v1, hub and spoke

```text
          people (browser) ──HTTPS──> proxy ──> PlantCraft  /
                                          ├──> Analytics    /link/
                                          ├──> View    /dash/
                                          └──> ...
   every app ──API v1──> PlantCraft (http://processcraft:8060), never to another app
```

- **API v1 is the only channel**, between PlantCraft and an app *and between apps*. Apps never
  call each other, never read another app's database or files, and never import another app's
  code. What one app offers another goes through PlantCraft as **results** and **events**
  (section 6).
- **Identity** is PlantCraft's Ed25519 tokens (`docs/api-v1.md`): the browser's
  `processcraft_token` cookie for people, a service token from the app key for background work.
  Every request an app receives is verified with `plantcraft_sdk.auth`; the app checks
  `apps[<own id>]`.
- **The SDK is the client.** Apps use `plantcraft-sdk` (vendored wheel, pinned version and
  SHA-256 in `vendor/README.md`) for tokens, references, API calls and tests
  (`FakePlantCraft`). No app writes its own HTTP client for API v1.
- **The SDK is the server skeleton (since 0.9.0).** What every app server does the same way lives
  once in `plantcraft_sdk.server`, never copied into an app: the app's SQLite file and the
  `Store` base class (`store`), `app.toml` and `docs/help` (`files.AppFiles`), the access checks
  (`access.Access`: signed-in person, editor, `guarded` reads of PlantCraft) and the web
  application under the prefix (`web.suite_api` and `web.mount`: `/healthz`, `/api/me`,
  `/api/meta`, `/api/help`, `/api/status`, the built interface and sign-in redirects). The image's
  SBOM is `plantcraft-app sbom` (`plantcraft_sdk.sbom`). An app keeps only its own stores,
  routers, runtime and settings.
- **Operations come with the SDK (since 0.10.0).** Every server logs through
  `plantcraft_sdk.server.logs.configure_logging` (JSON lines, rotating file in the data folder,
  secrets redacted) and runs uvicorn with `log_config=None`; `mount` adds request ids and
  `GET /api/ops/metrics`; `Database(path, version=__version__)` stamps the schema. Each release
  has its `CHANGELOG.md` entry. See `docs/operations.md`.
- **One wheel per SDK version.** Apps vendor the wheel built by `make sdk-wheel` in this
  repository, at the commit of that version: it builds from sdk/python's files with fixed
  timestamps and file modes and the setuptools pinned in `sdk/python/pyproject.toml`, so every
  machine gets the same bytes, and prints the SHA-256 that goes in `vendor/README.md`. Two apps
  on the same SDK version vendor the same hash; a different hash means a different build.
  Offline, point pip at a folder holding that setuptools wheel
  (`PIP_FIND_LINKS=<folder> PIP_NO_INDEX=1 make sdk-wheel`).
- **The data layer.** Apps read signals and series only from PlantCraft (API v1); they never
  know which component answered. With `HISTCRAFT_URL` set, PlantCraft checks the caller and
  forwards to Historian's `/api/v1/data/...` routes (same shapes as API v1) with a token it
  issues to itself; without it, PlantCraft answers from its own sources and history cache.
  Only PlantCraft and Historian reach data stores (`docs/api-v1.md`, "Data layer").
- **Additive only.** Inside v1 fields and endpoints are added, never removed or renamed; apps
  ignore unknown fields and use a documented fallback when a newer field is missing. The one
  exception is the signal id change of D2, done once before v1 is frozen (2026-10-20).

## 4. The app manifest: `app.toml`

Every app has `app.toml` at the root of its folder (`apps/<app>/app.toml`). It is the single source of the app's metadata:
the launcher card, the Apps page, the package manifest (`docs/app-package.md` builds
`manifest.json` from it), the image labels, `/api/meta` and the docs all read it. Nothing else
repeats these values by hand; `plantcraft-app check` (in the SDK) validates it in CI.

```toml
[app]
id = "linkcraft"                    # machine id: lowercase, [a-z][a-z0-9]{2,30}
name = "PlantCraft Analytics"            # PlantCraft {Function} or {Function}Craft
version = "0.1.0"                   # semver; equals pyproject version
category = "Control loop performance"
summary = "Finds control loops that oscillate, stick or sit in manual, and says why."
description = """One paragraph for the Apps page: what it does, for whom, what it needs."""
publisher = "PlantCraft"          # matches a key in deploy/trusted-publishers/
license = "Apache-2.0"              # the code licence; the client's right to use it is PlantCraft's licence
homepage = ""                       # optional; never a vendor or client address
mark = "linkcraft"                  # app mark in the PlantCraft brand family (frontend appMarks)
source = "open"                     # open | closed: a closed app ships compiled code only (app-package.md §8)
languages = ["en"]                  # BCP 47 tags it is translated to; "en" always, each one with its catalogs

[runtime]
prefix = "/link/"                   # URL prefix behind the proxy (table in section 7)
port = 8140                         # port inside the container
uid = 10012                         # container user and group (table in section 7)
health = "/healthz"                 # 200 when ready
image = "linkcraft"                 # image name; tag = version

[requires]
platform = ">=0.6,<0.8"             # PlantCraft versions it installs on (app-package.md §7)
processcraft_api = ">=1.0,<2"       # API v1 version range
sdk = "0.2.0"                       # plantcraft-sdk version vendored
asset_types = ["loop"]              # types it works on (subtypes included); [] if none
roles = { loop = ["pv", "op"] }     # signal roles it needs per type

[tested]                            # stamped by the package build from compat/<version>.json, never by hand
platform = []                       # the PlantCraft versions its compatibility tests passed on

[license]                           # optional; a closed app that needs a licence (app-package.md §8)
required = false                    # true: it works only with a .pclicense its publisher signed
grace_days = 14                     # days it keeps working after the licence ends (0 to 90)

[permissions]                       # shown to the admin before install; held to every API v1 route
read = ["assets", "signals", "series", "results"]   # also: events runs schedules people knowledge
write = ["audit", "results", "events", "runs", "schedules"]   # also: series notifications knowledge
plant_write = false                 # always false; true is a maintainer decision (AGENTS.md)
outbound = []                       # outbound hosts it may contact; [] for every app today

[publishes]                         # its outputs: results and events other apps may read (section 6)
results = [{ kind = "loop_health", subject = "asset:loop" }]   # read by others as linkcraft.loop_health
events = ["finding.opened", "finding.closed"]                  # sent as linkcraft.finding.opened

[consumes]                          # its optional inputs: the app must work without them
results = [{ kind = "linkcraft.signal_quality", subject = "signal" }]

[suggests]                          # asset types offered at install; the client owns them afterwards
asset_types = ["loop"]

[backup]                            # its data folder in the suite's backup (docs/operations.md)
sqlite = ["linkcraft.sqlite3"]      # online SQLite backup, then integrity_check
files = ["secret.key"]              # copied as they are; a folder ends in "/"
skip = ["logs/"]                    # left out; anything not named is copied as a file
```

## 4b. What an app adds to PlantCraft: `[contributes]`

A new app must reach every
place of the platform **without a change to the platform**. So an app declares, in its
`app.toml`, everything PlantCraft draws for it, and PlantCraft draws from the declarations
without knowing the app. The manifest has three groups, each with one role:

| Group | For | What |
| --- | --- | --- |
| `[app]` `[runtime]` `[requires]` `[permissions]` `[backup]` | the installation | section 4 |
| `[publishes]` `[consumes]` | the other apps, through PlantCraft | results, events (section 6), series (below) |
| `[contributes]` | PlantCraft itself, which draws them | uses of a language model, widgets, search, calendar feeds, to-do kinds, reference kinds, installation settings, Settings pages, work queue, objects and examples for notebooks, the assistant's works and tools |

```toml
[[contributes.llm]]                  # a use of a language model, in Setup > Language models
id = "algorithm-draft"               # called as <app id>:<id>; the app never holds a key
title = "Draft an algorithm"
description = "Builds an algorithm from what a person describes."
reads = "The description and the block catalog; no plant data."
default = "default"                  # the default model, or "off" until an administrator picks one
                                     # (an app outside the suite's bundle always starts off);
                                     # [permissions] write needs "llm"

[[contributes.widgets]]              # its data stays at <prefix>api/widgets/<id> (docs/widgets.md)
id = "worst-assets"
title = "Worst assets"
size = "m"                           # s, m or l; sizes = [{ w, h }] up to three
default = true

[contributes.search]                 # it answers <prefix>api/search (section 10)
types = ["Block", "Algorithm", "Loop"]

[[contributes.calendar]]             # a feed of dated items in Desk's calendar
id = "reviews"
title = "Loop reviews"
visible = false                      # a chip each person switches on

[[contributes.todo]]                 # a kind of to-do it may give a person or a group
id = "review-schedule"
title = "Review a schedule"

[[contributes.assistant.tools]]      # a read-only tool for the assistant (SDK 0.61.0): served at
id = "search_documents"              # <prefix>api/assistant/tools/<id>, called as the person,
title = "Search the plant documents" # listed to the model as <app id>_<id> (docs/assistant.md)
description = "The plant's manuals and guides: causes, procedures, limits. Cite what you use."
[[contributes.assistant.tools.args]]
key = "query"
title = "What to find"
required = true

[[contributes.start]]                # a new plant's first step (SDK 0.65.0): offered on Assets ›
id = "analyze-loops"                 # Import once an import is applied, sent as the person to
title = "Monitor the loops"          # POST <prefix>api/start/<id> with StartIn (what the import
open = "/link/results"               # wrote); it answers StartOut and skips what it did already

[[contributes.refs]]                 # #protocol:<id> in messages, actions and notes
kind = "protocol"                    # never one of PlantCraft's (asset, signal, action, run...)
title = "Algorithm"
url = "/link/algorithms/{id}"

[[contributes.settings]]             # an installation setting, drawn in Setup > Apps
key = "workers"
title = "Workers"
type = "integer"                     # text, number, integer, boolean or choice (with options)
default = 2
min = 1
max = 16

[[contributes.setup]]                # one of its pages, listed in PlantCraft's Setup
title = "Sources"
path = "/hist/sources"               # under the app's prefix

[[contributes.objects]]              # a kind of object notebooks read: pc.app("link").blocks()
kind = "block"                       # served at <prefix>api/objects/<kind>[/<id>]
title = "Blocks"
run = "local"                        # none, local (runs in the notebook) or app

[contributes.notebooks]
examples = true                      # it serves <prefix>api/notebooks/examples: Examples/<app>
runtime = ["linkcraft", "plantcraft_sdk"]  # packages zipped for local runs
entry = "linkcraft.notebook"         # run(kind, item, plant, app, **options)

[contributes]
queue = true                         # it answers <prefix>api/queue (section 6)

[[publishes.series]]                 # what it writes to the Historian, in the Historian's format
name = "{schedule}.{output}"         # the pattern of its point names
title = "Schedule outputs"
type = "number"                      # number, integer, boolean, text, instant, structured, run_series
per = "asset"                        # asset (a result asset under it), signal or app
retention = "app"                    # app (set per point, managed_by), historian, or days (0: forever)
```

- **One owner per contract.** The format of each one is written by the platform or by the app
  every other app relies on, never by the app that uses it: the Historian owns the series, Alarms
  the event (section 6), Desk the calendar item and the to-do, PlantCraft the rest.
- **Checked in CI.** `plantcraft-app check` validates every table (`plantcraft_sdk.contributes`):
  an unknown key, a repeated id, a reference kind of PlantCraft's or a setting whose default is
  not its type fails the app's `make ci`.
- **Shown before the install.** The package carries the tables (`docs/app-package.md`); the Apps
  page shows "What it adds to PlantCraft" beside the permissions, and the installed apps' table
  says what each one adds.
- **Sent when the app starts.** The SDK's server sends all of it at once,
  `PUT /api/v1/contributions` (the events go to the catalog with it), retried while PlantCraft is
  not up and never stopping the app; an app without an app key carries it in
  `GET /api/ops/metrics`, which PlantCraft's monitor reads every minute. PlantCraft keeps one row
  per app, replaced whole (`plantcraft.apps.contributions`); `GET /api/v1/contributions` lists
  what every installed app adds.
- **Every screen reads the registry**, never a list written for an app: Settings › Language
  models, Desk's calendar and to-do, the Overviews, Settings › Apps, Alarms' catalog. An app that is
  uninstalled leaves the screens; what it wrote (events, series, to-dos) follows its retention.
- **Only fields are added.** A table PlantCraft does not know (an app newer than its platform) is
  set aside and shown on the Apps page, never refused. An app asks what its platform draws with
  `client.features()` (`GET /api/v1/installation`, `features`) and hides what is missing.
- **Where it stands (SDK 0.33.0).** Every table is checked, packaged, sent and kept, and the Apps
  page draws it. Calendar feeds and to-dos are live (SDK 0.33.0: `client.put_calendar`,
  `put_todo`, `todos`, `close_todos`; Desk draws them, `docs/desk.md`), and so are reference
  kinds: `#protocol:flow` gets the kind's title and the page `url` (under the app's prefix,
  checked by the manifest), named by the app's text about it (`PUT /api/v1/knowledge`) or by its
  id. Installation settings and Settings pages are in Settings › Apps (`/setup/apps`): PlantCraft draws
  each declared setting by its type, keeps what the administrator chose (a secret is never shown
  again) and the app reads them with `client.app_settings()`
  (`GET /api/v1/contributions/settings`, defaults for what was not set). The uses of a model
  are in Settings › Language models (SDK 0.32.0, `client.llm`). Widgets, search and queues keep
  their probes for now.
- **Objects for notebooks (SDK 0.48.0).** Each `[[contributes.objects]]` kind is served with
  `plantcraft_sdk.server.objects.AppObjects` (a lister and a getter, the person's identity
  given; a kind with `run = "app"` adds `@objects.runner`, which starts the run in the app's own
  queue behind an administrator's switch and answers the object to read back) and
  `notebooks_router(EXAMPLES, manifest)` serves the examples
  (`plantcraft_sdk.notebooks.Example`) and the runtime zip. A local run happens in the
  notebook: the runtime may import only what a notebook has (numpy, pandas, scipy, matplotlib,
  pydantic), never a web server or an HTTP client, and reads data through the `plant` it is
  given (`plantcraft_notebook`). `apptest.objects_problems` checks the routes and the examples,
  and `apptest.run_examples` runs every example's cells as a notebook does, against the app and
  the fake PlantCraft (SDK 0.49.0).
- **What stays in code.** The live data keeps coming from the app (a widget's values, the answers
  of a search, a calendar's items), and each page still declares its own assistant tasks, menu
  entries and tour in `@plantcraft/ui` (section 10): they belong to a page, not to the app.

## 5. Folder layout

The same files, in the same places, in every app's folder (`apps/<app>`, or the root of an
external app's own repository):

```text
app.toml            the manifest (section 4)
README.md           what the app is, how to run it against PlantCraft, screenshots
AGENTS.md CLAUDE.md the suite's agent rules (copied from PlantCraft, app section filled in)
SPEC.md ROADMAP.md  product spec and readiness (template: docs/product-template-SPEC.md)
SECURITY.md LICENSE ATTRIBUTION.md
Makefile            ci, deps, lint, format, test, frontend, e2e, image, package (same names)
Dockerfile          the three-stage image (section 7)
pyproject.toml      Python package; version = app.toml version; ruff==0.17.1, line length 100
deploy/requirements.in, deploy/requirements.lock   hash-pinned runtime dependencies
vendor/             plantcraft-sdk wheel + README.md with its SHA-256
src/<id>/           code; api/ (routers on plantcraft_sdk.server), cli.py (`<id> serve`)
frontend/           React + Vite + TypeScript, PlantCraft tokens and brand, no CDN
tests/              unit, contract (against FakePlantCraft), hostile inputs, floors.toml, oracles/, e2e/
docs/               STATUS.md, gaps.md, devlog.md, help/ (one page per method or screen)
```

`make ci` is `deps standard lint frontend test` in every app (`standard` is
`$(PYTHON) -m plantcraft_sdk.app_cli check .`; `plantcraft-app check` refuses another `ci`,
SDK 0.44.0); CI runs the same on Linux plus `e2e` and `image`.

### Inside `src/<id>/`: the same layers in every app

StarterCraft (`templates/app`) is the model; `plantcraft_sdk.apptest` checks each rule.

```text
config.py meta.py   settings and the manifest (layer 0)
suite/              the only code that talks to PlantCraft for the app (layer 1): events.py
                    (EventCatalog, by the names of [[publishes.events]]), desk.py (calendar feeds,
                    to-dos), llm.py (each [[contributes.llm]] use), results, links; a class Suite
                    joins them and the runtime builds it with the service client
<object>/           the app's own object (layer 2): models.py (pydantic drafts), store.py (its
                    tables), service.py (the rules: store + suite, no HTTP)
api/                routers (layer 3): validate, check access, call the service, answer; a
                    page reading the plant as the person uses rt.user_client(user) here
api/runtime.py      builds the clients, the stores, the services and the Suite
cli.py              `<id> serve` and the app's commands (layer 3)
```

- `suite_problems(root, id)`: only `suite/`, `runtime.py` and `cli.py` use the service client
  or `EventCatalog`.
- `router_problems(root, id)`: no router imports a `store` or a database driver.
- `contribution_problems(root, id, api_routes(app))`: every event, calendar feed, to-do kind and
  model use `app.toml` declares is named in the code; each widget, search and reference kind
  has its route.
- `ui_copy_problems(root, ui_src)`: no copy of an `@plantcraft/ui` file, no own `Plot.tsx`,
  `HelpPage.tsx` or brand colours.

## 6. Results and events: how apps link

Apps share findings through PlantCraft, never directly. A result on an asset or signal is how
apps link: DataCraft writes the data quality of a signal or asset, CPMCraft
reads it before judging a loop; CPMCraft writes the loop's health, View and the asset page
show it. The asset page in PlantCraft lists every app's results for that asset.

- **Results**: the latest value an app computed about a subject. `PUT /api/v1/results` with

  ```json
  [{"subject": "asset:u200-fic1001", "kind": "loop_health",
    "status": "ok|warning|alarm|unknown", "score": 0-100 or null, "usable": true|false|null,
    "value": 12.3 or null, "summary": "one line people read",
    "detail": {}, "at": "<iso>", "expires_at": "<iso> or null"}]
  ```

  The app id comes from the token. One row per (app, subject, kind): a new PUT replaces it.
  - `status` is the one vocabulary of the suite. `score` is optional (100 = best).
    `usable` is optional and means "other apps may trust this subject's data for analysis"
    (DataCraft's "apt"); consumers treat `null` as "don't know".
  - `expires_at`: after it, PlantCraft reports the result as `unknown` ("stale"), so an app
    that stopped running never leaves a green light behind. Producers set it to about two run
    periods.
  - **Aggregation is the producer's job.** If a loop's quality is the worst of its signals,
    DataCraft computes it and publishes it on the asset; consumers never recompute another
    app's logic.
  - Read with `GET /api/v1/results?subject=&app=&kind=` (several subjects in one call, one
    `subject` parameter each: ids may hold commas). History:
    PlantCraft keeps every change of `status` for 90 days, read with
    `GET /api/v1/results/history?subject=&kind=&after=`.
- **Events**: something that happened. `POST /api/v1/events` with
  `{"kind": "<app>.<noun>.<verb>", "subject", "summary", "refs": [...], "payload": {...}}`; read
  with `GET /api/v1/events?ref=&kind=&after=`. The asset page shows them as its timeline. Many
  events go as one list (up to 1,000 per request, `client.post_events`), never one request each.
  - **Every app declares its events** (2026-10-25), even when it writes none yet:
    `[[publishes.events]]` in `app.toml`, one table per event with `name` (`noun.verb`, sent as
    `<app id>.<name>`), `title`, `description`, the default `severity` (info, ok, warning,
    critical), `category` (process, equipment, data, run, system, user), `phase` (`instant`, or
    `interval` for a condition sent as `start` then `end` with one `key`), `payload` (each field
    and what it holds) and the `rule` Alarms suggests for it (`when` event, open or repeated,
    `minutes`, `count`, `priority`, `creates` alarm or notice, `notify` owner or admins,
    `enabled` for system events only). The code writes them with
    `plantcraft_sdk.events.EventCatalog` (`catalog.event("run.failed", subject, ...)`), so a
    name the catalog lacks fails in the app's tests; the SDK's server sends the catalog (with the
    rest of section 4b, `PUT /api/v1/contributions`) to
    PlantCraft when the app starts.
  - **Apps report, Alarms judges.** An app never notifies anyone about its events and never
    decides they are alarms: it says what happened and how bad it thinks it is. Alarms' rules
    decide what becomes an alarm, its priority and who hears it (`apps/alarms/SPEC.md`).

- **Derived signals**: series an app computed (a loop health score over time, a filtered flow,
  a mass balance). The app publishes them with `PUT /api/v1/series` (`client.put_series`) as
  signals of its own source, `app-<app id>:<name>`, never into its own database for others to
  read: PlantCraft stores them (or forwards them to Historian, the data layer), and every app
  reads them back like any other signal, through the v1 series, batch and value routes.
  `GET /api/v1/signals?app=&subject=&result=` finds them; each carries `app`, `subject` (the
  asset or signal it is about) and `result` (the result kind it comes from). Scores use the
  unit `/100`. Only the app's service token writes them, and only to its own source.

Kinds are named `<app id>.<name>` when read by others (`linkcraft.signal_quality`,
`linkcraft.loop_health`) and listed in `app.toml` (`[publishes]`, `[consumes]`). A consumer must
work, with a visible "not available", when the producer is not installed or its result expired.

### Methods, protocols, schedules and executions belong to each app

Each app has its own methods, protocols, parameters and way of running (a CPM round over loops,
a Modelica simulation with its inputs and outputs, a data-quality sweep over signals). They are
**not shared between apps** and PlantCraft does not run them. PlantCraft only gives a **read-only overview**
of what every app is running, fed by the apps through API v1:

- **Runs**: `PUT /api/v1/runs` with `[{"id": "<app's run id>", "name", "status":
  "queued|running|done|failed|cancelled", "trigger": "manual|schedule|api", "started_at",
  "finished_at", "subjects": ["asset:..."], "summary", "url": "<link into the app>"}]`; one row
  per (app, id), replaced on PUT; PlantCraft keeps the last 90 days.
- **Schedules**: `PUT /api/v1/schedules` with the app's full list
  `[{"id", "name", "cadence": "<people's words, e.g. every day at 06:00>", "next_run",
  "enabled", "url"}]`; a PUT replaces that app's list.
- Read with `GET /api/v1/runs?app=&status=&subject=` and `GET /api/v1/schedules?app=`. The
  Executions page in PlantCraft shows both for every app, each row linking into the app, which
  is where people start, stop or change them.

### A work queue looks the same in every app

An app that queues work (Analytics' executions, Models' simulations) shows its queue one way: the numbers of now (in the queue, running, done and failed in the last hour, how
long the oldest item has waited, the workers busy) and the same numbers over 1 hour, 24 hours,
7 days and 30 days.

- **Server** (`plantcraft_sdk.server.queue`): the app writes `now(since) -> QueueNow` from its
  own queue table; `QueueSampler(QueueMetrics(db), now)` keeps a sample every 15 s for 30 days
  in the app's database (table `queue_metrics`); `GET <prefix>/api/queue?window=1h|24h|7d|30d`
  answers `queue_answer(now, metrics, window)`, format `plantcraft-queue/1`
  (`{"now": {...}, "history": [{"at", "queued", "running", "done", "failed", "cancelled",
  "delay_seconds", "average_seconds"}]}`). An app may add its own keys beside them (Models: the
  runs with their progress).
- **Monitor** (`plantcraft_sdk.server.ops.report_queue(now)`, SDK 0.19.0): the app names what
  its queue holds now; `GET /api/ops/metrics` then carries `queue` (`queued`, `running`,
  `workers`, `delay_seconds`, `done_hour`, `failed_hour`), PlantCraft records it as
  `system:<service>.queue_items` and `.queue_wait_min` and its watch tells the administrators
  when the queue does not drain (`docs/operations.md`, section 4).
- **Interface** (`@plantcraft/ui`): `QueuePanel` (tiles of now, the history with its period)
  on the app's executions page and `QueueSummary` in its Overview widget; both take the app's
  Plotly component, like the time chart.
- **Every app's sidebar** (`@plantcraft/ui` 0.25.0, `SuiteQueueButton`): one line above the
  messages button sums what runs and waits across the suite ("4 running · 12 waiting") and opens
  each app's numbers, with a link to `<prefix>executions`. It reads the same
  `GET <prefix>api/queue?window=1h` every 30 s while the page is visible; an app that answers
  404 or another format is asked once, so an app only has to serve the endpoint. The line turns
  to attention when the oldest item has waited 30 minutes or an item failed in the last hour.

## 7. Image, runtime settings and the suite table

**Image.** Three stages like Analytics' `Dockerfile`: frontend build (Node, never shipped),
hash-checked wheelhouse (`--require-hashes --only-binary=:all:`, SDK from `vendor/` checked by
SHA-256), runtime (Python slim pinned by digest, `--no-index`, no pip, no compilers, non-root
`uid`, `/data` owned by it, `HEALTHCHECK` on `health`). OCI labels: title, description
(= summary), version, revision, created, licenses, source, and `org.processcraft.app.id`,
`org.processcraft.app.prefix`, `org.processcraft.app.port`.

**Container rules** (the installer and `deploy/compose.yaml` apply them, the app must work under
them): read-only root filesystem, state only in `/data`, scratch in a `/tmp` tmpfs, `cap_drop: ALL`,
`no-new-privileges`, `pull_policy: never`, internal `apps` network only, no published port.

**Settings**, the same names in every app (`<ID>` is the id in capitals):

| Variable | Meaning |
|---|---|
| `PLANTCRAFT_URL` | PlantCraft inside the network (`http://processcraft:8060`) |
| `PLANTCRAFT_APP_KEY_FILE` | file with the app key (`/run/secrets/<id>_app_key`) |
| `<ID>_ROOT_PATH` | the prefix without trailing slash (`/link`) |
| `<ID>_DATA_DIR` | `/data` |
| `<ID>_HOST`, `<ID>_PORT` | bind address and port |

An app reads them once, with `plantcraft_sdk.server.settings.AppSettings` (its `Settings`
extends it with the app's own fields), and connects to PlantCraft with
`plantcraft_sdk.server.platform.PlatformRuntime` (HTTP client, token verifier, service client,
a client per person and the audit log).

**Endpoints every app serves** (under its prefix): `/healthz` (200 when ready, no auth),
`/api/meta` (`app.toml` as JSON plus `revision`, no secrets; auth required), `/api/help`
(the help pages index, `[{id, title, category}]`; `/api/help/<id>` is `{id, title, markdown}`), `assets/<id>` (section 2) when it works on assets; everything else needs
a valid token, and a browser without one is sent to `/login?next=<url>`.
Built frontend files are served from `<prefix>static/` (Vite `build.assetsDir = 'static'`);
`assets/` is reserved for the asset deep link.

**An app outside the table** (a company's own, one from the template, a publisher's) names
only its prefix, which must be free on the installation (scale review E5, 2026-10-25,
`plantcraft-sdk` 0.38): `port` may be left out (it listens on 8000 inside its own container;
two apps may use the same port) and so may `uid` (its container user comes from its id,
`app_manifest.default_uid`, 20000 to 59999, the same on every installation). It may not take a
prefix or a uid of the table below.

**The suite table** (assigned here, nowhere else):

| App | id | Prefix | Port | uid |
|---|---|---|---|---|
| PlantCraft | `processcraft` | `/` | 8060 | 10001 |
| CPMCraft (merged into LinkCraft, D9) | `cpmcraft` | `/cpm/` | 8070 | 10002 |
| proxy | | | 8443 | 10003 |
| PlantCraft Simulator | `simcraft` | (OPC UA `opc.tcp://plantcraft:4840`) | 4840 | 10004 |
| installer | | | | 10005 |
| PlantCraft View (DashCraft, was TrendCraft, shown as View since 2026-10-21) | `dashcraft` | `/dash/` | 8080 | 10006 |
| DataCraft (merged into LinkCraft, D9) | `datacraft` | `/quality/` | 8090 | 10007 |
| PlantCraft Historian | `histcraft` | `/hist/` | 8100 | 10008 |
| PlantCraft Alarms | `alarmcraft` | `/alarm/` | 8110 | 10009 |
| PlantCraft Twin (merged into Analytics, 2026-10-22) | `twincraft` | `/twin/` | 8120 | 10010 |
| PlantCraft Models | `modelcraft` | `/model/` | 8130 | 10011 |
| PlantCraft Analytics | `linkcraft` | `/link/` | 8140 | 10012 |
| PlantCraft Documents | `doccraft` | `/doc/` | 8150 | 10015 |
| PlantCraft PID (closed, its own package, not in the bundle) | `pidcraft` | `/pid/` | 8160 | 10016 |
| llm-egress | | | 3128 | 10014 |
| compute | | | | 10020 |

`compute` is the user of the local compute worker's `compute-gateway` and of the apps' executors,
which share `data/compute-jobs` (docs/compute.md).

**Apps outside the table** (a company's own app, one made from `templates/app`) pick their own
id, prefix, port and uid. `plantcraft-app check` and the platform's installer accept them when
none of the three is a row's, the port and uid are not the stack's (8060, 8443, 4840; 10001,
10003, 10004, 10005), the uid is between 10002 and 65533, and the name is not "PlantCraft X",
which the suite's own apps keep (name yours like `StarterCraft`).

## 8. Install and package

The suite starts as **PlantCraft alone**; the admin adds apps from PlantCraft's Apps page.

Every app ships the same way: `make package` builds the image, exports it, writes the SBOM
(SPDX JSON) and builds `<id>-<version>.pcapp` from `app.toml` with PlantCraft's
`deploy/package.sh` (format in `docs/app-package.md`), signed with the publisher key. Three ways
to add an app, all from the Apps page:

1. **From the catalog (internet)**, the easiest: the Apps page lists the published apps, the
   admin picks one, PlantCraft downloads the `.pcapp`. Off until an admin turns it on.
2. **From a file**, for isolated networks: upload the `.pcapp`, or `./install.sh --add
   <id>-<version>.pcapp`. Always available.
3. **Register an external app** already running elsewhere (a developer's machine, another
   server): admin only, shown as "external" because PlantCraft did not check its code; it gets
   an app key like any other.

In 1 and 2 the installer service checks the publisher signature and every SHA-256, refuses a
package whose licence the client does not hold, shows the `[permissions]` to the admin, and runs
it under the rules of section 7. Updating is the same flow with a newer version; the previous
image is kept for rollback.

## 9. Checklist for a new app

1. Ask a maintainer for the repository (private). Take the id, prefix, port and uid from section 7.
2. Copy an app's layout (section 5; PlantCraft Alarms is the smallest), write `app.toml`,
   `SPEC.md`, `ROADMAP.md`. Build the server on `plantcraft_sdk.server`, never on a copy.
3. Vendor the SDK wheel; read data only through it; reference things only as section 2 says;
   test against `FakePlantCraft`.
4. Publish what others may use as results and events (section 6) and report runs and schedules;
   never call another app.
5. Serve `assets/<id>` if it works on assets.
6. `make ci` green, `make package` builds a signed package, it installs on a clean offline suite.

## 10. Interface: one frame for every app

The short checklist of these rules, to read before drawing or reviewing a screen, is
[ui-guidelines.md](ui-guidelines.md) (navigation only through the side menu and tabs, no buttons
at the top of an Overview, buttons, forms, tables and widgets).

Every app's web interface installs `@plantcraft/ui`, built from `ui/` in this repository and
vendored like the SDK wheel: `make ui-package` writes `plantcraft-ui-<version>.tgz`, the app
copies it to `vendor/` next to the wheel and names it in `frontend/package.json`
(`"@plantcraft/ui": "file:../vendor/plantcraft-ui-<version>.tgz"`), with its SHA-256 in
`vendor/README.md` (`plantcraft-app check` verifies all three). The package holds:

- `tokens.css`, `fonts.css` (self-hosted Inter and JetBrains Mono, bundled in the package) and `shell.css`, imported first by the app's styles;
- `SuiteShell`: the sidebar, top to bottom: the app's name (the app switcher, whose list floats over the sidebar and the page, as wide as its names); the suite's search; the app's pages;
  **Apps**, every app the person may open, read from `GET /api/v1/apps` on the shared host, with
  PlantCraft always first (added by the frame, so every app links back to the platform);
  four quick buttons that cross every app, all the same size:
  **Messages** and **Notifications** with their unread counts, the **Assistant** and the suite's
  **work queues** (below), each opening the same panel (`SidePanel`) out from under the sidebar's
  edge, over the page, without leaving the app, with **Full page** and close in its header; one
  panel at a time, all of one width: going from one straight to another
  swaps what is inside without sliding, the button of the open panel closes it, and going to another
  page or app closes it. Messages and Notifications show their unread counts; the queues' button turns
  while work runs, is green for a moment when it finished well and red after a failure until the
  panel is opened. Last in the row, the **fold button** (the [ key folds too), so it stays where it
  was clicked. Then the person's menu, a floating window beside the sidebar, with the person's profile (PlantCraft's
  `/people/me`), **Preferences** (PlantCraft's `/preferences`, owner 2026-10-24: where times are shown, Local time, UTC or this device, and the language, saved for the person), **Help** (one for the suite, owner 2026-10-23: PlantCraft's `/help?app=<id>`, open at
  the app's guides, which it reads from the app's `/api/help`; `helpTo: null` leaves it out), the tour and Sign out, under the theme, which comes first; the version is a quiet line at its foot. The person's menu, the list of apps and the quick panels close alike: Escape or a click outside them, also on the app's page inside the frame (`dismiss.ts`). It folds to icons (the Apps keep their marks) and is a drawer on a
  phone. A page entry may name a `section` ("Work", "Administration"): the frame draws a heading
  over each group (a line when folded to icons). PlantCraft groups the day to day (Home, Assets,
  Actions) apart from what administrators do once or seldom (Users, Apps with their keys, Backups,
  Updates, Settings). **An app's Settings page is always the last
  entry of its menu**;
- the **frame**: in
  an installation PlantCraft draws the sidebar once and every app runs beside it as content only,
  so switching apps never loads the sidebar again and every app shows the platform's current
  sidebar, whatever ui version it was built with. The proxy sends a page the person opens
  (`Sec-Fetch-Dest: document`, signed in, under an app's prefix, not `/api/`) to PlantCraft, which
  loads the same address in a same-origin iframe marked `data-pc-frame`; that request goes to the
  app. Inside it `SuiteShell` draws only the app's pages (`FramedShell`) and tells the frame, by
  `postMessage` on the same origin only, its sidebar entries (icons as SVG markup, which the frame
  cleans to shapes only), where it is and the page's title; the frame asks it to go to a page, to
  open its assistant (the page's own tasks live in the app) or its tour. Links out of the app and
  the frame's shortcuts ("[" and Ctrl+K) go to the frame. The last three apps opened stay loaded,
  hidden, behind PlantCraft's pages. An app that does not say it is ready in 4 s (a ui before
  0.39.0) is opened on its own page with `?pc-frame=off`, which the proxy leaves to the app. Run
  alone (`npm run dev`, the template) an app still draws its whole sidebar. An app needs nothing
  of its own for this: `SuiteShell` does it;
- the **Messages** panel (`MessagesDrawer.tsx`): PlantCraft's own Messages page, `/messages?embed=1` on the
  same host, out from the sidebar over the page; links outside Messages open in the whole window, the page
  tells the frame when something was read (`announceMessagesChanged`), Escape or the close button
  returns to the same screen, and **Full page** opens `/messages`. `openMessages(conversation?)`
  opens it from code;
- the **Assistant** button in that row above the person, and its side panel. One panel at a time: opening one closes the other.
  Each page tells it what it can do there, once, in the page's code:
  `useAssistantPage({ subject?, title, place, context, tasks })`. `place` is where the person is
  ("Alarms › FIC-101 HI"); `context` what the page shows, in a few lines, for the model; each task is
  `{ label, hint?, instructions, ask?, context?, subject? }`: what the person picks, what the model is
  asked to do, the person's words it needs first (`ask: "Which execution?"`) and what it adds to the
  context when chosen (a table's rows). Offer the three to five things people do on that page; the
  suite adds "Explain this page" and "What needs attention here?". A page that declares nothing still
  gets the button, with its visible text as the context. The model reads the plant as the person,
  through PlantCraft's tools, so a task never needs more access than the person has
  (docs/assistant.md);
- Folders (`FolderColumn`, `FolderField`, `FolderPlaceLine`, `useFolders`, set up once with
  `configureFolders`) over `plantcraft_sdk.server.folders` (`FolderStore` with the app's kinds,
  `folders_router`): every list of objects people make files them the same way, a column on the
  left (`?folder=`), Move to folder on the object's page (who moved it, when), the folder a new
  object goes in on its form. Analytics (blocks, algorithms, schedules) and Models (models, blocks,
  studies) use them; shipped objects (a block library the app ships) stay out;
- Versions: `VersionsTab` (About, then each version), `ComparePicker` under it (`?versions=1,3`
  opens the object's Compare tab), `CodeDiff`/`lineDiff` for code; what a comparison runs is the
  app's (Analytics: the same asset and data; Models: the same simulation settings);
- Blocks: a block's picture (`BlockSpec.image`, checked by `plantcraft_sdk.images`, served
  under the path `describe_block` gives, tagged with its content) shows in the diagram's node and
  the palette; a block's Overview draws it with `BlockDrawing` (inputs left, outputs right) and
  its form or page chooses the picture with `BlockImageField`. The app keeps the picture with
  the block's version (Analytics: the block file; Models: the class's `Icon` annotation);
- `HelpBrowser`: the app's help as folders (the guide's `category`, `A/B` nests) with a filter;
  no introduction text;
- `DataTable` for every list that can grow past a screen: pages of 25/50/100, a click on a header sorts
  (`sort`), a search box (`searchText`) and, per column, `filter` (the suite's `MultiSelect`;
  `true`: the values found, each with its count; `{options}`: a fixed list such as every status; `value`: what a row is
  filtered by), "Clear filters" and "N of M"; `selectable` adds a checkbox per row;
- `CopyPrompt` ("Copy as prompt", `docs/design/copy-prompt.md`) on every object an AI assistant
  can read, explain or rebuild (a method, a model, an import format): the app serves
  `GET /api/prompts/<kind>/<id>` built with `plantcraft_sdk.prompts` and the button copies its
  text; preset questions only, never a free question from the URL;
- `BlockEditor` (`@plantcraft/ui/blockEditor`, its styles in `blockEditor.css`): the one block
  diagram editor of the suite, Simulink-like, on a page of its own. It takes
  the app's block catalog (`plantcraft_sdk.blocks.describe_block`), the diagram (version 2) and
  the app's check and test trace, and gives back the edited diagram; an app never draws its own
  diagram editor. It needs `@xyflow/react` 12 in the app's `frontend/package.json`, and the page
  imports `@xyflow/react/dist/style.css` before `@plantcraft/ui/blockEditor.css`;
- `PageTabs` for pages that belong together, the brand marks (`AppMark`, `AppLockup`) and the
  theme helpers (`initTheme()` before the first render; the choice is one browser setting shared
  by every app).
- `base.css`: everything a page is made of (headings, section titles, breadcrumbs, buttons,
  panels and cards, KPI cards, pills, notices, toolbars, tables, forms, dialogs) and **the page
  grid**: `.pc-grid` puts cards 4 to a row on every page of every app (2 below 760 px of content
  width, 1 on a phone); `.pc-grid-2` is two panels side by side (a lone panel takes the row);
  `.pc-span-2`, `.pc-span-3` and `.pc-span-all` widen a card; `.kpi-split` shows counts by
  status inside one card. A page never sets another column count. The app's `styles.css` imports
  `base.css` and keeps only what is the app's own;
- the **guided tour** (`GuidedTour`, `TourStep`, `tourClosing()`): `SuiteShell`'s `tour` prop
  takes the app's steps (`{path?, target?, title, body}`: a step opens a page of the app and
  points at something on it). It opens the first time a person opens the app (stored per app in
  the browser, `plantcraft-ui:tour:<app>`), again from "Take the tour" in the user menu or
  `startTour()`; `plantcraft-ui:tours-off` = `1` switches the first-visit opening off (browser
  tests set it). PlantCraft's tour walks the platform and ends on the Apps; each app's tour
  starts with a welcome that does not move the person, walks the app's pages and ends with
  `tourClosing()`;
- the **Overview** (`AppOverview`): every app's first page, named "Overview" in the menu and
  drawn like Desk's Today, on the same board (`WidgetBoard`): the title and the app's main
  actions at the right, its notices, then the widgets each person arranges (Customize: add,
  move, pick a size, set up, remove, restore the default), kept per person and per app in
  PlantCraft (`/api/home/layout?page=<app id>`). Desk's Today offers the widgets of every
  installed app; an app's Overview offers only its own. The widgets are the
  ones the app declares in `[[contributes.widgets]]` and serves with `plantcraft_sdk.widgets`
  ([widgets.md](widgets.md)), so a widget is written once and reads the same on both pages; a
  page draws one itself (`render`) only when it needs the browser (the queue's chart). The app
  names a new person's board (`defaultLayout`, placements with sizes) so it looks finished on
  the first visit. What the app works on (dashboards, alarms, projects) is its own page after
  Overview, never the Overview itself;
- the **routine** (`JourneyPath`, up to four numbered steps on a first page): it folds to one
  line ("Hide"), the choice is kept in the browser per page (`pc-journey:<path>`), and a routine
  whose steps are all done starts folded, since the tour already covers the first visit. An app never draws its own routine panel;
- the **start** (scale review A2, ui 0.54.0): `main.tsx` is `startApp(App, { t, statusTones })`
  (the theme before the first paint, the app's `t` and status ids for the shared components)
  and `App` calls `useSuiteSession(UNAUTHORIZED_EVENT)` (the token renewed, sign-in again on a
  second 401). An app keeps no `session.ts` or `brandTheme.ts` of its own: it imports them from
  `@plantcraft/ui`;
- shared helpers, never copied into an app: `createNav(BASE_URL)` (links and client navigation
  under the app's base path), the session (`renewToken`, `signInAgain`, `signOut`), the number
  and date formats (`formatNumber`, `formatDate`, `formatAgo`, `formatShare`,
  `formatDuration`; `configureUi({t, locale})` sets the language), the building blocks
  (`Heading`, `FormSection`, `FormFooter`, `Pill`, `Loading`, `ErrorBox`, `Health`) and the colours for charts
  (`brandTheme`, `STATUS_TONES`, `addStatusTones` for an app's own status ids);
- the **signal picker** (scale review A5, plantcraft-sdk 0.45.0): the ui's `SignalSearch`
  asks the app's own `GET <prefix>api/signals?q=` (the app reads PlantCraft with the person's
  token), and the app answers with `plantcraft_sdk.server.picker.signal_choices`: plant
  signals before derived series, then exact, prefix and other matches, so every app lists the
  same signals in the same order. An app ranks no signals of its own;
- the **search**: an entry at the top of the sidebar and
  Ctrl+K (Cmd+K on a Mac) on any screen open one box that asks every app the person may open at
  once, `GET <prefix>api/search?q=<text>&limit=6`, and lists the answers by app (arrows, Enter,
  Esc; Ctrl+Enter opens in a new tab). The answer is
  `{"format": "plantcraft-search/1", "items": [{"title", "detail", "type", "href"}]}`: `title`
  what the person looks for (a point's tag, a dashboard's name), `detail` one more line, `type`
  the kind of object in the person's language ("Point", "Dashboard", "Block"), `href` a path
  inside the app. Each app answers for its own objects only (PlantCraft: assets, people, groups,
  actions; Historian: points; View: dashboards and trends; Analytics: blocks, algorithms and loops;
  Alarms: alarms; Models: projects and models), with the person's access, in under a second,
  and never with an error: an app that does not search adds nothing. Texts of fewer than two
  letters ask nobody. An app writes its route with `plantcraft_sdk.server.search` (SDK
  0.21.0: `search_text`, `matches`, `SearchItem`, `search_answer` ranks and cuts the answer);
  `suite_api` answers `GET /api/search` and `GET /api/queue` with "nothing" for an app that
  passes no route of its own, so the frame's probes never end in a 404;
- **charts**:
  `@plantcraft/ui/plot` holds the suite's one Plotly build (`Plot`, the cartesian bundle, so an
  app never keeps its own `Plot.tsx`) and `TimeChart`, the time chart every trend uses: the
  user's theme (or a fixed light or dark one, the PNG included), a y axis titled only with a unit
  every line shares, quality bands (`qualityBands`) behind the lines and a toolbar slot. Its
  period is `PeriodPicker` ("Last 2 hours" … or "From – to"; `periodRange` gives what to load).
  An app installs `react-plotly.js` and `plotly.js-cartesian-dist-min` only when it draws charts.

- **the page's top**: the title at the
  left and the page's buttons at the right, in a band of one height, so the buttons sit at the same
  place on every page. Nothing above the title (no eyebrow, no breadcrumb) and nothing under it (no
  line of purpose): the sidebar already says where the person is, and what a page is for belongs in
  its Help and in its empty states. `Heading` draws only `title` and `actions` (`eyebrow` and `detail`
  are still accepted and not drawn); `AppOverview` likewise. A line that must stay under a title (a
  date, an object's status) carries the class `pc-heading-keep`.
- **time zones**: every field that asks
  for a time zone is `TimeZoneSelect`. The person's default comes first ("Local time · Sao Paulo
  (UTC−3)", or UTC), then the other, then the fixed offsets UTC−1 … UTC+14, and the cities last,
  folded. It saves `local` for the installation's zone (Settings › Installation); the app resolves it
  where it runs (`plantcraft_sdk.utc.resolve_zone(name, client.installation_time_zone())`), so a
  schedule follows the installation when its zone changes. Times on screen come from `formatDate`,
  `wallClock` and `Plot`, which follow the person's choice; `timeZoneLabel` names a saved zone.
- **buttons and forms**: a page's actions sit at the right of its title, in `Heading`'s `actions`
  (class `heading-actions`, 8 px apart, wrapping on a phone). Any number of them: at most one
  `button-primary` (blue, the page's main action), the others `button-secondary` (grey);
  `button-danger` (red) only for what deletes or takes back; `button-ghost` for small actions
  inside a row or a card. Every button is 36 px high (`button-small` 30 px), its icon 16 px.
  Refresh is an icon-only button (`button-icon`, `RefreshCw`, title and aria-label "Refresh").
  A settings page is one `panel form-panel`; each group of fields is a `FormSection` (title and
  explanation at the left, the fields at the right; one column below 820 px), the fields in a
  `form-grid` (two columns, `field-span` for a full-width field, `check` for a checkbox line), and
  the page's Save in a `FormFooter` (`sticky` on a long form). Dialogs keep `form-grid` and their
  footer. An app never sets its own button heights, gaps or form columns.
- **dialogs** (scale review A1, ui 0.53.0): every window over the page is the ui's `Dialog`
  (`title`, `onClose`, `footer`, `wide`; `onSubmit` makes it a form). It is named by its title,
  takes the focus and keeps Tab inside, gives it back on close, and closes on Escape, the × or a
  click outside until a field is changed. Asking before an action is `await confirmAction(text,
  { confirm: t("Delete"), danger: true })`, never the browser's `window.confirm`, which ignores
  the theme and the frame. Asking for one short text is `await askText(question, { value,
  confirm: t("Copy") })` (`type: "number"` for a number above zero), resolving the trimmed text or
  null, never `window.prompt`. A message after an action is `showToast(text, { tone: "error" })`
  (`"ok"`, `"info"`): it closes on its own, with its × or Escape, and never blocks the page as
  `window.alert` does. An app draws no `dialog-backdrop` of its own.

Rules: no app draws its own top menu or user menu; page order follows D7; the app's own pages
are the only entries above **Apps**. An app that needs something the frame lacks asks for it in a
PlantCraft PR (a new package version), never a local copy: what two apps draw the same way
belongs in the package.

## 11. Analytics

Analytics is the analysis app of the suite (D9). It works on **signals** (data
quality) and **loops** (control performance). Its analyses are `@method`s; a **protocol** wires
methods as blocks (inputs: signals, assets and asset roles; methods; combinations such as
worst-of; outputs: results, derived series in Historian, messages) and runs on a **schedule**;
each execution is a **run**. Pages: Overview (now and the week, with a link to the app's
dashboard in View), Signals, Loops, Runs, Protocols, Methods, Help.

DashCraft (formerly TrendCraft) stays separate: dashboards are only a view of the data in
Historian and of the apps' results, so any app's Overview links to a View dashboard instead
of drawing its own.
