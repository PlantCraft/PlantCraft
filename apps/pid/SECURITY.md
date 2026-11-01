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

Security fixes are released as new versions of the PlantCraft PID package; the latest version is supported.

## Scope and design notes

- **No plant connections, no plant writes.** PlantCraft PID never talks to a DCS,
  PLC, historian or OPC UA server. Its only outbound connection is to the
  PlantCraft named by `PLANTCRAFT_URL`, through `plantcraft_sdk.client`
  (`tests/test_suite_rules.py` fails on any other network module). It writes only
  its own notes and audit entries; `app.toml` declares `plant_write = false`.

- **Sign-in is PlantCraft's.** Every API route and page needs a PlantCraft
  token whose `apps` claim grants `pidcraft`, verified offline with
  PlantCraft's published keys. Viewers read notes; editors write them.
- **Who reads.** Asset names are read with the person's own token, so nobody
  sees through the app an asset PlantCraft does not show them.
- **App key.** The service token comes from an app key an admin creates in
  PlantCraft. Give it as a file (`PLANTCRAFT_APP_KEY_FILE`, a Docker secret
  in the suite's compose file) or `PLANTCRAFT_APP_KEY`; it is never logged or
  stored by PlantCraft PID.
- **Audit.** Every note created, changed or deleted is recorded in PlantCraft's
  audit log (action `pidcraft.note.*`).
- **Limits.** A note holds up to 4,000 characters; `tests/test_suite_rules.py`
  sends malformed input to every API operation.
- **Container.** The image runs as uid 10016 with a read-only root filesystem;
  state lives only in `/data`, scratch in the `/tmp` tmpfs. It holds no build
  tools and no compiler, not even pip. Dependencies are installed offline from
  a hash-checked wheelhouse (`deploy/requirements.lock`); `plantcraft-sdk`
  comes from `vendor/` with its SHA-256 in `vendor/README.md`.
