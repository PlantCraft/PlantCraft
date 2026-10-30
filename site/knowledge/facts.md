# About PlantCraft

> The facts the site's chat starts from, kept up to date with the site. When another page says
> something different, this page is the newer one.

## What PlantCraft is

PlantCraft is a complete, open suite of industrial software for process engineers: a historian,
analytics for signals and plant assets (control loops among them), alarms, dashboards and process diagrams, process models,
plant documents, notebooks and each person's day (Desk), in one platform. It is built to work
with AI: creating things and asking questions go through an assistant on every page.

The goal: engineers should not lose their time building methods, blocks and analyses. They should
quickly find where the plant has a problem, and discuss and plan the solution with their team.

## The name

PlantCraft was called ProcessCraft until 27 October 2026, before it was published. It is the same
product. The old name still shows in a few ids inside an installation (image and
service names, the app id, data folders), kept so existing installations keep working; the code
is the Python package `plantcraft`, the command is `plantcraft` and the release files are `plantcraft-<version>-...`. The
apps are PlantCraft Historian, Analytics, View, Alarms, Models and Documents, with Desk and
Notebooks built in and the Simulator as the demo plant. Analytics was called Link (and before
that CPMCraft and DataCraft), and View was called TrendCraft and Dashboards.

## The four pillars

1. **Open.** All the code and every method is open, under the Apache License 2.0. Anyone may use,
   change and extend it. The suite is made to grow: new apps for specific uses start from the app
   template and slot in beside the official ones.
2. **Secure.** It installs on the customer's own infrastructure and network (even with no
   internet), only reads the plant (it never writes to a DCS, PLC, PI or OPC UA server), publishes
   one HTTPS port with sign-in and an audit log, runs calculations isolated with no network or
   secrets, backs up before every update, and keeps language models off until an administrator
   turns one on. The model is configurable: any provider the customer chooses, or a model the
   company already runs on its own network.
3. **LLM-first.** Mainly an assistant that checks the calculations and the results, points to
   what needs attention and suggests actions, in a chat, instead of the engineer searching through
   results and charts. It answers from the plant's own data, with the permissions of the person
   asking. It also helps build blocks, algorithms, alarm rules and models. Every proposal is
   confirmed by a person.
4. **Fast.** Value in days, not months: it installs from the offline bundle in under an hour,
   one algorithm runs on one asset in about 0.2 s, Analytics checks every signal and asset from
   its first round, and a new app starts from a template that already has the interface, the
   tests and the rules.

## Quick facts (measured; use these numbers)

- **Server for a trial or a pilot unit:** 4 vCPU and 8 GB of memory (12 GB with every app on),
  50 GB SSD, Linux with Docker (macOS or Windows with Docker Desktop for trials).
- **Server for a plant area** (up to 8,000 signals, 2,000 loops, 30 people at once): 8 vCPU,
  32 GB of memory, 1 TB SSD, Linux. A whole site (up to 30,000 signals, 100 people) is estimated
  at 16 vCPU, 64 GB and 4 TB.
- **Measured on a 4 vCPU, 16 GB machine** at 8,000 signals and 2,050 loops: Analytics checks
  every loop in 106 s, a 24-hour trend comes back in 21 ms (p95), the Historian writes 29,000
  values a second (or more on a larger server), and 30 people at once open a page in 1.4 s (p95). There is no licence limit
  on users or signals; the limits are the server's.
- **Network:** one inbound port, HTTPS 443, from the people who use it. Outbound only to the
  plant's data sources an administrator registers (and to a language model, only if one is set
  up). Every app sits on an internal network with no route out; PlantCraft opens no other port.
  How the plant administers the server itself (for example SSH) is the plant's own choice, not
  part of PlantCraft.
- **Data sources, all read-only:** OPC UA, PI Web API, MQTT, Modbus TCP, SQL and CSV. No
  connector has a write call. Others (for example a PLC protocol) go through an OPC UA server.
- **No lock-in:** plain Python, Modelica and JSON underneath; everything can be exported at any
  time: history as CSV, models as Modelica files, the plant map as JSON or Excel, reports as PDF
  or Word ([Your data](../../docs/your-data.md)).
- **Install time:** under an hour from copying the offline bundle to the first sign-in (the demo
  took about ten minutes in our tests on a prepared machine), plus the plant's own approvals.
- **Signed releases:** every bundle is signed with the publisher's Ed25519 key. You check it with
  `ssh-keygen` before unpacking, and `install.sh` checks it again before it changes anything
  ([Check a release](../../docs/verify-a-release.md)).
- **Updates:** all data is in one folder; an update backs it up first and rolls back by itself if
  the new version does not come up healthy; schemas only go forward.
- **Corporate sign-in:** Active Directory or LDAP, and OpenID Connect (Entra ID, Keycloak, AD FS,
  Okta), off until an administrator turns it on. SAML is not supported yet.
- **Try it without a plant:** the Simulator is an OPC UA plant of 50 control loops with faults on
  purpose (sticky valves, oscillating loops, a drifting temperature); the demo fills every app,
  and the Getting started tour follows one sticky valve across the apps.

## Price, offers and contact

- The software is free: Apache License 2.0. There is no paid edition and no locked feature.
  Companies may use, change and ship it in their own products, keeping the licence and NOTICE
  files; the names and logos are trademarks ([TRADEMARKS](../../TRADEMARKS.md)).
- **No prices, plans or packages are published.** For help to install it at a plant, a pilot, a
  guided demo, training, support, a custom app, a partnership, or any commercial question, the
  answer is: talk to us, through the contact form of this chat or by email to info@plantcraft.io,
  and the team writes back by email. Security reports go to security@plantcraft.io (or GitHub's
  private vulnerability reporting).
- The team never quotes a price, a discount, a date or a delivery time in this chat.

## Status

- PlantCraft is in **alpha**: built in the open, used on a simulated plant and in trials. Screens
  may still change between releases; data and API v1 follow the [support policy](../../docs/support-policy.md).
- There is no hosted (SaaS) version. It runs on your own servers or on a virtual machine you
  control, in the cloud or on premises.
- There is a public online demo with simulated data ("Try the live demo" on the site): a visit
  lasts while it is used (it ends 30 minutes after the last use), ten at once, with a waiting line
  when it is full; visitors can open every app and
  editor, but nothing is saved and the assistant cannot be asked there. It is a separate machine:
  no real plant or customer installation is ever connected to it. To try it with saving, install
  it with the demo plant in about ten minutes, or ask the team for a guided demo.
- **Language:** the interface is in English. A Brazilian Portuguese translation covers only part
  of the screens and is not complete yet. Pages that say otherwise are older than this one.

## Who builds it

Contributions are welcome: bug reports and ideas as GitHub issues, fixes, methods and
translations as pull requests ([CONTRIBUTING](../../CONTRIBUTING.md)). Vulnerabilities are
reported privately ([SECURITY](../../SECURITY.md)).

PlantCraft is written almost entirely with Claude Code (an AI coding agent by Anthropic),
directed by a process engineer who decides what to build and reviews every result. How it is
built, and the rules that hold the agent, are public: [How we build](../../docs/how-we-build.md).

## What the chat is

This chat is an AI assistant on PlantCraft's site. It answers from PlantCraft's public
documentation only, and it can be wrong: the documentation it cites is the reference. It does not
see any plant, installation or person's data.
