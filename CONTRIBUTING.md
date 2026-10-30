# Contributing to PlantCraft

Thank you for helping. PlantCraft is built by and for process engineers;
bug reports, new methods, translations and documentation are all welcome. Everything is open
under the [Apache License 2.0](LICENSE), and so is every contribution.

## Ways to help

| You want to | Do this |
|---|---|
| Report something that does not work | Open an issue with the **Bug** form: what you did, what you expected, what happened, the version |
| Suggest a feature or a method | Open an issue with the **Idea** form; say which app it belongs to and, for a method, its public reference |
| Report a vulnerability | Never in a public issue: report it privately ([SECURITY.md](SECURITY.md)) |
| Fix a bug, add a method, improve a page | A pull request, as below |
| Translate | Brazilian Portuguese entries for the English texts ([Translations](#translations-i18n)) |
| Build an app for a specific use | In your own repository, open or closed, from the app template ([templates/app](templates/app/README.md)); it builds on the published SDK and does not need a pull request here |

## What is core and what is open

PlantCraft is a platform that others build on, so its base changes slowly and on purpose, and
everything on top of it is open to grow. Before you start, find where your change lands
([the picture](docs/architecture.md#core-and-extensions)):

| Zone | Folders | Open an issue first? | What a pull request needs |
|---|---|---|---|
| **Core** | `plantcraft/`, `frontend/`, `sdk/python/`, `ui/`, `docs/api/v1/`, `deploy/`, `.github/`, `ci/`, `dev/`, `AGENTS.md` | **Yes**, and wait for a maintainer to agree on the approach | An additive change (nothing that existing apps or installations rely on breaks), with its tests; the owner reviews it ([CODEOWNERS](.github/CODEOWNERS)) |
| **Official apps** | `apps/<app>/`, `simulator/`, `templates/app/` | For a new feature or a new dependency, yes; for a bug fix, no | Stays inside one app, `make ci` green in that app's folder, no import from another app or from the platform's code |
| **Content** | Methods, blocks, algorithms, alarm rule templates, model libraries and notebook examples inside the app that owns them; `docs/`; translations | No | A public reference for every method, tests on known answers, the description format checks green |
| **Your own app** | Your own repository, from [`templates/app`](templates/app/README.md) | No | Nothing here: it builds on the published SDK and installs as a signed package |

A pull request that changes the core without an agreed issue is closed with a pointer to open
one: it is not a judgement on the code, it keeps the base that every app relies on stable. Keep
each pull request to **one zone and one change**; a core change and an app change go in two pull
requests, the core first.

Pull requests written with an AI assistant are welcome: this repository is built that way. The
same rules apply, and you should be able to explain every line.

## Your first pull request

1. Fork the repository and make a branch from `main`.
2. Set it up ([Development setup](#development-setup)) and make your change, with its tests and
   its documentation.
3. **Run `make ci` before every push**, in each part you touched: the root for the platform,
   `apps/<app>` for an app, `simulator/`, `sdk/python` or `site/`. Each part has its own
   `make ci`; it runs what CI runs.
4. Open the pull request against `main`: one change, and why it is needed. CI runs the lint and
   security checks on it; the full tests run on `main`.
5. A maintainer reviews it, usually within a few days. Paths listed in
   [.github/CODEOWNERS](.github/CODEOWNERS) wait for the owner's review
   ([Pull requests](#pull-requests)). What a reviewer checks is in
   [docs/maintainers.md](docs/maintainers.md).

## Development setup

Requirements: Python 3.12 or 3.13, Node.js 22 and npm.

```bash
git clone https://github.com/PlantCraft/PlantCraft.git plantcraft
cd plantcraft
python3 -m venv .venv && . .venv/bin/activate
python -m pip install -e ".[server,opcua,dev]"
(cd frontend && npm ci)
```

Run the demo (the Simulator's OPC UA server, API and interface; install the Simulator first with
`pip install -e simulator`):

```bash
python run_opcua_demo.py --browser
```

For interface work, `npm run dev` in `frontend/` starts Vite with hot reload.

## Checks

Run the same checks as CI before opening a pull request:

```bash
ruff check . && pytest -q
cd frontend && npm run lint && npm test && npm run build
```

`make ci` runs them all. It installs `plantcraft-sdk` from `sdk/python` first, into the active
virtual environment only: it does nothing when that Python already imports this tree's SDK, and
it stops with a message when no virtual environment is active (CI, which sets `CI`, is allowed).

Browser journeys live in `tests/e2e` and need Playwright:

```bash
python -m pip install -e ".[e2e]"
python -m playwright install chromium
pytest -q tests/e2e
```

## Add a method

Methods are the analyses of the suite: a loop's oscillation, a valve's stiction, a frozen signal.
They belong to the app that owns them, never to PlantCraft itself, which has no methods. Most
live in PlantCraft Analytics, under `apps/link/src/linkcraft/methods/` (`signal/` for signals,
`cpm/` for control loops).

1. **Start from public literature.** Every method comes from a published, public source, listed
   in `methods/references.py` and in the method's description. No proprietary or confidential
   method, data or plant material.
2. **Write it as a `@method`** (`plantcraft_sdk.methods`): an id, a label, its inputs by signal
   role, parameters with labels and units, `run`, and `describe(metrics)`, the one place its
   finding is worded (in English, with its pt-BR translation). A short example is
   `signal/frozen.py`.
3. **Test it** in the app's `tests/`: on synthetic signals with a known answer, on hostile inputs
   (gaps, constant values, text) and, where public data exists, on the oracles in
   `tests/oracles/` (for example the International Stiction Database). The
   app's catalog checks hold every method to the same description format.
4. **Run `make ci` in `apps/link`** and open the pull request.

A method can also be built without code, as an algorithm of blocks in the Analytics editor, and
kept in your installation; a pull request makes it part of the suite for everyone. The block
format is in [docs/blocks.md](docs/blocks.md).

## Rules of the codebase

- **Layers.** Modules only import downward; see the table in `README.md` and
  [docs/architecture.md](docs/architecture.md). `tests/test_architecture.py`
  fails on any violation.
- **Storage.** Each module owns its tables through a `Store` subclass
  (`plantcraft/db.py`). Add columns with a guarded `ALTER TABLE` in the
  store's `__init__`; never edit existing rows by hand.
- **Apps of the suite** live in `apps/<app>` (each its own image, package and `make ci`) and reach
  PlantCraft only through API v1 (`docs/api-v1.md`); PlantCraft never imports them, and
  analysis code (methods, scores, diagnoses) belongs to them, not here.
- **One version of each contract.** No versioned copies (`_v2`), digests,
  manifests or generated evidence files.
- **API v1 changes** are additive and land with `docs/api-v1.md`, the
  contract tests (`tests/contract`) and `FakePlantCraft` (`sdk/python`) in
  the same change.
- **No plant-specific material.** Do not commit real plant data, tag lists,
  hostnames, credentials or screenshots of proprietary tools.

## Translations (i18n)

English is the source language of every user-facing string; Brazilian
Portuguese (pt-BR) is a translation. **Every new or changed string needs its
English text and its pt-BR entry in the same change.**

- Backend: `from plantcraft.i18n import t` and
  `t("Loop {loop} not found.", loop=loop_id)`. The English text is the key in
  `plantcraft/i18n/locales/pt-BR.json`. Call `t()` when the text is produced,
  not at import time.
- Frontend: `import { t, locale } from "./i18n"` and `t("Save")`, with keys in
  `frontend/src/locales/pt-BR.json`. Use `locale` for `Intl` and
  `localeCompare`.
- Each method's `describe(metrics)` is the one place its finding is worded.
- User guides live in `docs/en/` with their translation in `docs/pt-BR/`.

`tests/test_i18n.py` checks that the catalogs are complete. Write plain, short
product English in sentence case ("Add source", not "Add Source").

## Pull requests

- Keep each pull request focused on one change and describe why it is needed.
- Include tests for behaviour changes and update the documentation in `docs/`.
- A change to a path in [.github/CODEOWNERS](.github/CODEOWNERS) (sign-in, permissions, the
  assistant, the stores, the sandbox, the installer, CI, dependencies) waits for the owner's
  review; dependency bumps come alone, and binary files from outside are not accepted
  ([docs/contributing-safety.md](docs/contributing-safety.md)).
- By contributing, you agree that your contribution is licensed under the
  [Apache License 2.0](LICENSE).

## Security

Do not open public issues for vulnerabilities; see [SECURITY.md](SECURITY.md).
