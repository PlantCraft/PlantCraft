# Security policy and threat model

## Reporting a vulnerability

Please report vulnerabilities privately. Do not open a public issue, and do not
include credentials, private endpoints, exploit payloads, or historian contents
in one.

Use GitHub's private vulnerability reporting: go to the repository's
**Security** tab and choose **Report a vulnerability**
(https://github.com/PlantCraft/PlantCraft/security/advisories/new). Include the
affected version or commit, how to reproduce it, the impact you expect, and the
smallest safe proof of concept. We will acknowledge the report, keep you
informed while we work on a fix and credit you in the advisory unless you prefer
otherwise.

## Supported versions

PlantCraft Simulator is in alpha. Security fixes go to the `main` branch and the latest
release (0.4.0). It is a simulator, not a production industrial source. See
[Release and compatibility](docs/release.md) for the version table.

## Scope and design notes

- **Synthetic only.** Both servers generate their values; PlantCraft Simulator reads no
  plant system, opens no outbound connection and needs no credentials.
- **Read-only to clients.** No OPC UA node is writable; clients can browse, read,
  subscribe and read history.
- **Container.** The image runs as uid 10004 with a read-only root filesystem;
  state lives only in `/data`, scratch in the `/tmp` tmpfs. It holds no build
  tools, not even pip. Dependencies are installed offline from a hash-checked
  wheelhouse (`deploy/requirements.lock`) on a base image pinned by digest.
- **In the suite** the `simcraft` service sits on PlantCraft's `plant`
  network only and publishes no host port (PlantCraft `deploy/compose.yaml`).
  The local `compose.yaml` here publishes 4840 on host loopback only.

## Intended trust boundary

The servers are a synthetic research and integration-test source. Their OPC UA
endpoint uses anonymous access and `NoSecurity`. The Compose files drop Linux
capabilities, use a read-only root filesystem, and persist only the SQLite
historian (and, for the loop portfolio, its state file) in `/data`.

The supported deployment boundary is therefore:

- a developer workstation or isolated laboratory network;
- trusted local OPC UA clients;
- no routable exposure of port 4840 to an untrusted network;
- no production control, safety, or industrial write path;
- no confidential or proprietary input data.

The simulator does not provide certificate enrollment, user authentication,
authorization roles, audit-event retention, denial-of-service protection, or
high-availability guarantees. Those controls must be supplied by an external
deployment boundary, and such deployments are not covered by the public
support statement.

## Assets and threats

| Asset | Relevant threat | Current control | Residual limitation |
| --- | --- | --- | --- |
| Benchmark identity | Catalog or parameter substitution | Closed schemas and SHA-256 manifest identity | Digests establish identity, not author authenticity |
| Observation history | Silent truncation, duplication, or incompatible restart | Transactional checkpoint, retention bounds, mismatch rejection | SQLite is development persistence, not replicated archival storage |
| Hidden truth | Label leakage into evaluated methods | Separate truth artifact; absent from OPC UA | Researchers must maintain separation after export |
| OPC UA endpoint | Unauthorized reads or resource exhaustion | Loopback-only container default and bounded history responses | Anonymous `NoSecurity` is unsafe on untrusted networks |
| Release artifacts | Dependency or artifact tampering | Pinned runtime dependency, CI builds, planned checksums and provenance | Signed release provenance remains a publication gate |

## Secrets and data handling

The repository and generated benchmark artifacts require no credentials.
Never commit tunnel tokens, certificates, private keys, source credentials, or
private endpoint names. Generated histories and datasets are disposable unless
explicitly selected as research evidence. Hidden-truth artifacts must not be
mounted into an inference service or exposed through OPC UA.
