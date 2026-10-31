# Offline installation with Docker

For the IT administrator of a plant. This guide installs the PlantCraft suite on a Linux server
**without internet access**, from the release bundle `plantcraft-<version>-linux-<arch>-bundle.tar.gz`.
Target: under 10 minutes from copying the bundle to the first sign-in. The security design behind
it is summarised in [security-guide.md](security-guide.md). For a trial on macOS or Windows,
and to choose between the ways to install, start at [install.md](install.md).

## 1. What you need

| Item | Requirement |
|---|---|
| Server | Linux on x86_64 (`amd64` bundle) or 64-bit ARM (`arm64` bundle: Ampere, Graviton, Apple silicon under Docker Desktop); Ubuntu 22.04+, RHEL/Rocky/Alma 9+, Debian 12+; at Purdue level 3 or in the industrial DMZ |
| Resources | 4 vCPU, 8 GB RAM, 20 GB free disk for the install folder (more for long histories); 16 GB RAM with every app on. By plant size, with measured numbers: [requirements.md](requirements.md) and [en/sizing.md](en/sizing.md) |
| Docker | Docker Engine 24.0+ with the Compose plugin 2.24+ (`docker compose version`) |
| Account | `root`, or a user in the `docker` group (treat that group as root: it controls the daemon) |
| Network | Inbound TCP 443 from the users' network; outbound only to the PI Web API and OPC UA servers |

Docker itself must come from your offline package mirror (Docker's or your distribution's
packages); the bundle does not install it. Nothing else is needed: no Python, Node.js, compiler or
registry access.

## 2. Bring the bundle to the server and check it (1 minute)

Each release has one bundle per processor: `linux-amd64` for x86_64 servers and `linux-arm64`
for 64-bit ARM ones (`uname -m` says `x86_64` or `aarch64`). The installer refuses a bundle for
the other processor (`--allow-emulation` runs it emulated, several times slower). Copy three
files of the release to the server: the bundle, its `.sha256` and the signature of that hash,
`.sha256.sig`. Then check that the bundle is the one the publisher signed **before unpacking
it**, with `ssh-keygen` (OpenSSH 8.1 or later, already on every supported Linux and on macOS):

```bash
# The publisher's key, once: this line, compared with the one on the release page.
echo 'release@plantcraft namespaces="file" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMwhizmfd8aZQ1zHpVLpIrrgxv/YlT/ufewCBueO0hnE' \
    > plantcraft.allowed_signers
B=plantcraft-0.5.1-linux-amd64-bundle.tar.gz
ssh-keygen -Y verify -f plantcraft.allowed_signers -I release@plantcraft -n file \
    -s $B.sha256.sig < $B.sha256        # Good "file" signature for release@plantcraft ...
sha256sum -c $B.sha256                 # plantcraft-...tar.gz: OK  (macOS: shasum -a 256 -c)
tar -xzf $B
cd ${B%.tar.gz}
```

The publisher **PlantCraft** signs every release with one Ed25519 key:

| | |
|---|---|
| Key id (what `install.sh` prints) | `af2643fa16867976` |
| OpenSSH fingerprint (`ssh-keygen -l`) | `SHA256:9l/yDgR8/Pzel1pncxrXz2IGCIhFirKpDT78tO49fG8` |
| Public key (PEM) | `trusted-publishers/processcraft.pub` in the bundle and in the repository |

If `ssh-keygen` does not say `Good "file" signature`, or the hash does not match, do not use the
bundle. `install.sh` checks the signature again from the inside (section 3), against the key
the bundle carries, or with `--publisher-key processcraft.pub` against a copy of the key you
keep apart from the bundle.

The bundle holds:

| File | What it is |
|---|---|
| `images.tar` | The container images (`docker save`): `processcraft`, `processcraft-proxy` (Caddy), `processcraft-installer`, and the apps the release includes (table below) |
| `compose.yaml` | The services, networks and hardening of the suite |
| `install.sh` | Install, update, rollback, backup, restore and uninstall |
| `firewall.sh` | Optional outbound rules for the plant network (section 8) |
| `.env.example`, `bundle.env` | Settings template; versions and image ids of this release |
| `sbom/` | CycloneDX software bills of materials, and `<app>.json` for an app image that carries its own |
| `release.json`, `RELEASE-NOTES.md` | Version of the suite and of each module, the oldest version it updates (`upgrade_from`), every image id; what changed in each module |
| `SHA256SUMS` | Hash of every file above; `install.sh` checks it before doing anything |
| `SHA256SUMS.sig` | The publisher's Ed25519 signature over `SHA256SUMS`; every install checks it (section 3), an update against the installation's `trusted-publishers/` (section 7) |
| `notebook-kits/` | Optional: the Notebooks kits for people's computers (Windows, macOS, Linux; `kits.json` lists them), offered in Notebooks while Notebooks are on (an administrator may take them away) |
| `trusted-publishers/` | The publisher keys of the release (`processcraft.pub`, and `processcraft.allowed_signers` for `ssh-keygen`), trusted by the installation from then on |
| `docs/` | This guide and the security guide |
| `demo/plantcraft-50-loops-map.json` | With the Simulator only: the plant map of its 50 loops (section 4) |

## 3. Install (3 to 6 minutes)

```bash
sudo ./install.sh                         # installs into /opt/plantcraft
# or, as a member of the docker group, into a folder you own:
./install.sh --prefix /srv/processcraft
```

The apps of the suite, each in its own container and Compose profile, turned on with a flag
(`bundle.env` lists the ones this bundle carries; a flag for an app it lacks stops with a
message):

| App | Flag (profile) | Address | Container user | Data |
|---|---|---|---|---|
| Analytics, control loop performance and signal quality | `--with-linkcraft` (on by default when bundled) | `/link/` | 10012 | `data/linkcraft/` |
| View, dashboards, reports and trends | `--with-dashcraft` | `/dash/` | 10006 | `data/dashcraft/` |
| Historian, process historian | `--with-histcraft` | `/hist/` | 10008 | `data/histcraft/`, and its PostgreSQL database `histcraft-db` in `data/histcraft-db/` |
| PlantCraft Alarms (alarmcraft), ISA-18.2 alarm management | `--with-alarmcraft` | `/alarm/` | 10009 | `data/alarmcraft/` |
| PlantCraft Models (modelcraft), Modelica workbench with an OpenModelica runner | `--with-modelcraft` | `/model/` | 10011 | `data/modelcraft/`; its runner `modelcraft-executor` works on `data/compute-jobs/modelcraft/` (docs/compute.md) |
| the Simulator, the OPC UA plant simulator | `--demo` | `opc.tcp://plantcraft:4840/plantcraft/` | 10004 | `data/simcraft/` |

`--all-apps` turns on every app of the bundle (not the Simulator: add `--demo` for a trial, e.g.
`./install.sh --all-apps --demo`). Flags add apps; they never turn one off: remove its profile
from `COMPOSE_PROFILES` in `.env` and run `./install.sh` again. The Simulator is its own product
and image (`simcraft`); `--demo` stops with a message when the bundle does not carry it. An
installation that had an app or the demo keeps running without it, with a warning, after an
upgrade to a bundle without that image.

`--public-demo` is `--demo` for an installation left open to visitors: it also writes the demo
story (`plantcraft demo seed`: the plant map, the Simulator's last 48 hours copied into the Historian,
loop criticalities, Analytics' three monitors (loops, signals, the Furnaces model), dashboards with a
public link, Analytics' model examples of the plant (the Furnaces model names the drifting
sensor), the suggested alarms of every loop with the story's alarms and two
days of their history, a team of three with a conversation, a scripted valve specialist and
actions) and turns on `PLANTCRAFT_PUBLIC_DEMO`: the sign-in page offers "Enter the demo", a
visit of the read-only visitor account `demo` in one of ten places, for as long as it is used (it ends 30 minutes after the last use), with a line
to wait in when every place is taken ([public-demo.md](public-demo.md)); the home page shows a
tour, visitors try the apps' editors but nothing is saved (not even a message), language models
stay off for them and each visit's requests are held to a few at once (only requests
through the proxy count; the apps' own calls inside the network do not).
The administrator account stays private. The seed can be run again on any installation with the
demo plant: `docker compose exec processcraft processcraft demo seed`. The journeys in
`tests/e2e_suite` walk that story in a browser: `make e2e-suite SUITE_URL=https://host/`.

The Historian reads its own sources (OPC UA, PI Web API, CSV files dropped in
`data/histcraft-csv/`), created on its Sources page: like PlantCraft it sits on the plant
network (restricted by `firewall.sh`, section 8), and on the demo network to reach the Simulator.
It needs no app key; its source passwords are encrypted with `data/histcraft/secret.key`, which
belongs in every backup.

`install.sh` then, in order:

1. checks the Docker Engine and Compose versions;
2. checks every file of the bundle against `SHA256SUMS` and stops at the first mismatch, and
   that the bundle is built for this server's processor;
3. loads the images with `docker load` (no download: `pull_policy: never` everywhere), then
   checks the publisher's signature over `SHA256SUMS` (so over every file, `images.tar`
   included) and prints who signed it and the key id; an unsigned bundle, or one signed by
   another key, stops here with nothing started (`--allow-unsigned` for a development bundle);
4. copies `compose.yaml`, `install.sh`, `firewall.sh` and `.env` into the install folder;
5. creates `data/` with one folder per container user and generates the administrator password
   (`data/initial-admin-password`) and the Historian's database password
   (`data/histcraft-db-password`), mode 0600, written only once;
6. starts the suite and waits until every container reports healthy;
7. for each app turned on that uses one (all but the Historian), the first time: has PlantCraft issue its app key (listed under
   **Users and app keys**, recorded in the audit log), writes it to `data/<app>-app-key` (the
   app's user, mode 0600) and restarts the app, so its background work runs without a manual
   step;
8. prints the address, the administrator account and the password.

```text
PlantCraft is running: https://processcraft.plant.example/
  Administrator: admin
  Password:      <24 random characters>
  (shown once; stored in /opt/plantcraft/data/initial-admin-password, mode 0600)
  HTTPS:         local CA; install this root certificate in the browsers: /opt/plantcraft/local-ca-root.crt
  Took 97 s. Backups: /opt/plantcraft/backups
```

Measured on a test machine (2026-10-19, bundle of 197 MB): 97 seconds for a first install
(30 seconds to load the images, the rest for the first start and the health checks), 26 seconds
for an upgrade including the backup, 20 seconds for a rollback. Slow disks take longer to load
the images. If the suite does not become healthy,
`install.sh` prints the container states and their last log lines and stops.

## 4. First sign-in (2 minutes)

1. Open the printed address and sign in as `admin` with the printed password.
2. Add the data sources in **Sources and signals** (PI Web API or OPC UA); with `--demo`, the
   simulator is at `opc.tcp://plantcraft:4840/plantcraft/`, namespace
   `urn:processcraft:plantcraft`, anonymous, 50 loops under `CPM/Loops`.
3. Import the asset tree (**Assets › Import**: Excel, JSON, CSV, ISA-95 or PI AF; the last
   import can be undone there) and create the people who will use the suite. With `--demo`
   the map of the simulator (the bundle's `demo/plantcraft-50-loops-map.json`: the Simulator
   source, the unit, the 50 loops with their signals by role and each loop's type) is already
   imported by `plantcraft demo seed`. A whole map can still be applied by script
   ([configuration file](en/configuration-file.md)).
4. Open the apps from the launcher; they use the same sign-in. Analytics analyses the loops of
   the map in its next round (every 10 minutes), or at once with **Run round**, and checks every
   signal's quality on its own schedule (`LINKCRAFT_SIGNAL_ROUND_MINUTES`, 15 by default); View builds dashboards of the signals and assets. The Historian
   archives the OPC UA variables you pick: in the Historian, **Sources > Add source**
   (`opc.tcp://plantcraft:4840/plantcraft/` with `--demo`), browse, pick the variables, archive.

The administrator password is the content of `data/initial-admin-password`. To change it, write
the new password into that file (one line) and run `docker compose restart processcraft` in the
install folder. Keep it as the emergency account; people sign in with their own accounts.

## 5. Settings

Settings live in `.env` in the install folder; `install.sh` creates it on the first install and
afterwards only updates the version lines. After a change, run `./install.sh` again from the
install folder: the copy kept there works on its own folder, needs no bundle and only applies
settings and certificates.

| Variable | Default | Effect |
|---|---|---|
| `PLANTCRAFT_HOSTNAME` | the server's name and IP | Names users type, separated by spaces; the HTTPS certificate must cover them |
| `PLANTCRAFT_BIND_ADDRESS` | `0.0.0.0` | Host address of the HTTPS port; set the users' interface to publish on that one only |
| `PLANTCRAFT_HTTPS_PORT` | `443` | The only published port |
| `COMPOSE_PROFILES` | empty | `linkcraft`, `dashcraft`, `histcraft`, `alarmcraft`, `modelcraft`, `demo`, comma-separated; `install.sh` keeps `PLANTCRAFT_APPS` (the launcher's list) in step |
| `LINKCRAFT_VERSION`, `DASHCRAFT_VERSION`, `HISTCRAFT_VERSION`, `ALARMCRAFT_VERSION`, `MODELCRAFT_VERSION` | from the bundle | Image of each app; set by `install.sh` |
| `LINKCRAFT_SIGNAL_ROUND_MINUTES`, `LINKCRAFT_SIGNAL_WINDOW_HOURS` | `15`, `24` | Analytics' Signal quality schedule and window at its first start (then changed in Analytics) |
| `HISTCRAFT_URL` | empty | Optional data layer. Empty: PlantCraft reads its own sources. With the Historian on, `http://histcraft:8100/hist` makes the Historian the data layer (sources kept in the Historian, signals and series read through it) |
| `SIMCRAFT_VERSION` | `0.5.1` | Image of the `demo` profile; set by `install.sh` from the bundle |
| `PLANTCRAFT_ADMIN_USERNAME` | `admin` | Emergency administrator |
| `PLANTCRAFT_MACHINE` | `auto` | The machine profile (below): `small`, `medium`, `large`, `xlarge`, `auto` or `off`; `--machine` sets it |
| `PLANTCRAFT_MAX_CPUS`, `PLANTCRAFT_MAX_MEMORY` | empty | On a shared server, the most the profile sizes for (`6`, `12g`) |
| `PLANTCRAFT_CPUS`, `PLANTCRAFT_MEMORY` | `4`, `4g` | Container limits (also `LINKCRAFT_*` `4`/`4g`; `DASHCRAFT_*`, `HISTCRAFT_*` `2`/`2g`; `HISTCRAFT_DB_MEMORY` `2g`, with `HISTCRAFT_DB_SHARED_BUFFERS` `512MB` and `HISTCRAFT_DB_CACHE_SIZE` `1GB`: about 1/4 and 1/2 of it); `install.sh` lowers a CPU limit above the host's CPU count, which Docker would refuse |
| `PLANTCRAFT_PLANT_SUBNET`, `_APPS_SUBNET`, `_EDGE_SUBNET`, `_DEMO_SUBNET`, `_HISTDB_SUBNET` | `172.30.10-14.0/24` | Change only if they clash with a plant or office network |
| `PLANTCRAFT_PROXY_ADDRESS` | `172.30.11.250` | The proxy's address in the apps subnet (change it with `_APPS_SUBNET`): PlantCraft trusts the client address forwarded by this address only |
| `PLANTCRAFT_DNS` | empty | DNS server PlantCraft asks for names outside the suite. Empty: none, so PI and OPC UA servers are given by IP address; set the plant's DNS server to give them by name |

### Machine profile

One choice sizes the whole suite: every container's CPU and memory limit, how many processes
PlantCraft and the Historian run, how many analyses Analytics runs at once and the slots of its
compute worker, Models' runs, the Historian's read budget and its database's memory. `install.sh`
picks it on every run from the CPUs and memory Docker sees (Docker Desktop: its virtual machine,
not the computer), within `PLANTCRAFT_MAX_CPUS` and `PLANTCRAFT_MAX_MEMORY` when they are set,
or from `--machine`:

| Profile | Machine | Picked when |
|---|---|---|
| `small` | 2 CPUs, 4 GB (needs 2 GB of swap with every app on) | 2 CPUs or less, or under 6 GB |
| `medium` | 4 CPUs, 8 GB | 4 CPUs or less, or under 14 GB |
| `large` | 8 CPUs, 32 GB | 8 CPUs or less, or under 48 GB |
| `xlarge` | 16 CPUs or more, 64 GB | more |

The values are one table in `install.sh` (`MACHINE_TABLE`); the ones it wrote last are kept in
`data/machine-profile.env`. A value changed by hand in `.env` is never overwritten: the profile
only replaces a value that is still its own (or the shipped default). `PLANTCRAFT_MACHINE=off`
leaves every value as it is. The measurements behind the table are in `docs/bench/README.md`
("CPU, processes and the machine profile").

## 6. Certificates

HTTPS is always on; the proxy is the only published port.

- **Your certificate (recommended).** Put `cert.pem` (server certificate followed by the
  intermediates) and `key.pem` (unencrypted private key) in `certs/` in the install folder and run
  `./install.sh` again. It gives the key to the proxy's user (mode 0400) and restarts the proxy.
  The certificate must name every entry of `PLANTCRAFT_HOSTNAME`.
- **Local certificate authority (fallback).** Without those files the proxy issues its own
  certificate from a local CA created on the first start. Distribute `local-ca-root.crt` from the
  install folder to the browsers (for example by group policy) to avoid the browser warning. The
  CA's private key stays in `data/proxy/`.

Renewal: replace the two files and run `./install.sh` again. The proxy never contacts a
certificate authority, OCSP responder or update server.

## 7. Update, rollback, backup

**Update.** Read `RELEASE-NOTES.md` in the new bundle, extract it anywhere and run its installer
against the same folder:

```bash
cd plantcraft-0.5.1-linux-amd64-bundle
sudo ./install.sh --prefix /opt/plantcraft
```

Every update takes the same path (`docs/operations.md`, section 3):

1. **Check, change nothing.** It refuses the bundle, with nothing changed, when a file does not
   match `SHA256SUMS`, the signature (`SHA256SUMS.sig`) is missing or not from a publisher in
   the installation's `trusted-publishers/`, the bundle is older than what runs (going back is
   `--rollback`), the installed version is below the bundle's `upgrade_from`, another backup or
   restore is running, or the disk lacks room for the new images and twice the data. The
   signature is checked by the installer image already installed, never by the new one. A
   development bundle needs `--allow-unsigned`. An installation that trusts no publisher yet
   (one made from an unsigned 0.2.0 bundle) checks the first signed update against the key that
   bundle carries, says so, and trusts it from then on; `--publisher-key FILE` checks it against
   your own copy of the key instead.
2. **Back up.** A `pre-update` backup while the suite still runs (section 2 of
   `docs/operations.md`: SQLite copied online, the Historian's database by blocks, settings, image ids),
   verified before it counts.
3. **Apply.** Loads the images, writes the settings, starts the suite.
4. **Verify.** Every service healthy within `PLANTCRAFT_WAIT_SECONDS` (600) and running the
   image of the new version.
5. **Return by itself** when step 3 or 4 fails, or the script is interrupted: it saves what the
   failed attempt looked like (`update-<date>-<version>-failed.log`, `docker compose ps` and the
   last log lines, mode 0600) and restores the `pre-update` backup, so the old version runs again
   with its data. The outcome of each update is in the operations history
   (`data/installer/status/update.json`).

An installation of 0.1.0 has no backup engine yet: its update to the next version uses the
earlier stop-and-copy backup (`backups/<date>-<old version>/`, `backups/LATEST`).

**Rollback.** From the install folder:

```bash
sudo ./install.sh --rollback
```

It restores the `pre-update` backup of the last update, so the version before it runs again with
its settings, images and data. The data written since is not deleted: it is set aside in
`backups/<date>-before-restore/`. Any other backup: `./install.sh --list-backups` and
`./install.sh --restore <name>`.

**Backups.** The suite backs itself up every night at 02:00 while it runs, checks each backup,
and every Sunday restores the latest into an isolated copy to prove it can be used
(`docs/operations.md`, section 2). By hand: `sudo ./install.sh --backup`. They live in
`backups/` (root only); copy that folder off the server, encrypted, as you would any confidential
plant data. `data/processcraft/sources.key` encrypts the source passwords typed in the
interface: it is in every backup with the database.

**Apps.** The suite starts with PlantCraft; add apps on the Apps page (administrators) or from
the install folder with the same checks:

```bash
sudo ./install.sh --add linkcraft-0.1.0.pcapp  # verify, load, start, route under its prefix
sudo ./install.sh --remove linkcraft           # stop and unroute; data/apps/linkcraft is kept
```

A package installs only if its publisher's public key is in `trusted-publishers/` (copy the
`.pub` file the publisher gives you there; `install.sh` copies the bundle's ones). An app added
from the command line has no app key yet: click "Give it an app key" on the Apps page. The
online catalog is off: isolated plants keep it off and install from files; to use it, set
`PLANTCRAFT_APP_CATALOG_URL` in `.env`, restart, and turn it on in the Apps page. Format and
folders: [app-package.md](app-package.md).

## 8. Firewall rules

| Direction | From | To | Port | Why |
|---|---|---|---|---|
| Inbound | Users' network | PlantCraft server | TCP 443 (or `PLANTCRAFT_HTTPS_PORT`) | Browsers to the proxy |
| Outbound | PlantCraft server | PI Web API servers | TCP 443 | Read history (read-only account) |
| Outbound | PlantCraft server | OPC UA servers | TCP 4840 (or as configured) | Read values and history (PlantCraft and the Historian) |
| Inbound | Administrators | PlantCraft server | TCP 22 | Your usual server administration |
| Outbound, only if set up | PlantCraft server | The company's language model or gateway | As configured | Specialists answering with a language model (off by default, [collaboration.md](collaboration.md)); list it with `firewall.sh --allow` |
| Inbound, only if turned on | People's AI assistants | PlantCraft server | TCP 443, path `/mcp` | The read-only MCP server (off by default, [assistant-access.md](assistant-access.md)); same port and proxy as the browsers |

Nothing else is needed, in either direction (the two "only if" rows stay closed by default): no DNS to the internet, no NTP from the containers
(they use the host clock), no update or licence server. Add the plant's DNS server (UDP and TCP
53) only when `PLANTCRAFT_DNS` is set.

Inside the server, the networks already separate the containers: the apps network has no route
out of the host, the proxy's network has no outbound NAT, and the Simulator (with `--demo`) shares
an internal network with PlantCraft and the Historian only, and the Historian's database `histcraft-db`
sits alone with the Historian on the internal `histdb` network, out of reach of every other
container. No container resolves a name outside the suite:
Docker's resolver answers the service names and would forward any other lookup through the
host, past the rules below, so the proxy and the Simulator send it to `127.0.0.1` inside their own
container, where it fails at once, and PlantCraft does the same unless `PLANTCRAFT_DNS` names
the plant's DNS server. Docker's published ports bypass
host firewalls such as `ufw` and `firewalld` zones, so restrict the outbound traffic of the
PlantCraft container itself in Docker's `DOCKER-USER` chain:

```bash
sudo ./firewall.sh --allow 10.20.0.15:443 --allow 10.20.0.40:4840          # show the rules
sudo ./firewall.sh --allow 10.20.0.15:443 --allow 10.20.0.40:4840 --apply  # install them
```

The rules let the plant network open connections only to the listed `host:port` pairs and stop
any new outbound connection from the proxy. They do not survive a reboot: save them with
`iptables-save`/`netfilter-persistent`, or run the script from a boot unit after Docker starts.

## 9. Operations

| Task | Command (in the install folder) |
|---|---|
| State and health | `docker compose ps` |
| Logs | `docker compose logs -f --tail 100 processcraft` |
| Restart one part | `docker compose restart proxy` |
| Stop and start | `docker compose stop` / `docker compose start` |
| Apply settings or certificates | `./install.sh` |
| Uninstall, keep data | `./install.sh --uninstall` |
| Uninstall and delete data, backups and images | `./install.sh --uninstall --purge` |

A page saying "This application is not running" under `/link/`, `/dash/` or
`/hist/` means that app's container is not up: check `COMPOSE_PROFILES` and `docker compose ps`.

## 10. Install folder

```text
/opt/plantcraft/
  compose.yaml  .env  install.sh  firewall.sh  bundle.env  local-ca-root.crt
  certs/        cert.pem and key.pem, when you provide them
  data/         processcraft/ (database, sources.key, session secret), linkcraft/,
                dashcraft/, alarmcraft/, modelcraft/, compute-jobs/, histcraft/, histcraft-db/ (PostgreSQL), proxy/ (local CA), simcraft/,
                histcraft-csv/ (CSV files the Historian reads), initial-admin-password, <app>-app-key,
                histcraft-db-password
  backups/      one folder per backup (<date>-<reason>: daily, manual, pre-update, ...)
```

Each container runs as its own user (10001 PlantCraft, 10003 proxy, 10004 the Simulator,
10005 installer, 10006 View, 10008 Historian and its database, 10009 PlantCraft Alarms, 10010 (PlantCraft Twin, retired),
10011 PlantCraft Models and its Modelica runner, 10012 Analytics)
and owns only its folder of `data/`. `install.sh` sets these owners through a
short-lived container, so a member of the `docker` group needs no `sudo`.

## 11. Building a bundle (release managers)

On a machine with internet, Docker, bash 4 or newer and the GNU tools (`sed -i`, `find -printf`),
from a green `main`, once per processor. Linux has them; on macOS, install them and put them first
on the PATH, and keep the temporary folder on a case-sensitive volume (the Notebooks kits hold
files whose names differ only in case):

```bash
brew install bash gnu-sed findutils coreutils gnu-tar grep
export PATH="$(brew --prefix)/opt/gnu-sed/libexec/gnubin:$(brew --prefix)/opt/findutils/libexec/gnubin:$(brew --prefix)/opt/coreutils/libexec/gnubin:$(brew --prefix)/opt/gnu-tar/libexec/gnubin:$(brew --prefix)/opt/grep/libexec/gnubin:$(brew --prefix)/bin:$PATH"
export TMPDIR=/Volumes/<a case-sensitive APFS volume>/tmp   # or build without kits: NOTEBOOK_KITS=none
```

`make bundle` ships an app only when its image of this version is
already built, so a release starts with `make release-bundle`:

```bash
make release-bundle  # every app's image (make apps-images), then make bundle
make bundle          # the platform (+ the Simulator) and the app images already built
make isolation       # the isolation tests against the built images (tests/test_isolation.py)
# The arm64 bundle on an x86_64 machine (QEMU registered in binfmt_misc), or the other way round:
make bundle ARCH=arm64 DOCKER_BUILD_FLAGS="--platform linux/arm64"
```

The result is `dist/plantcraft-<version>-linux-<arch>-bundle/` and its `.tar.gz` with a
`.sha256` file to publish with the release. `ARCH` (`amd64` or `arm64`, default the build
machine's) names the bundle and `bundle.env`; every image must be built for it (each app with
`make image DOCKER_BUILD_FLAGS="--platform linux/<arch>"` in its repository, PostgreSQL with
`docker pull --platform linux/<arch>` of the digest), or `bundle.sh` stops and says which is
not. The web interfaces are built on the build machine's own processor (`FROM
--platform=$BUILDPLATFORM`): their files are the same for both, so only the Python stages run
emulated. One processor's images are tagged like the other's, so build and bundle one after the
other.

**Signing.** With `RELEASE_KEY=/path/processcraft.key` (the publisher's private key, Ed25519 PEM,
never in a repository or on a build server), `bundle.sh` writes `SHA256SUMS.sig` inside the
bundle and `<bundle>.tar.gz.sha256.sig` beside it. The key can stay on an offline machine
instead, since only two small files are signed there (docs/operations.md, section 3). The key
id, the OpenSSH fingerprint and the `allowed_signers` line to publish come from
`python -m plantcraft.apps.release fingerprint deploy/trusted-publishers/processcraft.pub --publisher processcraft`.

Each app is included when its image `<app>:$<APP>_VERSION` exists
locally (built in its folder, `apps/<app>`, with `make image`; `LINKCRAFT_VERSION`,
`DASHCRAFT_VERSION`, `HISTCRAFT_VERSION`, `ALARMCRAFT_VERSION`, `MODELCRAFT_VERSION`, default the suite's version), the Historian only with its
PostgreSQL image (`docker pull` the digest `compose.yaml` names, once), and the Simulator when
`simcraft:$SIMCRAFT_VERSION` (default `0.5.1`) does.
The Simulator lives in `simulator/`: `make simcraft-image` builds its image from the
folder at `SIMCRAFT_SRC` (default `simulator`, which must be that version), and
`make bundle` and `make isolation` run it whenever that folder exists. A Simulator image
built elsewhere only needs to be loaded (`docker load`) under that tag before `make bundle`.

`make isolation` runs the Simulator's own image when it is built. Without it, as in CI (which
does not build the Simulator), a stand-in on the demo network answers at
`plantcraft:4840`, so the checks of who can reach the plant still run; the OPC UA conversation
itself is tested by `tests/test_opcua_demo.py` against a small asyncua server
(`tests/opcua_plant.py`) that serves the nodes the demo scenario reads. `cyclonedx-py` (`pip install cyclonedx-bom`) and npm write the SBOMs; without them the
bundle is built without SBOMs and says so (CI always produces them). Behind a TLS-inspecting
proxy, add `BUILD_CA=/path/to/ca.pem`; to use a registry mirror holding the same digests, pass
`DOCKER_BUILD_FLAGS="--build-arg PYTHON_IMAGE=... --build-arg NODE_IMAGE=..."` and
`PROXY_BUILD_FLAGS="--build-arg CADDY_IMAGE=..."`. The Python dependencies of the image are
pinned with hashes in `deploy/requirements.lock` (`make lock` regenerates it).

For development, `make image simcraft-image && deploy/install.sh --dev --demo` runs the same stack from the
checkout, with its settings and data in `deploy/` (git-ignored).
