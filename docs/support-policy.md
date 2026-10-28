# Support and API policy

What an installation can count on between versions: which versions get fixes, how a part of
API v1 is retired, and what an update promises about data. PlantCraft is in alpha; this policy
is what the project holds itself to now and tightens at 1.0.

## Versions

- **The suite has one version** (`release.json`, today 0.4.0) and each app its own; a bundle
  names the ones that were tested together. Install a bundle, not apps from different bundles.
- **Supported:** the latest release, and `main` for those who build it. Fixes, security fixes
  included, go to `main` and ship in the next release; there are no patch branches for older
  releases during the alpha.
- **Updating from the release before** is tested on every release (`make e2e-upgrade`: install
  the previous bundle with the demo, update, compare every row, roll back). Skipping releases
  works when the bundle allows it: a bundle names the oldest version it updates (`UPGRADE_FROM`),
  and the installer refuses an older one, or a bundle older than the installed version, before
  anything changes.
- **Stages** in `ROADMAP.md` (alpha, beta, stable) say how much a part may still change. A part in
  alpha may change its screens between releases; its data and API v1 follow the rules below.

## API v1

API v1 is the contract between PlantCraft and every app, the suite's own and anyone else's
([api-v1.md](api-v1.md)).

- **Inside v1, only additions.** New routes, new optional parameters, new response fields. CI
  compares the API with every published release (`docs/api/v1/releases/<version>.json`) and
  fails on a route removed, a field removed or newly required, or a type changed.
- **Deprecation.** A route or field that should go stays and works. It is marked deprecated in
  `docs/api-v1.md` and the [API v1 reference](api-v1-reference.md) with the release that
  deprecated it and what to use instead, and the CHANGELOG says so under "Deprecated".
- **Removal only in v2.** A deprecated part leaves when API v2 ships, and v2 ships beside v1 for
  at least two releases, so an app moves when it updates, not on the day the suite does.
- **The SDK follows the API.** `plantcraft-sdk` keeps working against the PlantCraft of its
  release and the next one (`tests/contract/test_sdk_previous.py`).

Deprecated today:

| Part | Since | Use instead |
|---|---|---|
| Bare tags in place of signal ids (`/api/v1/signals/{tag}` and the rest, [api-v1.md](api-v1.md) "Transition") | before 0.4.0 | the signal id `<source>:<tag>` |
| `/api/v1/assistant` and its conversations (the suite's screens no longer use them since ui 0.51.0) | 0.4.x | the assistant's works ([assistant.md](assistant.md)) |

## Data

- **An update never loses data.** Before it changes anything the installer takes a `pre-update`
  backup, and a failed update rolls back to it by itself ([operations.md](operations.md),
  section 3).
- **Schemas only go forward.** A release migrates the stores it finds; going back restores the
  backup, it never undoes a migration.

## Getting help

- Questions and ideas: GitHub Discussions on the public repository, once it is open.
- Bugs: an issue with the bug form (version, what you did, what you saw).
- Vulnerabilities: privately, as [SECURITY.md](../SECURITY.md) says. Never in a public issue.

There is no paid support and no guaranteed response time during the alpha.
