# Contributing at scale: many people and agents, no conflicts

> **Updated:** 2026-10-21 · Status: plan. The repositories are private and under one personal
> account today; the organisation below is set up when a maintainer decides (AGENTS.md, section 9).

The suite is meant to grow fast: many contributors, most of them working with an AI agent, each
on a module of their own, with little human review in between. That only works if the structure
keeps changes apart and the checks catch what reviewers would. This page is how.

## 1. What keeps changes apart

- **One repository per module.** A contributor (or an agent session) works in one repository at
  a time. Modules never import each other; they meet only in API v1, so two module teams never
  touch the same file.
- **The platform is the only shared code**, and it changes by release: a change to
  `plantcraft-sdk` or `@plantcraft/ui` is a PlantCraft PR and a new version; each module
  picks it up in its own PR with `dev/revendor`. Nobody edits a vendored file. The version
  number is taken at merge time by `dev/sdk-version` (main's next free one), never by hand.
- **Contracts are additive.** API v1, the app standard and the SDK add fields and functions; they
  do not rename or remove inside a major version. A breaking change is a maintainer decision with a
  migration for every module in the same release.
- **Assigned once.** Ids, prefixes, ports and container users live in the suite table
  ([app-standard.md](app-standard.md), section 7). A new module takes the next row in a
  PlantCraft PR before its repository exists.
- **Small PRs from `main`.** No stacked chains. Merge one, run `make ci`, then the next.

## 2. What replaces most human review

Every repository runs the same gates in CI, so a PR that passes them is safe to merge without a
line-by-line read:

| Gate | Catches |
|---|---|
| `plantcraft-app check` | Drift from the app standard: manifest, layout, Makefile targets, vendored hashes |
| `tests/test_suite_rules.py` (`plantcraft_sdk.apptest`) | Network access outside the runtime, imports that point up or into another module or a plant protocol, an image that disagrees with `app.toml`, a 500 on junk input |
| Time budget (`[tool.plantcraft.tests]`) | Tests that grow slow |
| Floors (`tests/floors.toml`) | Fewer methods, oracle cases, API routes or help pages than before |
| Oracles (`tests/oracles`) | Wrong answers on public data with known results |
| e2e journeys | A broken screen |
| Security audit (per stage) and dependency scans | What tests do not see |

A human reviews what the gates cannot judge: product decisions, wording people read, new
dependencies, and anything in section 9 of AGENTS.md. A change to a path `.github/CODEOWNERS`
guards (sign-in, permissions, the assistant's tools, the stores, the sandbox, the installer, CI,
the agents' rules and the tests that hold them) is always read by a maintainer, gates or not: a
hostile pull request can weaken a gate too ([contributing-safety.md](contributing-safety.md)).

## 3. Roles

| Role | Who | May |
|---|---|---|
| Owner | the project lead | Maintainer decisions (AGENTS.md section 9), releases, the suite table, the rules |
| Maintainer | one or two per module | Merge PRs in their module when CI is green; review module PRs from others |
| Platform maintainer | few, trusted | Merge in `processcraft` (SDK, UI, API v1, the standard); every module depends on it |
| Contributor | anyone invited | Open PRs; an agent session counts as the person who runs it |

Every PR names the person responsible, even when an agent wrote it.

## 4. The GitHub organisation (when a maintainer sets it up)

- **One organisation** (the platform's name), all repositories private until a maintainer opens
  them (after the institutional clearance and a pilot).
- **Two repositories** (decided 2026-10-23): `PlantCraft`, the whole suite (the platform at the
  root, every official app in `apps/<app>`, the Simulator in `simulator/`), and
  `plantcraft-app-template`, the starting point for an app of one's own. The private
  repositories the apps came from (`linkcraft`, `histcraft`, `dashcraft`, `alarmcraft`,
  `modelcraft`, `plantcraft`) and the retired ones (`cpm`, `datacraft`) are archived, not deleted.
- **Teams**: `owners`, `platform` (the root, `sdk/`, `ui/`), one team per module (its
  `apps/<app>` folder), `contributors` (triage everywhere). `CODEOWNERS` names the team of each
  folder; `sdk/`, `ui/` and `docs/app-standard.md` name `platform`.
- **Branch protection on `main`**: PR required, the workflows of the folders a PR touches
  required, no force push. One approval for the root, `sdk/` and `ui/`; for a module's folder,
  green CI plus its maintainer's merge.
- **Organisation-wide**: a `.github` repository with the PR template, issue forms (bug from the
  plant, new method, new module), CONTRIBUTING pointer and the security policy; Dependabot or
  Renovate on every repository; secret scanning on.
- **Agents**: the Claude GitHub App installed on the organisation, so agent sessions open PRs
  and answer review comments; agents never get admin, never merge in `processcraft` without a
  human approval, and never touch repository settings.
- **Releases**: one tag for the suite (`vX.Y.Z`, the platform and the apps share the version;
  the Simulator, the SDK and the ui keep their own); `make bundle` assembles the offline suite
  bundle from that tree.

## 5. Adding a module (the checklist)

1. PlantCraft PR: a row in the suite table and `PLANTCRAFT_APPS`, an entry in
   [suite.md](suite.md).
2. A new folder `apps/<app>` from the smallest module's layout (Alarms), with its workflow
   `.github/workflows/<app>.yml` copied from `alarms.yml`: `app.toml`, `AGENTS.md` (the short
   module file), `CLAUDE.md`, `README.md` (with the "How it is built" section), `SPEC.md`,
   `ROADMAP.md`, `docs/` (`STATUS.md`, `gaps.md`, `devlog.md`, `help/`), `vendor/`.
3. The server from `plantcraft_sdk.server`, the interface on `@plantcraft/ui`, the tests on
   `plantcraft_sdk.apptest`; `make ci` green.
4. A first PR that passes every gate, then a maintainer adds it to the bundle.
