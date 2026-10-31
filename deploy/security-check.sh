#!/usr/bin/env bash
# PlantCraft security check: an installed suite against its security promises (docs/security-guide.md),
# from the install folder, without changing anything. Also run as `./install.sh --security-check`.
#
#   ./security-check.sh                     every check, a table, the score and the summary
#   ./security-check.sh --format json       one JSON document (checks, summary, score)
#   ./security-check.sh --format junit      JUnit XML (a failed check is a failed test case)
#   ./security-check.sh --format sarif      SARIF 2.1.0 (code-scanning tools)
#   ./security-check.sh --format evidence   the evidence report for an audit (IEC 62443-4-2 CR 7.6
#                                           RE 1, 3-3 SR 7.6): settings, results by requirement,
#                                           exceptions and the hashes of the checks that ran (JSON)
#   ./security-check.sh --url https://plantcraft.plant.local   check the HTTPS answer at this address
#   ./security-check.sh --skip PC-HOST-03,PC-TLS-01   leave checks out of this run
#   ./security-check.sh --exceptions FILE   accepted risks (default security-exceptions.conf here)
#
# An exception is a line "ID YYYY-MM-DD reason": until that day (inclusive) a warning or failure
# of that check reports as "excepted" (half the points, not a failure); from the day after, the
# check reports its own warning or failure again and says the exception expired. The checks' severities, titles and references come
# from security-checks.tsv, which the bundle signs with the rest (PC-INT-01 checks both files).
#
# Each check has a stable id (PC-<area>-NN), a severity, a result (pass, warn, fail, info, na), the
# evidence it saw, how to fix it and its references (IEC 62443-4-2 CR, NIST SP 800-53). The score
# is 0-100, weighted by severity; a warning counts half. Exit code: 0 no failure, 1 a failure,
# 2 the check could not run. It reads docker inspect, the folder's files and the proxy's HTTPS
# answer; nothing leaves the server.
set -Euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$HERE/.env"
CATALOG="$HERE/security-checks.tsv"
EXCEPTIONS="$HERE/security-exceptions.conf"
EXCEPTIONS_GIVEN=0
FORMAT=text
URL=""
SKIP=","
while [ $# -gt 0 ]; do
    case "$1" in
        --json) FORMAT=json ;;
        --format) [ $# -ge 2 ] || { echo "--format needs text, json, junit, sarif or evidence" >&2; exit 2; }; FORMAT="$2"; shift ;;
        --url) [ $# -ge 2 ] || { echo "--url needs an address" >&2; exit 2; }; URL="$2"; shift ;;
        --skip) [ $# -ge 2 ] || { echo "--skip needs check ids" >&2; exit 2; }; SKIP=",$2,"; shift ;;
        --exceptions) [ $# -ge 2 ] || { echo "--exceptions needs a file" >&2; exit 2; }; EXCEPTIONS="$2"; EXCEPTIONS_GIVEN=1; shift ;;
        -h | --help) sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option $1 (--help)" >&2; exit 2 ;;
    esac
    shift
done
case "$FORMAT" in text | json | junit | sarif | evidence) ;; *) echo "unknown format $FORMAT" >&2; exit 2 ;; esac

env_get() { [ -f "$ENV_FILE" ] && sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1; return 0; }
mode_of() { stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1" 2>/dev/null || echo "?"; }
mtime_of() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || echo 0; }
PROJECT="$(env_get COMPOSE_PROJECT_NAME)"
PROJECT="${PROJECT:-processcraft}"
NOW="$(date +%s)"

TODAY="$(date -u +%Y-%m-%d)"

# The catalogue (signed with the bundle): severity, title and references by check id.
declare -A CAT_SEV=() CAT_TITLE=() CAT_REFS=()
if [ -f "$CATALOG" ]; then
    while IFS=$'\t' read -r id sev title refs; do
        case "$id" in '' | '#'*) continue ;; esac
        CAT_SEV[$id]="$sev" CAT_TITLE[$id]="$title" CAT_REFS[$id]="${refs:-}"
    done <"$CATALOG"
fi

# Exceptions: "ID YYYY-MM-DD reason", valid through that day (UTC).
declare -A EXC_UNTIL=() EXC_REASON=() EXC_USED=()
EXC_IDS=()
if [ -f "$EXCEPTIONS" ]; then
    while read -r id until reason; do
        case "$id" in '' | '#'*) continue ;; esac
        if ! [[ "$id" =~ ^PC-[A-Z]+-[0-9][0-9]$ ]] || ! [[ "$until" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || [ -z "$reason" ]; then
            echo "$(basename "$EXCEPTIONS"): line ignored, it is not \"ID YYYY-MM-DD reason\": $id $until $reason" >&2
            continue
        fi
        if [ "${#CAT_SEV[@]}" -gt 0 ] && [ -z "${CAT_SEV[$id]:-}" ]; then
            echo "$(basename "$EXCEPTIONS"): line ignored, $id is not a check of this release" >&2
            continue
        fi
        [ -n "${EXC_UNTIL[$id]:-}" ] || EXC_IDS+=("$id")
        EXC_UNTIL[$id]="$until" EXC_REASON[$id]="$reason"
    done <"$EXCEPTIONS"
elif [ "$EXCEPTIONS_GIVEN" = 1 ]; then
    echo "--exceptions: $EXCEPTIONS is not a file" >&2
    exit 2
fi
exception_state() { # active, expired, or "not needed" (the check passed or did not run)
    if [ -z "${EXC_USED[$1]:-}" ]; then echo "not needed"; elif [[ "$TODAY" > "${EXC_UNTIL[$1]}" ]]; then echo expired; else echo active; fi
}

IDS=() TITLES=() SEVERITIES=() RESULTS=() EVIDENCE=() FIXES=() REFS=()
# check ID SEVERITY RESULT TITLE EVIDENCE REMEDIATION REFS (the catalogue's severity, title and
# references win over the ones given here; an exception in force turns warn or fail into excepted)
check() {
    case "$SKIP" in *",$1,"*) return 0 ;; esac
    local sev="$2" result="$3" title="$4" evidence="$5" refs="$7"
    if [ -n "${CAT_SEV[$1]:-}" ]; then sev="${CAT_SEV[$1]}" title="${CAT_TITLE[$1]}" refs="${CAT_REFS[$1]}"; fi
    if [ -n "${EXC_UNTIL[$1]:-}" ]; then
        case "$result" in
            warn | fail)
                EXC_USED[$1]=1
                if [[ "$TODAY" > "${EXC_UNTIL[$1]}" ]]; then
                    evidence="$evidence (the exception expired on ${EXC_UNTIL[$1]}: ${EXC_REASON[$1]})"
                else
                    evidence="$evidence (excepted until ${EXC_UNTIL[$1]}: ${EXC_REASON[$1]}; it was $result)"
                    result=excepted
                fi
                ;;
        esac
    fi
    IDS+=("$1") SEVERITIES+=("$sev") RESULTS+=("$result") TITLES+=("$title") EVIDENCE+=("$evidence") FIXES+=("$6") REFS+=("$refs")
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
# This check and its catalogue against the release's signed SHA256SUMS (install.sh keeps a copy
# as release-SHA256SUMS and release-SHA256SUMS.sig), the signature checked with this server's
# OpenSSL against trusted-publishers/.
sha256_of() { { sha256sum "$1" 2>/dev/null || shasum -a 256 "$1" 2>/dev/null; } | awk '{print $1}'; }
SCRIPT_SHA="$(sha256_of "$HERE/security-check.sh")"
CATALOG_SHA="$([ -f "$CATALOG" ] && sha256_of "$CATALOG" || true)"
SUMS="$HERE/release-SHA256SUMS" sig="$HERE/release-SHA256SUMS.sig"
# Installed in the bundle's own folder: the bundle's files themselves.
if [ ! -f "$SUMS" ] && [ -f "$HERE/SHA256SUMS" ]; then SUMS="$HERE/SHA256SUMS" sig="$HERE/SHA256SUMS.sig"; fi
if [ ! -f "$SUMS" ]; then
    check PC-INT-01 high warn "The security check and its catalogue are the ones the signed release ships" "no release-SHA256SUMS in the folder (installed before 0.6.0, or run from a source tree)" \
        "Install the signed bundle again (./install.sh --yes): it keeps the signed hashes beside the check." "CR 3.4 / SI-7"
else
    differ=""
    for f in security-check.sh security-checks.tsv; do
        want="$(awk -v f="$f" '$2 == f {print $1}' "$SUMS")"
        if [ ! -f "$HERE/$f" ] || [ -z "$want" ] || [ "$want" != "$(sha256_of "$HERE/$f")" ]; then differ="$differ $f"; fi
    done
    sigstate=""
    if [ -n "$differ" ]; then
        sigstate="fail"
    elif [ ! -f "$sig" ]; then
        sigstate="warn" sigtext="the hashes match release-SHA256SUMS, which is not signed (a development bundle)"
    elif ! command -v openssl >/dev/null 2>&1 || ! openssl pkeyutl -help 2>&1 | grep -q -- '-rawin'; then
        sigstate="warn" sigtext="the hashes match release-SHA256SUMS; its signature needs OpenSSL 1.1.1 or later to check here"
    else
        publisher="$(sed -n 's/^ *"publisher": *"\([a-z0-9-]*\)".*/\1/p' "$sig" | head -n 1)"
        raw="$(sed -n 's/^ *"signature": *"\([A-Za-z0-9+\/=]*\)".*/\1/p' "$sig" | head -n 1)"
        sigbin="$(mktemp)"
        if [ -n "$publisher" ] && [ -f "$HERE/trusted-publishers/$publisher.pub" ] && printf '%s' "$raw" | base64 -d >"$sigbin" 2>/dev/null &&
            openssl pkeyutl -verify -pubin -inkey "$HERE/trusted-publishers/$publisher.pub" -rawin -in "$SUMS" -sigfile "$sigbin" >/dev/null 2>&1; then
            sigstate="pass" sigtext="the hashes match release-SHA256SUMS, signed by $publisher (trusted-publishers/$publisher.pub)"
        else
            sigstate="fail" differ=" release-SHA256SUMS (its signature does not verify against trusted-publishers/${publisher:-?}.pub)"
        fi
        rm -f "$sigbin"
    fi
    check PC-INT-01 high "$sigstate" "The security check and its catalogue are the ones the signed release ships" "$(ev "$differ" "differ from the signed release:" "${sigtext:-}")" \
        "Install the signed bundle again (./install.sh --yes): a changed check or catalogue cannot be trusted." "CR 3.4 / SI-7"
fi
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
    check PC-ACC-01 medium warn "The emergency administrator is kept for emergencies" \
        "data/initial-admin-password exists ($age days old)" \
        "Give people named administrator accounts, sign in as admin only in an emergency, and keep the file on encrypted storage." "CR 1.5 / IA-5"
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
PASS=0 WARN=0 FAIL=0 INFO=0 NA=0 EXCEPTED=0 got=0 total=0
for i in "${!IDS[@]}"; do
    w="$(weight "${SEVERITIES[$i]}")"
    case "${RESULTS[$i]}" in
        pass) PASS=$((PASS + 1)); got=$((got + 2 * w)); total=$((total + 2 * w)) ;;
        warn) WARN=$((WARN + 1)); got=$((got + w)); total=$((total + 2 * w)) ;;
        excepted) EXCEPTED=$((EXCEPTED + 1)); got=$((got + w)); total=$((total + 2 * w)) ;;
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
summary_json() {
    printf '{"pass":%s,"warn":%s,"fail":%s,"excepted":%s,"info":%s,"na":%s}' "$PASS" "$WARN" "$FAIL" "$EXCEPTED" "$INFO" "$NA"
}
checks_json() { # the checks as a JSON list; an excepted or expired one carries its exception
    local i x
    printf '['
    for i in "${!IDS[@]}"; do
        [ "$i" -eq 0 ] || printf ','
        x=""
        if [ -n "${EXC_USED[${IDS[$i]}]:-}" ]; then
            x="$(printf ',"exception":{"until":"%s","reason":"%s","state":"%s"}' "${EXC_UNTIL[${IDS[$i]}]}" "$(esc "${EXC_REASON[${IDS[$i]}]}")" "$(exception_state "${IDS[$i]}")")"
        fi
        printf '{"id":"%s","title":"%s","severity":"%s","result":"%s","evidence":"%s","remediation":"%s","refs":"%s"%s}' \
            "${IDS[$i]}" "$(esc "${TITLES[$i]}")" "${SEVERITIES[$i]}" "${RESULTS[$i]}" "$(esc "${EVIDENCE[$i]}")" "$(esc "${FIXES[$i]}")" "$(esc "${REFS[$i]}")" "$x"
    done
    printf ']'
}

case "$FORMAT" in
    text)
        for i in "${!IDS[@]}"; do
            printf '%-8s %-11s %-8s %s\n         %s\n' "$(printf '%s' "${RESULTS[$i]}" | tr a-z A-Z)" "${IDS[$i]}" "${SEVERITIES[$i]}" "${TITLES[$i]}" "${EVIDENCE[$i]}"
            case "${RESULTS[$i]}" in warn | fail | excepted) [ -z "${FIXES[$i]}" ] || printf '         fix: %s\n' "${FIXES[$i]}" ;; esac
        done
        printf '\nScore %s/100: %s passed, %s warnings, %s failures, %s excepted, %s info, %s not applicable\n' "$SCORE" "$PASS" "$WARN" "$FAIL" "$EXCEPTED" "$INFO" "$NA"
        for id in "${EXC_IDS[@]}"; do
            printf 'Exception %s until %s (%s): %s\n' "$id" "${EXC_UNTIL[$id]}" "$(exception_state "$id")" "${EXC_REASON[$id]}"
        done
        ;;
    json)
        printf '{"tool":"plantcraft-security-check","version":"%s","installation_id":"%s","ran_at":"%s","score":%s,' "$(esc "$VERSION")" "$(esc "$INSTALL_ID")" "$RAN_AT" "$SCORE"
        printf '"summary":%s,"checks":' "$(summary_json)"
        checks_json
        printf '}\n'
        ;;
    evidence)
        # IEC 62443-4-2 CR 7.6 RE 1: the security settings in force, reported machine-readably,
        # with what was checked against what requirement, the accepted risks and the check set.
        printf '{"report":"plantcraft-security-evidence","format":1,'
        printf '"standard":["IEC 62443-4-2 CR 7.6 RE 1 Machine-readable reporting of current security settings","IEC 62443-3-3 SR 7.6 Network and security configuration settings"],'
        printf '"guide":"docs/security-guide.md",'
        printf '"scope":{"host":"%s","install_folder":"%s","compose_project":"%s","version":"%s","installation_id":"%s"},' \
            "$(esc "$(hostname 2>/dev/null || uname -n)")" "$(esc "$HERE")" "$(esc "$PROJECT")" "$(esc "$VERSION")" "$(esc "$INSTALL_ID")"
        printf '"ran_at":"%s","check_set":{"script_sha256":"%s","catalog_sha256":"%s","integrity":"%s"},' \
            "$RAN_AT" "$SCRIPT_SHA" "$CATALOG_SHA" "$(for i in "${!IDS[@]}"; do [ "${IDS[$i]}" = PC-INT-01 ] && esc "${RESULTS[$i]}: ${EVIDENCE[$i]}"; done)"
        printf '"score":%s,"summary":%s,"settings":{' "$SCORE" "$(summary_json)"
        # The .env settings in force, without anything that names a secret.
        first=1
        while IFS= read -r line; do
            key="${line%%=*}"
            [[ "$key" =~ ^[A-Z][A-Z0-9_]*$ ]] || continue
            [[ "$key" =~ (SECRET|PASSWORD|PASSWD|TOKEN|KEY|CREDENTIAL|PRIVATE) ]] && continue
            [ "$first" = 1 ] || printf ','
            first=0
            printf '"%s":"%s"' "$key" "$(esc "${line#*=}")"
        done < <([ -f "$ENV_FILE" ] && grep -v '^ *#' "$ENV_FILE" | grep '=' |
            awk -F= '{ if (!($1 in last)) order[n++] = $1; last[$1] = $0 } END { for (i = 0; i < n; i++) print last[order[i]] }')
        printf '},"exceptions":['
        first=1
        for id in "${EXC_IDS[@]}"; do
            [ "$first" = 1 ] || printf ','
            first=0
            printf '{"id":"%s","until":"%s","reason":"%s","state":"%s"}' "$id" "${EXC_UNTIL[$id]}" "$(esc "${EXC_REASON[$id]}")" "$(exception_state "$id")"
        done
        printf '],"requirements":['
        # Each requirement (CR, SAR or SR of IEC 62443) with the checks that give its evidence.
        declare -A REQ=()
        for i in "${!IDS[@]}"; do
            iec="${REFS[$i]%% / *}"
            case "$iec" in CR\ * | SAR\ *) ;; *) continue ;; esac
            kind="${iec%% *}"
            for n in $(printf '%s' "${iec#* }" | tr ',' ' '); do REQ["$kind $n"]="${REQ["$kind $n"]:-} ${IDS[$i]}:${RESULTS[$i]}"; done
        done
        first=1
        while IFS= read -r req; do
            [ -n "$req" ] || continue
            [ "$first" = 1 ] || printf ','
            first=0
            # The worst result decides: fail, then warn, excepted, pass; na when nothing ran.
            worst=na list=""
            for pair in ${REQ[$req]}; do
                r="${pair#*:}"
                case "$r:$worst" in
                    fail:*) worst=fail ;;
                    warn:fail) ;;
                    warn:*) worst=warn ;;
                    excepted:fail | excepted:warn) ;;
                    excepted:*) worst=excepted ;;
                    pass:na | info:na) worst=pass ;;
                esac
                list="$list${list:+,}\"${pair%%:*}\""
            done
            printf '{"requirement":"%s","result":"%s","checks":[%s]}' "$req" "$worst" "$list"
        done < <(printf '%s\n' "${!REQ[@]}" | sort -V)
        printf '],"checks":'
        checks_json
        printf '}\n'
        ;;
    junit)
        printf '<?xml version="1.0" encoding="UTF-8"?>\n<testsuite name="plantcraft-security-check" tests="%s" failures="%s" skipped="%s" timestamp="%s">\n' \
            "${#IDS[@]}" "$FAIL" "$((NA + INFO))" "$RAN_AT"
        for i in "${!IDS[@]}"; do
            printf '  <testcase classname="%s" name="%s">' "${IDS[$i]%-*}" "$(xml "${IDS[$i]} ${TITLES[$i]}")"
            case "${RESULTS[$i]}" in
                fail) printf '<failure message="%s">%s</failure>' "$(xml "${EVIDENCE[$i]}")" "$(xml "${FIXES[$i]}")" ;;
                warn) printf '<system-out>WARN: %s</system-out>' "$(xml "${EVIDENCE[$i]}")" ;;
                info | na | excepted) printf '<skipped message="%s"/>' "$(xml "${RESULTS[$i]}: ${EVIDENCE[$i]}")" ;;
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
