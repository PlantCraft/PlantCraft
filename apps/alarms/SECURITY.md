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

PlantCraft Alarms is in alpha. Security fixes go to the `main` branch and the latest
release.

## Scope and design notes

- **No plant connections, no plant writes.** PlantCraft Alarms never talks to a DCS,
  PLC, historian or OPC UA server. Its only outbound connection is to the
  PlantCraft named by `PLANTCRAFT_URL`, through `plantcraft_sdk.client`
  (`tests/test_suite_rules.py` fails on any other network module). It writes only
  its own results, events, runs, schedules, and audit entries; `app.toml` declares `plant_write = false`.

- **Sign-in is PlantCraft's.** Every API route and page needs a PlantCraft
  token whose `apps` claim grants `alarmcraft`, verified offline with
  PlantCraft's published keys. Viewers read the alarm summary, journal and
  performance; editors acknowledge, shelve and configure alarms.
- **Two readers.** The monitor and an alarm's chart read the plant with
  Alarms' service token (an alarm is a published judgement). The pickers,
  suggested limits and "Try it" read with the editor's own token, so an editor cannot browse what
  PlantCraft does not show them.
- **App key.** The service token comes from an app key an admin creates in
  PlantCraft. Give it as a file (`PLANTCRAFT_APP_KEY_FILE`, a Docker secret
  in the suite's compose file) or `PLANTCRAFT_APP_KEY`; it is never logged or
  stored by PlantCraft Alarms.
- **Audit.** Every change a person makes (alarms created, changed, deleted,
  shelved, unshelved, taken out of or returned to service) is recorded in PlantCraft's audit log (action `alarmcraft.*`).
- **Limits.** Delays up to an hour, shelving up to 7 days, windows up to 366
  days, 5,000 points per chart, 2,000 journal rows per request. `tests/test_suite_rules.py` sends malformed input
  to every API operation.
- **Container.** The image runs as uid 10009 with a read-only root filesystem;
  state lives only in `/data`, scratch in the `/tmp` tmpfs. It holds no build
  tools and no compiler, not even pip. Dependencies are installed offline from
  a hash-checked wheelhouse (`deploy/requirements.lock`); `plantcraft-sdk`
  comes from `vendor/` with its SHA-256 in `vendor/README.md`.
