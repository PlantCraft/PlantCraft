# Product page

> **Draft**, 2026-10-26 · the text of the public product page, section by section, for the site
> and the repository's front page at publication. Positioning set by the owner on 2026-10-26
> and 2026-10-27: four pillars, **open**, **secure**, **LLM-first** and **fast**, in that order,
> and no prices or offers on the site, only **Talk to us**. Names follow the
> [glossary](glossary.md). Only public facts: each section says where its claims are checked. The
> site itself is built from [site/](../site/README.md), with a chat that answers from these pages.

---

## Hero

**Spend your time on the plant, not on building the tools.**

PlantCraft is a complete, open suite for process engineers: historian, analytics, alarms,
dashboards and process models in one place, built to work with AI. You ask, and the assistant
builds the method, the block, the rule or the dashboard. You go straight to where the plant has
a problem, and discuss and plan the solution with your team.

**Open** · **Secure** · **LLM-first** · **Fast**

[Install free](install.md) · [Take the tour](en/getting-started.md) · [Source on GitHub](../README.md) · Talk to us

*Apache-2.0 · runs offline on your own servers · Linux, macOS and Windows with Docker*

---

## Open: all of it, and yours to extend

Every line of code and every method is open. Nothing is a black box: a finding says how it was
reached, and the algorithm behind it is blocks and Python you can read, change and share.

- **A complete suite, one platform.** Each app does one job and shares the same people, plant
  assets, signals and look:

  | App | What it does |
  |---|---|
  | **Desk** | Your day: what needs you, actions, calendar, to-do, notes and the team on shift |
  | **Historian** | Collects and archives the plant's signals from OPC UA, PI Web API, MQTT, Modbus TCP, SQL and CSV |
  | **Analytics** | Algorithms of blocks that watch every signal and control loop and say what is wrong and why |
  | **Alarms** | ISA-18.2 alarms and alerts, shelving, history and alarm performance |
  | **View** | Dashboards, scheduled reports and trends |
  | **Models** | Block-diagram models (Modelica underneath), simulations, studies and FMUs |
  | **Notebooks** | JupyterLab with the plant's data, in the browser or on your computer |

- **Expandable.** The apps work together only through what they publish (results and events), so
  a new app slots in beside them. A finding in Analytics becomes an alarm, the alarm a
  notification, the notification an action for the right person, whatever app comes next.
- **New apps in days.** Start from the app template: the shared interface, the SDK, tests against
  a simulated plant, and the rules and prompts an AI assistant needs to build in the suite's
  format. One command makes a signed package that installs offline. Build one for your own
  process, for a research method, for a client; open or closed, in your own repository.
- **Open methods.** Loop performance, signal quality, alarm performance against ISA-18.2: every
  method is written from public literature and tested against public data, so you can check it,
  cite it and improve it.
- **No lock-in.** Plain Python, Modelica and JSON underneath; export everything at any time.
  Apache License 2.0: use it, change it, ship it inside your own products.

*Source: [the suite](suite.md), [the app standard](app-standard.md), [the app
template](../templates/app), [blocks and algorithms](../apps/link/docs/blocks-and-algorithms.md).*

---

## Secure: built for the plant's IT and OT review

Industrial plants install nothing their security teams have not approved. PlantCraft is built
for that review from the first line.

| | |
|---|---|
| **Offline** | Installs from one signed bundle with no internet. No telemetry, update check, licence call, web font or CDN, and a test fails on any of them |
| **Read-only to the plant** | The connectors have no write call: PlantCraft never touches a DCS, PLC, PI or OPC UA server |
| **One port** | Only the HTTPS proxy listens; every app sits on an internal network with no route out |
| **Sign-in by default** | Roles checked on every route, a random first password, an audit log of who changed what |
| **Isolated calculations** | Code people or the assistant write runs on compute workers with no network, no secrets and hard limits |
| **AI under your control** | The assistant reads only what the person asking may read and never writes without their confirmation. No model is called until an administrator sets one up, and it can be a model on your own network |
| **Signed releases** | Ed25519 signatures, SHA-256 hashes and a software bill of materials per release |
| **Never lose data** | One data folder, a backup before every update, automatic rollback when an update fails |

A two-page [security guide](security-guide.md) maps the installation to the Purdue model and to
IEC 62443 for your IT and OT teams ([em português](pt-BR/security-guide.md)).

---

## LLM-first: ask, don't build

Engineers lose weeks building the tools before they can look at the plant: writing a method,
wiring blocks, setting up an analysis, drawing a dashboard. In PlantCraft the language model does
that work, so your time goes to what only you can do: find the problem, understand it, and plan
the fix with your team.

- **Create by asking.** Every page has an assistant with tasks for that page: *Help me create a
  new block* and *Help me design a new algorithm* in Analytics, *Help me create an alarm* in
  Alarms, *Help me design a new model* in Models. It proposes the block, the algorithm, the rule
  or the model with its fields filled in; you review it and confirm.
- **Find the problems first.** Analytics runs over every signal and loop and ranks the results:
  a level, a score and a sentence that says why, with the evidence. You start from the worst
  loops, not from a blank screen.
- **Ask about the plant.** *Why did this alarm fire?*, *Which alarms should we fix first?*,
  *What changed in the period?*, *Explain this dashboard*: the assistant answers from the
  plant's own data, results and history, with charts and links to its sources.
- **Discuss and plan.** Answers turn into actions with an owner, conversations with the team and
  specialists, and reports for the shift: the step from "what is wrong" to "who fixes it, and
  how".
- **Your own AI, too.** **Copy as prompt** hands any block, algorithm, model or the plant map to
  the assistant you already use, and a read-only MCP server lets it read the plant as you see it.

The suite itself was built this way: written almost entirely by
[Claude Code](https://claude.com/claude-code) (Anthropic's Claude Opus 5.5), directed by a
process engineer who decides what to build and reviews every result. One engineer with an AI
agent can bring a whole category of industrial software to researchers and plant engineers, and
every rule that held the agent (one standard for every app, tests on network access, junk input
and public data, a security audit per stage) is in the repository for the next one.

*Source: [the assistant](assistant.md), [assistant-access.md](assistant-access.md), [Copy as
prompt](design/copy-prompt.md), [How we build](how-we-build.md).*

---

## Fast: value in days, not months

No project before the first result. Install it, point it at the plant's data, and the first
findings arrive the same day: the demo installs in about ten minutes from the offline bundle,
Analytics checks every signal and loop from its first round, and a new app starts from a template
that already has the interface, the tests and the rules. At 8,000 signals and 2,050 loops on a
4 vCPU, 16 GB server, Analytics checks every loop in 106 s and a 24-hour trend comes back in 21 ms.

*Source: [Install PlantCraft](install.md), [Sizing the server](en/sizing.md).*

---

## See it on a plant that misbehaves

The suite ships with the **Simulator**, an OPC UA plant of 50 control loops with faults on
purpose: four sticky valves, oscillating pressure loops, a drifting furnace temperature. The demo
fills every app as if a team had used it for three weeks. Follow one sticky valve from the
signal to the alarm, the dashboard, the model and the notebook in an hour.

[Getting started](en/getting-started.md)

---

## Sized from measured numbers

At 8,000 signals and 2,000 loops, on a 4 vCPU, 16 GB machine: the Historian writes 29,000 values
a second, a 24-hour trend comes back in 21 ms (p95), and Analytics checks every loop in under a
minute. A unit or a pilot plant runs on 4 vCPU and 8 GB.

*Source: [Sizing the server](en/sizing.md), `make bench-suite`.*

---

## Install

One bundle and one command, made for networks without internet: copy the bundle to the server,
check its signature, run the installer. It sets up the platform, the apps, the Simulator if you
want it, and an administrator account.

```bash
tar -xzf processcraft-0.5.0-linux-amd64-bundle.tar.gz
cd processcraft-0.5.0-linux-amd64-bundle
./install.sh --all-apps --demo
# open https://<server>/ and sign in as admin
```

Linux for plant servers; macOS and Windows (Docker Desktop) for trials and development.
[The install guide](install.md)

---

## Questions

**Is it free?** Yes, under the Apache License 2.0, with no paid edition and no locked feature.
The names and logos are trademarks ([TRADEMARKS.md](../TRADEMARKS.md)).

**Can you help us at our plant?** Talk to us: a pilot on your unit, help to install it, training,
an app for your process. No prices are published; the team answers each request personally.

**Do I need a cloud AI?** No. The suite installs and runs offline, and works without a language
model: the analyses, alarms and dashboards do not need one. The assistant needs a model, which can
run on your own network, and stays off until an administrator sets it up.

**Does the assistant change anything on its own?** No. It reads with the permissions of the person
asking, and anything it creates is a proposal that person confirms. It never writes to the plant.

**Does it replace our historian or DCS?** It never replaces the DCS: it only reads. It can be
your historian, or read the one you have through PI Web API or OPC UA.

**Can my company build an app for it?** Yes, open or closed, in its own repository, on the
published SDK and interface, starting from the app template.

**Who supports it?** It is an alpha, built in the open. Versions and what an update promises:
[support policy](support-policy.md). Security reports: [SECURITY.md](../SECURITY.md).
