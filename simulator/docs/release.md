# Release and compatibility

## Version status

| Version | Status | Python | Operating-system evidence | Contract behavior |
| --- | --- | --- | --- | --- |
| 0.2.0 | Previous release | 3.12+ | Linux container and development hosts | Original 50-loop, 500-signal public benchmark |
| 0.3.0 | Superseded alpha release | 3.12, 3.13 | CI: Linux 3.12/3.13, macOS 3.13, Windows 3.13 | Closed v1 manifests, profiles, scenario studies, bounded historian continuity; cold bootstrap is not operationally qualified |
| 0.3.1 | Superseded alpha release | 3.12, 3.13 | CI plus measured 24-hour cold bootstrap | Same 0.3.0 benchmark and checkpoint identity with bounded bootstrap performance correction |
| 0.3.2 | Superseded alpha release | 3.12, 3.13 | CI plus restart-gap and timestamp-freshness coverage | Same 0.3.0 benchmark and checkpoint identity with wall-clock resume correction |
| 0.3.3 | Superseded alpha release | 3.12, 3.13 | CI plus indexed-retention integration coverage | Same 0.3.0 benchmark and checkpoint identity with bounded steady-state retention |
| 0.3.4 | Superseded alpha release | 3.12, 3.13 | CI plus scenario-independent heartbeat coverage | Same 0.3.0 benchmark and checkpoint identity with explicit process liveness |
| 0.3.5 | Superseded alpha release | 3.12, 3.13 | CI plus off-lattice checkpoint recovery coverage | Same 0.3.0 benchmark and checkpoint identity with sampling-lattice repair |
| 0.3.6 | Superseded alpha release | 3.12, 3.13 | Local container smoke and vulnerability scan; release CI exposed a wall-clock-sensitive Windows test | Same 0.3.0 benchmark and checkpoint identity with runtime-image hardening |
| 0.3.7 | Superseded alpha release | 3.12, 3.13 | Cross-platform CI with deterministic restart interoperability test | Same 0.3.0 benchmark and checkpoint identity with runtime-image hardening |
| 0.4.0 | Current alpha release (PlantCraft Simulator) | 3.12, 3.13 | CI as 0.3.7 plus the loop portfolio round trip and a read-only container smoke | Benchmark identity 0.4.0: only `namespace_uri` and `benchmark_version` changed; catalog, model and NodeIds as in 0.3.0 |

The table describes tested configurations, not a promise that every Python or
operating-system combination works. The container image is the reference
runtime. `CITATION.cff` identifies the current software release; an archival
DOI remains absent until an exact archive is created.

## Compatibility rules

The Python package version and benchmark identity are related but distinct.
A consumer must pin all of the following:

1. package or container release and artifact digest;
2. benchmark-manifest digest and catalog digest;
3. schema identifiers;
4. runtime profile or complete explicit timing parameters;
5. seed and explicit UTC start time for reproducible datasets.

A schema-major change is incompatible. A changed catalog, resolved model,
scenario parameterization, or runtime profile creates a new benchmark identity
even when the schema remains compatible. Do not append observations from
different identities to one experiment or historian.

## Migration from 0.4.x to 0.5.0 (simcraft)

The platform took the name PlantCraft (2026-10-27), so the Simulator's machine name is now
`simcraft`; what people see is still "PlantCraft Simulator".

- **Names.** Install `simcraft`, import `simcraft` and run `simcraft`; the image is
  `simcraft:<version>` and the suite's compose service is `simcraft`. The `plantcraft` names
  are gone: PlantCraft is the platform.
- **Variables.** `PLANTCRAFT_*` become `SIMCRAFT_*` (for example `SIMCRAFT_HEALTH_ENDPOINT`,
  `SIMCRAFT_HISTORY_DB`).
- **Unchanged on the wire.** The namespace `urn:processcraft:plantcraft`, the endpoint path
  `/plantcraft/`, the NodeIds and the history and state files stay as they were, so sources
  and archives already configured keep reading. In the suite the service also answers to its
  old host name `plantcraft` on the demo network.

## Migration from 0.3.x to 0.4.0 (PlantCraft Simulator)

- **Names.** Install `plantcraft`, import `plantcraft` and run `plantcraft`; the 0.3.x names
  are gone (removed in 0.4.1).
- **Namespace.** Resolve `urn:processcraft:plantcraft` instead of the 0.3.x repository URL.
  NodeIds are unchanged.
- **Benchmark identity.** `benchmark_version` is 0.4.0 and the manifest digest is
  `sha256:37705f1f809d0397404ca8ee8003a7d450423ae647f18b01d0a0012fce864d6b`. A 0.3.x
  manifest, scenario study or isolation matrix does not validate against 0.4.0 schemas; keep it
  as prior evidence, regenerate it with 0.4.0.
- **Historian.** A 0.3.x historian carries a 0.3.0 checkpoint and the old namespace, so 0.4.0
  refuses to start on it (checkpoint mismatch) rather than adopt it. Keep it as a prior artifact
  and give 0.4.0 a new `--history-db`, or pass `--reset` if it is disposable.
- **Variables.** `PROCESS_SIMULATOR_ENDPOINT` and `PROCESS_SIMULATOR_MAX_SAMPLE_AGE_SECONDS`
  become `PLANTCRAFT_HEALTH_ENDPOINT` and `PLANTCRAFT_MAX_SAMPLE_AGE_SECONDS` (the old names
  were read as well until 2026-10-23). The image runs as uid 10004 with `/data` owned by it; a
  volume written by the 0.3.x image (user `simulator`) needs `chown -R 10004:10004`.
- **Image.** The default command is now `plantcraft loops serve`; run the benchmark with
  `plantcraft serve --profile smoke --history-db /data/history.sqlite3`.

## Migration from 0.2.0 to 0.3.0

0.3.0 adds versioned public contracts and a versioned server checkpoint. A
0.2.0 SQLite historian has no compatible checkpoint and must not be silently
adopted. Preserve it as an immutable prior artifact or start a new 0.3.0
historian with an explicit path. `--reset` is appropriate only when the chosen
development historian is intentionally disposable.

Consumers should export and validate the 0.3.0 benchmark manifest before
mapping NodeIds. Stable NodeIds remain catalog-owned, but clients must still
resolve the runtime namespace index by namespace URI. Dataset consumers should
adopt the observation, truth-frame, and dataset-manifest v1 schemas and keep
truth separate from inference inputs.

Package release 0.3.1 retains the benchmark-manifest, catalog, schema, and
checkpoint identities of 0.3.0. Its only runtime change removes redundant
retention work while filling an initially empty, already time-bounded
historian. A 0.3.0 checkpoint is therefore compatible with 0.3.1, although a
consumer should prefer a new 0.3.1 volume when replacing an unqualified or
interrupted 0.3.0 cold bootstrap.

Package release 0.3.2 remains checkpoint-compatible with 0.3.0 and 0.3.1. On
restart it advances deterministic state across real downtime, records one
current observation frame, and preserves the outage as a historical gap. Its
healthcheck additionally requires a fresh Signal source timestamp.

Package release 0.3.3 adds source-timestamp indexes to new and compatible
existing historian tables. It preserves the 0.3.2 restart and health semantics
while bounding steady-state retention work for the 24-hour profile.

Package release 0.3.4 adds one technical heartbeat outside the scientific
Signal catalog. This does not change the 500 Signals, benchmark identity, or
historian contract; it prevents deliberate Signal gaps from being interpreted
as process failure by the container healthcheck.

Package release 0.3.5 repairs compatible checkpoints whose elapsed time was
written outside the configured sampling lattice by an earlier wall-clock
resume. It advances deterministic state to the next valid sample boundary,
after which normal Signal cadences remain reachable. The benchmark, schema,
catalog, and checkpoint identities are unchanged.

Package release 0.3.6 applies available Debian updates when building
the runtime image and removes Python packaging tools after installation. These
container-only changes preserve the benchmark, schema, catalog, and checkpoint
identities.

Package release 0.3.7 fixes only the release test harness: the immediate
restart interoperability test now injects a fixed wall clock rather than
depending on runner speed. Runtime behavior and all scientific identities are
unchanged from 0.3.6.

## Candidate build and smoke procedure

From a clean checkout and supported Python environment:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[test]'
python -m pytest
simcraft validate-catalog
simcraft export-manifest --output var/benchmark-manifest.json
simcraft validate-manifest var/benchmark-manifest.json
simcraft generate --profile smoke --seed 20260903 \
  --start-at 2026-09-03T00:00:00+00:00 \
  --output var/smoke.csv --truth-output var/smoke-truth.jsonl
python -m build
```

Install the wheel into a second clean environment, repeat manifest validation
and smoke generation, then start the server and run an independent OPC UA read
of all 500 nodes plus a paged Historical Access query. Build the container from
the same commit and repeat the interoperability test against its loopback port.
The container default is the bounded `smoke` profile. Longer profiles must be
selected explicitly and their cold historian-bootstrap time recorded.

## Publication gate

A software alpha release is publishable after the build, test, identity,
interoperability, security, and provenance items below are recorded. An
archival or publication-grade scientific release additionally requires the
independent scientific-review disposition:

- complete CI matrix and local test result;
- exact Git commit and clean source tree;
- wheel, source distribution, and container digests;
- generated benchmark manifest and digest;
- dependency SBOMs and vulnerability-scan results for package and image;
- installed-wheel and container interoperability evidence;
- scenario qualification, isolation matrix, and replay;
- independent scientific-review disposition before archival or
  publication-grade claims;
- signed tag or equivalent provenance attestation;
- release notes and rollback/migration instructions.

Zenodo or an equivalent archive comes after the immutable release exists. Add
its DOI to `CITATION.cff` only after the archive resolves to the exact release.
Generated runtime history, credentials, private endpoints, and proprietary
inputs are never release artifacts.
