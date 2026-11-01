#!/usr/bin/env bash
# PlantCraft's public site, its chat and the public demo on one cloud VM (docs/public-demo.md,
# "On a cloud VM"). Run as root on the VM, from the copy of the repository that
# deploy/cloud/push-to-vm.sh leaves at /opt/plantcraft-src:
#
#   vm.sh setup       Docker, cloudflared, Python, time zone, swap, security updates (once)
#   vm.sh tunnel      asks for the Cloudflare Tunnel's token and runs cloudflared as a service
#   vm.sh tunnel-login  the same without the dashboard: one sign-in link, then the tunnel, its DNS
#                     names (SITE_HOST, DEMO_HOST) and routes are made here
#   vm.sh chat-key    asks for the chat's language model key (never on the command line)
#   vm.sh site        builds the site and (re)starts its server at 127.0.0.1:8090, and the watch
#   vm.sh watch       (re)starts the watch only: the host's health on /stats, alerts by push
#   vm.sh alerts      prints the alerts' ntfy topic (subscribe in the ntfy app) and sends a test
#   vm.sh demo        builds the bundle here and installs or updates the suite with --public-demo,
#                     published on 127.0.0.1:443 only, behind the tunnel
#   vm.sh all         setup, site and demo
#   vm.sh status      what runs, and a request to each part
#   vm.sh stats-password  prints the password of https://SITE_HOST/stats, the private stats page
#                     (site visits, demo visits, chat questions, contacts), made by vm.sh site
#
# Settings (environment, or /etc/plantcraft-site/vm.env): SITE_HOST (plantcraft.io), DEMO_HOST
# (demo.plantcraft.io), CONTACT (the team's e-mail, for the privacy page and security.txt),
# LAUNCHED (1 lets search engines in; until then the site says noindex), TIMEZONE
# (America/Sao_Paulo), DEMO_ISOLATED (true: each visit plays in its own copy of the apps' data;
# false turns it off), UPDATE_NOTICE_MINUTES (2: how long visits are warned before vm.sh demo
# updates the suite; 0 updates at once). Nothing here opens a port: the tunnel is the only way in.
#
# This VM holds simulated data only. A plant's installation never connects to it.
set -Eeuo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONF=/etc/plantcraft-site
[ -f "$CONF/vm.env" ] && . "$CONF/vm.env"
SITE_HOST="${SITE_HOST:-plantcraft.io}"
DEMO_HOST="${DEMO_HOST:-demo.plantcraft.io}"
CONTACT="${CONTACT:-}"
LAUNCHED="${LAUNCHED:-0}"
TIMEZONE="${TIMEZONE:-America/Sao_Paulo}"
SITE_HOME=/opt/plantcraft-site
SITE_DATA=/var/lib/plantcraft-site
SUITE=/opt/processcraft

log() { printf '[vm] %s\n' "$*"; }
die() {
    printf '[vm] ERROR: %s\n' "$*" >&2
    exit 1
}
[ "$(id -u)" = 0 ] || die "run as root (sudo)"

setup() {
    export DEBIAN_FRONTEND=noninteractive
    . /etc/os-release
    [ "$ID" = ubuntu ] || die "made for Ubuntu (22.04 or 24.04), found $ID"
    log "packages"
    apt-get update -q
    apt-get install -y -q ca-certificates curl gnupg make python3 python3-venv python-is-python3 nsis \
        unattended-upgrades >/dev/null
    install -m 0755 -d /etc/apt/keyrings
    if ! command -v docker >/dev/null; then
        log "Docker Engine and Compose (download.docker.com)"
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc]" \
            "https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" \
            >/etc/apt/sources.list.d/docker.list
        apt-get update -q
        apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin \
            docker-compose-plugin >/dev/null
    fi
    if ! command -v cloudflared >/dev/null; then
        log "cloudflared (pkg.cloudflare.com)"
        curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
            -o /usr/share/keyrings/cloudflare-main.gpg
        echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg]" \
            "https://pkg.cloudflare.com/cloudflared any main" >/etc/apt/sources.list.d/cloudflared.list
        apt-get update -q
        apt-get install -y -q cloudflared >/dev/null
    fi
    timedatectl set-timezone "$TIMEZONE"
    if ! swapon --show | grep -q .; then
        log "4 GB of swap"
        fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap -q /swapfile && swapon /swapfile
        grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab
    fi
    install -d -m 0750 "$CONF"
    log "ready: next vm.sh tunnel, then vm.sh site and vm.sh demo"
}

tunnel() {
    local token
    command -v cloudflared >/dev/null || die "run vm.sh setup first"
    read -rsp "Cloudflare Tunnel token (Zero Trust › Networks › Tunnels › your tunnel): " token
    echo
    [ -n "$token" ] || die "no token"
    cloudflared service uninstall >/dev/null 2>&1 || true
    cloudflared service install "$token"
    log "cloudflared runs as a service (systemctl status cloudflared)"
}

tunnel_login() {
    # The same tunnel without the dashboard: one sign-in link, then the tunnel, its two DNS
    # names and its routes are made here. The sign-in certificate (which may change the zone's
    # DNS) is removed at the end; the tunnel keeps only its own credentials.
    local id dir=/etc/cloudflared
    command -v cloudflared >/dev/null || die "run vm.sh setup first"
    log "open the link below, sign in to Cloudflare and choose the domain of $SITE_HOST"
    rm -f /root/.cloudflared/cert.pem
    cloudflared tunnel login
    cloudflared tunnel info plantcraft >/dev/null 2>&1 || cloudflared tunnel create plantcraft
    id="$(cloudflared tunnel list --name plantcraft --output json |
        python3 -c 'import json, sys; print(json.load(sys.stdin)[0]["id"])')"
    install -d -m 0755 "$dir"
    install -m 0600 "/root/.cloudflared/$id.json" "$dir/$id.json"
    cat >"$dir/config.yml" <<EOF
# PlantCraft's site and public demo (deploy/cloud/vm.sh tunnel-login).
tunnel: $id
credentials-file: $dir/$id.json
ingress:
  - hostname: $SITE_HOST
    service: http://127.0.0.1:8090
  - hostname: $DEMO_HOST
    service: https://127.0.0.1:443
    originRequest:
      noTLSVerify: true
      originServerName: $DEMO_HOST
  - service: http_status:404
EOF
    cloudflared tunnel route dns --overwrite-dns plantcraft "$SITE_HOST"
    cloudflared tunnel route dns --overwrite-dns plantcraft "$DEMO_HOST"
    rm -f /root/.cloudflared/cert.pem
    cloudflared service uninstall >/dev/null 2>&1 || true
    cloudflared service install
    systemctl restart cloudflared
    log "tunnel plantcraft ($id): https://$SITE_HOST and https://$DEMO_HOST"
}

chat_key() {
    local key
    read -rsp "The chat's OpenAI key (not shown, never logged): " key
    echo
    [ -n "$key" ] || die "no key"
    install -d -m 0750 -g plantcraft-site "$CONF" 2>/dev/null || install -d -m 0750 "$CONF"
    umask 077
    printf '%s\n' "$key" >"$CONF/chat-key"
    chown root:plantcraft-site "$CONF/chat-key" 2>/dev/null || true
    chmod 0640 "$CONF/chat-key"
    sed -i 's/^SITE_CHAT_PROVIDER=.*/SITE_CHAT_PROVIDER=openai/' "$CONF/site.env" 2>/dev/null || true
    systemctl restart plantcraft-site 2>/dev/null || true
    log "chat key saved in $CONF/chat-key; the chat answers once vm.sh site has run"
}

stats_secrets() { # the stats page's password and the key it reads the demo's numbers with
    install -d -m 0750 "$CONF"
    getent group plantcraft-site >/dev/null && chgrp plantcraft-site "$CONF"
    local name
    for name in stats-password demo-stats-key; do
        if [ ! -s "$CONF/$name" ]; then
            (umask 077 && head -c 24 /dev/urandom | base64 | tr -d '/+=' >"$CONF/$name")
        fi
        chmod 0640 "$CONF/$name"
        getent group plantcraft-site >/dev/null && chgrp plantcraft-site "$CONF/$name"
    done
    return 0
}

watch() { # the host's health for /stats and the alerts (site/sitechat/health.py)
    [ -x "$SITE_HOME/venv/bin/python" ] || die "run vm.sh site first"
    if [ ! -f "$CONF/watch.env" ]; then
        local topic
        topic="plantcraft-$(head -c 32 /dev/urandom | base64 | tr -dc 'a-z0-9' | head -c 18)"
        (umask 077 && cat >"$CONF/watch.env" <<EOF
# The watch (vm.sh watch). Edit, then: systemctl restart plantcraft-watch
SITE_DATA_DIR=$SITE_DATA
WATCH_SITE_HOST=$SITE_HOST
WATCH_DEMO_HOST=$DEMO_HOST
# Alerts are pushed to this ntfy topic: subscribe to it in the ntfy app (vm.sh alerts). Its name
# is the secret; empty: alerts go only to the log (journalctl -u plantcraft-watch).
WATCH_NTFY_URL=https://ntfy.sh/$topic
# An e-mail address ntfy also sends each alert to (optional).
WATCH_EMAIL=
EOF
        )
    fi
    install -m 0644 "$SRC/deploy/cloud/plantcraft-watch.service" /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable -q plantcraft-watch
    systemctl restart plantcraft-watch
    log "watch running: the server's health on https://$SITE_HOST/stats; vm.sh alerts for the phone"
}

alerts() {
    [ -f "$CONF/watch.env" ] || die "run vm.sh watch first"
    local url
    url="$(sed -n 's/^WATCH_NTFY_URL=//p' "$CONF/watch.env")"
    [ -n "$url" ] || die "no WATCH_NTFY_URL in $CONF/watch.env"
    printf 'Alerts topic: %s\n' "$url"
    printf 'Phone: install the ntfy app, tap +, topic %s (server ntfy.sh)\n' "${url##*/}"
    curl -fsS -H "Title: PlantCraft test alert" -d "If you read this, the alerts reach you." "$url" >/dev/null &&
        log "test alert sent"
}

site() {
    local flags=(--demo-url "https://$DEMO_HOST/")
    [ -n "$CONTACT" ] && flags+=(--contact "$CONTACT")
    [ "$LAUNCHED" = 1 ] || flags+=(--noindex)
    id plantcraft-site >/dev/null 2>&1 || useradd --system --home "$SITE_HOME" --shell /usr/sbin/nologin plantcraft-site
    install -d -m 0755 "$SITE_HOME"
    install -d -m 0750 -o plantcraft-site -g plantcraft-site "$SITE_DATA"
    install -d -m 0750 -g plantcraft-site "$CONF"
    log "the site's server (Python venv)"
    [ -x "$SITE_HOME/venv/bin/python" ] || python3 -m venv "$SITE_HOME/venv"
    "$SITE_HOME/venv/bin/pip" install -q "$SRC/site"
    log "building the site (${flags[*]})"
    (cd "$SRC/site" && "$SITE_HOME/venv/bin/python" build.py --out "$SITE_HOME/dist.new" "${flags[@]}")
    rm -rf "$SITE_HOME/dist.old"
    [ -d "$SITE_HOME/dist" ] && mv "$SITE_HOME/dist" "$SITE_HOME/dist.old"
    mv "$SITE_HOME/dist.new" "$SITE_HOME/dist"
    if [ ! -f "$CONF/site.env" ]; then
        local provider=off
        [ -s "$CONF/chat-key" ] && provider=openai
        cat >"$CONF/site.env" <<EOF
# PlantCraft's site and chat (site/README.md). Edit, then: systemctl restart plantcraft-site
SITE_DIST=$SITE_HOME/dist
SITE_DATA_DIR=$SITE_DATA
SITE_TRUST_PROXY=cloudflare
SITE_CHAT_PROVIDER=$provider
SITE_CHAT_API_KEY_FILE=$CONF/chat-key
SITE_CHAT_DAILY_LIMIT=1000
# A Slack, Discord, Teams or ntfy address told of each contact request.
SITE_CONTACT_WEBHOOK=
EOF
        chmod 0640 "$CONF/site.env"
        chgrp plantcraft-site "$CONF/site.env"
    fi
    stats_secrets
    # The stats page (added after the first sites: appended once to an existing site.env).
    grep -q '^SITE_STATS_PASSWORD_FILE=' "$CONF/site.env" || cat >>"$CONF/site.env" <<EOF
# The private stats page https://$SITE_HOST/stats (vm.sh stats-password prints its password).
SITE_STATS_PASSWORD_FILE=$CONF/stats-password
SITE_STATS_TIMEZONE=$TIMEZONE
SITE_DEMO_STATS_URL=https://$DEMO_HOST/api/demo/stats
SITE_DEMO_STATS_KEY_FILE=$CONF/demo-stats-key
SITE_DEMO_URL=https://$DEMO_HOST
EOF
    # Empty until vm.sh chat-key: the site starts with its chat off rather than not at all.
    [ -f "$CONF/chat-key" ] || install -m 0640 /dev/null "$CONF/chat-key"
    chgrp plantcraft-site "$CONF/chat-key"
    install -m 0644 "$SRC/deploy/cloud/plantcraft-site.service" /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable -q plantcraft-site
    systemctl restart plantcraft-site
    log "site at http://127.0.0.1:8090 (https://$SITE_HOST through the tunnel)"
    watch
}

set_env() { # set_env KEY VALUE: in the installation's .env
    local env="$SUITE/.env"
    if grep -q "^$1=" "$env"; then
        sed -i "s|^$1=.*|$1=$2|" "$env"
    else
        printf '%s=%s\n' "$1" "$2" >>"$env"
    fi
}

# The suite's own command inside its PlantCraft container, tried for up to 3 minutes while the
# container (re)starts.
suite_cli() {
    local try
    for try in $(seq 1 36); do
        docker compose --project-directory "$SUITE" --env-file "$SUITE/.env" exec -T processcraft \
            plantcraft "$@" && return 0
        sleep 5
    done
    return 1
}

# Visits see "updated in N min" (docs/public-demo.md, "Updating the demo"), no new visit starts,
# and when the time comes every visit ends and waits on the site's page.
update_notice() {
    local minutes="${UPDATE_NOTICE_MINUTES:-2}"
    [ "$minutes" != 0 ] || return 0
    if suite_cli demo update-notice --in "$minutes"; then
        log "visits warned: the update starts in $minutes min"
        sleep "$((minutes * 60))"
    else
        log "could not warn the visits (is the suite running?); updating now"
    fi
}

demo() {
    local version arch archive bundle sign=() gateways
    command -v docker >/dev/null || die "run vm.sh setup first"
    version="$(python3 -c "import tomllib; print(tomllib.load(open('$SRC/pyproject.toml', 'rb'))['project']['version'])")"
    arch="$(dpkg --print-architecture)"
    archive="$SRC/dist/plantcraft-$version-linux-$arch-bundle.tar.gz"
    log "building the bundle $version for $arch here (20 to 40 min the first time; logs in $SRC/dist/e2e-bundle/logs)"
    (cd "$SRC" && ci/e2e-bundle.sh --bundle-only)
    rm -rf "$SRC/dist/vm-bundle" && mkdir -p "$SRC/dist/vm-bundle"
    tar -xzf "$archive" -C "$SRC/dist/vm-bundle"
    bundle="$SRC/dist/vm-bundle/plantcraft-$version-linux-$arch-bundle"
    [ -f "$bundle/SHA256SUMS.sig" ] || sign=(--allow-unsigned)
    if [ -x "$SUITE/install.sh" ]; then
        update_notice
        log "updating the suite in $SUITE"
        "$bundle/install.sh" --prefix "$SUITE" --yes "${sign[@]}"
    else
        log "installing the suite with the public demo in $SUITE"
        "$bundle/install.sh" --prefix "$SUITE" --all-apps --public-demo --yes "${sign[@]}"
    fi
    # Only the tunnel on this host reaches the suite; it reads the visitor's address from it.
    gateways="$(docker network inspect $(docker inspect --format \
        '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}} {{end}}' \
        "$(docker compose --project-directory "$SUITE" --env-file "$SUITE/.env" ps -q proxy)") \
        --format '{{range .IPAM.Config}}{{.Gateway}} {{end}}' | tr -s ' \n' ' ' | sed 's/ *$//')"
    [ -n "$gateways" ] || die "no Docker gateway found for the proxy"
    set_env PLANTCRAFT_HOSTNAME "$DEMO_HOST"
    set_env PLANTCRAFT_BIND_ADDRESS 127.0.0.1
    set_env PLANTCRAFT_TRUSTED_PROXIES "$(printf '%s\n' $gateways | awk 'NF { printf "%s%s/32", sep, $1; sep = "," }')"
    # The site's stats page reads the demo's visits with this key.
    stats_secrets
    set_env PLANTCRAFT_PUBLIC_DEMO_STATS_KEY "$(cat "$CONF/demo-stats-key")"
    # The visit's "Talk to us" button opens the site's contact form.
    set_env PLANTCRAFT_PUBLIC_DEMO_CONTACT_URL "https://$SITE_HOST/#talk"
    # When an update comes, a visit waits on the site's page, which opens the demo again after.
    set_env PLANTCRAFT_PUBLIC_DEMO_UPDATING_URL "https://$SITE_HOST/demo-updating"
    # Each visit plays in its own copy of the apps' data, deleted after it (docs/public-demo.md).
    set_env PLANTCRAFT_PUBLIC_DEMO_ISOLATED "${DEMO_ISOLATED:-true}"
    "$SUITE/install.sh" --yes
    suite_cli demo update-notice --clear || log "could not clear the update notice: run vm.sh demo again"
    log "demo at https://127.0.0.1/ (https://$DEMO_HOST through the tunnel)"
}

status() {
    systemctl --no-pager --lines=0 status cloudflared plantcraft-site plantcraft-watch || true
    [ -f "$SUITE/.env" ] && docker compose --project-directory "$SUITE" --env-file "$SUITE/.env" ps \
        --format 'table {{.Service}}\t{{.Status}}'
    printf 'site: %s\n' "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8090/)"
    printf 'demo: %s\n' "$(curl -sk -o /dev/null -w '%{http_code}' --resolve "$DEMO_HOST:443:127.0.0.1" "https://$DEMO_HOST/")"
}

case "${1:-}" in
    setup) setup ;;
    tunnel) tunnel ;;
    tunnel-login) tunnel_login ;;
    stats-password)
        stats_secrets
        printf 'https://%s/stats  (any user name)  password: %s\n' "$SITE_HOST" "$(cat "$CONF/stats-password")"
        ;;
    chat-key) chat_key ;;
    site) site ;;
    watch) watch ;;
    alerts) alerts ;;
    demo) demo ;;
    all) setup && site && demo ;;
    status) status ;;
    *) sed -n '2,24p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
