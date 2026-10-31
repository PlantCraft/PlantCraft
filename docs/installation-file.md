# The installation file (draft)

> Draft for review (PlantCraft/PlantCraft draft PR). Nothing here is released yet.

Some choices belong to whoever installs the server, not to the administrators who use PlantCraft
afterwards: which apps exist, how much of the machine the suite may take, the network it listens
on and the security ceilings (language models, installing apps from the web). They live in one
file **outside the platform**, `/etc/plantcraft/installation.conf`:

- owned by root, mode 644 or stricter, or `install.sh` refuses it (like sshd's `StrictModes`);
- never mounted in a container, so no account inside PlantCraft, and no flaw in it, can change it;
- read by `install.sh` on every run (install, update, "apply settings"); its values win over the
  command line and over `.env`;
- what it decided is listed in `.env` as `PLANTCRAFT_INSTALLATION_LOCKED` with the file's SHA-256
  (`PLANTCRAFT_INSTALLATION_CONF_SHA256`), so Settings › Installation can show each value as
  *Set by the installation* and the audit log can tell when it changed.

This is the pattern GitLab (`/etc/gitlab/gitlab.rb` + `gitlab-ctl reconfigure`), Mattermost
(settings set by environment are read-only in the System Console) and Grafana (provisioned
resources cannot be saved from the interface) use.

## Keys

See [`deploy/installation.conf.example`](../deploy/installation.conf.example). In short:

| Key | Values | Becomes |
|---|---|---|
| `APPS` | `all` or a list of analytics, historian, view, alarms, models, documents | the Compose profiles; apps left out are switched off |
| `WEB_APP_INSTALL` | on, off | `PLANTCRAFT_APP_INSTALL` |
| `DEMO` | off, on, public | `--demo` / `--public-demo` |
| `MACHINE` | auto, small, medium, large, xlarge, off | `install.sh --machine` (machine profile) |
| `MAX_CPUS`, `MAX_MEMORY` | numbers | ceiling for the machine profile (to wire) |
| `MAX_SIGNALS`, `MAX_PARALLEL_RUNS`, `MAX_SESSIONS` | numbers | load ceilings (to enforce in the apps) |
| `HOSTNAME`, `HTTPS_PORT`, `BIND_ADDRESS` | | the same `PLANTCRAFT_*` |
| `NETWORK_BASE` | like `172.30` | the seven internal subnets and the proxy address |
| `LLM` | off, on | `PLANTCRAFT_LLM` (off forbids models everywhere) |
| `TIMEZONE`, `LOCK_TIMEZONE` | IANA name, yes/no | `PLANTCRAFT_TIMEZONE`, `PLANTCRAFT_TIMEZONE_LOCKED` |

## Requirements check

`./install.sh --check` (or `./preflight.sh`, `--json` for tools) checks the server for the apps
of the file and changes nothing: system, processor, Docker Engine and Compose versions, Docker
Desktop (licence warning), control groups, CPUs and memory as Docker sees them, swap, free disk
(install folder and Docker's), the HTTPS port, the internal networks against the host's routes,
the clock, and the file's own owner and mode. `install.sh` runs it first and stops on a FAIL
before anything changes (`PLANTCRAFT_SKIP_CHECK=1` skips it).

## Setup wizard

`sudo python3 wizard/wizard.py` from the bundle folder opens the installer's screens in a browser
(127.0.0.1 only; the address carries a random key, new on each start and valid while the wizard
runs; from another computer through `ssh -L`). It asks the apps, runs the requirements check for
them (including that the folder is a complete release bundle), asks the other choices above, shows the file, writes it as root and, with `--apply`,
runs `install.sh --config` and shows its log. Standard library only.
