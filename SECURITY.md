# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately. Do not open a public issue.

Use GitHub's private vulnerability reporting: go to the repository's
**Security** tab and choose **Report a vulnerability**
(https://github.com/PlantCraft/PlantCraft/security/advisories/new),
or write to [security@plantcraft.io](mailto:security@plantcraft.io).

Include what you found, how to reproduce it, the affected version or commit
and the impact you expect. We will acknowledge the report, keep you informed
while we work on a fix and credit you in the advisory unless you prefer
otherwise.

## Supported versions

PlantCraft is in alpha. Security fixes go to the `main` branch and the
latest release; see [docs/support-policy.md](docs/support-policy.md).

## Scope and design notes

- **Plant data stays local.** PlantCraft runs on premises. It reads from
  your historians and keeps its state on the server; it sends nothing to
  third parties. The assistant's language model is off until an administrator
  turns it on, and then only the egress named in
  [docs/assistant-access.md](docs/assistant-access.md) leaves the server.
- **Read-only towards the process.** The platform never writes to a
  controller or a historian.
- **Credentials.** Source passwords typed in the interface are encrypted with a
  key kept next to the database (`sources.key`) and never return to the
  browser or appear in exports. Prefer `password_env` for scenario files.
- **Apps of the suite.** Apps verify PlantCraft's tokens offline and use
  app keys for background work. Keys are stored hashed, shown once and
  revocable under **Settings → Users and app keys**.
- **Exposure.** The installed suite (`deploy/install.sh`) signs in by default,
  serves HTTPS only and keeps session cookies on HTTPS. A development server
  started by hand with sign-in off serves `127.0.0.1` only, unless told
  otherwise with `--no-sign-in` on a trusted test network. The demo plant (the Simulator's OPC UA server) uses no
  security and must stay on an isolated network.

See [docs/deployment.md](docs/deployment.md) for a hardened installation.
