# Changelog

## [0.5.1] - 2026-10-30

- Suite 0.5.1: same Simulator, version aligned with the suite; its image now carries this
  changelog for the release notes.

## [0.5.0] - 2026-10-27

- **0.5.0: renamed to `simcraft`.** The platform is now PlantCraft, so the Simulator's package,
  import, command, image and compose service are `simcraft` and its variables `SIMCRAFT_*`
  (were `plantcraft` and `PLANTCRAFT_*`). The namespace, endpoint path and NodeIds are unchanged
  (docs/release.md, "Migration from 0.4.x to 0.5.0").
- **Source test kit** (`plantcraft.testkit`, extra `testkit`, development and CI only: its libraries
  are not in the image, and it is not in `--help`). The plant's PV, SP, OP and MODE served as the other sources Historian
  reads: sample CSV files in every layout (and one with errors), a PI Web API (Basic auth,
  paging, digital states, 503 bursts, slow answers), an MQTT broker (value, JSON, nested JSON), a
  Modbus TCP device (every data type and byte order, scaled integers, coils) and PostgreSQL
  tables (wide, long, naive times). `plantcraft testkit --serve ...` runs them by hand;
  Historian's `make sources-check` compares what it archives with what the kit published.
- **README.** Says how it is built (vibe coded with Claude Code, as every repository of the
  suite) and which parts of the suite read it (ProcessCraft and its Historian, on the `demo`
  network).
- **Old command names removed.** `plantcraft` is the only command; the 0.3.x names are gone.
- **Old variable names removed.** Only `PLANTCRAFT_*` variables are read; the
  `PROCESS_SIMULATOR_*` and `PROCESSCRAFT_OPCUA_*` fallbacks are gone (the suite sets the new
  names since 0.4.0).
- ruff 0.17.1, as in the rest of the suite.

## 0.4.0 — 2026-10-19

PlantCraft: the project becomes the OPC UA plant simulator app of the ProcessCraft suite.

- **Renamed.** Distribution and import package `plantcraft`, command `plantcraft`, Docker
  image `plantcraft`, repository `PlantCraft/plantcraft`.
- **One OPC UA namespace URI, `urn:processcraft:plantcraft`,** for both servers (was a
  repository URL for the benchmark and `urn:processcraft:simulator` for ProcessCraft's demo
  server). Clients resolve the namespace
  index by this URI. The default endpoint path is `/plantcraft/` (the server accepts any path).
- **Benchmark identity 0.4.0.** The namespace URI is part of the benchmark manifest and the
  server checkpoint, so `benchmark_version` moves from 0.3.0 to 0.4.0. Catalog, model, scenario
  parameterization, profiles and NodeIds are unchanged (catalog digest
  `sha256:6c737ebd…2339cb`). Benchmark manifest `sha256:37705f1f…864d6b`; 60-second seed-42
  dataset fixture `sha256:889c8959…5498ae1`. A 0.3.x historian is refused at start (checkpoint
  mismatch): keep it as a prior artifact or start a new volume (docs/release.md).
- **The 50-loop portfolio** that the ProcessCraft demo reads (`CPM.Loops.<LOOP>.<SIGNAL>`, 205
  tags, 48 hours of history, restart continuity) moved here from ProcessCraft
  (`processcraft/simulator`) as `plantcraft.loops`: `plantcraft loops serve` and
  `plantcraft loops catalog` (JSON). Dynamics are unchanged, pinned by a reference test.
- **Settings** are `PLANTCRAFT_*` variables (docs/opcua-interface.md); the former
  `PROCESS_SIMULATOR_*` and `PROCESSCRAFT_OPCUA_*` names are still read as fallbacks.
- **One health check** (`python -m plantcraft.healthcheck`, `plantcraft healthcheck`) for either
  server: the benchmark heartbeat, or the first loop's PV for the portfolio.
- **Image** for the suite's `deploy/compose.yaml`: pinned `python:3.13.16-slim-trixie` digest,
  hash-checked offline wheelhouse (`deploy/requirements.lock`), uid 10004, read-only root,
  state in `/data`, no pip at runtime, `HEALTHCHECK`; default command `plantcraft loops serve`.
- App-repository rules and tracking: AGENTS.md, SPEC.md, ROADMAP.md, docs/STATUS.md,
  docs/gaps.md, docs/devlog.md, ATTRIBUTION.md, `make ci`.

## 0.3.7 — 2026-09-06

- Make the cross-platform historian restart interoperability test use an
  explicit fixed wall clock so runner speed cannot create a legitimate new
  sample while an immediate-restart assertion is being evaluated.
- Preserve the 0.3.6 runtime image hardening and all scientific identities.

## 0.3.6 — 2026-09-06

- Apply available Debian security updates while building the runtime image.
- Remove `pip`, `setuptools`, and `wheel` after installing the simulator so
  build tooling and its known vulnerabilities are absent from runtime.
- Preserve the 0.3.0 benchmark, schema, catalog, and checkpoint identities.

## 0.3.5 — 2026-09-06

- Realign compatible checkpoints to the configured sampling lattice during
  restart so checkpoints written by earlier releases cannot leave all Signal
  publication cadences permanently unreachable.
- Preserve deterministic state, intentional Signal gaps, and the existing
  benchmark, schema, catalog, and checkpoint identities.

## 0.3.4 — 2026-09-04

- Publish a non-historized simulator heartbeat with deterministic source
  timestamps and use it for container liveness.
- Keep intentional Signal gaps and communication-loss scenarios from being
  misclassified as a failed simulator process.

## 0.3.3 — 2026-09-04

- Index every historian table by source timestamp, including compatible
  existing volumes, so steady-state retention remains bounded after a
  24-hour bootstrap.
- Preserve the 0.3.2 restart-gap and freshness semantics and all scientific
  benchmark identities.

## 0.3.2 — 2026-09-04

- Advance compatible deterministic state across wall-clock downtime before the
  OPC UA endpoint becomes ready, then commit one current frame without
  fabricating observations inside the outage gap.
- Preserve the 0.3.0 benchmark, schema, catalog, and checkpoint identities so
  existing compatible historian volumes resume in place.
- Make the container healthcheck reject stale or implausibly future source
  timestamps instead of treating server-state availability as sufficient.
- Add restart-gap, current-publication, and timestamp-freshness coverage.

## 0.3.1 — 2026-09-04

- Preserve the 0.3.0 benchmark, schema, catalog, and checkpoint identities while
  eliminating redundant per-node retention deletes during a new historian's
  bounded cold bootstrap.
- Increase the bounded cold-bootstrap write batch from 20,000 to 100,000 values;
  steady-state writes continue enforcing retention on every committed frame.
- Add direct coverage proving that retention can be deferred only for the
  already bounded, initially empty bootstrap transaction stream.

## 0.3.0 — 2026-09-04

- Add closed JSON Schema v1 contracts for benchmark manifests, runtime profiles,
  observation rows, hidden-truth frames, and dataset manifests.
- Add canonical prefixed SHA-256 manifest identities and compatibility checks.
- Add executable smoke, development, paper, and stress profiles shared by
  offline generation and the OPC UA server.
- Reject ambiguous timestamps, rounded intervals, and silently clamped runtime
  parameters before generation or server startup.
- Preserve distinct source and server timestamps in datasets and OPC UA values.
- Publish all resolved loop-model parameters and structure policies in the
  benchmark manifest.
- Enforce coupling delays, actuator travel limits, bounded anti-windup,
  bumpless manual return, reversal-aware backlash, split-range mapping, and
  protective selector behavior.
- Add deterministic invariants for model completeness, signed delayed coupling,
  control modes, balance residuals, actuator failures, and sensor recovery.
- Normalize historian timestamps and close inclusive, reverse, empty-range, and
  continuation-point behavior.
- Add bounded retention plus a transactional, versioned simulator checkpoint so
  compatible restarts continue without duplicating bootstrap history.
- Reject incompatible checkpoints and interrupted historian bootstraps before
  starting the OPC UA endpoint.
- Freeze numerical parameterizations and executable minimum signatures for all
  20 scenarios in versioned contracts.
- Scope controller-tuning scenarios to their active windows, propagate the
  downstream oscillation through the declared delayed coupling, and model
  irregular cadence with deterministic missing slots and timestamp jitter.
- Add a reproducible parallel 15/5/10-seed scenario qualification workflow and
  canonical study manifests.
- Add per-scenario 95% seed confidence intervals and development-fit,
  observation-only window baselines for cumulative PV/SP,
  controller/actuator/mode, and quality/timestamp views.
- Add explicit scenario allowlists for integrated, isolated, and deliberate
  overlap studies, with fail-fast validation and exact selection provenance.
- Add an observation-only active/inactive per-frame baseline and a graph view
  using directly connected published PVs, while reporting false alarms per
  loop-day and excluding topology-confounded scenario-name scoring.
- Add a canonical 600-run isolation matrix covering all 20 scenarios and 30
  fixed seeds, with per-run digests, failures, confidence intervals, and a
  closed JSON Schema contract.
- Excite declared upstream control loops during `process.interaction` so the
  isolated scenario propagates a measurable delayed response through the plant
  graph without implicitly enabling the global load-change scenario.
- Add a bounded-memory option for high-cadence scenario studies that omits only
  in-memory per-frame baselines while preserving scenario and window metrics.
- Exclude frames with no nominally scheduled Signals from transport-signature
  denominators, preventing high publication cadence from appearing as data loss.
- Give `control.sluggish_tuning` an explicit 0.06 normalized setpoint step and
  qualify its response over a fixed 1,800-second physical window, so changing
  the scenario-cycle duration no longer dilutes the signature threshold.
- Cache immutable scenario-onset offsets and reuse the preceding active state
  during integration, reducing qualification profiler time by about 25% while
  preserving canonical evaluation digests.
- Add observation-only temporal detection and candidate-loop localization
  baselines, using three-frame persistence and a shared identity-free anomaly
  score with average precision plus precision/recall at five.
- Compare native irregular observations with a causal 60-second last-value
  regularization that retains quality, timestamps, and explicit imputation.
- Add a cross-platform Python 3.12/3.13 CI matrix and complete-suite execution
  on Linux, macOS, and Windows release-support targets.
- Document release compatibility, 0.2-to-0.3 migration, scenario change
  control, the security threat model, and the independent scientific-review
  disposition required before publication-grade claims.
- Include citation, security, release, scientific, container, and contract
  documentation in the source distribution.
- Make the standalone container start with the bounded `smoke` profile by
  default; longer research histories remain explicit profile selections.
- Qualify scenario behavior across Linux, macOS, and Windows while defining
  byte-identical numerical replay within one recorded execution environment;
  system math libraries may differ in last-bit floating-point results.

## 0.2.0 — 2026-09-03

- Define an integrated ten-area, 50-loop, 500-signal plant catalog.
- Add 20 layered normal and failure scenarios.
- Add deterministic grey-box process, PI controller, actuator, sensor, and
  transport models.
- Add separate observation CSV and hidden-truth JSONL generation with SHA-256
  digests.
- Add a 500-node OPC UA Data Access and Historical Access server.
- Add scientific-method, research-protocol, security, citation, container, and
  continuous-integration documentation.
