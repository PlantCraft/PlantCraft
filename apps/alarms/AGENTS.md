# AGENTS.md: PlantCraft Alarms

**Read the suite's rules first**: the repository's root `AGENTS.md` (`../../AGENTS.md`), the single
source of rules for the platform and every app. This file adds only
what is particular to PlantCraft Alarms; where the two differ, ask a maintainer which one wins and fix the other.

This folder is **PlantCraft Alarms** (`alarmcraft`, prefix `/alarm/`, port 8110, uid 10009):
Alarm limits on plant signals, the alarm summary and alarm performance against ISA-18.2.

## Start here

1. `git status`, `git log origin/main..HEAD`, open PRs; then `docs/STATUS.md`, `docs/gaps.md`,
   `ROADMAP.md` and `SPEC.md` of this folder.
2. `make test-fast` while working, `make ci` before every push, `make e2e` when you touched a user
   journey (the same commands in every folder: PlantCraft `docs/claude-code.md`).
3. Commit messages start with `alarmcraft: `; append a line to `docs/devlog.md` before you finish.

## Map and layers

This folder:

```text
app.toml        the manifest: id, version, prefix, port, uid, permissions (single source; tested)
src/alarmcraft/  the app (layers below); tests/ (pytest, against FakePlantCraft); tests/oracles/
docs/help/      help pages served at /api/help and shown under Help
frontend/       Vite + React + TypeScript, served under /alarm/ (base path in vite.config.ts)
vendor/         the plantcraft-sdk wheel and the @plantcraft/ui package PlantCraft Alarms pins (never
                edited here; SHA-256 of both in its README)
deploy/         requirements.in/.lock (+ overrides.txt): hashed dependencies of the image (`make lock`)
```

| Layer | Packages (`src/alarmcraft/`) | Role |
|---|---|---|
| -1 | `i18n` | `t()`; anything may use it |
| 0 | `config`, `meta` | settings from the environment, `app.toml` and help pages (the store is `plantcraft_sdk.server.store`) |
| 1 | `alarms` | the alarm contract (`AlarmDraft`), the store: alarms, occurrences, journal |
| 2 | `engine` | `evaluate` (limits, deadband, delays, no data; replay on history) and `performance` |
| 3 | `monitor` | the background cycle and what it publishes to PlantCraft |
| 4 | `api`, `cli` | FastAPI app under `/alarm`, command line |

- **An alarm names its signal, never copies it.** A signal id, or an asset and a signal role
  (`asset_id` + `role`), resolved through API v1 every cycle, so remapping a signal in
  PlantCraft moves every alarm that uses it. Alarms keeps no asset, signal or plant sample of
  its own.
- **Who reads plant data.** The monitor and alarm pages read with Alarms' service token (an
  alarm is a published judgement); editors' pickers, "Try it" and suggested limits read with
  their own token.
- **The monitor owns `state_json`; people own acknowledgement and shelving** (their own
  columns). Never let one side overwrite the other's columns.
- **Every change a person makes** (alarms created, changed, deleted, shelved, taken out of
  service) is recorded with
  `POST /api/v1/audit` (`Runtime.audit`).

The layer table is enforced by `tests/test_suite_rules.py` (`plantcraft_sdk.apptest`).

## This module's own rules

- **Language**: user-facing text is English only for now: every string goes through `t()` (`src/alarmcraft/i18n.py`, `frontend/src/i18n.ts`) so a Portuguese catalog can be added later (parked in `docs/gaps.md`).
- **Bad data never crashes.** NaN, gaps, constant signals, empty windows, a dead source: the
  alarm keeps its state and shows the reason in words a person can act on;
  never an exception or a 500. Unfinished features return "not supported" and are hidden in the UI.
- **No silent wrong answers.** An alarm that could not be judged says so ("without data"), never
  "normal"; a result expires after 15 minutes, so a stopped Alarms leaves no green light. People act on
  these verdicts in a running plant.
- **One judging path**: the monitor and "Try it" both go through `engine.evaluate`.
- **Clean room** (suite rule): the tools studied for this module, for public behaviour only, are AVEVA, AspenTech, Siemens, Yokogawa, Honeywell, Cognite.
- Tests talk to `plantcraft_sdk.testing.FakePlantCraft`, never to a real PlantCraft; the
  test plant (loops, a pump, a text signal, every kind of user) is in `tests/plant.py`.
- Performance is a feature: a cycle reads every alarmed signal in one batch request, from where
  the last cycle stopped; evaluation is linear in the samples.

## Oracles and floors

PlantCraft Alarms' oracle (planned): the ISA-18.2 and EEMUA 191 figures computed on a public
sample alarm log, checked against the figures computed by hand; today `tests/test_engine.py`
checks every figure on synthetic alarm logs.
