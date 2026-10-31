# AGENTS.md: rules for AI agents and contributors

**Read the suite's rules first**: the repository's root `AGENTS.md` (`../AGENTS.md`). The Simulator
lives in `simulator/` of the PlantCraft repository and keeps its own version, image and `make ci`.
This file adds only what is particular to it; "this repository" below means this folder.

PlantCraft is an open-source suite for process engineers. **PlantCraft** is the central app
(users, licences, connections, assets, signals, app launcher); each product is a **separate app**
in its own folder and container: Link, Historian, View, Alarms, Models and the Simulator. Each app brings together what the tools of its category offer
across vendors; it never presents itself as a copy of one vendor's product. Names are always
written `{Function}Craft` in user-facing text; machine names stay lowercase (`simcraft`,
`plantcraft-sdk`). Read this file first, then `docs/STATUS.md`. Code and identifiers are in
English. **This folder is PlantCraft Simulator**, the OPC UA plant simulator; its text is English only
(the benchmark catalog still carries Portuguese descriptions, `docs/gaps.md`).

## 1. Start every session here (5 minutes)

1. `git status`, `git log origin/main..HEAD`, open PRs: finish or park unmerged work before starting new work.
2. Read `docs/STATUS.md`: current focus, next task, blockers, last devlog entries.
3. Read `ROADMAP.md` (readiness per area) and `docs/gaps.md` (ranked work list). Pick work from there.
4. Read `SPEC.md`, and `docs/opcua-interface.md` if you touch anything a client sees (namespace,
   NodeIds, history, timestamps, status codes).
5. Work autonomously. Stop and ask only for **maintainer decisions** (section 9).

## 2. Map and layers

```text
processcraft   the repository root: the central app (people, sign-in, sources, assets, signals,
               launcher); deploy/compose.yaml runs this image as service `simcraft`
apps/<app>     one folder and one container per app
simulator/     this folder (`simcraft`): the OPC UA plant simulator
```

This folder:

```text
src/simcraft/          the package (layers below); catalog/ profiles/ schemas/ are data
src/simcraft/loops/    the 50-loop portfolio the PlantCraft demo reads (`simcraft loops`)
tests/                   pytest; both servers are exercised through a real asyncua client
deploy/                  requirements.in/.lock: hashed dependencies of the Docker image (`make lock`)
docs/                    interface, contracts, scientific model, validation, release, tracking
```

| Layer | Modules (`src/simcraft/`) | Role |
|---|---|---|
| 0 | `settings` | `env()`: `SIMCRAFT_*` variables with their former names as fallbacks |
| 1 | `catalog`, `profiles`, `loops.dynamics` | benchmark catalog and runtime profiles; loop definitions and dynamics |
| 2 | `model`, `loops.storage` | benchmark model and couplings; loop historian and state store |
| 3 | `engine`, `contracts`, `storage` | benchmark simulation, manifests and `NAMESPACE_URI`, historian |
| 4 | `dataset`, `experiments`, `server`, `loops.server` | datasets, studies, the two OPC UA servers |
| 5 | `healthcheck` | one probe for either server |
| 6 | `cli` | the `simcraft` command |

- **Two simulators, one namespace.** The benchmark (`serve`) and the loop portfolio
  (`loops serve`) share only `contracts.NAMESPACE_URI` and `settings`; `loops` never imports
  benchmark modules and the benchmark never imports `loops`. `tests/test_architecture.py` fails
  on any import that goes up a layer or crosses between them.
- **The namespace URI is `urn:processcraft:plantcraft`.** It is part of the benchmark identity
  (manifest, checkpoint). Changing it is a maintainer decision and a new `benchmark_version`.
- **NodeIds are a public contract.** `CPM.Loops.<LOOP>.<SIGNAL>` (read by PlantCraft's demo
  scenario) and the benchmark's catalog-owned `Plant.*` ids. Add nodes; never rename or remove
  one without a release note and a line in `docs/STATUS.md` for PlantCraft.
- **Benchmark identity.** A changed catalog, model, scenario parameterization, profile,
  namespace or schema creates a new benchmark identity: bump `BENCHMARK_VERSION`, update the
  pinned digests in `tests/test_contracts.py` and record the new ones in `CHANGELOG.md` and
  `docs/validation.md`. Follow `docs/scenario-authoring.md`. Never add a `_v2` copy of a module
  or schema.

## 3. Golden rules

### Never break the plant, never break the user (outranks feature work)

- **PlantCraft Simulator is the suite's only write target**, and today it accepts no writes: every node
  is read-only. A writable node (for Models/MPC against simulation) is a maintainer decision.
- **Deterministic.** The same seed, start time and settings give the same values on the same
  platform. Randomness comes only from seeded, documented functions.
- **Bad states are explicit.** Faults show as values, status codes and gaps a client can see
  (`Bad`, `Uncertain`, `BadNoCommunication`, missing samples), never as a crashed server. A
  historian it cannot adopt is refused with a message that says what to do (`--reset`).
- **Restart continues.** A restart resumes from the saved state and history; it never
  duplicates or silently rewrites history.
- **Prove it.** Every fix lands with a small regression test that failed before.

### Clean room

- Simulation behaviour comes from public sources only: papers, standards (OPC UA Parts 4, 8, 11),
  public benchmarks (Tennessee Eastman, DAMADICS) and public manuals. Every source used goes in
  `SPEC.md` with its link. Never use vendor code, binaries, internal manuals, client data, or
  anything received under NDA or an employer/client contract.
- Never copy GPL/AGPL code into the package. `asyncua` (LGPL-3.0) is used as an unmodified
  dependency only.
- Public text (README, release notes, docs) describes the category and our features, never "a
  clone of" or "a free X"; vendor names appear only in the research table of `SPEC.md`.
- Every asset (image, icon, dataset) has a row in `ATTRIBUTION.md` in the same commit.
- **No client or employer specifics**: no plant names, tags copied from a real plant,
  hostnames, IP addresses or credentials, even as defaults or examples. All data is synthetic.

### Secure and offline by default

- **No outbound network.** PlantCraft Simulator opens no connection; it only listens on its OPC UA port.
- **Isolated container.** Non-root (uid 10004), read-only root filesystem, state only in
  `/data`, no pip at runtime, base image pinned by digest, dependencies hash-checked
  (`deploy/requirements.lock`). The image must run unchanged under PlantCraft's
  `deploy/compose.yaml`; `make smoke` starts it that way.
- **Loopback by default.** CLI defaults bind `127.0.0.1`; only the image binds `0.0.0.0`, and
  the suite keeps it on the `plant` network without a published port. The endpoint is anonymous
  `NoSecurity`; never document exposing it to an untrusted network.
- **Never lose data on upgrade.** Historian and state migrations are additive; an incompatible
  file is refused, never overwritten without `--reset`.

### Tests are the gate

- Every change comes with tests; a new feature has at least one test that fails without it.
- Interface changes are tested through an independent `asyncua` client on an ephemeral port
  (`tests/test_server.py`, `tests/test_loops.py`).
- The oracle for PlantCraft Simulator (section 5) is OPC UA conformance through a standard client.

## 4. Before you finish a task

```sh
make ci     # ruff check, ruff format --check, simcraft validate-catalog, pytest, python -m build
make image && make smoke    # when the Dockerfile, dependencies or startup change
```

Then:

- Update the `ROADMAP.md` row and `docs/gaps.md` entry if a number moved or a gap closed, with
  the date.
- Append a short entry to `docs/devlog.md` (what landed, numbers, what's still open).
- Keep the tree green at every commit. One task per commit, message starting with the product
  and task (`simcraft: writable setpoints for the loop portfolio`).

## 5. Oracles (public test data)

| Product | Oracle |
|---|---|
| PlantCraft Simulator | OPC UA conformance through a standard client (asyncua today; the OPC Foundation's UA .NET reference client or CTT later, `docs/gaps.md`) |

Oracle data is never committed; a new oracle is a new pin.

## 6. Parallel agents (several threads at once)

- **One thread owns one repository.** A change PlantCraft must follow (namespace, NodeIds,
  endpoint, image command) lands here first, released as a new version; PlantCraft picks it
  up in its own change. Never edit PlantCraft's files from this repository.
- **Never stack long PR chains.** Branch from `main`, keep PRs small, merge in order.
- Use your own ports (tests take ephemeral ones) and scratch folders; never delete shared paths.

## 7. Where things are tracked

- `docs/STATUS.md`: current focus, next task, blockers. Short; rewritten, not appended.
- `ROADMAP.md`: readiness per area against what the category offers, with the review date.
- `SPEC.md`: the features tools of the category offer (public sources only), each row marked
  done, partial or missing.
- `docs/gaps.md`: every known shortfall, ranked by user impact. The work list.
- `docs/devlog.md`: terse log, newest last.
- `CHANGELOG.md` and `docs/release.md`: per release, with benchmark identities.

## 8. Releases

- Versions `0.x` while alpha. This folder releases its own image (`simcraft:<version>`);
  PlantCraft's `make bundle` assembles the offline suite bundle from green `main` branches.

## 9. Maintainer decisions (stop and ask)

Licensing, making anything public, publishing a release, new remotes, secrets, any write path
(writable nodes), changing the namespace URI or a NodeId, translating the benchmark catalog
(it changes the benchmark identity), deleting data or branches, and changing these rules.
