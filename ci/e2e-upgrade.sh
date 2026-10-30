#!/usr/bin/env bash
# The upgrade a client makes, on this machine (never in GitHub CI): a released bundle installed
# with data, updated to what the checkouts build now, then rolled back (docs/operations.md,
# section 3). It proves that whoever installs a release can take the next one without losing
# anything, before that next one ships.
#
#   1. builds every image from this repository's apps/ (or *_SRC), tagged TO_VERSION (default: the
#      next patch after the released bundle), and makes a bundle of them (unsigned),
#   2. installs the released bundle in an empty folder (--all-apps --public-demo), as a client did,
#   3. adds marked records and takes a fingerprint through the APIs (ci/upgrade/fingerprint.py):
#      the ids of every list the apps serve, a closed past hour of signal values, the results,
#   4. updates with the new bundle's install.sh (backup first, health check, release notes),
#   5. checks that every id, value and result is still there and that PlantCraft runs TO_VERSION,
#      then walks the demo story (tests/e2e_suite) on the updated suite,
#   6. rolls back (install.sh --rollback) and checks the fingerprint again on the old version.
#
#   FROM_BUNDLE=/path/plantcraft-0.3.0-linux-amd64-bundle.tar.gz ci/e2e-upgrade.sh
#   ci/e2e-upgrade.sh --skip-build     reuse the TO_VERSION images and bundle of a previous run
#   ci/e2e-upgrade.sh --keep           leave the updated stack running (no rollback step)
#   ci/e2e-upgrade.sh --down           uninstall and purge the stack of a previous run
#
# Settings: FROM_BUNDLE (the released bundle: its .tar.gz, or the folder it unpacks to; required),
# TO_VERSION, the *_SRC of ci/e2e-bundle.sh, E2E_PREFIX (install folder, default
# dist/e2e-upgrade/install), BUILD_CA and DOCKER_BUILD_FLAGS as for make image,
# PYTHON (with pytest and Playwright) and PLANTCRAFT_SUITE_CHROMIUM for the journeys. Logs and fingerprints: dist/e2e-upgrade/logs/.
set -Eeuo pipefail
# Associative arrays need bash 4 or newer: macOS's /bin/bash is 3.2 (brew install bash).
if [ "${BASH_VERSINFO[0]}" -lt 4 ]; then
    echo "$0 needs bash 4 or newer (this is $BASH_VERSION); on macOS: brew install bash" >&2
    exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$ROOT/dist/e2e-upgrade"
LOGS="$WORK/logs"
PREFIX="${E2E_PREFIX:-$WORK/install}"
SKIP_BUILD=0
KEEP=0

log() { printf '[e2e-upgrade] %s\n' "$*"; }
die() {
    printf '[e2e-upgrade] ERROR: %s\n' "$*" >&2
    exit 1
}

down() {
    if [ -x "$PREFIX/install.sh" ]; then
        log "removing the stack in $PREFIX"
        (cd "$PREFIX" && ./install.sh --uninstall --purge --prefix "$PREFIX" --yes) \
            >"$LOGS/uninstall.log" 2>&1 || die "uninstall failed: $LOGS/uninstall.log"
    fi
}

for arg in "$@"; do
    case "$arg" in
        --skip-build) SKIP_BUILD=1 ;;
        --keep) KEEP=1 ;;
        --down) mkdir -p "$LOGS"; down; exit 0 ;;
        -h | --help) sed -n '2,27p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "unknown option $arg (--help)" ;;
    esac
done

command -v docker >/dev/null || die "Docker is needed"
docker info >/dev/null 2>&1 || die "the Docker daemon does not answer"
[ -n "${FROM_BUNDLE:-}" ] || die "set FROM_BUNDLE to the released bundle (.tar.gz or its folder)"
mkdir -p "$LOGS"

env_of() { sed -n "s/^$1=//p" "$2" | head -n 1; }
version_of() {
    python3 -c "import sys, tomllib; print(tomllib.load(open(sys.argv[1], 'rb'))['project']['version'])" "$1/pyproject.toml"
}
next_patch() { python3 -c "import sys; a, b, c = sys.argv[1].split('.')[:3]; print(f'{a}.{b}.{int(c.split(\"-\")[0]) + 1}')" "$1"; }

# The released bundle, unpacked once.
if [ -d "$FROM_BUNDLE" ]; then
    from_dir="$(cd "$FROM_BUNDLE" && pwd)"
else
    [ -f "$FROM_BUNDLE" ] || die "no bundle at $FROM_BUNDLE"
    rm -rf "$WORK/from" && mkdir -p "$WORK/from"
    tar -xzf "$FROM_BUNDLE" -C "$WORK/from"
    from_dir="$(find "$WORK/from" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
fi
[ -f "$from_dir/bundle.env" ] || die "$from_dir is not a bundle (no bundle.env)"
(cd "$from_dir" && sha256sum --quiet -c SHA256SUMS) || die "the released bundle's SHA256SUMS do not match"
# A bundle made before the rename to PlantCraft names the platform's version PROCESSCRAFT_VERSION
# (its PLANTCRAFT_VERSION is the Simulator's).
FROM_VERSION="$(env_of PROCESSCRAFT_VERSION "$from_dir/bundle.env")"
FROM_VERSION="${FROM_VERSION:-$(env_of PLANTCRAFT_VERSION "$from_dir/bundle.env")}"
# The Simulator is built from this checkout: 0.5.0 renamed it (plantcraft -> simcraft), so the
# released image no longer fits the new compose file.
SIMCRAFT_VERSION="$(version_of "$ROOT/simulator")"
TO_VERSION="${TO_VERSION:-$(next_patch "$FROM_VERSION")}"
APPS=(linkcraft dashcraft histcraft alarmcraft modelcraft doccraft)
# Each app's source: its *_SRC, else its folder in this repository (as in ci/e2e-bundle.sh).
declare -A FOLDER=([linkcraft]=apps/link [dashcraft]=apps/view [histcraft]=apps/historian [alarmcraft]=apps/alarms [modelcraft]=apps/models [doccraft]=apps/documents)
declare -A SRC
for app in "${APPS[@]}"; do
    key="${app^^}_SRC"
    value="${!key:-$ROOT/${FOLDER[$app]}}"
    [ -f "$value/Makefile" ] || die "no $app at $value: set $key"
    SRC[$app]="$(cd "$value" && pwd)"
done
log "from $FROM_VERSION (released bundle) to $TO_VERSION (these checkouts)"

started=$(date +%s)
step() { log "$1 ($(($(date +%s) - started)) s)"; }

if [ "$SKIP_BUILD" = 0 ]; then
    step "building the images of $TO_VERSION"
    for app in "${APPS[@]}"; do
        version="$(version_of "${SRC[$app]}")"
        make -C "${SRC[$app]}" image BUILD_CA="${BUILD_CA:-}" DOCKER_BUILD_FLAGS="${DOCKER_BUILD_FLAGS:-}" \
            >"$LOGS/image-$app.log" 2>&1 || die "$app image: $LOGS/image-$app.log"
        docker tag "$app:$version" "$app:$TO_VERSION"
        if [ "$app" = modelcraft ]; then
            make -C "${SRC[$app]}" runner-image BUILD_CA="${BUILD_CA:-}" DOCKER_BUILD_FLAGS="${DOCKER_BUILD_FLAGS:-}" \
                >"$LOGS/image-modelcraft-runner.log" 2>&1 || die "modelcraft-runner image: $LOGS/image-modelcraft-runner.log"
            docker tag "modelcraft-runner:$version" "modelcraft-runner:$TO_VERSION"
        fi
        log "  $app:$TO_VERSION ($(git -C "${SRC[$app]}" rev-parse --short HEAD))"
    done
    # The released images again under their own tags (an app whose version did not move was just
    # built under the released tag): the installation of step 2 runs exactly what was released.
    step "loading the released images"
    docker load -i "$from_dir/images.tar" >"$LOGS/load-from.log" 2>&1 || die "docker load: $LOGS/load-from.log"
    # The pinned third-party images compose.yaml names (the Historian's database and gateway).
    for image in $(sed -n 's/^ *image: \${[A-Z_]*:-\([a-z0-9._/-]*:[^ ]*@sha256:[0-9a-f]\{64\}\)}$/\1/p' "$ROOT/deploy/compose.yaml"); do
        for wait in 2 8 30 0; do
            docker image inspect "$image" >/dev/null 2>&1 || docker pull -q "$image" >>"$LOGS/pull.log" 2>&1 && break
            [ "$wait" = 0 ] && die "docker pull $image: $LOGS/pull.log"
            sleep "$wait" # a registry's rate limit (429) passes
        done
    done
    step "making the $TO_VERSION bundle"
    make -C "$ROOT" bundle VERSION="$TO_VERSION" LINKCRAFT_VERSION="$TO_VERSION" DASHCRAFT_VERSION="$TO_VERSION" \
        HISTCRAFT_VERSION="$TO_VERSION" ALARMCRAFT_VERSION="$TO_VERSION" MODELCRAFT_VERSION="$TO_VERSION" DOCCRAFT_VERSION="$TO_VERSION" \
        SIMCRAFT_VERSION="$SIMCRAFT_VERSION" SIMCRAFT_SRC="$ROOT/simulator" \
        BUILD_CA="${BUILD_CA:-}" DOCKER_BUILD_FLAGS="${DOCKER_BUILD_FLAGS:-}" \
        >"$LOGS/bundle.log" 2>&1 || die "make bundle: $LOGS/bundle.log"
fi
ARCH="$(docker info --format '{{.Architecture}}')"
case "$ARCH" in x86_64) ARCH=amd64 ;; aarch64) ARCH=arm64 ;; esac
archive="$ROOT/dist/plantcraft-$TO_VERSION-linux-$ARCH-bundle.tar.gz"
[ -f "$archive" ] || die "no $TO_VERSION bundle at $archive (run without --skip-build)"
rm -rf "$WORK/to" && mkdir -p "$WORK/to"
tar -xzf "$archive" -C "$WORK/to"
to_dir="$WORK/to/plantcraft-$TO_VERSION-linux-$ARCH-bundle"
(cd "$to_dir" && sha256sum --quiet -c SHA256SUMS) || die "the $TO_VERSION bundle's SHA256SUMS do not match"

step "installing the released $FROM_VERSION, as a client did"
if [ -x "$PREFIX/install.sh" ]; then
    (cd "$PREFIX" && ./install.sh --uninstall --purge --prefix "$PREFIX" --yes) >"$LOGS/uninstall-previous.log" 2>&1 || true
fi
rm -rf "$PREFIX" && mkdir -p "$PREFIX"
noproxy=(env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy)
"${noproxy[@]}" "$from_dir/install.sh" --prefix "$PREFIX" --all-apps --public-demo --yes \
    >"$LOGS/install-from.log" 2>&1 || die "install.sh of $FROM_VERSION: $LOGS/install-from.log"

host="$(sed -n 's/^PLANTCRAFT_HOSTNAME=\([^ ]*\).*/\1/p' "$PREFIX/.env")"
url="https://${host:-localhost}/"
password="$PREFIX/data/initial-admin-password"
[ -r "$password" ] || die "cannot read $password (run as the installation's owner or root)"
fingerprint() { "${noproxy[@]}" python3 "$ROOT/ci/upgrade/fingerprint.py" "$@" --url "$url" --password-file "$password"; }

step "adding marked records and taking the fingerprint of $FROM_VERSION"
# The demo's first rounds publish their results; a fingerprint taken before them misses some.
sleep_until() { python3 -c "import time; time.sleep($1)"; }
sleep_until 90
fingerprint seed >"$LOGS/seed.log" 2>&1 || die "seeding: $LOGS/seed.log"
fingerprint take --out "$LOGS/before.json" | tee "$LOGS/before.log"

step "updating to $TO_VERSION with its install.sh (backup, health check, release notes)"
"${noproxy[@]}" "$to_dir/install.sh" --prefix "$PREFIX" --all-apps --public-demo --yes --allow-unsigned \
    >"$LOGS/update.log" 2>&1 || die "the update failed: $LOGS/update.log"
grep -q "Updated from $FROM_VERSION to $TO_VERSION" "$LOGS/update.log" || die "install.sh did not report the update: $LOGS/update.log"
[ "$(env_of PLANTCRAFT_VERSION "$PREFIX/.env")" = "$TO_VERSION" ] || die "the installation does not run $TO_VERSION"

step "checking that nothing was lost"
status=0
fingerprint check --before "$LOGS/before.json" --out "$LOGS/after.json" --versions "$TO_VERSION" \
    | tee "$LOGS/check-after.log" || status=1

step "walking the demo story on $TO_VERSION (tests/e2e_suite)"
journeys=0
(cd "$ROOT" && PLANTCRAFT_SUITE_URL="$url" "${PYTHON:-python3}" -m pytest -q tests/e2e_suite) >"$LOGS/journeys.log" 2>&1 || journeys=$?
tail -n 3 "$LOGS/journeys.log"

rollback=skipped
if [ "$KEEP" = 0 ]; then
    step "rolling back to $FROM_VERSION"
    if (cd "$PREFIX" && "${noproxy[@]}" ./install.sh --rollback --prefix "$PREFIX" --yes) >"$LOGS/rollback.log" 2>&1 &&
        [ "$(env_of PLANTCRAFT_VERSION "$PREFIX/.env")" = "$FROM_VERSION" ]; then
        sleep_until 30
        if fingerprint check --before "$LOGS/before.json" --out "$LOGS/rolled-back.json" | tee "$LOGS/check-rollback.log"; then
            rollback=ok
        else
            rollback=lost
        fi
    else
        rollback=failed
    fi
fi

{
    echo "from=$FROM_VERSION to=$TO_VERSION seconds=$(($(date +%s) - started))"
    echo "processcraft $(git -C "$ROOT" rev-parse --short HEAD)"
    for app in "${APPS[@]}"; do echo "$app $(git -C "${SRC[$app]}" rev-parse --short HEAD)"; done
    echo "kept=$([ "$status" = 0 ] && echo yes || echo NO) journeys_exit=$journeys rollback=$rollback"
} >"$LOGS/summary.txt"
cat "$LOGS/summary.txt"
[ "$status" = 0 ] || die "data was lost in the update: $LOGS/check-after.log"
[ "$journeys" = 0 ] || die "the journeys failed on $TO_VERSION: $LOGS/journeys.log"
case "$rollback" in ok | skipped) ;; *) die "the rollback $rollback: $LOGS/rollback.log" ;; esac
step "done: $FROM_VERSION → $TO_VERSION kept everything$([ "$KEEP" = 1 ] && echo "; the stack runs at $url")"
