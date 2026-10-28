#!/usr/bin/env bash
# A second suite beside the one being developed, on one build, for the long tests (never in CI).
#
#   ci/bench/frozen.sh install BUNDLE_DIR [PREFIX] [PORT]   install it (default ~/PlantCraft-carga, 8443)
#   ci/bench/frozen.sh check PREFIX                         still on the images it was installed with?
#
# The suite in development (~/PlantCraft on the Mac mini) takes every merge
# (ci/macmini/suite-deploy, which only touches SUITE_DIR); this one does not: it is installed from
# a bundle (make bundle at the commit to test, or a release's), under its own Compose project
# (COMPOSE_PROJECT_NAME=processcraft-carga, so its own containers, networks and volumes) and its
# own port, with every app and the demo plant. Nothing updates it; install a newer bundle over it
# (install.sh in that bundle, --prefix PREFIX) when a newer build is to be tested.
#
# Its containers keep the image they were created with even when the suite in development
# retags the same names: `check` compares them with the list written at install
# (PREFIX/data/frozen-images.txt). Recreating its containers by hand (compose up) would take the
# images of the moment, so leave it to install.sh.
#
# Then, on it: ci/bench/suite_bench.py --keep (the plant at scale), ci/bench/age.py (months of
# history in steps) and ci/bench/soak.py (days at the plant's speed), with --prefix PREFIX.
set -Eeuo pipefail

log() { printf '[frozen] %s\n' "$*"; }
die() {
    printf '[frozen] ERROR: %s\n' "$*" >&2
    exit 1
}

images() { # images PREFIX: "container image-id" of the suite's containers
    local project
    project="$(sed -n 's/^COMPOSE_PROJECT_NAME=//p' "$1/.env" | tail -n 1)"
    docker ps -a --filter "label=com.docker.compose.project=$project" --format '{{.Names}} {{.Image}}' |
        while read -r name image; do
            printf '%s %s %s\n' "$name" "$image" "$(docker inspect -f '{{.Image}}' "$name")"
        done | sort
}

install() {
    local bundle="${1:?the bundle folder (make bundle, or an unpacked release)}"
    local prefix="${2:-$HOME/PlantCraft-carga}" port="${3:-8443}"
    bundle="$(cd "$bundle" && pwd)"
    [ -x "$bundle/install.sh" ] && [ -f "$bundle/.env.example" ] || die "no bundle in $bundle"
    mkdir -p "$prefix"
    prefix="$(cd "$prefix" && pwd)"
    if [ ! -f "$prefix/.env" ]; then
        # install.sh makes .env from .env.example only when there is none: this one first, with
        # the project and port of its own.
        local name ip
        name="$(hostname -f 2>/dev/null || hostname)"
        ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
        sed -e 's/^COMPOSE_PROJECT_NAME=.*/COMPOSE_PROJECT_NAME=processcraft-carga/' \
            -e "s/^PLANTCRAFT_HTTPS_PORT=.*/PLANTCRAFT_HTTPS_PORT=$port/" \
            "$bundle/.env.example" >"$prefix/.env"
        printf 'PLANTCRAFT_HOSTNAME=%s\n' "$name${ip:+ $ip}" >>"$prefix/.env"
        chmod 0640 "$prefix/.env"
    fi
    grep -q '^COMPOSE_PROJECT_NAME=processcraft-carga$' "$prefix/.env" ||
        die "$prefix/.env is not a frozen suite's (COMPOSE_PROJECT_NAME): choose another folder"
    log "installing $bundle in $prefix (project processcraft-carga, port $port)"
    (cd "$bundle" && ./install.sh --prefix "$prefix" --all-apps --demo --allow-unsigned --yes)
    images "$prefix" >"$prefix/data/frozen-images.txt"
    log "$(wc -l <"$prefix/data/frozen-images.txt") containers, their images in data/frozen-images.txt"
    log "open https://$(hostname):$port/ (admin password in $prefix/data/initial-admin-password)"
}

check() {
    local prefix="${1:?the folder of the frozen suite}"
    [ -f "$prefix/data/frozen-images.txt" ] || die "no frozen suite in $prefix"
    if diff <(cat "$prefix/data/frozen-images.txt") <(images "$prefix"); then
        log "every container is on the image it was installed with"
    else
        die "some containers changed image since the install (above)"
    fi
}

case "${1:-}" in
    install) shift; install "$@" ;;
    check) shift; check "$@" ;;
    *) sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
