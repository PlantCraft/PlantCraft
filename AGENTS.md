# AGENTS.md: rules for AI agents and contributors

PlantCraft is an open platform for process engineers: one central app and a family of modules
that bring together what the tools of a category offer across vendors. This one repository holds
them all: the platform at the root, every official app in `apps/<app>`, the Simulator in
`simulator/`. Each app keeps its own image, package, version and `make ci`; an installation
still picks which apps it runs. An external app lives in its publisher's own repository and
builds on the published SDK and ui. **This file is the suite's single source of rules**: every module's own
`AGENTS.md` is short, points here, and adds only what is particular to that module (section 10).

Names: only the platform carries the Craft brand. A module is
**PlantCraft <name>** in documents (PlantCraft Analytics, Historian, View, Alarms, Models,
Documents, Simulator; the names people see are in [docs/glossary.md](docs/glossary.md)) and just
**<name>** inside the suite. The platform was called ProcessCraft until 0.5.0: the SDK is `plantcraft-sdk` (`plantcraft_sdk`), the ui
`@plantcraft/ui`, the settings `PLANTCRAFT_*` (the old names are still read). App ids, images and
prefixes keep their lowercase `<function>craft` form for good, the Simulator is `simcraft`, and
each app's folder is its short name (`apps/link`). Code and identifiers are in English; user-facing text is written
in English and translated to Brazilian Portuguese (section 3, "One language source").

The suite is built with AI coding agents (Claude Code), in the open: see
[docs/how-we-build.md](docs/how-we-build.md). That is why these rules are strict and checked by
code. Read this file first, then `docs/STATUS.md`; the map of the suite is
[docs/suite.md](docs/suite.md), the commands and prompts are [docs/claude-code.md](docs/claude-code.md).

## 1. Start every session here (5 minutes)

1. `git status`, `git log origin/main..HEAD`, open PRs: finish or park unmerged work before starting new work.
2. Read `docs/STATUS.md`: current focus, next task, blockers, last devlog entries.
3. Read `ROADMAP.md` (readiness per product) and `docs/gaps.md` (ranked work list). Pick work from there.
4. Read the `SPEC.md` and `ROADMAP.md` of the product you touch (section 2).
5. Work autonomously. Stop and ask only for **maintainer decisions** (section 9).

## 2. Map and layers

```text
plantcraft/
  db config i18n refs                       layer 0: storage, settings, languages, references
  industrial_data auth assets events audit  layer 1: data sources, people and tokens, assets, events, audit
  results                                   layer 1: results, runs and schedules the apps publish (API v1)
  platform                                  layer 2: workspace, source registry, loops as assets, plant map
  api/ cli.py                               layer 3: the entry points (HTTP and command line)
sdk/python/                                 plantcraft-sdk: what the apps import (API v1 client, tokens, @method)
frontend/                                   PlantCraft's web app: sign-in, launcher, sources, assets, people
ui/                                         @plantcraft/ui: the shared interface every app draws
apps/link apps/historian apps/view          the official apps, one folder each (own image, package,
apps/alarms apps/models apps/documents      version, make ci, workflow in .github/workflows/<app>.yml)
simulator/                                  PlantCraft Simulator, the OPC UA plant (own version and image)
templates/app/                              StarterCraft, the app template (its own repository at release)
deploy/ ci/ dev/                            the suite's installer and bundle, CI, dev tools
```

PlantCraft is the central app only (2026-10-19). Each module is its own app, in its own folder
and container, and talks to PlantCraft through API v1 (`docs/api-v1.md`); a module never imports
another module's code, only the SDK. The full table (folders, ids, prefixes, ports, versions) is [docs/suite.md](docs/suite.md): Analytics (`linkcraft`, folder
`apps/link`), Historian (`histcraft`), View (`dashcraft`), Alarms (`alarmcraft`), Models (`modelcraft`),
Documents (`doccraft`) and the Simulator (`simcraft`, the simulated plant). The retired ids
`cpmcraft`, `datacraft` and `twincraft` merged into Analytics and `trendcraft` is View; they stay
reserved.

Each module's folder holds its `SPEC.md` and `ROADMAP.md` (template:
`docs/product-template-SPEC.md`); PlantCraft's are at the root of this repository.

**Every app follows `docs/app-standard.md`**: the same
`app.toml`, folder layout, image, settings and references (`asset:<id>`,
`signal:<source>:<tag>`, `run:<app>/<id>`). Apps link only through what they publish in
PlantCraft, **results** and **events** (API v1), and report their runs and schedules there;
they never call each other. Ids, prefixes, ports and container users are assigned once, in its
suite table (section 7); `tests/test_suite_table.py` holds `deploy/compose.yaml` to it, and
`plantcraft-app check` (in the SDK) holds each app folder to it.

- **Layering is enforced**: here by `tests/test_architecture.py`, in every module by
  `tests/test_suite_rules.py` (`plantcraft_sdk.apptest`). A module imports only from lower
  layers; a new one must be registered in the layer table. The layer table is in `docs/architecture.md`. Its `MOVED`
  table lists the packages that left for the products; they never come back here.
- **Written once.** Anything two modules repeat moves into the platform: the server skeleton,
  store, access checks, test kit and SBOM into `plantcraft-sdk` (`plantcraft_sdk.server`,
  `apptest`, `testplant`, `e2e`), the frame, help, API client and pickers into `@plantcraft/ui`.
  A module keeps only its own objects, methods and workflow.
- **Products never import each other, and PlantCraft never imports a product.** They talk through
  API v1 only: assets, signals, series, tokens and the audit log.
- **Core contracts are public API.** Changing one (a field, an endpoint, an event shape) needs a
  contract test update and a line in `docs/STATUS.md`. Never add a `_v2` copy: change it in place
  and migrate callers in the same PR.

## 3. Golden rules

### Never break the plant, never break the user (outranks feature work)

- **Read-only on plant systems.** No product writes to a DCS, PLC, PI or OPC UA server. The only
  write path is to the simulator (the Simulator); model-based control runs against simulation only.
  Any new write path is a maintainer decision.
- **Bad data never crashes.** NaN, gaps, constant signals, empty windows, wrong units, a dead
  source, a malformed CSV or plant map: every method returns a result marked insufficient or
  not usable with a reason a person can act on, never an exception or a 500. Unfinished features
  return "not supported" and are hidden in the UI.
- **Prove it.** Every crash fix lands with a small synthetic regression test that failed before.
  `tests/test_hostile_inputs.py` here, and `tests/test_suite_rules.py` in each module, run every
  API route with junk inputs and must stay green (modules with methods run them with junk too).
- **No silent wrong answers.** A method that cannot judge says so. Better "inconclusive" than a
  confident wrong diagnosis: people act on our findings in a running plant.

### Secure and offline by default

Our clients are industrial plants: nothing gets installed unless IT and OT security approve it.
`docs/security-guide.md` is the two-page guide handed to them with each release.

- **No outbound network by default.** No CDN, web fonts, telemetry, update checks or analytics.
  Fonts and scripts are bundled. The only outbound connections are the data sources the admin
  configures (PI, OPC UA) and, only if switched on, an LLM endpoint the client approves.
  `tests/test_offline.py` (here) and `tests/test_suite_rules.py` (modules) fail on any
  `http(s)://` resource fetched at runtime that is not configured.
- **Install offline in minutes, without admin rights.** Every release ships a Windows installer,
  a Docker image `.tar`, and a wheelhouse with every dependency and the built UI. Runs as a normal
  user, in one folder, on a port above 1024.
- **Never lose data on upgrade.** All state lives in one data folder. Upgrades back it up first;
  `./install.sh --rollback` returns to the previous version. Schema migrations are additive.
- **Secure defaults.** Sign-in on by default outside `127.0.0.1`; roles enforced on every route
  (test per route); HTTPS with the client's certificate; audit log of who changed what.
  Secrets come from environment variables or a vault, never stored in plain text or logged.
- **Supply chain.** Pinned dependencies, SBOM (CycloneDX) and SHA-256 hashes per release,
  vulnerability scan (pip-audit, npm audit) in CI. A new dependency needs a reason in the PR.
- **No client or employer specifics in the code**: no internal hostnames, tags, plant names or
  credentials, even as defaults or examples.

### Everything is registered once

1. **Every analysis is a `@method`** (`plantcraft_sdk.methods`, in the product that owns it):
   id, label, inputs by signal role, parameters with labels, `run`, `describe(metrics)`, tests.
   `describe(metrics)` is the one place a finding is worded. PlantCraft itself has no methods.
2. **Every user action is an API endpoint** with a test; the UI calls only the API. Specialists
   (LLM) act only through the same API and permissions as people.
3. **Each table is owned by one module** (a `Store` subclass in `plantcraft/db.py` with its
   `SCHEMA`). A change to a table a release shipped is a named step in the store's `MIGRATIONS`
   (`Migration`, `add_columns`): run once per database and recorded, never renamed or removed.
   At each release add its schema to `tests/schemas/` (`dev/schema-snapshot/dump.py`) and its
   API v1 to `docs/api/v1/releases/` (`python -m plantcraft.api.contract release <version>`),
   and replace `tests/contract/previous-sdk/` with that release's SDK wheel;
   never edit existing rows by hand.
4. **Apps of the suite are listed once**, in `PLANTCRAFT_APPS` (`plantcraft/auth/suite.py`):
   the launcher, people's access and API v1's `/apps` all read that list.

### One language source

- English is the source of every user-facing string; Brazilian Portuguese (pt-BR) is a translation.
- Backend: `from plantcraft.i18n import t` and `t("Loop {loop} not found.", loop=loop_id)`, called
  when the text is produced (not at import). Keys live in `plantcraft/i18n/locales/pt-BR.json`.
- Frontend: `import { t, locale } from "./i18n"`, `t("Save")`; keys in
  `frontend/src/locales/pt-BR.json`. Use `locale` for `Intl` and `localeCompare`.
- Until the MVP ships the product is English only: wrap new strings
  in `t()`, but a pt-BR entry is optional. `tests/test_i18n.py` checks the entries that exist.
- Help pages live in `docs/en/` and `docs/pt-BR/` under the same file name.

### Clean room

- **This repository is public.** Every commit, branch name, pull request, review and comment is
  published the moment it is pushed. Only public information and methods go in; the words that
  must never be published (a maintainer's list, repository secret `BANNED_WORDS`, never committed)
  appear nowhere, not even in a commit message. The Security workflow checks the tree and the
  commit messages of every pull request; check yours against the list before pushing.
- We study paid tools (AVEVA PI, Seeq, TrendMiner, Control Station, Honeywell, ABB, Aspen,
  Emerson) for **public behaviour only**: brochures, public manuals, papers, standards, public
  videos. Never use their code, binaries, internal manuals, client screenshots, or anything
  received under NDA or an employer/client contract. Every source used goes in the product's
  `SPEC.md` with its link.
- Formats and protocols come from public specs: OPC UA, PI Web API public docs, FMI/FMU,
  Modelica, ISA-18.2, EEMUA 191, ISA-5.1.
- Never copy GPL/AGPL code into the core. Never use vendor logos, colours, icons or names in the
  product. Public text (site, README, release notes) describes the category and our features,
  never "a clone of" or "a free X"; vendor names appear only in the research tables of `SPEC.md`.
- Every third-party asset (image, icon, dataset, font, library) has a row in `ATTRIBUTION.md` in
  the same commit. Client or employer data never enters the repository, prompts or issues.

### Tests are the gate

- Every change comes with tests; a new feature has at least one test that fails without it.
- Each product keeps **oracle tests** against public data (section 5). Their pass counts, and the
  other measured numbers in `tests/floors.toml`, are floors that only rise: when you raise one,
  update the floor in the same commit; never lower it (`tests/test_floors.py`).
- UI changes: run the app, take a screenshot with Playwright, look at it. The e2e journeys in
  `tests/e2e` must stay green.
- Tests stay fast: one layout and a time budget in every app ([docs/testing.md](docs/testing.md));
  `make test-fast` is the loop while working, slow tests are marked `slow` on purpose.
- Performance is a feature: `make bench-suite` (2,000 loops, 8,000 signals) and Link's bench
  (`python -m linkcraft.bench`) must not regress more than 20%.

## 4. Before you finish a task

```sh
make test-fast   # the loop while working (no slow tier)
make ci          # everything CI runs: app standard, ruff, frontend build and tests, pytest
make e2e         # if you touched a user journey (Playwright, Chromium)
                 # the same commands in every app: make -C apps/<app> ci (docs/claude-code.md)
dev/ship         # make ci in every part (platform, apps/<app>, simulator) your change touches
```

Then:

- Update the product's `ROADMAP.md` row and `docs/gaps.md` entry if a number moved or a gap closed,
  with the date.
- Append a short entry to `docs/devlog.md` (what landed, numbers, what's still open). Sessions end
  abruptly; the devlog plus a green tree is how the next agent picks up.
- Keep the tree green at every commit. One task per commit, message starting with the product and
  task (`linkcraft: stiction index on short windows`, `core: ...`, `sdk: ...`, `docs: ...`).
- A commit an agent wrote carries its `Co-Authored-By` line; never hide how a change was made.

### Quick interface changes (the person is waiting to see them)

When the person asks for small interface changes (a color, a label, a spacing), show each one on
the project's test server in seconds with `dev/preview` and run the slow steps once for the whole batch
with `dev/ship` (`dev/README.md`). Every app follows the same loop with these tools.

## 5. Oracles (public test data)

Oracles will be fetched into `oracles/` (gitignored) at pinned versions with sha256. Never commit
them; a new oracle is a new pin. None is wired yet (gap G3); the targets are:

| Product | Oracle |
|---|---|
| Link | International Stiction Database (Jelali and Huang), simulator loops with known faults, synthetic signals with injected freezes, spikes, gaps and drifts |
| Historian | A PlantCraft Simulator dataset archived and read back, every value within its point's deviation |
| Plant | OPC UA conformance through a standard client (asyncua) |
| View | Aggregations and windows checked against pandas |
| Alarms | ISA-18.2 and EEMUA 191 KPIs on a public sample alarm log |
| Link (models) | Twin's floors on the Simulator's faults, FMUs built in CI with OpenModelica |
| Models | The Modelica Standard Library examples, simulated by OpenModelica |

## 6. Parallel work (many people and agents at once)

The full plan, with roles and the GitHub organisation, is
[docs/contributing-at-scale.md](docs/contributing-at-scale.md). In short:

- **One session owns one folder** (the platform, `sdk/python`, `ui/`, one `apps/<app>` or
  `simulator/`) unless its task spans several. Changes to `plantcraft-sdk`, `@plantcraft/ui`
  or API v1 are released as a new version, and the apps pick it up with `dev/revendor --all`,
  in the same PR or the next one. Never edit a vendored file by hand.
- **SDK and ui version numbers are taken at merge, by a script.** Parallel branches start from
  the same main and would bump to the same number. Right before merging a branch that changes
  `sdk/python` or `ui/`, run `dev/sdk-version`: it merges `origin/main` (vendored files and
  version-only conflicts are taken from main), gives each changed package main's next minor
  version, rebuilds, vendors it into every app, the template and `frontend/`, and commits. Then
  `dev/ship`, push, merge at once, with the new number in the PR title. `dev/ship` and the Lint
  check of every PR fail when a branch changes the SDK or ui without a version above main's.
- **One pull request may span folders** when the change is one: an SDK change and the apps that
  use it, a ui change and every app that draws it. Each folder's workflow runs its own checks.
- Inside this repository, shared files (`plantcraft/api/app.py`, the frontend router, the
  locale catalogs, `pyproject.toml`) get small, surgical edits; re-read before editing. Add new
  code in a **new module** instead of growing a shared file.
- **CI cadence.** A pull request runs only Lint and Security; run `make ci` of
  every folder you touched (`dev/ship`) before merging, that is the gate. The tests and e2e run on
  main about four times a day (ci/macmini/README.md); when one fails, the merge that broke it is
  fixed or reverted at once.
- **Never stack long PR chains.** Branch from `main`, keep PRs small, merge in order. When merging
  several branches: merge one, run `make ci`, fix, then the next. Two green branches can still
  break each other.
- If another session's in-progress change breaks the build, don't fix their files; tell its owner.
- Use your own ports and scratch folders; never delete shared paths.

## 7. Where things are tracked

- `docs/STATUS.md`: current focus, next task, blockers. Short; rewritten, not appended.
- `ROADMAP.md`: stage and readiness % per product, one table, with the date of the last review.
- `<product folder>/ROADMAP.md`: readiness per area of that product against its target tool.
- `<product folder>/SPEC.md`: the feature list of the target tool, from public sources, each row
  marked done, partial or missing.
- `docs/gaps.md`: every known shortfall, ranked by user impact. The work list.
- `docs/devlog.md`: terse log, newest last.

A done row that turns out wrong or incomplete is downgraded to partial with a note. Readiness
numbers are measured (tests, oracles) where possible and labelled "estimated" where not.

## 8. Releases

- Versions `0.x` while any product is alpha. A release (wheel, Docker image, later a Windows
  installer) is built from a green `main` only.
- A product appears in the default install only when it passes its oracles and its main journey
  end to end. Until then it is marked "preview".

## 9. Maintainer decisions (stop and ask)

Licensing, making the repository or anything else public, publishing a release or the site,
deploying the demo, new remotes, secrets and API keys, any write path to a plant system, deleting
data or branches, and changing these rules.

## 10. A module's own AGENTS.md

Every module's folder has a short `AGENTS.md` (template:
[docs/templates/module-AGENTS.md](docs/templates/module-AGENTS.md)) that says: read the suite's
rules first (this file, `../../AGENTS.md` from the module's folder); the module's
id, prefix and port; its layer table; its own rules (what it owns, what it must never do, its
oracles and floors); and its quick commands. It never repeats a suite rule: a rule two modules
need belongs here. Its `CLAUDE.md` is one line pointing to `AGENTS.md`.
