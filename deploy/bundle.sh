#!/usr/bin/env bash
# Builds the offline release bundle (run by `make bundle`, on a machine with internet), for one
# processor architecture (ARCH: amd64 or arm64, default this machine's Docker):
#
#   dist/plantcraft-<version>-linux-<arch>-bundle/
#     images.tar            docker save of every image the suite runs
#     compose.yaml compose-worker.yaml certs/ .env.example bundle.env
#     install.sh firewall.sh docs/ LICENSE NOTICE
#     trusted-publishers/   public keys of the app publishers this server accepts
#     demo/                 plant map of the Simulator's 50 loops (with the Simulator only)
#     notebook-kits/        optional: Python and JupyterLab for people's own computers (Notebooks ›
#                           Run on your computer), when NOTEBOOK_KITS (default notebooks/kit/dist,
#                           make notebook-kits) holds kits.json; NOTEBOOK_KITS=none leaves them out
#     sbom/                 CycloneDX SBOMs (Python image dependencies, web interface) and each
#                           app image's own SBOM when it carries one (/app/sbom.json)
#     release.json          suite version, upgrade_from, each module's version, every image id,
#                           each app's [permissions] (from /app/app.toml of its image)
#     RELEASE-NOTES.md      each module's CHANGELOG.md entry for its version
#     SHA256SUMS            hash of every file above
#     SHA256SUMS.sig        Ed25519 signature over SHA256SUMS (with RELEASE_KEY, the publisher's
#                           private key, never committed; RELEASE_PUBLISHER, default processcraft)
#   dist/plantcraft-<version>-linux-<arch>-bundle.tar.gz (+ .sha256, + .sha256.sig: the same
#                         key's OpenSSH signature over that hash, for ssh-keygen -Y verify)
#
# Every image must be built for ARCH (make image DOCKER_BUILD_FLAGS=--platform=linux/<arch>;
# docs/install-offline.md, section 10). Without RELEASE_KEY the bundle is not signed; to sign it
# on another machine that holds the key (an offline one), see docs/operations.md, section 3.
#
# The processcraft, processcraft-proxy and processcraft-installer images must already be built
# (make image). Each app of the suite (LinkCraft, DashCraft, HistCraft, PlantCraft Alarms, PlantCraft Models) is added when its image <id>:$<ID>_VERSION exists on this machine (built in its own
# repository), PlantCraft Models with its runner (modelcraft-runner:$MODELCRAFT_VERSION, make
# runner-image in modelcraft), HistCraft with its PostgreSQL image (pinned by digest, pulled once: docker pull <HISTCRAFT_DB_IMAGE>)
# and its gateway, Telegraf (pinned by digest too: docker pull <HISTCRAFT_GATEWAY_IMAGE>),
# and the Simulator (the `demo` profile) when simcraft:$SIMCRAFT_VERSION does (make
# simcraft-image builds it from simulator/).
set -Eeuo pipefail
# Associative arrays need bash 4 or newer: macOS's /bin/bash is 3.2 (brew install bash).
if [ "${BASH_VERSINFO[0]}" -lt 4 ]; then
    echo "$0 needs bash 4 or newer (this is $BASH_VERSION); on macOS: brew install bash" >&2
    exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${VERSION:?set VERSION}"
LINKCRAFT_VERSION="${LINKCRAFT_VERSION:-$VERSION}"
DASHCRAFT_VERSION="${DASHCRAFT_VERSION:-$VERSION}"
HISTCRAFT_VERSION="${HISTCRAFT_VERSION:-$VERSION}"
ALARMCRAFT_VERSION="${ALARMCRAFT_VERSION:-$VERSION}"
MODELCRAFT_VERSION="${MODELCRAFT_VERSION:-$VERSION}"
DOCCRAFT_VERSION="${DOCCRAFT_VERSION:-$VERSION}"
# The apps compose.yaml runs, each in its own profile (install.sh SUITE_APPS).
APPS=(linkcraft dashcraft histcraft alarmcraft modelcraft doccraft)
SIMCRAFT_VERSION="${SIMCRAFT_VERSION:-0.5.1}"
# The oldest installed version this bundle updates (install.sh refuses older ones).
UPGRADE_FROM="${UPGRADE_FROM:-0.1.0}"
RELEASE_KEY="${RELEASE_KEY:-}"
RELEASE_PUBLISHER="${RELEASE_PUBLISHER:-processcraft}"
PYTHON="${PYTHON:-python3}"
ARCH="${ARCH:-$(docker info --format '{{.Architecture}}' 2>/dev/null || uname -m)}"
case "$ARCH" in
    x86_64 | amd64) ARCH=amd64 ;;
    aarch64 | arm64) ARCH=arm64 ;;
    *) printf '[bundle] ERROR: unsupported architecture %s (amd64 or arm64)\n' "$ARCH" >&2; exit 1 ;;
esac
CYCLONEDX_NPM="@cyclonedx/cyclonedx-npm@6.0.1"

NAME="plantcraft-$VERSION-linux-$ARCH-bundle"
DIST="$ROOT/dist"
OUT="$DIST/$NAME"

log() { printf '[bundle] %s\n' "$*"; }
die() {
    printf '[bundle] ERROR: %s\n' "$*" >&2
    exit 1
}

images=("processcraft:$VERSION" "processcraft-proxy:$VERSION" "processcraft-installer:$VERSION")
for image in "${images[@]}"; do
    docker image inspect "$image" >/dev/null 2>&1 || die "image $image not found: run make image"
done
# HistCraft's database, the image compose.yaml names (service histcraft-db).
HISTCRAFT_DB_IMAGE="$(sed -n 's/^ *image: \${HISTCRAFT_DB_IMAGE:-\(postgres:[^ ]*@sha256:[0-9a-f]\{64\}\)}$/\1/p' "$ROOT/deploy/compose.yaml")"
[ -n "$HISTCRAFT_DB_IMAGE" ] || die "compose.yaml names no histcraft-db image pinned by digest"
# HistCraft's gateway (service histcraft-gateway): Telegraf, pinned the same way.
HISTCRAFT_GATEWAY_IMAGE="$(sed -n 's/^ *image: \${HISTCRAFT_GATEWAY_IMAGE:-\(telegraf:[^ ]*@sha256:[0-9a-f]\{64\}\)}$/\1/p' "$ROOT/deploy/compose.yaml")"
[ -n "$HISTCRAFT_GATEWAY_IMAGE" ] || die "compose.yaml names no histcraft-gateway image pinned by digest"
declare -A bundled=()
for app in "${APPS[@]}"; do
    key="$(printf '%s' "$app" | tr '[:lower:]' '[:upper:]')_VERSION"
    version="${!key}"
    if ! docker image inspect "$app:$version" >/dev/null 2>&1; then
        log "$app:$version not found: the bundle ships without it (profile $app stays off)"
        continue
    fi
    if [ "$app" = histcraft ] && ! docker image inspect "$HISTCRAFT_DB_IMAGE" >/dev/null 2>&1; then
        # The app image is here, so HistCraft was meant to ship: a bundle without it is not a release.
        die "$HISTCRAFT_DB_IMAGE not found (docker pull it): HistCraft cannot ship without its database"
    fi
    if [ "$app" = histcraft ] && ! docker image inspect "$HISTCRAFT_GATEWAY_IMAGE" >/dev/null 2>&1; then
        die "$HISTCRAFT_GATEWAY_IMAGE not found (docker pull it): HistCraft cannot ship without its gateway"
    fi
    if [ "$app" = modelcraft ] && ! docker image inspect "modelcraft-runner:$version" >/dev/null 2>&1; then
        die "modelcraft-runner:$version not found (make runner-image in modelcraft): PlantCraft Models cannot ship without it"
    fi
    images+=("$app:$version")
    [ "$app" = modelcraft ] && images+=("modelcraft-runner:$version")
    bundled[$app]="$version"
done
if [ -n "${bundled[histcraft]:-}" ]; then
    # Saved under its tag; docker load restores the same index digest compose.yaml asks for.
    docker tag "$HISTCRAFT_DB_IMAGE" "${HISTCRAFT_DB_IMAGE%@*}"
    images+=("${HISTCRAFT_DB_IMAGE%@*}")
    docker tag "$HISTCRAFT_GATEWAY_IMAGE" "${HISTCRAFT_GATEWAY_IMAGE%@*}"
    images+=("${HISTCRAFT_GATEWAY_IMAGE%@*}")
fi
bundle_plant=""
if docker image inspect "simcraft:$SIMCRAFT_VERSION" >/dev/null 2>&1; then
    images+=("simcraft:$SIMCRAFT_VERSION")
    bundle_plant="$SIMCRAFT_VERSION"
else
    log "simcraft:$SIMCRAFT_VERSION not found: the bundle ships without the Simulator (install.sh --demo is refused)"
fi

# Each image must have its ARCH build here. With Docker's containerd image store a pulled image
# such as PostgreSQL is a multi-platform index (pull its ARCH part once: docker pull --platform
# linux/<arch> <image>) and docker save takes only that platform; the classic store keeps one
# platform per tag.
PLATFORM_FLAG=(--platform "linux/$ARCH")
docker image inspect "${PLATFORM_FLAG[@]}" --format '{{.Architecture}}' "${images[0]}" >/dev/null 2>&1 ||
    PLATFORM_FLAG=() # a Docker without --platform on inspect and save (before 28)
for image in "${images[@]}"; do
    found="$(docker image inspect "${PLATFORM_FLAG[@]}" --format '{{.Architecture}}' "$image" 2>/dev/null || true)"
    [ "$found" = "$ARCH" ] ||
        die "$image has no linux/$ARCH build here (${found:-other platforms only}): build it with --platform linux/$ARCH, or docker pull --platform linux/$ARCH it"
done

log "Writing $OUT (linux/$ARCH)"
rm -rf "$OUT" "$DIST/$NAME.tar.gz" "$DIST/$NAME.tar.gz.sha256" "$DIST/$NAME.tar.gz.sha256.sig"
mkdir -p "$OUT/certs" "$OUT/docs" "$OUT/sbom" "$OUT/trusted-publishers"
cp "$ROOT/deploy/compose.yaml" "$ROOT/deploy/compose-worker.yaml" "$ROOT/deploy/install.sh" "$ROOT/deploy/firewall.sh" "$ROOT/deploy/security-check.sh" "$OUT/"
cp "$ROOT/deploy/certs/README.md" "$OUT/certs/"
cp "$ROOT/LICENSE" "$ROOT/NOTICE" "$OUT/"
cp "$ROOT/docs/install-offline.md" "$ROOT/docs/security-guide.md" "$ROOT/docs/app-package.md" "$OUT/docs/"
cp "$ROOT/deploy/trusted-publishers/README.md" "$OUT/trusted-publishers/"
# Release publisher keys only; a development key (dev-*.pub) never ships.
find "$ROOT/deploy/trusted-publishers" -maxdepth 1 \( -name '*.pub' -o -name '*.allowed_signers' \) \
    ! -name 'dev*' -exec cp {} "$OUT/trusted-publishers/" \;
sed -e "s/^PLANTCRAFT_VERSION=.*/PLANTCRAFT_VERSION=$VERSION/" \
    -e "s/^LINKCRAFT_VERSION=.*/LINKCRAFT_VERSION=$LINKCRAFT_VERSION/" \
    -e "s/^DASHCRAFT_VERSION=.*/DASHCRAFT_VERSION=$DASHCRAFT_VERSION/" \
    -e "s/^HISTCRAFT_VERSION=.*/HISTCRAFT_VERSION=$HISTCRAFT_VERSION/" \
    -e "s/^ALARMCRAFT_VERSION=.*/ALARMCRAFT_VERSION=$ALARMCRAFT_VERSION/" \
    -e "s/^MODELCRAFT_VERSION=.*/MODELCRAFT_VERSION=$MODELCRAFT_VERSION/" \
    -e "s/^SIMCRAFT_VERSION=.*/SIMCRAFT_VERSION=$SIMCRAFT_VERSION/" \
    "$ROOT/deploy/.env.example" >"$OUT/.env.example"
{
    echo "# Written by deploy/bundle.sh; read by install.sh. An empty version: not in this bundle."
    echo "PLANTCRAFT_VERSION=$VERSION"
    echo "ARCH=$ARCH"
    for app in "${APPS[@]}"; do
        echo "$(printf '%s' "$app" | tr '[:lower:]' '[:upper:]')_VERSION=${bundled[$app]:-}"
    done
    echo "HISTCRAFT_DB_IMAGE=$([ -n "${bundled[histcraft]:-}" ] && printf '%s' "$HISTCRAFT_DB_IMAGE")"
    echo "HISTCRAFT_GATEWAY_IMAGE=$([ -n "${bundled[histcraft]:-}" ] && printf '%s' "$HISTCRAFT_GATEWAY_IMAGE")"
    echo "SIMCRAFT_VERSION=$bundle_plant"
    echo "UPGRADE_FROM=$UPGRADE_FROM"
    echo "REVISION=$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
    echo "CREATED=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "IMAGES=${images[*]}"
    for image in "${images[@]}"; do
        echo "# $image $(docker image inspect --format '{{.Id}}' "$image")"
    done
} >"$OUT/bundle.env"
chmod 0755 "$OUT/install.sh" "$OUT/firewall.sh" "$OUT/security-check.sh"
if [ -n "$bundle_plant" ]; then
    # The demo's plant map: the Simulator source, its 50 loops and their loop types.
    mkdir -p "$OUT/demo"
    cp "$ROOT/deploy/demo/plantcraft-50-loops-map.json" "$OUT/demo/"
fi

log "Saving images: ${images[*]}"
docker save "${PLATFORM_FLAG[@]}" -o "$OUT/images.tar" "${images[@]}"
# docker save of one platform of a multi-platform index stores that platform's manifest, so the
# loaded image answers to the manifest digest, not to the index digest of compose.yaml.
saved_digest() { # saved_digest KEY IMAGE LABEL: point bundle.env's KEY at the digest saved
    local saved
    saved="$(tar -xOf "$OUT/images.tar" index.json | "$PYTHON" -c '
import json, sys
name = "docker.io/library/" + sys.argv[1]
for entry in json.load(sys.stdin).get("manifests", []):
    if entry.get("annotations", {}).get("io.containerd.image.name") == name:
        print(entry["digest"])
        break
' "${2%@*}" 2>/dev/null || true)"
    if [ -n "$saved" ] && [ "$saved" != "${2#*@}" ]; then
        log "$3: saved as ${2%@*}@$saved (linux/$ARCH of ${2#*@})"
        sed -i "s|^$1=.*|$1=${2%@*}@$saved|" "$OUT/bundle.env"
    fi
}
if [ -n "${bundled[histcraft]:-}" ]; then
    saved_digest HISTCRAFT_DB_IMAGE "$HISTCRAFT_DB_IMAGE" "HistCraft database"
    saved_digest HISTCRAFT_GATEWAY_IMAGE "$HISTCRAFT_GATEWAY_IMAGE" "HistCraft gateway"
fi

# CycloneDX SBOMs. Missing tools are reported, not fatal: CI generates the SBOMs with pinned
# tool versions (.github/workflows/ci.yml, job "isolation").
if command -v cyclonedx-py >/dev/null 2>&1; then
    log "SBOM: Python dependencies of the image (deploy/requirements.lock)"
    cyclonedx-py requirements --pyproject "$ROOT/pyproject.toml" --output-reproducible \
        --of JSON -o "$OUT/sbom/processcraft-python.cdx.json" "$ROOT/deploy/requirements.lock"
else
    log "WARNING: cyclonedx-py not installed (pip install cyclonedx-bom): no Python SBOM in this bundle"
fi
if command -v npm >/dev/null 2>&1 && [ -d "$ROOT/frontend/node_modules" ]; then
    log "SBOM: web interface (frontend/package-lock.json, production dependencies)"
    (cd "$ROOT/frontend" && npm exec --yes -- "$CYCLONEDX_NPM" --omit dev --output-reproducible \
        --output-format JSON --output-file "$OUT/sbom/processcraft-frontend.cdx.json") ||
        log "WARNING: the frontend SBOM failed; the bundle ships without it"
else
    log "WARNING: npm or frontend/node_modules missing: no frontend SBOM in this bundle"
fi

# An app image that carries its own SBOM (/app/sbom.json) ships it as sbom/<id>.json, and its
# CHANGELOG.md (/app/CHANGELOG.md) gives its part of the release notes.
CHANGELOGS="$(mktemp -d)"
trap 'rm -rf "$CHANGELOGS"' EXIT
changelog_args=(--changelog "processcraft=$ROOT/CHANGELOG.md")
if [ -n "$bundle_plant" ]; then bundled[simcraft]="$bundle_plant"; fi
for app in "${!bundled[@]}"; do
    container="$(docker create --pull never "$app:${bundled[$app]}")"
    if [ "$app" != simcraft ]; then
        if docker cp "$container:/app/sbom.json" "$OUT/sbom/$app.json" >/dev/null 2>&1; then
            log "SBOM: $app (/app/sbom.json of its image)"
        else
            log "$app:${bundled[$app]} carries no /app/sbom.json: no $app SBOM in this bundle"
        fi
        # Its [permissions], pinned in the signed release.json: PlantCraft holds the app's token
        # to them, whatever the app declares when it starts (plantcraft.apps.scopes).
        docker cp "$container:/app/app.toml" "$CHANGELOGS/$app.toml" >/dev/null 2>&1 ||
            die "$app:${bundled[$app]} carries no /app/app.toml: its permissions cannot be pinned"
        changelog_args+=(--manifest "$app=$CHANGELOGS/$app.toml")
    fi
    if docker cp "$container:/app/CHANGELOG.md" "$CHANGELOGS/$app.md" >/dev/null 2>&1; then
        changelog_args+=(--changelog "$app=$CHANGELOGS/$app.md")
    fi
    docker rm "$container" >/dev/null
done

# Notebooks kits (optional, about 180 MB each; notebooks/kit/build_kit.py): the same three in
# every architecture's bundle, since they run on people's computers, not on this server.
NOTEBOOK_KITS="${NOTEBOOK_KITS:-$ROOT/notebooks/kit/dist}"
if [ "$NOTEBOOK_KITS" != none ] && [ -f "$NOTEBOOK_KITS/kits.json" ]; then
    log "Adding the Notebooks kits from $NOTEBOOK_KITS"
    mkdir -p "$OUT/notebook-kits"
    cp "$NOTEBOOK_KITS/kits.json" "$NOTEBOOK_KITS"/*.zip "$OUT/notebook-kits/"
    # The Windows setup, when the machine that built the kits had makensis.
    cp "$NOTEBOOK_KITS"/*.exe "$OUT/notebook-kits/" 2>/dev/null || true
else
    log "No Notebooks kits (make notebook-kits builds them): Run on your computer offers the package only"
fi

log "Writing release.json and RELEASE-NOTES.md"
PYTHONPATH="$ROOT" "$PYTHON" -m plantcraft.apps.release make "$OUT" \
    --upgrade-from "$UPGRADE_FROM" "${changelog_args[@]}"

log "Writing SHA256SUMS"
sums="$(cd "$OUT" && find . -type f -printf '%P\n' | LC_ALL=C sort | xargs sha256sum)"
printf '%s\n' "$sums" >"$OUT/SHA256SUMS"
if [ -n "$RELEASE_KEY" ]; then
    log "Signing SHA256SUMS as $RELEASE_PUBLISHER"
    PYTHONPATH="$ROOT" "$PYTHON" -m plantcraft.apps.release sign "$OUT" \
        --key "$RELEASE_KEY" --publisher "$RELEASE_PUBLISHER"
else
    log "WARNING: RELEASE_KEY not set: the bundle is not signed (installations that trust a publisher refuse it without --allow-unsigned)"
fi

log "Packing $NAME.tar.gz"
tar -C "$DIST" -czf "$DIST/$NAME.tar.gz" "$NAME"
(cd "$DIST" && sha256sum "$NAME.tar.gz" >"$NAME.tar.gz.sha256")
if [ -n "$RELEASE_KEY" ]; then
    PYTHONPATH="$ROOT" "$PYTHON" -m plantcraft.apps.release sign-file "$DIST/$NAME.tar.gz.sha256" \
        --key "$RELEASE_KEY"
fi
log "Done: $DIST/$NAME.tar.gz ($(du -h "$DIST/$NAME.tar.gz" | cut -f1))"
log "Publish this hash with the release so the client can check the download:"
cat "$DIST/$NAME.tar.gz.sha256"
