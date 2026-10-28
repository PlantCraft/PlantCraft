<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/logo-dark.svg">
  <img src="docs/images/logo.svg" alt="PlantCraft" width="300">
</picture>

# PlantCraft

PlantCraft is a complete, open suite for process engineers (historian, analytics, alarms,
dashboards and process models in one place), built on four ideas:

- **Open.** All the code and every method is open (Apache-2.0), and the suite is made to grow:
  new apps for specific uses start from the [app template](templates/app) and slot in beside the
  official ones.
- **Secure.** It installs offline on your own servers, only ever reads the plant, publishes one
  HTTPS port and asks for sign-in by default ([security guide](docs/security-guide.md)).
- **LLM-first.** Creating and asking go through the assistant on every page: it builds the
  block, the algorithm, the rule or the model, and answers questions about the plant, so the
  engineer's time goes to finding the problems and planning the solutions, not to building the
  tools ([product page](docs/product-page.md)).
- **Fast.** Value in days, not months: the demo installs in about ten minutes and Analytics checks
  every signal and loop from its first round ([sizing](docs/en/sizing.md)).

This repository holds the whole suite: the platform at its root (people and access, the plant's
data sources, signals and asset tree, what every app shares), the SDK
([`sdk/python`](sdk/python)) and the shared interface ([`ui`](ui)), and every official app in its
own folder. Each app still builds its own image and signed package, and an installation picks
which apps it runs. The apps reach the platform's data through API v1:

| Module | Folder | What it does |
| --- | --- | --- |
| PlantCraft Analytics | [`apps/link`](apps/link) | Checks every signal for bad data and every control loop for oscillation, sticking and manual mode, runs process models (FMUs) beside the plant, and says why |
| PlantCraft Historian | [`apps/historian`](apps/historian) | The data layer: every plant connection (OPC UA, PI Web API, MQTT, Modbus TCP, SQL, CSV) and every history, read-only toward the plant |
| PlantCraft View | [`apps/view`](apps/view) | Dashboards, scheduled reports and saved trends of any signal, shared with people or by a public link |
| PlantCraft Alarms | [`apps/alarms`](apps/alarms) | Rules that raise ISA-18.2 alarms and alerts from signals and results, the Active list, history and alarm performance |
| PlantCraft Models | [`apps/models`](apps/models) | Block-diagram models (Modelica underneath): draw or write them, simulate them on plant data, run studies and export FMUs |
| PlantCraft Simulator | [`simulator`](simulator) | The simulated plant (OPC UA) behind the demo and the benchmarks |
| App template | [`templates/app`](templates/app) | StarterCraft, the starting point for an app of your own: rules, tests and prompts for Claude Code, tried inside PlantCraft with `make dev` |

Desk (each person's day) and Notebooks (JupyterLab with the plant's data) are part of the
platform itself. Ports, prefixes and versions: [docs/suite.md](docs/suite.md).

**New here?** [Install PlantCraft](docs/install.md) on Linux, macOS or Windows, then take the
[Getting started](docs/en/getting-started.md) tour of the demo plant.

PlantCraft only reads the plant: it never writes to a controller, changes
tuning or alters the process. Everything installs on premises and works
offline.

## Features

- **Sign-in and people.** Individual passwords, four access levels (admin,
  editor, viewer, dashboards only) and, per person, the apps they may open.
- **The launcher.** The home page lists the apps installed beside PlantCraft
  (`PLANTCRAFT_APPS`) with each person's access.
- **API v1 for the apps.** Short-lived signed tokens, app keys for background
  work, the asset tree, signals and history, and a central audit log. The
  contract is in [docs/api-v1.md](docs/api-v1.md); apps build on
  [`sdk/python`](sdk/python) (`plantcraft-sdk`).
- **Data sources.** OPC UA Historical Access, PI Web API and CSV, with a local
  history cache and encrypted source credentials.
- **Signals and assets.** Choose the signals the suite uses, link them to
  assets with a role (a loop's `pv`, `sp`, `op`...), and organize the plant in
  folders.
- **Plant map.** Import or export the whole map (assets, signals, loops,
  sources) as Excel or JSON, with a preview before anything changes.
- **AI assistant access.** A read-only MCP server, off by default: each person connects their
  own assistant with a token of theirs and it reads exactly what they may read
  ([docs/assistant-access.md](docs/assistant-access.md)).
- **English** interface, with a Brazilian Portuguese translation in progress.

## Quick start

Requirements: Python 3.11+, and Node.js 22 to build the interface.

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
processcraft --scenario scenarios/generic_demo.json --browser
```

For a production installation (PI Web API, Kerberos, systemd, backups) see
[docs/deployment.md](docs/deployment.md).

## Command line

| Command | What it does |
| --- | --- |
| `processcraft [--scenario FILE] [--data-file CSV] [--host H] [--port P] [--browser] [--no-prewarm] [--no-sign-in]` | Start PlantCraft (API and interface); a host other than 127.0.0.1 needs sign-in on |
| `processcraft users list` | List people who can sign in |
| `processcraft users add USER --name NAME [--role R] [--access LEVEL] [--apps a,b] [--admin]` | Create a person (`admin`, `editor`, `viewer` or `dashboards`) |
| `processcraft users password USER` | Set a password (or from `PLANTCRAFT_PASSWORD`) |
| `processcraft users access USER LEVEL [--apps a,b]` | Change the access level and apps |
| `processcraft users admin USER [--off]` | Grant or remove admin access |
| `processcraft pi check [--hours H] [--report FILE]` | Test network, authentication, tags and loops of a PI Web API source |
| `processcraft demo reset` | Forget the workspace; the next start recreates it |

Every subcommand takes `--scenario` (default: `PLANTCRAFT_SCENARIO`).

## Configuration

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

## Languages

English is the default language. A Brazilian Portuguese translation covers part of the
interface and is being completed: choose **Português** in the language menu, or let the browser's
`Accept-Language` header pick it.

## Architecture

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

## Documentation

Start with [Install PlantCraft](docs/install.md), the [Getting started](docs/en/getting-started.md)
tour, [the suite at a glance](docs/suite.md) and [how we build](docs/how-we-build.md).
The full index is in [docs/README.md](docs/README.md); the current state is in
[docs/STATUS.md](docs/STATUS.md). The user guides are also available in the app
under **Help**.

## Project status

Alpha. PlantCraft was a single application with loop monitoring, data
quality, dashboards and collaboration inside it; it is now the central app, and
loop monitoring lives in PlantCraft Analytics. The earlier monolith is kept in this
repository's history.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). In short: `make ci` (ruff, pytest and
the frontend build) before every push, and every user-facing string in English
with its Brazilian Portuguese entry in the same change. To report a
vulnerability, see [SECURITY.md](SECURITY.md). Everyone in the project follows the
[code of conduct](CODE_OF_CONDUCT.md); supported versions and how API v1 changes are in the
[support policy](docs/support-policy.md).

## How it is built

PlantCraft is **vibe coded**: written almost entirely by [Claude Code](https://claude.com/claude-code)
(Anthropic's Claude Opus 5.5 model), directed by a process engineer who decides what to build,
reviews the results and owns every decision. We say so openly. It is how one person with an AI
agent can bring industrial software within reach of researchers and process engineers who would
never get a licence for it, and it is why the rules are strict: one standard for every module,
tests that fail on network access, junk input, upward imports and slow tests, oracles on public
data, and a security audit per stage ([AGENTS.md](AGENTS.md)). The suite is also meant to be
used with AI: **Copy as prompt** on methods, blocks, models and the plant map import, and a
read-only MCP server a person's own AI assistant reads the plant through
([assistant-access.md](docs/assistant-access.md)), both with the language model off until IT says
otherwise. More in [How we build](docs/how-we-build.md).

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). The names and logos are not
part of the license: see [TRADEMARKS.md](TRADEMARKS.md).

## Português

O PlantCraft é uma suíte completa para engenheiros de processo, apoiada em três pilares:
**aberta** (todo o código e todos os métodos abertos, e novos apps para aplicações específicas
criados com facilidade), **segura** (offline, só leitura na planta, login por padrão) e
**baseada em LLM** (criar e perguntar pelo assistente, para o engenheiro gastar o tempo achando
os problemas e planejando as soluções, não construindo ferramentas). O app central reúne pessoas e acesso, fontes de dados, sinais e a árvore de ativos da
planta, instalado na própria planta. Os módulos da suíte (como o PlantCraft Analytics, para o
desempenho de malhas) rodam ao lado dele. A suíte é feita com IA (Claude Code, vibe coding),
às claras, para dar a pesquisadores e engenheiros de processo acesso rápido a software
industrial, e foi pensada para ser usada com IA ("Copiar como prompt" e um servidor MCP somente
leitura, desligado por padrão): veja [como construímos](docs/how-we-build.md). O guia de
segurança para TI e automação está em [português](docs/pt-BR/security-guide.md). A interface tem tradução completa
para o português do Brasil (menu de idioma). Os guias do usuário em português
estão em [docs/pt-BR](docs/pt-BR/).
