# AGENTS.md: PlantCraft <Name>

**Read the suite's rules first**: the repository's root `AGENTS.md` (`../../AGENTS.md`), the single
source of rules for the platform and every app. This file adds only
what is particular to PlantCraft <Name>; where the two differ, ask the owner which one wins and
fix the other.

This folder is **PlantCraft <Name>** (`<id>`, prefix `/<prefix>/`, port <port>, uid <uid>):
<app.toml summary>

## Start here

1. `git status`, `git log origin/main..HEAD`, open PRs; then `docs/STATUS.md`, `docs/gaps.md`,
   `ROADMAP.md` and `SPEC.md` of this repository.
2. `make test-fast` while working, `make ci` before every push, `make e2e` when you touched a user
   journey (the same commands in every folder: PlantCraft `docs/claude-code.md`).
3. Commit messages start with `<id>: `; append a line to `docs/devlog.md` before you finish.

## Map and layers

This repository:

```text
app.toml        the manifest: id, version, prefix, port, uid, permissions (single source; tested)
src/<id>/       the module (layers below); tests/ (pytest, against FakePlantCraft); tests/oracles/
docs/help/      help pages served at /api/help and shown under Help
frontend/       Vite + React + TypeScript on @plantcraft/ui, served under /<prefix>/
vendor/         the plantcraft-sdk wheel and the @plantcraft/ui package this module pins
deploy/         requirements.in/.lock: hashed dependencies of the image (`make lock`)
```

| Layer | Packages (`src/<id>/`) | Role |
|---|---|---|
| -1 | `i18n` | `t()`; anything may use it |
| 0 | `config`, `meta` | settings from the environment, `app.toml` and help pages (the store is `plantcraft_sdk.server.store`) |
| 1 | `<objects>` | the module's own objects: contract and store |
| 2 | `engine` | what the module computes |
| 3 | `api`, `cli` | FastAPI app (`plantcraft_sdk.server.web`), command line |

- What the module owns, in one line each (its objects, who reads plant data and with which
  token, what is audited).

The layer table is enforced by `tests/test_suite_rules.py` (`plantcraft_sdk.apptest`).

## This module's own rules

- **Bad data never crashes**: what this module shows when data is bad.
- **No silent wrong answers**: what this module says when it cannot judge.
- **One path**: the one function every screen and job goes through.
- **Clean room** (suite rule): the tools studied for this module, for public behaviour only.
- Performance: the number that must not regress, and how it is measured.

## Oracles and floors

The public data with known answers this module is checked against (`tests/oracles/`), and the
`[oracles]` floor in `tests/floors.toml`.
