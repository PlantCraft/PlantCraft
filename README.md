<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/logo-dark.svg">
  <img src="docs/images/logo.svg" alt="PlantCraft" width="300">
</picture>

# PlantCraft

**Industrial software for process engineers. Spend your time on the plant, not on building the tools.**

[Website](https://plantcraft.io) · [Live demo](https://demo.plantcraft.io) · [Install](docs/install.md) ·
[Getting started](docs/en/getting-started.md) · [Security guide](docs/security-guide.md)

PlantCraft is a complete, open suite: historian, analytics, alarms, dashboards and diagrams,
process models and plant documents in one place, built to work with AI. You ask, and the
assistant builds the method, the block, the rule or the dashboard. You go straight to where the
plant has a problem, and plan the fix with your team.

> ⭐ **If PlantCraft is useful to you, or you would like to see it grow, star this repository.**
> It is the simplest way to help an open industrial project get found.

## Open, Secure, LLM-first, Fast

- **Open: all code and methods.** Every line of code and every method is open (Apache-2.0), with
  no paid edition and no locked feature. A finding says how it was reached, and the algorithm
  behind it is blocks and Python you can read, change and share. Apps work together only through
  what they publish, so a new app for your process, your research or your client starts from the
  [app template](templates/app) and slots in beside the official ones.
- **Secure: offline, read-only.** It installs from one signed bundle with no internet, never
  writes to a DCS, PLC or historian, publishes one HTTPS port and asks for sign-in by default.
  No language model is called until an administrator sets one up. The
  [security guide](docs/security-guide.md) maps it to the Purdue model and IEC 62443.
- **LLM-first: ask, don't build.** Every page has an assistant that proposes the block, the
  algorithm, the alarm rule or the model with its fields filled in, and answers questions from
  the plant's own data, results and documents. Your own AI can read the plant too, through a
  read-only MCP server ([assistant access](docs/assistant-access.md)).
- **Fast: value in days, not months.** The demo suite installs from the offline bundle in about
  ten minutes, and Analytics checks every loop and signal from its first round, the worst first,
  each with a sentence that says why ([sizing](docs/en/sizing.md)).

## The suite

One platform, every plant tool. Each app runs in its own container and shares the same people,
plant assets, signals and look; an installation picks the apps it needs.

| App | Folder | What it does |
| --- | --- | --- |
| PlantCraft Analytics | [`apps/link`](apps/link) | Checks every signal for bad data and every control loop for oscillation, sticking and manual mode, runs process models (FMUs) beside the plant, and says why |
| PlantCraft Historian | [`apps/historian`](apps/historian) | The data layer: every plant connection (OPC UA, PI Web API, MQTT, Modbus TCP, SQL, CSV) and every history, read-only toward the plant |
| PlantCraft View | [`apps/view`](apps/view) | Dashboards, process diagrams, scheduled reports and saved trends of any signal, shared with people or by a public link |
| PlantCraft Alarms | [`apps/alarms`](apps/alarms) | Rules that raise ISA-18.2 alarms and alerts from signals and results, the Active list, history and alarm performance |
| PlantCraft Models | [`apps/models`](apps/models) | Block-diagram models (Modelica underneath): draw or write them, simulate them on plant data, run studies and export FMUs |
| PlantCraft Documents | [`apps/documents`](apps/documents) | The plant's documents in one library (manuals, P&IDs, procedures, maintenance records), linked to the assets and searched by words and meaning; the assistant cites document, revision and page |
| PlantCraft Simulator | [`simulator`](simulator) | The simulated plant (OPC UA) behind the demo and the benchmarks |
| App template | [`templates/app`](templates/app) | StarterCraft, the starting point for an app of your own: rules, tests and prompts for Claude Code, tried inside PlantCraft with `make dev` |

Desk (each person's day) and Notebooks (JupyterLab with the plant's data) are part of the
platform itself, at the root of this repository with the SDK ([`sdk/python`](sdk/python)) and the
shared interface ([`ui`](ui)). Ports, prefixes and versions: [docs/suite.md](docs/suite.md).

## Try it

- **In your browser:** the [live demo](https://demo.plantcraft.io) runs the whole suite on a
  simulated plant.
- **On your own server:** [install PlantCraft](docs/install.md) from the offline bundle on Linux,
  macOS or Windows (`./install.sh --demo` adds the demo plant), then take the
  [Getting started](docs/en/getting-started.md) tour.
- **Questions:** ask the chat on [plantcraft.io](https://plantcraft.io), or write to
  [info@plantcraft.io](mailto:info@plantcraft.io).

## Documentation

Start with [Install PlantCraft](docs/install.md), the [Getting started](docs/en/getting-started.md)
tour, [the suite at a glance](docs/suite.md) and [how we build](docs/how-we-build.md). The full
index is in [docs/README.md](docs/README.md). The user guides are also in the app, under **Help**.

## Built with AI, in the open

PlantCraft is written almost entirely by [Claude Code](https://claude.com/claude-code), directed by
a process engineer who decides what to build, reviews the results and owns every decision. We say
so openly: it is how industrial software can reach researchers and process engineers who would
never get a licence for it, and it is why the rules are strict. One standard for every module,
tests that fail on network access, junk input, upward imports and slow tests, oracles on public
data, and a security audit per stage ([AGENTS.md](AGENTS.md), [how we build](docs/how-we-build.md)).

## Contributing

Contributions are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md). In short, `make ci` (ruff,
pytest and the frontend build) before every push. To report a vulnerability, see
[SECURITY.md](SECURITY.md). Everyone in the project follows the [code of conduct](CODE_OF_CONDUCT.md);
supported versions and how API v1 changes are in the [support policy](docs/support-policy.md).

PlantCraft is in alpha. If it helps you, ⭐ **star the repository** and tell us what you run it on.

## For developers

### Run it from source

Requirements: Python 3.12 or 3.13 (asyncua, the OPC UA library, fails on 3.15:
[#10](https://github.com/PlantCraft/PlantCraft/issues/10)), and Node.js 22 to build the interface.

```bash
git clone https://github.com/PlantCraft/PlantCraft.git plantcraft
cd plantcraft
python3 -m pip install -e sdk/python -e ".[server,opcua]"
python3 -m pip install -e simulator      # the Simulator, the demo plant
python3 run_opcua_demo.py --browser
```

The script starts the Simulator's OPC UA server (`simcraft loops serve`, unless
something already listens on port 4840; without the Simulator it says how to
install it), builds the interface when
`frontend/dist` is missing or out of date (`--skip-build` turns this off) and
opens PlantCraft at http://127.0.0.1:8060 with the simulated plant's 50 loops
in the asset tree. When the `linkcraft` command is on `PATH` (install it from
[`apps/link`](apps/link)) the script also starts PlantCraft Analytics on port
8140 with an app key and lists it in the launcher; `--no-linkcraft` leaves it
out.

With Docker (the same hardened stack as the offline release bundle):

```bash
make image simcraft-image   # simcraft-image builds the Simulator's image from simulator/
deploy/install.sh --dev --demo
```

It starts the PlantCraft Simulator (its own image), PlantCraft, PlantCraft Analytics (when its image is
present) and the HTTPS proxy, publishes only the proxy (https://localhost, local
certificate authority) and prints the administrator password. Plant servers
install from the offline bundle instead: see
[docs/install-offline.md](docs/install-offline.md).

A self-contained demo on a CSV file, without OPC UA:

```bash
plantcraft --scenario scenarios/generic_demo.json --browser
```

For a production installation (PI Web API, Kerberos, systemd, backups) see
[docs/deployment.md](docs/deployment.md).

### Command line

| Command | What it does |
| --- | --- |
| `plantcraft [--scenario FILE] [--data-file CSV] [--host H] [--port P] [--browser] [--no-prewarm] [--no-sign-in]` | Start PlantCraft (API and interface); a host other than 127.0.0.1 needs sign-in on |
| `plantcraft users list` | List people who can sign in |
| `plantcraft users add USER --name NAME [--role R] [--access LEVEL] [--apps a,b] [--admin]` | Create a person (`admin`, `editor`, `viewer` or `dashboards`) |
| `plantcraft users password USER` | Set a password (or from `PLANTCRAFT_PASSWORD`) |
| `plantcraft users access USER LEVEL [--apps a,b]` | Change the access level and apps |
| `plantcraft users admin USER [--off]` | Grant or remove admin access |
| `plantcraft pi check [--hours H] [--report FILE]` | Test network, authentication, tags and loops of a PI Web API source |
| `plantcraft demo reset` | Forget the workspace; the next start recreates it |

Every subcommand takes `--scenario` (default: `PLANTCRAFT_SCENARIO`).

### Configuration

PlantCraft is configured by a scenario file (data source, loops, storage; see
`scenarios/`) and by environment variables:

| Variable | Default | Effect |
| --- | --- | --- |
| `PLANTCRAFT_SCENARIO` | `scenarios/generic_demo.json` (`deploy/site/site.json` in the container) | Scenario file |
| `PLANTCRAFT_DATA_FILE` | empty | Replace the scenario source with this CSV file |
| `PLANTCRAFT_PORT` | `8060` | HTTP port |
| `PLANTCRAFT_APPS` | empty | Apps of the suite installed beside PlantCraft: `linkcraft=/link/@0.1.0,...` |
| `PLANTCRAFT_LANGUAGE` | `en` | Language of work done outside a request |
| `PLANTCRAFT_BASIC_AUTH_ENABLED` | `false` | Require sign-in |
| `PLANTCRAFT_BASIC_AUTH_USERNAME` | — | Emergency admin account (required with sign-in) |
| `PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE` | — | File holding that account's password |
| `PLANTCRAFT_SESSION_HTTPS_ONLY` | `false` | Send the session cookie over HTTPS only |
| `PLANTCRAFT_SESSION_SECRET_FILE` | `session.secret` next to the database | Key that signs sessions |
| `PLANTCRAFT_TOKEN_KEY_FILE` | `tokens.key` next to the database | Ed25519 key that signs the API v1 tokens |
| `PLANTCRAFT_DEMO_USERS` | `true` | Create the demo people |
| `PLANTCRAFT_DEFAULT_USER` | first person | Who acts when sign-in is off |
| `PLANTCRAFT_SOURCES_KEY_FILE` | `sources.key` next to the database | Key that encrypts source passwords |
| `PLANTCRAFT_OPCUA_ENDPOINT` | from the scenario | Override the OPC UA endpoint of the scenario |
| `PLANTCRAFT_OPCUA_CONCURRENT_READS` | `16` | Parallel OPC UA history reads |
| `PLANTCRAFT_PREWARM_HISTORY` | `true` | Fill the history cache on start |
| `PLANTCRAFT_RESET_HISTORY_CACHE` | `false` | Drop the local history cache on start |
| `PLANTCRAFT_LOG_LEVEL` | `INFO` | In `deploy/.env`: log level of the app and the Simulator containers |

The Simulator, the demo plant, has its own `PLANTCRAFT_*` variables (see
[docs/opcua-simulator.md](docs/opcua-simulator.md) and `simulator/`). Each app
of the suite has its own settings in its folder (`apps/<app>/README.md`).

### Architecture

The backend is a Python package (`processcraft/`) with a FastAPI API; the
interface is React + TypeScript (`frontend/`); state lives in one local SQLite
database. Modules only import downward, which `tests/test_architecture.py`
enforces:

| Layer | Modules | Role |
| --- | --- | --- |
| 0 | `db`, `config`, `refs`, `i18n` | Shared SQLite store and scenarios; `kind:id` references; interface language |
| 1 | `industrial_data`, `auth`, `assets`, `events`, `audit` | Data sources (CSV, PI Web API, OPC UA) and history cache; people, tokens and app keys; asset tree; events; the central audit log |
| 2 | `platform` | Workspace, source registry, scenario loops and the plant map |
| 3 | `api`, `cli` | HTTP (the interface's API and API v1), command line |

Details in [docs/architecture.md](docs/architecture.md).

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). The names and logos are not
part of the license: see [TRADEMARKS.md](TRADEMARKS.md).
