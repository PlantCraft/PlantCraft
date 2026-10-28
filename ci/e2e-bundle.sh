#!/usr/bin/env bash
# The whole suite from source to a walked demo, on this machine (gap G35; never in GitHub CI):
#
#   1. builds every image from the checkouts next to this one (or *_SRC),
#   2. makes the offline bundle (make bundle) and checks its SHA256SUMS,
#   3. installs it in an empty folder with `install.sh --all-apps --public-demo --yes`
#      (the images come only from the bundle's images.tar),
#   4. walks the demo story with the suite journeys (tests/e2e_suite) through the proxy,
#   5. leaves the stack running for a look, or removes it with --down.
#
#   make e2e-bundle                      everything, stack left running at https://<hostname>/
#   ci/e2e-bundle.sh --skip-build        reuse the images already built
#   ci/e2e-bundle.sh --down              uninstall and purge the stack of a previous run
#   ci/e2e-bundle.sh --bundle-only       steps 1 and 2 only: the checked bundle, nothing installed
#                                        (deploy/cloud/vm.sh builds the public demo's this way)
#
# Settings: LINKCRAFT_SRC, DASHCRAFT_SRC, HISTCRAFT_SRC, ALARMCRAFT_SRC, MODELCRAFT_SRC,
# SIMCRAFT_SRC (default: the app's folder in this repository, apps/<name> or simulator), E2E_PREFIX (install folder, default dist/e2e-bundle/install), PLANTCRAFT_SUITE_CHROMIUM (a
# Chromium binary when Playwright's own is not installed), BUILD_CA and DOCKER_BUILD_FLAGS as
# for make image. Logs: dist/e2e-bundle/logs/.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$ROOT/dist/e2e-bundle"
LOGS="$WORK/logs"
PREFIX="${E2E_PREFIX:-$WORK/install}"
SKIP_BUILD=0
BUNDLE_ONLY=0

log() { printf '[e2e-bundle] %s\n' "$*"; }
die() {
    printf '[e2e-bundle] ERROR: %s\n' "$*" >&2
    exit 1
}

source_of() {
    # An app's source: its *_SRC, else its folder in this repository.
    local key="$1" default="$2" value
    value="${!key:-$ROOT/$default}"
    [ -f "$value/Makefile" ] || die "no $default at $value: set $key"
    (cd "$value" && pwd)
}

version_of() {
    python3 -c "import sys, tomllib; print(tomllib.load(open(sys.argv[1], 'rb'))['project']['version'])" \
        "$1/pyproject.toml"
}

down() {
    if [ -x "$PREFIX/install.sh" ]; then
        log "removing the stack in $PREFIX"
        (cd "$PREFIX" && ./install.sh --uninstall --purge --prefix "$PREFIX" --yes) \
            >"$LOGS/uninstall.log" 2>&1 || die "uninstall failed: $LOGS/uninstall.log"
    fi
    rm -rf "$WORK/bundle"
}

for arg in "$@"; do
    case "$arg" in
        --skip-build) SKIP_BUILD=1 ;;
        --bundle-only) BUNDLE_ONLY=1 ;;
        --down) mkdir -p "$LOGS"; down; exit 0 ;;
        -h | --help) sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "unknown option $arg (--help)" ;;
    esac
done

command -v docker >/dev/null || die "Docker is needed"
docker info >/dev/null 2>&1 || die "the Docker daemon does not answer"
mkdir -p "$LOGS"

VERSION="$(version_of "$ROOT")"
SIMCRAFT_SRC="$(source_of SIMCRAFT_SRC simulator)"
SIMCRAFT_VERSION="$(version_of "$SIMCRAFT_SRC")"
declare -A SRC=(
    [linkcraft]="$(source_of LINKCRAFT_SRC apps/link)"
    [dashcraft]="$(source_of DASHCRAFT_SRC apps/view)"
    [histcraft]="$(source_of HISTCRAFT_SRC apps/historian)"
    [alarmcraft]="$(source_of ALARMCRAFT_SRC apps/alarms)"
    [modelcraft]="$(source_of MODELCRAFT_SRC apps/models)"
    [doccraft]="$(source_of DOCCRAFT_SRC apps/documents)"
)
for app in linkcraft dashcraft histcraft alarmcraft modelcraft doccraft; do
    found="$(version_of "${SRC[$app]}")"
    [ "$found" = "$VERSION" ] || die "$app at ${SRC[$app]} is $found, PlantCraft is $VERSION"
done

started=$(date +%s)
step() { log "$1 ($(($(date +%s) - started)) s)"; }

if [ "$SKIP_BUILD" = 0 ]; then
    step "building the images"
    for app in linkcraft dashcraft histcraft alarmcraft modelcraft doccraft; do
        make -C "${SRC[$app]}" image BUILD_CA="${BUILD_CA:-}" \
            DOCKER_BUILD_FLAGS="${DOCKER_BUILD_FLAGS:-}" >"$LOGS/image-$app.log" 2>&1 \
            || die "$app image: $LOGS/image-$app.log"
        if [ "$app" = modelcraft ]; then
            make -C "${SRC[$app]}" runner-image BUILD_CA="${BUILD_CA:-}" \
                DOCKER_BUILD_FLAGS="${DOCKER_BUILD_FLAGS:-}" >"$LOGS/image-modelcraft-runner.log" 2>&1 \
                || die "modelcraft-runner image: $LOGS/image-modelcraft-runner.log"
        fi
        log "  $app:$VERSION ($(git -C "${SRC[$app]}" rev-parse --short HEAD))"
    done
fi

# Third-party images pinned by digest in compose.yaml (HistCraft's PostgreSQL and its Telegraf
# gateway), written plain or as a ${VAR:-default}: pulled once, bundled like the rest.
for pinned in $(grep -o '[a-z][a-z0-9./_-]*:[^ @}]*@sha256:[0-9a-f]\{64\}' "$ROOT/deploy/compose.yaml" | sort -u); do
    if ! docker image inspect "$pinned" >/dev/null 2>&1; then
        step "pulling $pinned"
        docker pull -q "$pinned" >>"$LOGS/pull-pinned.log" 2>&1 \
            || die "docker pull $pinned: $LOGS/pull-pinned.log"
    fi
done

step "making the bundle"
make -C "$ROOT" bundle SIMCRAFT_SRC="$SIMCRAFT_SRC" SIMCRAFT_VERSION="$SIMCRAFT_VERSION" \
    BUILD_CA="${BUILD_CA:-}" DOCKER_BUILD_FLAGS="${DOCKER_BUILD_FLAGS:-}" \
    >"$LOGS/bundle.log" 2>&1 || die "make bundle: $LOGS/bundle.log"
ARCH="$(docker info --format '{{.Architecture}}')"
case "$ARCH" in x86_64) ARCH=amd64 ;; aarch64) ARCH=arm64 ;; esac
archive="$ROOT/dist/processcraft-$VERSION-linux-$ARCH-bundle.tar.gz"
[ -f "$archive" ] || die "no bundle at $archive"

step "unpacking and checking the bundle"
rm -rf "$WORK/bundle"
mkdir -p "$WORK/bundle"
tar -xzf "$archive" -C "$WORK/bundle"
bundle="$WORK/bundle/processcraft-$VERSION-linux-$ARCH-bundle"
(cd "$bundle" && sha256sum --quiet -c SHA256SUMS) || die "the bundle's SHA256SUMS do not match"
for app in linkcraft dashcraft histcraft alarmcraft modelcraft doccraft simcraft; do
    grep -q "$app" "$bundle/bundle.env" || die "the bundle has no $app image: $LOGS/bundle.log"
done
if [ "$BUNDLE_ONLY" = 1 ]; then
    step "bundle ready: $archive"
    exit 0
fi

step "installing (no network for the containers; images from images.tar)"
if [ -x "$PREFIX/install.sh" ]; then
    (cd "$PREFIX" && ./install.sh --uninstall --purge --prefix "$PREFIX" --yes) \
        >"$LOGS/uninstall-previous.log" 2>&1 || true
fi
mkdir -p "$PREFIX"
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
    "$bundle/install.sh" --prefix "$PREFIX" --all-apps --public-demo --yes \
    $([ -n "${RELEASE_KEY:-}" ] || echo --allow-unsigned) \
    >"$LOGS/install.log" 2>&1 || die "install.sh: $LOGS/install.log"

step "walking the demo story (tests/e2e_suite)"
# The proxy's certificate names the installation's host (PLANTCRAFT_HOSTNAME, first word).
host="$(sed -n 's/^PLANTCRAFT_HOSTNAME=\([^ ]*\).*/\1/p' "$PREFIX/.env")"
url="https://${host:-localhost}/"
status=0
(cd "$ROOT" && PLANTCRAFT_SUITE_URL="$url" python -m pytest -q tests/e2e_suite) \
    >"$LOGS/journeys.log" 2>&1 || status=$?
tail -n 3 "$LOGS/journeys.log"

{
    echo "version=$VERSION simcraft=$SIMCRAFT_VERSION seconds=$(($(date +%s) - started))"
    echo "processcraft $(git -C "$ROOT" rev-parse --short HEAD)"
    for app in linkcraft dashcraft histcraft alarmcraft modelcraft doccraft; do
        echo "$app $(git -C "${SRC[$app]}" rev-parse --short HEAD)"
    done
    echo "simcraft $(git -C "$SIMCRAFT_SRC" rev-parse --short HEAD)"
    echo "journeys exit=$status"
} >"$LOGS/summary.txt"
cat "$LOGS/summary.txt"
[ "$status" = 0 ] || die "journeys failed: $LOGS/journeys.log (stack left at $url)"
step "done: the stack is running at $url (ci/e2e-bundle.sh --down removes it)"
