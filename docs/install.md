# Install PlantCraft

> **Updated:** 2026-10-30 · suite 0.5.1

PlantCraft installs on your own machine or server, from one signed bundle, with no internet
connection. This page helps you pick the right way to install it and says what you need on
Linux, macOS and Windows. The step by step for a plant server is
[install-offline.md](install-offline.md); what IT and OT security teams need to approve it is the
[security guide](security-guide.md).

## Pick your path

| You want to | Use | Time |
|---|---|---|
| Try the suite with a simulated plant, on a laptop or a spare machine | The release bundle with `--demo` ([Try it](#try-it-with-the-demo-plant)) | about 10 minutes |
| Install it on a plant server, offline | The release bundle on Linux ([install-offline.md](install-offline.md)) | under 10 minutes, plus your approvals |
| Change the code or build an app | A source checkout ([From source](#from-source-developers)) | 15 minutes |

Every path runs the same containers with the same hardening. Only the source checkout builds
the images on your machine.

## What every installation gets

- **Offline.** The bundle carries every image, the installer and the documentation. Nothing is
  downloaded during the install or afterwards: no telemetry, update check, licence call, web font
  or CDN. `tests/test_offline.py` and `tests/test_isolation.py` hold that in CI.
- **Read-only toward the plant.** PlantCraft and the Historian read OPC UA, PI Web API, MQTT,
  Modbus TCP, SQL and CSV sources; no connector has a write call. Only the Simulator, the demo
  plant, can be written to.
- **One published port.** Browsers reach an HTTPS proxy on port 443; every app sits on an internal
  Docker network with no route out of the host. Each container runs as its own user, with a
  read-only root and no capabilities.
- **Sign-in by default.** The installer creates an administrator with a random password
  (`data/initial-admin-password`); roles are checked on every route and every change goes to the
  audit log.
- **Language models off.** The assistant and the specialists answer with a language model only
  after an administrator sets one up in Settings › Language models, and `PLANTCRAFT_LLM=off`
  forbids them whatever the settings say. The read-only MCP server for people's own AI assistants
  is off too ([assistant-access.md](assistant-access.md)).
- **Signed releases.** Every bundle is signed with the publisher's Ed25519 key and checked twice:
  by you with `ssh-keygen` before unpacking, and by `install.sh` before it changes anything.
- **Never lose data on update.** All state lives in one data folder; an update backs it up first
  and returns by itself when the new version does not come up healthy (`./install.sh --rollback`
  does it by hand).

## What you need

The full list, with measured numbers for the server, the compute workers, the computers that run
Notebooks and how the disk grows: [requirements.md](requirements.md).

| Item | Requirement |
|---|---|
| Processor | x86_64 (`linux-amd64` bundle) or 64-bit ARM (`linux-arm64` bundle, also Apple silicon) |
| Memory | 8 GB for a trial with a few apps; 16 GB with every app on. By plant size: [requirements](requirements.md) |
| Disk | 20 GB free for the install folder; more for long histories (a year of 8,000 signals with its backups is about 1 TB) |
| Docker | Docker Engine 24.0+ with the Compose plugin 2.24+ (Linux), or Docker Desktop (macOS, Windows) |
| Account | On Linux, `root` or a member of the `docker` group. Nothing else: no Python, Node.js, compiler or registry |
| Network | Inbound TCP 443 from the people who use it; outbound only to the plant's data sources you register |

## The release files

Each release has, per processor:

| File | What it is |
|---|---|
| `plantcraft-<version>-linux-<arch>-bundle.tar.gz` | The bundle: images, `compose.yaml`, `install.sh`, `firewall.sh`, SBOMs, this documentation |
| `....tar.gz.sha256` | Its SHA-256 hash |
| `....tar.gz.sha256.sig` | The publisher's signature over that hash |

Check them before you unpack, on any system with OpenSSH 8.1 or later (every supported Linux
and macOS has it; on Windows, in the Ubuntu window of WSL). Why and what each check proves:
[Check a release](verify-a-release.md).

```bash
echo 'release@plantcraft namespaces="file" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMwhizmfd8aZQ1zHpVLpIrrgxv/YlT/ufewCBueO0hnE' \
    > plantcraft.allowed_signers
B=plantcraft-0.5.1-linux-amd64-bundle.tar.gz
ssh-keygen -Y verify -f plantcraft.allowed_signers -I release@plantcraft -n file \
    -s $B.sha256.sig < $B.sha256      # Good "file" signature for release@plantcraft ...
sha256sum -c $B.sha256               # macOS: shasum -a 256 -c $B.sha256
```

Compare the key on the first line with the one on the release page (OpenSSH fingerprint
`SHA256:9l/yDgR8/Pzel1pncxrXz2IGCIhFirKpDT78tO49fG8`, key id `af2643fa16867976`). If either check fails, do not use the
bundle.

On a first install, `install.sh` checks the signature again and then warns "the key above came
with this bundle: compare its key id…". That is expected: it is the same key you just compared
above, and the id it prints is `af2643fa16867976`.

## Linux

The supported platform for a plant: Ubuntu 22.04+, Debian 12+, RHEL, Rocky or Alma 9+, at
Purdue level 3 or in the industrial DMZ. Docker comes from your offline package mirror.

```bash
tar -xzf $B && cd ${B%.tar.gz}
sudo ./install.sh --all-apps            # into /opt/plantcraft
# or, as a member of the docker group, into a folder you own:
./install.sh --all-apps --prefix ~/plantcraft
```

The installer checks the signature, the free disk and the processor, loads the images, writes the
settings with fresh secrets, starts the suite, waits until every container is healthy and prints
the address and where the administrator's password is. The whole procedure, with the settings,
certificates, updates, backups and firewall rules, is [install-offline.md](install-offline.md).

## macOS

For trials, demos and development, on Apple silicon or Intel. A Mac is not a plant server: it
sleeps, and Docker Desktop runs the containers inside a virtual machine.

1. Install [Docker Desktop](https://docs.docker.com/desktop/setup/install/mac-install/) and give
   it at least 8 GB of memory (Settings › Resources; 12 GB with every app on).
2. Use the `linux-arm64` bundle on Apple silicon and `linux-amd64` on Intel (`uname -m` says
   `arm64` or `x86_64`).
3. In Terminal, name the bundle for your Mac, check it as in [The release files](#the-release-files)
   (with `shasum -a 256 -c`), then unpack it and install into a folder of yours, without `sudo`:

   ```bash
   B=plantcraft-0.5.1-linux-arm64-bundle.tar.gz   # Intel Mac: linux-amd64
   tar -xzf $B && cd ${B%.tar.gz}
   ./install.sh --all-apps --demo --prefix ~/PlantCraft
   ```

4. Open the address the installer printed at the end (`https://<your-mac>.local/`: the
   certificate names the Mac, so `https://localhost` is refused) and sign in as `admin` with the
   password it printed (it is shown once, and kept in `~/PlantCraft/data/initial-admin-password`). Your
   browser warns about the local certificate authority the first time: trust
   `~/PlantCraft/local-ca-root.crt` in Keychain Access, or give the proxy your own certificate
   ([install-offline.md](install-offline.md), section 6).

Docker Desktop starts the suite again after a reboot. The project's own test server is a Mac mini
running exactly this.

## Windows

For trials, demos and development on Windows 10 (22H2) or 11, 64-bit. The suite runs in Linux
containers; on Windows they run in Docker Desktop's WSL 2 virtual machine, and `install.sh` runs
in a Linux distribution of WSL. Tested on 2026-10-26 with Docker Desktop 29.9 (Compose 5.6) and
Ubuntu in WSL 2, on an i5-8500T with 24 GB: the install with every app and the demo took about
10 minutes, and its 16 containers used about 4.5 GB of memory.

1. Install [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/) with
   the WSL 2 engine (its installer turns WSL on). **Start it once and accept its terms**: until
   then the engine does not run and `docker` answers with errors.
2. Add Ubuntu to WSL. Once WSL is on this needs no administrator, in PowerShell:

   ```powershell
   wsl --install -d Ubuntu --no-launch
   wsl --set-default Ubuntu
   ```

3. In Docker Desktop, Settings › Resources › WSL integration, turn on **Ubuntu**; without it,
   `docker` is "not found" inside Ubuntu. Give WSL at least 8 GB of memory (12 GB with every app
   on): in `%UserProfile%\.wslconfig`,

   ```ini
   [wsl2]
   memory=12GB
   ```

   then `wsl --shutdown` and start Docker Desktop again.
4. Open **Ubuntu** from the Start menu. Copy the three release files (the `linux-amd64` bundle)
   into your Linux home folder, not under `/mnt/c`: the suite's data folder needs Linux file
   permissions, and Windows folders are slow to read from containers.

   ```bash
   cp /mnt/c/Users/<you>/Downloads/plantcraft-0.5.1-linux-amd64-bundle.tar.gz* ~/
   cd ~ && B=plantcraft-0.5.1-linux-amd64-bundle.tar.gz
   ```

5. Check the bundle (above), unpack it and install, in the same Ubuntu window:

   ```bash
   tar -xzf $B && cd ${B%.tar.gz}
   ./install.sh --all-apps --demo --prefix ~/plantcraft
   ```

6. Open https://localhost in Edge or Chrome on Windows and sign in as `admin` with the password
   the installer printed at the end (shown once; kept in `~/plantcraft/data/initial-admin-password`).
   To stop the browser's certificate warning, import `~/plantcraft/local-ca-root.crt` (from
   Windows: `\\wsl$\Ubuntu\home\<you>\plantcraft\`) into **Trusted Root Certification
   Authorities** of the current user with `certmgr.msc`.

**Known issues of 0.4.0 in WSL**, fixed for the next release:

- `https://localhost` fails with a certificate error, because the installer names the
  certificate after the WSL machine instead. Set `PLANTCRAFT_HOSTNAME=localhost` in
  `~/plantcraft/.env` and run `./install.sh` again (same folder, same flags).
- Running `./install.sh` a second time as a normal user (not `root`) can stop with
  `mkdir: Permission denied` under `data/compute-jobs/` or `data/histcraft/gateway`. Run that
  second time with `sudo`.

If port 443 is taken on Windows (IIS, another proxy), set `PLANTCRAFT_HTTPS_PORT` in
`~/plantcraft/.env` and run `./install.sh` again. Docker Desktop must be running for the suite to
answer; it starts the containers again on its own.

### Windows without Docker Desktop

Docker Desktop needs a paid subscription in companies of 250 people or more, or US$10 million
of revenue or more. Two free ways give the suite the same Linux containers:

- **Docker Engine inside WSL (recommended).** Steps 2, 4, 5 and 6 above, without Docker Desktop.
  Ubuntu 24.04 in WSL starts systemd by default (otherwise add `[boot]` `systemd=true` to
  `/etc/wsl.conf` and run `wsl --shutdown`). On a PC that also has Docker Desktop, Windows' PATH
  makes its `docker.exe` visible inside WSL: add `[interop]` `appendWindowsPath=false` to that
  distribution's `/etc/wsl.conf` and run `wsl --terminate <name>` (`./install.sh --check` says
  so). Install with the Docker Engine the bundle carries:

  ```bash
  sudo apt-get install -y iptables     # the one package Docker needs from Ubuntu
  sudo ./install.sh --install-docker --all-apps --demo --prefix ~/plantcraft
  ```

  Tested on 2026-10-31 (Windows 11, WSL 3.0.3, a new Ubuntu 24.04 distribution next to Docker
  Desktop's, which stayed untouched): Docker installed in 10 s, and came back by itself after
  `wsl --terminate`. WSL may stop a distribution nobody uses; to keep the suite running, start
  it with Windows (a Task Scheduler entry `wsl -d Ubuntu --exec /bin/true` at sign-in).
- **Rancher Desktop** (SUSE, Apache 2.0), **not tested with PlantCraft yet**. Use it instead of
  Docker Desktop in step 1, set up like this:
  1. Preferences › Container Engine: **dockerd (moby)**. The suite needs the Docker API and
     `docker compose`; containerd with nerdctl will not work.
  2. Preferences › Kubernetes: turn it **off**. The suite does not use it, and it takes memory.
  3. Preferences › WSL › Integrations: turn on **Ubuntu**. Rancher Desktop then gives Ubuntu
     its Docker socket, and its Linux `docker` comes in through Windows' PATH.
     `./install.sh --check` accepts that `docker`. It refuses only Docker Desktop's.
  4. The memory limit is the same `%UserProfile%\.wslconfig` as in step 3 above (Rancher
     Desktop runs in WSL 2 too).
  5. Run steps 4 to 6 above as written, without `--install-docker`.

  If `./install.sh --check` says "Docker Compose missing", install the compose plugin inside
  Ubuntu (`sudo apt-get install docker-compose-plugin` from Docker's apt repository).

`./install.sh --check` names the Docker it found and warns when it is Docker Desktop.

**Notebooks on Windows.** People who want JupyterLab on their own computer install the
PlantCraft Notebooks kit from the Notebooks page: a setup for the current user only, no
administrator and no Docker, installed in about two minutes ([Notebooks](en/notebooks.md)).

## Try it with the demo plant

`--demo` adds the Simulator, an OPC UA plant of 50 control loops with known faults, and fills the
suite with a story that explains it by itself: the plant map, three weeks of history, monitors
already running, dashboards, alarm rules, model examples, a team with its conversations and a
specialist. The tutorial [Getting started](en/getting-started.md) walks through it.

```bash
./install.sh --all-apps --demo
```

`--public-demo` is the same story left open to visitors, with a read-only account `demo` on the
sign-in page and the language models off ([install-offline.md](install-offline.md), section 3).

## From source (developers)

Requirements: Python 3.12 or 3.13 (asyncua, the OPC UA library, fails on 3.15:
[#10](https://github.com/PlantCraft/PlantCraft/issues/10)), Node.js 22 and Docker.

```bash
git clone https://github.com/PlantCraft/PlantCraft.git plantcraft && cd plantcraft
make image simcraft-image       # build the images here
deploy/install.sh --dev --demo     # the same hardened stack as the bundle
```

Or without containers, PlantCraft and the Simulator only:

```bash
python3 -m pip install -e sdk/python -e ".[server,opcua]" -e simulator
python3 run_opcua_demo.py --browser
```

The rules every change follows are in [AGENTS.md](../AGENTS.md); building an app of your own
starts from the [app template](../templates/app).

## After the install

| Next | Where |
|---|---|
| Connect the plant: a PI Web API or OPC UA source, then the signals and assets | [User guide](en/user-guide.md), Historian › Sources |
| Load the plant map at once from Excel or JSON | [Configuration file](en/configuration-file.md) |
| Add people and groups, decide who opens which app | [User guide](en/user-guide.md), People |
| Certificates, backups, updates, the firewall | [install-offline.md](install-offline.md), [Running the suite](en/running-the-suite.md) |
| Run calculations on other machines | [Compute workers](compute.md) |
| Turn on the assistant (off until you connect a model), or the MCP server | [Turn it on](assistant.md#turn-it-on), [assistant-access.md](assistant-access.md) |
| Hand the installation to IT and OT security | [Security guide](security-guide.md) ([português](pt-BR/security-guide.md)) |

## Remove it

```bash
./install.sh --uninstall           # stops and removes the containers; data and backups stay
./install.sh --uninstall --purge   # also deletes the data, the backups and the images
```

`--purge` keeps an image that a container of another installation on the same Docker was
created from (a test and a production installation side by side) and says which. An
installation whose containers were already removed cannot be seen: its images go.
