# How we build PlantCraft

> **Updated:** 2026-10-21

## What it is for

Industrial software for process engineers (historians, loop monitoring, dashboards, alarm
management, digital twins, process modelling) is powerful, expensive and closed. A researcher, a
student or a process engineer in a small plant rarely gets to use it, and almost never gets to
change it. PlantCraft brings what the tools of each category offer across vendors into one open
platform that installs on premises, works offline, reads the plant without ever writing to it,
and can be read, tested and extended by the people who use it.

## Built with AI, in the open

**PlantCraft is vibe coded.** Nearly all of its code, tests and documentation were written by
[Claude Code](https://claude.com/claude-code) (Anthropic's Claude Opus 5.5 model), directed by a
process engineer who decides what to build, reviews the results and owns every decision. We say
so plainly, in every repository, because it is the point:

- **It is what makes the platform possible.** One engineer with an AI agent can bring a category
  of industrial software within reach of researchers and plant engineers who would never get a
  licence for it. The same path is open to anyone who wants to extend it.
- **It is why the rules are strict.** Code an agent writes quickly must be held to more checks,
  not fewer: every module follows one standard ([app-standard.md](app-standard.md)), one test
  layout with a time budget ([testing.md](testing.md)), hostile-input and offline tests, oracle
  tests against public data, and a security audit before every stage
  ([security-guide.md](security-guide.md)). The rules live in `AGENTS.md`, which the agents read
  first, so they hold whoever (or whatever) writes the next change.
- **It is how the platform is meant to be used.** PlantCraft is designed to work with AI:
  specialists answer questions over what the modules publish, every action is an API endpoint an
  agent can call with a person's permissions, and **Copy as prompt** turns an Analytics method, block
  or algorithm, a Models class or the plant map import into a prompt to rebuild, review or extend
  with any AI assistant ([design note](design/copy-prompt.md)). A person can also connect their
  own assistant to the read-only MCP server and ask it about the plant as they see it
  ([assistant-access.md](assistant-access.md)). The language model and the MCP server stay off by
  default and run only where the plant's IT allows them.

We are not ashamed of it, and we do not hide it: a commit written by an agent carries its
co-author line, and each repository's README says how it was made.

## How we think

1. **The plant comes first.** Read-only on plant systems; bad data never crashes; a method that
   cannot judge says "inconclusive" instead of guessing. People act on our findings in a running
   plant.
2. **Secure and offline by default.** Nothing reaches the internet unless an administrator turns
   it on; sign-in is on by default; containers are isolated; every release ships its SBOM and
   hashes. Plants install nothing that IT and OT security have not approved.
3. **One place for what is shared, one owner for everything else.** The platform holds people,
   access, assets, signal roles, results, events and messages. A module owns its objects, its
   methods and its workflow, and nothing else. A thing written twice is a bug: it moves into the
   platform, `plantcraft-sdk` or `@plantcraft/ui`.
4. **Same shape everywhere.** Every module has the same files, the same frame, the same help, the
   same tests and the same commands. Whoever knows one module, person or agent, knows them all.
5. **Clean room.** We learn from public behaviour of commercial tools (brochures, manuals, papers,
   standards) and never from their code or anything under NDA.
6. **Measured, not claimed.** Readiness comes from tests, oracles and benchmarks; numbers in
   `tests/floors.toml` only rise.

## How the work is organised

- **One repository per module**, one container per module, one owner thread per repository at a
  time. The platform changes first; modules pick up a new SDK or UI version in their own PR
  ([contributing-at-scale.md](contributing-at-scale.md)).
- **The rules are code.** `plantcraft-app check` and `plantcraft_sdk.apptest` check every
  module against the standard in CI, so the standard does not drift as the suite grows.
- **Everything is tracked in the repository.** `docs/STATUS.md` (now), `docs/gaps.md` (the ranked
  work list), `docs/devlog.md` (what happened), `SPEC.md` and `ROADMAP.md` (what the category
  offers and how far we are).
