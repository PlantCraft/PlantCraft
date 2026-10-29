#!/usr/bin/env bash
# The site and the demo seen from outside the VM: when the whole VM (or its tunnel) is gone, the
# watch on it (plantcraft-watch) cannot say so. Run on another machine (the Mac mini); every
# minute it opens both pages and pushes to the same ntfy topic as the VM's alerts after 3 misses
# in a row, and once more when they answer again.
#
#   outside-watch.sh install NTFY_URL   a LaunchAgent (macOS) running the check every minute
#   outside-watch.sh uninstall
#   outside-watch.sh check              one check (what the LaunchAgent runs)
#
# NTFY_URL is the topic vm.sh alerts prints on the VM. Settings: SITE_HOST (plantcraft.io),
# DEMO_HOST (demo.plantcraft.io). Written for the macOS bash 3.2 too.
set -uo pipefail

STATE="${HOME}/.plantcraft-outside-watch"
LABEL=io.plantcraft.outside-watch
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
SITE_HOST="${SITE_HOST:-plantcraft.io}"
DEMO_HOST="${DEMO_HOST:-demo.plantcraft.io}"
MISSES=3

push() { # push TITLE TEXT PRIORITY
    local url
    url="$(cat "$STATE/ntfy-url" 2>/dev/null)"
    [ -n "$url" ] || return 0
    curl -fsS -m 15 -H "Title: $1" -H "Priority: $3" -H "Click: https://$SITE_HOST/stats" \
        -d "$2" "$url" >/dev/null || true
}

check_one() { # check_one NAME URL
    local name="$1" url="$2" code count file="$STATE/$1.misses"
    code="$(curl -s -o /dev/null -m 20 -A PlantCraft-outside-watch/1 -w '%{http_code}' "$url")"
    count="$(cat "$file" 2>/dev/null || echo 0)"
    if [ "$code" -ge 200 ] 2>/dev/null && [ "$code" -lt 400 ]; then
        if [ "$count" -ge "$MISSES" ]; then
            push "PlantCraft: back to normal" "OK again (seen from outside): $name $url" default
        fi
        echo 0 >"$file"
        return
    fi
    count=$((count + 1))
    echo "$count" >"$file"
    if [ "$count" -eq "$MISSES" ]; then
        push "PlantCraft: something is wrong" \
            "PROBLEM (seen from outside): $name $url answers ${code:-nothing} for $MISSES min" high
    fi
}

case "${1:-}" in
    check)
        mkdir -p "$STATE"
        check_one site "https://$SITE_HOST/"
        check_one demo "https://$DEMO_HOST/"
        ;;
    install)
        [ -n "${2:-}" ] || { echo "usage: $0 install NTFY_URL" >&2; exit 1; }
        mkdir -p "$STATE" "$(dirname "$PLIST")"
        (umask 077 && printf '%s\n' "$2" >"$STATE/ntfy-url")
        cp "$0" "$STATE/outside-watch.sh" && chmod 0755 "$STATE/outside-watch.sh"
        cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>$STATE/outside-watch.sh</string><string>check</string>
  </array>
  <key>EnvironmentVariables</key><dict>
    <key>SITE_HOST</key><string>$SITE_HOST</string><key>DEMO_HOST</key><string>$DEMO_HOST</string>
  </dict>
  <key>StartInterval</key><integer>60</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardErrorPath</key><string>$STATE/error.log</string>
</dict></plist>
EOF
        launchctl unload "$PLIST" 2>/dev/null || true
        launchctl load "$PLIST"
        push "PlantCraft outside watch started" "The Mac mini checks $SITE_HOST and $DEMO_HOST every minute." default
        echo "outside watch on: every minute; state in $STATE"
        ;;
    uninstall)
        launchctl unload "$PLIST" 2>/dev/null || true
        rm -f "$PLIST"
        echo "outside watch off"
        ;;
    *) sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
