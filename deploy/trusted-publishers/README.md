# Trusted app publishers

Public keys (Ed25519, PEM) of the publishers whose app packages this server installs, one file per
publisher: `<slug>.pub`, where the slug is the `[app] publisher` of the app's `app.toml` in lower
case with other characters turned into `-` (`Acme Tools` -> `acme-tools.pub`; PlantCraft keeps its first
key, `processcraft.pub`;
docs/app-package.md). PlantCraft (to show a package before you confirm it) and
the installer service (before it runs anything) both check every package against this folder.

- Adding a file here means trusting that publisher's code to run on this server. Get the key from
  the publisher through a channel you trust and compare its fingerprint
  (`python package.py verify` prints the `key_id` of a package it accepts).
- Removing a file stops new installs, upgrades and rollbacks from that publisher; apps already
  running keep running until they are removed.
- No private key ever belongs here. A development key (`make dev-publisher`, `dev-*.pub`) is
  gitignored and never shipped in a release bundle.
