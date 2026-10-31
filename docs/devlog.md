# Devlog

Notes on how the module changed and why, newest first: what a later contributor would need to
know that the code and `CHANGELOG.md` do not say. One short entry per change worth explaining.

## Unreleased

- Operations (built-in, like Desk): Docker's CPU is a percentage of one core, so an "80 %" alert
  on it meant nothing for an app limited to 4 CPUs; the installer now gives each service its limit
  and the share of it, and samples the machine from `/proc`. Logs live in each app's own volume,
  which PlantCraft does not mount, so each server reads its own (`GET /api/ops/logs`) and PlantCraft
  fans out with an `ops` token instead of a log shipper: no new container, nothing leaves the
  machine. The load checks stay in the core watch, not in Alarms, so they still speak when Alarms
  is down. Phase 2 (tickets, integrator companies and teams, hours) is designed in the E4 report.

## 0.5.1

- The repository's public history starts here; earlier releases are summarized in `CHANGELOG.md`.
