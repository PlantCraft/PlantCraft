# PlantCraft security guide for IT and OT

Two pages handed to the client's IT and automation teams with every release. It describes the
Docker deployment of the suite ([install-offline.md](install-offline.md)). Items marked
**planned** are tracked in `docs/gaps.md` and are not yet true; **partial** says what is missing.

## 1. What it is and what it does not do

PlantCraft reads process data from a historian (PI Web API), OPC UA servers or CSV files and
serves analyses (PlantCraft Analytics, Historian, View, Alarms and Models; repositories
`linkcraft`, `histcraft`, `dashcraft`, `alarmcraft`, `modelcraft`) to browsers. It **never
writes** to a DCS, PLC, PI or OPC UA server: the data connectors (PlantCraft's and the
Historian's) have no write call. The demo plant (PlantCraft Simulator, profile `demo`) is a separate
image that PlantCraft and the Historian only read. It sends nothing to the internet: no
telemetry, update check, licence call, web font or CDN (`tests/test_offline.py`).

**Language models are off by default.** PlantCraft can let its specialists answer with a
language model the administrator sets up in Settings › Language models ([collaboration.md](collaboration.md)):
a model on the company's network (vLLM, Ollama, a gateway) or a cloud API. Until then nothing is
sent to any model. `PLANTCRAFT_LLM=off` forbids models in the installation, whatever the
settings say. A model on the plant's network is reached over the plant conduit Z4, so
`firewall.sh` must list its `host:port`, as for a PI server. A model in the cloud is reached only
through `llm-egress` (row "LLM egress" below): PlantCraft itself still resolves no internet name.
**AI assistants** reach the suite the other way round, through the
read-only MCP server (section 4), also off by default.

## 2. Where to install (Purdue model)

On a Linux server at **level 3** (site operations, next to the historian) or in the **industrial
DMZ (level 3.5)**. Never at levels 0 to 2. Users reach it from level 3 or 4 through HTTPS; it reads
from level 3 (PI) or from OPC UA servers the OT team exposes to level 3. It needs no inbound
connection from levels 0 to 2 and opens none to level 4 or the internet.

## 3. Zones and conduits (IEC 62443-3-2)

```text
 Level 4/3 users ──C1 HTTPS 443──▶ [edge: proxy] ──▶ [apps: PlantCraft, Analytics,
                                                       View, Historian, Alarms, Models]
                                                       │ (internal network, no route out)
                                   [histdb: Historian and histcraft-db only] (internal)
                                   [plant: PlantCraft, Historian] ──C2──▶ PI Web API 443, OPC UA 4840
                                   [demo: PlantCraft, Historian and the Simulator]
                                                       (internal network, no route out)
```

| Zone or conduit | What is in it | Controls |
|---|---|---|
| Z1 Host | The server and Docker | Client's hardening and patching; only Docker and SSH needed |
| Z2 Edge | Proxy (Caddy) | The only published port (443); TLS with the client's certificate or a local CA; no admin API; no outbound NAT, so it cannot reach out |
| Z3 Apps | PlantCraft (uid 10001), View (10006), Historian (10008), PlantCraft Alarms (10009), PlantCraft Models (10011), Analytics (10012) | Docker network with `internal: true`: no route outside the host; apps reach plant data only through PlantCraft's API with signed tokens, except the Historian (row below) |
| Historian database | `histcraft-db`, the Historian's PostgreSQL (uid 10008) | Its own internal network `histdb`, shared with the Historian only: no other container (proxy, PlantCraft, Analytics, View) can open a connection to it; no published port; scram-sha-256 with a password only the Historian holds |
| Historian collection | Historian (profile `histcraft`) | The suite's historian and data layer: it reads its own sources (OPC UA, PI Web API, CSV files in `data/histcraft-csv`, read-only), created on its Sources page, so it is the second component on the plant conduit Z4, under the same `firewall.sh` rules; it also joins the internal `demo` network to read the Simulator. Source passwords are encrypted with `data/histcraft/secret.key` |
| Historian gateway | `histcraft-gateway`: Telegraf, unchanged and pinned by digest (uid 10008, profile `histcraft`) | Reads the MQTT, Modbus TCP and SQL sources on the same plant conduit Z4 and `demo`, never `histdb` or `apps`. Its only configuration is `data/histcraft/gateway/telegraf.conf` (0600, mounted read-only), written by the Historian's collector: only reading inputs (`mqtt_consumer`, `modbus`, `sql` with one checked SELECT) and one output, to the collector with a token. No port, no other secret |
| Compute workers | `compute-gateway` (uid 10020, PlantCraft's image) and the apps' executors `linkcraft-executor` and `modelcraft-executor` (uid 10020), here and on other machines (docs/compute.md) | They run the code people write: Analytics' analyses and blocks' code, Models' Modelica jobs. The executors have no network at all (`network_mode: none`), no secret, a read-only root, `/tmp` a noexec tmpfs, no capabilities, `no-new-privileges`, CPU, memory and process limits and a time and memory limit per task; their only link is their folder in `data/compute-jobs/` (mode 0700), shared with the gateway. The gateway holds the worker's credential, opens no port and asks PlantCraft for tasks on the internal network `compute` (another machine: over HTTPS); an administrator pauses or revokes a worker in Settings › Compute. Models' runner (`modelcraft-runner` image) is the one image that holds a C compiler (OpenModelica needs it); Models and the runner refuse `external` code and file or system functions before a job runs |
| Installer | `installer` service (uid 10005) | The only container with the Docker socket; no network at all (`network_mode: none`), read-only, no capabilities; acts only on signed packages it verifies itself |
| LLM egress | `llm-egress` (uid 10014, PlantCraft's image) | The only way to a language model in the cloud: an HTTPS proxy on the internal `llm` network (PlantCraft and itself only) with its own route out (`egress`). It opens a tunnel only to port 443 of the hosts of the providers an administrator added in Settings › Language models (PlantCraft writes them to `data/egress/allow.json`, which it reads only), and never to a name that resolves inside the plant or the host. No provider in the cloud, or `PLANTCRAFT_LLM=off`: it opens nothing. It holds no key (the request is encrypted end to end), logs every connection and refusal, and is the only container that resolves internet names (`PLANTCRAFT_LLM_DNS`). Leave the service out to forbid models in the cloud at the network level |
| Z4 Plant conduit | PlantCraft and the Historian | Outbound to the PI and OPC UA hosts the administrator registers; `firewall.sh` limits the whole plant network to those `host:port` pairs |
| Demo | the Simulator (only with `--demo`), PlantCraft and the Historian | Docker network with `internal: true`: the simulator has no route out of the host |
| DNS | Every container | No lookup of a name outside the suite leaves the server: the proxy and the Simulator resolve service names only, PlantCraft too unless `PLANTCRAFT_DNS` names the plant's DNS server, and the apps sit on internal networks. The one exception is `llm-egress`, for the providers' hosts only |
| C1 Users → Z2 | HTTPS | HSTS, secure session cookies, sign-in required, 10 failed sign-ins block 5 minutes |
| C2 Z4 → PI/OPC UA | HTTPS / OPC UA binary | Read-only service account on PI; OPC UA anonymous or user/password (**planned:** OPC UA signing and encryption) |

`tests/test_isolation.py` proves in CI that only the proxy publishes a port, that an app container
has no route out (a connection to the internet fails) and cannot reach the plant network or
the Historian's database, that
no container resolves an external name, and that
every container runs as described in section 5.

## 4. Accounts and access

- Sign-in is required in this deployment; the emergency administrator's password is generated
  at install (24 random characters, file mode 0600, never logged).
- Roles admin, editor, viewer and dashboards-only, with per-application access, enforced by the
  API. Apps receive short-lived Ed25519-signed tokens (15 minutes) and verify them offline
  (`docs/api-v1.md`). `tests/test_route_permissions.py` walks every route and fails on one that
  answers without a session or above the caller's level. **Partial:** sign-in outside this
  Docker deployment is still optional.
- Corporate sign-in (off by default, `docs/corporate-login.md`): Active Directory or LDAP over
  LDAPS or StartTLS only, and single sign-on with OpenID Connect (PKCE, state, nonce, signed ID
  tokens). The directory's groups map to levels, apps and groups; the installation's admin account
  always signs in locally. **Not yet:** SAML.
- Central audit log: who changed what (people, groups, assets, apps, keys, settings, backups),
  in PlantCraft and in every app (the apps write theirs through `POST /api/v1/audit`), with the
  person's name, kept in PlantCraft's database, plus every sign-in, failed sign-in, blocked
  sign-in and sign-out with the address it came from and the method (local, LDAP, OIDC).
  Administrators read it on Settings › Audit log (filters, search, CSV download); rows are only added.
- Desk's calendar links (off by default, `docs/desk.md`): when an admin turns them on and names
  the servers allowed, PlantCraft reads those `.ics` addresses over https every 15 minutes (2 MB
  at most, no credentials in the link, addresses inside the network refused). Importing an `.ics`
  file needs no network.
- AI assistant access (off by default, `docs/assistant-access.md`): a read-only MCP server at
  `/mcp` that a person's own AI assistant reads the plant through, with an access token of that
  person (shown once, stored as a SHA-256, expiring, revocable) and exactly that person's access.
  Nothing writes; every tool call is audited; `PLANTCRAFT_MCP=off` forbids it in the installation.
- Desk's Assistant (off until a language model is set up, `docs/assistant.md`): reads the plant
  through the same read-only tools, as the person who asks, with a token issued at each read, and
  only the apps that person may open; the MCP server applies the same app filter. Each read is
  audited (`assistant.tool`); answers are limited per person and per day.
- Notebooks (off by default, `docs/en/notebooks.md`): JupyterLite built into the image, so
  Python runs in each person's browser, never on the server, and reads API v1 as that person.
  Nothing is downloaded at run time (no PyPI fallback). Only the pages under `/notebooks/lite/`
  get a Content-Security-Policy that also allows `'unsafe-eval' 'wasm-unsafe-eval'` (WebAssembly
  and JupyterLab's generated code); every other page keeps `script-src 'self'`. On a person's
  computer the same package reads with their access token, read-only, while Notebooks are on.
  `PLANTCRAFT_NOTEBOOKS=off` forbids them in the installation.
  What one person may ask API v1 for is limited (Settings › Notebooks: 120 requests a minute and
  2 reads at once by default, `plantcraft/api/usage.py`): every request with an access token,
  and series reads from a browser through the proxy; past it that person alone gets 429, and the
  apps' own reads inside the internal network never count.
  The Notebooks kit (an optional part of the bundle, offered with Notebooks, an administrator may take it away) runs Python and
  JupyterLab on the person's computer, listening on 127.0.0.1 only; PlantCraft adds the server's
  address and the local CA's public certificate to the zip, never a token. The kit's token lasts
  90 days at most, never longer than the administrator's limit for tokens (Setup, 30 days by
  default), reads only, and is kept in the system's vault. The person pastes it into the app once as a
  connection code (shown once on the signed-in page): the server's address, the token and the
  SHA-256 of the local CA, which the app checks before it trusts the CA. A link names a
  server and a notebook only; the app runs nothing that comes with it. JupyterLab there needs a
  password the app makes at each start. Every file of the kits is pinned by
  SHA-256 at build time; the kits are not code-signed yet (Windows and macOS warn on first open).
- Public demo (`install.sh --public-demo`, off by default, [public-demo.md](public-demo.md)):
  visitors enter as visits of one read-only viewer account (a few places at once, minutes each;
  from outside the account never signs in with its password); every write by a viewer answers
  403 (they may only sign out and mark messages read), they never reach a language model (only
  the editors and administrators an administrator created do; the apps' uses stay off), each
  visit is limited to `PLANTCRAFT_PUBLIC_DEMO_RATE` requests a minute through the proxy (429) and to a few
  requests in flight in each app.
  Never turn it on for an installation holding real plant data.
- Source passwords typed in the interface are encrypted at rest with a key kept in the data folder.

## 5. Containers and data

- Every container: non-root user, read-only root filesystem, all Linux capabilities dropped,
  `no-new-privileges`, CPU, memory and process limits, health checks, restart policy. The images
  hold no compiler or package manager (pip is removed), except the Modelica runner's compiler (row Modelica runner above); Python dependencies are installed from
  hash-checked wheels.
- All state is in one folder (`data/`, one sub-folder per container user: `processcraft/`,
  `linkcraft/`, `dashcraft/`, `alarmcraft/`, `modelcraft/`, `compute-jobs/`, `histcraft/`, `histcraft-db/`, `proxy/`,
  `plantcraft/`). App keys (`data/<app>-app-key`) and the Historian's database password
  (`data/histcraft-db-password`) are files of mode 0600 owned by the app's user, passed as Docker
  secrets. No data leaves the server. Backup means copying the install folder; upgrades back it
  up automatically (the Historian's database by blocks, with PostgreSQL's own tools) and
  `./install.sh --rollback` returns to the previous version. **Planned:** `plantcraft rollback`
  for installations without Docker (G12). Data at rest is not encrypted by PlantCraft: use the
  server's disk encryption if required.

## 6. Install, update and remove

Offline bundle per release: images `.tar`, compose file, installer, SBOM, SHA-256 sums. No internet
needed to install, update or roll back. Removal: `./install.sh --uninstall` keeps the data;
`--purge` deletes it. **Signed releases:** the publisher signs `SHA256SUMS` (the hash of every file,
the images included) with an Ed25519 key; the bundle's hash is checked with `ssh-keygen` before
unpacking, and `install.sh` checks the signature again before installing and on every update,
against the installation's `trusted-publishers/` ([install-offline.md](install-offline.md),
section 2). Bundles for x86_64 and arm64. **Planned:** Windows installer without administrator
rights, wheelhouse for installations without Docker (G11).

**Apps.** Administrators add apps from the Apps page (a signed `.pcapp` file, the online catalog,
or an external app's address) or with `./install.sh --add <file>` ([app-package.md](app-package.md)).
Every package is checked against the publisher keys in `trusted-publishers/` (Ed25519 signature
of the manifest, SHA-256 of the image and of the SBOM), its publisher, permissions and SBOM are
shown before confirming, and every step is in the audit log. A package can never ask to write to
the plant (`plant_write`) or reach outside hosts (`outbound`), nor set its own environment,
volumes or ports. Each app's own token is held to its permissions on every API v1 route: a
package to its signed manifest, an app of the suite's bundle to the `[permissions]` of the
`app.toml` in its image, pinned in the bundle's signed `release.json`, so no app grants itself
more when it starts. Sending text to a language model is a permission of its own (`write.llm`),
and a use of an app outside the suite's bundle has no model until an administrator gives it one.
The online catalog is off until `PLANTCRAFT_APP_CATALOG_URL` is set and an
administrator turns it on; isolated plants leave it off.

Access to the Docker socket is equivalent to root on the host. It is confined to the `installer`
service: PlantCraft and the apps never get it, and PlantCraft only drops requests in a folder
the installer reads. The installer has no network, re-verifies every package with its own
read-only copy of the trusted keys and runs each app under the same hardening as the suite.
**To switch installs off**, set `PLANTCRAFT_APP_INSTALL=off` in `.env` and do not run the
`installer` service (remove it from `compose.yaml` or `docker compose stop installer`); the
Apps page then only lists apps and registers external ones.

## 7. Release integrity and supply chain

SHA-256 sums for every file and for the bundle; base images pinned by digest; Python dependencies
pinned with hashes; CycloneDX SBOMs for the Python dependencies and the web interface, plus the
SBOM an app image carries (`sbom/<app>.json`, View today); PostgreSQL ships as the official
image pinned by digest. CI runs
pip-audit and npm audit on every change (fails on any known vulnerability in shipped Python
packages and on high or critical ones in shipped npm packages). **Partial:** the SBOM does not yet
list the operating-system packages of the images or the Caddy binary (G13).

## 8. IEC 62443-4-2 component requirements (SL1 target; SL2 where noted)

| Requirement | Status |
|---|---|
| CR 1.1 Human user identification and authentication | Met: local accounts, Active Directory or LDAP, OpenID Connect single sign-on |
| CR 1.2 Software process identification | Met: app keys and signed service tokens (API v1) |
| CR 1.5 / 1.7 Authenticator management, password strength | Met: hashed passwords, at least 8 characters, generated admin password |
| CR 1.11 Unsuccessful login attempts | Met: 10 failures block 5 minutes |
| CR 2.1 Authorization enforcement | Met in the API, with a permission test of every route |
| CR 2.8 Auditable events | Yes: central audit log of the changes in PlantCraft and the apps, of AI assistant tool calls and of every sign-in and sign-out, read on Settings › Audit log |
| CR 3.1 / 4.1 Communication integrity and confidentiality | Met on C1 (TLS); C2 depends on the PI and OPC UA servers' TLS settings |
| CR 3.4 Software and information integrity | Met: SHA-256 sums, pinned images; releases and app packages signed (Ed25519) and checked before install and update |
| CR 5.1 Network segmentation | Met: zones Z2 to Z4 above (SL2) |
| CR 7.1 Denial of service protection | Partial: resource limits, sign-in throttling |
| CR 7.3 / 7.4 Backup and recovery | Met: scheduled online backups (the Historian's database full and incremental), a restore drill, backup before upgrade, rollback |
| CR 7.7 Least functionality | Met: non-root, read-only, no capabilities, no admin API, no build tools (SL2) |
| Depends on the client | Host hardening, patching, physical security, disk encryption, central logging |

## 9. Contact

Report vulnerabilities as described in `SECURITY.md`.
