#!/usr/bin/env bash
# Checks an installed PlantCraft against the suite's security promises (docs/security-guide.md),
# from the install folder, without changing anything:
#
#   ./security-check.sh                 every check, a table and a summary
#   ./security-check.sh --json          the same as JSON lines (for the client's own tools)
#   ./security-check.sh --url https://plantcraft.plant.local   check the HTTPS answer at this address
#
# Exit code: 0 all passed, 1 a warning, 2 a failure. It reads docker inspect, the folder's files and
# one HTTPS answer of the proxy. Nothing leaves the server; it needs no network beyond the proxy.
set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$HERE/.env"
JSON=0
URL=""
while [ $# -gt 0 ]; do
    case "$1" in
        --json) JSON=1 ;;
        --url) [ $# -ge 2 ] || { echo "--url needs an address" >&2; exit 2; }; URL="$2"; shift ;;
        -h | --help) sed -n '2,11p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option $1 (--help)" >&2; exit 2 ;;
    esac
    shift
done

env_get() { [ -f "$ENV_FILE" ] && sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1; return 0; }
PROJECT="$(env_get COMPOSE_PROJECT_NAME)"
PROJECT="${PROJECT:-processcraft}"
PASS=0 WARN=0 FAIL=0

report() { # report pass|warn|fail AREA TEXT
    case "$1" in pass) PASS=$((PASS + 1)) ;; warn) WARN=$((WARN + 1)) ;; fail) FAIL=$((FAIL + 1)) ;; esac
    if [ "$JSON" = 1 ]; then
        printf '{"result":"%s","area":"%s","check":"%s"}\n' "$1" "$2" "$(printf '%s' "$3" | sed 's/"/\\"/g')"
    else
        printf '%-5s %-11s %s\n' "$(printf '%s' "$1" | tr a-z A-Z)" "$2" "$3"
    fi
}

command -v docker >/dev/null || { echo "Docker is needed" >&2; exit 2; }
mapfile -t CONTAINERS < <(docker ps --filter "label=com.docker.compose.project=$PROJECT" --format '{{.Names}}' | sort)
[ "${#CONTAINERS[@]}" -gt 0 ] || { echo "no running container of project $PROJECT: run it from the install folder" >&2; exit 2; }

# 1. Containers: user, file system, privileges, Docker socket, published ports.
for c in "${CONTAINERS[@]}"; do
    read -r user ro priv nnp caps pids < <(docker inspect "$c" --format \
        '{{if .Config.User}}{{.Config.User}}{{else}}root{{end}} {{.HostConfig.ReadonlyRootfs}} {{.HostConfig.Privileged}} {{range .HostConfig.SecurityOpt}}{{.}}{{end}}x {{if .HostConfig.CapAdd}}{{join .HostConfig.CapAdd ","}}{{else}}-{{end}}/{{join .HostConfig.CapDrop ","}} {{.HostConfig.PidsLimit}}')
    name="${c#"$PROJECT"-}"
    case "$user" in root | 0 | 0:*) report fail container "$name runs as root" ;; *) report pass container "$name runs as user $user" ;; esac
    [ "$ro" = true ] && report pass container "$name has a read-only file system" || report fail container "$name can write its own file system"
    [ "$priv" = false ] || report fail container "$name is privileged"
    case "$nnp" in *no-new-privileges*) ;; *) report warn container "$name lacks no-new-privileges" ;; esac
    case "$caps" in -/ALL) ;; *) report warn container "$name capabilities: $caps (expected none added, ALL dropped)" ;; esac
    [ "${pids:-0}" -gt 0 ] 2>/dev/null || report warn container "$name has no process limit (fork bomb)"
    sock="$(docker inspect "$c" --format '{{range .Mounts}}{{if eq .Destination "/var/run/docker.sock"}}yes{{end}}{{end}}')"
    if [ "$sock" = yes ]; then
        case "$name" in installer-*) report pass container "$name holds the Docker socket (the installer only, no network)" ;;
            *) report fail container "$name holds the Docker socket" ;; esac
    fi
    ports="$(docker inspect "$c" --format '{{range $p, $b := .NetworkSettings.Ports}}{{if $b}}{{$p}} {{end}}{{end}}')"
    if [ -n "$ports" ]; then
        case "$name" in proxy-*) report pass network "only the proxy publishes ports: $ports" ;;
            *) report fail network "$name publishes $ports on the host" ;; esac
    fi
done

# 2. Networks: only the edge (proxy), plant (data sources) and egress (language model) leave Docker.
while read -r net internal; do
    short="${net#"$PROJECT"_}"
    case "$short" in
        edge | plant | egress) report pass network "$short reaches outside Docker (by design)" ;;
        *) [ "$internal" = true ] && report pass network "$short is internal" || report fail network "$short is not internal" ;;
    esac
done < <(docker network ls --filter "label=com.docker.compose.project=$PROJECT" --format '{{.Name}}' |
    while read -r n; do printf '%s %s\n' "$n" "$(docker network inspect "$n" --format '{{.Internal}}')"; done)

# 3. Settings.
[ "$(env_get PLANTCRAFT_PUBLIC_DEMO)" = true ] && report warn settings "the public demo is on (a visitor account anyone may enter)" ||
    report pass settings "the public demo is off"
case "$(env_get PLANTCRAFT_LLM)" in
    off) report pass settings "language models are off (PLANTCRAFT_LLM=off)" ;;
    *) report warn settings "language models may be switched on by an administrator; only the hosts they add are reachable (llm-egress)" ;;
esac
[ "$(env_get PLANTCRAFT_SESSION_HTTPS_ONLY)" != false ] && report pass settings "session cookies travel over HTTPS only" ||
    report fail settings "PLANTCRAFT_SESSION_HTTPS_ONLY=false"

# 4. Files: secrets readable only by their owner, backups kept.
mode_of() { stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"; }
for f in .env data/initial-admin-password data/histcraft-db-password data/*-app-key data/processcraft/tokens.key data/processcraft/session.secret; do
    for path in "$HERE"/$f; do
        [ -e "$path" ] || continue
        mode="$(mode_of "$path" 2>/dev/null || echo "?")"
        case "$mode" in 600 | 640 | 400 | 440) report pass files "${path#"$HERE"/} is mode $mode" ;;
            '?') report warn files "${path#"$HERE"/}: cannot read its mode (run as the install folder's owner)" ;;
            *) report fail files "${path#"$HERE"/} is mode $mode (others may read it)" ;; esac
    done
done
if [ -e "$HERE/data/initial-admin-password" ]; then
    report warn files "the administrator password is kept in clear in data/initial-admin-password: keep it as the emergency account and store backups encrypted"
fi
latest="$(ls -1t "$HERE/backups" 2>/dev/null | head -n 1 || true)"
if [ -z "$latest" ]; then
    report warn backup "no backup yet (./install.sh --backup, or Settings > Backups)"
else
    age_days=$((($(date +%s) - $(stat -c %Y "$HERE/backups/$latest" 2>/dev/null || echo 0)) / 86400))
    [ "$age_days" -le 7 ] && report pass backup "latest backup $latest ($age_days days old)" ||
        report warn backup "latest backup is $age_days days old"
    report warn backup "backups hold the app keys and passwords unencrypted: keep them on encrypted storage"
fi

# 5. The proxy's answer: HTTPS, headers, sign-in.
if [ -z "$URL" ]; then
    host="$(env_get PLANTCRAFT_HOSTNAME | awk '{print $1}')"
    URL="https://${host:-localhost}"
fi
if command -v curl >/dev/null; then
    headers="$(curl -sk --noproxy '*' --max-time 10 -D - -o /dev/null "$URL/" || true)"
    if [ -z "$headers" ]; then
        report warn https "no answer from $URL (pass --url)"
    else
        for h in strict-transport-security content-security-policy x-frame-options x-content-type-options referrer-policy; do
            printf '%s' "$headers" | grep -qi "^$h:" && report pass https "$h is set" || report fail https "$h is missing"
        done
        code="$(curl -sk --noproxy '*' --max-time 10 -o /dev/null -w '%{http_code}' "$URL/api/users" || true)"
        [ "$code" = 401 ] || [ "$code" = 403 ] && report pass https "the API asks for sign-in ($code)" ||
            report fail https "the API answered $code without sign-in"
        plain="$(curl -s --noproxy '*' --max-time 5 -o /dev/null -w '%{http_code}' "${URL/https:/http:}/" || true)"
        case "$plain" in 30[1278] | 000) report pass https "plain HTTP is redirected or closed ($plain)" ;;
            *) report fail https "plain HTTP answers $plain" ;; esac
        if curl -s --noproxy '*' --max-time 10 -o /dev/null "$URL/" 2>/dev/null; then
            report pass https "the certificate is trusted by this server"
        else
            report warn https "the certificate is not trusted here (self-signed?): install the plant's certificate in certs/"
        fi
    fi
fi

if [ "$JSON" = 0 ]; then
    printf '\n%s passed, %s warnings, %s failures\n' "$PASS" "$WARN" "$FAIL"
fi
[ "$FAIL" -gt 0 ] && exit 2
[ "$WARN" -gt 0 ] && exit 1
exit 0
