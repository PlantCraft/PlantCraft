# AGENTS.md: PlantCraft View

**Read the suite's rules first**: the repository's root `AGENTS.md` (`../../AGENTS.md`), the single
source of rules for the platform and every app. This file adds only
what is particular to PlantCraft View; where the two differ, ask the owner which one wins and fix the other.

This folder is **PlantCraft View** (`dashcraft`, prefix `/dash/`, port 8080, uid 10006):
Dashboards, trends and reports over the plant's signals and assets.

## Start here

1. `git status`, `git log origin/main..HEAD`, open PRs; then `docs/STATUS.md`, `docs/gaps.md`,
   `ROADMAP.md` and `SPEC.md` of this folder.
2. `make test-fast` while working, `make ci` before every push, `make e2e` when you touched a user
   journey (the same commands in every folder: PlantCraft `docs/claude-code.md`).
3. Commit messages start with `dashcraft: `; append a line to `docs/devlog.md` before you finish.

## Map and layers

This folder:

```text
app.toml        the manifest: id, version, prefix, port, uid, permissions (single source; tested)
src/dashcraft/ the app (layers below); tests/ (pytest, against FakePlantCraft); tests/oracles/
docs/help/      help pages served at /api/help and shown under Help
frontend/       Vite + React + TypeScript, served under /dash/ (base path in vite.config.ts)
vendor/         the plantcraft-sdk wheel and the @plantcraft/ui package PlantCraft View pins (never
                edited here; SHA-256 of both in its README)
deploy/         requirements.in/.lock: hashed dependencies of the Docker image (`make lock`)
```

| Layer | Packages (`src/dashcraft/`) | Role |
|---|---|---|
| -1 | `i18n` | `t()`; anything may use it |
| 0 | `config`, `meta` | settings from the environment, `app.toml` and help pages (the store is `plantcraft_sdk.server.store`) |
| 1 | `dashboards` | the card contract (`model`), saved dashboards and public links (`store`), starters |
| 2 | `query` | card data from API v1: assets and roles resolved, values, trends, the shared cache |
| 3 | `api`, `cli` | FastAPI app under `/dash`, command line |

- **A card names signals, never copies them.** A card item is a PlantCraft signal id, or an
  asset and a signal role (`asset_id` + `role`), or the dashboard's asset (`$context`) and a
  role. It is resolved through API v1 at every read, so remapping a signal in PlantCraft moves
  every card that uses it. PlantCraft View keeps no asset, signal or sample of its own.
- **Who reads plant data.** Saved dashboards and public links read with PlantCraft View's service
  token (published-report model: whoever may open the dashboard sees what its editors put on it);
  one read per card serves every viewer for `DASHCRAFT_CACHE_SECONDS`. Editors building cards
  (pickers, previews) read with their own token, so PlantCraft's permissions decide what they
  can pick. A viewer may only choose a dashboard asset of the dashboard's `context_kind`.
- **Every change a person makes** (dashboards, cards, public links) is recorded with
  `POST /api/v1/audit` (`Runtime.audit`).

The layer table is enforced by `tests/test_suite_rules.py` (`plantcraft_sdk.apptest`).

## This module's own rules

- **Language**: user-facing text is English only for now: every string goes through `t()` (`src/dashcraft/i18n.py`, `frontend/src/i18n.ts`) so a Portuguese catalog can be added later (parked in `docs/gaps.md`).
- **Bad data never crashes.** NaN, gaps, constant signals, empty windows, wrong units, a dead
  source, a malformed CSV or plant map: every card shows the problem on the item it concerns, in
  words a person can act on, and the rest of the card still draws; never an exception or a 500. Unfinished features return "not
  supported" and are hidden in the UI.
- **No silent wrong answers.** A value from another window than the one asked (a recorded file,
  a stopped source) says so on the card. People act on these screens in a running plant.
- **Every card kind** (KPI, trend, bars, table) is one branch of `query/cards.py` and one
   drawing in `frontend/src/CardView.tsx`; the editor, the grid, previews and public links all
   draw through them.
- Tests talk to `plantcraft_sdk.testing.FakePlantCraft`, never to a real PlantCraft; the
  test plant (loops, a pump, a text signal, every kind of user) is in `tests/plant.py`.
- Performance is a feature: a dashboard of 30 cards open on 20 screens costs PlantCraft one
  read per card per cache period (`tests/test_query.py` counts the requests).

## Oracles and floors

PlantCraft View's oracle: what a card shows equals what pandas computes from the same samples
(`tests/oracles/test_pandas_oracle.py`, a recorded file with gaps, irregular sampling and a spike).
Its pass count is the `[oracles]` floor in `tests/floors.toml`.
