# Validation record for 0.2.0

Date: 2026-09-03
Host profile: Apple Silicon macOS, Python 3.12.13
Scope: pre-publication local release candidate

## Structural validation

| Check | Result |
| --- | --- |
| Unique control loops | 50 |
| Unique temporal Signals | 500 |
| Loop-associated Signals | 250 |
| Plant-context Signals | 250 |
| Unique candidate OPC UA NodeIds | 500 |
| Named scenario families | 20 |
| Signals per control loop | 5 |
| Catalog SHA-256 | `6c737ebdffa92708361632de0bad17a61c28e9b264608a3361558dee1e2339cb` |

## Automated checks

Ten tests passed locally. They cover catalog integrity, deterministic replay,
seed sensitivity, finite and bounded states, fault-truth isolation, transport
failure semantics, sparse plant-wide coupling, dataset byte reproducibility,
and an independent OPC UA client read from a 500-node server.

Static analysis and formatting checks passed with Ruff.

The numerical suite is instrumented for coverage. The independent 500-node
OPC UA test runs separately because Python 3.12 coverage instrumentation causes
severe overhead inside asynchronous address-space construction; the same test
passes without instrumentation, while Python 3.13 also completed the
instrumented path.

## Six-hour generation benchmark

Command:

```bash
simcraft generate \
  --duration-hours 6 \
  --sample-seconds 30 \
  --seed 20260903 \
  --output var/observations-6h.csv \
  --truth-output var/truth-6h.jsonl
```

| Metric | Result |
| --- | ---: |
| Frames | 720 |
| Published observations | 315,141 |
| Wall time | 8.08 s |
| Maximum resident set size | 79,937,536 bytes |
| Observation file size | approximately 31 MiB |
| Truth file size | approximately 13 MiB |
| Observation SHA-256 | `ea794857e9d0fc210000f907fe31f9a28aa2d44b9c6208b1917c6dcd6aba06bd` |
| Truth SHA-256 | `fbf71e4edc6d3968cc729a936305eccf0db50737b4322f677677e3c447ddd449` |

The digests printed by the application matched independent `shasum -a 256`
results. Generated files remain ignored and are not distributed in Git.

## Interpretation

This evidence verifies software behavior and reproducibility on one host. It
does not validate refinery fidelity, parameter calibration, fault prevalence,
or cross-platform bitwise identity. Linux CI, longer profiles, OPC UA
Historical Access continuation, and empirical calibration remain future
release gates.

## 0.3.0 contract checkpoint

Date: 2026-09-03

The SIM-10 checkpoint added nine bundled JSON Schema v1 documents and four
executable runtime profiles. Twenty-three local tests passed, including strict
manifest compatibility failures, schema validation, timezone and interval
rejection, byte-identical replay in different directories, independent OPC UA
source/server timestamp verification, and the existing 500-node client test.
Ruff checks passed for every changed Python file.

At SIM-10 closure, the canonical benchmark-manifest digest was
`sha256:f490e3e5b24abfb901ff2c89eadf3e9a90069b249ac26456ba813bcc7088d6ea`.
For the regression fixture (seed 42, `2026-01-01T00:00:00+00:00`, 60 seconds,
one-second integration, 30-second frames, six-hour scenario cycle), the
path-independent dataset-manifest digest is
`sha256:9ac42aa26077f79bab3f816703470ac48ab534e3aad15d68d176eb6966038296`.

The source distribution and wheel built successfully. Inspection of the wheel
confirmed all four profile resources and all nine schema resources. A CLI smoke
run exported and revalidated the benchmark manifest, then generated and linked
observation, hidden-truth, and dataset-manifest artifacts.

This is development evidence, not a published release record. Cross-platform
digest confirmation, long profile runs, Historian continuation/restart stress,
and scientific calibration remain assigned to later checkpoints.

## 0.3.0 dynamic-model checkpoint

Date: 2026-09-03

SIM-20 added a tenth schema for resolved loop-model definitions and embedded all
50 definitions in the benchmark manifest. The model now enforces declared
coupling delays, signed gains, actuator travel limits, bounded integral state,
manual tracking, reversal-aware backlash, split-range crossover, protective
selection, and distinct AUTO/CAS/REMOTE structure policies. Hidden truth adds
normalized balance residual, integral, actuator-stuck, and sensor-bias states.

Thirty-four tests passed. New deterministic checks cover model completeness,
pre-runtime rejection, all ten control-structure modes, actuator and balance
invariants, every loop's positive step response, coupling delay and direction,
bumpless manual recovery, stiction, saturation, and sensor-drift recovery. Ruff checks passed for every changed
Python file. Source and wheel builds passed; wheel inspection confirmed four
profiles and ten schemas, and the installed-wheel CLI manifest/dataset smoke
passed.

Canonical regression identities at SIM-20 closure:

- benchmark manifest:
  `sha256:a335cc7a8dc859bdc7d3e9997bd14babe48f7f9ec8a195036d6320cded849918`;
- 60-second seed-42 dataset fixture:
  `sha256:e49323dfb7bc6bbb97425c023c5b6c6f00f1cf99485916fadb650a73bb2ab85a`.

The balance is deliberately normalized and grey-box; it is not evidence of
engineering-unit mass or energy closure. Parameter calibration, independent
process review, long runs, and scenario overlaps remain SIM-40 work.

## 0.3.0 OPC UA and historian checkpoint

Date: 2026-09-03

SIM-30 normalized SQLite timestamps to UTC, bounded every Historical Access
page, closed inclusive/reverse/empty range behavior, and added profile-based
retention. Observation writes and a versioned simulator checkpoint now commit
atomically. Compatible restart deterministically replays to that checkpoint
without rewriting the bootstrap interval; incompatible configuration and
interrupted bootstrap state fail before endpoint startup.

The complete local suite passed with 43 tests. The independent-client test
forced two-value continuation pages across a 600-second interval and verified
ordered and reverse reads, exact bounds, empty ranges, 30/60-second mixed
cadences, Good/Uncertain/Bad recovery, missing gap rows, distinct source/server
timestamps, restart row identity, and mismatch rejection. Direct storage tests
also cover retention, generator inputs, checkpoint round-trip, and timestamp and
status preservation. Changed-file Ruff checks and source/wheel builds passed;
the wheel contains four profiles and eleven schemas.

The same ten OPC UA/historian tests passed in Linux containers on:

- ARM64, Python 3.12;
- ARM64, Python 3.13;
- AMD64 emulation, Python 3.13.

This establishes local cross-version and cross-architecture interoperability,
but it is not a hosted CI or native AMD64 performance measurement. Long-profile
startup, write throughput, read latency, storage/signal-day, memory, crash
injection, and native AMD64 evidence remain performance/release gates.

## 0.3.0 accelerated scenario qualification

Date: 2026-09-04

SIM-40 now has an executable first-stage qualification for all 20 scenario
families. Numerical scenario parameters are part of the benchmark manifest;
minimum active-window signatures, fixed seed partitions, and full results are
part of a canonical scenario-study manifest. The development, validation, and
held-out partitions contain 15, 5, and 10 complete seeds respectively. Seed 0,
used to calibrate thresholds, is excluded.

The complete local suite passed with 71 tests and changed-file Ruff checks
passed. Two independent 30-seed runs completed with all 30 seeds passing every
scenario rule and no failed runs. Their outputs were identical byte for byte
and validated against the 14 bundled schemas.

Reproducibility identities (benchmark 0.3.0; see the note below for 0.4.0):

- current benchmark manifest:
  `sha256:90ba4be9f5c743c434ae75be3d90cfb53bd925a795f4a7c890bd62ee23afc673`;
- current 60-second seed-42 dataset fixture:
  `sha256:1ce7dc41c863a8914cc05baab4b80e257202442e5adca5383be82408b01dee8c`;
- embedded 30-seed study digest:
  `sha256:f14d648164a49da79e791a4f683010fac729bc2898b1ce39f6fa6e6bd0914601`;
- complete study file SHA-256:
  `2e28c8f24db3b95e47ed0842b8f0c2f882b7ebd4f5eb219f6dbd530f03b0303f`.

**Benchmark 0.4.0 (PlantCraft Simulator rename).** Only `namespace_uri` and `benchmark_version` changed;
the catalog digest, model and scenario parameterization are those above. The benchmark manifest
is `sha256:37705f1f809d0397404ca8ee8003a7d450423ae647f18b01d0a0012fce864d6b` and the 60-second
seed-42 dataset fixture `sha256:889c895951e3bd392f84fb927483eab828cda51613cfd1fbb07b7075e5498ae1`
(both pinned in `tests/test_contracts.py`). The 30-seed study and isolation-matrix digests embed
`benchmark_version`, so they must be regenerated for 0.4.0; that run is listed in
`docs/gaps.md`.

Before the held-out run, tuning effects were restricted to active windows,
propagated oscillation was routed through the declared delayed coupling,
irregular cadence gained deterministic missing slots, saturation demand was
made binding, and controller-output variation was defined temporally. The
detailed method and aggregate signatures are in
[Scenario validation](scenario-validation.md).

The manifest now includes 95% Student t intervals for every active-window
metric and a development-fit nearest-centroid comparison across PV/SP,
PV/SP/OP/MVFB/MODE, and quality/timestamp-enriched views. All features come
only from published observations. Held-out macro-F1 was 0.9333, 0.9333, and
0.9333 respectively. These are observation-window baselines, not online
per-frame detector claims.

The binary per-frame reference reached held-out macro-F1 0.5479 with PV/SP,
0.5663 with controller/actuator/mode, 0.5804 with quality/timestamps, and 0.6131
with directly connected graph observations. The graph view increased false
alarms from 148.16 to 169.43 per loop-day, so it is not an operational detector.
The study deliberately excludes graph features from scenario-name summary
classification because fixed topology would confound loop identity with the
scenario label.

Explicit scenario selection now distinguishes integrated, isolated, and
selected-overlap studies. Thirty-seed controls passed for isolated
`sensor.noise` and for the deliberate `process.disturbance` plus `sensor.noise`
overlap. Unselected fault injections and load changes remained inactive. The
unchanged sensor-noise interval across those two controls supports absence of
spurious interference for that pair, not graph-mediated causal interaction.

A canonical isolation matrix now runs every scenario independently over all 30
fixed seeds. The first matrix preserved a reproducible negative result:
571/600 passed, with 29 `process.interaction` failures caused by an unexcited
source. After adding a declared shared driver to real upstream loops, without
lowering the preregistered threshold, the corrected matrix passed 600/600 and
its replay was byte-identical. Its embedded digest is
`sha256:1bc50e7881fef3c097436bd08646603d0e01a4b280a0ba0eded7ab00a39650a3`
and complete file SHA-256 is
`5b45c23c11c1498a6159d7864627bbce1ffd7c9fbbb67d16594907b0b67c7305`.

A 30-seed connected `normal.load_change + process.interaction` control passed
and exercised the declared FIC-301 to FIC-403 edge. The first exact six-hour,
five-second-cadence paper-profile pass then evaluated 129,600 frames and
produced a schema-valid negative result. It exposed scheduled-cadence
denominator bias, now corrected and regression-tested, plus a remaining
duration-scale mismatch in the `control.sluggish_tuning` mean signature. The
scenario now contains an explicit setpoint excitation and uses a fixed
1,800-second initial-response error while retaining the 0.003 cutoff. Seed 1
passed the exact six-hour, one-second integration, five-second publication
configuration with initial-response error 0.0393718; the exact 30-seed
confirmation is recorded below. This canonical parameter change
also means the previously listed study and isolation digests are historical,
not qualification of the current benchmark. The negative artifact and its
limitations are recorded in [Scenario validation](scenario-validation.md).

The long-run hot path now caches each loop's immutable activation offset and
reuses the preceding active state instead of hashing and recomputing it on
every integration step. A controlled 600-second profile fell from 0.819 to
0.615 seconds (about 25%) while the canonical one-hour evaluation digest and
all behavioral tests remained unchanged.

The revised benchmark then passed a 30-seed integrated qualification and its
byte-identical replay. The embedded digest is
`sha256:6a851b2fa6462c1c495ba55c94611c73b931c4de83f2303ddab81673bf7d6f8a`
and file SHA-256 is
`177a2831e7cc4a10d4ad67d6a3b74898e8fde409f6707226418ac530184425c3`.
Its regenerated isolation matrix passed 600/600 runs with embedded digest
`sha256:35d163d1234e082a42ac5ce4ae505114fe7d56c472ce20190a7b96dae28a48cc`
and file SHA-256
`0a2700a5a07186dc4063a266c65b2efdcbae6fb9ad098a7da747dd64f360996f`.

The revised exact paper-cycle study also passed 30/30 seeds and 129,600 frames
with no failed runs. It is schema-valid, has embedded digest
`sha256:61b02a3075171985419c1006a96d75c33c961620dbfb03912876f90f0b0efaf5`,
and file SHA-256
`3e275814ba8b8d963ebb426ae8db1d93cee4df41f1a6ed6b055374372543b3a6`.
Held-out observation-window macro-F1 remained 0.9283 for PV/SP and 0.9333 for
both richer views.

Three additional direct-edge overlap controls were selected before execution
and all passed 30/30 seeds: FIC-901 to LIC-902, TIC-303 to TIC-304, and
PIC-1001 to LIC-1002. Their embedded digests are respectively
`sha256:693445eea7ff88df1654e64c573937a377921dbde4a5a6e10959ad0448427cfd`,
`sha256:7936c1604fa11e2c6c181c8a32ba2a36dc9260a116ff36894e0f14230319e7a7`,
and `sha256:938f71d2397f7bb6748d631b2f6794875e3169b7213033bc099660d04f33e40b`.
These results establish coexistence on declared paths, not causal
localization.

The observation-only frame baseline now includes three-frame-persistent onset
detection and candidate-loop ranking without loop or scenario identity as a
feature. On held-out seeds, the graph view detected 68.96% of 480 onsets with
176-second mean and 810-second p95 delay. Localization MAP was 0.6253,
precision@5 was 0.6513, and recall@5 was 0.1443. The byte-identical study and
replay have embedded digest
`sha256:16c11788ddb44f4ac5e36795c8827ff1a1929b15f5b95e11257ea128795c0229`
and file SHA-256
`979e0a27301d7fca47c809d225ac59e134f5aed53ac90ecc94623fc9b23bfb28`.

A causal 60-second last-value regularization was compared with native
irregular observations while retaining quality, timestamp, and imputation
evidence. Held-out macro-F1 improved only from 0.58058 to 0.58165 and onset
detection from 49.38% to 51.46%; false alarms worsened from 150.48 to 151.83
per loop-day and localization MAP was effectively unchanged. The result is
retained as a mixed ablation, with byte-identical digest
`sha256:c84fb45efaee11b8ab013cdeb5f04efe638a2995d7d5410dde8258f9ca11bb08`
and file SHA-256
`97bfc71ae39fb1e9c322c9ae97f0f0e72e0e1950eb631cb63fdd03ea31216125`.

This is an accelerated one-hour-cycle qualification, not the final paper
study. SIM-40 remains open for independent causal and process-engineering
review.

## 0.3.1 bounded cold-bootstrap correction

Date: 2026-09-04

The first consumer integration measurement rejected package 0.3.0 for the
24-hour operational profile before deployment. The historian advanced only
343 five-second frames after several minutes and projected more than one hour
to readiness. Profiling located the dominant cost in a process-delay deque
retained for the complete six-hour scenario cycle and scanned from its oldest
entry for every coupled-loop integration step. Per-node retention deletes were
also repeated during every already bounded bootstrap batch.

Package 0.3.1 retains the exact 0.3.0 benchmark, model, schema, catalog,
manifest, and checkpoint identities. It bounds each source loop's delay deque
by the maximum declared outgoing coupling delay, which cannot change any value
available to the model, and defers redundant retention deletes only while
filling a new empty 24-hour historian. Steady-state writes still enforce
retention on every committed frame. Existing scenario-signature, isolation,
and experiment tests passed unchanged.

The corrected full profile generated a complete 86,400-second checkpoint for
all 500 nodes in 47.781 seconds on the Apple Silicon development host. The
Linux container, constrained to 0.75 CPU and 384 MiB as in the consumer
composition, announced its ready 500-node endpoint after approximately 75
seconds and passed its OPC UA healthcheck by 90 seconds. The resulting SQLite
historian was approximately 232 MiB. These are development-host measurements,
not universal latency or storage guarantees; the consumer health start period
must retain margin and the exact deployed image is rechecked before cutover.

## 0.3.2 restart wall-clock correction

Date: 2026-09-04

Consumer integration exposed a restart defect in 0.3.1: a persisted simulator
continued from its checkpoint timestamp at real-time speed, so recent
acquisition windows remained empty for the full duration of an outage even
though the OPC UA server-state healthcheck passed.

Package 0.3.2 advances compatible deterministic state across elapsed wall-clock
downtime before serving, commits one current historian frame, and deliberately
does not synthesize intermediate observations. Automated coverage verifies the
exact resumed timestamp, the retained outage gap, prompt live publication, and
healthcheck rejection of stale or future source timestamps. The full automated
suite passes with the unchanged 0.3.0 benchmark and checkpoint identities.

## 0.3.3 indexed steady-state retention correction

Date: 2026-09-04

Deployment of 0.3.2 against the retained 24-hour historian proved that its
per-node retention predicate scanned unindexed tables. The deterministic
checkpoint reached wall time, but the first steady-state transaction remained
busy long enough for current values to become stale; the new freshness
healthcheck correctly rejected the endpoint.

Package 0.3.3 creates one source-timestamp index per historian node, including
when opening an existing compatible volume. Query-plan coverage proves that the
retention predicate uses the index. Restart-gap, current-publication, historian,
scenario, and complete package tests pass with unchanged benchmark and
checkpoint identities.

## 0.3.4 scenario-independent process liveness

Date: 2026-09-04

Extended consumer observation found that the representative Signal selected by
the 0.3.2 healthcheck could legitimately become stale during a declared data
unavailability scenario while the simulator checkpoint and other runtime work
continued advancing. Package 0.3.4 uses a dedicated, non-historized heartbeat
outside the 500-Signal catalog. Automated coverage verifies that its source
timestamp advances in real time; freshness and future-skew checks remain
unchanged. This separates simulator-process liveness from intentional Signal
quality and availability behavior.
