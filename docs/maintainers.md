# Maintainers: issues and pull requests

> **Updated:** 2026-10-30

How an issue or a pull request from outside is handled, so that every one gets an answer in a
few days and nothing reaches the core without an agreed plan. The zones are in
[CONTRIBUTING.md](../CONTRIBUTING.md#what-is-core-and-what-is-open); the picture is in
[architecture.md](architecture.md#core-and-extensions).

## An issue

1. **Answer within 3 days**, even if only to say it was read. Thank the person.
2. **Label it** with one area and one kind:
   - area: `core`, `app: analytics`, `app: historian`, `app: view`, `app: alarms`,
     `app: models`, `app: documents`, `app: simulator`, `docs`, `install`;
   - kind: `bug`, `idea`, `question`; plus `upstream` when the cause is in a dependency (keep it
     open until that dependency ships the fix), `good first issue` when a newcomer can take it.
3. **A core idea** gets a short plan in the issue (what changes, what stays compatible) before
   anyone writes code. The owner agrees in the issue; the pull request then links it.
4. Close with the reason: fixed (link the pull request), duplicate (link the other), or not
   planned (one sentence why).

## A pull request

The Zones check writes, on the pull request's run page, which zones it touches. Then:

| Check | Pass when |
|---|---|
| Zone | One zone. A core change links an issue a maintainer agreed to (the check fails a fork's core change without one) |
| Scope | One change; no unrelated formatting, renames or dependency bumps |
| Contract | API v1 only grows (`make api-contract` shows no removal); apps import only the SDK |
| Tests | New behaviour has tests; `make ci` green in each folder it touches (root, `apps/<app>`) |
| Safety | No network call, no write to the plant, no secret, no binary from outside; paths in [CODEOWNERS](../.github/CODEOWNERS) get a maintainer's review |
| Methods | A public reference, tests on a known answer, the description format |
| Docs | User-visible changes update `docs/`, the CHANGELOG and the pt-BR catalog |

Then one of three answers, in the pull request:

- **Merge**: squash, with a title that says what a person sees.
- **Changes needed**: a list of what to change, each with why.
- **Not here**: the reason and where it fits instead (an issue first, another app, its own
  repository from the app template).

## Ask Claude

The repository carries the review as a Claude Code skill
([`.claude/skills/review-contribution`](../.claude/skills/review-contribution/SKILL.md)). In a
Claude Code session on this repository, ask:

> Review pull request #N: is it aligned?

It reads the pull request, runs the checks above and the `make ci` of the folders it touches,
and answers with the verdict, the reasons and a draft reply for the contributor. Nothing is
posted or merged without a maintainer.

## Releases

Work for the next version collects on one branch during the day. One pull request,
"PlantCraft X.Y.Z", carries the CHANGELOG section as its description; the full tests run on it,
it merges to `main` and is tagged `vX.Y.Z`. The public demo updates only on a release, at a quiet
hour.
