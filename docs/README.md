# PlantCraft documentation

This folder is the source of truth for the documentation. The in-app **Help**
page reads the user guides directly from `docs/<language>/`; there is no
separate copy inside the interface. English (`docs/en/`) is the source;
Brazilian Portuguese (`docs/pt-BR/`) is a translation, and a guide that is not
translated falls back to English.

## User guides (also in the app)

- [Getting started](en/getting-started.md): an hour with the demo plant, one sticky valve
  followed through every app.
- [User guide](en/user-guide.md): sign in, open your apps, and look after
  sources, signals, assets and people.
- [How the suite works](en/how-it-works.md): PlantCraft in the middle, each
  app on its own, data through API v1.
- [Configuration file](en/configuration-file.md): set an installation up at
  once (sources, signals, assets and loops) from Excel or JSON, with a prompt to
  build it from equipment manuals.
- [Concepts](en/concepts.md): source, signal, asset, role, loop, group, app, app key
  and token.
- [Stack](en/stack.md): the libraries the suite uses by area, with versions and licences, and
  the parts we wrote ourselves that a mature library could take over.

Em português: [docs/pt-BR](pt-BR/).

## Running and deploying

- [Install PlantCraft](install.md): pick a path, and what you need on Linux, macOS and Windows,
  offline, with the security defaults every installation gets.
- [Requirements](requirements.md): server, compute workers, Notebooks computers and disk growth,
  minimum, recommended and large scale, from measured numbers.
- [Offline installation](install-offline.md): the step by step for a plant server.
- [Check a release](verify-a-release.md): prove a bundle is the one the publisher signed, before
  you unpack it, and what the installer checks again.
- [Your data](your-data.md): where an installation keeps its data and how each kind comes out
  (no lock-in).
- [Security guide](security-guide.md): what IT and OT security teams need to
  approve an installation (network, data, accounts, updates). Em português:
  [guia de segurança](pt-BR/security-guide.md).
- [Contributing safely](contributing-safety.md): what stops a hostile or careless pull
  request (code owners, CI that never runs a fork on the Mac mini, scans) and the GitHub settings
  the owner turns on.
- [Deployment](deployment.md): on-premises installation, PI Web API, service,
  containers, backup and update.
- [Disaster recovery](disaster-recovery.md): how much can be lost and how fast the suite comes
  back (RPO and RTO), and how each release checks it.
- [Support and API policy](support-policy.md): supported versions, how a part of API v1 is
  deprecated, and what an update promises about data.
- [AI assistant access (MCP)](assistant-access.md): the read-only MCP server people connect
  their own AI assistant to, with a token of their own. Off by default.
- [OPC UA demo plant](opcua-simulator.md): the Simulator as the demo source, its
  loops, tags, history and containers.

## For developers

- [The suite at a glance](suite.md): every module, its repository, id, prefix, port and the
  shared packages.
- [Product page (draft)](product-page.md): the public page's text, section by section, with
  where each claim is checked.
- [How we build](how-we-build.md): what the platform is for, how we think, and why it is built
  with AI in the open.
- [Working with Claude Code](claude-code.md): the same commands in every repository, and prompts
  that work.
- [Contributing at scale](contributing-at-scale.md): many people and agents in parallel, roles,
  and the GitHub organisation plan.
- [Design notes](design/): [Copy as prompt](design/copy-prompt.md).
- [Desk](desk.md): each person's day, the suite's first screen (Today, calendar, to-do,
  team) and its API.
- [Architecture](architecture.md): philosophy, layers, the apps of the suite,
  loops and data sources.
- [The app standard](app-standard.md): what every app of the suite follows
  (manifest, layout, image, settings, references, results and events, the
  suite table). Decided by the owner on 2026-10-19.
- [Interface rules](ui-guidelines.md): the short checklist every screen follows (navigation,
  buttons, forms, tables, widgets).
- [API v1](api-v1.md): the contract the apps of the suite build on.
- [Testing](testing.md): one test layout for every repository, the shared checks and the time
  budget.
- [Status](STATUS.md), [gaps](gaps.md) and [devlog](devlog.md).
- [Contributing](../CONTRIBUTING.md): ways to help, development setup, adding a method, checks
  and the translation rule.

## Maintenance rules

- Update the Markdown first; the app reads it as is.
- When you change a user guide, update `docs/en/` and `docs/pt-BR/` in the
  same change.
- Show in the interface only what helps a decision or an interpretation; keep
  architecture details in the developer documents.
- Documentation of an app of the suite (Analytics' methods, for example)
  lives in that app's folder, `apps/<app>/docs`.
