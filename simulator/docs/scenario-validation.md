# Scenario validation record

Date: 2026-09-04
Target: 0.3.0 alpha release
Status: accelerated integrated and isolation qualification; not the final paper study

## Method

The executable study evaluates every declared scenario over one complete,
one-hour deterministic cycle. It uses fixed seed partitions: 1–15 for
development, 16–20 for validation, and 21–30 as held-out tests. Seed 0 was used
to calibrate the minimum signature thresholds and is excluded from all three
partitions. Rules, scenario parameters, partitions, and results are embedded in
the canonical output manifest.

```bash
simcraft validate-scenarios \
  --jobs 6 \
  --output var/scenario-study-30-seeds.json
```

The study uses 30-second publication frames and one-second integration. It
checks scenario observability and minimum physical, control, actuator, sensor,
operations, and transport signatures; it does not score a detector.

## Result

All 30 seeds passed all 20 preregistered scenario rules, with no failed runs.
The active-window means below summarize selected diagnostic quantities across
the 30 seeds. Values are normalized except observed fraction.

| Scenario | Observed | PV range | Sensor error | Control error |
| --- | ---: | ---: | ---: | ---: |
| `actuator.saturation` | 1.000 | 0.1493 | 0.0018 | 0.1308 |
| `control.aggressive_tuning` | 1.000 | 0.2654 | 0.0015 | 0.0077 |
| `control.oscillation` | 1.000 | 0.1045 | 0.0014 | 0.0202 |
| `control.propagated_oscillation` | 1.000 | 0.0172 | 0.0012 | 0.0037 |
| `control.sluggish_tuning` | 1.000 | 0.0103 | 0.0012 | 0.0053 |
| `data.bad_quality` | 1.000 | 0.0098 | 0.0016 | 0.0016 |
| `data.communication_loss` | 0.000 | 0.0524 | 0.0016 | 0.0024 |
| `data.gap` | 0.000 | 0.0220 | 0.0016 | 0.0095 |
| `data.irregular_cadence` | 0.776 | 0.0143 | 0.0023 | 0.0025 |
| `normal.load_change` | 1.000 | 0.2246 | 0.0020 | 0.0156 |
| `normal.steady` | 1.000 | 0.2870 | 0.0017 | 0.0041 |
| `operations.manual` | 1.000 | 0.0967 | 0.0011 | 0.0135 |
| `operations.setpoint_activity` | 1.000 | 0.3532 | 0.0018 | 0.0243 |
| `process.disturbance` | 1.000 | 0.0551 | 0.0014 | 0.0103 |
| `process.interaction` | 1.000 | 0.0229 | 0.0013 | 0.0038 |
| `sensor.drift` | 1.000 | 0.0311 | 0.0105 | 0.0129 |
| `sensor.frozen` | 1.000 | 0.0000 | 0.0038 | 0.0023 |
| `sensor.noise` | 1.000 | 0.2300 | 0.0336 | 0.0357 |
| `valve.backlash` | 1.000 | 0.0064 | 0.0010 | 0.0020 |
| `valve.stiction` | 1.000 | 0.0311 | 0.0015 | 0.0021 |

Reproducibility identities:

- embedded study digest:
  `sha256:f14d648164a49da79e791a4f683010fac729bc2898b1ce39f6fa6e6bd0914601`;
- complete file SHA-256:
  `2e28c8f24db3b95e47ed0842b8f0c2f882b7ebd4f5eb219f6dbd530f03b0303f`.

An independent replay in the same recorded execution environment produced the
same embedded digest and an identical file. The complete manifest validates
against the bundled scenario-study schema. Cross-platform qualification uses
the same physical signature rules and tolerances; system math libraries may
produce different last-bit values and therefore different whole-file digests.

## Corrections closed before the held-out run

- aggressive and sluggish controller tuning now applies only inside its active
  scenario window;
- propagated oscillation reaches TIC-702 through the declared delayed coupling
  from FIC-701 instead of being injected locally;
- irregular cadence now includes deterministic missing publication slots as
  well as source-timestamp jitter;
- actuator saturation receives enough setpoint demand for the declared limit
  to bind;
- controller-output variation is measured across time, separately from the
  command-to-actuator gap.
- `process.interaction` excites its declared upstream loops with a shared,
  published 0.12-amplitude, 720-second-period driver before the graph delay.

The benchmark manifest freezes numerical parameterizations for all 20
scenarios, and the executable study freezes their minimum signatures.

## Confidence intervals and observation-window baselines

The study reports a two-sided 95% Student t interval across the 30 independent
seed summaries for every active-window metric. Examples include sensor-error
mean 0.033611 with interval [0.032910, 0.034312] for `sensor.noise`, and
control-error mean 0.130051 with interval [0.129996, 0.130106] for
`actuator.saturation`.

A standardized nearest-centroid reference is fitted only on development seeds.
Its features are calculated exclusively from published OPC UA observations;
hidden process, sensor, actuator, and truth states are excluded. It compares
cumulative observation views on validation and held-out seeds:

| View | Validation accuracy | Validation macro-F1 | Held-out accuracy | Held-out macro-F1 |
| --- | ---: | ---: | ---: | ---: |
| PV/SP | 0.940 | 0.9232 | 0.950 | 0.9333 |
| PV/SP/OP/MVFB/MODE | 0.950 | 0.9333 | 0.950 | 0.9333 |
| Above plus quality/timestamps | 0.950 | 0.9333 | 0.950 | 0.9333 |

Availability is explicit, and unavailable numeric features contribute zero.
These are reproducible active-window baselines over observed data, not
deployable per-frame detector scores. Replacing the earlier controlled-state
proxy with observation-only features produced the same scores, showing that
hidden state had not inflated the result. The lack of aggregate improvement
from quality/timestamp features is retained as a result, not optimized away.

## Per-frame and graph baseline

A second development-fit nearest-centroid reference classifies each primary-loop
publication frame as active or inactive. Frame samples exist only in memory
during scoring and are removed from the canonical manifest results. The graph
view adds observed PV availability and variation from directly connected
upstream and downstream loops.

| View | Held-out accuracy | Held-out macro-F1 | False alarms/loop-day |
| --- | ---: | ---: | ---: |
| PV/SP | 0.5844 | 0.5479 | 210.05 |
| PV/SP/OP/MVFB/MODE | 0.6017 | 0.5663 | 151.35 |
| Above plus quality/timestamps | 0.6124 | 0.5804 | 148.16 |
| Above plus plant graph | 0.6363 | 0.6131 | 169.43 |

The graph improves macro-F1 but increases false alarms from 148.16 to 169.43
relative to the quality/timestamp view. These rates are far too high for an
operational alarm system and are retained as a benchmark floor. Graph features are excluded from
the scenario-name window classifier because fixed loop topology would act as a
loop-identity confounder and produce a misleading perfect score.

The per-frame baseline now also reports temporal detection and candidate-loop
localization. An onset requires three consecutive active predictions. At each
timestamp, all candidate loops are ranked by distance to the inactive centroid
minus distance to the active centroid; loop and scenario identities are not
features and are used only to break exact score ties.

| View | Held-out onset detection | Mean delay | P95 delay | Localization MAP | Precision@5 | Recall@5 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| PV/SP | 0.6083 | 128 s | 360 s | 0.5533 | 0.5213 | 0.0698 |
| PV/SP/OP/MVFB/MODE | 0.5125 | 90 s | 270 s | 0.5626 | 0.5453 | 0.0798 |
| Above plus quality/timestamps | 0.4938 | 91 s | 270 s | 0.5646 | 0.5492 | 0.0804 |
| Above plus plant graph | 0.6896 | 176 s | 810 s | 0.6253 | 0.6513 | 0.1443 |

The graph view detects more of the 480 held-out onsets and ranks affected loops
better, but does so with longer tail delay and 172.24 false alarms per loop-day.
This is a reproducible research baseline, not an operational detector. The
canonical study and independent replay are byte-identical, with embedded digest
`sha256:16c11788ddb44f4ac5e36795c8827ff1a1929b15f5b95e11257ea128795c0229`
and file SHA-256
`979e0a27301d7fca47c809d225ac59e134f5aed53ac90ecc94623fc9b23bfb28`.

The irregular-observation ablation compares the native enriched view with a
causal regular grid. The last observed value is carried forward for at most 60
seconds; quality and timestamps remain native, and `imputed_fraction` exposes
every filled channel. Long data gaps are not filled. On held-out seeds,
regularization changed macro-F1 from 0.58058 to 0.58165 and onset detection
from 49.38% to 51.46%, while false alarms increased from 150.48 to 151.83 per
loop-day. Localization MAP changed only from 0.56464 to 0.56473. This mixed,
small effect does not justify claiming that regularization is superior. The
study and replay are byte-identical, with embedded digest
`sha256:c84fb45efaee11b8ab013cdeb5f04efe638a2995d7d5410dde8258f9ca11bb08`
and file SHA-256
`97bfc71ae39fb1e9c322c9ae97f0f0e72e0e1950eb631cb63fdd03ea31216125`.

## Scenario isolation and deliberate overlap controls

The engine now accepts an explicit scenario allowlist. An empty or unknown
selection fails before simulation, and unselected fault layers plus the global
load change remain inactive. The CLI uses one `--scenario` for isolation and
repeated flags for a deliberate plant-wide overlap; every result records its
mode and exact selection.

Before the next connected-overlap executions, three direct-edge controls were
selected without inspecting their outcomes:

| Selection | Declared path | Signatures required |
| --- | --- | --- |
| `operations.setpoint_activity + process.interaction` | FIC-901 to LIC-902, wastewater load to quality | setpoint range and interaction control error |
| `control.sluggish_tuning + control.oscillation` | TIC-303 to TIC-304, within hydrotreater | fixed-window control error and PV range |
| `actuator.saturation + data.gap` | PIC-1001 to LIC-1002, flare load to knockout drum | capacity fraction and low observed fraction |

Each control must pass both existing preregistered rules over all 30 fixed
seeds. Passing establishes coexistence on a declared directed path; it does not
by itself identify the upstream cause from downstream observations.

All three controls passed 30/30 seeds with schema-valid manifests:

| Selection | Embedded digest | File SHA-256 |
| --- | --- | --- |
| `operations.setpoint_activity + process.interaction` | `sha256:693445eea7ff88df1654e64c573937a377921dbde4a5a6e10959ad0448427cfd` | `1999060d6b6e6033a457b0145eca4833a66e9b91391f0cfd64a1267b14fcc17f` |
| `control.sluggish_tuning + control.oscillation` | `sha256:7936c1604fa11e2c6c181c8a32ba2a36dc9260a116ff36894e0f14230319e7a7` | `df774bcc2528bc29017255ed119327026448cc4043c791b1903a7566dd0be76d` |
| `actuator.saturation + data.gap` | `sha256:938f71d2397f7bb6748d631b2f6794875e3169b7213033bc099660d04f33e40b` | `3f80f7cf6d3d51e755d60280cc3607ea239429bd24ff792e8c97a76d02a8bca5` |

The first pair retained setpoint range 0.364991 and interaction control error
0.002853. The second retained initial-response error 0.035285 and oscillation
PV range 0.104000. The third retained capacity fraction 0.987013 while the
downstream observed fraction remained 0.0.

Four 30-seed controls passed without failed runs:

| Mode | Selection | Embedded digest | File SHA-256 |
| --- | --- | --- | --- |
| Isolated | `process.interaction` | `sha256:b0161f708fd8d548f59af059add0659ab3bff9b59401b224a8f7199511f5e0d1` | `7dcee1ce816efc0cbf9398f9f6275c028dd4d52b92514cbb6aee0e7cb8dcf1cc` |
| Isolated | `sensor.noise` | `sha256:f0693ef27ef804a9ba7eb0c6c79376d980787cacfc27481d173534bd6d227fc1` | `cad9c190e4c26bbae3c4b0074131fc4720c8dcea5cff9e860f44b2f6d9275fb5` |
| Selected overlap | `process.disturbance`, `sensor.noise` | `sha256:e81498ab1a8d876e6108f5bb7f86a7256d682ae018d496be92130ebdb6c72fe7` | `e159510e2bc8c535a365ddf80a9d6817e2312dabbc2e6bb14fa78f114ee95d25` |
| Connected overlap | `normal.load_change`, `process.interaction` | `sha256:a623f38d3221db0b55fcc3168b7cd8285350d94e5cc92ee5d9d48aa97e2653f7` | `5f8922bd34a475e9f9c993f4e98d36bcd68d72b782c19ff0e3ab0637c0424b3e` |

The isolated sensor-error mean was 0.033611 with 95% interval [0.032910,
0.034312]. It was unchanged in the selected overlap, while the disturbance PV
range mean was 0.055088 [0.054541, 0.055636]. This is evidence that this pair
coexists without spurious interference; it is not evidence of graph-mediated
interaction. The connected control also passed 30/30 and exercises the
declared FIC-301 to FIC-403 path. Its similar interaction signature establishes
coexistence on a connected path, not causal localization.

The first complete isolation matrix was retained as a negative result. It
passed 571/600 runs and failed `process.interaction` in 29/30 seeds because its
gain increase had no independent source excitation. The file was reproduced
byte-for-byte (embedded digest `sha256:2c2e4e85fb85c3abb46466ad8fba5733d54daa830503304d0f92961e7902187b`,
file SHA-256 `54bccf3b0a9762db7e6f37bfa507a0ca1243a2e4e94b5358086232c739ae95a5`).
After adding the declared source driver without changing the rule threshold,
the corrected matrix passed all 600 runs. Its independent replay was also
byte-identical (embedded digest `sha256:1bc50e7881fef3c097436bd08646603d0e01a4b280a0ba0eded7ab00a39650a3`,
file SHA-256 `5b45c23c11c1498a6159d7864627bbce1ffd7c9fbbb67d16594907b0b67c7305`).
The isolated interaction control-error mean was 0.002721 with 95% interval
[0.002684, 0.002757], against the unchanged minimum rule of 0.0015.

## First paper-profile cycle

The first exact high-cadence pass evaluated 30 seeds, a six-hour scenario
cycle, one-second integration, and five-second publication: 129,600 total
frames. Per-frame samples were deliberately not retained; the already
qualified accelerated frame baseline is therefore empty in this manifest.
The schema-valid negative result has embedded digest
`sha256:171583c4acf96a616962185d07493e452896787a099de1327d58cfab93c7c032`
and file SHA-256
`224d1f27bbf4150bb21dcadb48ded9077fd5fcaf8092b39ff0369eebf4dfaa4f`.

It exposed two distinct issues. Frames with no nominally due Signals were
incorrectly counted as missing transport data; the denominator is now
cadence-aware and covered by a high-cadence regression test. Separately,
`control.sluggish_tuning` produced mean control error 0.002823–0.002911 across
seeds, below the unchanged 0.003 rule because a six-hour active window diluted
the transient response. The implementation now matches the declared scenario
description: activation applies a repeatable 0.06 normalized setpoint step,
and the rule measures mean absolute control error over the first fixed 1,800
seconds of the response. This horizon is about 3.75 times the slowest declared
process time constant. The 0.003 cutoff was not lowered. Seed 1 passed this
signature in both one- and six-hour exploratory cycles. It also passed the
exact six-hour, one-second integration, five-second publication configuration:
the initial-response error was 0.0393718 over 4,147 active samples, with
evaluation digest
`sha256:33f65df38a3967c6bb5369c44c0241e401139ae07ab2b5ab1fdc84292848710e`.
The exact 30-seed confirmation is recorded below.

Because the excitation is part of the canonical scenario parameterization,
the benchmark manifest is now
`sha256:90ba4be9f5c743c434ae75be3d90cfb53bd925a795f4a7c890bd62ee23afc673`.
All study and isolation identities above remain reproducible historical
evidence for the preceding parameterization, but they do not qualify this
revised benchmark until regenerated.

## Revised benchmark requalification

The revised one-hour integrated study passed all 20 signatures for all 30
seeds with no failed runs. An independent replay was byte-identical. Its
embedded digest is
`sha256:6a851b2fa6462c1c495ba55c94611c73b931c4de83f2303ddab81673bf7d6f8a`
and file SHA-256 is
`177a2831e7cc4a10d4ad67d6a3b74898e8fde409f6707226418ac530184425c3`.
The sluggish initial-response error mean was 0.0354271 with 95% interval
[0.0353808, 0.0354734].

The revised isolation matrix also passed all 600 scenario-seed runs with no
failures. Every scenario has exactly 30 seeds. Its embedded digest is
`sha256:35d163d1234e082a42ac5ce4ae505114fe7d56c472ce20190a7b96dae28a48cc`
and file SHA-256 is
`0a2700a5a07186dc4063a266c65b2efdcbae6fb9ad098a7da747dd64f360996f`.
In isolation, the sluggish initial-response error mean was 0.0352846 with 95%
interval [0.0352383, 0.0353309].

The revised exact paper-cycle study passed all 30 seeds and all scenario rules:
six-hour cycles, one-second integration, five-second publication, and 129,600
total frames. It is valid against the bundled study schema and intentionally
contains no per-frame baseline. Its embedded digest is
`sha256:61b02a3075171985419c1006a96d75c33c961620dbfb03912876f90f0b0efaf5`
and file SHA-256 is
`3e275814ba8b8d963ebb426ae8db1d93cee4df41f1a6ed6b055374372543b3a6`.
The sluggish initial-response error mean was 0.0397062 with 95% interval
[0.0396804, 0.0397319]. Scheduled-signal availability and bad-quality means
were both 1.0; irregular-cadence uncertain and jitter means were both 0.995178.

## Remaining paper gate

This accelerated study establishes deterministic scenario presence,
reproducibility, confidence intervals, and preliminary summary ablations. It
does not establish refinery fidelity, online per-frame detector performance,
causal identifiability, or publication-grade external validity. SIM-40 remains
open until causal localization and assumptions are independently reviewed by
a process-control specialist.
