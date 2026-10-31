#!/usr/bin/env bash
# PlantCraft offline installer (docs/install-offline.md).
#
#   ./install.sh                 install, or update an existing installation: the bundle is checked
#                                (signature, versions, disk), a backup is taken, and when the new
#                                version does not come up healthy the suite returns by itself
#   ./install.sh --rollback      return to the version before the last update (its backup)
#   ./install.sh --backup        back up now, while the suite runs (verified; docs/operations.md)
#   ./install.sh --list-backups  the backups and their state
#   ./install.sh --restore NAME  return to a backup; the current state is set aside, not deleted
#   ./install.sh --export-backup NAME --passphrase-file FILE [--out FILE]
#                                an encrypted copy of a backup to take off the server
#                                (AES-256, key from the passphrase; backups hold every key)
#   ./install.sh --security-check [--format json|junit|sarif|evidence]
#                                the installed suite against its security promises (security-check.sh)
#   ./install.sh --drill         restore the latest good backup into an isolated copy and start it
#   ./install.sh --diagnostics   write a diagnostic bundle (zip, no secrets, no plant data) here
#   ./install.sh --check         check this server's requirements (preflight.sh) and change nothing;
#                                --ignore ID[,ID] lets those checks fail (ids in the report); --json for tools
#   ./install.sh --show-config   the installation file, each value it sets and what .env holds now
#   ./install.sh --uninstall     stop and remove the containers; data and backups are kept
#   ./install.sh --uninstall --purge   also delete data, backups and the suite's images
#   ./install.sh --add FILE.pcapp       install or upgrade an app from a signed package
#   ./install.sh --remove APP           remove an installed app (its data is kept)
#   ./install.sh --worker --platform URL --code CODE [--ca FILE]
#                                a compute worker on this machine for the PlantCraft at URL
#                                (the code and command come from Settings › Compute › Add
#                                worker; --ca: PlantCraft's local-ca-root.crt; docs/compute.md)
#
# Options: --prefix DIR (install folder, default /opt/plantcraft or $PLANTCRAFT_HOME),
#          --config FILE (the installation file, default /etc/plantcraft/installation.conf when
#          it exists: apps, machine size, network and security ceilings decided outside the
#          platform; its values win over these options; docs/installation-file.md),
#          --with-linkcraft, --with-dashcraft, --with-histcraft,
#          --with-alarmcraft, --with-modelcraft, --with-doccraft (turn that app on; LinkCraft is on by default when the bundle
#          has it), --all-apps (every app the bundle has),
#          --publisher-key FILE (check the bundle's signature against this public key, got from
#          the publisher through a channel you trust, instead of the keys the bundle or the
#          installation carries), --allow-unsigned (install or update with a development bundle,
#          not signed by a trusted publisher), --allow-emulation (a bundle built for another
#          processor than this server's: runs emulated, slowly),
#          --demo (the Simulator, if the bundle has it, and the demo story: plant map,
#          loops, algorithms, model examples, dashboards, messages; `processcraft demo seed`),
#          --public-demo (--demo left open to visitors: a read-only account `demo` shown on the
#          sign-in page, no LLM for visitors, rate limits), --yes,
#          --install-docker (no Docker on this Linux server: install the Docker Engine and Compose
#          the bundle carries in docker-engine/, offline, as root),
#          --dev (run from a source checkout: no bundle checks, images built locally),
#          --machine small|medium|large|xlarge|auto|off (the machine profile: every container's
#          CPU and memory limit, processes and pools from one choice; auto, the default, picks
#          by the CPUs and memory Docker sees; a value changed by hand in .env is kept;
#          MACHINE in the installation file wins over it).
#
# Needs Docker Engine and the Compose plugin, run as root or as a member of the `docker` group.
# It never downloads anything: images come from images.tar in this bundle.
set -Eeuo pipefail
# Settings named before the rename to PlantCraft (2026-10-27) still count, as PLANTCRAFT_*.
for former in $(compgen -e | grep '^PROCESSCRAFT_' || true); do
    current="PLANTCRAFT_${former#PROCESSCRAFT_}"
    [ -n "${!current+set}" ] || export "$current=${!former}"
done
unset former current
umask 027

MIN_DOCKER="24.0.0"
MIN_COMPOSE="2.24.0"
WAIT_SECONDS="${PLANTCRAFT_WAIT_SECONDS:-600}"
# Container users (compose.yaml); each owns its own folder under data/.
PLANTCRAFT_UID=10001
PROXY_UID=10003
SIMCRAFT_UID=10004
INSTALLER_UID=10005
# The apps of the suite table (docs/app-standard.md, section 7) that compose.yaml runs, each in
# the profile named after it: "id:Name:prefix:uid:key". Each owns data/<id>/; an app with key=key
# also data/<id>-app-key (HistCraft needs none).
SUITE_APPS=(
    "linkcraft:LinkCraft:/link/:10012:key"
    "dashcraft:DashCraft:/dash/:10006:key"
    "histcraft:HistCraft:/hist/:10008:"
    "alarmcraft:PlantCraft Alarms:/alarm/:10009:key"
    "modelcraft:PlantCraft Models:/model/:10011:key"
    "doccraft:PlantCraft Documents:/doc/:10015:key"
)
HISTCRAFT_UID=10008
# The compute gateway and the apps' executors (docs/compute.md): they share data/compute-jobs.
COMPUTE_UID=10020

BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# A new installation goes to /opt/plantcraft; one made before the rename stays where it is.
DEFAULT_PREFIX=/opt/plantcraft
if [ -f /opt/processcraft/compose.yaml ] && [ ! -e /opt/plantcraft ]; then
    DEFAULT_PREFIX=/opt/processcraft
fi
PREFIX="${PLANTCRAFT_HOME:-$DEFAULT_PREFIX}"
ACTION="install"
WORKER_PLATFORM=""
WORKER_CODE=""
WORKER_CA=""
PURGE=0
ASSUME_YES=0
DEV=0
WITH_APPS=" "    # " <id> <id> ": apps turned on by --with-<id>
CHECK_JSON=0     # --check --json: the requirements report as JSON (preflight.sh --json)
ALL_APPS=0
MACHINE=""
WITH_DEMO=0
PUBLIC_DEMO=0
APP_PACKAGE=""
APP_ID=""
BACKUP_NAME=""
PASSPHRASE_FILE=""
CHECK_ARGS=()
EXPORT_OUT=""
ALLOW_UNSIGNED=0
ALLOW_EMULATION=0
PUBLISHER_KEY=""
INSTALL_DOCKER=0
# The installation file (docs/installation-file.md): read once, after the options.
INSTALLATION_CONF="${PLANTCRAFT_INSTALLATION_CONF:-}"
CONF_ENV=()      # KEY=VALUE pairs it sets in .env, applied last by write_env
CONF_APPS=""     # " <id> <id> " when it names the apps: the others are switched off
CONF_LOCKED=""   # the .env keys it decided, for Settings › Installation ("Set by the installation")
# An update in progress (do_install): the version it started from, its backup, and whether the
# suite is being changed (a failure then returns to UPDATE_FROM by itself, on_exit).
UPDATE_FROM=""
UPDATE_TO=""
UPDATE_BACKUP=""
UPDATE_APPLYING=0
UPDATE_STARTED=""
STARTED_AT="$(date +%s)"

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
warn() { printf '[%s] WARNING: %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
die() {
    printf '[%s] ERROR: %s\n' "$(date +%H:%M:%S)" "$*" >&2
    exit 1
}

usage() { sed -n '2,55p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) [ $# -ge 2 ] || die "--prefix needs a folder"; PREFIX="$2"; shift ;;
        --prefix=*) PREFIX="${1#*=}" ;;
        --rollback) ACTION="rollback" ;;
        --backup) ACTION="backup" ;;
        --list-backups) ACTION="list-backups" ;;
        --drill) ACTION="drill" ;;
        --diagnostics) ACTION="diagnostics" ;;
        --security-check) ACTION="security-check" ;;
        --format | --url | --skip) [ $# -ge 2 ] || die "$1 needs a value"; CHECK_ARGS+=("$1" "$2"); shift ;;
        --check) ACTION="check" ;;
        --json) CHECK_JSON=1 ;;
        --show-config) ACTION="show-config" ;;
        --ignore) [ $# -ge 2 ] || die "--ignore needs check ids (see --check)"; export PLANTCRAFT_PREFLIGHT_IGNORE="${PLANTCRAFT_PREFLIGHT_IGNORE:+$PLANTCRAFT_PREFLIGHT_IGNORE,}$2"; shift ;;
        --ignore=*) export PLANTCRAFT_PREFLIGHT_IGNORE="${PLANTCRAFT_PREFLIGHT_IGNORE:+$PLANTCRAFT_PREFLIGHT_IGNORE,}${1#*=}" ;;
        --config) [ $# -ge 2 ] || die "--config needs a file"; INSTALLATION_CONF="$2"; shift ;;
        --config=*) INSTALLATION_CONF="${1#*=}" ;;
        --restore) [ $# -ge 2 ] || die "--restore needs a backup name (see --list-backups)"; ACTION="restore"; BACKUP_NAME="$2"; shift ;;
        --export-backup) [ $# -ge 2 ] || die "--export-backup needs a backup name (see --list-backups)"; ACTION="export-backup"; BACKUP_NAME="$2"; shift ;;
        --passphrase-file) [ $# -ge 2 ] || die "--passphrase-file needs a file"; PASSPHRASE_FILE="$2"; shift ;;
        --out) [ $# -ge 2 ] || die "--out needs a file name"; EXPORT_OUT="$2"; shift ;;
        --add) [ $# -ge 2 ] || die "--add needs a package file"; ACTION="add"; APP_PACKAGE="$2"; shift ;;
        --remove) [ $# -ge 2 ] || die "--remove needs an app id"; ACTION="remove"; APP_ID="$2"; shift ;;
        --uninstall) ACTION="uninstall" ;;
        --purge) PURGE=1 ;;
        --yes | -y) ASSUME_YES=1 ;;
        --with-linkcraft | --with-dashcraft | --with-histcraft | --with-alarmcraft | --with-modelcraft | --with-doccraft)
            WITH_APPS="$WITH_APPS${1#--with-} " ;;
        --all-apps) ALL_APPS=1 ;;
        --demo) WITH_DEMO=1 ;;
        --public-demo) WITH_DEMO=1; PUBLIC_DEMO=1 ;;
        --dev) DEV=1 ;;
        --install-docker) INSTALL_DOCKER=1 ;;
        --machine) [ $# -ge 2 ] || die "--machine needs small, medium, large, xlarge, auto or off"; MACHINE="$2"; shift ;;
        --machine=*) MACHINE="${1#*=}" ;;
        --allow-unsigned) ALLOW_UNSIGNED=1 ;;
        --allow-emulation) ALLOW_EMULATION=1 ;;
        --publisher-key) [ $# -ge 2 ] || die "--publisher-key needs a public key file"; PUBLISHER_KEY="$2"; shift ;;
        --publisher-key=*) PUBLISHER_KEY="${1#*=}" ;;
        --worker) ACTION="worker" ;;
        --platform) [ $# -ge 2 ] || die "--platform needs PlantCraft's address"; WORKER_PLATFORM="$2"; shift ;;
        --code) [ $# -ge 2 ] || die "--code needs the code from Settings › Compute"; WORKER_CODE="$2"; shift ;;
        --ca) [ $# -ge 2 ] || die "--ca needs a certificate file"; WORKER_CA="$2"; shift ;;
        -h | --help) usage; exit 0 ;;
        *) die "unknown option: $1 (see --help)" ;;
    esac
    shift
done

# Run from an install folder (the copy install.sh leaves there, next to .env and without
# images.tar), it works on that folder: apply settings, --rollback, --uninstall.
INSTALLED=0
if [ "$DEV" = 0 ] && [ -f "$BUNDLE_DIR/.env" ] && [ -f "$BUNDLE_DIR/compose.yaml" ] && [ ! -f "$BUNDLE_DIR/images.tar" ]; then
    INSTALLED=1
fi
if { [ "$DEV" = 1 ] || [ "$INSTALLED" = 1 ]; } && [ -z "${PLANTCRAFT_HOME:-}" ] && [ "$PREFIX" = "$DEFAULT_PREFIX" ]; then
    PREFIX="$BUNDLE_DIR"
fi
if [ "$ACTION" = "worker" ] && [ -z "${PLANTCRAFT_HOME:-}" ] && [ "$PREFIX" = "$DEFAULT_PREFIX" ]; then
    PREFIX="/opt/plantcraft-worker"
    if [ -f /opt/processcraft-worker/compose.yaml ] && [ ! -e /opt/plantcraft-worker ]; then
        PREFIX="/opt/processcraft-worker"
    fi
fi
[ "$PURGE" = 0 ] || [ "$ACTION" = "uninstall" ] || die "--purge only goes with --uninstall"

# The installation file ----------------------------------------------------------------------
# Decided outside the platform by whoever installs the server: it must be owned by root and
# writable by nobody else (like sshd's StrictModes), or it is refused. Never mounted in a
# container: PlantCraft sees only what is derived from it in .env.
conf_value() { sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$INSTALLATION_CONF" | sed 's/[[:space:]]*#.*$//; s/^"//; s/"$//' | tail -n 1; }
conf_set() { CONF_ENV+=("$1=$2"); CONF_LOCKED="${CONF_LOCKED:+$CONF_LOCKED,}$1"; }
conf_app_id() {
    case "$1" in
        analytics | link | linkcraft) echo linkcraft ;; historian | hist | histcraft) echo histcraft ;;
        view | dash | dashcraft) echo dashcraft ;; alarms | alarm | alarmcraft) echo alarmcraft ;;
        models | model | modelcraft) echo modelcraft ;; documents | doc | doccraft) echo doccraft ;;
        *) return 1 ;;
    esac
}
load_installation_conf() {
    if [ -z "$INSTALLATION_CONF" ]; then
        [ -f /etc/plantcraft/installation.conf ] || return 0
        INSTALLATION_CONF=/etc/plantcraft/installation.conf
    fi
    [ -f "$INSTALLATION_CONF" ] || die "--config: $INSTALLATION_CONF is not a file"
    local owner mode value app id
    owner="$(stat -c %u "$INSTALLATION_CONF")"
    mode="$(stat -c %a "$INSTALLATION_CONF")"
    if [ "$DEV" = 0 ] && { [ "$owner" != 0 ] || [ $((8#$mode & 8#022)) -ne 0 ]; }; then
        die "$INSTALLATION_CONF must be owned by root and writable by root only (it is owner $owner, mode $mode): sudo chown root:root $INSTALLATION_CONF && sudo chmod 644 $INSTALLATION_CONF"
    fi
    log "Installation file: $INSTALLATION_CONF"
    value="$(conf_value APPS)"
    if [ -n "$value" ]; then
        if [ "$value" = all ]; then
            ALL_APPS=1
        else
            CONF_APPS=" "
            for app in $(printf '%s' "$value" | tr ',' ' '); do
                id="$(conf_app_id "$app")" || die "$INSTALLATION_CONF: APPS has an unknown app '$app'"
                CONF_APPS="$CONF_APPS$id "
            done
            WITH_APPS="$CONF_APPS"
        fi
        CONF_LOCKED="${CONF_LOCKED:+$CONF_LOCKED,}COMPOSE_PROFILES"
    fi
    value="$(conf_value WEB_APP_INSTALL)"
    case "$value" in "") ;; on | off) conf_set PLANTCRAFT_APP_INSTALL "$value" ;; *) die "$INSTALLATION_CONF: WEB_APP_INSTALL is on or off" ;; esac
    value="$(conf_value DEMO)"
    case "$value" in "" | off) ;; on) WITH_DEMO=1 ;; public) WITH_DEMO=1; PUBLIC_DEMO=1 ;; *) die "$INSTALLATION_CONF: DEMO is off, on or public" ;; esac
    value="$(conf_value LLM)"
    case "$value" in "") ;; off | on) conf_set PLANTCRAFT_LLM "$([ "$value" = off ] && echo off || echo '')" ;; *) die "$INSTALLATION_CONF: LLM is off or on" ;; esac
    # The other security switches: assistants from outside (MCP) and Notebooks.
    value="$(conf_value ASSISTANT_ACCESS)"
    case "$value" in "") ;; on | off) conf_set PLANTCRAFT_MCP "$([ "$value" = on ] && echo true || echo false)" ;; *) die "$INSTALLATION_CONF: ASSISTANT_ACCESS is on or off" ;; esac
    value="$(conf_value NOTEBOOKS)"
    case "$value" in "") ;; on | off) conf_set PLANTCRAFT_NOTEBOOKS "$([ "$value" = on ] && echo true || echo false)" ;; *) die "$INSTALLATION_CONF: NOTEBOOKS is on or off" ;; esac
    value="$(conf_value MACHINE)"
    # The machine profile (install.sh --machine, thread "CPU and processes") reads PLANTCRAFT_MACHINE.
    # MACHINE of the file wins over --machine.
    if [ -n "$value" ]; then MACHINE="$value"; conf_set PLANTCRAFT_MACHINE "$value"; fi
    value="$(conf_value MAX_CPUS)"; if [ -n "$value" ]; then conf_set PLANTCRAFT_MAX_CPUS "$value"; fi
    value="$(conf_value MAX_MEMORY)"; if [ -n "$value" ]; then conf_set PLANTCRAFT_MAX_MEMORY "$value"; fi
    value="$(conf_value HOSTNAME)"; if [ -n "$value" ]; then conf_set PLANTCRAFT_HOSTNAME "$value"; fi
    value="$(conf_value HTTPS_PORT)"; if [ -n "$value" ]; then conf_set PLANTCRAFT_HTTPS_PORT "$value"; fi
    value="$(conf_value BIND_ADDRESS)"; if [ -n "$value" ]; then conf_set PLANTCRAFT_BIND_ADDRESS "$value"; fi
    value="$(conf_value NETWORK_BASE)"
    if [ -n "$value" ]; then
        [[ "$value" =~ ^[0-9]{1,3}\.[0-9]{1,3}$ ]] || die "$INSTALLATION_CONF: NETWORK_BASE is like 172.30"
        local net n=10
        for net in PLANT APPS EDGE DEMO HISTDB LLM EGRESS; do
            conf_set "PLANTCRAFT_${net}_SUBNET" "$value.$n.0/24"
            n=$((n + 1))
        done
        conf_set PLANTCRAFT_PROXY_ADDRESS "$value.11.250"
    fi
    value="$(conf_value TIMEZONE)"; if [ -n "$value" ]; then conf_set PLANTCRAFT_TIMEZONE "$value"; fi
    value="$(conf_value LOCK_TIMEZONE)"; if [ "$value" = yes ]; then conf_set PLANTCRAFT_TIMEZONE_LOCKED true; fi
    for value in MAX_SIGNALS MAX_PARALLEL_RUNS MAX_SESSIONS; do
        app="$(conf_value "$value")"
        if [ -n "$app" ]; then conf_set "PLANTCRAFT_$value" "$app"; fi
    done
}
apply_installation_conf() { # apply_installation_conf ENV_FILE: last step of write_env
    [ -n "$INSTALLATION_CONF" ] || return 0
    local pair profiles app
    for pair in "${CONF_ENV[@]}"; do env_set "${pair%%=*}" "${pair#*=}" "$1"; done
    if [ -n "$CONF_APPS" ]; then
        profiles="$(env_get COMPOSE_PROFILES "$1")"
        for app in $(app_ids); do
            if [[ ",$profiles," == *",$app,"* ]] && [[ "$CONF_APPS" != *" $app "* ]]; then
                warn "$app is not in APPS of $INSTALLATION_CONF: switched off"
                profiles="$(printf '%s' ",$profiles," | sed "s/,$app,/,/; s/^,//; s/,\$//")"
            fi
        done
        env_set COMPOSE_PROFILES "$profiles" "$1"
        env_set PLANTCRAFT_APPS "$(suite_apps_setting "$profiles" "$(env_get PLANTCRAFT_APPS "$1")" "$1")" "$1"
    fi
    env_set PLANTCRAFT_INSTALLATION_LOCKED "$CONF_LOCKED" "$1"
    env_set PLANTCRAFT_INSTALLATION_CONF_SHA256 "$(sha256sum "$INSTALLATION_CONF" | cut -c 1-64)" "$1"
}

confirm() {
    [ "$ASSUME_YES" = 1 ] && return 0
    [ -t 0 ] || die "$1 Re-run with --yes to confirm."
    local answer
    read -r -p "$1 [y/N] " answer
    case "$answer" in y | Y | yes | YES) return 0 ;; *) die "cancelled" ;; esac
}

# True when version $1 >= version $2.
# version_ge A B: A is B or newer, as SemVer orders them (plantcraft/apps/release.py, version_key):
# a release candidate comes before its release (0.5.1-rc3 < 0.5.1), which sort -V alone reverses.
version_ge() {
    local a="${1%%+*}" b="${2%%+*}"
    local core_a="${a%%-*}" core_b="${b%%-*}"
    if [ "$core_a" != "$core_b" ]; then
        [ "$(printf '%s\n%s\n' "$core_b" "$core_a" | sort -V | head -n 1)" = "$core_b" ]
        return
    fi
    [ "$a" != "$core_a" ] || return 0 # A is the release itself
    [ "$b" != "$core_b" ] || return 1 # B is the release, A one of its candidates
    [ "$(printf '%s\n%s\n' "${b#*-}" "${a#*-}" | sort -V | head -n 1)" = "${b#*-}" ]
}

check_docker() {
    if ! command -v docker >/dev/null 2>&1 && [ "$INSTALL_DOCKER" = 1 ]; then
        [ -x "$BUNDLE_DIR/docker-engine/docker-engine.sh" ] || die "--install-docker: this bundle has no docker-engine/ folder."
        "$BUNDLE_DIR/docker-engine/docker-engine.sh" install "$BUNDLE_DIR/docker-engine"
    fi
    command -v docker >/dev/null 2>&1 || die "Docker is not installed: run again with --install-docker (the bundle carries Docker Engine), or see docs/install-offline.md, section 1."
    docker info >/dev/null 2>&1 ||
        die "cannot reach the Docker daemon: start it, and run as root or as a member of the docker group."
    local engine compose
    engine="$(docker version --format '{{.Server.Version}}' 2>/dev/null || true)"
    version_ge "${engine:-0}" "$MIN_DOCKER" || die "Docker Engine $MIN_DOCKER or newer is needed (found ${engine:-none})."
    compose="$(docker compose version --short 2>/dev/null || true)"
    compose="${compose#v}"
    version_ge "${compose:-0}" "$MIN_COMPOSE" ||
        die "Docker Compose plugin $MIN_COMPOSE or newer is needed (found ${compose:-none})."
    log "Docker Engine $engine, Compose $compose"
}

# The suite's compose file plus one per app the installer service runs (data/installer/apps/).
compose() {
    local files=(-f "$PREFIX/compose.yaml") app
    for app in "$PREFIX"/data/installer/apps/*/compose.json; do
        if [ -f "$app" ]; then files+=(-f "$app"); fi
    done
    docker compose --project-directory "$PREFIX" "${files[@]}" --env-file "$PREFIX/.env" "$@"
}

env_get() { # env_get KEY FILE
    [ -f "$2" ] || return 0
    sed -n "s/^$1=//p" "$2" | tail -n 1
}

new_installation_id() { # a random UUID (version 4), from the kernel when it offers one
    if [ -r /proc/sys/kernel/random/uuid ]; then
        cat /proc/sys/kernel/random/uuid
        return
    fi
    od -An -N16 -tx1 /dev/urandom | tr -d ' \n' |
        sed -E 's/^(.{8})(.{4}).(.{3})(.)(.{3})(.{12})$/\1-\2-4\3-\4\5-\6/' |
        awk '{ v = substr($0, 20, 1); m = "89ab"; i = index("0123456789abcdef", v) % 4 + 1;
               print substr($0, 1, 19) substr(m, i, 1) substr($0, 21) }'
}

env_set() { # env_set KEY VALUE FILE
    local tmp
    tmp="$(mktemp "$3.XXXXXX")"
    if grep -q "^$1=" "$3"; then
        awk -v key="$1" -v value="$2" 'index($0, key "=") == 1 { print key "=" value; next } { print }' "$3" >"$tmp"
    else
        cat "$3" >"$tmp"
        printf '%s=%s\n' "$1" "$2" >>"$tmp"
    fi
    chmod 0640 "$tmp"
    mv "$tmp" "$3"
}

env_rename() { # env_rename OLD NEW FILE: a setting renamed in a release keeps its value
    local tmp
    [ -f "$3" ] && grep -q "^$1=" "$3" || return 0
    tmp="$(mktemp "$3.XXXXXX")"
    if grep -q "^$2=" "$3"; then
        grep -v "^$1=" "$3" >"$tmp" || true
    else
        awk -v old="$1" -v new="$2" 'index($0, old "=") == 1 { print new substr($0, length(old) + 1); next } { print }' "$3" >"$tmp"
    fi
    chmod 0640 "$tmp"
    mv "$tmp" "$3"
}

# Fields of an app of SUITE_APPS: app_field ID 2 (name), 3 (prefix), 4 (uid), 5 (key).
app_field() {
    local entry
    for entry in "${SUITE_APPS[@]}"; do
        if [ "${entry%%:*}" = "$1" ]; then printf '%s' "$entry" | cut -d: -f"$2"; fi
    done
}
app_ids() { local entry; for entry in "${SUITE_APPS[@]}"; do printf '%s\n' "${entry%%:*}"; done; }
# The .env key of an app's version: linkcraft -> LINKCRAFT_VERSION.
version_key() { printf '%s_VERSION' "$(printf '%s' "$1" | tr '[:lower:]' '[:upper:]')"; }
wants_app() { [[ "$WITH_APPS" == *" $1 "* ]]; }
app_image() { docker image inspect "$1:$2" >/dev/null 2>&1; }

# Runs a shell command as root inside a throwaway container without network, with the install
# folder at /install. Used for files owned by the container users, so that a member of the
# docker group needs no sudo.
as_root() { # as_root IMAGE COMMAND
    docker run --rm --network none --user 0:0 --pull never \
        --cap-drop ALL --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER \
        --security-opt no-new-privileges:true \
        -v "$PREFIX:/install" --entrypoint /bin/sh "$1" -c "$2"
}

helper_image() { printf 'processcraft:%s' "$(env_get PLANTCRAFT_VERSION "$PREFIX/.env")"; }

stack_exists() { [ -f "$PREFIX/compose.yaml" ] && [ -f "$PREFIX/.env" ] && [ -n "$(compose ps -a -q 2>/dev/null)" ]; }

verify_bundle() {
    [ -f "$BUNDLE_DIR/SHA256SUMS" ] || die "SHA256SUMS is missing: this is not a complete release bundle."
    log "Checking the bundle against SHA256SUMS"
    (cd "$BUNDLE_DIR" && sha256sum --quiet --strict -c SHA256SUMS) ||
        die "the bundle is damaged or was modified: a file does not match SHA256SUMS."
    check_architecture
}

# The processor the bundle's images are built for (bundle.env ARCH; none before 0.3.0: amd64)
# against this server's Docker.
check_architecture() {
    local wanted host
    wanted="$(env_get ARCH "$BUNDLE_DIR/bundle.env")"
    wanted="${wanted:-amd64}"
    host="$(docker info --format '{{.Architecture}}' 2>/dev/null || uname -m)"
    case "$host" in
        x86_64 | amd64) host=amd64 ;;
        aarch64 | arm64) host=arm64 ;;
    esac
    [ "$wanted" = "$host" ] && return 0
    if [ "$ALLOW_EMULATION" = 1 ]; then
        warn "this bundle is for linux/$wanted and this server is linux/$host: the suite runs emulated (--allow-emulation), several times slower."
        return 0
    fi
    die "this bundle is for linux/$wanted and this server is linux/$host: get the linux/$host bundle of this release (plantcraft-<version>-linux-$host-bundle.tar.gz), or pass --allow-emulation. Nothing was changed."
}

# The publisher keys a signature is checked against, in a folder for the installer image:
# --publisher-key when given, else the installation's trusted-publishers/ (an update), else the
# bundle's own (a first install, or the first signed update of an installation that had none).
# Sets TRUST_DIR; FIRST_TRUST=1 when the keys come from the bundle being checked.
FIRST_TRUST=0
TRUST_TMP=""
TRUST_DIR=""
set_trust_dir() {
    FIRST_TRUST=0
    if [ -n "$PUBLISHER_KEY" ]; then
        [ -f "$PUBLISHER_KEY" ] || die "--publisher-key: $PUBLISHER_KEY is not a file"
        case "$(basename "$PUBLISHER_KEY")" in
            *.pub) ;;
            *) die "--publisher-key: the file is named after its publisher, like processcraft.pub" ;;
        esac
        TRUST_TMP="$(mktemp -d)"
        cp "$PUBLISHER_KEY" "$TRUST_TMP/"
        chmod 0755 "$TRUST_TMP"
        chmod 0644 "$TRUST_TMP"/*
        TRUST_DIR="$TRUST_TMP"
    elif [ "$INSTALLED_TRUST" = 1 ]; then
        TRUST_DIR="$PREFIX/trusted-publishers"
    else
        FIRST_TRUST=1
        TRUST_DIR="$BUNDLE_DIR/trusted-publishers"
    fi
}
INSTALLED_TRUST=0
bundle_keys() { (cd "$BUNDLE_DIR/trusted-publishers" 2>/dev/null && ls -- *.pub 2>/dev/null | tr '\n' ' ' | sed 's/ $//'); }
has_installed_trust() { compgen -G "$PREFIX/trusted-publishers/*.pub" >/dev/null 2>&1; }

# A first install: the signature over SHA256SUMS (the hash of every file, images.tar included),
# checked by the installer image of this bundle before anything starts. Its key is the one the
# bundle carries unless --publisher-key names another, so the key id printed here is what to
# compare with the one the publisher publishes (docs/install-offline.md, section 2).
check_signature() { # check_signature VERSION
    local args=(check /bundle --trusted /trusted) out
    INSTALLED_TRUST=0
    if has_installed_trust; then INSTALLED_TRUST=1; fi
    set_trust_dir
    if [ "$ALLOW_UNSIGNED" = 1 ]; then args+=(--allow-unsigned); fi
    log "Checking the bundle's signature"
    out="$(docker run --rm --network none --pull never --read-only --cap-drop ALL \
        --security-opt no-new-privileges:true --user "$(id -u):$(id -g)" \
        -v "$BUNDLE_DIR:/bundle:ro" -v "$TRUST_DIR:/trusted:ro" \
        --entrypoint python "processcraft-installer:$1" -m processcraft.apps.release "${args[@]}" 2>&1 >/dev/null)" ||
        { printf '%s\n' "$out" >&2; die "the bundle was refused (the reason is above). Nothing was started."; }
    printf '%s\n' "$out" | sed 's/^/    /'
    if [ -n "$TRUST_TMP" ]; then rm -rf "$TRUST_TMP"; TRUST_TMP=""; fi
    if [ "$FIRST_TRUST" = 1 ] && printf '%s' "$out" | grep -q 'signature checked'; then
        warn "the key above came with this bundle: compare its key id with the one published with the release (or install with --publisher-key FILE)."
    fi
}

# Before any image is loaded: the signature over SHA256SUMS checked with this server's own
# OpenSSL (Ed25519, 1.1.1 or later), not with a program that came in the bundle being checked.
# SHA256SUMS was already checked against every file (verify_bundle), so a good signature covers
# images.tar too. Without a usable openssl the check runs, as before, in the installer image
# after the load (check_signature), and a warning says so.
host_signature() {
    local sig="$BUNDLE_DIR/SHA256SUMS.sig" publisher raw key tmp
    INSTALLED_TRUST=0
    if has_installed_trust; then INSTALLED_TRUST=1; fi
    set_trust_dir
    if [ ! -f "$sig" ]; then
        if compgen -G "$TRUST_DIR/*.pub" >/dev/null 2>&1 && [ "$ALLOW_UNSIGNED" != 1 ]; then
            die "the bundle is not signed (SHA256SUMS.sig is missing) and this server trusts publisher keys: get the signed bundle, or pass --allow-unsigned for a development bundle. Nothing was loaded."
        fi
        host_signature_done
        return 0
    fi
    if ! command -v openssl >/dev/null 2>&1 ||
        ! openssl pkeyutl -help 2>&1 | grep -q -- '-rawin'; then
        warn "openssl 1.1.1 or later is not on this server: the signature is checked after the images are loaded, by the bundle's installer."
        host_signature_done
        return 0
    fi
    publisher="$(sed -n 's/^ *"publisher": *"\([a-z0-9-]*\)".*/\1/p' "$sig" | head -n 1)"
    raw="$(sed -n 's/^ *"signature": *"\([A-Za-z0-9+\/=]*\)".*/\1/p' "$sig" | head -n 1)"
    [ -n "$publisher" ] && [ -n "$raw" ] || die "SHA256SUMS.sig cannot be read. Nothing was loaded."
    key="$TRUST_DIR/$publisher.pub"
    if [ ! -f "$key" ]; then
        if [ "$FIRST_TRUST" = 0 ]; then
            die "the bundle is signed by '$publisher', which this server does not trust (trusted-publishers/). Nothing was loaded."
        fi
        die "the bundle is signed by '$publisher' but carries no key for it. Nothing was loaded."
    fi
    tmp="$(mktemp)"
    printf '%s' "$raw" | base64 -d >"$tmp" 2>/dev/null || { rm -f "$tmp"; die "SHA256SUMS.sig cannot be read. Nothing was loaded."; }
    log "Checking the bundle's signature with this server's OpenSSL (before loading anything)"
    if ! openssl pkeyutl -verify -pubin -inkey "$key" -rawin -in "$BUNDLE_DIR/SHA256SUMS" -sigfile "$tmp" >/dev/null 2>&1; then
        rm -f "$tmp"
        die "the signature does not match SHA256SUMS: the bundle was modified. Nothing was loaded."
    fi
    rm -f "$tmp"
    echo "    signature checked: publisher $publisher"
    host_signature_done
}
host_signature_done() {
    if [ -n "$TRUST_TMP" ]; then rm -rf "$TRUST_TMP"; TRUST_TMP=""; fi
}

load_images() {
    log "Loading images from images.tar (no download)"
    docker load -i "$BUNDLE_DIR/images.tar" | sed 's/^/    /'
}

backup() { # backup LABEL: stops the stack, saves data, settings and the current image ids
    local now stamp dir version
    version="$(env_get PLANTCRAFT_VERSION "$PREFIX/.env")"
    now="$(date +%Y%m%d-%H%M%S)"
    stamp="$now-${1}"
    dir="$PREFIX/backups/$stamp"
    log "Backing up data, settings and images to backups/$stamp"
    mkdir -p "$dir"
    chmod 0700 "$PREFIX/backups" "$dir"
    dump_histcraft_db "$dir"
    compose stop >/dev/null 2>&1 || true
    local file
    for file in .env compose.yaml bundle.env; do
        if [ -f "$PREFIX/$file" ]; then cp -p "$PREFIX/$file" "$dir/$file"; fi
    done
    : >"$dir/images.txt"
    local ref id
    while read -r ref; do
        [ -n "$ref" ] || continue
        id="$(docker image inspect --format '{{.Id}}' "$ref" 2>/dev/null || true)"
        [ -n "$id" ] || continue
        printf '%s %s\n' "$ref" "$id" >>"$dir/images.txt"
        # A second tag keeps the old image even when a new one takes over its name. An image
        # pinned by digest (histcraft-db) cannot be replaced under that reference; it is
        # tagged too, so that a purge or prune of the new version leaves it on the host.
        docker tag "$id" "$(rollback_tag "$ref" "$now")" >/dev/null 2>&1 || true
    done < <(compose config --images 2>/dev/null | sort -u)
    as_root "processcraft:$version" \
        "cd /install && tar --numeric-owner -czf backups/$stamp/data.tar.gz data certs" ||
        die "the backup failed; nothing was changed."
    printf '%s\n' "$stamp" >"$PREFIX/backups/LATEST"
    log "Backup done: $(du -sh "$dir" 2>/dev/null | cut -f1) in backups/$stamp"
}

# The rollback tag of an image reference: name:rollback-<date> (tag and digest dropped).
rollback_tag() { # rollback_tag REF DATE
    local name="${1%%@*}"
    case "${name##*/}" in *:*) name="${name%:*}" ;; esac
    printf '%s:rollback-%s' "$name" "$2"
}

# HistCraft's database, dumped while it still runs (pg_dump, custom format) before an upgrade:
# backups/<stamp>/histcraft-db.dump beside data.tar.gz, which holds its files too (stopped).
dump_histcraft_db() { # dump_histcraft_db BACKUP_DIR
    [ -n "$(compose ps -q --status running histcraft-db 2>/dev/null)" ] || return 0
    log "Dumping HistCraft's database (pg_dump) to $(basename "$1")/histcraft-db.dump"
    (umask 077 && compose exec -T histcraft-db pg_dump -U histcraft -d histcraft -Fc >"$1/histcraft-db.dump") ||
        die "pg_dump of histcraft-db failed; nothing was changed."
    [ -s "$1/histcraft-db.dump" ] || die "pg_dump of histcraft-db wrote nothing; nothing was changed."
}

copy_files() {
    if [ "$PREFIX" = "$BUNDLE_DIR" ]; then return 0; fi
    log "Copying the suite files to $PREFIX"
    cp "$BUNDLE_DIR/compose.yaml" "$BUNDLE_DIR/.env.example" "$BUNDLE_DIR/install.sh" "$BUNDLE_DIR/firewall.sh" "$PREFIX/"
    if [ -f "$BUNDLE_DIR/security-check.sh" ]; then cp "$BUNDLE_DIR/security-check.sh" "$PREFIX/"; chmod 0755 "$PREFIX/security-check.sh"; fi
    # The security check's catalogue and the release's signed hashes, which it checks itself
    # against (PC-INT-01). Named release-* so the folder is not taken for a bundle.
    if [ -f "$BUNDLE_DIR/security-checks.tsv" ]; then cp "$BUNDLE_DIR/security-checks.tsv" "$PREFIX/"; fi
    rm -f "$PREFIX/release-SHA256SUMS" "$PREFIX/release-SHA256SUMS.sig"
    if [ -f "$BUNDLE_DIR/SHA256SUMS" ]; then cp "$BUNDLE_DIR/SHA256SUMS" "$PREFIX/release-SHA256SUMS"; fi
    if [ -f "$BUNDLE_DIR/SHA256SUMS.sig" ]; then cp "$BUNDLE_DIR/SHA256SUMS.sig" "$PREFIX/release-SHA256SUMS.sig"; fi
    local file
    for file in bundle.env release.json RELEASE-NOTES.md; do
        if [ -f "$BUNDLE_DIR/$file" ]; then cp "$BUNDLE_DIR/$file" "$PREFIX/"; fi
    done
    mkdir -p "$PREFIX/certs" "$PREFIX/trusted-publishers"
    cp "$BUNDLE_DIR/certs/README.md" "$PREFIX/certs/README.md"
    # Public keys of the publishers whose app packages this server accepts.
    if [ -d "$BUNDLE_DIR/trusted-publishers" ]; then
        cp "$BUNDLE_DIR"/trusted-publishers/* "$PREFIX/trusted-publishers/" 2>/dev/null || true
    fi
    # Notebooks kits (optional part of the bundle): this bundle's replace the ones before.
    mkdir -p "$PREFIX/notebook-kits"
    if [ -f "$BUNDLE_DIR/notebook-kits/kits.json" ]; then
        find "$PREFIX/notebook-kits" -maxdepth 1 -type f \( -name '*.zip' -o -name kits.json \) -delete
        cp "$BUNDLE_DIR"/notebook-kits/* "$PREFIX/notebook-kits/"
    fi
}

# The proxy (uid 10003) reads the certificate folder through a bind mount.
set_file_modes() {
    mkdir -p "$PREFIX/certs" "$PREFIX/trusted-publishers" "$PREFIX/notebook-kits"
    chmod 0755 "$PREFIX/install.sh" "$PREFIX/firewall.sh" "$PREFIX/certs" "$PREFIX/trusted-publishers" "$PREFIX/notebook-kits"
    chmod 0644 "$PREFIX/compose.yaml"
    find "$PREFIX/trusted-publishers" "$PREFIX/notebook-kits" -maxdepth 1 -type f -exec chmod 0644 {} +
}

default_hostnames() {
    local name ip
    name="$(hostname -f 2>/dev/null || hostname 2>/dev/null || echo localhost)"
    # In WSL, Docker Desktop publishes the port on Windows' localhost: the distribution's own
    # name and address are not reachable from Windows' browsers (docs/install.md, Windows).
    if grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null; then
        printf 'localhost %s' "$name"
        return
    fi
    ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
    printf '%s%s' "$name" "${ip:+ $ip}"
}

# The server's IANA time zone (the plant's, as a rule); UTC when the system does not say.
server_time_zone() {
    local zone=""
    if command -v timedatectl >/dev/null 2>&1; then zone="$(timedatectl show -p Timezone --value 2>/dev/null || true)"; fi
    if [ -z "$zone" ] && [ -f /etc/timezone ]; then zone="$(head -n 1 /etc/timezone)"; fi
    if [ -z "$zone" ] && [ -L /etc/localtime ]; then zone="$(readlink /etc/localtime | sed -n 's#.*/zoneinfo/##p')"; fi
    case "$zone" in
        "" | *[!A-Za-z0-9/_+-]*) zone=UTC ;;
    esac
    printf '%s' "$zone"
}

write_env() { # write_env PLANTCRAFT_VERSION SIMCRAFT_VERSION (apps: BUNDLE_APP_VERSIONS)
    local env="$PREFIX/.env" profiles plant app key version db zone
    if [ ! -f "$env" ]; then
        cp "$PREFIX/.env.example" "$env"
        chmod 0640 "$env"
        env_set PLANTCRAFT_HOSTNAME "$(default_hostnames)" "$env"
        env_set PLANTCRAFT_TIMEZONE "$(server_time_zone)" "$env"
    fi
    # Settings were PROCESSCRAFT_* until the rename to PlantCraft (2026-10-27). In such a .env,
    # PLANTCRAFT_VERSION is the Simulator's (it was `plantcraft` until its 0.5.0): it moves first.
    if grep -q '^PROCESSCRAFT_' "$env"; then
        env_rename PLANTCRAFT_VERSION SIMCRAFT_VERSION "$env"
        local former
        for former in $(sed -n 's/^\(PROCESSCRAFT_[A-Z0-9_]*\)=.*/\1/p' "$env" | sort -u); do
            env_rename "$former" "PLANTCRAFT_${former#PROCESSCRAFT_}" "$env"
        done
        log "Settings renamed to PLANTCRAFT_* in $env"
    fi
    # Installations from before 0.4 kept UTC on every upgrade: nobody chose it, so the server's
    # zone is adopted (D2). What Setup › Installation saves wins over this.
    zone="$(env_get PLANTCRAFT_TIMEZONE "$env")"
    if [ -z "$zone" ] || [ "$zone" = "UTC" ]; then
        local server_zone
        server_zone="$(server_time_zone)"
        if [ "$server_zone" != "UTC" ]; then
            env_set PLANTCRAFT_TIMEZONE "$server_zone" "$env"
            log "Time zone: $server_zone (the server's; change it in Setup › Installation)."
        fi
    fi
    # The installation's id, made once and kept for good (exports and backups carry it, so a
    # company's plants can be told apart); installations from before 0.5 get theirs here.
    if [ -z "$(env_get PLANTCRAFT_INSTALLATION_ID "$env")" ]; then
        env_set PLANTCRAFT_INSTALLATION_ID "$(new_installation_id)" "$env"
    fi
    env_set PLANTCRAFT_VERSION "$1" "$env"
    db="$(env_get HISTCRAFT_DB_IMAGE "$BUNDLE_DIR/bundle.env")"
    if [ -n "$db" ]; then env_set HISTCRAFT_DB_IMAGE "$db" "$env"; fi
    db="$(env_get HISTCRAFT_GATEWAY_IMAGE "$BUNDLE_DIR/bundle.env")"
    if [ -n "$db" ]; then env_set HISTCRAFT_GATEWAY_IMAGE "$db" "$env"; fi
    if [ -n "$2" ]; then env_set SIMCRAFT_VERSION "$2" "$env"; fi
    profiles="$(env_get COMPOSE_PROFILES "$env")"
    for app in $(app_ids); do
        key="$(version_key "$app")"
        version="$(bundle_app_version "$app")"
        if [ -n "$version" ]; then env_set "$key" "$version" "$env"; fi
        if wants_app "$app" && [[ ",$profiles," != *",$app,"* ]]; then
            profiles="${profiles:+$profiles,}$app"
        fi
        # An app whose image is not loaded is switched off (an upgrade to a bundle without it).
        version="$(env_get "$key" "$env")"
        if [[ ",$profiles," == *",$app,"* ]] && ! app_image "$app" "${version:-0.5.1}"; then
            warn "image $app:${version:-0.5.1} is not loaded: the $app profile is switched off"
            profiles="$(printf '%s' ",$profiles," | sed "s/,$app,/,/; s/^,//; s/,\$//")"
        fi
    done
    if [ "$WITH_DEMO" = 1 ] && [[ ",$profiles," != *",demo,"* ]]; then
        profiles="${profiles:+$profiles,}demo"
    fi
    # The Simulator is its own image; an installation that had the demo keeps running without it
    # when the new bundle does not carry it (--demo itself was checked before anything changed).
    plant="$(env_get SIMCRAFT_VERSION "$env")"
    if [[ ",$profiles," == *",demo,"* ]] && ! simcraft_image "${plant:-0.5.1}"; then
        warn "image simcraft:${plant:-0.5.1} is not loaded: the demo profile is switched off"
        profiles="$(printf '%s' ",$profiles," | sed 's/,demo,/,/; s/^,//; s/,$//')"
    fi
    env_set COMPOSE_PROFILES "$profiles" "$env"
    # The demo story archives every Simulator signal in HistCraft: with HistCraft on, it is the
    # demo's data layer.
    if [ "$WITH_DEMO" = 1 ] && [[ ",$profiles," == *",histcraft,"* ]] && [ -z "$(env_get HISTCRAFT_URL "$env")" ]; then
        env_set HISTCRAFT_URL http://histcraft:8100/hist "$env"
    fi
    if [ "$PUBLIC_DEMO" = 1 ]; then
        env_set PLANTCRAFT_PUBLIC_DEMO true "$env"
        if [ -z "$(env_get PLANTCRAFT_PUBLIC_DEMO_PASSWORD "$env")" ]; then
            env_set PLANTCRAFT_PUBLIC_DEMO_PASSWORD plantcraft-demo "$env"
        fi
    fi
    env_set PLANTCRAFT_APPS "$(suite_apps_setting "$profiles" "$(env_get PLANTCRAFT_APPS "$env")" "$env")" "$env"
    # The installer service mounts the install folder at its own path and joins the group of
    # the Docker socket.
    env_set PLANTCRAFT_INSTALL_DIR "$PREFIX" "$env"
    env_set PLANTCRAFT_DOCKER_GID "$(docker_gid)" "$env"
    # The installation file first: its MACHINE and MAX_CPUS/MAX_MEMORY feed the machine profile.
    apply_installation_conf "$env"
    apply_machine_profile "$env"
    fit_cpu_limits "$env"
    cap_parallel_runs "$env"
}

# MAX_PARALLEL_RUNS of the installation file: no executor runs more tasks at once than that,
# whatever the machine profile or a hand edit chose (applied last).
cap_parallel_runs() {
    local env="$1" most key value default
    most="$(env_get PLANTCRAFT_MAX_PARALLEL_RUNS "$env")"
    [[ "$most" =~ ^[1-9][0-9]*$ ]] || return 0
    for key in LINKCRAFT_EXECUTOR_SLOTS:4 MODELCRAFT_EXECUTOR_SLOTS:2 MODELCRAFT_RUN_WORKERS:2; do
        default="${key#*:}"
        key="${key%%:*}"
        value="$(env_get "$key" "$env")"
        value="${value:-$default}"
        if [ "$value" -gt "$most" ] 2>/dev/null; then
            log "$key=$value is over MAX_PARALLEL_RUNS of the installation file: using $most"
            env_set "$key" "$most" "$env"
        fi
    done
}

# PLANTCRAFT_APPS: PlantCraft lists every app whose profile is on (launcher, access, API v1)
# as id=prefix@version, in the order of SUITE_APPS; entries an administrator added for other
# apps are kept after them.
suite_apps_setting() { # suite_apps_setting PROFILES CURRENT ENV_FILE
    local app entries="" others version
    others="$(printf '%s' "$2" | tr ',' '\n' | grep -v -E "^ *($(app_ids | paste -sd'|' -))=" | grep -v '^ *$' | paste -sd, - || true)"
    for app in $(app_ids); do
        [[ ",$1," == *",$app,"* ]] || continue
        version="$(env_get "$(version_key "$app")" "$3")"
        entries="${entries:+$entries,}$app=$(app_field "$app" 3)${version:+@$version}"
    done
    printf '%s' "$entries${others:+${entries:+,}$others}"
}

# Machine profile (plan B3, 2026-10-31): one choice fills every CPU, memory, process and pool
# value of the suite. Memory limits add up to what the machine has less about 1 GB for the system
# and Docker. A value the profile wrote is the profile's until someone changes it in .env: the
# values written last are kept in data/machine-profile.env, and a key whose value differs from
# them is the person's and is left alone. Values: docs/bench (plan B, 2026-10-31).
machine_size() { # machine_size CPUS MEMORY_MB -> small | medium | large | xlarge
    if [ "$1" -le 2 ] || [ "$2" -lt 6000 ]; then echo small
    elif [ "$1" -le 4 ] || [ "$2" -lt 14000 ]; then echo medium
    elif [ "$1" -le 8 ] || [ "$2" -lt 48000 ]; then echo large
    else echo xlarge
    fi
}

# One line per key: KEY small medium large xlarge. "cpus" is the machine's CPUs, "half" half of
# them, "rest" all but two.
MACHINE_TABLE='
PLANTCRAFT_WORKERS 2 3 4 8
PLANTCRAFT_CPUS 2 cpus cpus 8
PLANTCRAFT_MEMORY 768m 1536m 4g 8g
LINKCRAFT_CPUS 2 2 4 4
LINKCRAFT_MEMORY 896m 1g 4g 8g
LINKCRAFT_WORKERS 2 3 6 rest
LINKCRAFT_COMPUTE_SLOTS 2 3 6 rest
LINKCRAFT_EXECUTOR_CPUS 2 3 6 rest
LINKCRAFT_EXECUTOR_SLOTS 2 3 6 rest
LINKCRAFT_EXECUTOR_MEMORY 1536m 2g 8g 16g
LINKCRAFT_TASK_MEMORY_MB 768 1024 2048 4096
DASHCRAFT_CPUS 1 2 2 4
DASHCRAFT_MEMORY 384m 512m 2g 2g
ALARMCRAFT_CPUS 0.5 1 1 2
ALARMCRAFT_MEMORY 384m 384m 1g 1g
MODELCRAFT_CPUS 0.5 1 1 2
MODELCRAFT_MEMORY 384m 512m 1g 2g
MODELCRAFT_RUN_WORKERS 1 2 2 4
MODELCRAFT_EXECUTOR_CPUS 1 2 4 half
MODELCRAFT_EXECUTOR_SLOTS 1 2 3 half
MODELCRAFT_EXECUTOR_MEMORY 1g 2g 4g 16g
DOCCRAFT_CPUS 1 1 2 4
DOCCRAFT_MEMORY 1g 1g 1536m 4g
HISTCRAFT_CPUS 2 2 4 8
HISTCRAFT_WORKERS 2 2 3 4
HISTCRAFT_MEMORY 1g 1536m 2g 4g
HISTCRAFT_READ_VALUES 1500000 3000000 4000000 8000000
HISTCRAFT_COLLECTOR_CPUS 1 1 2 2
HISTCRAFT_COLLECTOR_MEMORY 384m 512m 1g 2g
HISTCRAFT_DB_CPUS 2 2 4 8
HISTCRAFT_DB_MEMORY 768m 1536m 8g 16g
HISTCRAFT_DB_SHARED_BUFFERS 192MB 384MB 2GB 4GB
HISTCRAFT_DB_CACHE_SIZE 512MB 1GB 6GB 12GB
'

machine_values() { # machine_values SIZE CPUS -> KEY=VALUE lines
    local column
    case "$1" in small) column=2 ;; medium) column=3 ;; large) column=4 ;; *) column=5 ;; esac
    printf '%s\n' "$MACHINE_TABLE" | awk -v c="$column" -v n="$2" 'NF == 5 {
        v = $c
        if (v == "cpus") v = n
        else if (v == "half") v = (n >= 4 ? int(n / 2) : 1)
        else if (v == "rest") v = (n > 3 ? n - 2 : 1)
        print $1 "=" v
    }'
}

docker_machine() { # "CPUS MEMORY_MB" as Docker sees them (Docker Desktop: its VM, not the Mac)
    local cpus mem
    cpus="$(docker info --format '{{.NCPU}}' 2>/dev/null || true)"
    mem="$(docker info --format '{{.MemTotal}}' 2>/dev/null || true)"
    [ -n "$cpus" ] || cpus="$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)"
    if [ -n "$mem" ]; then
        mem=$((mem / 1048576))
    else
        mem="$(awk '/^MemTotal:/ { print int($2 / 1024) }' /proc/meminfo 2>/dev/null || echo 4096)"
    fi
    printf '%s %s' "$cpus" "$mem"
}

apply_machine_profile() { # apply_machine_profile ENV_FILE
    local env="$1" choice size cpus mem record line key value current previous kept=""
    choice="${MACHINE:-$(env_get PLANTCRAFT_MACHINE "$env")}"
    choice="${choice:-auto}"
    read -r cpus mem <<<"$(docker_machine)"
    # Ceilings for a shared server (installation.conf, plan H): the profile sizes for at most
    # PLANTCRAFT_MAX_CPUS and PLANTCRAFT_MAX_MEMORY (6, 12g, 12288m), leaving the rest to others.
    local max
    max="$(env_get PLANTCRAFT_MAX_CPUS "$env")"
    if [[ "$max" =~ ^[0-9]+$ ]] && [ "$max" -gt 0 ] && [ "$max" -lt "$cpus" ]; then cpus="$max"; fi
    max="$(env_get PLANTCRAFT_MAX_MEMORY "$env")"
    case "$max" in
        *[gG]) max="${max%?}"; [[ "$max" =~ ^[0-9]+$ ]] && max=$((max * 1024)) || max="" ;;
        *[mM]) max="${max%?}"; [[ "$max" =~ ^[0-9]+$ ]] || max="" ;;
        *) max="" ;;
    esac
    if [ -n "$max" ] && [ "$max" -gt 0 ] && [ "$max" -lt "$mem" ]; then mem="$max"; fi
    case "$choice" in
        off) return 0 ;;
        auto) size="$(machine_size "$cpus" "$mem")" ;;
        small | medium | large | xlarge) size="$choice" ;;
        *) die "--machine: $choice is not small, medium, large, xlarge, auto or off" ;;
    esac
    record="$PREFIX/data/machine-profile.env"
    mkdir -p "$PREFIX/data"
    touch "$record"
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        key="${line%%=*}"
        value="${line#*=}"
        current="$(env_get "$key" "$env")"
        previous="$(env_get "$key" "$record")"
        # Before the first profile, the shipped default (.env.example) is nobody's choice either.
        [ -n "$previous" ] || previous="$(env_get "$key" "$PREFIX/.env.example")"
        if [ -z "$current" ] || [ "$current" = "$previous" ]; then
            env_set "$key" "$value" "$env"
        elif [ "$current" != "$value" ]; then
            kept="${kept:+$kept, }$key=$current"
        fi
    done <<<"$(machine_values "$size" "$cpus")"
    machine_values "$size" "$cpus" >"$record"
    env_set PLANTCRAFT_MACHINE "$choice" "$env"
    env_set PLANTCRAFT_MACHINE_SIZE "$size" "$env"
    log "Machine profile: $size ($cpus CPUs, $((mem / 1024)) GB: what Docker sees, within PLANTCRAFT_MAX_*; chosen: $choice)"
    if [ -n "$kept" ]; then log "Kept as set by hand in .env: $kept"; fi
    # Every app on, the demo plant and a round at its peak use about 4.5 GB (plan B5): a small
    # machine needs swap, or fewer apps (docs/requirements.md).
    if [ "$size" = small ] && [ -r /proc/meminfo ] &&
        [ "$(awk '/^SwapTotal:/ { print int($2 / 1024) }' /proc/meminfo)" -lt 1024 ]; then
        warn "a small machine ($((mem / 1024)) GB) without swap: give it 2 GB of swap, or turn off apps it does not need (Documents, Models), or a busy moment stops a container"
    fi
}

# Docker refuses to start a container whose CPU limit exceeds the host's CPU count ("range of
# CPUs is from 0.01 to N"), so the limits never ask for more than the host has: every
# ${KEY:-default} CPU limit of compose.yaml, set in .env or left at its default (a 2-CPU
# machine stopped on LINKCRAFT_EXECUTOR_CPUS's default 4, 0.6.0 load tests).
fit_cpu_limits() {
    local env="$1" cpus key default value file
    cpus="$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)"
    for file in "$PREFIX/compose.yaml" "$BUNDLE_DIR/compose.yaml"; do
        [ -f "$file" ] && break
    done
    [ -f "$file" ] || return 0
    while IFS=' ' read -r key default; do
        value="$(env_get "$key" "$env")"
        value="${value:-$default}"
        if awk -v a="$value" -v b="$cpus" 'BEGIN { exit !(a + 0 > b + 0) }'; then
            warn "$key=$value is more than the $cpus CPUs of this host: using $cpus"
            env_set "$key" "$cpus" "$env"
        fi
    done < <(sed -n 's/^ *cpus: "${\([A-Z_]*_CPUS\):-\([0-9.]*\)}".*/\1 \2/p' "$file" | sort -u)
}

simcraft_image() { docker image inspect "simcraft:$1" >/dev/null 2>&1; }

# --demo needs the Simulator's image: in the bundle, or built locally with --dev.
check_demo() { # check_demo SIMCRAFT_VERSION_OF_THE_BUNDLE
    [ "$WITH_DEMO" = 1 ] || return 0
    local version
    if [ "$DEV" = 0 ] && [ "$INSTALLED" = 0 ]; then
        [ -n "$1" ] || die "--demo: this bundle has no Simulator image. Build the bundle with it (make simcraft-image bundle)."
        return 0
    fi
    version="${1:-$(env_get SIMCRAFT_VERSION "$PREFIX/.env")}"
    version="${version:-${SIMCRAFT_VERSION:-0.5.1}}"
    simcraft_image "$version" ||
        die "--demo: image simcraft:$version not found. Build it from simulator/ (make simcraft-image)."
}

# Apps of the bundle (bundle.env: <ID>_VERSION), or of the local images with --dev.
BUNDLE_APP_VERSIONS=""
bundle_app_version() { printf '%s' "$BUNDLE_APP_VERSIONS" | tr ' ' '\n' | sed -n "s/^$1=//p"; }

# HistCraft's PostgreSQL image: the digest the bundle saved (bundle.env), else the compose.yaml pin.
histcraft_db_image() {
    local saved
    saved="$(env_get HISTCRAFT_DB_IMAGE "$BUNDLE_DIR/bundle.env")"
    if [ -n "$saved" ]; then printf '%s\n' "$saved"; else compose_db_image; fi
}
compose_db_image() { sed -n 's/^ *image: \${HISTCRAFT_DB_IMAGE:-\(postgres:[^ ]*@sha256:[0-9a-f]\{64\}\)}$/\1/p' "$BUNDLE_DIR/compose.yaml"; }
# HistCraft's gateway (Telegraf): the same, for HISTCRAFT_GATEWAY_IMAGE.
histcraft_gateway_image() {
    local saved
    saved="$(env_get HISTCRAFT_GATEWAY_IMAGE "$BUNDLE_DIR/bundle.env")"
    if [ -n "$saved" ]; then printf '%s\n' "$saved"; else compose_gateway_image; fi
}
compose_gateway_image() { sed -n 's/^ *image: \${HISTCRAFT_GATEWAY_IMAGE:-\(telegraf:[^ ]*@sha256:[0-9a-f]\{64\}\)}$/\1/p' "$BUNDLE_DIR/compose.yaml"; }

# --all-apps turns on every app the bundle has; --with-<app> needs that app's image.
check_apps() {
    local app version
    for app in $(app_ids); do
        version="$(bundle_app_version "$app")"
        if [ "$ALL_APPS" = 1 ] && [ -n "$version" ]; then WITH_APPS="$WITH_APPS$app "; fi
        wants_app "$app" || continue
        if [ "$DEV" = 0 ] && [ "$INSTALLED" = 0 ]; then
            [ -n "$version" ] || die "--with-$app: this bundle has no $(app_field "$app" 2) image."
            continue
        fi
        version="${version:-$(env_get "$(version_key "$app")" "$PREFIX/.env")}"
        version="${version:-0.5.1}"
        app_image "$app" "$version" || die "--with-$app: image $app:$version not found."
        if [ "$app" = histcraft ]; then
            local db
            db="$(histcraft_db_image)"
            docker image inspect "$db" >/dev/null 2>&1 ||
                die "--with-histcraft: HistCraft's database image $db is not loaded."
            db="$(histcraft_gateway_image)"
            docker image inspect "$db" >/dev/null 2>&1 ||
                die "--with-histcraft: HistCraft's gateway image $db (Telegraf) is not loaded."
        fi
    done
}

docker_gid() {
    local socket="${DOCKER_HOST:-unix:///var/run/docker.sock}"
    socket="${socket#unix://}"
    stat -c %g "$socket" 2>/dev/null || echo 0
}

random_secret() { head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | cut -c 1-24; }

NEW_PASSWORD=""
prepare_data() {
    local data="$PREFIX/data"
    # The Simulator's history and state, in data/plantcraft until its 0.5.0.
    if [ -d "$data/plantcraft" ] && [ ! -e "$data/simcraft" ]; then
        mv "$data/plantcraft" "$data/simcraft"
    fi
    mkdir -p "$data/processcraft" "$data/proxy" "$data/simcraft" "$PREFIX/certs" "$PREFIX/backups" \
        "$data/installer/routes" "$data/installer/status" "$data/app-requests" "$data/apps" "$data/egress" \
        "$data/histcraft-db" "$data/histcraft-csv" "$data/compute-jobs"
    chmod 0711 "$data"
    chmod 0700 "$PREFIX/backups"
    if [ ! -e "$data/initial-admin-password" ]; then
        NEW_PASSWORD="$(random_secret)"
        [ "${#NEW_PASSWORD}" -ge 20 ] || die "could not generate a password"
        (umask 077 && printf '%s\n' "$NEW_PASSWORD" >"$data/initial-admin-password")
    fi
    # HistCraft's database password, written once (only histcraft and histcraft-db read it).
    if [ ! -e "$data/histcraft-db-password" ]; then
        (umask 077 && random_secret >"$data/histcraft-db-password")
        [ "$(wc -c <"$data/histcraft-db-password")" -ge 20 ] || die "could not generate a password"
    fi
    # The local compute worker's credential (compute-gateway holds it; PlantCraft reads it once
    # to keep its hash), written once like the passwords above (docs/compute.md).
    if [ ! -e "$data/compute-local-key" ]; then
        (umask 077 && printf 'pcw_%s%s\n' "$(random_secret)" "$(random_secret)" >"$data/compute-local-key")
    fi
    # Every app owns data/<id>/ and, when it needs one, its app key file, filled in on its first
    # start (provision_app_keys) or by the administrator.
    local app uid owners=""
    for app in $(app_ids); do
        uid="$(app_field "$app" 4)"
        mkdir -p "$data/$app"
        # HistCraft's gateway reads its configuration from here (written by the collector),
        # made as root: once data/histcraft is the app's (0700), a second run cannot reach it.
        if [ "$app" = histcraft ]; then owners="$owners
        mkdir -p data/$app/gateway"; fi
        owners="$owners
        chown -R $uid:$uid data/$app
        chmod 0700 data/$app"
        [ -n "$(app_field "$app" 5)" ] || continue
        if [ ! -e "$data/$app-app-key" ]; then (umask 077 && : >"$data/$app-app-key"); fi
        owners="$owners
        chown $uid:$uid data/$app-app-key
        chmod 0600 data/$app-app-key"
    done
    log "Setting owners of data/ (one folder per container user)"
    as_root "$(helper_image)" "
        set -e
        cd /install
        chown -R $PLANTCRAFT_UID:$PLANTCRAFT_UID data/processcraft data/initial-admin-password
        chown -R $PROXY_UID:$PROXY_UID data/proxy
        chown -R $SIMCRAFT_UID:$SIMCRAFT_UID data/simcraft
        chown $PLANTCRAFT_UID:$PLANTCRAFT_UID data/app-requests
        chown -R $PLANTCRAFT_UID:$PLANTCRAFT_UID data/egress
        chown -R $INSTALLER_UID:$INSTALLER_UID data/installer
        chown -R $HISTCRAFT_UID:$HISTCRAFT_UID data/histcraft-db data/histcraft-db-password
        # Its folders are made in here: once data/compute-jobs is the compute user's (0700), a
        # second install.sh run as a member of the docker group cannot reach inside it.
        mkdir -p data/compute-jobs/linkcraft data/compute-jobs/modelcraft
        chown -R $COMPUTE_UID:$COMPUTE_UID data/compute-jobs
        # Alarms and its sandbox container share only this folder (its socket).
        mkdir -p data/alarmcraft-sandbox
        chown 10009:10009 data/alarmcraft-sandbox
        chmod 0700 data/alarmcraft-sandbox
        chown $COMPUTE_UID:$PLANTCRAFT_UID data/compute-local-key
        chmod 0640 data/compute-local-key
        $owners
        chmod 0700 data/processcraft data/proxy data/simcraft data/histcraft-db data/compute-jobs
        chmod 0750 data/app-requests data/egress
        chmod 0755 data/installer data/installer/routes data/installer/status
        chmod 0711 data/apps
        chmod 0755 data/histcraft-csv
        chmod 0600 data/initial-admin-password data/histcraft-db-password
        if [ -f certs/key.pem ]; then chown $PROXY_UID:$PROXY_UID certs/key.pem; chmod 0400 certs/key.pem; fi
        if [ -f certs/cert.pem ]; then chmod 0444 certs/cert.pem; fi
    "
}

# The containers of an installation already here, removed (data, settings, images and volumes
# stay) with the compose files that made them, before the new ones are copied. A container kept
# from an earlier run can hold its name while `up` makes the new one ("already in use"), seen
# when the same version is installed again with other image tags.
remove_containers() {
    stack_exists || return 0
    log "Removing the current containers (data, settings and images stay)"
    local out
    out="$(compose down --remove-orphans 2>&1)" || {
        printf '%s\n' "$out" >&2
        die "the current containers could not be removed (the reason is above). Data and settings are unchanged."
    }
}

start_stack() {
    log "Starting the suite and waiting for every container to be healthy (up to ${WAIT_SECONDS}s)"
    # The proxy reads certs/ when it starts: recreate it so that a new certificate takes effect.
    compose rm -s -f proxy >/dev/null 2>&1 || true
    if ! compose up -d --remove-orphans --wait --wait-timeout "$WAIT_SECONDS"; then
        compose ps -a || true
        compose logs --tail 40 || true
        [ "$UPDATE_APPLYING" = 0 ] || die "the suite did not become healthy on $UPDATE_TO."
        die "the suite did not become healthy. Fix the cause above, or return to the previous version with: $PREFIX/install.sh --rollback"
    fi
    compose ps
}

# An app's background work (rounds, schedules, collection) needs an app key. The first time an
# app runs, PlantCraft issues one (audited, listed under Users and app keys), install.sh writes
# it to data/<id>-app-key (the app's user, 0600) and restarts the app with it.
APP_KEY_SNIPPET='
import os, sys
from plantcraft.config import load_scenario
from plantcraft.platform.workspace import Workspace
app_id, name = sys.argv[1], sys.argv[2]
workspace = Workspace(load_scenario(os.environ["PLANTCRAFT_SCENARIO"]).storage.sqlite_path)
record, key = workspace.app_keys.create(app_id, label=f"{name} (install.sh)", actor="install.sh")
workspace.audit.record("install.sh", "app_key.create", f"app:{app_id}",
    {"key_id": record["key_id"], "label": record["label"]}, app_id="processcraft")
print(key)
'
provision_app_key() { # provision_app_key ID: 0 when a new key was written
    local app="$1" name uid key
    name="$(app_field "$app" 2)"
    uid="$(app_field "$app" 4)"
    if as_root "$(helper_image)" "test -s /install/data/$app-app-key"; then return 1; fi
    log "Issuing $name's app key in PlantCraft (data/$app-app-key)"
    key="$(compose exec -T processcraft python -c "$APP_KEY_SNIPPET" "$app" "$name" | tail -n 1)" || key=""
    if [[ ! "$key" =~ ^pck_[A-Za-z0-9._-]{20,}$ ]]; then
        warn "could not issue $name's app key: create one under Users and app keys, write it to $PREFIX/data/$app-app-key and run docker compose restart $app"
        return 1
    fi
    printf '%s\n' "$key" | docker run --rm -i --network none --user "$uid:$uid" --pull never \
        --cap-drop ALL --security-opt no-new-privileges:true -v "$PREFIX/data:/install-data" \
        --entrypoint /bin/sh "$(helper_image)" -c "cat >/install-data/$app-app-key" ||
        die "could not write data/$app-app-key"
}

provision_app_keys() {
    local profiles app restart=()
    profiles="$(env_get COMPOSE_PROFILES "$PREFIX/.env")"
    for app in $(app_ids); do
        [[ ",$profiles," == *",$app,"* ]] && [ -n "$(app_field "$app" 5)" ] || continue
        if provision_app_key "$app"; then restart+=("$app"); fi
    done
    [ "${#restart[@]}" -gt 0 ] || return 0
    compose restart "${restart[@]}" >/dev/null
    compose up -d --wait --wait-timeout "$WAIT_SECONDS" "${restart[@]}" >/dev/null ||
        die "${restart[*]} did not become healthy with the app key: see docker compose logs ${restart[*]}"
}

# The demo story (plantcraft/demo_seed.py): idempotent, so every install or upgrade with the
# demo profile repairs it. A failure is reported, never fatal: the suite itself is up.
seed_demo() {
    [[ ",$(env_get COMPOSE_PROFILES "$PREFIX/.env")," == *",demo,"* ]] || return 0
    log "Writing the demo story (plant map, loops, algorithms, model examples, dashboards, messages)"
    if ! compose exec -T \
        -e PLANTCRAFT_PUBLIC_DEMO_PASSWORD="$(env_get PLANTCRAFT_PUBLIC_DEMO_PASSWORD "$PREFIX/.env")" \
        processcraft processcraft demo seed; then
        warn "the demo story is incomplete (see above); run it again with: docker compose --project-directory $PREFIX exec processcraft processcraft demo seed"
    fi
}

print_access() {
    local names first port url ca="$PREFIX/local-ca-root.crt"
    names="$(env_get PLANTCRAFT_HOSTNAME "$PREFIX/.env" | tr ',' ' ')"
    first="$(printf '%s' "$names" | awk '{print $1}')"
    port="$(env_get PLANTCRAFT_HTTPS_PORT "$PREFIX/.env")"
    url="https://${first:-localhost}$([ "${port:-443}" = 443 ] || printf ':%s' "$port")/"
    echo
    echo "PlantCraft is running: $url"
    echo "  Administrator: $(env_get PLANTCRAFT_ADMIN_USERNAME "$PREFIX/.env")"
    if [ -n "$NEW_PASSWORD" ]; then
        echo "  Password:      $NEW_PASSWORD"
        echo "  (shown once; stored in $PREFIX/data/initial-admin-password, mode 0600)"
    else
        echo "  Password:      unchanged (data/initial-admin-password)"
    fi
    if [ -f "$PREFIX/certs/cert.pem" ]; then
        echo "  HTTPS:         client certificate in certs/cert.pem"
    else
        # The local CA's public root certificate, readable for distribution to browsers.
        # PlantCraft adds it to the Notebooks kits people download (plantcraft/notebooks/kits.py).
        as_root "$(helper_image)" "cp /install/data/proxy/caddy/pki/authorities/local/root.crt /install/local-ca-root.crt && chmod 0644 /install/local-ca-root.crt && cp /install/local-ca-root.crt /install/data/processcraft/local-ca-root.crt" ||
            warn "could not copy the local CA root certificate"
        echo "  HTTPS:         local CA; install this root certificate in the browsers: $ca"
    fi
    if [ "$(env_get PLANTCRAFT_PUBLIC_DEMO "$PREFIX/.env")" = true ]; then
        echo "  Public demo:   visitors click Enter the demo (read-only visits, docs/public-demo.md)"
    fi
    echo "  Took $(($(date +%s) - STARTED_AT)) s. Backups: $PREFIX/backups"
}

do_install() {
    if [ "$(env_get PLANTCRAFT_WORKER "$PREFIX/.env")" = 1 ]; then
        die "$PREFIX is a compute worker's folder: run ./install.sh --worker there."
    fi
    check_docker
    local version plant_version previous app app_version
    if [ "$DEV" = 1 ]; then
        version="${PLANTCRAFT_VERSION:-$(env_get PLANTCRAFT_VERSION "$BUNDLE_DIR/.env.example")}"
        plant_version="${SIMCRAFT_VERSION:-}"
        warn "--dev: no bundle check and no image load; using local images processcraft:$version"
        # The apps of a source checkout are the ones whose image is built here (`make image` in
        # each app's repository), so that --all-apps means them.
        for app in $(app_ids); do
            app_version="$(env_get "$(version_key "$app")" "$BUNDLE_DIR/.env.example")"
            app_version="${app_version:-0.5.1}"
            if app_image "$app" "$app_version"; then BUNDLE_APP_VERSIONS="$BUNDLE_APP_VERSIONS $app=$app_version"; fi
        done
    elif [ "$INSTALLED" = 1 ] && [ "$PREFIX" = "$BUNDLE_DIR" ]; then
        version="$(env_get PLANTCRAFT_VERSION "$PREFIX/.env")"
        plant_version=""
        log "Applying the settings of $PREFIX to the installed version $version"
    else
        verify_bundle
        version="$(env_get PLANTCRAFT_VERSION "$BUNDLE_DIR/bundle.env")"
        plant_version="$(env_get SIMCRAFT_VERSION "$BUNDLE_DIR/bundle.env")"
        [ -n "$version" ] || die "bundle.env has no PLANTCRAFT_VERSION"
        for app in $(app_ids); do
            app_version="$(env_get "$(version_key "$app")" "$BUNDLE_DIR/bundle.env")"
            if [ -n "$app_version" ]; then BUNDLE_APP_VERSIONS="$BUNDLE_APP_VERSIONS $app=$app_version"; fi
        done
        # LinkCraft is on by default when the bundle has it; the other apps with --with-<app>.
        if [ -n "$(bundle_app_version linkcraft)" ]; then WITH_APPS="$WITH_APPS""linkcraft "; fi
    fi
    mkdir -p "$PREFIX" 2>/dev/null || die "cannot create $PREFIX: choose another folder with --prefix, or create it first."
    [ -w "$PREFIX" ] || die "$PREFIX is not writable by $(id -un)."
    PREFIX="$(cd "$PREFIX" && pwd)"
    log "Install folder: $PREFIX"
    check_demo "$plant_version"
    check_apps

    previous="$(env_get PLANTCRAFT_VERSION "$PREFIX/.env")"
    if [ -n "$previous" ] && [ "$previous" != "$version" ] && [ -d "$PREFIX/data" ] &&
        docker image inspect "processcraft:$previous" >/dev/null 2>&1; then
        log "Updating from $previous to $version"
        UPDATE_STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        [ "$DEV" = 1 ] || check_update "$previous" "$version"
        pre_update_backup "$previous"
        UPDATE_FROM="$previous"
        UPDATE_TO="$version"
        UPDATE_APPLYING=1
        trap on_exit EXIT
    elif [ -n "$previous" ] && [ -d "$PREFIX/data" ]; then
        log "Version $version is already installed: applying settings and certificates again"
    fi
    if [ "$DEV" = 0 ] && [ -f "$BUNDLE_DIR/images.tar" ]; then
        host_signature
        load_images
        # An update was checked above by the installed version, before anything changed.
        if [ "$UPDATE_APPLYING" = 0 ]; then check_signature "$version"; fi
    fi
    docker image inspect "processcraft:$version" >/dev/null 2>&1 || die "image processcraft:$version is not loaded."
    remove_containers
    copy_files
    set_file_modes
    write_env "$version" "$plant_version"
    prepare_data
    start_stack
    if [ "$UPDATE_APPLYING" = 1 ]; then verify_update; fi
    provision_app_keys
    seed_demo
    if [ "$UPDATE_APPLYING" = 1 ]; then
        UPDATE_APPLYING=0
        trap - EXIT
        note_update ok "updated from $UPDATE_FROM to $UPDATE_TO"
        log "Updated from $UPDATE_FROM to $UPDATE_TO. What changed: $PREFIX/RELEASE-NOTES.md"
        log "To return to $UPDATE_FROM: $PREFIX/install.sh --rollback"
    fi
    print_access
}

# Updates (docs/operations.md, section 3) -------------------------------------------------------

# The installer images of every version answer to the package's old name, processcraft (0.5.1 and
# later through plantcraft/legacy.py): the calls below run on the version installed, which may be
# older than this script.

# True when the installer image of VERSION has the operations driver and release checks.
has_ops() { # has_ops VERSION
    docker run --rm --network none --pull never --read-only --cap-drop ALL \
        --entrypoint python "processcraft-installer:$1" \
        -c "import processcraft.apps.operations, processcraft.apps.release" >/dev/null 2>&1
}

driver_busy() { [ -n "$(docker ps -q --filter 'name=^processcraft-ops$' 2>/dev/null)" ]; }

# One operation at a time (the driver's name is the lock): wait up to an hour for another one,
# such as the nightly backup the installer service started, to end.
wait_for_driver() {
    local waited=0
    while driver_busy; do
        [ "$waited" -lt 3600 ] || die "another operation (a backup or a restore) has been running for an hour: try again when it ends."
        if [ "$waited" = 0 ]; then log "Waiting for another operation (a backup or a restore) to end"; fi
        sleep 5
        waited=$((waited + 5))
    done
}

# Before anything changes: versions, signature (checked by the installed version, with the
# publisher keys this server already trusts), another operation, free disk. A refusal changes nothing.
check_update() { # check_update INSTALLED NEW
    version_ge "$2" "$1" ||
        die "this bundle ($2) is older than the installed version ($1). Going back is $PREFIX/install.sh --rollback or --restore NAME. Nothing was changed."
    local from
    from="$(env_get UPGRADE_FROM "$BUNDLE_DIR/bundle.env")"
    if [ -n "$from" ] && ! version_ge "$1" "$from"; then
        die "$2 updates $from or later; $1 is installed. Update to $from first. Nothing was changed."
    fi
    if has_ops "$1"; then
        log "Checking the release and its signature with the installed version $1"
        local trusted=() args=(check /bundle --installed "$1")
        INSTALLED_TRUST=0
        if has_installed_trust; then INSTALLED_TRUST=1; fi
        set_trust_dir
        if [ -d "$TRUST_DIR" ]; then
            trusted=(-v "$TRUST_DIR:/trusted:ro")
            args+=(--trusted /trusted)
        fi
        if [ "$INSTALLED_TRUST" = 0 ] && [ -z "$PUBLISHER_KEY" ] && [ -n "$(bundle_keys)" ]; then
            warn "this installation trusts no publisher yet: the bundle's own key ($(bundle_keys)) is checked and then trusted. Compare its key id with the one published with the release."
        fi
        if [ "$ALLOW_UNSIGNED" = 1 ]; then args+=(--allow-unsigned); fi
        docker run --rm --network none --pull never --read-only --cap-drop ALL \
            --security-opt no-new-privileges:true --user "$(id -u):$(id -g)" \
            -v "$BUNDLE_DIR:/bundle:ro" "${trusted[@]}" \
            --entrypoint python "processcraft-installer:$1" -m processcraft.apps.release "${args[@]}" >/dev/null ||
            die "the bundle was refused (the reason is above). Nothing was changed."
        if [ -n "$TRUST_TMP" ]; then rm -rf "$TRUST_TMP"; TRUST_TMP=""; fi
    else
        warn "the installed version $1 cannot check signatures: only SHA256SUMS was checked."
    fi
    local need free images data
    images="$(stat -c %s "$BUNDLE_DIR/images.tar" 2>/dev/null || echo 0)"
    data="$(as_root "$(helper_image)" "du -sk /install/data 2>/dev/null | cut -f1" || echo 0)"
    need=$((images / 1024 + 2 * ${data:-0}))
    free="$(df -Pk "$PREFIX" | awk 'NR == 2 { print $4 }')"
    [ "${free:-0}" -ge "$need" ] ||
        die "not enough free disk in $PREFIX: $((need / 1024)) MB needed (the new images and twice the data), $((${free:-0} / 1024)) MB free. Nothing was changed."
}

# The backup an update returns to: online and verified by the operations driver of the installed
# version; an installation from before the driver gets the stop-and-copy backup of this script.
pre_update_backup() { # pre_update_backup INSTALLED
    if has_ops "$1"; then
        log "Backing up before the update (while the suite runs; checked before it counts)"
        DRIVER_IMAGE="processcraft-installer:$1" run_driver drive backup --reason pre-update ||
            die "the backup before the update failed (the reason is above). Nothing was changed."
        UPDATE_BACKUP="$(DRIVER_IMAGE="processcraft-installer:$1" run_driver latest --reason pre-update)" ||
            die "the backup before the update cannot be found. Nothing was changed."
    else
        backup "$1"
    fi
}

# After the start: every service of the new version running, healthy and on its new image.
verify_update() {
    has_ops "$UPDATE_TO" || return 0
    log "Checking every service of $UPDATE_TO"
    run_driver health >/dev/null || {
        run_driver health || true
        die "the new version $UPDATE_TO is not healthy (above)."
    }
}

# What the failed attempt looked like, kept for diagnosis before the containers are replaced.
save_update_log() {
    local file
    file="$PREFIX/update-$(date +%Y%m%d-%H%M%S)-$UPDATE_TO-failed.log"
    (
        umask 077
        {
            echo "Update from $UPDATE_FROM to $UPDATE_TO, failed at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
            compose ps -a 2>&1 || true
            compose logs --no-color --tail 200 2>&1 || true
        } >"$file"
    )
    printf '%s' "$file"
}

note_update() { # note_update STATE MESSAGE: in the operations history and the Updates page
    has_ops "$(env_get PLANTCRAFT_VERSION "$PREFIX/.env")" || return 0
    run_driver note-update --from "$UPDATE_FROM" --to "$UPDATE_TO" --state "$1" --message "$2" \
        --backup "$UPDATE_BACKUP" --started-at "$UPDATE_STARTED" >/dev/null 2>&1 || true
}

# A failure while an update changes the suite (die, an error, Ctrl-C): back to UPDATE_FROM.
on_exit() {
    local code=$?
    [ "$UPDATE_APPLYING" = 1 ] && [ "$code" != 0 ] || return 0
    UPDATE_APPLYING=0
    trap - EXIT
    set +e
    local details
    details="$(save_update_log)"
    warn "The update to $UPDATE_TO failed: returning to $UPDATE_FROM by itself."
    if [ -n "$UPDATE_BACKUP" ]; then
        if DRIVER_IMAGE="processcraft-installer:$UPDATE_FROM" run_driver drive restore --name "$UPDATE_BACKUP"; then
            note_update returned "the update to $UPDATE_TO failed; returned to $UPDATE_FROM (details: $(basename "$details"))"
            warn "Back on $UPDATE_FROM, healthy, with its data. The failed attempt is described in $details"
        else
            warn "The return to $UPDATE_FROM failed too. The data before the update is in backups/$UPDATE_BACKUP; run $PREFIX/install.sh --restore $UPDATE_BACKUP or ask for help. Details: $details"
        fi
    else
        ASSUME_YES=1
        (legacy_rollback) || warn "The return to $UPDATE_FROM failed too: run $PREFIX/install.sh --rollback. Details: $details"
    fi
    exit "$code"
}

do_rollback() {
    check_docker
    installed_prefix
    local version name
    version="$(env_get PLANTCRAFT_VERSION "$PREFIX/.env")"
    if has_ops "$version" && name="$(run_driver latest --reason pre-update --before "$version")" && [ -n "$name" ]; then
        confirm "Return to backup $name, taken before the last update? The suite stops for a few minutes; data written since then is set aside in backups/, not deleted."
        run_driver drive restore --name "$name" || die "the rollback did not complete (the reason is above)."
        UPDATE_FROM="$version"
        UPDATE_TO="$(env_get PLANTCRAFT_VERSION "$PREFIX/.env")"
        UPDATE_BACKUP="$name"
        note_update rolled-back "returned from $UPDATE_FROM to $UPDATE_TO (install.sh --rollback)"
        log "Back on $UPDATE_TO."
        print_access
        return 0
    fi
    legacy_rollback
}

# The return of installations from before the operations driver: backups/LATEST, stop and copy.
legacy_rollback() {
    [ -f "$PREFIX/backups/LATEST" ] || die "no backup to return to in $PREFIX/backups"
    local stamp dir image
    stamp="$(cat "$PREFIX/backups/LATEST")"
    dir="$PREFIX/backups/$stamp"
    [ -f "$dir/data.tar.gz" ] && [ -f "$dir/images.txt" ] || die "backup $stamp is incomplete"
    confirm "Return to backup $stamp? Data written since then is set aside in backups/, not deleted."
    image="$(awk '$1 ~ /^processcraft:/ { print $2; exit }' "$dir/images.txt")"
    [ -n "$image" ] || die "backup $stamp does not name a processcraft image"
    log "Stopping the suite"
    compose down --remove-orphans || true
    local aside
    aside="$(date +%Y%m%d-%H%M%S)-before-rollback"
    log "Setting the current data aside in backups/$aside"
    mkdir -p "$PREFIX/backups/$aside"
    as_root "$image" "cd /install && tar --numeric-owner -czf backups/$aside/data.tar.gz data certs"
    log "Restoring images, settings and data from backups/$stamp"
    local ref id
    while read -r ref id; do
        [ -n "$ref" ] || continue
        if [[ "$ref" == *@sha256:* ]]; then
            # Pinned by digest: the same reference always names the same image.
            docker image inspect "$ref" >/dev/null 2>&1 || die "image $ref is no longer on this host"
            continue
        fi
        docker tag "$id" "$ref" || die "image $ref ($id) is no longer on this host"
    done <"$dir/images.txt"
    local file
    for file in .env compose.yaml bundle.env; do
        if [ -f "$dir/$file" ]; then cp -p "$dir/$file" "$PREFIX/$file"; fi
    done
    as_root "$image" "cd /install && rm -rf data && tar --numeric-owner -xzpf backups/$stamp/data.tar.gz"
    start_stack
    print_access
}

# purge_images PROJECT < image names: remove each image no container of another Compose project
# uses (by the name it was started with: removing a tag that another installation's containers
# were created from leaves them unable to start again); prints the names kept. An installation
# whose containers were removed (compose down) cannot be seen, and its images go.
purge_images() {
    local project="$1" others image
    others="$(docker ps -a --format '{{.Label "com.docker.compose.project"}}|{{.Image}}' 2>/dev/null |
        awk -F'|' -v p="$project" '$1 != p {print $2}' | sort -u)"
    while IFS= read -r image; do
        [ -n "$image" ] || continue
        if printf '%s\n' "$others" | grep -qxF -- "$image"; then
            printf '%s\n' "$image"
        else
            docker image rm "$image" >/dev/null 2>&1 || true
        fi
    done
}

do_uninstall() {
    check_docker
    [ -d "$PREFIX" ] || die "no installation in $PREFIX (use --prefix)"
    PREFIX="$(cd "$PREFIX" && pwd)"
    [ -f "$PREFIX/compose.yaml" ] || die "no installation in $PREFIX"
    if [ "$PURGE" = 1 ]; then
        confirm "Delete ALL data, backups and images of PlantCraft in $PREFIX? This cannot be undone."
        local image
        image="$(helper_image)"
        compose down --remove-orphans --volumes || true
        as_root "$image" "cd /install && rm -rf data backups certs/key.pem certs/cert.pem local-ca-root.crt"
        local project kept
        project="$(compose config 2>/dev/null | awk '/^name:/ {print $2; exit}')"
        kept="$( { compose config --images 2>/dev/null
            docker images --format '{{.Repository}}:{{.Tag}}' |
                grep -E '^(processcraft|processcraft-proxy|processcraft-installer|linkcraft|dashcraft|histcraft|alarmcraft|modelcraft|modelcraft-runner|doccraft|postgres|telegraf|simcraft|plantcraft):rollback-'
        } | sort -u | purge_images "$project")"
        log "Removed containers, networks, images, data and backups. The folder $PREFIX holds only the suite files now."
        [ -z "$kept" ] || log "Kept the images another installation on this Docker still uses: $(printf '%s' "$kept" | xargs)"
    else
        compose down --remove-orphans
        log "Stopped and removed the containers and networks. Data, backups, settings and images are kept in $PREFIX."
        log "Start again with: $PREFIX/install.sh  (or delete everything with --uninstall --purge)"
    fi
}

# Runs the installer image once, with the same rights as the installer service.
run_installer() { # run_installer ARGS...
    local version gid
    version="$(env_get PLANTCRAFT_VERSION "$PREFIX/.env")"
    gid="$(env_get PLANTCRAFT_DOCKER_GID "$PREFIX/.env")"
    docker image inspect "processcraft-installer:$version" >/dev/null 2>&1 ||
        die "image processcraft-installer:$version is not loaded: install or upgrade the suite first."
    docker run --rm -i --network none --pull never --read-only \
        --user "$INSTALLER_UID:$INSTALLER_UID" --group-add "${gid:-0}" \
        --cap-drop ALL --security-opt no-new-privileges:true \
        --tmpfs /tmp:size=64m,mode=1777,noexec,nosuid,nodev \
        --env-file "$PREFIX/.env" \
        -e PLANTCRAFT_INSTALL_DIR="$PREFIX" \
        -e PLANTCRAFT_INSTALLER_IMAGE="processcraft-installer:$version" \
        -v /var/run/docker.sock:/var/run/docker.sock \
        -v "$PREFIX/compose.yaml:$PREFIX/compose.yaml:ro" \
        -v "$PREFIX/data/installer:$PREFIX/data/installer" \
        -v "$PREFIX/trusted-publishers:/trusted-publishers:ro" \
        "processcraft-installer:$version" "$@"
}

# The operations driver (plantcraft.apps.operations): the installer image as root, no network,
# the install folder at its own path and the Docker socket. The same code the Backups page runs.
run_driver() { # run_driver ARGS...
    local version image project attempt code=0
    version="$(env_get PLANTCRAFT_VERSION "$PREFIX/.env")"
    image="${DRIVER_IMAGE:-processcraft-installer:$version}"
    project="$(env_get COMPOSE_PROJECT_NAME "$PREFIX/.env")"
    docker image inspect "$image" >/dev/null 2>&1 ||
        die "image $image is not loaded: install or upgrade the suite first."
    for attempt in 1 2 3; do
        wait_for_driver
        docker run --rm --name processcraft-ops --network none --user 0:0 --pull never --read-only \
            --cap-drop ALL --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER --cap-add FSETID \
            --security-opt no-new-privileges:true \
            --tmpfs /tmp:size=256m,mode=1777,noexec,nosuid,nodev \
            --label org.processcraft.ops=driver \
            -e PLANTCRAFT_INSTALL_DIR="$PREFIX" -e COMPOSE_PROJECT_NAME="${project:-processcraft}" \
            -v /var/run/docker.sock:/var/run/docker.sock -v "$PREFIX:$PREFIX" \
            --entrypoint python "$image" -m processcraft.apps.operations "$@" && return 0 || code=$?
        # 125: Docker refused to start it; another driver took the name meanwhile, so wait again.
        [ "$code" = 125 ] && driver_busy || return "$code"
    done
    return "$code"
}

do_backup() {
    check_docker
    installed_prefix
    log "Backing up while the suite runs (databases copied online, then verified)"
    run_driver drive backup --reason manual || die "the backup failed (the reason is above); nothing else changed."
}

do_drill() {
    check_docker
    installed_prefix
    log "Restore drill: the latest good backup in a separate, isolated copy of the suite"
    run_driver drive drill || die "the restore drill failed (the reason is above); the suite was not touched."
}

do_list_backups() {
    check_docker
    installed_prefix
    run_driver list
}

do_restore() {
    check_docker
    installed_prefix
    [[ "$BACKUP_NAME" =~ ^[0-9]{8}-[0-9]{6}-[a-z][a-z0-9-]{1,30}$ ]] || die "invalid backup name: $BACKUP_NAME (see --list-backups)"
    confirm "Return to backup $BACKUP_NAME? The suite stops for a few minutes; the current data is set aside in backups/, not deleted."
    run_driver drive restore --name "$BACKUP_NAME" ||
        die "the restore did not complete (the reason is above)."
    log "Restored $BACKUP_NAME."
    print_access
}

# A backup holds .env, every app key, the admin and database passwords and the certificate
# authority's key in clear (mode 0600, root): fine on the server, not on a disk that leaves it.
# The copy is AES-256 (OpenSSL, key from the passphrase with PBKDF2, 600,000 rounds); the backup's
# manifest checks every file again when it is restored.
#   openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -pass file:PASS -in X.tar.enc | tar -x
do_export_backup() {
    check_docker
    installed_prefix
    [[ "$BACKUP_NAME" =~ ^[0-9]{8}-[0-9]{6}-[a-z][a-z0-9-]{1,30}$ ]] || die "invalid backup name: $BACKUP_NAME (see --list-backups)"
    [ -n "$PASSPHRASE_FILE" ] && [ -r "$PASSPHRASE_FILE" ] || die "--passphrase-file FILE is needed: the passphrase, one line, at least 16 characters"
    [ "$(head -n 1 "$PASSPHRASE_FILE" | tr -d '\n' | wc -c)" -ge 16 ] || die "the passphrase must have at least 16 characters"
    command -v openssl >/dev/null 2>&1 || die "openssl is not on this server"
    local out="${EXPORT_OUT:-$PWD/plantcraft-backup-$BACKUP_NAME.tar.enc}" image
    image="$(helper_image)"
    [ ! -e "$out" ] || die "$out exists: choose another --out"
    log "Encrypting backups/$BACKUP_NAME to $out"
    (umask 077 && as_root "$image" "cd /install/backups && test -d '$BACKUP_NAME' && tar --numeric-owner -cf - '$BACKUP_NAME'" |
        openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -salt -pass "file:$PASSPHRASE_FILE" -out "$out") ||
        { rm -f "$out"; die "the backup could not be exported (is the name right? see --list-backups)."; }
    [ -s "$out" ] || { rm -f "$out"; die "the export wrote nothing."; }
    chmod 0600 "$out"
    log "Written: $out ($(du -h "$out" | cut -f1)). Keep the passphrase apart from the file."
}

do_diagnostics() {
    check_docker
    installed_prefix
    local out
    out="$PWD/processcraft-diagnostics-$(date -u +%Y%m%d-%H%M%S).zip"
    log "Collecting a diagnostic bundle: versions, Docker's view, health, the end of each log, settings without secrets"
    run_installer diagnostics --out - --by "$(id -un)" >"$out" || { rm -f "$out"; die "the diagnostic bundle could not be written (the reason is above)."; }
    chmod 600 "$out"
    log "Written: $out (read it before sending it: log lines may name tags, assets and people)."
}

installed_prefix() {
    [ -d "$PREFIX" ] && [ -f "$PREFIX/.env" ] && [ -d "$PREFIX/data/installer" ] ||
        die "no installation in $PREFIX (use --prefix)"
    PREFIX="$(cd "$PREFIX" && pwd)"
}

do_add() {
    check_docker
    installed_prefix
    [ -f "$APP_PACKAGE" ] && [ -r "$APP_PACKAGE" ] || die "cannot read the package $APP_PACKAGE"
    log "Verifying and installing $(basename "$APP_PACKAGE") (signature and SHA-256 are checked by the installer)"
    run_installer add - --by "$(id -un)" <"$APP_PACKAGE" ||
        die "the package was not installed (the reason is above); nothing else changed."
    log "Installed. PlantCraft lists it on the Apps page and in the launcher."
}

do_remove() {
    check_docker
    installed_prefix
    [[ "$APP_ID" =~ ^[a-z][a-z0-9-]{1,39}$ ]] || die "invalid app id: $APP_ID"
    confirm "Remove the app $APP_ID? Its data in data/apps/$APP_ID is kept."
    run_installer remove "$APP_ID" --by "$(id -un)" || die "$APP_ID was not removed (the reason is above)."
    log "Removed $APP_ID."
}

# A compute worker on another machine (docs/compute.md) --------------------------------------

# The apps whose executor compose-worker.yaml runs, each in the profile named after it.
WORKER_APPS=(linkcraft modelcraft)
# The image an app's executor runs: the app's own, but OpenModelica's runner for Models.
executor_image() { if [ "$1" = modelcraft ]; then echo modelcraft-runner; else echo "$1"; fi; }

do_worker() {
    check_docker
    local env version app app_version file profiles="" waited=0
    if [ "$INSTALLED" = 1 ] && [ "$PREFIX" = "$BUNDLE_DIR" ]; then
        version="$(env_get PLANTCRAFT_VERSION "$PREFIX/.env")"
        [ -n "$WORKER_PLATFORM" ] || WORKER_PLATFORM="$(env_get PLANTCRAFT_PLATFORM_URL "$PREFIX/.env")"
    else
        verify_bundle
        version="$(env_get PLANTCRAFT_VERSION "$BUNDLE_DIR/bundle.env")"
        [ -n "$version" ] || die "bundle.env has no PLANTCRAFT_VERSION"
    fi
    [[ "$WORKER_PLATFORM" =~ ^https?://[A-Za-z0-9.:-]+(:[0-9]+)?/?$ ]] ||
        die "--platform needs PlantCraft's address, like https://plantcraft.plant.local"
    WORKER_PLATFORM="${WORKER_PLATFORM%/}"
    mkdir -p "$PREFIX" 2>/dev/null || die "cannot create $PREFIX: choose another folder with --prefix."
    PREFIX="$(cd "$PREFIX" && pwd)"
    log "Compute worker folder: $PREFIX, for $WORKER_PLATFORM"
    if [ -f "$PREFIX/data/worker/credential" ] && [ -n "$WORKER_CODE" ]; then
        warn "this worker is enrolled already: the code is not used (remove data/worker/credential to enroll it again)."
        WORKER_CODE=""
    elif [ ! -f "$PREFIX/data/worker/credential" ] && [ -z "$WORKER_CODE" ]; then
        die "--code is needed the first time: PlantCraft › Settings › Compute › Add worker."
    fi
    if [ "$PREFIX" != "$BUNDLE_DIR" ]; then
        if [ -f "$BUNDLE_DIR/images.tar" ]; then
            host_signature
            load_images
            check_signature "$version"
        fi
        cp "$BUNDLE_DIR/compose-worker.yaml" "$PREFIX/compose.yaml"
        cp "$BUNDLE_DIR/install.sh" "$PREFIX/install.sh"
        for file in bundle.env release.json RELEASE-NOTES.md; do
            if [ -f "$BUNDLE_DIR/$file" ]; then cp "$BUNDLE_DIR/$file" "$PREFIX/"; fi
        done
    fi
    chmod 0644 "$PREFIX/compose.yaml"
    chmod 0755 "$PREFIX/install.sh"
    docker image inspect "processcraft:$version" >/dev/null 2>&1 || die "image processcraft:$version is not loaded."
    env="$PREFIX/.env"
    if [ ! -f "$env" ]; then (umask 027 && : >"$env"); fi
    env_set PLANTCRAFT_WORKER 1 "$env"
    env_set PLANTCRAFT_VERSION "$version" "$env"
    env_set PLANTCRAFT_PLATFORM_URL "$WORKER_PLATFORM" "$env"
    for app in "${WORKER_APPS[@]}"; do
        app_version="$(env_get "$(version_key "$app")" "$PREFIX/bundle.env")"
        app_version="${app_version:-$(env_get "$(version_key "$app")" "$env")}"
        if [ -n "$app_version" ] && app_image "$(executor_image "$app")" "$app_version"; then
            env_set "$(version_key "$app")" "$app_version" "$env"
            profiles="${profiles:+$profiles,}$app"
        fi
    done
    [ -n "$profiles" ] || die "this bundle has no app image with an executor (${WORKER_APPS[*]})."
    env_set COMPOSE_PROFILES "$profiles" "$env"
    mkdir -p "$PREFIX/certs" "$PREFIX/data/worker" "$PREFIX/data/compute-jobs"
    if [ -n "$WORKER_CA" ]; then
        [ -f "$WORKER_CA" ] || die "--ca: $WORKER_CA is not a file"
        cp "$WORKER_CA" "$PREFIX/certs/platform-ca.crt"
        chmod 0644 "$PREFIX/certs/platform-ca.crt"
    fi
    if [ -f "$PREFIX/certs/platform-ca.crt" ]; then
        env_set PLANTCRAFT_CA_FILE /certs/platform-ca.crt "$env"
    fi
    log "Setting owners of data/ (the worker's user $COMPUTE_UID)"
    as_root "processcraft:$version" "
        set -e
        cd /install
        for app in ${WORKER_APPS[*]}; do mkdir -p data/compute-jobs/\$app; done
        chown -R $COMPUTE_UID:$COMPUTE_UID data/worker data/compute-jobs
        chmod 0700 data/worker data/compute-jobs
    "
    if [ -n "$WORKER_CODE" ]; then
        # Only for the first start: the gateway trades it for its own credential.
        env_set PLANTCRAFT_COMPUTE_CODE "$WORKER_CODE" "$env"
    fi
    log "Starting the compute worker ($profiles)"
    compose up -d --remove-orphans >/dev/null || die "the worker did not start: see docker compose --project-directory $PREFIX logs"
    if [ -n "$WORKER_CODE" ]; then
        while ! as_root "processcraft:$version" "test -s /install/data/worker/credential" 2>/dev/null; do
            waited=$((waited + 2))
            if [ "$waited" -ge 90 ]; then
                env_set PLANTCRAFT_COMPUTE_CODE "" "$env"
                compose logs --tail 20 compute-gateway >&2 || true
                die "the worker did not enroll (the reason is above): make a new code in Settings › Compute and run again."
            fi
            sleep 2
        done
        env_set PLANTCRAFT_COMPUTE_CODE "" "$env"
        log "Enrolled: PlantCraft lists this worker in Settings › Compute."
        compose up -d >/dev/null
    fi
    compose up -d --wait --wait-timeout "$WAIT_SECONDS" >/dev/null ||
        die "the worker did not become healthy: see docker compose --project-directory $PREFIX logs compute-gateway"
    log "The compute worker is running. Pause or revoke it in PlantCraft › Settings › Compute."
}

# The apps this run would install, for the requirements check: the installation file's, or
# --all-apps, or Analytics (on by default) and the --with-<app> ones.
check_apps() {
    local apps
    if [ "$ALL_APPS" = 1 ]; then echo all; return; fi
    apps="$(printf '%s' "$WITH_APPS" | xargs)"
    if [ -z "$CONF_APPS" ] && [[ " $apps " != *" linkcraft "* ]]; then apps="linkcraft $apps"; fi
    printf '%s' "$apps" | xargs | tr ' ' ','
}

do_check() {
    [ -x "$BUNDLE_DIR/preflight.sh" ] || die "preflight.sh is missing next to install.sh"
    local args=(--prefix "$PREFIX" --apps "$(check_apps)")
    [ "$CHECK_JSON" = 1 ] && args+=(--json)
    PLANTCRAFT_INSTALLATION_CONF="${INSTALLATION_CONF:-/etc/plantcraft/installation.conf}" \
        "$BUNDLE_DIR/preflight.sh" "${args[@]}"
}

# What the installation file sets against what .env holds: "differs" means .env was edited by
# hand (or install.sh was not run since the file changed): the next run puts the file's value back.
# Exit code, like diff: 0 when .env holds what the file sets and the file was applied as it is
# now; 1 when a value differs or the file changed or was never applied (monitoring can alert on it).
do_show_config() {
    [ -n "$INSTALLATION_CONF" ] || { log "No installation file (/etc/plantcraft/installation.conf): .env alone decides."; return 0; }
    local env="$PREFIX/.env" pair key want have state applied current differs=0
    printf 'Installation file: %s\n' "$INSTALLATION_CONF"
    current="$(sha256sum "$INSTALLATION_CONF" | cut -c 1-64)"
    applied="$(env_get PLANTCRAFT_INSTALLATION_CONF_SHA256 "$env")"
    if [ -z "$applied" ]; then
        printf 'Never applied to %s: run %s/install.sh\n\n' "$env" "$PREFIX"
        differs=1
    elif [ "$applied" != "$current" ]; then
        printf 'Changed since it was last applied: run %s/install.sh to apply it\n\n' "$PREFIX"
        differs=1
    else
        printf 'Applied (SHA-256 %s)\n\n' "${current:0:16}"
    fi
    printf '  %-36s %-28s %-28s %s\n' "Setting (.env)" "Installation file" ".env now" ""
    for pair in "${CONF_ENV[@]}"; do
        key="${pair%%=*}"
        want="${pair#*=}"
        have="$(env_get "$key" "$env")"
        state=""
        [ "$want" = "$have" ] || { state="differs"; differs=1; }
        printf '  %-36s %-28s %-28s %s\n' "$key" "${want:-(empty)}" "${have:-(empty)}" "$state"
    done
    if [ -n "$CONF_APPS" ]; then
        want="$(printf '%s' "$CONF_APPS" | xargs | tr ' ' ',')"
        have="$(env_get COMPOSE_PROFILES "$env" | tr ',' '\n' | grep -v '^demo$' | paste -sd, -)"
        state=""
        [ "$want" = "$have" ] || { state="differs"; differs=1; }
        printf '  %-36s %-28s %-28s %s\n' "COMPOSE_PROFILES (apps)" "$want" "${have:-(empty)}" "$state"
    fi
    return "$differs"
}

# With --check --json only the report goes to stdout, so tools can read it.
if [ "$ACTION" = check ] && [ "$CHECK_JSON" = 1 ]; then log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" >&2; }; fi
case "$ACTION" in install | check | show-config) load_installation_conf ;; esac
case "$ACTION" in
    check) do_check ;;
    show-config) do_show_config ;;
    install)
        # A server that fails the requirements stops here, before anything is changed.
        # --install-docker puts the bundle's Docker Engine in place before the check looks for it.
        if [ "$INSTALL_DOCKER" = 1 ]; then check_docker; fi
        if [ -x "$BUNDLE_DIR/preflight.sh" ] && [ "$DEV" = 0 ] && [ "${PLANTCRAFT_SKIP_CHECK:-0}" != 1 ]; then
            do_check || die "the requirements check failed (above); nothing was changed. PLANTCRAFT_SKIP_CHECK=1 skips it."
        fi
        do_install ;;
    worker) do_worker ;;
    add) do_add ;;
    remove) do_remove ;;
    rollback) do_rollback ;;
    backup) do_backup ;;
    list-backups) do_list_backups ;;
    drill) do_drill ;;
    diagnostics) do_diagnostics ;;
    restore) do_restore ;;
    export-backup) do_export_backup ;;
    security-check)
        [ -x "$PREFIX/security-check.sh" ] || die "no security-check.sh in $PREFIX: install this bundle first"
        exec "$PREFIX/security-check.sh" "${CHECK_ARGS[@]}"
        ;;
    uninstall) do_uninstall ;;
esac
