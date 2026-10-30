# Develop PlantCraft

> **Updated:** 2026-10-30

How to run PlantCraft from a source checkout, its command line and its settings. Where a change
belongs and how a pull request is reviewed: [CONTRIBUTING.md](../CONTRIBUTING.md); how the
pieces fit: [architecture.md](architecture.md).

## Run it from source

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
[`apps/link`](../apps/link)) the script also starts PlantCraft Analytics on port
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
[install-offline.md](install-offline.md).

A self-contained demo on a CSV file, without OPC UA:

```bash
plantcraft --scenario scenarios/generic_demo.json --browser
```

For a production installation (PI Web API, Kerberos, systemd, backups) see
[deployment.md](deployment.md).

## Command line

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
[opcua-simulator.md](opcua-simulator.md) and `simulator/`). Each app
of the suite has its own settings in its folder (`apps/<app>/README.md`).

## Architecture

The backend is a Python package (`plantcraft/`) with a FastAPI API; the
interface is React + TypeScript (`frontend/`); state lives in one local SQLite
database. Modules only import downward, which `tests/test_architecture.py`
enforces:

| Layer | Modules | Role |
| --- | --- | --- |
| 0 | `db`, `config`, `refs`, `i18n` | Shared SQLite store and scenarios; `kind:id` references; interface language |
| 1 | `industrial_data`, `auth`, `assets`, `events`, `audit` | Data sources (CSV, PI Web API, OPC UA) and history cache; people, tokens and app keys; asset tree; events; the central audit log |
| 2 | `platform` | Workspace, source registry, scenario loops and the plant map |
| 3 | `api`, `cli` | HTTP (the interface's API and API v1), command line |

Details in [architecture.md](architecture.md).
