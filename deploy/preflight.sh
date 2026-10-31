#!/usr/bin/env bash
# PlantCraft requirements check, run before anything is installed (docs/requirements.md).
#
#   ./preflight.sh                      check this server for the apps of installation.conf (or all)
#   ./preflight.sh --apps "link,hist"   check for these apps only (ids or short names)
#   ./preflight.sh --prefix DIR         the install folder whose disk is checked (default /opt/plantcraft)
#   ./preflight.sh --json               the same report as JSON, for the setup wizard
#
# It changes nothing and needs no network. Every line is PASS, WARN or FAIL; the exit code is 1
# when one line is FAIL (install.sh --check and the setup wizard stop there), 0 otherwise.
# The CPUs and memory are read the way the machine profile reads them (docker info NCPU and
# MemTotal, so on Docker Desktop or WSL they are the VM's), and the host's own when Docker is
# missing.
set -uo pipefail

PREFIX="${PLANTCRAFT_HOME:-/opt/plantcraft}"
APPS=""
JSON=0
CONF="${PLANTCRAFT_INSTALLATION_CONF:-/etc/plantcraft/installation.conf}"
BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIN_DOCKER="24.0.0"
MIN_COMPOSE="2.24.0"
PORT=443

while [ $# -gt 0 ]; do
    case "$1" in
        --apps) APPS="$2"; shift ;;
        --apps=*) APPS="${1#*=}" ;;
        --prefix) PREFIX="$2"; shift ;;
        --prefix=*) PREFIX="${1#*=}" ;;
        --config) CONF="$2"; shift ;;
        --json) JSON=1 ;;
        -h | --help) sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

conf_get() { [ -r "$CONF" ] && sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$CONF" | sed 's/[[:space:]]*#.*$//; s/^"//; s/"$//' | tail -n 1; }
if [ -z "$APPS" ]; then APPS="$(conf_get APPS)"; fi
APPS="${APPS:-all}"
p="$(conf_get HTTPS_PORT)"; PORT="${p:-$PORT}"

# Memory each app needs idle plus its share at work, in MB (docs/requirements.md: 4.5 to 7 GB for
# all of them idle; the busiest peak at about 1 GB each). The platform, proxy and installer: 1.5 GB.
app_mb() {
    case "$1" in
        linkcraft) echo 2500 ;; histcraft) echo 2000 ;; dashcraft) echo 700 ;;
        alarmcraft) echo 400 ;; modelcraft) echo 1500 ;; doccraft) echo 900 ;; *) echo 0 ;;
    esac
}
app_id() {
    case "$1" in
        link | analytics | linkcraft) echo linkcraft ;; hist | historian | histcraft) echo histcraft ;;
        dash | view | dashcraft) echo dashcraft ;; alarm | alarms | alarmcraft) echo alarmcraft ;;
        model | models | modelcraft) echo modelcraft ;; doc | documents | doccraft) echo doccraft ;;
        *) echo "" ;;
    esac
}
if [ "$APPS" = all ]; then
    APP_IDS="linkcraft histcraft dashcraft alarmcraft modelcraft doccraft"
else
    APP_IDS=""
    for a in $(printf '%s' "$APPS" | tr ',' ' '); do
        id="$(app_id "$a")"
        [ -n "$id" ] && APP_IDS="$APP_IDS $id"
    done
fi

RESULTS=()
FAILS=0
WARNS=0
add() { # add STATE NAME FOUND NEEDED [HOW TO FIX]
    RESULTS+=("$1|$2|$3|$4|${5:-}")
    [ "$1" = FAIL ] && FAILS=$((FAILS + 1))
    [ "$1" = WARN ] && WARNS=$((WARNS + 1))
    return 0
}
version_ge() { [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n 1)" = "$2" ]; }

# 1. Operating system and processor ------------------------------------------------------------
os="$(uname -s)"
kernel="$(uname -r)"
distro="$( (. /etc/os-release 2>/dev/null && printf '%s' "${PRETTY_NAME:-}") || true)"
wsl=0
grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null && wsl=1
if [ "$os" != Linux ]; then
    add WARN "Operating system" "$os" "Linux server" "macOS runs through Docker Desktop: fine for trials, not for a plant."
elif [ "$wsl" = 1 ]; then
    add WARN "Operating system" "${distro:-Linux} on WSL 2" "Linux server" "Windows (WSL 2) is fine for trials; a plant runs on a Linux server."
else
    add PASS "Operating system" "${distro:-Linux} (kernel $kernel)" "Linux with kernel 4.18 or newer"
fi

arch="$(uname -m)"
case "$arch" in x86_64 | amd64) arch=amd64 ;; aarch64 | arm64) arch=arm64 ;; esac
want="$(sed -n 's/^ARCH=//p' "$BUNDLE_DIR/bundle.env" 2>/dev/null)"
if [ -n "$want" ] && [ "$want" != "$arch" ]; then
    add FAIL "Processor" "$arch" "$want (this bundle)" "Get the linux/$arch bundle of this release."
elif [ "$arch" = amd64 ] || [ "$arch" = arm64 ]; then
    add PASS "Processor" "$arch" "amd64 or arm64"
else
    add FAIL "Processor" "$arch" "amd64 or arm64"
fi

# 2. Docker --------------------------------------------------------------------------------------
docker_ok=0
if ! command -v docker >/dev/null 2>&1; then
    add FAIL "Docker Engine" "not installed" ">= $MIN_DOCKER" "Install Docker Engine (the bundle's docker/ folder, or docs/install-offline.md section 1)."
elif ! docker info >/dev/null 2>&1; then
    add FAIL "Docker Engine" "installed, daemon not reachable" "running, and this user may use it" "Start Docker; run as root or as a member of the docker group."
else
    engine="$(docker version --format '{{.Server.Version}}' 2>/dev/null)"
    if version_ge "${engine:-0}" "$MIN_DOCKER"; then
        add PASS "Docker Engine" "$engine" ">= $MIN_DOCKER"
        docker_ok=1
    else
        add FAIL "Docker Engine" "${engine:-unknown}" ">= $MIN_DOCKER" "Update Docker Engine."
    fi
    compose="$(docker compose version --short 2>/dev/null)"
    compose="${compose#v}"
    if version_ge "${compose:-0}" "$MIN_COMPOSE"; then
        add PASS "Docker Compose" "$compose" ">= $MIN_COMPOSE"
    else
        add FAIL "Docker Compose" "${compose:-missing}" ">= $MIN_COMPOSE" "Install the docker-compose-plugin package."
    fi
    product="$(docker info --format '{{.OperatingSystem}}' 2>/dev/null)"
    case "$product" in
        *"Docker Desktop"*) add WARN "Docker product" "$product" "Docker Engine" "Docker Desktop needs a paid subscription in companies with 250+ people or US\$10M+ revenue; Docker Engine (Linux) and Rancher Desktop do not." ;;
        *) add PASS "Docker product" "${product:-unknown}" "Docker Engine" ;;
    esac
    cg="$(docker info --format '{{.CgroupVersion}}' 2>/dev/null)"
    if [ "$cg" = 2 ]; then
        add PASS "Control groups" "v2" "v2 (CPU and memory limits)"
    else
        add WARN "Control groups" "v${cg:-?}" "v2" "Limits work on v1 too, but the machine profile reads the quota from v2."
    fi
fi

# 3. CPU, memory, swap ------------------------------------------------------------------------
if [ "$docker_ok" = 1 ]; then
    cpus="$(docker info --format '{{.NCPU}}' 2>/dev/null)"
    mem_b="$(docker info --format '{{.MemTotal}}' 2>/dev/null)"
    mem_mb=$((${mem_b:-0} / 1048576))
    where="(seen by Docker)"
else
    cpus="$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)"
    mem_mb=$(($(sed -n 's/^MemTotal: *\([0-9]*\) kB/\1/p' /proc/meminfo 2>/dev/null || echo 0) / 1024))
    where="(host)"
fi
need_mb=1500
for id in $APP_IDS; do need_mb=$((need_mb + $(app_mb "$id"))); done
need_gb=$(((need_mb + 1023) / 1024))
have_gb=$(((mem_mb + 512) / 1024))
if [ "${cpus:-0}" -lt 2 ]; then
    add FAIL "CPUs" "$cpus $where" ">= 4 (2 for a trial)"
elif [ "$cpus" -lt 4 ]; then
    add WARN "CPUs" "$cpus $where" ">= 4" "Runs, but Analytics rounds are slow; machine size: small."
else
    add PASS "CPUs" "$cpus $where" ">= 4 (8 for a plant area)"
fi
if [ "$mem_mb" -lt $((need_mb * 3 / 4)) ]; then
    add FAIL "Memory" "${have_gb} GB $where" ">= ${need_gb} GB for these apps" "Add memory, or install fewer apps (APPS in installation.conf)."
elif [ "$mem_mb" -lt "$need_mb" ]; then
    add WARN "Memory" "${have_gb} GB $where" ">= ${need_gb} GB for these apps" "Turn on swap, or install fewer apps."
else
    add PASS "Memory" "${have_gb} GB $where" ">= ${need_gb} GB for these apps"
fi
swap_kb="$(sed -n 's/^SwapTotal: *\([0-9]*\) kB/\1/p' /proc/meminfo 2>/dev/null)"
if [ "${swap_kb:-0}" -eq 0 ] && [ "$mem_mb" -lt 16384 ]; then
    add WARN "Swap" "none" "2 GB or more below 16 GB of memory" "Without swap a busy moment ends a container (out of memory)."
else
    add PASS "Swap" "$((${swap_kb:-0} / 1024)) MB" "2 GB or more below 16 GB of memory"
fi

# 4. Disk ----------------------------------------------------------------------------------------
probe="$PREFIX"
while [ ! -d "$probe" ] && [ "$probe" != / ]; do probe="$(dirname "$probe")"; done
free_gb=$(($(df -Pk "$probe" 2>/dev/null | awk 'NR==2 {print $4}') / 1048576))
images_gb=0
[ -f "$BUNDLE_DIR/images.tar" ] && images_gb=$((($(stat -c %s "$BUNDLE_DIR/images.tar") / 1073741824) * 2 + 1))
need_disk=$((50 > images_gb + 20 ? 50 : images_gb + 20))
if [ "$free_gb" -lt 20 ]; then
    add FAIL "Disk free" "${free_gb} GB in $probe" ">= ${need_disk} GB" "Choose another folder (PREFIX) or free space."
elif [ "$free_gb" -lt "$need_disk" ]; then
    add WARN "Disk free" "${free_gb} GB in $probe" ">= ${need_disk} GB (1 TB for a plant area)"
else
    add PASS "Disk free" "${free_gb} GB in $probe" ">= ${need_disk} GB (1 TB for a plant area)"
fi
if [ "$docker_ok" = 1 ]; then
    root="$(docker info --format '{{.DockerRootDir}}' 2>/dev/null)"
    dfree=$(($(df -Pk "${root:-/var/lib/docker}" 2>/dev/null | awk 'NR==2 {print $4}') / 1048576))
    if [ "$dfree" -lt $((images_gb + 10)) ]; then
        add FAIL "Docker's disk" "${dfree} GB in ${root}" ">= $((images_gb + 10)) GB for the images"
    else
        add PASS "Docker's disk" "${dfree} GB in ${root}" ">= $((images_gb + 10)) GB for the images"
    fi
fi

# 5. Network -------------------------------------------------------------------------------------
port_used=""
if command -v ss >/dev/null 2>&1; then
    port_used="$(ss -Hltn "sport = :$PORT" 2>/dev/null | head -n 1)"
elif [ -r /proc/net/tcp ]; then
    hex="$(printf ':%04X ' "$PORT")"
    port_used="$(awk -v h="$hex" '$4 == "0A" && index($2, h)' /proc/net/tcp /proc/net/tcp6 2>/dev/null | head -n 1)"
fi
if [ -n "$port_used" ] && ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q 'processcraft-proxy'; then
    add FAIL "Port $PORT" "in use by another program" "free" "Stop that program or set HTTPS_PORT in installation.conf."
else
    add PASS "Port $PORT" "free" "free"
fi
clash=""
if command -v ip >/dev/null 2>&1; then
    for net in 10 11 12 13 14 15 16; do
        if ip route 2>/dev/null | grep -v 'br-\|docker' | grep -q "172\.30\.$net\."; then clash="$clash 172.30.$net.0/24"; fi
    done
fi
if [ -n "$clash" ]; then
    add FAIL "Internal networks" "in use:$clash" "172.30.10-16.0/24 free" "Pick other subnets (NETWORK_BASE in installation.conf)."
else
    add PASS "Internal networks" "172.30.10-16.0/24 free" "free"
fi
fqdn="$(hostname -f 2>/dev/null || hostname)"
add PASS "Server name" "$fqdn" "the name people type (HOSTNAME in installation.conf)"

# 6. Clock ---------------------------------------------------------------------------------------
sync=""
command -v timedatectl >/dev/null 2>&1 && sync="$(timedatectl show -p NTPSynchronized --value 2>/dev/null)"
case "$sync" in
    yes) add PASS "Clock" "synchronised (NTP)" "synchronised" ;;
    no) add WARN "Clock" "not synchronised" "synchronised" "Point the server at the plant's time server: every value is stamped by this clock." ;;
    *) add WARN "Clock" "unknown" "synchronised" "Check that the server uses the plant's time server." ;;
esac

# 7. Installation file ---------------------------------------------------------------------------
if [ -f "$CONF" ]; then
    owner="$(stat -c '%u' "$CONF")"
    mode="$(stat -c '%a' "$CONF")"
    if [ "$owner" != 0 ] || [ $((8#$mode & 8#022)) -ne 0 ]; then
        add FAIL "Installation file" "$CONF owner $owner mode $mode" "owned by root, not writable by others" "sudo chown root:root $CONF && sudo chmod 644 $CONF"
    else
        add PASS "Installation file" "$CONF" "owned by root, mode 644 or stricter"
    fi
else
    add WARN "Installation file" "none ($CONF)" "optional" "Without it install.sh uses its options and defaults; the setup wizard writes one."
fi

# Report -----------------------------------------------------------------------------------------
if [ "$JSON" = 1 ]; then
    esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
    printf '{"apps":"%s","fails":%d,"warnings":%d,"checks":[' "$(esc "$APP_IDS")" "$FAILS" "$WARNS"
    first=1
    for r in "${RESULTS[@]}"; do
        IFS='|' read -r s n f w h <<<"$r"
        [ "$first" = 1 ] || printf ','
        first=0
        printf '{"state":"%s","name":"%s","found":"%s","needed":"%s","fix":"%s"}' \
            "$s" "$(esc "$n")" "$(esc "$f")" "$(esc "$w")" "$(esc "$h")"
    done
    printf ']}\n'
else
    printf 'PlantCraft requirements check (apps:%s)\n\n' "${APP_IDS:- none}"
    for r in "${RESULTS[@]}"; do
        IFS='|' read -r s n f w h <<<"$r"
        printf '  %-4s  %-18s %-40s needs %s\n' "$s" "$n" "$f" "$w"
        [ -n "$h" ] && [ "$s" != PASS ] && printf '        %s\n' "$h"
    done
    printf '\n%d failed, %d warnings. %s\n' "$FAILS" "$WARNS" \
        "$([ "$FAILS" = 0 ] && echo 'This server can take the installation.' || echo 'Fix the FAIL lines before installing.')"
fi
[ "$FAILS" = 0 ]
