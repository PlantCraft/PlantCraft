#!/usr/bin/env bash
# The preview loop of `suite-dev` (dev/README.md). It runs in the processcraft-dev container on
# the Mac mini, never on a client's server.
#
# It keeps one checkout of the repository on its `preview` branch (main when there is none) and,
# for each app, a watch.mjs build of the app's interface into its folder's frontend/dist, which the
# app's container serves (dev.compose.yaml). A push to `preview` shows in the browser a few
# seconds later.
#
# Environment: APPS (the apps whose interface it builds, as compose services), OWNER (REMOTE:
# where the repository is, https://github.com/OWNER), BRANCH (preview), INTERVAL (seconds between
# checks), GH_TOKEN (reads the private repository). /work is the suite's dev/ folder:
# src/processcraft the checkout, state/<app> what each app shows, logs in docker logs.
set -uo pipefail

: "${APPS:?}" "${GH_TOKEN:?}"
OWNER="${OWNER:-PlantCraft}"
REMOTE="${REMOTE:-https://github.com/$OWNER}"
BRANCH="${BRANCH:-preview}"
INTERVAL="${INTERVAL:-3}"
export WORK=/work
umask 022
mkdir -p "$WORK/src" "$WORK/state"
git config --global credential.helper '!f() { echo username=x-access-token; echo "password=$GH_TOKEN"; }; f'
git config --global advice.detachedHead false
git config --global --add safe.directory '*'

SRC="$WORK/src/processcraft"
# Where each app lives in the repository (processcraft is the platform, at the root).
folder_of() {
    case "$1" in
        processcraft) echo . ;;
        linkcraft) echo apps/link ;;
        histcraft) echo apps/historian ;;
        dashcraft) echo apps/view ;;
        alarmcraft) echo apps/alarms ;;
        modelcraft) echo apps/models ;;
        doccraft) echo apps/documents ;;
        *) return 1 ;;
    esac
}

log() { echo "$(date +%H:%M:%S) [$1] ${*:2}"; }
declare -A watcher

# The commit to show: the head of BRANCH when the repository has one, else main's.
wanted() {
    local refs
    refs="$(git -C "$SRC" ls-remote origin "refs/heads/$BRANCH" refs/heads/main 2>/dev/null)" || return 1
    awk -v b="refs/heads/$BRANCH" '$2 == b { print $1 " " "'"$BRANCH"'"; found = 1 } END { if (!found) exit 1 }' <<<"$refs" ||
        awk '$2 == "refs/heads/main" { print $1 " main" }' <<<"$refs"
}

# Each build runs in a process group of its own, so stopping it stops node too.
stop_watch() {
    local pid="${watcher[$1]:-}"
    if [ -n "$pid" ]; then
        kill -- "-$pid" 2>/dev/null
        wait "$pid" 2>/dev/null
    fi
    watcher[$1]=""
}

start_watch() {
    local app="$1"
    stop_watch "$app"
    APP="$app" FRONT="$SRC/$(folder_of "$app")/frontend" SRC="$SRC" setsid bash -c '
        cd "$FRONT" || exit 1
        node "$SRC/dev/watch.mjs" --ui "$SRC/ui/src" 2>&1 |
            while IFS= read -r line; do
                echo "$(date +%H:%M:%S) [$APP] $line"
                case "$line" in "built in"*) cp "$WORK/state/checkout" "$WORK/state/$APP" ;; esac
            done' &
    watcher[$app]=$!
}

# npm ci when the package-lock changed since the last install into node_modules (a volume that
# outlives the container, so a restart reinstalls nothing).
install_deps() {
    local app="$1" front="$SRC/$(folder_of "$1")/frontend" lock
    lock="$(sha256sum "$front/package-lock.json" | cut -c1-64)"
    [ "$(cat "$front/node_modules/.suite-dev-lock" 2>/dev/null)" = "$lock" ] && return 0
    log "$app" "npm ci"
    (cd "$front" && npm ci --no-audit --no-fund --no-update-notifier --loglevel=error) 2>&1 |
        while IFS= read -r line; do log "$app" "$line"; done
    [ -d "$front/node_modules/vite" ] && echo "$lock" >"$front/node_modules/.suite-dev-lock"
    return 0
}

changed() { [ -n "$1" ] && ! git -C "$SRC" diff --quiet "$1" "$2" -- "${@:3}" 2>/dev/null; }

# Checks out SHA; reinstalls and restarts an app's build when what it depends on changed (a
# change to its sources alone is picked up by the build that is already watching them).
update() {
    local sha="$1" ref="$2" old="${shown:-}" app folder
    git -C "$SRC" fetch -q --depth=1 origin "$sha" || { log suite "fetch ${sha:0:7} failed"; return 1; }
    git -C "$SRC" checkout -q -f --detach "$sha" && git -C "$SRC" clean -q -fd -e node_modules -e dist
    echo "$ref ${sha:0:7} $(date -u +%FT%TZ)" >"$WORK/state/checkout"
    log suite "now $ref ${sha:0:7}"
    shown="$sha"
    if changed "$old" "$sha" dev/follow.sh; then
        log suite "dev/follow.sh changed: restarting with the new one"
        for app in $APPS; do stop_watch "$app"; done
        exit 0 # --restart unless-stopped runs the container again, with this checkout's copy
    fi
    for app in $APPS; do
        folder="$(folder_of "$app")"
        if [ -z "$old" ] || [ -z "${watcher[$app]:-}" ] || changed "$old" "$sha" dev/watch.mjs ||
            changed "$old" "$sha" "$folder/frontend/package-lock.json" "$folder/frontend/vite.config.*"; then
            install_deps "$app"
            start_watch "$app"
        fi
    done
}

# An app that no longer exists (renamed or retired) is skipped, not fatal: exiting here would put
# a container started with an older app list into a restart loop.
known=""
for app in $APPS; do
    if folder_of "$app" >/dev/null; then known="$known $app"; else log suite "$app: no such app, skipped"; fi
done
APPS="${known# }"
[ -n "$APPS" ] || { log suite "no known app to build"; exit 1; }
[ -d "$SRC/.git" ] || { git init -q "$SRC" && git -C "$SRC" remote add origin "$REMOTE/processcraft.git"; }
shown=""

trap 'for a in $APPS; do stop_watch "$a"; done; exit 0' TERM INT
log suite "following $BRANCH (else main); building: $APPS"
while :; do
    if read -r sha ref < <(wanted); then
        [ "$sha" = "$shown" ] || update "$sha" "$ref"
    fi
    for app in $APPS; do
        # A build that stopped (an error it could not recover from) starts again.
        pid="${watcher[$app]:-}"
        if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
            log "$app" "build stopped; starting it again"
            start_watch "$app"
        fi
    done
    sleep "$INTERVAL"
done
