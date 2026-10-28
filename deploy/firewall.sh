#!/usr/bin/env bash
# Restricts what the PlantCraft containers may reach, with iptables rules in Docker's
# DOCKER-USER chain (docs/install-offline.md, section 8). Prints the rules; --apply installs them.
#
#   sudo ./firewall.sh --allow 10.20.0.15:443 --allow 10.20.0.40:4840 --apply
#
# Effect: new connections from the `plant` network (PlantCraft and HistCraft) go only to the listed
# host:port pairs (the PI Web API and OPC UA servers); new connections from the `edge` network
# (the proxy) are refused. The `apps` network is internal to Docker and has no route out anyway.
# The rules are not persistent: save them with your distribution's tool (iptables-save,
# netfilter-persistent) or run this script at boot after Docker starts.
set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$HERE/.env"
APPLY=0
ALLOW=()

env_get() { [ -f "$ENV_FILE" ] && sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1; return 0; }

while [ $# -gt 0 ]; do
    case "$1" in
        --allow) [ $# -ge 2 ] || { echo "--allow needs HOST:PORT" >&2; exit 1; }; ALLOW+=("$2"); shift ;;
        --apply) APPLY=1 ;;
        -h | --help) sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 1 ;;
    esac
    shift
done

PLANT="$(env_get PLANTCRAFT_PLANT_SUBNET)"
EDGE="$(env_get PLANTCRAFT_EDGE_SUBNET)"
PLANT="${PLANT:-172.30.10.0/24}"
EDGE="${EDGE:-172.30.12.0/24}"
TAG="processcraft"

rules=()
rules+=("-s $PLANT -d $PLANT -j RETURN")
rules+=("-s $PLANT -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN")
for target in "${ALLOW[@]}"; do
    host="${target%:*}"
    port="${target##*:}"
    [[ "$port" =~ ^[0-9]+$ ]] && [ -n "$host" ] && [ "$host" != "$target" ] ||
        { echo "bad --allow value: $target (expected HOST:PORT)" >&2; exit 1; }
    rules+=("-s $PLANT -d $host -p tcp --dport $port -m conntrack --ctstate NEW -j RETURN")
done
rules+=("-s $PLANT -m conntrack --ctstate NEW -j DROP")
rules+=("-s $EDGE -m conntrack --ctstate NEW ! -d $EDGE -j DROP")

if [ "$APPLY" = 0 ]; then
    echo "# Rules for the DOCKER-USER chain (run again with --apply as root to install them):"
    for rule in "${rules[@]}"; do
        echo "iptables -I DOCKER-USER <n> $rule -m comment --comment $TAG"
    done
    [ "${#ALLOW[@]}" -gt 0 ] || echo "# No --allow given: PlantCraft could reach no PI or OPC UA server." >&2
    exit 0
fi

[ "$(id -u)" = 0 ] || { echo "--apply needs root" >&2; exit 1; }
command -v iptables >/dev/null || { echo "iptables is not installed" >&2; exit 1; }
iptables -L DOCKER-USER -n >/dev/null 2>&1 || { echo "the DOCKER-USER chain does not exist: is Docker running?" >&2; exit 1; }

# Remove the rules a previous run installed, then insert the new ones at the top, in order.
while read -r line; do
    # shellcheck disable=SC2086
    iptables -D DOCKER-USER ${line#-A DOCKER-USER }
done < <(iptables -S DOCKER-USER | grep -- "--comment $TAG" || true)
position=1
for rule in "${rules[@]}"; do
    # shellcheck disable=SC2086
    iptables -I DOCKER-USER "$position" $rule -m comment --comment "$TAG"
    position=$((position + 1))
done
echo "Installed ${#rules[@]} rules in DOCKER-USER:"
iptables -S DOCKER-USER | grep -- "--comment $TAG"
