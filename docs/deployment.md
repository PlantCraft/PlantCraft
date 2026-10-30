# Deployment

This guide installs PlantCraft from scratch on a Linux server in the plant
network, or runs it in containers. PlantCraft is designed to run on premises:
plant data stays on your own server.

## 1. Requirements

| Item | Version | What for |
| --- | --- | --- |
| Linux (Ubuntu 22.04+ or RHEL 9+) | 64-bit | Application server |
| Python | 3.11 or newer | Backend |
| Node.js and npm | 20 or newer (22 recommended) | Only to build the interface; not used at run time |
| git | any | Get and update the code |
| Kerberos libraries | `libkrb5-dev` and `gcc` (Ubuntu) or `krb5-devel` and `gcc` (RHEL) | Only for PI Web API with Kerberos |

Resources: 2 vCPU and 4 GB of RAM serve 50 loops; 4 vCPU and 8 GB serve 500
loops. The database is a local SQLite file; reserve 5 GB of disk.

The server must reach your historian (PI Web API over HTTPS, an OPC UA server,
or CSV files). Users reach the server on the chosen port (8060 in this guide).

## 2. Install

```bash
sudo apt install -y python3 python3-venv git nodejs npm   # Ubuntu
git clone https://github.com/PlantCraft/PlantCraft.git plantcraft
cd plantcraft
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[server,opcua]'
(cd frontend && npm ci && npm run build)
```

Without GitHub access from the server, copy the project folder (or a `.zip` of
the `main` branch) and continue from `python3 -m venv .venv`.

Check the installation:

```bash
plantcraft --help
```

## 3. Demo with the Simulator

```bash
. .venv/bin/activate
python -m pip install -e simulator      # the Simulator, the demo plant
python run_opcua_demo.py --reset --port 8060
```

Open `http://localhost:8060`. The first start generates 48 hours of the Simulator
signals and a week of demo stories that ends today, with five people. Without
authentication, the profile menu at the bottom left switches between people.
To renew the demo on another day, stop the process (Ctrl+C) and run it again
with `--reset`. Without `--reset`, the demo continues where it stopped. See
[opcua-simulator.md](opcua-simulator.md).

## 4. Production

### 4.1 Scenario

A scenario is a JSON file that says where the data comes from and which loops
exist. Start from `scenarios/generic_demo.json` or
`scenarios/opcua_demo.json` and keep your own scenario outside the repository
(for example `/etc/processcraft/plant.json`). A PI Web API source looks like
this:

```json
"source": {
  "type": "pi_web_api",
  "base_url": "https://pi-web-api.example.com/piwebapi",
  "server": "PI-DATA-ARCHIVE",
  "auth_type": "kerberos",
  "timezone": "UTC",
  "tags": ["FIC-101.PV", "FIC-101.SP", "FIC-101.OP"],
  "mapping": {"FIC-101.PV": "FIC-101.PV"}
}
```

- `auth_type`: `kerberos` (default), `basic` or `ntlm`, with `username` and
  `password_env` (the name of the environment variable holding the password);
- `ca_bundle`: PEM file of your corporate CA, if the PI Web API certificate is
  not accepted;
- `tags` and `mapping`: the historian tag on the left, the name used by the
  loops on the right;
- `storage.sqlite_path`: where the database lives (default
  `var/processcraft.sqlite3`).

For OPC UA, use `"type": "opcua"` with `endpoint_url`, `namespace_uri` and
`auth_type` (`anonymous` or `basic`). For files, `"type": "csv"` with `path`.
More sources can be added later in the Historian, or by script with the configuration file;
see [Configuration file](en/configuration-file.md).

### 4.2 Kerberos (PI Web API)

The application uses the Kerberos ticket of the service user that runs it.
Install Kerberos support (system libraries and the `pi` extra):

```bash
sudo apt install -y libkrb5-dev gcc        # RHEL: sudo dnf install -y krb5-devel gcc
.venv/bin/python -m pip install -e '.[server,opcua,pi]'
```

With a keytab provided by IT:

```bash
kinit -kt /etc/processcraft/service.keytab service@DOMAIN
curl --negotiate -u : https://YOUR-PI-WEB-API/piwebapi/dataservers
```

`curl` should list the Data Archive configured in `server`. Renew the ticket
every hour from the service user's `cron`:

```
0 * * * * kinit -kt /etc/processcraft/service.keytab service@DOMAIN
```

### 4.3 Service configuration

Create `/etc/processcraft/env` (mode 600, owned by the service user):

```bash
PLANTCRAFT_SCENARIO=/etc/processcraft/plant.json
PLANTCRAFT_DEMO_USERS=false
PLANTCRAFT_BASIC_AUTH_ENABLED=true
PLANTCRAFT_BASIC_AUTH_USERNAME=admin
PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE=/etc/processcraft/admin-password
```

`PLANTCRAFT_DEMO_USERS=false` stops creating the demo people. `admin` is the
emergency account; its password is in the named file, on a single line.

### 4.4 People and access

Each person signs in with their own username and password:

```bash
export PLANTCRAFT_SCENARIO=/etc/processcraft/plant.json PLANTCRAFT_DEMO_USERS=false
plantcraft users add ana.lima --name "Ana Lima" --role "Control engineering"
plantcraft users password ana.lima
plantcraft users list
```

Passwords must have at least 8 characters. To change a password, run
`plantcraft users password` again (`PLANTCRAFT_PASSWORD` provides it
without a prompt).

Each person has an **access level** and the **applications** they can see.
The admin manages both in **Settings → Users and app keys** (`/settings/users`):
create the person with username, name, role and initial password, edit, reset
the password and deactivate. From the command line:

```bash
plantcraft users add tv.room --name "Control room TV" --access dashboards
plantcraft users add joao.link --name "João" --access viewer --apps linkcraft
plantcraft users access marina.costa editor          # changes the level; --apps limits
plantcraft users admin ana.lima                      # same as --access admin
```

| Level | What it does |
| --- | --- |
| `admin` (Admin) | Everything, including people, data sources and app keys |
| `editor` (Editor) | Changes the plant data in PlantCraft (assets, signals in use, plant map) and edits in the apps |
| `viewer` (Viewer) | Sees the plant data and opens their apps read-only; changes nothing |
| `dashboards` (Dashboards only) | For control-room screens (View); opens no plant data in PlantCraft |

Apps (`linkcraft`, …, the ids in `PLANTCRAFT_APPS`) apply to every level
except admin: without a list, the person opens all of them, including those
installed later. Access granted under the module ids of the former monolith
(`cpm`, `data_quality`) and under the ids of apps since renamed or merged
(`cpmcraft`, `datacraft`, `trendcraft`) still counts for the app that took them over. The rules
apply in the API, not only in the interface: a write by someone who only reads
answers 403, and an app refuses a person its token does not allow. The user in
`PLANTCRAFT_BASIC_AUTH_USERNAME` is always an admin.

Changing a password ends that person's open sessions; ten wrong passwords in a
row block new attempts for five minutes. Behind HTTPS, set
`PLANTCRAFT_SESSION_HTTPS_ONLY=true` so the session cookie only travels
encrypted.

### 4.5 First start

Before starting the service, run the PI connection check. It tests the
network, certificate, Kerberos, server, each tag and each loop, says what to
fix and writes a Markdown report:

```bash
set -a; . /etc/processcraft/env; set +a
plantcraft pi check
plantcraft --host 0.0.0.0 --port 8060
```

`processcraft` refuses a network address such as `0.0.0.0` while sign-in is off (4.4); pass
`--no-sign-in` only on a trusted test network. Open `http://SERVER:8060`, sign in as a person created in 4.4 and go to
**Sources and signals → Test connection**. Then select a loop's signals and
check their history over the last 48 hours. If the connection fails, the page shows the reason
(expired Kerberos ticket, wrong PI server, missing tag).

### 4.6 systemd service

`/etc/systemd/system/processcraft.service`:

```ini
[Unit]
Description=PlantCraft
After=network-online.target

[Service]
User=processcraft
WorkingDirectory=/opt/processcraft
EnvironmentFile=/etc/processcraft/env
ExecStart=/opt/processcraft/.venv/bin/processcraft --host 0.0.0.0 --port 8060
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now processcraft
curl http://localhost:8060/healthz
```

Put a reverse proxy with TLS (nginx, Caddy, your corporate gateway) in front of
the service when people reach it from other machines.

## 5. Operations

| Task | Command |
| --- | --- |
| Check it is up | `curl http://localhost:8060/healthz` |
| Follow the log | `journalctl -u processcraft -f` |
| Daily backup | `sqlite3 var/processcraft.sqlite3 ".backup /backup/processcraft-$(date +%F).sqlite3"` |
| Update | `git pull && .venv/bin/python -m pip install -e '.[server,opcua,pi]' && (cd frontend && npm ci && npm run build) && sudo systemctl restart processcraft` |

Back up `sources.key` (next to the database) together with the database: it
encrypts the passwords of sources added in the interface. Updates keep the
database: new columns and tables are created on start. Do not share the same
SQLite file between hosts.

## 6. Containers

The Docker deployment (HTTPS proxy as the only published port, isolated
networks, non-root read-only containers, offline install, backup before
upgrade and rollback) has its own guide:
[install-offline.md](install-offline.md). It is the recommended way to run the
suite on a plant server. For PI with Kerberos, prefer the installation in
section 2 for now: the service user's ticket is simpler to maintain outside a
container.

## 7. Options

| Variable | Default | Effect |
| --- | --- | --- |
| `PLANTCRAFT_APPS` | empty | Apps of the suite installed beside PlantCraft (`linkcraft=/link/@0.1.0,...`) |
| `PLANTCRAFT_PREWARM_HISTORY` | `true` | Fill the history cache of the last 48 hours on start |
| `PLANTCRAFT_LANGUAGE` | `en` | Language of work done outside a request |
| `PLANTCRAFT_DEFAULT_USER` | first person | Who acts when authentication is off |

The full list of variables is in the [README](../README.md#configuration).
Each app of the suite (Analytics' rounds, for example) has its own options in
its repository.

## 8. Data model and testability

Names used in the code and the database:

- **Source**: a configured connection (`data_sources`); the scenario's source
  is always there.
- **Signal route**: a signal in use and the source it is read from
  (`signal_routes`).
- **Asset**: a node of the plant tree (`assets`), with a kind, an origin
  (`scenario`, `map`, `platform` or `manual`) and attributes.
- **Asset signal**: a signal linked to an asset with a role (`asset_signals`);
  a loop is an asset of kind `loop` with the roles `pv`, `sp`, `op`, `mode`
  and `secondary`.
- **User**, **app key** and **audit entry**: people and their access, the keys
  apps use for background work, and who changed what.

Testable boundaries: scenario models, source adapters, the history cache,
workspace transactions, the plant map, routes, API v1 (contract tests), the
health endpoint and the container smoke test. Run `make ci`.
