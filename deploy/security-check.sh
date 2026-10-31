#!/usr/bin/env bash
# PlantCraft security check: an installed suite against its security promises (docs/security-guide.md),
# from the install folder, without changing anything. Also run as `./install.sh --security-check`.
#
#   ./security-check.sh                     every check, a table, the score and the summary
#   ./security-check.sh --format json       one JSON document (checks, summary, score)
#   ./security-check.sh --format junit      JUnit XML (a failed check is a failed test case)
#   ./security-check.sh --format sarif      SARIF 2.1.0 (code-scanning tools)
#   ./security-check.sh --url https://plantcraft.plant.local   check the HTTPS answer at this address
#   ./security-check.sh --skip PC-HOST-03,PC-TLS-01   leave checks out (the reason belongs in your notes)
#
# Each check has a stable id (PC-<area>-NN), a severity, a result (pass, warn, fail, info, na), the
# evidence it saw, how to fix it and its references (IEC 62443-4-2 CR, NIST SP 800-53). The score
# is 0-100, weighted by severity; a warning counts half. Exit code: 0 no failure, 1 a failure,
# 2 the check could not run. It reads docker inspect, the folder's files and the proxy's HTTPS
# answer; nothing leaves the server.
set -Euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$HERE/.env"
FORMAT=text
URL=""
SKIP=","
while [ $# -gt 0 ]; do
    case "$1" in
        --json) FORMAT=json ;;
        --format) [ $# -ge 2 ] || { echo "--format needs text, json, junit or sarif" >&2; exit 2; }; FORMAT="$2"; shift ;;
        --url) [ $# -ge 2 ] || { echo "--url needs an address" >&2; exit 2; }; URL="$2"; shift ;;
        --skip) [ $# -ge 2 ] || { echo "--skip needs check ids" >&2; exit 2; }; SKIP=",$2,"; shift ;;
        -h | --help) sed -n '2,17p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option $1 (--help)" >&2; exit 2 ;;
    esac
    shift
done
case "$FORMAT" in text | json | junit | sarif) ;; *) echo "unknown format $FORMAT" >&2; exit 2 ;; esac

env_get() { [ -f "$ENV_FILE" ] && sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1; return 0; }
mode_of() { stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1" 2>/dev/null || echo "?"; }
mtime_of() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || echo 0; }
PROJECT="$(env_get COMPOSE_PROJECT_NAME)"
PROJECT="${PROJECT:-processcraft}"
NOW="$(date +%s)"

IDS=() TITLES=() SEVERITIES=() RESULTS=() EVIDENCE=() FIXES=() REFS=()
# check ID SEVERITY RESULT TITLE EVIDENCE REMEDIATION REFS
check() {
    case "$SKIP" in *",$1,"*) return 0 ;; esac
    IDS+=("$1") SEVERITIES+=("$2") RESULTS+=("$3") TITLES+=("$4") EVIDENCE+=("$5") FIXES+=("$6") REFS+=("$7")
}
# The evidence: PREFIX and the offenders, or DEFAULT when there is none.
ev() { if [ -n "$1" ]; then printf '%s%s' "$2" "$1"; else printf '%s' "$3"; fi; }
# A list of offenders, or nothing: pass, else LEVEL.
verdict() { [ -z "$1" ] && echo pass || echo "$2"; }

command -v docker >/dev/null || { echo "Docker is needed" >&2; exit 2; }
mapfile -t CONTAINERS < <(docker ps --filter "label=com.docker.compose.project=$PROJECT" --format '{{.Names}}' | sort)
[ "${#CONTAINERS[@]}" -gt 0 ] || { echo "no running container of project $PROJECT: run it from the install folder" >&2; exit 2; }
short() { local n="${1#"$PROJECT"-}"; echo "${n%-[0-9]*}"; }

# Listing the last backup's archive takes a second: it runs while the other checks do.
latest="$(ls -1t "$HERE/backups" 2>/dev/null | grep -v '^LATEST$' | head -n 1 || true)"
LISTING="$(mktemp)"
trap 'rm -f "$LISTING"' EXIT
LISTER=""
if [ -n "$latest" ] && [ -f "$HERE/backups/$latest/data.tar.gz" ]; then
    tar -tzf "$HERE/backups/$latest/data.tar.gz" >"$LISTING" 2>/dev/null &
    LISTER=$!
fi

# --- Integrity -------------------------------------------------------------------------------
if docker info --format '{{json .DriverStatus}}' 2>/dev/null | grep -q containerd.snapshotter; then
    # The containerd image store names an image by its manifest, release.json by its config.
    check PC-INT-02 high na "The images in use are the ones the signed release lists" \
        "Docker's containerd image store names images by manifest; release.json lists configs" "" "CR 3.4 / CM-14"
elif [ -f "$HERE/release.json" ]; then
    bad=""
    while read -r ref id; do
        [ -n "$ref" ] || continue
        have="$(docker image inspect "$ref" --format '{{.Id}}' 2>/dev/null || true)"
        [ -z "$have" ] || [ "$have" = "$id" ] || bad="$bad $ref"
    done < <(tr -d ' \n\t' <"$HERE/release.json" | grep -o '"id":"sha256:[0-9a-f]*","ref":"[^"]*"' | sed 's/"id":"\([^"]*\)","ref":"\([^"]*\)"/\2 \1/')
    check PC-INT-02 high "$(verdict "$bad" fail)" "The images in use are the ones the signed release lists" \
        "$(ev "${bad:-}" "differ from release.json:" "every image matches release.json")" \
        "Install the signed bundle again (./install.sh --yes); an image built or pulled by hand is not the release." "CR 3.4 / CM-14"
else
    check PC-INT-02 high na "The images in use are the ones the signed release lists" "no release.json in the folder" "" "CR 3.4 / CM-14"
fi
unsigned="$(grep -l '"allow_unsigned": *true' "$HERE"/data/installer/apps/*/app.json 2>/dev/null | xargs -r -n1 dirname | xargs -r -n1 basename | tr '\n' ' ')"
check PC-INT-03 high "$(verdict "$unsigned" fail)" "Installed apps are signed by a trusted publisher" \
    "$(ev "${unsigned:-}" "installed without a signature: " "no app installed with --allow-unsigned")" \
    "Remove the app or install a signed build from a publisher in trusted-publishers/." "SAR 3.2 / CM-14"

# --- Containers ------------------------------------------------------------------------------
root="" rw="" caps="" nnp="" limits="" priv="" sock="" unhealthy=""
# One docker inspect for every container (a call each took most of the check's time).
FIELDS='{{.Name}}|{{if .Config.User}}{{.Config.User}}{{else}}root{{end}}|{{.HostConfig.ReadonlyRootfs}}|{{.HostConfig.Privileged}}|{{range .HostConfig.SecurityOpt}}{{.}} {{end}}|{{join .HostConfig.CapAdd ","}}|{{join .HostConfig.CapDrop ","}}|{{.HostConfig.PidsLimit}}|{{.HostConfig.Memory}}|{{.HostConfig.NetworkMode}}|{{.HostConfig.PidMode}}|{{with index .State "Health"}}{{index . "Status"}}{{else}}none{{end}}|{{range .Mounts}}{{if eq .Destination "/var/run/docker.sock"}}yes{{end}}{{end}}|{{range $p, $b := .NetworkSettings.Ports}}{{if $b}}{{$p}} {{end}}{{end}}'
mapfile -t INSPECTED < <(docker inspect "${CONTAINERS[@]}" --format "$FIELDS")
published=""
for line in "${INSPECTED[@]}"; do
    IFS='|' read -r c user ro privileged secopt capadd capdrop pids mem netmode pidmode health hassock ports <<<"$line"
    n="$(short "${c#/}")"
    case "$user" in root | 0 | 0:*) root="$root $n" ;; esac
    [ "$ro" = true ] || rw="$rw $n"
    [ "$capdrop" = ALL ] && [ -z "$capadd" ] || caps="$caps $n(${capadd:+add $capadd }drop ${capdrop:-none})"
    case "$secopt" in *no-new-privileges*) ;; *) nnp="$nnp $n" ;; esac
    { [ "${pids:-0}" -gt 0 ] && [ "${mem:-0}" -gt 0 ]; } 2>/dev/null || limits="$limits $n"
    [ "$privileged" = false ] && [ "$netmode" != host ] && [ "$pidmode" != host ] || priv="$priv $n"
    if [ "$hassock" = yes ]; then
        [ "$n" = installer ] && [ "$netmode" = none ] || sock="$sock $n($netmode)"
    fi
    [ "$health" = healthy ] || [ "$health" = none ] || unhealthy="$unhealthy $n($health)"
    [ -z "$ports" ] || [ "$n" = proxy ] || published="$published $n(${ports% })"
done
check PC-CTR-01 high "$(verdict "$root" fail)" "Every container runs as a user other than root" \
    "$(ev "${root:-}" "as root:" "${#CONTAINERS[@]} containers, none as root")" "Use the compose.yaml of the bundle; do not set user: root." "CR 7.7 / CM-7"
check PC-CTR-02 medium "$(verdict "$rw" fail)" "Every container has a read-only file system" \
    "$(ev "${rw:-}" "writable:" "all read-only")" "Keep read_only: true from the bundle's compose.yaml." "CR 7.7 / CM-7"
check PC-CTR-03 high "$(verdict "$caps$nnp" fail)" "Every container drops all capabilities and has no-new-privileges" \
    "$(e="${caps:+capabilities:$caps }${nnp:+no-new-privileges missing:$nnp}"; echo "${e:-ALL dropped, none added, no-new-privileges everywhere}")" \
    "Keep cap_drop: [ALL] and security_opt: [no-new-privileges:true] from the bundle." "CR 7.7 / AC-6"
check PC-CTR-04 medium "$(verdict "$limits" warn)" "Every container has a memory and a process limit" \
    "$(ev "${limits:-}" "no limit:" "all limited")" "Set PLANTCRAFT_MEMORY and keep pids_limit from the bundle." "CR 7.1, 7.2 / SC-5"
check PC-CTR-05 critical "$(verdict "$priv" fail)" "No container is privileged or shares the host's network or processes" \
    "$(ev "${priv:-}" "found:" "none")" "Remove privileged, network_mode: host and pid: host." "CR 5.1 / SC-7"
check PC-CTR-06 critical "$(verdict "$sock" fail)" "Only the installer holds the Docker socket, and it has no network" \
    "$(ev "${sock:-}" "socket in:" "installer only, network none")" "Remove the /var/run/docker.sock mount from every other service." "CR 2.1 / AC-6"
check PC-CTR-07 low "$(verdict "$unhealthy" warn)" "Every container reports healthy" \
    "$(ev "${unhealthy:-}" "not healthy:" "all healthy")" "See ./install.sh --status and the app's log." "CR 7.6 / SI-4"

# --- Network ---------------------------------------------------------------------------------
check PC-NET-01 critical "$(verdict "$published" fail)" "Only the proxy publishes a port on the host" \
    "$(ev "${published:-}" "also published:" "proxy only, on $(b="$(env_get PLANTCRAFT_BIND_ADDRESS)"; echo "${b:-every address}")")" \
    "Remove ports: from every service but the proxy." "CR 5.1 / SC-7"
open_nets=""
mapfile -t NETS < <(docker network ls --filter "label=com.docker.compose.project=$PROJECT" --format '{{.Name}}')
while read -r net internal; do
    s="${net#"$PROJECT"_}"
    case "$s" in edge | plant | egress | default) continue ;; esac
    [ "$internal" = true ] || open_nets="$open_nets $s"
done < <([ "${#NETS[@]}" -eq 0 ] || docker network inspect "${NETS[@]}" --format '{{.Name}} {{.Internal}}')
check PC-NET-02 high "$(verdict "$open_nets" fail)" "The apps' networks have no way out (only edge, plant and egress reach outside)" \
    "$(ev "${open_nets:-}" "not internal:" "every app network is internal")" "Keep internal: true on the bundle's networks." "CR 5.1 / SC-7"
if command -v iptables >/dev/null && iptables -S DOCKER-USER >/dev/null 2>&1; then
    rules="$(iptables -S DOCKER-USER 2>/dev/null | grep -c -- '-j' || true)"
    check PC-NET-03 medium "$([ "$rules" -gt 1 ] && echo pass || echo warn)" "The plant firewall rules are loaded (DOCKER-USER)" \
        "$rules rules in DOCKER-USER" "Run ./firewall.sh (docs/install-offline.md, section 8)." "CR 5.1 / SC-7"
else
    check PC-NET-03 medium na "The plant firewall rules are loaded (DOCKER-USER)" "iptables not readable here (run as root to check)" "" "CR 5.1 / SC-7"
fi

# --- HTTPS -----------------------------------------------------------------------------------
if [ -z "$URL" ]; then
    host="$(env_get PLANTCRAFT_HOSTNAME | awk '{print $1}')"
    port="$(env_get PLANTCRAFT_HTTPS_PORT)"
    URL="https://${host:-localhost}${port:+:$port}"
    [ "${port:-443}" != 443 ] || URL="https://${host:-localhost}"
fi
if command -v curl >/dev/null && headers="$(curl -sk --noproxy '*' --max-time 10 -D - -o /dev/null "$URL/" 2>/dev/null)" && [ -n "$headers" ]; then
    if curl -s --noproxy '*' --max-time 10 -o /dev/null "$URL/" 2>/dev/null; then
        check PC-TLS-01 medium pass "The certificate is trusted (the plant's own, not the local CA)" "trusted by this server" "" "CR 1.8 / SC-17"
    else
        check PC-TLS-01 medium warn "The certificate is trusted (the plant's own, not the local CA)" "not trusted by this server (the local CA?)" \
            "Put the plant's certificate and key in certs/ (docs/install-offline.md, section 6)." "CR 1.8 / SC-17"
    fi
    if command -v openssl >/dev/null; then
        hp="${URL#https://}"; hp="${hp%%/*}"; case "$hp" in *:*) ;; *) hp="$hp:443" ;; esac
        issuer="$(echo | openssl s_client -connect "$hp" -servername "${hp%%:*}" 2>/dev/null | openssl x509 -noout -issuer 2>/dev/null)"
        end="$(echo | openssl s_client -connect "$hp" -servername "${hp%%:*}" 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)"
        if [ -n "$end" ]; then
            left=$((($(date -d "$end" +%s 2>/dev/null || date -j -f '%b %d %T %Y %Z' "$end" +%s) - NOW) / 86400))
            r=pass; [ "$left" -lt 30 ] && r=warn; [ "$left" -lt 7 ] && r=fail
            case "$issuer" in
                *"PlantCraft local CA"*) check PC-TLS-02 high pass "The certificate is valid for more than 30 days" \
                    "local CA certificate, renewed by the proxy on its own (expires $end)" "" "CR 1.8 / SC-17" ;;
                *) check PC-TLS-02 high "$r" "The certificate is valid for more than 30 days" "$left days left ($end)" "Renew the certificate in certs/." "CR 1.8 / SC-17" ;;
            esac
            weak=""
            for v in tls1 tls1_1; do echo | openssl s_client -connect "$hp" "-$v" >/dev/null 2>&1 && weak="$weak $v"; done
            check PC-TLS-04 high "$(verdict "$weak" fail)" "Only TLS 1.2 and 1.3 are accepted" "$(ev "${weak:-}" "accepted:" "TLS 1.0 and 1.1 refused")" \
                "Use the bundle's proxy configuration." "CR 4.1 / SC-8"
        fi
    fi
    missing=""
    for h in strict-transport-security content-security-policy x-frame-options x-content-type-options referrer-policy; do
        printf '%s' "$headers" | grep -qi "^$h:" || missing="$missing $h"
    done
    check PC-TLS-03 high "$(verdict "$missing" fail)" "HTTPS answers carry HSTS and the security headers" \
        "$(ev "${missing:-}" "missing:" "HSTS, CSP, X-Frame-Options, nosniff, Referrer-Policy")" "Use the bundle's proxy configuration." "CR 4.1 / SC-8"
    plain="$(curl -s --noproxy '*' --max-time 5 -o /dev/null -w '%{http_code}' "${URL/https:/http:}/" 2>/dev/null || true)"
    case "$plain" in 30[1278] | 000) r=pass ;; *) r=fail ;; esac
    check PC-TLS-05 high "$r" "Plain HTTP is redirected to HTTPS or closed" "HTTP answered $plain" "Use the bundle's proxy configuration." "CR 4.1 / SC-8"
    code="$(curl -sk --noproxy '*' --max-time 10 -o /dev/null -w '%{http_code}' "$URL/api/users" 2>/dev/null || true)"
    case "$code" in 401 | 403) r=pass ;; *) r=fail ;; esac
    check PC-ACC-04 critical "$r" "The API asks for sign-in" "GET /api/users without sign-in: $code" "Keep sign-in on (the default)." "CR 1.1 / IA-2"
    for spec in /openapi.json /dash/api/openapi.json /hist/api/openapi.json /alarm/api/openapi.json /doc/api/openapi.json /link/api/openapi.json /model/api/openapi.json; do
        body="$(curl -sk --noproxy '*' --max-time 10 "$URL$spec" 2>/dev/null | head -c 200 || true)"
        case "$body" in *'"paths"'*) open_spec="${open_spec:-} $spec" ;; esac
    done
    check PC-MIN-04 low "$(verdict "${open_spec:-}" warn)" "The route lists (openapi.json) are not served" \
        "$(ev "${open_spec:-}" "served:" "none served")" "Leave PLANTCRAFT_OPENAPI unset outside development." "CR 7.7 / CM-7"
else
    for id in PC-TLS-01 PC-TLS-02 PC-TLS-03 PC-TLS-04 PC-TLS-05 PC-ACC-04 PC-MIN-04; do
        check "$id" medium na "HTTPS answer" "no answer from $URL (pass --url)" "" ""
    done
fi

# --- Secrets ---------------------------------------------------------------------------------
loose="" n=0
for f in data/initial-admin-password data/histcraft-db-password data/*-app-key data/compute-local-key data/processcraft/tokens.key data/processcraft/session.secret data/histcraft/secret.key; do
    for path in "$HERE"/$f; do
        [ -e "$path" ] || continue
        n=$((n + 1))
        mode="$(mode_of "$path")"
        case "$mode" in 600 | 400 | 640 | 440) ;; *) loose="$loose ${path#"$HERE"/}($mode)" ;; esac
    done
done
check PC-SEC-01 high "$(verdict "$loose" fail)" "Secret files are readable by their owner only" \
    "$(ev "${loose:-}" "too open:" "$n secret files, mode 600 or 640")" "chmod 600 each file (install.sh sets it on install)." "CR 1.5 / IA-5"
envmode="$(mode_of "$ENV_FILE")"
secret_lines="$(grep -E '^[A-Z_]*(PASSWORD|SECRET|TOKEN|KEY)=.+' "$ENV_FILE" 2>/dev/null | grep -v -E '_(FILE|STATS_KEY)=' | cut -d= -f1 | tr '\n' ' ' || true)"
r=pass; case "$envmode" in 600 | 640 | 400 | 440) ;; *) r=warn ;; esac; [ -z "$secret_lines" ] || r=warn
check PC-SEC-02 medium "$r" ".env holds no secret and only its owner and group read it" \
    "mode $envmode${secret_lines:+; secrets in .env: $secret_lines}" "Keep secrets in data/ files (install.sh does); chmod 640 .env." "IA-5"
if [ -n "$LISTER" ]; then
    wait "$LISTER" 2>/dev/null || true
    keys="$(grep -c -E 'processcraft/(tokens\.key|session\.secret)$' "$LISTING" || true)"
    check PC-SEC-03 high "$([ "${keys:-0}" -ge 2 ] && echo pass || echo fail)" "The last backup holds the signing key and the session secret" \
        "backup $latest: ${keys:-0} of 2" "Run ./install.sh --backup; a restore without them signs everyone out and ends every app token." "CR 7.3 / CP-9"
else
    check PC-SEC-03 high na "The last backup holds the signing key and the session secret" "no backup yet" "" "CR 7.3 / CP-9"
fi

# --- Accounts --------------------------------------------------------------------------------
if [ -e "$HERE/data/initial-admin-password" ]; then
    age=$(((NOW - $(mtime_of "$HERE/data/initial-admin-password")) / 86400))
    # Its password is rotated at least every 90 days (./install.sh --rotate-admin-password).
    if [ "$age" -gt 90 ]; then r=fail; else r=warn; fi
    check PC-ACC-01 medium "$r" "The emergency administrator is kept for emergencies" \
        "data/initial-admin-password exists, its password set $age days ago" \
        "Give people named administrator accounts and sign in as admin only in an emergency; change its password at least every 90 days with ./install.sh --rotate-admin-password." "CR 1.5 / IA-5"
else
    check PC-ACC-01 medium pass "The emergency administrator is kept for emergencies" "no password file in data/" "" "CR 1.5 / IA-5"
fi
[ "$(env_get PLANTCRAFT_SESSION_HTTPS_ONLY)" != false ] && r=pass || r=fail
check PC-ACC-02 high "$r" "Session cookies travel over HTTPS only" "PLANTCRAFT_SESSION_HTTPS_ONLY=$(v="$(env_get PLANTCRAFT_SESSION_HTTPS_ONLY)"; echo "${v:-true (default)}")" \
    "Remove PLANTCRAFT_SESSION_HTTPS_ONLY=false from .env." "CR 4.1 / SC-23"

# --- Records and recovery --------------------------------------------------------------------
free="$(df -P "$HERE/data" 2>/dev/null | awk 'NR==2 {gsub("%","",$5); print 100-$5}')"
r=pass; [ "${free:-100}" -lt 15 ] && r=warn; [ "${free:-100}" -lt 5 ] && r=fail
check PC-AUD-02 medium "$r" "The data disk has room for the audit log and the series (more than 15% free)" "${free:-?}% free" \
    "Free space or grow the disk; see Settings > Storage." "CR 2.9 / AU-4"
if command -v timedatectl >/dev/null && timedatectl show >/dev/null 2>&1; then
    synced="$(timedatectl show -p NTPSynchronized --value 2>/dev/null)"
    check PC-AUD-03 medium "$([ "$synced" = yes ] && echo pass || echo warn)" "The host clock is synchronised (NTP)" "NTPSynchronized=$synced" \
        "Turn on time synchronisation (timedatectl set-ntp true)." "CR 2.11 / AU-8"
else
    check PC-AUD-03 medium na "The host clock is synchronised (NTP)" "timedatectl not available" "" "CR 2.11 / AU-8"
fi
if [ -n "$latest" ]; then
    days=$(((NOW - $(mtime_of "$HERE/backups/$latest")) / 86400))
    state="$(sed -n 's/.*"state": *"\([a-z]*\)".*/\1/p' "$HERE/backups/$latest/status.json" 2>/dev/null | head -n 1)"
    r=pass; [ "$days" -ge 1 ] && r=warn; [ "$days" -gt 7 ] && r=fail; [ "${state:-ok}" = ok ] || r=fail
    check PC-REC-01 high "$r" "The last backup is less than a day old and verified" "$latest, $days days, ${state:-not verified}" \
        "Keep the daily backup on (Settings > Backups) or run ./install.sh --backup." "CR 7.3 / CP-9"
else
    check PC-REC-01 high fail "The last backup is less than a day old and verified" "no backup in backups/" \
        "Run ./install.sh --backup and keep the daily backup on." "CR 7.3 / CP-9"
fi
drill="$(grep -h '"action": *"drill"' "$HERE/.ops/history.jsonl" 2>/dev/null | tail -n 1 | sed -n 's/.*"at": *"\([^"]*\)".*/\1/p')"
if [ -n "$drill" ]; then
    ddays=$(((NOW - $(date -d "$drill" +%s 2>/dev/null || echo 0)) / 86400))
    check PC-REC-02 medium "$([ "$ddays" -le 90 ] && echo pass || echo warn)" "A restore was rehearsed in the last 90 days" "last drill $drill" \
        "Run ./install.sh --drill." "CR 7.4 / CP-4"
else
    check PC-REC-02 medium warn "A restore was rehearsed in the last 90 days" "no drill recorded" "Run ./install.sh --drill." "CR 7.4 / CP-4"
fi
exported="$(ls -1 "$HERE"/backups/*.enc "$HERE"/*.tar.gz.enc 2>/dev/null | head -n 1 || true)"
check PC-REC-03 low "$([ -n "$exported" ] && echo pass || echo info)" "Backups taken off the server are encrypted" \
    "$(ev "${exported#"$HERE"/}" "encrypted export found: " "no encrypted export here")" \
    "Copy backups off the server with ./install.sh --export-backup NAME --passphrase-file F (AES-256)." "CR 4.1 / SC-28"

# --- Least functionality ---------------------------------------------------------------------
on=""
[ "$(env_get PLANTCRAFT_LLM)" = off ] || on="$on language-model"
[ "$(env_get PLANTCRAFT_APP_INSTALL)" = true ] && on="$on app-install"
[ -n "$(env_get PLANTCRAFT_APP_CATALOG_URL)" ] && on="$on online-catalog"
check PC-MIN-01 info info "Optional functions that are switched on" "$(ev "$on" "on:" "none")" "Switch off what the plant does not use in .env." "CR 7.7 / CM-7"
r=pass; [ "$(env_get PLANTCRAFT_PUBLIC_DEMO)" = true ] && r=warn
check PC-MIN-02 high "$r" "The public demo is off" "PLANTCRAFT_PUBLIC_DEMO=$(env_get PLANTCRAFT_PUBLIC_DEMO)" \
    "Never turn the public demo on in a plant with real sources." "CR 7.7 / CM-7"
r=pass; [ -n "$(env_get PLANTCRAFT_APP_CATALOG_URL)" ] && [ -n "$(env_get PLANTCRAFT_DNS)" ] && r=warn
check PC-MIN-03 low "$r" "No online catalog on an isolated install" "PLANTCRAFT_APP_CATALOG_URL=$(env_get PLANTCRAFT_APP_CATALOG_URL)" \
    "Leave the catalog empty on a server without internet." "CR 5.1 / CM-7"

# --- Host ------------------------------------------------------------------------------------
dv="$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo 0)"
major="${dv%%.*}"
check PC-HOST-01 medium "$([ "${major:-0}" -ge 24 ] 2>/dev/null && echo pass || echo warn)" "Docker Engine is a supported version (24 or later)" \
    "Docker $dv" "Update Docker Engine." "SI-2"
tcp="$(ps -eo args 2>/dev/null | grep -E '[d]ockerd.*-H *tcp://' | grep -v tlsverify || true)"
lr="$(docker info --format '{{.LiveRestoreEnabled}}' 2>/dev/null || echo false)"
r=pass; [ "$lr" = true ] || r=warn; [ -z "$tcp" ] || r=fail
check PC-HOST-02 high "$r" "The Docker daemon has no open TCP socket and keeps containers up on restart" \
    "live-restore=$lr${tcp:+; TCP socket without TLS}" 'Set "live-restore": true in /etc/docker/daemon.json; never expose the daemon on TCP without TLS.' "CIS Docker 2.x"
hostfw=""
if command -v ufw >/dev/null; then ufw status 2>/dev/null | grep -q 'Status: active' && hostfw="ufw active"; fi
if [ -z "$hostfw" ] && command -v firewall-cmd >/dev/null; then firewall-cmd --state 2>/dev/null | grep -q running && hostfw="firewalld running"; fi
check PC-HOST-03 medium "$([ -n "$hostfw" ] && echo pass || echo info)" "The host firewall is on" "${hostfw:-no ufw or firewalld active}" \
    "Turn on the host firewall, and run a host benchmark (Lynis or OpenSCAP) for the rest of the operating system." "CM-6"
crypt="$(lsblk -o TYPE 2>/dev/null | grep -c crypt || true)"
check PC-HOST-04 info info "The data disk is encrypted" "${crypt:-0} encrypted volumes (lsblk)" "Use full-disk encryption (LUKS, BitLocker) on the server." "CR 4.1 / SC-28"

# --- Report ----------------------------------------------------------------------------------
weight() { case "$1" in critical) echo 10 ;; high) echo 5 ;; medium) echo 3 ;; low) echo 1 ;; *) echo 0 ;; esac; }
PASS=0 WARN=0 FAIL=0 INFO=0 NA=0 got=0 total=0
for i in "${!IDS[@]}"; do
    w="$(weight "${SEVERITIES[$i]}")"
    case "${RESULTS[$i]}" in
        pass) PASS=$((PASS + 1)); got=$((got + 2 * w)); total=$((total + 2 * w)) ;;
        warn) WARN=$((WARN + 1)); got=$((got + w)); total=$((total + 2 * w)) ;;
        fail) FAIL=$((FAIL + 1)); total=$((total + 2 * w)) ;;
        info) INFO=$((INFO + 1)) ;;
        *) NA=$((NA + 1)) ;;
    esac
done
SCORE=$([ "$total" -gt 0 ] && echo $((100 * got / total)) || echo 100)
esc() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr '\n\t' '  '; }
xml() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' -e 's/"/\&quot;/g'; }
VERSION="$(env_get PLANTCRAFT_VERSION)"
INSTALL_ID="$(env_get PLANTCRAFT_INSTALLATION_ID)"
RAN_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

case "$FORMAT" in
    text)
        for i in "${!IDS[@]}"; do
            printf '%-5s %-11s %-8s %s\n      %s\n' "$(printf '%s' "${RESULTS[$i]}" | tr a-z A-Z)" "${IDS[$i]}" "${SEVERITIES[$i]}" "${TITLES[$i]}" "${EVIDENCE[$i]}"
            case "${RESULTS[$i]}" in warn | fail) [ -z "${FIXES[$i]}" ] || printf '      fix: %s\n' "${FIXES[$i]}" ;; esac
        done
        printf '\nScore %s/100: %s passed, %s warnings, %s failures, %s info, %s not applicable\n' "$SCORE" "$PASS" "$WARN" "$FAIL" "$INFO" "$NA"
        ;;
    json)
        printf '{"tool":"plantcraft-security-check","version":"%s","installation_id":"%s","ran_at":"%s","score":%s,' "$(esc "$VERSION")" "$(esc "$INSTALL_ID")" "$RAN_AT" "$SCORE"
        printf '"summary":{"pass":%s,"warn":%s,"fail":%s,"info":%s,"na":%s},"checks":[' "$PASS" "$WARN" "$FAIL" "$INFO" "$NA"
        for i in "${!IDS[@]}"; do
            [ "$i" -eq 0 ] || printf ','
            printf '{"id":"%s","title":"%s","severity":"%s","result":"%s","evidence":"%s","remediation":"%s","refs":"%s"}' \
                "${IDS[$i]}" "$(esc "${TITLES[$i]}")" "${SEVERITIES[$i]}" "${RESULTS[$i]}" "$(esc "${EVIDENCE[$i]}")" "$(esc "${FIXES[$i]}")" "$(esc "${REFS[$i]}")"
        done
        printf ']}\n'
        ;;
    junit)
        printf '<?xml version="1.0" encoding="UTF-8"?>\n<testsuite name="plantcraft-security-check" tests="%s" failures="%s" skipped="%s" timestamp="%s">\n' \
            "${#IDS[@]}" "$FAIL" "$((NA + INFO))" "$RAN_AT"
        for i in "${!IDS[@]}"; do
            printf '  <testcase classname="%s" name="%s">' "${IDS[$i]%-*}" "$(xml "${IDS[$i]} ${TITLES[$i]}")"
            case "${RESULTS[$i]}" in
                fail) printf '<failure message="%s">%s</failure>' "$(xml "${EVIDENCE[$i]}")" "$(xml "${FIXES[$i]}")" ;;
                warn) printf '<system-out>WARN: %s</system-out>' "$(xml "${EVIDENCE[$i]}")" ;;
                info | na) printf '<skipped message="%s"/>' "$(xml "${RESULTS[$i]}: ${EVIDENCE[$i]}")" ;;
            esac
            printf '</testcase>\n'
        done
        printf '</testsuite>\n'
        ;;
    sarif)
        printf '{"version":"2.1.0","$schema":"https://json.schemastore.org/sarif-2.1.0.json","runs":[{"tool":{"driver":{"name":"plantcraft-security-check","version":"%s","rules":[' "$(esc "$VERSION")"
        for i in "${!IDS[@]}"; do
            [ "$i" -eq 0 ] || printf ','
            printf '{"id":"%s","shortDescription":{"text":"%s"},"help":{"text":"%s"},"properties":{"severity":"%s","refs":"%s"}}' \
                "${IDS[$i]}" "$(esc "${TITLES[$i]}")" "$(esc "${FIXES[$i]}")" "${SEVERITIES[$i]}" "$(esc "${REFS[$i]}")"
        done
        printf ']}},"results":['
        first=1
        for i in "${!IDS[@]}"; do
            case "${RESULTS[$i]}" in fail) level=error ;; warn) level=warning ;; *) continue ;; esac
            [ "$first" = 1 ] || printf ','
            first=0
            printf '{"ruleId":"%s","level":"%s","message":{"text":"%s"},"locations":[{"physicalLocation":{"artifactLocation":{"uri":"compose.yaml"}}}]}' \
                "${IDS[$i]}" "$level" "$(esc "${EVIDENCE[$i]}")"
        done
        printf ']}]}\n'
        ;;
esac
[ "$FAIL" -gt 0 ] && exit 1
exit 0
