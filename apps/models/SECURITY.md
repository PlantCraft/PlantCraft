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

PlantCraft Models is in alpha. Security fixes go to the `main` branch and the latest
release.

## Scope and design notes

- **Models run code; the code runs in a sandbox.** A Modelica model is compiled to C and run.
  OpenModelica never runs in the app's container: every check, diagram, simulation and export
  is a task of PlantCraft's compute workers, answered by the runner (`modelcraft-executor`, the
  `modelcraft-runner` image), which the suite runs with **no network at all**
  (`network_mode: none`), **no secret** (no app key, no token, no database), a read-only root
  filesystem, no Linux capabilities, `no-new-privileges`, the compute user (10020) and CPU,
  memory and process limits. Each job also runs in its own process group with a time limit
  (killed at the limit), an address-space limit, a file-size limit and no core dumps. The runner
  shares only its jobs folder, with the worker's gateway; the app shares nothing with it.
- **What a model may not use.** `external` functions (C or Fortran code) and the file, system
  and environment functions of `Modelica.Utilities` (`System`, `Files`, `Internal`, however
  imported or aliased) are refused by the app before a job leaves
  (`modelica.source.policy`) and by the runner again. The administrator may allow `external`
  code with `MODELCRAFT_ALLOW_EXTERNAL=true`; leave it off unless every editor is trusted to run
  code on the server.
- **No plant connections, no plant writes.** PlantCraft Models never talks to a DCS,
  PLC, historian or OPC UA server. Its only outbound connection is to the
  PlantCraft named by `PLANTCRAFT_URL`, through `plantcraft_sdk.client`
  (`tests/test_suite_rules.py` fails on any other network module). It writes only
  its own runs and audit entries; `app.toml` declares `plant_write = false`.
- **Sign-in is PlantCraft's.** Every API route and page needs a PlantCraft
  token whose `apps` claim grants `modelcraft`, verified offline with
  PlantCraft's published keys. Viewers read projects and runs; editors change files, draw
  diagrams (a diagram runs omc), check, simulate and export.
- **Plant data with the person's own token.** Signals that feed a simulation are read with the
  editor's token, so an editor cannot read what PlantCraft does not show them.
- **App key.** The service token comes from an app key an admin creates in
  PlantCraft, used only to report runs. Give it as a file (`PLANTCRAFT_APP_KEY_FILE`, a Docker secret
  in the suite's compose file) or `PLANTCRAFT_APP_KEY`; it is never logged, stored by
  PlantCraft Models or handed to the runner.
- **Audit.** Every change to a project's shape (projects created, changed, duplicated,
  deleted; files created, renamed, deleted, imported) and every run started or deleted is
  recorded in PlantCraft's audit log (actions `modelcraft.project.*`, `modelcraft.file.*`,
  `modelcraft.run.*`, `modelcraft.fmu.*`). Saves of a file's text (by hand or from the diagram)
  are kept as the file's versions, each with who saved it and when.
- **Shown safely.** Class documentation (HTML from models) is shown in a sandboxed frame with no
  script, no form and a content policy that loads nothing; Modelica text is never interpreted
  by the browser.
- **Limits.** 200 files, 1 MB per file and 8 MB per project; 50 versions per file; 500
  overrides; 100,000 plant samples per simulation; 40 variables and 20,000 points per plot
  request. `tests/test_suite_rules.py` sends malformed input to every API operation.
- **Containers.** The app image runs as uid 10011 with a read-only root filesystem;
  state lives only in `/data`, jobs in `/jobs`, scratch in the `/tmp` tmpfs. It holds no build
  tools and no compiler, not even pip. Dependencies are installed offline from
  a hash-checked wheelhouse (`deploy/requirements.lock`); `plantcraft-sdk`
  comes from `vendor/` with its SHA-256 in `vendor/README.md`. The runner image is
  OpenModelica's, pinned by digest, with the Modelica Standard Library pinned by commit.
