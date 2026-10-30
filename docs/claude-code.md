# Working with Claude Code

> **Updated:** 2026-10-21

Most changes to PlantCraft are made by people working with an AI coding agent (we use
[Claude Code](https://claude.com/claude-code)). This page is the shared playbook: the commands
every repository answers to the same way, and prompts that work. The rules the agent follows are
in `AGENTS.md` (the suite's, in this repository, plus each module's short one); this page is about
how to ask.

## The same commands in every repository

| Command | What it does | When |
|---|---|---|
| `make ci` | Everything CI runs: app standard check, ruff, frontend build and unit tests, pytest (both tiers) | Before every push |
| `make test-fast` | pytest without the slow tier (hostile inputs, oracles, real sockets, e2e) | The loop while working |
| `make test` | pytest, both tiers | Before `make ci`, if you only touched Python |
| `make e2e` | Browser journeys (Playwright, Chromium) | When you touched a user journey |
| `make format` | ruff format and safe fixes | Before committing |
| `make serve` | The module against a PlantCraft at `PLANTCRAFT_URL` | Trying it by hand |
| `make image`, `make package` | The container image; the signed `.pcapp` with its SBOM | Releases |
| `plantcraft-app check .` | The module against the app standard (also in `make ci`) | After touching `app.toml`, the Makefile or vendor/ |
| `dev/revendor --all` (platform) | Puts a new SDK wheel and UI package in every module, with hashes | After an SDK or UI release |

Every test run is held to a time budget (`[tool.plantcraft.tests]` in `pyproject.toml`): a test
that grows slow fails and is named ([testing.md](testing.md)).

## Starting a session

The agent reads `AGENTS.md` by itself (`CLAUDE.md` points to it). A good first message names the
repository, the goal and the limit:

> In `alarmcraft`: an alarm's page should show the last 20 journal entries of that alarm. Follow
> AGENTS.md; `make ci` green before you push; open a PR and tell me what changed.

## Prompts that work

**A new method** (Analytics, or any module with `@method`s):

> Add a `@method` to Analytics that flags a valve whose OP stays above 95 % for more than 10 % of the
> window. Inputs by signal role, parameters with labels, `describe(metrics)` with the finding
> text, a help page in `methods/help/`, a hostile-data test and an oracle case from the simulated
> plant. Raise the floors it moves.

**A new module** (a new repository):

> Start `<name>craft` from the app standard (PlantCraft `docs/app-standard.md`): copy the
> layout of the smallest module (Alarms), take the server skeleton and the test kit from
> `plantcraft_sdk.server` and `plantcraft_sdk.apptest`, register it in the suite table and
> `PLANTCRAFT_APPS`, and leave a `SPEC.md` from public sources only.

**Something repeated** (the most valuable kind of change):

> Dashboards and Alarms both draw the same signal picker. Move it into `@plantcraft/ui`,
> release a new UI version, `dev/revendor` it into both, delete the copies, and keep both
> modules' tests green.

**A bug from the plant:**

> On the project's test server, Analytics' loop page for FIC-1004 shows "unexpected error". Find the cause, add
> the test that fails before the fix, fix it, and add a line to `docs/devlog.md`.

**A review before merging:**

> Review PR #12 (`apps/link`) against AGENTS.md and the app standard: offline, read-only toward
> the plant, hostile inputs, tests that fail without the change, docs and devlog updated.

## Rules of thumb

- **One goal per session and per PR.** Small PRs merge; long chains conflict.
- **Ask for the test first.** "Write the test that fails, then fix it" gives better fixes than
  "fix it".
- **Name the folder.** The platform is the repository's root and each module is `apps/<app>`;
  a change to the SDK or ui is released as a new version and the apps pick it up with
  `dev/revendor --all`, in the same PR when the change is one.
- **Maintainer decisions stay with a person** (AGENTS.md, section 9): making anything public, secrets,
  deleting data or branches, a write path to a plant, licences. An agent stops and asks.
- **Look at the screen.** For interface changes ask for a Playwright screenshot, or use
  `dev/preview` on the project's test server to see the change in seconds.
