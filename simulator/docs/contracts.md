# Versioned contracts and runtime profiles

The public benchmark surface is closed and versioned independently from Python
implementation details. Version 1 schemas are bundled under
`src/simcraft/schemas/v1`; unknown fields, missing fields,
invalid references, duplicate identities, and incompatible schema identifiers
are rejected before generation or server startup.

## Benchmark manifest

`benchmark-manifest/v1` is the machine-readable identity of one benchmark
release. It contains the benchmark version, namespace URI, catalog digest,
complete loop/signal/scenario definitions, resolved loop-model parameters,
directed coupling graph, and exact runtime profiles. Export and validate it with:

```bash
simcraft export-manifest --output benchmark-manifest.json
simcraft validate-manifest benchmark-manifest.json
```

Consumers that pin a release should also pass its expected prefixed catalog
digest to `validate-manifest --expected-catalog-digest`. A changed schema
identifier or benchmark major version is incompatible. A changed catalog or
manifest digest is a different benchmark instance and must not be mixed into an
existing experiment without an explicit decision.

## Dataset artifacts

Generation produces three deliberately separate artifacts:

- observation CSV using `observation/v1`;
- hidden-truth JSONL using `truth-frame/v1`;
- canonical `dataset-manifest/v1` linking both files by prefixed SHA-256.

The dataset manifest records the benchmark-manifest and catalog digests, seed,
UTC interval, integration step, observation frame, scenario cycle, frame and
observation counts, artifact names, and artifact digests. Artifact paths are
basenames so identical runs in different directories have identical manifest
bytes and digest. JSON documents use UTF-8, sorted keys, compact separators,
finite numbers only, and a final newline.

Hidden truth is a scoring artifact. It must not be mounted in the OPC UA address
space or supplied to a method at inference time.

`server-checkpoint/v1` is internal persistent provenance for Historical Access
continuity. It contains no secret and no hidden scenario truth. It binds an
existing historian to the exact benchmark and runtime identity needed for
deterministic replay; incompatible or incomplete state is rejected.

## Time semantics

All public timestamps are ISO 8601 values with an explicit UTC offset. Naive
datetimes are rejected; they are never interpreted using the host timezone.
Simulation time advances from `start_at` using a fixed integration step.
Observation frames and total duration must be exact integer multiples of their
respective lower-level interval, preventing silent partial or rounded steps.

`source_timestamp` is when the synthetic source says a value was measured.
`server_timestamp` is the containing publication frame. They are normally
equal. The irregular-cadence scenario shifts only the source timestamp, making
transport timing behavior observable without altering physical time or hidden
truth.

## Runtime profiles

The bundled profiles are versioned inputs, not informal recommendations:

| Profile | Duration | History | Integration | Frame | Scenario cycle | History response limit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| smoke | 15 min | 15 min | 1 s | 30 s | 1 h | 1,000/node |
| development | 6 h | 6 h | 1 s | 30 s | 6 h | 10,000/node |
| paper | 72 h | 24 h | 1 s | 5 s | 6 h | 20,000/node |
| stress | 30 d | 24 h | 5 s | 30 s | 6 h | 50,000/node |

List the exact installed definitions with `simcraft profiles`.
Both `generate` and `serve` accept `--profile`; explicit interval flags override
individual profile values and are validated against the same invariants.

Scenario numerical parameters and their study rules are versioned separately.
The benchmark manifest embeds all 20 parameterizations, while the scenario
study schema closes the partitions, results, and reproducibility identity of an
executed qualification. See [Scenario validation](scenario-validation.md).

## Reproducibility identity

Within one recorded execution environment, a fixed benchmark manifest, release,
seed, start time, duration, integration step, observation frame, and scenario
cycle produces identical observation bytes, truth bytes, artifact digests,
dataset-manifest bytes, and dataset-manifest digest. File location is
intentionally excluded from that identity; artifact filenames remain included.
System math-library implementations may differ in their last floating-point
bits across operating systems. Cross-platform qualification therefore requires
the same rules and tolerances to pass, while exact artifact comparison requires
the same recorded environment.
