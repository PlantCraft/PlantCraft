# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately. Do not open a public issue.

Use GitHub's private vulnerability reporting: go to the repository's
**Security** tab and choose **Report a vulnerability**
(https://github.com/PlantCraft/PlantCraft/security/advisories/new).

Include what you found, how to reproduce it, the affected version or commit
and the impact you expect. We will acknowledge the report, keep you informed
while we work on a fix and credit you in the advisory unless you prefer
otherwise.

## Supported versions

PlantCraft Analytics is in alpha. Security fixes go to the `main` branch and the latest
release.

## Scope and design notes

- **No plant connections.** PlantCraft Analytics never talks to a DCS, PLC, historian or
  OPC UA server. Its only outbound connection is to the PlantCraft named by
  `PLANTCRAFT_URL`, through `plantcraft_sdk.client` (`tests/test_suite_rules.py`
  fails on any other network module). It writes nothing to the plant.
- **Sign-in is PlantCraft's.** Every API route and page needs a PlantCraft
  token whose `apps` claim grants `linkcraft`; tokens are verified offline with
  PlantCraft's published keys. Viewers read; editors change loops, protocols
  and schedules; admins change method defaults. Requests a person makes reach
  PlantCraft with that person's token, so PlantCraft's own permissions
  apply.
- **App key.** Background work (rounds, schedules) uses a service token
  obtained with an app key an admin creates in PlantCraft. Give it as a file
  (`PLANTCRAFT_APP_KEY_FILE`, a Docker secret in the suite's compose file) or
  `PLANTCRAFT_APP_KEY`; it is never logged or stored by PlantCraft Analytics. Revoking it
  in PlantCraft stops background work at once.
- **Audit.** Every change a person makes (loops, protocols, schedules, method
  defaults, rounds started) is recorded in PlantCraft's audit log
  (`POST /api/v1/audit`, tagged `app: linkcraft`). A failed audit write is
  logged and does not block the change (see `docs/gaps.md`).
- **Container.** The image runs as uid 10012 with a read-only root filesystem;
  state lives only in `/data`, scratch in the `/tmp` tmpfs. It holds no build
  tools, not even pip. Dependencies are installed offline from a hash-checked
  wheelhouse (`deploy/requirements.lock`); `plantcraft-sdk` comes from
  `vendor/` with its SHA-256 in `vendor/README.md`.
- **No code execution.** PlantCraft Analytics has no method studio: methods ship with the
  code and cannot be changed at runtime.
